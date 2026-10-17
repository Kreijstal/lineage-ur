#!/usr/bin/env python3
"""Export Android compilation objects and prepare an opt-in source overlay."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import shlex
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"})


def inject_default(text, module):
    """Insert one defaults reference into the original library, preserving it."""
    # Pinned recipes have four-space property indentation. Locate the module
    # using its name; nested arch properties have deeper indentation.
    match = re.search(r'(?m)^    name: "' + re.escape(module) + r'",[ \t]*$', text)
    if not match:
        raise ValueError("cannot locate pinned source module " + module)
    end = text.index("\n}", match.end())
    body = text[match.end():end]
    name = "lineage_ur_target_" + module
    if re.search(r"(?m)^    defaults:\s*\[", body):
        body = re.sub(r"(?m)^(    defaults:\s*\[)", lambda m: m[1] + json.dumps(name) + ", ", body, count=1)
    else:
        body = "\n    defaults: [" + json.dumps(name) + "]," + body
    return text[:match.end()] + body + text[end:]


def adapter(module, checksum):
    return ('// Generated target object package; source module owns linking and installation.\n'
            'cc_defaults {\n    name: "lineage_ur_target_' + module + '",\n'
            '    target_package: {\n        manifest: "lineage-ur-target/snapshots/' + checksum + '/package.json",\n'
            '        sha256: "' + checksum + '",\n    },\n}\n')


def compilation_inputs(source, reference, product, objects):
    """Use Ninja's read-only tools to recover headers and generator source inputs.

    `inputs` traverses generation edges, including protoc and its inputs;
    `deps` adds the actual preprocessor dependencies from the completed build.
    Output files are retained as provenance, not treated as checkout sources.
    """
    command = [str(source / "prebuilts/build-tools/linux-x86/bin/ninja"),
               "-f", str(reference / ("combined-" + product + ".ninja")), "-t"]
    paths = set()
    # Bound argv size, including kernels with a small ARG_MAX.
    for offset in range(0, len(objects), 1000):
        batch = [str(p.relative_to(source)) for p in objects[offset:offset + 1000]]
        for tool in ("inputs", "deps"):
            raw = subprocess.check_output(command + [tool, *batch], cwd=source, text=True)
            if tool == "inputs":
                paths.update(shlex.split(line)[0] for line in raw.splitlines() if line)
            else:
                if "(STALE)" in raw or "deps not found" in raw:
                    raise ValueError("reference compiler dependencies are missing or stale")
                paths.update(line[4:] for line in raw.splitlines() if line.startswith("    "))
    sources, generated = set(), set()
    for name in paths:
        path = source / name
        if not path.is_file():
            raise ValueError("missing recorded compilation input: " + name)
        if path.is_relative_to(reference):
            generated.add(path)
        elif path.is_relative_to(source) and not Path(name).is_absolute() and ".." not in Path(name).parts:
            sources.add(path)
        else:
            raise ValueError("compilation input outside checkout: " + name)
    return sources, generated


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
    recipes = json.loads(args.recipes.read_text())["libraries"]
    if args.module:
        selected = set(args.module)
        recipes = [r for r in recipes if r["module"] in selected]
        if selected != {r["module"] for r in recipes}:
            raise ValueError("unknown target module requested")
    # Multiple packages may modify one component. Every manifest must hash the
    # final combined definition, not an intermediate one-module overlay.
    original_bps, patched_bps = {}, {}
    for recipe in recipes:
        repo = recipe["repository"]
        if repo not in original_bps:
            original_bps[repo] = (source / repo / "Android.bp").read_text()
            patched_bps[repo] = original_bps[repo]
        patched_bps[repo] = inject_default(patched_bps[repo], recipe["module"])
    digests = {}
    def input_sha(path):
        relative = path.relative_to(source).as_posix()
        if relative not in digests:
            repo = str(Path(relative).parent)
            digests[relative] = (hashlib.sha256(patched_bps[repo].encode()).hexdigest()
                                 if path.name == "Android.bp" and repo in patched_bps else sha(path))
        return digests[relative]
    variables = reference / "soong" / ("soong." + args.product + ".variables")
    profile = json.loads(variables.read_text())
    if profile.get("DeviceName") != state["device"] or profile.get("DeviceArch") != "arm64":
        raise ValueError("reference must be the ARM64 Android target")
    used_env = reference / "soong" / ("soong.environment.used." + args.product + ".build")
    original_env = {row["Key"]: row["Value"] for row in json.loads(used_env.read_text())}
    environment_keys = ("CLANG_PREBUILTS_VERSION", "LLVM_PREBUILTS_VERSION", "CLANG_PREBUILTS_BASE",
                        "LLVM_PREBUILTS_BASE", "OVERRIDE_ANDROID_CLANG_PREBUILTS_VERSION",
                        "THINLTO_USE_MLGO", "THINLTO_EMIT_INDEXES_AND_IMPORTS", "AUTO_PATTERN_INITIALIZE",
                        "DISABLE_SCS", "DISABLE_CFI", "NATIVE_COVERAGE", "CLANG_COVERAGE", "ANDROID_PGO_INSTRUMENT")
    environment = {key: original_env.get(key, "") for key in environment_keys}
    global_inputs = {path.relative_to(source).as_posix(): sha(path)
                     for path in (source / "build/soong/cc/config").glob("*.go")}
    clang_version = profile["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"]
    for name in ("clang", "clang-real", "ld.lld"):
        path = source / "prebuilts/clang/host/linux-x86" / clang_version / "bin" / name
        global_inputs[path.relative_to(source).as_posix()] = sha(path)
    before = {p: sha(p) for p in (args.build_state, args.reference_manifest, variables)}
    output.parent.mkdir(parents=True, exist_ok=True)
    records = []
    with tempfile.TemporaryDirectory(prefix=".target-libraries-", dir=output.parent) as temporary:
        stage = Path(temporary) / "result"
        overlay = stage / "overlay"
        for recipe in recipes:
            module, repo_rel = recipe["module"], recipe["repository"]
            repo = source / repo_rel
            revision = git(repo, "rev-parse", "HEAD").strip()
            project = pinned.find("./project[@path='" + repo_rel + "']")
            if (revision != recipe["revision"] or project is None or project.get("revision") != revision
                    or git(repo, "status", "--porcelain")):
                raise ValueError(f"{module}: clean, reviewed, manifest-pinned sources required")
            original_bp, patched_bp = original_bps[repo_rel], patched_bps[repo_rel]
            package = stage / "packages" / module
            package.mkdir(parents=True)
            inputs = dict(global_inputs)
            for name in git(repo, "ls-files").splitlines():
                path = repo / name
                if path.is_file():
                    inputs[(Path(repo_rel) / name).as_posix()] = input_sha(path)
            # Record global flag definitions too. Current fork additions do not
            # modify these files, so their identities remain baseline inputs.
            variants = []
            all_objects = []
            intermediate = reference / "soong/.intermediates" / repo_rel / module
            for directory in sorted(intermediate.glob("android*_static*")):
                objects = sorted((directory / "obj").rglob("*.o"))
                if not objects:
                    continue
                dumps = sorted((directory / "obj").rglob("*.sdump"))
                row = {"variation": directory.name, "objects": [], "abi_dumps": []}
                for kind, paths in (("objects", objects), ("abi_dumps", dumps)):
                    for path in paths:
                        if kind == "objects":
                            with path.open("rb") as stream:
                                header = stream.read(20)
                            arm64 = "_arm64_" in directory.name
                            if header[:4] == b"\x7fELF":
                                expected = b"\xb7\x00" if arm64 else b"\x28\x00"
                                if header[18:20] != expected:
                                    raise ValueError("object architecture does not match Android variant")
                            elif header[:4] != b"BC\xc0\xde":
                                raise ValueError("unsupported target object format")
                        relative = Path("variants") / directory.name / path.relative_to(directory)
                        destination = package / relative
                        destination.parent.mkdir(parents=True, exist_ok=True)
                        before[path] = sha(path)
                        shutil.copy2(path, destination)
                        row[kind].append(relative.as_posix())
                variants.append(row)
                all_objects.extend(objects)
            if not variants:
                raise ValueError(f"{module}: no compiled Android object variants")
            print(f"{module}: collecting compiler and generator dependencies", flush=True)
            dependencies, generated = compilation_inputs(source, reference, args.product, all_objects)
            for path in sorted(dependencies):
                inputs[path.relative_to(source).as_posix()] = input_sha(path)
            # Generated outputs remain provenance. Their checked-in leaves are
            # guarded above; Soong still owns generation and header exports.
            generated_inputs = {p.relative_to(reference).as_posix(): sha(p) for p in sorted(generated)}
            generated_prefix = recipe.get("generated_header_prefix")
            if generated_prefix:
                marker = "/gen/" + generated_prefix + "/"
                for header in sorted(generated):
                    if marker not in str(header) or header.suffix != ".h":
                        continue
                    relative = str(header).split(marker, 1)[1]
                    destination = package / "include" / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    if destination.exists() and sha(destination) != sha(header):
                        raise ValueError("conflicting generated header: " + relative)
                    shutil.copy2(header, destination)
            for header_pattern in recipe["headers"]:
                pattern = header_pattern if isinstance(header_pattern, str) else header_pattern["pattern"]
                for header in repo.glob(pattern):
                    relative = header.name if isinstance(header_pattern, str) else header.relative_to(repo / header_pattern["strip_prefix"])
                    destination = package / "include" / relative
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(header, destination)
            for name in recipe["licenses"]:
                destination = package / "licenses" / Path(name).name
                destination.parent.mkdir(exist_ok=True)
                shutil.copy2(repo / name, destination)
            (package / "reference").mkdir()
            runtime = dict(recipe["runtime"])
            runtime["support_archives"] = []
            core = next(v["variation"] for v in variants
                        if v["variation"] == "android_arm64_" + profile["DeviceArchVariant"] + "_static"
                        or (v["variation"].startswith("android_arm64_" + profile["DeviceArchVariant"] + "_static_afdo-")
                            and "_apex" not in v["variation"]))
            for relative in runtime.pop("reference_archives", []):
                path = reference / "soong/.intermediates" / relative.format(variant=core)
                destination = package / "support" / path.name
                destination.parent.mkdir(exist_ok=True)
                before[path] = sha(path)
                shutil.copy2(path, destination)
                runtime["support_archives"].append(destination.relative_to(package).as_posix())
            for name, path in (("soong.variables.json", variables), ("manifest.xml", args.reference_manifest), ("build-state.json", args.build_state)):
                shutil.copy2(path, package / "reference" / name)
            manifest = {"schema_version": 1, "module": module, "context": args.context, "environment": environment,
                        "source_repository": repo_rel, "source_revision": revision,
                        "generated_reference_inputs": generated_inputs,
                        "runtime": runtime,
                        "files": {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*")) if p.is_file()},
                        "inputs": inputs, "variants": variants}
            manifest_path = package / "package.json"
            manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")
            checksum = sha(manifest_path)
            snapshot_rel = Path("lineage-ur-target/snapshots") / checksum
            component = overlay / repo_rel
            shutil.copytree(package, component / snapshot_rel)
            (component / "Android.bp").write_text(patched_bp)
            with (component / "lineage-ur-target/Android.bp").open("a") as stream:
                stream.write(adapter(module, checksum))
            record = {"module": module, "repository": repo_rel, "manifest_sha256": checksum,
                      "original_android_bp_sha256": hashlib.sha256(original_bp.encode()).hexdigest(),
                      "variants": len(variants), "objects": sum(len(v["objects"]) for v in variants),
                      "source_inputs": len(inputs), "generated_reference_inputs": len(generated_inputs)}
            records.append(record)
            print(f"{module}: {record['variants']} Android variants, {record['objects']} packaged objects", flush=True)
        if any(sha(path) != expected for path, expected in before.items()):
            raise ValueError("reference inputs changed during export")
        (stage / "inventory.json").write_text(json.dumps({"context": args.context, "product": args.product,
                                                         "libraries": records}, indent=2) + "\n")
        os.rename(stage, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("source-root", "reference-out", "build-state", "reference-manifest", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--context", required=True)
    parser.add_argument("--recipes", type=Path, default=Path(__file__).with_name("recipes.json"))
    parser.add_argument("--module", action="append", help="export only selected modules; repeatable")
    args = parser.parse_args()
    try:
        build(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(2, f"target package error: {error}\n")


if __name__ == "__main__":
    main()
