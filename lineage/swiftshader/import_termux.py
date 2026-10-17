#!/usr/bin/env python3
"""Fetch hash-pinned Termux ARM64 packages into an isolated staging tree."""

import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import io
import json
from pathlib import Path
import subprocess
import tarfile


def verify_inputs(staging, paths, lock_path=None):
    """Compare consumed files with the hash-pinned original Debian payloads."""
    lock = json.loads((staging / "lock.json").read_text())
    expected = json.loads((lock_path or Path(__file__).with_name("termux-aarch64.lock.json")).read_text())
    if lock["packages"] != expected["packages"]:
        raise ValueError("imported package versions differ from the recipe lock")
    wanted = {p.resolve().relative_to(staging / "root").as_posix(): p for p in paths}
    remaining = dict(wanted)
    for entry in expected["packages"].values():
        deb = staging / "downloads" / Path(entry["Filename"]).name
        if hashlib.sha256(deb.read_bytes()).hexdigest() != entry["SHA256"]:
            raise ValueError("imported archive was modified: " + str(deb))
        member = next(m for m in subprocess.check_output(["ar", "t", str(deb)], text=True).splitlines() if m.startswith("data.tar"))
        with tarfile.open(fileobj=io.BytesIO(subprocess.check_output(["ar", "p", str(deb), member]))) as archive:
            for item in archive:
                name = item.name.removeprefix("./")
                if item.isfile() and name in remaining:
                    if hashlib.sha256(archive.extractfile(item).read()).hexdigest() != hashlib.sha256(remaining[name].read_bytes()).hexdigest():
                        raise ValueError("consumed Termux input differs from archive: " + name)
                    del remaining[name]
    if remaining:
        raise ValueError("consumed files absent from pinned archives: " + repr(sorted(remaining)))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--lock", type=Path, default=Path(__file__).with_name("termux-aarch64.lock.json"))
    args = parser.parse_args()
    output = args.output.resolve()
    lock = json.loads(args.lock.read_text())
    if output.exists():
        parser.error("output must be a new staging directory")
    output.mkdir(parents=True)
    downloads = output / "downloads"
    downloads.mkdir()

    def fetch(item):
        name, entry = item
        path = downloads / Path(entry["Filename"]).name
        subprocess.run(["curl", "-fLsS", "--retry", "2", "--max-time", "180",
                        lock["repository"] + entry["Filename"], "-o", str(path)], check=True)
        if path.stat().st_size != int(entry["Size"]) or hashlib.sha256(path.read_bytes()).hexdigest() != entry["SHA256"]:
            raise ValueError("package checksum/size mismatch: " + name)
        print(name + ": archive verified", flush=True)
        return name, path

    with ThreadPoolExecutor(max_workers=4) as executor:
        packages = list(executor.map(fetch, lock["packages"].items()))
    extra = lock.get("libiconv_source")
    if extra:
        source = downloads / "libiconv-1.19.tar.gz"
        subprocess.run(["curl", "-fLsS", "--retry", "2", "--max-time", "180", extra["url"], "-o", str(source)], check=True)
        if hashlib.sha256(source.read_bytes()).hexdigest() != extra["sha256"]:
            raise ValueError("libiconv source checksum mismatch")
    for name, checksum in lock.get("supplemental_licenses", {}).items():
        path = Path(__file__).with_name("licenses") / name
        if hashlib.sha256(path.read_bytes()).hexdigest() != checksum:
            raise ValueError("supplemental license checksum mismatch: " + name)
    root = output / "root"
    root.mkdir()
    for name, path in packages:
        members = subprocess.check_output(["ar", "t", str(path)], text=True).splitlines()
        payload = next(m for m in members if m.startswith("data.tar"))
        data = subprocess.check_output(["ar", "p", str(path), payload])
        with tarfile.open(fileobj=io.BytesIO(data)) as archive:
            archive.extractall(root, filter="data")
    (output / "lock.json").write_text(json.dumps(lock, indent=2) + "\n")
    print("Extracted packages without installing or executing package scripts: " + str(root))


if __name__ == "__main__":
    main()
