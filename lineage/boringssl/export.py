#!/usr/bin/env python3
"""Package the host shared BoringSSL pair from a completed reference build.

Reads existing artifacts and Ninja commands only; never invokes a build or
changes the reference checkout. Device, static and FIPS variants are excluded.
"""

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import tempfile
import xml.etree.ElementTree as ET


def sha(path):
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def write_json(path, value):
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n")


def export(source, reference, product, state_path, manifest_path, output):
    source, reference, output = (Path(p).resolve() for p in (source, reference, output))
    state_path, manifest_path = (Path(p).resolve() for p in (state_path, manifest_path))
    if (platform.system(), platform.machine(), platform.libc_ver()[0]) != ("Linux", "x86_64", "glibc"):
        raise ValueError("requires Linux x86-64/glibc")
    if not reference.is_relative_to(source) or output.is_relative_to(source) or source.is_relative_to(output):
        raise ValueError("reference output must be inside source; package output must be separate")
    if output.exists():
        raise ValueError("package output already exists; choose a new directory")
    if not re.fullmatch(r"[A-Za-z0-9_]+", product):
        raise ValueError("invalid product name")
    state = json.loads(state_path.read_text())
    if state.get("status") != "complete" or Path(state.get("source_root", "")).resolve() != source:
        raise ValueError("need a completed build state for this source checkout")
    if product != "lineage_" + state.get("device", ""):
        raise ValueError("product does not match the completed reference build")
    repo = source / "external/boringssl"
    if subprocess.check_output(["git", "-C", str(repo), "status", "--porcelain"]):
        raise ValueError("BoringSSL source must be clean")
    revision = subprocess.check_output(["git", "-C", str(repo), "rev-parse", "HEAD"], text=True).strip()
    pinned = ET.parse(manifest_path).getroot().find("./project[@path='external/boringssl']")
    if pinned is None or pinned.get("revision") != revision:
        raise ValueError("reference manifest must pin the current BoringSSL revision")
    variables_path = reference / "soong" / ("soong." + product + ".variables")
    variables = json.loads(variables_path.read_text())
    if variables.get("HostArch") != "x86_64" or variables.get("HostMusl") or variables.get("SanitizeHost"):
        raise ValueError("need unsanitized x86-64/glibc reference host artifacts")
    libraries = {name: reference / "host/linux-x86/lib64" / (name + "-host.so")
                 for name in ("libcrypto", "libssl")}
    runtime = {"libdl.so.2", "libpthread.so.0", "libm.so.6", "librt.so.1", "libgcc_s.so.1",
               "libc.so.6", "ld-linux-x86-64.so.2"}
    for name, library in libraries.items():
        info = subprocess.check_output(["readelf", "-dW", str(library)], text=True,
                                       env=os.environ | {"LC_ALL": "C"})
        soname = re.search(r"\(SONAME\).*\[([^]]+)\]", info)
        needed = set(re.findall(r"\(NEEDED\).*\[([^]]+)\]", info))
        allowed = runtime | ({"libcrypto-host.so"} if name == "libssl" else set())
        if not soname or soname[1] != library.name or needed - allowed:
            raise ValueError(f"{name}: unexpected SONAME or runtime dependency; dedicated adapter required")
        if name == "libssl" and "libcrypto-host.so" not in needed:
            raise ValueError("libssl must dynamically depend on the packaged crypto library")
    before = {str(p): sha(p) for p in [*libraries.values(), state_path, manifest_path, variables_path]}
    # A completed build's command graph is provenance, not a build attestation.
    # -t commands reads the graph; it executes none of the printed commands.
    graph = reference / ("combined-" + product + ".ninja")
    ninja = source / "prebuilts/build-tools/linux-x86/bin/ninja"
    commands = subprocess.check_output([str(ninja), "-f", str(graph), "-t", "commands",
                                        *(str(p.relative_to(source)) for p in libraries.values())], cwd=source)
    compilers = sorted(set(re.findall(rb"prebuilts/clang/host/linux-x86/clang-[^\s/\"']+/bin/clang(?:\+\+)?", commands)))
    if not compilers:
        raise ValueError("reference graph has no pinned Clang compiler commands")
    tools = {p.decode(): sha(source / p.decode()) for p in compilers}
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".boringssl-export-", dir=output.parent) as temporary:
        stage = Path(temporary) / "package"
        stage.mkdir()
        entries = []
        for name, library in libraries.items():
            package = stage / name
            (package / "lib").mkdir(parents=True)
            (package / "licenses").mkdir()
            (package / "provenance").mkdir()
            shutil.copy2(library, package / "lib" / library.name)
            shutil.copytree(repo / "src/include", package / "include")
            shutil.copy2(repo / "LICENSE", package / "licenses/BoringSSL-LICENSE")
            # The reference shared objects incorporate libc++ statically.
            shutil.copy2(source / "external/libcxx/LICENSE.TXT", package / "licenses/libcxx-LICENSE.TXT")
            (package / "provenance/commands.txt").write_bytes(commands)
            shutil.copy2(variables_path, package / "provenance/soong.variables.json")
            shutil.copy2(manifest_path, package / "provenance/manifest-pinned.xml")
            shutil.copy2(state_path, package / "provenance/build-state.json")
            configuration = {"scope": "host-shared-only", "unique_host_soname": True,
                             "source_output": str(library), "source_output_sha256": before[str(library)],
                             "commands_sha256": hashlib.sha256(commands).hexdigest(),
                             "soong_variables_sha256": before[str(variables_path)],
                             "note": "Read-only export of completed reference outputs; no build attestation or automatic cross-revision compatibility claim."}
            dependencies = {} if name == "libcrypto" else {"libcrypto": {
                "sha256": sha(stage / "libcrypto/package.json"), "linkage": "shared", "reexport_headers": False}}
            files = {p.relative_to(package).as_posix(): sha(p) for p in sorted(package.rglob("*")) if p.is_file()}
            write_json(package / "package.json", {
                "schema_version": 1, "module": name, "host": "linux_glibc_x86_64",
                "source_revision": revision, "toolchain": json.dumps(tools, sort_keys=True),
                "configuration": json.dumps(configuration, sort_keys=True),
                "shared": "lib/" + library.name, "unique_host_soname": True,
                "include_dirs": ["include"], "dependencies": dependencies, "files": files})
            entries.append({"module": name, "manifest": name + "/package.json",
                            "sha256": sha(package / "package.json"), "licenses": ["external_boringssl_license"]})
        if any(sha(Path(path)) != checksum for path, checksum in before.items()):
            raise ValueError("reference inputs changed during export")
        write_json(stage / "policy.json", {"schema_version": 1, "host": "linux_glibc_x86_64", "libraries": entries})
        os.rename(stage, output)
    return revision


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--reference-out", type=Path, required=True)
    parser.add_argument("--product", required=True)
    parser.add_argument("--build-state", type=Path, required=True)
    parser.add_argument("--reference-manifest", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        revision = export(args.source_root, args.reference_out, args.product, args.build_state,
                          args.reference_manifest, args.output)
    except (ValueError, OSError, subprocess.SubprocessError) as error:
        parser.exit(2, f"export error: {error}\n")
    print(f"Exported host shared BoringSSL {revision} to {args.output}")


if __name__ == "__main__":
    main()
