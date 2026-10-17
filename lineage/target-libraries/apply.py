#!/usr/bin/env python3
"""Install target-package defaults into a separate idle Android checkout."""

import argparse
from contextlib import ExitStack
import fcntl
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def plan(packages, checkout):
    packages, checkout = Path(packages).resolve(), Path(checkout).resolve()
    inventory = json.loads((packages / "inventory.json").read_text())
    first = inventory["libraries"][0]["module"]
    donor = Path(json.loads((packages / "packages" / first / "reference/build-state.json").read_text())["source_root"]).resolve()
    if checkout == donor or checkout.is_relative_to(donor):
        raise ValueError("refusing to modify the protected reference checkout")
    if not (checkout / "build/soong/cc/packaged_target.go").is_file():
        raise ValueError("checkout must use the modified Soong fork")
    changes = []
    components = {}
    overlay_bps = {r["repository"] + "/Android.bp": packages / "overlay" / r["repository"] / "Android.bp"
                   for r in inventory["libraries"]}
    checked = {}
    for record in inventory["libraries"]:
        repository, module = record["repository"], record["module"]
        component = checkout / repository
        if (not component.resolve().is_relative_to(checkout) or component.resolve().is_relative_to(donor)):
            raise ValueError("component must be private to the experimental checkout")
        source_bp = component / "Android.bp"
        if sha(source_bp) != record["original_android_bp_sha256"]:
            raise ValueError(f"{module}: Android.bp differs from the reviewed baseline")
        destination = component / "lineage-ur-target"
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
        modified_bp = packages / "overlay" / repository / "Android.bp"
        if sha(modified_bp) != manifest["inputs"][repository + "/Android.bp"]:
            raise ValueError(f"{module}: overlay source definition checksum mismatch")
        for relative, expected in manifest["inputs"].items():
            if relative in overlay_bps:
                if sha(overlay_bps[relative]) != expected:
                    raise ValueError(f"{module}: conflicting combined overlay input: {relative}")
                continue
            if relative not in checked:
                checked[relative] = sha(checkout / relative)
            if checked[relative] != expected:
                raise ValueError(f"{module}: source/toolchain input differs: {relative}")
        # Reconstruct the adapter rather than trusting an editable generated bp.
        adapter = ('// Generated target object package; source module owns linking and installation.\n'
                   'cc_defaults {\n    name: "lineage_ur_target_' + module + '",\n'
                   '    target_package: {\n        manifest: "lineage-ur-target/snapshots/' + record["manifest_sha256"] + '/package.json",\n'
                   '        sha256: "' + record["manifest_sha256"] + '",\n    },\n}\n')
        if repository not in components:
            change = {"bp": source_bp, "original": source_bp.read_bytes(), "replacement": modified_bp.read_bytes(),
                      "destination": destination, "snapshots": [], "adapter": ""}
            components[repository] = change
            changes.append(change)
        change = components[repository]
        change["snapshots"].append((package, record["manifest_sha256"]))
        change["adapter"] += adapter
    return checkout, changes


def replace(path, data):
    # Atomic replacement also avoids changing a reference file through a hardlink.
    with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".lineage-ur-", delete=False) as stream:
        temporary = Path(stream.name)
        stream.write(data)
    temporary.chmod(path.stat().st_mode & 0o777)
    os.replace(temporary, path)


def install(packages, checkout, check_only=False):
    checkout, changes = plan(packages, checkout)
    count = sum(len(c["snapshots"]) for c in changes)
    with ExitStack() as stack:
        for output in checkout.glob("out*"):
            lock = output / ".lock"
            if lock.is_file():
                stream = stack.enter_context(lock.open("rb"))
                try:
                    fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
                except BlockingIOError as error:
                    raise ValueError("checkout has an active build") from error
        if check_only:
            return count
        installed, modified = [], []
        try:
            for change in changes:
                destination = change["destination"]
                destination.mkdir()
                installed.append(destination)
                for package, checksum in change["snapshots"]:
                    shutil.copytree(package, destination / "snapshots" / checksum)
                (destination / "Android.bp").write_text(change["adapter"])
            for change in changes:
                replace(change["bp"], change["replacement"])
                modified.append(change)
        except Exception:
            for change in reversed(modified):
                replace(change["bp"], change["original"])
            for path in reversed(installed):
                shutil.rmtree(path)
            raise
    return count


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--packages", type=Path, required=True)
    parser.add_argument("--checkout", type=Path, required=True)
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    try:
        count = install(args.packages, args.checkout, args.check_only)
    except (ValueError, OSError) as error:
        parser.exit(2, f"integration error: {error}\n")
    print(f"{'Validated' if args.check_only else 'Installed'} {count} target-library adapters")


if __name__ == "__main__":
    main()
