#!/usr/bin/env python3
"""Cross-build the Android Vulkan HAL using packaged ARM64/Bionic LLVM."""

import argparse
import json
from pathlib import Path
import shutil
import shlex
import subprocess
from import_termux import verify_inputs


def verify_source(source):
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    if revision != "cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5":
        raise ValueError("SwiftShader source revision differs from the recipe pin")
    patch = subprocess.check_output(["git", "-C", str(source), "diff", "--binary"])
    if patch != (Path(__file__).parent / "patches/android-bionic.patch").read_bytes():
        raise ValueError("SwiftShader source must contain exactly the Android/Bionic recipe patch")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-source", type=Path, required=True)
    parser.add_argument("--swiftshader-source", type=Path, required=True)
    parser.add_argument("--termux", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--jobs", type=int, default=2)
    parser.add_argument("--configure-only", action="store_true")
    args = parser.parse_args()
    android, source, termux, output = [p.resolve() for p in
        (args.android_source, args.swiftshader_source, args.termux, args.output)]
    if output.is_relative_to(android) or output.is_relative_to(source) or output.is_relative_to(termux):
        parser.error("build output must be outside all input trees")
    if source.is_relative_to(android):
        parser.error("use a separate upstream SwiftShader checkout outside Android")
    verify_source(source)
    prefix = termux / "root/data/data/com.termux/files/usr"
    verify_inputs(termux, [prefix / "lib/libLLVM.so", prefix / "lib/libc++_shared.so",
                          *[p for p in (prefix / "include/llvm").rglob("*") if p.is_file()]])
    reference = android / "out"
    variables = json.loads((reference / "soong/soong.lineage_r8q.variables").read_text())
    clang = android / "prebuilts/clang/host/linux-x86" / variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"]
    api = str(variables["Platform_sdk_version"])
    product = reference / "target/product" / variables["DeviceName"]
    output.mkdir(parents=True, exist_ok=True)
    sysroot = output / "sysroot"
    if not sysroot.exists():
        shutil.copytree(reference / "soong/ndk/sysroot/usr/include", sysroot / "usr/include")
        libs = sysroot / "usr/lib/aarch64-linux-android" / api
        shutil.copytree(reference / "soong/ndk/sysroot/usr/lib/aarch64-linux-android" / api, libs)
        for name in ("crtbegin_so", "crtend_so", "crtbegin_dynamic", "crtend_android"):
            path = reference / "soong/.intermediates/bionic/libc" / name / (
                "android_arm64_" + variables["DeviceArchVariant"]) / (name + ".o")
            shutil.copy2(path, libs / (name + ".o"))
    # These headers select the NDK __ndk1 C++ ABI used by Termux's LLVM.
    cxx = ["-nostdinc++", "-isystem", str(clang / "android_libc++/ndk/aarch64/include/c++/v1"),
           "-isystem", str(clang / "include/c++/v1")]
    link = ["-nostdlib++", "-L" + str(prefix / "lib"), "-lc++_shared",
            "-L" + str(product / "system/lib64"),
            "-Wl,-rpath-link," + str(prefix / "lib"), "-Wl,-rpath-link," + str(product / "system/lib64")]
    # Linux supplies CMake's kernel/platform conventions; Clang's explicit
    # Android target and copied Bionic sysroot determine the actual ELF ABI.
    toolchain = output / "toolchain.cmake"
    def cmake_value(value):
        return "[=[" + str(value) + "]=]"
    config = {
        "CMAKE_SYSTEM_NAME": "Linux", "CMAKE_SYSTEM_PROCESSOR": "aarch64",
        "CMAKE_SYSROOT": str(sysroot), "CMAKE_C_COMPILER": str(clang / "bin/clang"),
        "CMAKE_CXX_COMPILER": str(clang / "bin/clang++"), "CMAKE_ASM_COMPILER": str(clang / "bin/clang"),
        "CMAKE_C_COMPILER_TARGET": "aarch64-linux-android" + api,
        "CMAKE_CXX_COMPILER_TARGET": "aarch64-linux-android" + api,
        "CMAKE_ASM_COMPILER_TARGET": "aarch64-linux-android" + api,
        "CMAKE_CXX_FLAGS_INIT": shlex.join(cxx), "CMAKE_EXE_LINKER_FLAGS_INIT": shlex.join(link),
        "CMAKE_SHARED_LINKER_FLAGS_INIT": shlex.join(link),
        "CMAKE_AR": str(clang / "bin/llvm-ar"), "CMAKE_RANLIB": str(clang / "bin/llvm-ranlib"),
        "CMAKE_FIND_ROOT_PATH_MODE_PROGRAM": "NEVER", "CMAKE_FIND_ROOT_PATH_MODE_LIBRARY": "ONLY",
        "CMAKE_FIND_ROOT_PATH_MODE_INCLUDE": "ONLY", "CMAKE_FIND_ROOT_PATH_MODE_PACKAGE": "ONLY",
    }
    toolchain.write_text("\n".join("set(" + k + " " + cmake_value(v) + ")" for k, v in config.items()) + "\n")
    configure = ["cmake", "-S", str(Path(__file__).with_name("android").resolve()), "-B", str(output / "build"),
                 "-G", "Ninja", "-DCMAKE_TOOLCHAIN_FILE=" + str(toolchain), "-DCMAKE_BUILD_TYPE=Release",
                 "-DSWIFTSHADER_SOURCE=" + str(source), "-DANDROID_SOURCE=" + str(android), "-DTERMUX_PREFIX=" + str(prefix)]
    build = ["cmake", "--build", str(output / "build"), "--target", "vk_swiftshader", "-j" + str(args.jobs)]
    (output / "commands.json").write_text(json.dumps({"configure": configure, "build": build}, indent=2) + "\n")
    subprocess.run(configure, check=True)
    if not args.configure_only:
        subprocess.run(build, check=True)


if __name__ == "__main__":
    main()
