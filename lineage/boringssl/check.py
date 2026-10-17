#!/usr/bin/env python3
"""Compile a C API consumer and check it loads the selected BoringSSL pair."""

import argparse
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from select_host_libraries import inspect_package


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--selection", type=Path, required=True)
    parser.add_argument("--reference-out", type=Path, help="also run against original host libraries")
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    selection = args.selection.resolve()
    records = {r["module"]: r for r in json.loads((selection / "selection.json").read_text())["libraries"]}
    packages = {}
    for name in ("libcrypto", "libssl"):
        record = records.get(name)
        if not record or record["decision"] != "package":
            parser.error("both libcrypto and libssl must select packages")
        package = selection / record["snapshot"]
        # Revalidate snapshot hashes, including headers and dependency pins.
        manifest, _ = inspect_package({"module": name, "manifest": str(package / "package.json"),
                                      "sha256": record["manifest_sha256"]}, selection, "readelf")
        packages[name] = (package, manifest)
    dependency = packages["libssl"][1]["dependencies"].get("libcrypto", {})
    if dependency.get("sha256") != records["libcrypto"]["manifest_sha256"]:
        parser.error("libssl does not pin the selected crypto package")
    include = packages["libcrypto"][0] / "include"
    pairs = {"package": {name: directory / manifest["shared"]
                          for name, (directory, manifest) in packages.items()}}
    if args.reference_out:
        pairs["reference"] = {name: args.reference_out.resolve() / "host/linux-x86/lib64" / (name + "-host.so")
                              for name in packages}
    with tempfile.TemporaryDirectory(prefix="lineage-boringssl-check-") as temporary:
        for label, libraries in pairs.items():
            executable = Path(temporary) / label
            subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror",
                            "-I", str(include), str(Path(__file__).with_name("smoke.c")),
                            str(libraries["libssl"]), str(libraries["libcrypto"]),
                            "-o", str(executable)], check=True)
            env = os.environ | {"LD_LIBRARY_PATH": ":".join(dict.fromkeys(str(p.parent) for p in libraries.values())),
                                "LD_DEBUG": "libs", "LC_ALL": "C"}
            # Keep inherited preloads/debug-output redirection from masking evidence.
            env.pop("LD_PRELOAD", None)
            env.pop("LD_DEBUG_OUTPUT", None)
            result = subprocess.run([str(executable)], capture_output=True, text=True, env=env, timeout=15)
            if result.returncode:
                sys.stderr.write("\n".join(result.stderr.splitlines()[-20:]) + "\n")
                result.check_returncode()
            loaded = set(re.findall(r"calling init:\s*(\S+)", result.stderr))
            for library in libraries.values():
                if str(library) not in loaded:
                    raise RuntimeError(f"loader did not confirm selected artifact: {library}")
            print(f"{label}: {result.stdout.strip()} (loader paths verified)")


if __name__ == "__main__":
    main()
