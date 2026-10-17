#!/usr/bin/env python3
"""Check adapted Termux ELFs and run existing Android programs against them."""

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import zipfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("android-source", "adapter", "qemu", "output"):
        parser.add_argument("--" + name, type=Path, required=True)
    args = parser.parse_args()
    android, adapter, qemu, output = [p.resolve() for p in (args.android_source, args.adapter, args.qemu, args.output)]
    if output.exists() or output.is_relative_to(android) or output.is_relative_to(adapter):
        parser.error("output must be a new directory outside input trees")
    package = adapter / "package"
    manifest = json.loads((package / "package.json").read_text())
    for name, expected in manifest["files"].items():
        path = package / name
        if not path.resolve().is_relative_to(package) or sha(path) != expected:
            raise ValueError("package content mismatch: " + name)
    variables = json.loads((android / "out/soong/soong.lineage_r8q.variables").read_text())
    product = android / "out/target/product" / variables["DeviceName"]
    compiler = android / "prebuilts/clang/host/linux-x86" / variables["BuildFlags"]["RELEASE_BUILD_CLANG_VERSION"]
    bionic = product / "apex/com.android.runtime/lib64/bionic"
    libs = package / "lib64"
    output.mkdir(parents=True)
    records = []
    for name, relative in manifest["libraries"].items():
        command = ["python3", str(android / "build/make/tools/check_elf_file.py"), str(package / relative),
                   "--soname", name + ".so", "--max-page-size", "16384",
                   "--llvm-readobj", str(compiler / "bin/llvm-readobj")]
        for dependency in [*sorted(libs.glob("*.so")), *[bionic / n for n in ("libc.so", "libm.so", "libdl.so")]]:
            if dependency != package / relative:
                command.extend(["--shared-lib", str(dependency)])
        result = subprocess.run(command, capture_output=True, text=True, timeout=30)
        records.append({"test": name + " ELF/SONAME/dependencies/symbols/16KiB-alignment", "command": command,
                        "returncode": result.returncode, "stdout": result.stdout, "stderr": result.stderr})
    payload = b"Independent Termux dependencies in Android consumers.\n" * 1000
    archive = output / "fixture.zip"
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_DEFLATED) as zip_file:
        zip_file.writestr("payload.txt", payload)
    plain = output / "payload.txt"
    plain.write_bytes(payload)
    compressed = output / "fixture.zst"
    subprocess.run(["zstd", "-q", str(plain), "-o", str(compressed)], check=True)
    loader_path = ":".join(map(str, [libs, bionic, product / "system/lib64", *sorted((product / "apex").glob("*/lib64"))]))
    launcher = [str(qemu), "-cpu", "max", "-E", "LD_LIBRARY_PATH=" + loader_path,
                str(product / "apex/com.android.runtime/bin/linker64")]
    for name, binary, arguments in [
        ("Android ziptool + libziparchive + Termux zlib", product / "system/bin/ziptool", ["unzip", "-p", str(archive), "payload.txt"]),
        ("Android zstd CLI + Termux zstd/zlib", product / "system_ext/bin/zstd", ["-d", "-q", "-c", str(compressed)]),
    ]:
        command = launcher + [str(binary), *arguments]
        result = subprocess.run(command, capture_output=True, timeout=30)
        match = result.stdout == payload
        records.append({"test": name, "command": command, "returncode": result.returncode,
                        "output_matches": match, "output_bytes": len(result.stdout),
                        "output_sha256": hashlib.sha256(result.stdout).hexdigest(),
                        "stderr": result.stderr.decode(errors="replace"), "binary_sha256": sha(binary)})
    passed = all(r["returncode"] == 0 and r.get("output_matches", True) for r in records)
    (output / "report.json").write_text(json.dumps({
        "scope": "existing r8q Android executables under ARM64/Bionic QEMU, independent Termux shared libraries; no ROM boot or hardware validation",
        "package_manifest_sha256": sha(package / "package.json"), "qemu_sha256": sha(qemu),
        "result": "pass" if passed else "fail", "tests": records,
    }, indent=2) + "\n")
    for record in records:
        print(record["test"] + ": " + ("PASS" if record["returncode"] == 0 and record.get("output_matches", True) else "FAIL"))
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
