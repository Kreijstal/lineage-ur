#!/usr/bin/env python3
"""Audit independent Termux binaries against Android consumers and emit opt-in adapters."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import importlib.util
import json
from pathlib import Path
import re
import shutil
import subprocess


RECIPE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("import_termux", RECIPE.parent / "swiftshader/import_termux.py")
importer = importlib.util.module_from_spec(spec)
spec.loader.exec_module(importer)


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def elf(path):
    raw = subprocess.check_output(["readelf", "--dyn-syms", "-dW", str(path)], text=True)
    exports, imports = set(), set()
    for line in raw.splitlines():
        fields = line.split()
        if len(fields) >= 8 and fields[0].endswith(":") and fields[0][:-1].isdigit():
            if fields[4] not in ("GLOBAL", "WEAK"):
                continue
            symbol = fields[7].split("@")[0]
            if fields[6] != "UND":
                exports.add(symbol)
            elif fields[4] == "GLOBAL":
                imports.add(symbol)
    return {"needed": re.findall(r"\(NEEDED\).*?\[(.*?)\]", raw),
            "soname": re.findall(r"\(SONAME\).*?\[(.*?)\]", raw),
            "rpath": re.findall(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]", raw),
            "exports": exports, "imports": imports}


def arm64(path):
    with path.open("rb") as stream:
        header = stream.read(20)
    return header[:6] == b"\x7fELF\x02\x01" and header[18:20] == b"\xb7\x00"


def run_record(command, **kwargs):
    result = subprocess.run(command, text=True, capture_output=True, timeout=60, **kwargs)
    return {"command": command, "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("android-source", "sysroot", "termux", "qemu", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    android, sysroot, termux, qemu, output = [p.resolve() for p in (
        args.android_source, args.sysroot, args.termux, args.qemu, args.output)]
    if output.exists() or any(output.is_relative_to(p) for p in (android, sysroot, termux)):
        parser.error("output must be a new directory outside input trees")
    lock = RECIPE / "termux-aarch64.lock.json"
    recipes = json.loads((RECIPE / "recipes.json").read_text())["libraries"]
    prefix = termux / "root/data/data/com.termux/files/usr"
    inputs = [prefix / "lib" / r["file"] for r in recipes]
    importer.verify_inputs(termux, inputs, lock)
    variables = json.loads((android / "out/soong/soong.lineage_r8q.variables").read_text())
    api = variables["Platform_sdk_version"]
    clang = android / "prebuilts/clang/host/linux-x86" / variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"] / "bin/clang"
    product = android / "out/target/product" / variables["DeviceName"]
    output.mkdir(parents=True)
    candidates = output / "candidates"
    candidates.mkdir()
    rename = {elf(p)["soname"][0]: r["module"] + ".so" for r, p in zip(recipes, inputs)}
    for recipe, original in zip(recipes, inputs):
        target = candidates / (recipe["module"] + ".so")
        shutil.copy2(original, target)
        subprocess.run(["patchelf", "--remove-rpath", "--set-soname", target.name, str(target)], check=True)
        for old, new in rename.items():
            if old in elf(original)["needed"]:
                subprocess.run(["patchelf", "--replace-needed", old, new, str(target)], check=True)
        if elf(target)["rpath"] or not arm64(target):
            raise ValueError("invalid transformed payload")

    # Inspect actual installed ARM64 ELF consumers. This catches missing private
    # exports, but is deliberately not presented as a complete ABI proof.
    paths = sorted({p.resolve() for base in ("system", "system_ext", "vendor", "product", "apex")
                    for p in (product / base).rglob("*") if p.is_file() and arm64(p)})
    def inspect(path):
        return path, elf(path)
    with ThreadPoolExecutor(max_workers=4) as executor:
        consumers = list(executor.map(inspect, paths))
    records = []
    loader = product / "apex/com.android.runtime/bin/linker64"
    loader_path = ":".join(map(str, [candidates, product / "apex/com.android.runtime/lib64/bionic",
                                    product / "system/lib64", *sorted((product / "apex").glob("*/lib64"))]))
    for recipe, original in zip(recipes, inputs):
        name = recipe["module"]
        target = candidates / (name + ".so")
        reference = product / "system/lib64" / target.name
        baseline = elf(reference)["exports"] if reference.is_file() else set()
        missing = baseline - elf(target)["exports"]
        dependents = []
        for path, info in consumers:
            if target.name in info["needed"]:
                dependents.append({"path": path.relative_to(product).as_posix(),
                                   "missing_imports": sorted(info["imports"] & missing)})
        smoke = RECIPE.parent / "host-libraries/smoke" / (recipe["smoke"] + ".c")
        executable = output / (name + "-consumer")
        compile_command = [str(clang), "--target=aarch64-linux-android" + str(api), "--sysroot=" + str(sysroot),
                           "-std=c11", "-Wall", "-Wextra", "-Werror", "-fPIE", "-pie",
                           *["-I" + str(android / recipe["repository"] / p) for p in recipe["include_dirs"]],
                           str(smoke), str(target), "-Wl,-rpath-link," + str(candidates), "-o", str(executable),
                           "-Wl,--dynamic-linker=" + str(loader)]
        build = run_record(compile_command)
        execution = None
        if build["returncode"] == 0:
            execution = run_record([str(qemu), "-cpu", "max", "-E", "LD_LIBRARY_PATH=" + loader_path, str(executable)])
        passed = build["returncode"] == 0 and execution["returncode"] == 0
        eligible = passed and not recipe.get("restriction") and not any(c["missing_imports"] for c in dependents)
        records.append({**recipe, "version": json.loads(lock.read_text())["packages"][recipe["package"]]["Version"],
                        "input_sha256": sha(original), "output_sha256": sha(target),
                        "missing_baseline_exports": sorted(missing), "installed_direct_consumers": dependents,
                        "build": build, "runtime": execution, "consumer_passed": passed,
                        "adapter_eligible": eligible})
        print(name + ": consumer " + ("PASS" if passed else "FAIL") + "; adapter " + ("eligible" if eligible else "withheld"), flush=True)

    adapter = output / "adapter"
    package = adapter / "package"
    libs = package / "lib64"
    libs.mkdir(parents=True)
    selected = [r for r in records if r["adapter_eligible"]]
    selected_names = {r["module"] + ".so" for r in selected}
    for record in selected:
        name = record["module"]
        if set(elf(candidates / (name + ".so"))["needed"]) - selected_names - {"libc.so", "libm.so", "libdl.so"}:
            raise ValueError("dependency closure is not independently reusable: " + name)
        shutil.copy2(candidates / (name + ".so"), libs / (name + ".so"))
        # Preserve the platform-facing headers used by the successful consumer,
        # rather than silently upgrading callers to Termux's newer API surface.
        include = package / "include" / name
        include.mkdir(parents=True)
        header_sources = {}
        for directory in record["include_dirs"]:
            for header in sorted((android / record["repository"] / directory).glob("*.h")):
                if header.name in header_sources:
                    raise ValueError("ambiguous exported header: " + header.name)
                shutil.copy2(header, include / header.name)
                header_sources[header.name] = {"path": header.relative_to(android).as_posix(), "sha256": sha(header)}
        record["platform_headers"] = header_sources
        license_dir = package / "licenses" / record["package"]
        license_dir.mkdir(parents=True)
        docs = prefix / "share/doc" / record["package"]
        licenses = [p for p in docs.glob("*") if p.is_file() and p.name.lower().startswith(("copyright", "license", "copying", "readme.ijg"))]
        if not licenses and record["package"] == "zstd":
            licenses = [RECIPE.parent / "swiftshader/licenses/zstd/LICENSE"]
        if not licenses:
            raise ValueError("missing license: " + record["package"])
        for path in licenses:
            shutil.copy2(path, license_dir / path.name)
    shutil.copy2(lock, package / "termux-packages.json")
    (package / "provenance.json").write_text(json.dumps({
        "origin": "official Termux binary packages; no LineageOS library objects",
        "changes": "SONAME/DT_NEEDED adapted to Android module names; Termux RUNPATH removed",
        "libraries": [{k: r[k] for k in ("module", "package", "version", "input_sha256", "output_sha256", "platform_headers")} for r in selected],
    }, indent=2) + "\n")
    manifest = {"schema_version": 1, "arch": "arm64", "android_api": api, "partition": "vendor",
                "libraries": {r["module"]: "lib64/" + r["module"] + ".so" for r in selected},
                "files": {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*")) if p.is_file()}}
    (package / "package.json").write_text(json.dumps(manifest, indent=2) + "\n")
    checksum = sha(package / "package.json")
    bp = ['package { default_applicable_licenses: ["lineage_ur_termux_c_license"] }',
          'license { name: "lineage_ur_termux_c_license", visibility: [":__subpackages__"],',
          '    license_kinds: ["SPDX-license-identifier-Zlib", "SPDX-license-identifier-BSD", "SPDX-license-identifier-Libpng"],',
          '    license_text: ["package/licenses/**/*"],\n}']
    for record in selected:
        name = record["module"]
        info = elf(libs / (name + ".so"))
        shared = [n.removesuffix(".so") for n in info["needed"] if n not in ("libc.so", "libm.so", "libdl.so")]
        system = [n.removesuffix(".so") for n in info["needed"] if n in ("libc.so", "libm.so", "libdl.so")]
        bp.append('cc_packaged_library_shared_target {\n' + '\n'.join([
            '    name: ' + json.dumps(name) + ',', '    vendor_available: true,', '    compile_multilib: "64",', '    stl: "none",',
            '    srcs: ["package/lib64/' + name + '.so"],',
            '    export_include_dirs: ["package/include/' + name + '"],',
            '    package_manifest: "package/package.json",', '    package_sha256: ' + json.dumps(checksum) + ',',
            '    shared_libs: ' + json.dumps(shared) + ',', '    system_shared_libs: ' + json.dumps(system) + ',',
            '    strip: { none: true },',
        ]) + '\n}')
    (adapter / "Android.bp").write_text('\n\n'.join(bp) + '\n')
    (output / "report.json").write_text(json.dumps({
        "scope": "synthetic ARM64/Bionic consumers compiled with LineageOS headers; installed ELF symbol audit; no ROM boot or full ABI proof",
        "installed_arm64_elfs_scanned": len(paths), "qemu_sha256": sha(qemu),
        "adapter_manifest_sha256": checksum, "libraries": records,
    }, indent=2) + "\n")
    print("Independent Termux adapters: " + ", ".join(r["module"] for r in selected))


if __name__ == "__main__":
    main()
