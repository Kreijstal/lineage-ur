#!/usr/bin/env python3
"""Run a Bionic Vulkan compute consumer under ARM64 QEMU userspace."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--android-source", type=Path, required=True)
    parser.add_argument("--swiftshader-source", type=Path, required=True)
    parser.add_argument("--build", type=Path, required=True)
    parser.add_argument("--library", type=Path, required=True)
    parser.add_argument("--library-dir", type=Path, required=True)
    parser.add_argument("--qemu", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--icd-only", action="store_true")
    args = parser.parse_args()
    android, source, build, library, library_dir, qemu, output = [p.resolve() for p in (
        args.android_source, args.swiftshader_source, args.build, args.library, args.library_dir, args.qemu, args.output)]
    if output.is_relative_to(android) or output.is_relative_to(source):
        parser.error("test outputs must be outside source trees")
    output.mkdir(parents=True, exist_ok=True)
    reference = android / "out"
    variables = json.loads((reference / "soong/soong.lineage_r8q.variables").read_text())
    clang = android / "prebuilts/clang/host/linux-x86" / variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"] / "bin/clang"
    product = reference / "target/product" / variables["DeviceName"]
    api = str(variables["Platform_sdk_version"])
    recipe = Path(__file__).with_name("android")
    consumer = output / "vulkan-consumer"
    shader = output / "compute.spv"
    compile_shader = ["glslangValidator", "-V", "--target-env", "vulkan1.1", str(recipe / "compute.comp"), "-o", str(shader)]
    compile_consumer = [str(clang), "--target=aarch64-linux-android" + api, "--sysroot=" + str(build / "sysroot"),
        "-std=c11", "-Wall", "-Wextra", "-Werror", "-Wno-unused-parameter", "-fPIE", "-pie",
        "-I" + str(source / "include"), "-I" + str(android / "frameworks/native/vulkan/include"),
        "-I" + str(android / "hardware/libhardware/include_all"), "-I" + str(android / "system/core/libcutils/include"),
        "-I" + str(android / "system/core/libsystem/include"),
        str(recipe / "consumer.c"), "-ldl", "-o", str(consumer),
        "-Wl,--dynamic-linker=" + str(product / "apex/com.android.runtime/bin/linker64")]
    loader_path = ":".join(map(str, [library_dir, product / "apex/com.android.runtime/lib64/bionic", product / "system/lib64",
                                    *sorted((product / "apex").glob("*/lib64"))]))
    execute = [str(qemu), "-cpu", "max", "-E", "LD_LIBRARY_PATH=" + loader_path, str(consumer), str(library), str(shader)]
    if args.icd_only:
        execute.append("--icd-only")
    commands = {"shader": compile_shader, "consumer": compile_consumer, "execute": execute}
    (output / "commands.json").write_text(json.dumps(commands, indent=2) + "\n")
    subprocess.run(compile_shader, check=True)
    subprocess.run(compile_consumer, check=True)
    result = subprocess.run(execute, text=True, capture_output=True, timeout=180)
    print(result.stdout, end="")
    print(result.stderr, end="")
    report = {"scope": "synthetic ARM64/Bionic Vulkan execution; no physical hardware or display validation",
              "android_hal_required": not args.icd_only, "returncode": result.returncode,
              "stdout": result.stdout, "stderr": result.stderr, "library_sha256": sha(library),
              "consumer_sha256": sha(consumer), "shader_sha256": sha(shader), "qemu_sha256": sha(qemu)}
    (output / "report.json").write_text(json.dumps(report, indent=2) + "\n")
    if result.returncode:
        raise SystemExit(result.returncode)


if __name__ == "__main__":
    main()
