#!/usr/bin/env python3
"""Package the Bionic Vulkan HAL and its private Termux LLVM dependency closure."""

import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess
from import_termux import verify_inputs
from build_android import verify_source


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dynamic(path):
    raw = subprocess.check_output(["readelf", "-dW", str(path)], text=True)
    return {"needed": re.findall(r"\(NEEDED\).*?\[(.*?)\]", raw),
            "soname": re.findall(r"\(SONAME\).*?\[(.*?)\]", raw),
            "rpath": re.findall(r"\((?:RUNPATH|RPATH)\).*?\[(.*?)\]", raw)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--termux", type=Path, required=True)
    parser.add_argument("--swiftshader-source", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    build, termux, source, output = [p.resolve() for p in (args.build, args.termux, args.swiftshader_source, args.output)]
    if output.exists() or any(output.is_relative_to(p) for p in (build, termux, source)):
        parser.error("output must be a new directory outside the input trees")
    prefix = termux / "root/data/data/com.termux/files/usr"
    verify_source(source)
    driver = build / "build/vulkan.pastel.so"
    exports = subprocess.check_output(["readelf", "--dyn-syms", "-W", str(driver)], text=True)
    for symbol in ("HMI", "vk_icdGetInstanceProcAddr", "vk_icdNegotiateLoaderICDInterfaceVersion"):
        if not re.search(r"\b" + symbol + r"$", exports, re.M):
            raise ValueError("Android HAL export missing: " + symbol)
    package = output / "package"
    library_dir = package / "lib64"
    (library_dir / "hw").mkdir(parents=True)
    system = {"libc.so", "libm.so", "libdl.so", "liblog.so", "libnativewindow.so", "libhardware.so", "libsync.so"}
    private = {
        "libLLVM.so": "liblineage_ur_llvm21.so", "libc++_shared.so": "liblineage_ur_cxx.so",
        "libffi.so": "liblineage_ur_ffi.so", "libz.so.1": "liblineage_ur_z.so",
        "libzstd.so.1": "liblineage_ur_zstd.so", "libxml2.so.16": "liblineage_ur_xml2.so",
        "libiconv.so": "liblineage_ur_iconv.so",
    }
    pending = [driver]
    copied = {}
    libraries = {}
    provenance = {}
    imported_inputs = []
    while pending:
        original = pending.pop()
        info = dynamic(original)
        if len(info["soname"]) != 1:
            raise ValueError("expected exactly one SONAME: " + str(original))
        soname = info["soname"][0]
        if soname in copied:
            continue
        if original == driver:
            relative = "lib64/hw/vulkan.pastel.so"
            module = "vulkan.pastel"
            target_name = "vulkan.pastel.so"
        else:
            imported_inputs.append(original)
            target_name = private[soname]
            relative = "lib64/" + target_name
            module = target_name.removesuffix(".so")
        target = package / relative
        shutil.copy2(original, target)
        subprocess.run(["patchelf", "--remove-rpath", "--set-soname", target_name, str(target)], check=True)
        for dependency in info["needed"]:
            if dependency in system:
                continue
            if dependency not in private:
                raise ValueError("unmapped runtime dependency: " + dependency)
            imported = prefix / "lib" / dependency
            if not imported.resolve().is_relative_to(prefix) or not imported.is_file():
                raise ValueError("missing or escaping imported dependency: " + dependency)
            pending.append(imported)
            subprocess.run(["patchelf", "--replace-needed", dependency, private[dependency], str(target)], check=True)
        copied[soname] = target
        libraries[module] = relative
        provenance[relative] = {"input_sha256": sha(original), "original_soname": soname, "original_needed": info["needed"], "original_rpath": info["rpath"]}
    verify_inputs(termux, imported_inputs)
    licenses = package / "licenses"
    licenses.mkdir()
    commands = json.loads((build / "commands.json").read_text())
    android = Path(next(flag.removeprefix("-DANDROID_SOURCE=") for flag in commands["configure"] if flag.startswith("-DANDROID_SOURCE=")))
    variables = json.loads((android / "out/soong/soong.lineage_r8q.variables").read_text())
    compiler = android / "prebuilts/clang/host/linux-x86" / variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"]
    (licenses / "android").mkdir()
    shutil.copy2(android / "bionic/libc/NOTICE", licenses / "android/bionic-NOTICE")
    shutil.copy2(compiler / "NOTICE", licenses / "android/compiler-runtime-NOTICE")
    for path in sorted(source.rglob("*")):
        if path.is_file() and path.name.upper().startswith(("LICENSE", "COPYING", "NOTICE")) and ".git" not in path.parts:
            target = licenses / "swiftshader" / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(path, target)
    for name in ("libllvm", "libc++", "libffi", "zlib", "zstd", "libxml2", "libiconv"):
        docs = prefix / "share/doc" / name
        if not docs.is_dir() or not any(p.is_file() for p in docs.rglob("*")):
            docs = Path(__file__).with_name("licenses") / name
        if not docs.is_dir():
            raise ValueError("missing license material: " + name)
        shutil.copytree(docs, licenses / "termux" / name, ignore_dangling_symlinks=True)
    iconv_source = termux / "downloads/libiconv-1.19.tar.gz"
    expected_iconv = "88dd96a8c0464eca144fc791ae60cd31cd8ee78321e67397e25fc095c4a19aa6"
    if sha(iconv_source) != expected_iconv:
        raise ValueError("missing or modified libiconv source archive")
    (package / "sources").mkdir()
    shutil.copy2(iconv_source, package / "sources/libiconv-1.19.tar.gz")
    recipe_lock = Path(__file__).with_name("termux-aarch64.lock.json")
    lock = json.loads(recipe_lock.read_text())
    for name, checksum in lock["supplemental_licenses"].items():
        if sha(Path(__file__).with_name("licenses") / name) != checksum:
            raise ValueError("supplemental license was modified: " + name)
    shutil.copy2(recipe_lock, package / "termux-packages.json")
    source_patch = subprocess.check_output(["git", "-C", str(source), "diff", "--binary"])
    (package / "swiftshader.patch").write_bytes(source_patch)
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    (package / "provenance.json").write_text(json.dumps({
        "upstream": {"repository": "https://swiftshader.googlesource.com/SwiftShader", "revision": revision},
        "scope": "Android/Bionic ARM64 vendor Vulkan HAL; pending full-ROM and hardware/display validation",
        "modifications": "SwiftShader LLVM/Android CMake port; private SONAME/DT_NEEDED renaming and removal of build/Termux RPATHs",
        "libraries": provenance,
        "build_commands": commands,
    }, indent=2) + "\n")
    manifest = {"schema_version": 1, "arch": "arm64", "android_api": 36, "partition": "vendor",
                "libraries": libraries,
                "files": {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*")) if p.is_file()}}
    raw = (json.dumps(manifest, indent=2) + "\n").encode()
    (package / "package.json").write_bytes(raw)
    checksum = hashlib.sha256(raw).hexdigest()
    reverse = {Path(path).name: name for name, path in libraries.items()}
    kinds = ["SPDX-license-identifier-" + name for name in ("Apache-2.0", "BSD", "MIT", "NCSA", "LGPL-2.1+", "GPL-3.0+")]
    bp = ['// Generated opt-in Android/Bionic package. Keep upstream source modules.\n',
          'package { default_applicable_licenses: ["lineage_ur_swiftshader_package_license"] }\n',
          'license { name: "lineage_ur_swiftshader_package_license", visibility: [":__subpackages__"],\n'
          + '    license_kinds: ' + json.dumps(kinds) + ',\n'
          + '    license_text: ["package/licenses/**/*"],\n}\n']
    for module, relative in sorted(libraries.items()):
        info = dynamic(package / relative)
        if info["rpath"]:
            raise ValueError("package retained an RPATH")
        private_deps = [reverse[n] for n in info["needed"] if n in reverse]
        system_deps = [n.removesuffix(".so") for n in info["needed"] if n in system]
        if len(private_deps) + len(system_deps) != len(info["needed"]):
            raise ValueError("runtime dependency closure incomplete")
        header = subprocess.check_output(["readelf", "-h", str(package / relative)], text=True)
        if not re.search(r"Machine:\s+AArch64", header):
            raise ValueError("non-ARM64 payload")
        lines = ["cc_packaged_library_shared_target {", "    name: " + json.dumps(module) + ",",
                 '    vendor: true,', '    compile_multilib: "64",', '    stl: "none",',
                 "    srcs: [" + json.dumps("package/" + relative) + "],",
                 '    package_manifest: "package/package.json",', "    package_sha256: " + json.dumps(checksum) + ",",
                 '    strip: { none: true },',
                 "    shared_libs: " + json.dumps(private_deps + [n for n in system_deps if n not in ("libc", "libm", "libdl")]) + ",",
                 "    system_shared_libs: " + json.dumps([n for n in ("libc", "libm", "libdl") if n in system_deps]) + ","]
        if module == "vulkan.pastel":
            lines.append('    relative_install_path: "hw",')
        lines.append("}\n")
        bp.append("\n".join(lines))
    (output / "Android.bp").write_text("\n".join(bp))
    (output / "inventory.json").write_text(json.dumps({"manifest_sha256": checksum, "libraries": libraries,
                                                     "bytes": sum((package / p).stat().st_size for p in libraries.values())}, indent=2) + "\n")
    print("Packaged " + str(len(libraries)) + " ARM64/Bionic shared libraries at " + str(output))


if __name__ == "__main__":
    main()
