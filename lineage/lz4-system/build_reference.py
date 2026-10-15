#!/usr/bin/env python3
"""Build a CLI reference for tests; normal system-lz4 selection builds nothing."""

import argparse
import hashlib
import json
from pathlib import Path
import shutil
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-dir", type=Path, required=True, help="clean pinned external/lz4 repository")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    source, output = args.source_dir.resolve(), args.output.resolve()
    if output.is_relative_to(source):
        parser.error("output must be outside the reference source repository")
    if subprocess.check_output(["git", "-C", str(source), "status", "--porcelain"]):
        parser.error("reference source repository must be clean")
    revision = subprocess.check_output(["git", "-C", str(source), "rev-parse", "HEAD"], text=True).strip()
    compiler = shutil.which(args.cc)
    if not compiler:
        parser.error("C compiler not found")
    # Same translation units as the pinned Android.bp's lz4 host executable
    # and its liblz4 dependency. Compile serially through a native C driver.
    files = [source / "programs" / (name + ".c") for name in
             ("bench", "lz4io", "lz4cli", "timefn", "threadpool", "lorem")]
    files += [source / "lib" / (name + ".c") for name in ("lz4", "lz4hc", "lz4frame", "xxhash")]
    output.mkdir(parents=True, exist_ok=True)
    command = [compiler, "-O2", "-pthread", "-I", str(source / "lib"),
               *map(str, files), "-o", str(output / "lz4")]
    subprocess.run(command, check=True)
    shutil.copy2(source / "programs/COPYING", output / "COPYING")
    record = {"source_revision": revision, "command": command,
              "compiler_sha256": hashlib.sha256(Path(compiler).resolve().read_bytes()).hexdigest(),
              "binary_sha256": hashlib.sha256((output / "lz4").read_bytes()).hexdigest()}
    (output / "build.json").write_text(json.dumps(record, indent=2) + "\n")
    print(f"Built isolated LZ4 CLI reference from {revision}")


if __name__ == "__main__":
    main()
