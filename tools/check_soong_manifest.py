#!/usr/bin/env python3
"""Check that the optional Soong manifest actually selects our recorded fork."""

import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET


def check(root):
    config = json.loads((root / "soong.json").read_text())
    upstream, fork = config["upstream"], config["fork"]
    revision = upstream["revision"]
    if not re.fullmatch(r"[0-9a-f]{40}", revision) or fork["base_revision"] != revision:
        raise ValueError("Soong upstream and fork base revisions must match")
    if config["schema_version"] != 1:
        raise ValueError("Unsupported Soong metadata schema")
    manifest = ET.parse(root / config["integration_manifest"]).getroot()
    if manifest.tag != "manifest":
        raise ValueError("Expected repo manifest")
    removals, projects = manifest.findall("remove-project"), manifest.findall("project")
    if len(removals) != 1 or len(projects) != 1:
        raise ValueError("Expected one removed upstream project and one replacement")
    removed, project = removals[0].attrib, projects[0].attrib
    if removed.get("path") != "build/soong" or project.get("path") != "build/soong":
        raise ValueError("Soong checkout path must remain build/soong")
    if removed.get("base-rev") != revision:
        raise ValueError("Manifest must guard against a changed upstream base")
    if upstream["repository"] != "https://github.com/" + removed.get("name", ""):
        raise ValueError("Removed project does not match the recorded upstream")
    remotes = {remote.attrib["name"]: remote.attrib["fetch"] for remote in manifest.findall("remote")}
    fetch = remotes.get(project.get("remote"), "")
    repository = fetch.rstrip("/") + "/" + project.get("name", "")
    if repository != fork["repository"] or project.get("revision") != fork["branch"]:
        raise ValueError("Manifest remote, project name or branch does not select the recorded fork")
    return f"Soong manifest selects {repository}@{fork['branch']} from {revision}"


if __name__ == "__main__":
    try:
        print(check(Path(__file__).resolve().parents[1]))
    except (OSError, ValueError, KeyError, TypeError, ET.ParseError) as error:
        print(f"Soong metadata: {error}", file=sys.stderr)
        sys.exit(1)
