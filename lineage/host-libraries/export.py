#!/usr/bin/env python3
"""Package six pinned C host libraries without changing Android build inputs."""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET

from jpeg import build as build_jpeg

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from select_host_libraries import check_archive


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def git(repo, *args):
    return subprocess.check_output(["git", "-C", str(repo), *args], text=True,
                                   env=os.environ | {"GIT_OPTIONAL_LOCKS": "0"}).strip()


def export(args):
    source, reference, output = (p.resolve() for p in (args.source_root, args.reference_out, args.output))
    if (platform.system(), platform.machine(), platform.libc_ver()[0]) != ("Linux", "x86_64", "glibc"):
        raise ValueError("requires Linux x86-64/glibc")
    if not reference.is_relative_to(source) or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("reference output must be in Android; package output must be separate")
    if output.exists():
        raise ValueError("output exists; choose a new package directory")
    if not re.fullmatch(r"[A-Za-z0-9_]+", args.product) or not 1 <= args.jobs <= 4:
        raise ValueError("invalid product or jobs (use 1..4)")
    state = json.loads(args.build_state.read_text())
    if (state.get("status") != "complete" or Path(state.get("source_root", "")).resolve() != source
            or args.product != "lineage_" + state.get("device", "")):
        raise ValueError("need completed reference state for this checkout and product")
    manifest = ET.parse(args.reference_manifest).getroot()
    recipes_path = Path(__file__).with_name("recipes.json")
    recipes = json.loads(recipes_path.read_text())["libraries"]
    variables_path = reference / "soong" / ("soong." + args.product + ".variables")
    variables = json.loads(variables_path.read_text())
    if variables.get("HostArch") != "x86_64" or variables.get("HostMusl") or variables.get("SanitizeHost"):
        raise ValueError("reference must be unsanitized Linux x86-64/glibc")
    originals = [args.build_state, args.reference_manifest, variables_path]
    artifacts = {}
    for recipe in recipes:
        repo = source / recipe["repository"]
        pinned = manifest.find("./project[@path='" + recipe["repository"] + "']")
        if (git(repo, "status", "--porcelain") or git(repo, "rev-parse", "HEAD") != recipe["revision"]
                or pinned is None or pinned.get("revision") != recipe["revision"]):
            raise ValueError(f"{recipe['module']}: clean, reviewed, manifest-pinned revision required")
        if recipe.get("builder"):
            continue
        for linkage in recipe["linkages"]:
            filename = recipe["module"] + ("-host" if linkage == "shared" and recipe.get("unique_host_soname") else "")
            filename += ".a" if linkage == "static" else ".so"
            artifact = reference / "soong/.intermediates" / recipe["repository"] / recipe["module"] / ("linux_glibc_x86_64_" + linkage) / filename
            if linkage == "static":
                check_archive(artifact.read_bytes())
            else:
                dynamic = subprocess.check_output(["readelf", "-dW", str(artifact)], text=True,
                                                  env=os.environ | {"LC_ALL": "C"})
                soname = re.search(r"\(SONAME\).*\[([^]]+)\]", dynamic)
                needed = set(re.findall(r"\(NEEDED\).*\[([^]]+)\]", dynamic))
                if not soname or soname[1] != filename or needed - {"libc.so.6", "libm.so.6", "libdl.so.2", "libpthread.so.0", "librt.so.1", "libgcc_s.so.1", "ld-linux-x86-64.so.2"}:
                    raise ValueError("unexpected shared library SONAME/runtime dependency")
            artifacts[recipe["module"], linkage] = artifact
            originals.append(artifact)
    before = {p: sha(p) for p in originals}
    ninja = source / "prebuilts/build-tools/linux-x86/bin/ninja"
    commands = subprocess.check_output([str(ninja), "-f", str(reference / ("combined-" + args.product + ".ninja")),
                                       "-t", "commands", *(str(p.relative_to(source)) for p in artifacts.values())], cwd=source)
    compilers = sorted(set(re.findall(rb"prebuilts/clang/host/linux-x86/clang-[^\s/\"']+/bin/clang(?:\+\+)?", commands)))
    if not compilers:
        raise ValueError("reference graph has no pinned compiler commands")
    toolchain = {p.decode(): sha(source / p.decode()) for p in compilers}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".host-libraries-", dir=output.parent) as temporary:
        work = Path(temporary)
        stage = work / "packages"
        stage.mkdir()
        entries = []
        for recipe in recipes:
            name = recipe["module"]
            repo = source / recipe["repository"]
            package = stage / name
            for directory in ("lib", "include", "licenses", "provenance"):
                (package / directory).mkdir(parents=True)
            configuration = {"recipe_sha256": sha(recipes_path), "mode": "reference-export", "artifacts": {}}
            manifest_fields = {}
            for linkage in recipe["linkages"]:
                if recipe.get("builder") == "jpeg-native":
                    destination = package / "lib" / (name + ".a")
                    configuration.update(build_jpeg(repo, work, destination, args.jobs))
                    check_archive(destination.read_bytes())
                else:
                    original = artifacts[name, linkage]
                    destination = package / "lib" / original.name
                    shutil.copy2(original, destination)
                    configuration["artifacts"][linkage] = {"source": str(original), "sha256": before[original]}
                manifest_fields[linkage] = destination.relative_to(package).as_posix()
            for pattern in recipe["headers"]:
                headers = sorted(repo.glob(pattern))
                if not headers:
                    raise ValueError(f"header pattern has no matches: {pattern}")
                for header in headers:
                    shutil.copy2(header, package / "include" / header.name)
            for license_path in recipe["licenses"]:
                shutil.copy2(repo / license_path, package / "licenses" / Path(license_path).name)
            (package / "provenance/reference-commands.txt").write_bytes(commands)
            shutil.copy2(recipes_path, package / "provenance/recipes.json")
            shutil.copy2(variables_path, package / "provenance/soong.variables.json")
            shutil.copy2(args.reference_manifest, package / "provenance/manifest-pinned.xml")
            shutil.copy2(args.build_state, package / "provenance/build-state.json")
            write_json(package / "provenance/configuration.json", configuration)
            dependencies = {}
            for dependency, requirement in recipe.get("dependencies", {}).items():
                dependencies[dependency] = requirement | {"sha256": sha(stage / dependency / "package.json")}
            write_json(package / "package.json", {
                "schema_version": 1, "module": name, "host": "linux_glibc_x86_64",
                "source_revision": recipe["revision"],
                "toolchain": json.dumps(configuration.get("tools", toolchain), sort_keys=True),
                "configuration": json.dumps(configuration, sort_keys=True),
                "include_dirs": ["include"], "dependencies": dependencies,
                "unique_host_soname": recipe.get("unique_host_soname", False), **manifest_fields,
                "files": {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*")) if p.is_file()}})
            entries.append({"module": name, "manifest": name + "/package.json", "sha256": sha(package / "package.json"),
                            "licenses": [recipe["soong_license"]]})
            print(f"{name}: packaged {', '.join(recipe['linkages'])} ({configuration['mode']})", flush=True)
        if any(sha(p) != expected for p, expected in before.items()):
            raise ValueError("reference inputs changed during export")
        for recipe in recipes:
            repo = source / recipe["repository"]
            if git(repo, "status", "--porcelain") or git(repo, "rev-parse", "HEAD") != recipe["revision"]:
                raise ValueError("source changed during export")
        write_json(stage / "policy.json", {"schema_version": 1, "host": "linux_glibc_x86_64", "libraries": entries})
        os.rename(stage, output)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for option in ("source-root", "reference-out", "build-state", "reference-manifest", "output"):
        parser.add_argument("--" + option, type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--jobs", type=int, default=2)
    args = parser.parse_args()
    try:
        export(args)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        if isinstance(error, subprocess.CalledProcessError) and error.stderr:
            sys.stderr.write(error.stderr.decode() if isinstance(error.stderr, bytes) else error.stderr)
        parser.exit(2, f"package error: {error}\n")


if __name__ == "__main__":
    main()
