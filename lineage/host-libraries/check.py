#!/usr/bin/env python3
"""Compile and execute actual consumers of each selected host C library."""

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
    parser.add_argument("--reference-out", type=Path, help="also compare five exported reference libraries")
    parser.add_argument("--cc", default="cc")
    args = parser.parse_args()
    selection = args.selection.resolve()
    records = {item["module"]: item for item in json.loads((selection / "selection.json").read_text())["libraries"]}
    recipes = json.loads(Path(__file__).with_name("recipes.json").read_text())["libraries"]
    packages = {}
    for recipe in recipes:
        name = recipe["module"]
        record = records.get(name)
        if not record or record["decision"] != "package":
            parser.error(f"{name}: an accepted package is required")
        package = selection / record["snapshot"]
        manifest, _ = inspect_package({"module": name, "manifest": str(package / "package.json"),
                                      "sha256": record["manifest_sha256"]}, selection, "readelf")
        if manifest["source_revision"] != recipe["revision"]:
            parser.error(f"{name}: source revision differs from reviewed recipe")
        packages[name] = package, manifest
    for name, (_, manifest) in packages.items():
        for dependency, requirement in manifest["dependencies"].items():
            if records[dependency]["manifest_sha256"] != requirement["sha256"]:
                parser.error(f"{name}: dependency pin mismatch")
    results = []
    with tempfile.TemporaryDirectory(prefix="host-library-consumers-") as temporary:
        for recipe in recipes:
            name = recipe["module"]
            package, manifest = packages[name]
            for linkage in recipe["linkages"]:
                modes = ["package"] + (["reference"] if args.reference_out and not recipe.get("builder") else [])
                for mode in modes:
                    def artifact(module, kind):
                        directory, data = packages[module]
                        if mode == "package":
                            return directory / data[kind]
                        component = next(r for r in recipes if r["module"] == module)
                        return args.reference_out.resolve() / "soong/.intermediates" / component["repository"] / module / ("linux_glibc_x86_64_" + kind) / Path(data[kind]).name
                    libraries = [artifact(name, linkage)]
                    # These recipes currently have a single-level dependency: PNG -> zlib shared.
                    for dependency, requirement in manifest["dependencies"].items():
                        libraries.append(artifact(dependency, requirement["linkage"]))
                    executable = Path(temporary) / (name + "-" + linkage + "-" + mode)
                    subprocess.run([args.cc, "-std=c11", "-Wall", "-Wextra", "-Werror", "-I", str(package / "include"),
                                    str(Path(__file__).with_name("smoke") / (name.removeprefix("lib") + ".c")),
                                    *(str(p) for p in libraries), "-lm", "-pthread", "-o", str(executable)], check=True)
                    shared = [p for p in libraries if p.suffix == ".so"]
                    env = os.environ | {"LC_ALL": "C", "LD_LIBRARY_PATH": ":".join(dict.fromkeys(str(p.parent) for p in shared)),
                                        "LD_DEBUG": "libs"}
                    env.pop("LD_PRELOAD", None); env.pop("LD_DEBUG_OUTPUT", None)
                    result = subprocess.run([str(executable)], capture_output=True, text=True, timeout=15, env=env)
                    if result.returncode:
                        sys.stderr.write("\n".join(result.stderr.splitlines()[-20:]) + "\n")
                        result.check_returncode()
                    loaded = set(re.findall(r"calling init:\s*(\S+)", result.stderr))
                    if any(str(p) not in loaded for p in shared):
                        raise RuntimeError("loader did not use the selected shared dependencies")
                    row = {"module": name, "linkage": linkage, "mode": mode, "result": "pass", "output": result.stdout.strip()}
                    results.append(row)
                    print(f"{name} {linkage} {mode}: {result.stdout.strip()}", flush=True)
    (selection / "consumer-check.json").write_text(json.dumps({"scope": "host consumers; no ROM/device compatibility claim", "tests": results}, indent=2) + "\n")


if __name__ == "__main__":
    main()
