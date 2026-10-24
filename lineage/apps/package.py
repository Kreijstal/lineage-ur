#!/usr/bin/env python3
"""Export leaf Android apps from a completed reference build as hash-pinned packages."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET

ANDROID = "{http://schemas.android.com/apk/res/android}"
# Build environment that changes Java/dex/resource outputs without changing
# product variables. A different value at selection time keeps the source app.
ENVIRONMENT_KEYS = ("ALTERNATE_JAVAC", "ANDROID_JAVA_HOME", "ANDROID_JAVA8_HOME", "EMMA_INSTRUMENT",
                    "EMMA_INSTRUMENT_FRAMEWORK", "EMMA_INSTRUMENT_STATIC", "GENERATE_DEX_DEBUG",
                    "NO_OPTIMIZE_DX", "R8_DUMP_DIRECTORY", "RUN_ERROR_PRONE", "RUN_ERROR_PRONE_INLINE",
                    "SOONG_PARTIAL_COMPILE", "TURBINE_ENABLED", "USE_D8_DESUGAR", "ALWAYS_EMBED_NOTICES")
PARTITIONS = {"system": None, "product": "product_specific", "system_ext": "system_ext_specific"}


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"})


def make_entries(makefile, module):
    """Resolved Make variables Soong exported for one installed android_app."""
    for block in makefile.split("include $(CLEAR_VARS)"):
        values = dict(re.findall(r"^(LOCAL_[A-Z0-9_]+) := ?(.*)$", block, re.M))
        if values.get("LOCAL_MODULE") == module and values.get("LOCAL_SOONG_MODULE_TYPE") == "android_app":
            return values
    raise ValueError(f"{module}: no android_app entry in the reference Make export")


def adapter(record):
    """The generated Soong adapter; apply.py rebuilds it from the inventory record."""
    lines = ["// Generated packaged app; the source android_app remains the fallback.",
             "android_packaged_app {",
             f'    name: {json.dumps(record["module"])},',
             f'    apk: "snapshots/{record["manifest_sha256"]}/{record["apk"]}",',
             f'    package_manifest: "snapshots/{record["manifest_sha256"]}/package.json",',
             f'    package_sha256: "{record["manifest_sha256"]}",',
             "    default_dev_cert: true,"]
    if record["partition_property"]:
        lines.append(f'    {record["partition_property"]}: true,')
    for name in ("overrides", "required", "auto_generated_rros", "uses_libs", "optional_uses_libs"):
        if record[name]:
            lines.append(f"    {name}: {json.dumps(record[name])},")
    lines.append("}")
    return "\n".join(lines) + "\n"


def license_files(source, repo_rel, path_rel, tracked):
    """License texts to ship with an APK built from this repository."""
    names = [name for name in tracked
             if re.fullmatch(r"(LICENSE|COPYING|NOTICE)[^/]*|LICENSES/[^/]+", name)]
    if names:
        return [source / repo_rel / name for name in names]
    # AOSP apps name a shared license module, e.g. Android-Apache-2.0, instead.
    blueprint = (source / path_rel / "Android.bp").read_text()
    package = re.search(r"default_applicable_licenses:\s*\[([^\]]*)\]", blueprint)
    licenses = re.findall(r'"([^"]+)"', package.group(1)) if package else []
    common = (source / "build/soong/licenses/Android.bp").read_text()
    files = []
    for name in licenses:
        module = re.search(r'name: "' + re.escape(name) + r'",(.*?)\n}', common, re.S)
        texts = re.search(r"license_text:\s*\[([^\]]*)\]", module.group(1)) if module else None
        if not texts:
            raise ValueError(f"{path_rel}: cannot resolve license text for {name}")
        files += [source / "build/soong/licenses" / text for text in re.findall(r'"([^"]+)"', texts.group(1))]
    if not files:
        raise ValueError(f"{path_rel}: no license files found")
    return files


def apk_inputs(source, reference, product, apk):
    """Every checked-in file the unsigned APK was built from, via Ninja's read-only inputs tool.

    This covers the app, its static libraries, SDK stubs and the host tools built
    from source (aapt2, R8 wrappers, ...). Intermediate outputs are not inputs.
    """
    raw = subprocess.check_output([str(source / "prebuilts/build-tools/linux-x86/bin/ninja"),
                                   "-f", str(reference / ("combined-" + product + ".ninja")), "-t", "inputs",
                                   str(apk.relative_to(source))], cwd=source, text=True)
    sources = set()
    for line in raw.splitlines():
        name = shlex.split(line)[0]
        path = source / name
        if Path(name).is_absolute() or ".." in Path(name).parts:
            raise ValueError("APK input outside checkout: " + name)
        if path.is_relative_to(reference):
            continue
        if not path.is_file():
            raise ValueError("missing recorded APK input: " + name)
        sources.add(path)
    return sources


def uses_libraries(manifest):
    """<uses-library> entries in manifest order, split as android_app_import expects them."""
    required, optional = [], []
    application = ET.parse(manifest).getroot().find("application")
    for entry in [] if application is None else application.findall("uses-library"):
        name = entry.get(ANDROID + "name")
        (optional if entry.get(ANDROID + "required") == "false" else required).append(name)
    return required, optional


def build(args):
    source, reference, output = (p.resolve() for p in (args.source_root, args.reference_out, args.output))
    if output.exists() or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("use a new package directory outside Android")
    if not reference.is_relative_to(source) or not re.fullmatch(r"[a-zA-Z0-9_]+", args.product):
        raise ValueError("invalid reference output/product")
    if not re.fullmatch(r"[0-9a-f]{64}", args.context):
        raise ValueError("context must be generated with the Soong target_package_context helper")
    state = json.loads(args.build_state.read_text())
    if (state.get("status") != "complete" or Path(state.get("source_root", "")).resolve() != source
            or args.product != "lineage_" + state.get("device", "")):
        raise ValueError("completed reference build for this checkout/product required")
    pinned = ET.parse(args.reference_manifest).getroot()
    recipes = json.loads(args.recipes.read_text())["apps"]
    if args.module:
        selected = set(args.module)
        recipes = [r for r in recipes if r["module"] in selected]
        if selected != {r["module"] for r in recipes}:
            raise ValueError("unknown app requested")
    variables = reference / "soong" / ("soong." + args.product + ".variables")
    profile = json.loads(variables.read_text())
    if profile.get("DefaultAppCertificate"):
        raise ValueError("custom default app certificates are not supported yet")
    default_certificate = "build/make/target/product/security/testkey.x509.pem"
    used_env = reference / "soong" / ("soong.environment.used." + args.product + ".build")
    original_env = {row["Key"]: row["Value"] for row in json.loads(used_env.read_text())}
    environment = {key: original_env.get(key, "") for key in ENVIRONMENT_KEYS}
    # `m --build-from-source-stub` reaches soong_build as a flag, not through the environment.
    from_text_stub = (not args.build_from_source_stub and not any(environment[key] == "true" for key in
                      ("EMMA_INSTRUMENT", "EMMA_INSTRUMENT_FRAMEWORK", "EMMA_INSTRUMENT_STATIC"))
                      and not profile.get("BuildFromSourceStub"))
    makefile = (reference / "soong" / ("Android-" + args.product + ".mk")).read_text()
    before = {p: sha(p) for p in (args.build_state, args.reference_manifest, variables)}
    digests = {}

    def input_sha(path):
        relative = path.relative_to(source).as_posix()
        if relative not in digests:
            digests[relative] = sha(path)
        return digests[relative]

    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix=".apps-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        for recipe in recipes:
            module, repo_rel = recipe["module"], recipe["repository"]
            repo = source / repo_rel
            revision = git(repo, "rev-parse", "HEAD").strip()
            project = pinned.find("./project[@path='" + repo_rel + "']")
            if (revision != recipe["revision"] or project is None or project.get("revision") != revision
                    or git(repo, "status", "--porcelain")):
                raise ValueError(f"{module}: clean, reviewed, manifest-pinned sources required")
            entry = make_entries(makefile, module)
            if entry.get("LOCAL_PATH", recipe["path"]) != recipe["path"]:
                raise ValueError(f"{module}: module directory differs from the recipe")
            installed = entry["LOCAL_SOONG_INSTALLED_MODULE"]
            partition = installed.split("/")[4]
            # Only plain leaf apps for now: platform/shared keys, priv-app allowlists
            # and separately installed JNI libraries need their own handling.
            if (entry.get("LOCAL_CERTIFICATE") != default_certificate or entry.get("LOCAL_PRIVILEGED_MODULE")
                    or partition not in PARTITIONS or installed != "/".join(installed.split("/")[:5]) + f"/app/{module}/{module}.apk"
                    or any(":" in name for name in entry.get("LOCAL_REQUIRED_MODULES", "").split())
                    or not entry.get("LOCAL_SOONG_DEXPREOPT_CONFIG") and not entry.get("LOCAL_SOONG_BUILT_INSTALLED")):
                raise ValueError(f"{module}: not a default-signed, non-privileged leaf app with code")
            intermediate = source / Path(entry["LOCAL_PREBUILT_MODULE_FILE"]).parent
            unsigned = intermediate / (module + "-unsigned.apk")
            invocation = next((intermediate / "dexpreopt").glob("*/oat/*/package.invocation"))
            context = re.search(r"--class-loader-context=(\S+)", invocation.read_text())
            uses_libs, optional_uses_libs = uses_libraries(source / entry["LOCAL_FULL_MANIFEST_FILE"])
            # The import rebuilds the class loader context from these lists, skipping
            # optional libraries the build does not provide, as the source app did.
            # It must name the same libraries, in the same order.
            context_libs = re.findall(r"/([^/\]#]+)\.jar\]", context.group(1) if context else "")
            declared = [name for name in uses_libs + optional_uses_libs if name in context_libs]
            if declared != context_libs or not set(uses_libs) <= set(context_libs):
                raise ValueError(f"{module}: class loader context {context_libs} differs from its manifest")
            package = stage / "packages" / module
            package.mkdir(parents=True)
            apk_name = module + ".apk"
            before[unsigned] = sha(unsigned)
            shutil.copy2(unsigned, package / apk_name)
            # Auto-generated RROs read this merged manifest through `{.manifest.xml}`.
            merged = source / entry["LOCAL_FULL_MANIFEST_FILE"]
            before[merged] = sha(merged)
            shutil.copy2(merged, package / "AndroidManifest.xml")
            tracked = git(repo, "ls-files").splitlines()
            for path in license_files(source, repo_rel, recipe["path"], tracked):
                destination = package / "licenses" / path.relative_to(source).as_posix().replace("/", "__")
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(path, destination)
            (package / "reference").mkdir()
            for name, path in (("soong.variables.json", variables), ("manifest.xml", args.reference_manifest),
                               ("build-state.json", args.build_state)):
                shutil.copy2(path, package / "reference" / name)
            print(f"{module}: collecting APK inputs", flush=True)
            inputs = {}
            # Build definitions are graph inputs, not Ninja inputs: guard the whole repository.
            for name in tracked:
                path = repo / name
                if path.is_file() and not path.is_symlink():
                    inputs[(Path(repo_rel) / name).as_posix()] = input_sha(path)
            for path in sorted(apk_inputs(source, reference, args.product, unsigned)):
                inputs[path.relative_to(source).as_posix()] = input_sha(path)
            # Soong cannot represent paths containing `$`; apply.py still checks them.
            installer_inputs = {name: inputs.pop(name) for name in sorted(inputs) if "$" in name}
            manifest = {"schema_version": 1, "module": module, "context": args.context, "apk": apk_name,
                        "environment": environment, "build_from_text_stub": from_text_stub,
                        "app_manifest": "AndroidManifest.xml",
                        "source_repository": repo_rel, "source_revision": revision,
                        "reference_apk": entry["LOCAL_PREBUILT_MODULE_FILE"],
                        "files": {p.relative_to(package).as_posix(): sha(p)
                                  for p in sorted(package.rglob("*")) if p.is_file()},
                        "inputs": inputs, "installer_checked_inputs": installer_inputs}
            manifest_path = package / "package.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            checksum = sha(manifest_path)
            # Soong creates these RROs from the source app and they depend on it, so
            # the package requires them from Make only, as the source app does.
            required = entry.get("LOCAL_REQUIRED_MODULES", "").split()
            rros = [name for name in required if re.fullmatch(
                re.escape(module) + "__" + re.escape(args.product) + "__auto_generated_rro_(vendor|product)", name)]
            record = {"module": module, "path": recipe["path"], "repository": repo_rel, "manifest_sha256": checksum,
                      "apk": apk_name, "partition_property": PARTITIONS[partition],
                      "overrides": entry.get("LOCAL_OVERRIDES_PACKAGES", "").split(),
                      "required": [name for name in required if name not in rros],
                      "auto_generated_rros": rros,
                      "uses_libs": uses_libs, "optional_uses_libs": optional_uses_libs,
                      "installed": installed, "source_inputs": len(inputs) + len(installer_inputs),
                      "installer_checked_inputs": len(installer_inputs), "apk_bytes": unsigned.stat().st_size}
            destination = stage / "overlay" / recipe["path"] / "lineage-ur-app"
            shutil.copytree(package, destination / "snapshots" / checksum)
            (destination / "Android.bp").write_text(adapter(record))
            records.append(record)
            print(f"{module}: {len(inputs)} guarded source inputs, {record['apk_bytes']} byte APK", flush=True)
        if any(sha(path) != expected for path, expected in before.items()):
            raise ValueError("reference inputs changed during export")
        (stage / "inventory.json").write_text(json.dumps({"context": args.context, "product": args.product,
                                                         "apps": records}, indent=2) + "\n")
        os.rename(stage, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "reference-out", "build-state", "reference-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--recipes", type=Path, default=Path(__file__).with_name("recipes.json"))
    parser.add_argument("--module", action="append", help="export only selected apps; repeatable")
    parser.add_argument("--build-from-source-stub", action="store_true",
                        help="the reference build ran `m --build-from-source-stub`")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, subprocess.SubprocessError, StopIteration) as error:
        parser.exit(2, f"app package error: {error!r}\n")


if __name__ == "__main__":
    main()
