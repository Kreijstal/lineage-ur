#!/usr/bin/env python3
"""Build an experimental native C host package from a clean LineageOS LZ4 repo."""

import argparse
import hashlib
import json
from pathlib import Path
import platform
import shutil
import subprocess
import tempfile


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="synced external/lz4 repository")
    parser.add_argument("--output", type=Path, required=True, help="package directory outside the source repository")
    parser.add_argument("--cc", default="cc")
    parser.add_argument("--ar", default="ar")
    args = parser.parse_args()
    source = args.source_dir.resolve()
    output = args.output.resolve()
    if (platform.system(), platform.machine(), platform.libc_ver()[0]) != ("Linux", "x86_64", "glibc"):
        parser.error("requires a Linux x86-64/glibc host")
    if output.is_relative_to(source):
        parser.error("output must be outside the source repository")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"]):
        parser.error("source repository must be clean; record source changes first")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    compiler = shutil.which(args.cc)
    archiver = shutil.which(args.ar)
    if not compiler or not archiver:
        parser.error("C compiler and archiver required")
    version = subprocess.check_output([compiler, "--version"], text=True).splitlines()[0]
    flags = ["-O2", "-fPIC", "-std=c99"]
    with tempfile.TemporaryDirectory(prefix="lineage-lz4-") as temporary:
        work = Path(temporary)
        objects = []
        for name in ("lz4", "lz4hc", "lz4frame", "xxhash"):
            obj = work / (name + ".o")
            subprocess.run([compiler, *flags, "-c", str(source / "lib" / (name + ".c")), "-o", str(obj)], check=True)
            objects.append(str(obj))
        (output / "lib").mkdir(parents=True, exist_ok=True)
        (output / "include").mkdir(exist_ok=True)
        (output / "licenses").mkdir(exist_ok=True)
        archive = work / "liblz4.a"
        subprocess.run([archiver, "rcs", str(archive), *objects], check=True)
        shutil.copy2(archive, output / "lib/liblz4.a")
        subprocess.run([compiler, "-shared", "-Wl,-soname,liblz4.so", *objects,
                        "-o", str(output / "lib/liblz4.so")], check=True)
        for header in (source / "lib").glob("*.h"):
            shutil.copy2(header, output / "include" / header.name)
        shutil.copy2(source / "lib/LICENSE", output / "licenses/LICENSE")
    files = sorted(path for directory in ("lib", "include", "licenses") for path in (output / directory).rglob("*") if path.is_file())
    config = json.dumps({"compile_flags": flags, "soname": "liblz4.so", "archiver_sha256": sha(Path(archiver).resolve())}, sort_keys=True)
    manifest = {
        "schema_version": 1, "module": "liblz4", "host": "linux_glibc_x86_64",
        "source_revision": revision, "toolchain": version + "; sha256=" + sha(Path(compiler).resolve()),
        "configuration": config, "static": "lib/liblz4.a", "shared": "lib/liblz4.so",
        "include_dirs": ["include"], "dependencies": {},
        "files": {path.relative_to(output).as_posix(): sha(path) for path in files},
    }
    manifest_path = output / "package.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n")
    policy = {"schema_version": 1, "host": "linux_glibc_x86_64", "libraries": [{
        "module": "liblz4", "manifest": "package.json", "sha256": sha(manifest_path),
        "licenses": ["external_lz4_lib_license"],
    }]}
    (output / "policy.json").write_text(json.dumps(policy, indent=2) + "\n")
    print(f"Built {manifest_path} from {revision}; manifest SHA-256 {sha(manifest_path)}")


if __name__ == "__main__":
    main()
