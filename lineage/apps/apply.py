#!/usr/bin/env python3
"""Install packaged-app adapters into a separate idle Android checkout.

Each adapter is a new `lineage-ur-app/` directory beside the source app; no
existing file is modified. Apps whose recorded inputs differ from the checkout
are reported and skipped, since Soong would keep their source build anyway.
"""

import argparse
from contextlib import ExitStack
import fcntl
import json
from pathlib import Path
import shutil

from package import adapter, sha


def plan(packages, checkout):
    packages, checkout = Path(packages).resolve(), Path(checkout).resolve()
    inventory = json.loads((packages / "inventory.json").read_text())
    first = inventory["apps"][0]["module"]
    donor = Path(json.loads((packages / "packages" / first / "reference/build-state.json").read_text())["source_root"]).resolve()
    if checkout == donor or checkout.is_relative_to(donor):
        raise ValueError("refusing to modify the protected reference checkout")
    if not (checkout / "build/soong/java/packaged_app.go").is_file():
        raise ValueError("checkout must use the modified Soong fork")
    ready, stale = [], []
    checked = {}
    for record in inventory["apps"]:
        module = record["module"]
        destination = checkout / record["path"] / "lineage-ur-app"
        if not destination.parent.resolve().is_relative_to(checkout) or destination.parent.resolve().is_relative_to(donor):
            raise ValueError(f"{module}: app directory must be private to the experimental checkout")
        if destination.exists() or destination.is_symlink():
            raise ValueError(f"{module}: adapter directory already exists")
        package = packages / "packages" / module
        manifest_path = package / "package.json"
        if sha(manifest_path) != record["manifest_sha256"]:
            raise ValueError(f"{module}: manifest checksum mismatch")
        manifest = json.loads(manifest_path.read_text())
        for relative, expected in manifest["files"].items():
            if sha(package / relative) != expected:
                raise ValueError(f"{module}: package content mismatch: {relative}")
        differences = []
        for relative, expected in (manifest["inputs"] | manifest.get("installer_checked_inputs", {})).items():
            if relative not in checked:
                path = checkout / relative
                checked[relative] = sha(path) if path.is_file() else None
            if checked[relative] != expected:
                differences.append(relative)
        if differences:
            stale.append((module, differences))
            continue
        # Reconstruct the adapter rather than trusting an editable generated bp.
        ready.append((record, package, destination))
    return checkout, ready, stale


def install(packages, checkout, check_only=False):
    checkout, ready, stale = plan(packages, checkout)
    with ExitStack() as stack:
        for output in checkout.glob("out*"):
            lock = output / ".lock"
            if lock.is_file():
                stream = stack.enter_context(lock.open("rb"))
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError("checkout has an active build") from error
        if not check_only:
            installed = []
            try:
                for record, package, destination in ready:
                    destination.mkdir()
                    installed.append(destination)
                    shutil.copytree(package, destination / "snapshots" / record["manifest_sha256"])
                    (destination / "Android.bp").write_text(adapter(record))
            except Exception:
                for path in reversed(installed):
                    shutil.rmtree(path)
                raise
    return ready, stale


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        ready, stale = install(args.packages, args.checkout, args.check_only)
    except (ValueError, OSError) as error:
        parser.exit(2, f"integration error: {error}\n")
    for module, differences in stale:
        shown = ", ".join(differences[:3]) + (f" and {len(differences) - 3} more" if len(differences) > 3 else "")
        print(f"{module}: skipped, {len(differences)} inputs differ from the package ({shown})")
    print(f"{'Validated' if args.check_only else 'Installed'} {len(ready)} packaged-app adapters")


if __name__ == "__main__":
    main()
