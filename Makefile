PYTHON ?= python3

.PHONY: check
check:
	$(PYTHON) -m json.tool repo.json > /dev/null
	$(PYTHON) -m json.tool templates/component.json > /dev/null
	$(PYTHON) -c 'import json; from pathlib import Path; config = json.loads(Path("repo.json").read_text()); assert config["pkg_format"] == "debian"; entries = {k: v for k, v in config.items() if k != "pkg_format"}; assert entries; assert all(Path(k).is_dir() and all(v.get(field) for field in ("name", "distribution", "component", "url")) for k, v in entries.items()), "Invalid repository entry or missing recipe directory"'
	$(PYTHON) -c 'from pathlib import Path; import xml.etree.ElementTree as ET; [ET.parse(path) for path in Path("manifests").glob("*.xml")]'
	git diff --check
	git diff --cached --check
