#!/usr/bin/env python3
"""Relink Android libraries from packages and run Bionic consumers under QEMU."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--reference-out", type=Path)
    parser.add_argument("--module", action="append", help="run only selected consumers; repeatable")
    args = parser.parse_args()
    source, packages, qemu, output = (p.resolve() for p in (args.source_root, args.packages, args.qemu, args.output))
    if output.is_relative_to(source) or output.is_relative_to(packages):
        parser.error("consumer build output must be outside Android")
    output.mkdir(parents=True, exist_ok=True)
    inventory = json.loads((packages / "inventory.json").read_text())
    if args.module and not set(args.module).issubset({r["module"] for r in inventory["libraries"]}):
        parser.error("requested consumer is not in this package inventory")
    first = inventory["libraries"][0]["module"]
    variables = json.loads((packages / "packages" / first / "reference/soong.variables.json").read_text())
    recipes = {r["module"]: r for r in json.loads(Path(__file__).with_name("recipes.json").read_text())["libraries"]}
    version = variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"]
    clang_root = source / "prebuilts/clang/host/linux-x86" / version
    clang, archiver = clang_root / "bin/clang", clang_root / "bin/llvm-ar"
    # The test consumes the built platform sysroot and CRTs, not host glibc.
    reference = args.reference_out.resolve() if args.reference_out else source / "out"
    product = reference / "target/product" / variables["DeviceName"]
    sysroot = reference / "soong/ndk/sysroot"
    arch = "arm64_" + variables["DeviceArchVariant"]
    crt = reference / "soong/.intermediates/bionic/libc"
    def crt_file(module):
        return crt / module / ("android_" + arch) / (module + ".o")
    builtins = next((clang_root / "lib/clang").glob("*/lib/linux/libclang_rt.builtins-aarch64-android.a"))
    ubsan = next((clang_root / "lib/clang").glob("*/lib/linux/libclang_rt.ubsan_minimal-aarch64-android.a"))
    api = str(variables["Platform_sdk_version"])
    common = [str(clang), "--target=aarch64-linux-android" + api, "--sysroot=" + str(sysroot), "-nostdlib", "-flto=thin",
              "-Wl,--thinlto-jobs=2", "-Wl,--gc-sections"]
    runtime = product / "apex/com.android.runtime/lib64/bionic"
    linker = product / "apex/com.android.runtime/bin/linker64"
    library_dir = output / "lib"
    library_dir.mkdir(exist_ok=True)
    runtime_args = ["-L" + str(library_dir), "-L" + str(product / "system/lib64"),
                    "-L" + str(sysroot / "usr/lib/aarch64-linux-android" / api),
                    "-Wl,--no-as-needed", "-lc++", "-lc", "-lm", "-ldl", str(ubsan), str(builtins)]
    manifests = {}
    variants = {}
    libraries = {}
    settings = {}
    for record in inventory["libraries"]:
        name = record["module"]
        package = packages / "packages" / name
        manifest_path = package / "package.json"
        if sha(manifest_path) != record["manifest_sha256"]:
            raise ValueError("manifest checksum mismatch")
        manifest = json.loads(manifest_path.read_text())
        for relative, expected in manifest["files"].items():
            if sha(package / relative) != expected:
                raise ValueError("package content mismatch: " + relative)
        candidates = [v for v in manifest["variants"] if v["variation"].startswith("android_" + arch + "_static")
                      and not any(suffix in v["variation"] for suffix in ("_apex", "_cfi", "_lto-"))]
        if not candidates:
            raise ValueError("no core ARM64 compilation variant for " + name)
        variant = candidates[0]
        manifests[name], variants[name] = manifest, variant["variation"]
        settings[name] = manifest.get("runtime", recipes[name]["runtime"])
        static = settings[name]["linkage"] == "static"
        library = library_dir / (name + (".a" if static else ".so"))
        libraries[name] = library
        objects = [str(package / p) for p in variant["objects"]]
        if static:
            library.unlink(missing_ok=True)
            subprocess.run([str(archiver), "rcsD", str(library), *objects], check=True)
        else:
            dependencies = ["-l" + d.removeprefix("lib") for d in settings[name].get("dependencies", [])]
            subprocess.run([*common, "-shared", "-Wl,--no-undefined", "-Wl,-soname," + name + ".so", str(crt_file("crtbegin_so")),
                            *objects, *dependencies, *runtime_args, str(crt_file("crtend_so")),
                            "-o", str(library)], check=True)
        print(f"{name}: Android library relinked from {len(objects)} packaged objects", flush=True)
    results = []
    for name, manifest in manifests.items():
        if args.module and name not in args.module:
            continue
        package = packages / "packages" / name
        executable = output / (name + "-consumer")
        recipe = settings[name]
        smoke = Path(__file__).parent / recipe["smoke"]
        library = libraries[name]
        dependency_names = recipe.get("dependencies", [])
        dependencies = [str(libraries[n]) for n in dependency_names]
        support = [str(packages / "packages" / n / p) for n in [name, *dependency_names]
                   for p in settings[n].get("support_archives", [])]
        reference_inputs = [reference / "soong/.intermediates" / p
                            for p in recipe.get("reference_link_inputs", [])]
        support.extend(map(str, reference_inputs))
        includes = ["-I" + str(package / "include" / p) for p in recipe.get("include_dirs", [])]
        cxx = smoke.suffix == ".cpp"
        language = ["-std=c++20", "-fno-rtti", "-isystem", str(clang_root / "include/c++/v1"), "-isystem",
                    str(clang_root / "android_libc++/platform/aarch64/include/c++/v1")] if cxx else ["-std=c11"]
        shared = ["-l" + n.removeprefix("lib") for n in recipe.get("shared_dependencies", [])]
        # Keep the test consumer native. Packaged Android bitcode retains its
        # original LTO module flags; a separately compiled SDK consumer must not
        # introduce a conflicting split-LTO policy into those modules.
        command = [*common, *language, "-fno-lto", "-fPIE", "-pie", "-Wall", "-Wextra", "-Werror", "-I", str(package / "include"),
                        *includes, *recipe.get("cflags", []),
                        str(crt_file("crtbegin_dynamic")), str(smoke), str(library), *dependencies, *support, *shared,
                        *runtime_args, str(crt_file("crtend_android")), "-o", str(executable),
                        "-Wl,--dynamic-linker=" + str(linker)]
        (output / (name + "-link-command.json")).write_text(json.dumps(command, indent=2) + "\n")
        subprocess.run(command, check=True)
        loader_path = ":".join(str(p) for p in [library_dir, runtime, product / "system/lib64",
                                                *sorted((product / "apex").glob("*/lib64"))])
        result = subprocess.run([str(qemu), "-cpu", "max", "-E", "LD_LIBRARY_PATH=" + loader_path, str(executable)],
                                capture_output=True, text=True, timeout=30)
        if result.returncode:
            raise RuntimeError(f"{name}: consumer exited {result.returncode}\n{result.stdout}{result.stderr}")
        print(f"{name}: {result.stdout.strip()} (Android/Bionic ARM64 emulation)", flush=True)
        results.append({"module": name, "variant": variants[name], "result": "pass", "stdout": result.stdout.strip(),
                        "executable_sha256": sha(executable), "library_sha256": sha(library),
                        "reference_link_inputs": {p.relative_to(reference).as_posix(): sha(p) for p in reference_inputs}})
    (output / "report.json").write_text(json.dumps({"scope": "synthetic ARM64/Bionic userspace; not hardware verified or a full ROM build",
                                                  "context": inventory["context"], "qemu_sha256": sha(qemu), "tests": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
