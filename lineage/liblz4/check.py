#!/usr/bin/env python3
"""Compile and run a roundtrip consumer against both selected LZ4 variants."""
import argparse
import json
from pathlib import Path
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    selection = args.selection.resolve()
    records = json.loads((selection / "selection.json").read_text())["libraries"]
    record = next((item for item in records if item["module"] == "liblz4"), None)
    if not record or record["decision"] != "package":
        parser.error("selection must contain an accepted liblz4 package")
    package = selection / record["snapshot"]
    with tempfile.TemporaryDirectory(prefix="lineage-lz4-check-") as temporary:
        for linkage, extension in (("static", "a"), ("shared", "so")):
            executable = str(Path(temporary) / linkage)
            subprocess.run([args.cc, str(Path(__file__).with_name("smoke.c")),
                            "-I", str(package / "include"), str(package / "lib" / ("liblz4." + extension)),
                            "-Wl,-rpath," + str(package / "lib"), "-o", executable], check=True)
            subprocess.run([executable], check=True)
            print(f"LZ4 {linkage} package consumer: PASS")


if __name__ == "__main__":
    main()
