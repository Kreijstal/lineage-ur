#!/usr/bin/env python3
"""Prepare an overlay with adapters under each component's original directory."""

import argparse
import json
import os
from pathlib import Path
import sys
import tempfile

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from select_host_libraries import prepare


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--policy", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True, help="new overlay directory, not the live Android checkout")
    args = parser.parse_args()
    output = args.output.resolve()
    if output.exists():
        parser.error("overlay output already exists; choose a new directory")
    # Never interpret a source checkout as a destination for an overlay.
    if any((path / ".repo").exists() for path in (output, *output.parents)):
        parser.error("prepare outside Android; apply only to a separate idle checkout")
    recipes = json.loads(Path(__file__).with_name("recipes.json").read_text())["libraries"]
    output.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".host-library-overlay-", dir=output.parent) as temporary:
        stage = Path(temporary) / "overlay"
        stage.mkdir()
        records = []
        for recipe in recipes:
            destination = Path(recipe["repository"]) / "lineage-ur-generated"
            lock = prepare(args.policy, stage / destination, modules=[recipe["module"]])
            record = lock["libraries"][0]
            if record["decision"] != "package":
                parser.error(f"{recipe['module']}: package unavailable: {record.get('reason')}")
            records.append(record | {"adapter_directory": str(destination)})
        (stage / "overlay.json").write_text(json.dumps({"libraries": records}, indent=2) + "\n")
        os.rename(stage, output)
    print(f"Prepared {len(records)} adapters under {output}")


if __name__ == "__main__":
    main()
