"""Build a pinned native JPEG archive using the reviewed Android source lists."""

from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess


def build(repo, work, destination, jobs):
    # The recipe is pinned to Android.bp's hash/revision by the caller. This
    # deliberately understands only this defaults block, not arbitrary Soong.
    bp = (repo / "Android.bp").read_text()
    defaults = bp.split('name: "libjpeg-defaults",', 1)[1].split("    arch: {", 1)[0]
    common = re.search(r"\bsrcs:\s*\[(.*?)\]", defaults, re.S)[1]
    x64 = bp.split("        x86_64: {", 1)[1].split("        riscv64: {", 1)[0]
    optimized = re.search(r"\bsrcs:\s*\[(.*?)\]", x64, re.S)[1]
    sources = re.findall(r'"([^"\n]+\.(?:c|asm))"', common + optimized)
    if len(sources) != len(set(sources)) or not sources or "simd/x86_64/jsimd.c" not in sources:
        raise ValueError("unexpected pinned JPEG source layout")
    tools = {name: shutil.which(name) for name in ("cc", "ar", "nasm")}
    if not all(tools.values()):
        raise ValueError("JPEG native build requires cc, ar and nasm")
    flags = ["-O3", "-fPIC", "-fstrict-aliasing", "-DNO_GETENV", "-DWITH_SIMD",
             "-I", str(repo), "-I", str(repo / "simd/nasm")]
    commands = []
    for index, name in enumerate(sources):
        obj = work / f"jpeg-{index}.o"
        if name.endswith(".asm"):
            command = [tools["nasm"], "-f", "elf64", "-DPIC", "-D__x86_64__", "-DELF",
                       "-I" + str(repo / "simd/nasm") + "/", "-I" + str((repo / name).parent) + "/",
                       str(repo / name), "-o", str(obj)]
        else:
            command = [tools["cc"], *flags, "-c", str(repo / name), "-o", str(obj)]
        commands.append(command)
    with ThreadPoolExecutor(max_workers=jobs) as executor:
        list(executor.map(lambda command: subprocess.run(command, check=True, capture_output=True), commands))
    archive = [tools["ar"], "rcsD", str(destination), *(str(work / f"jpeg-{i}.o") for i in range(len(sources)))]
    subprocess.run(archive, check=True)
    commands.append(archive)
    identities = {}
    for name, tool in tools.items():
        identities[name] = {"path": tool, "sha256": hashlib.sha256(Path(tool).read_bytes()).hexdigest(),
                            "version": subprocess.check_output([tool, "--version"], text=True).splitlines()[0]}
    return {"mode": "native-recipe", "tools": identities, "commands": commands,
            "note": "Android source lists, SIMD, original configuration headers and arithmetic coding; native host toolchain, not the complete Soong flag set."}
