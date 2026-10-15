#!/usr/bin/env python3
"""Test the fork with reference checkout dependencies and an isolated Go cache."""

import argparse
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--soong-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/soong-tests"))
    args = parser.parse_args()
    source = args.source_root.resolve()
    soong = args.soong_root.resolve()
    out = args.out_dir.resolve()
    go = source / "prebuilts/go/linux-x86/bin/go"
    if not go.is_file() or not (soong / "go.work").is_file():
        parser.error("need a synced reference checkout and the separate Soong fork")
    # Rebase upstream's relative workspace paths onto the reference checkout,
    # replacing only its Soong module with our fork. Write nothing to that tree.
    def resolve(match):
        token = match.group()
        path = soong if token == "." else (source / "build/soong" / token).resolve()
        return str(path)
    workspace = re.sub(r"(?<!\S)\.{1,2}(?:/[^\s]+)?(?=\s|$)", resolve, (soong / "go.work").read_text())
    out.mkdir(parents=True, exist_ok=True)
    work = out / "go.work"
    work.write_text(workspace)
    env = os.environ | {"GOWORK": str(work), "GOCACHE": str(out / "cache"),
                        "GOPROXY": "off", "GOTOOLCHAIN": "local", "GOENV": "off"}
    env.pop("ANDROID_BUILD_TOP", None)
    subprocess.run([str(go), "test", "-p", "2", "./android", "./genrule", "./cc",
                    "-run", "^(TestSystemBuildTool.*|TestPrebuiltTool|TestPrebuilts)$", "-count=1"],
                   cwd=soong, env=env, check=True)


if __name__ == "__main__":
    main()
