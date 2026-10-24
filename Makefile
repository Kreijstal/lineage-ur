PYTHON ?= python3
BORINGSSL_SELECTION ?= artifacts/boringssl-host-selection
BORINGSSL_REFERENCE_OUT ?=
HOST_LIBRARIES_SELECTION ?= artifacts/host-libraries-selection
HOST_LIBRARIES_REFERENCE_OUT ?=
TARGET_SOURCE_ROOT ?=
TARGET_SOONG_ROOT ?= ../android_build_soong
TARGET_PACKAGES ?= artifacts/target-libraries-r8q-v2
TARGET_QEMU ?= artifacts/qemu-user/usr/bin/qemu-aarch64
TARGET_RUNTIME_OUT ?= artifacts/target-libraries-runtime-v2
TARGET_GRAPHICS_PACKAGES ?= artifacts/target-libraries-r8q-graphics-tracing
TARGET_GRAPHICS_RUNTIME_OUT ?= artifacts/target-graphics-tracing-runtime

.PHONY: check-graphics-tracing
check-graphics-tracing:
	$(MAKE) check-target-libraries TARGET_PACKAGES="$(TARGET_GRAPHICS_PACKAGES)" TARGET_RUNTIME_OUT="$(TARGET_GRAPHICS_RUNTIME_OUT)"

.PHONY: check-target-libraries
check-target-libraries:
	$(PYTHON) -m py_compile lineage/target-libraries/package.py lineage/target-libraries/apply.py lineage/target-libraries/check.py
	$(PYTHON) -m json.tool lineage/target-libraries/recipes.json > /dev/null
	$(PYTHON) -m unittest discover -s tools -p test_target_packages.py -v
	$(PYTHON) tools/test_soong.py --source-root "$(TARGET_SOURCE_ROOT)" --soong-root "$(TARGET_SOONG_ROOT)" --out-dir artifacts/soong-target-tests --target-overlay "$(TARGET_PACKAGES)/overlay" --run '^(TestPackagedTarget.*|TestTargetPackage.*)$$'
	$(PYTHON) lineage/target-libraries/check.py --source-root "$(TARGET_SOURCE_ROOT)" --packages "$(TARGET_PACKAGES)" --qemu "$(TARGET_QEMU)" --output "$(TARGET_RUNTIME_OUT)"

.PHONY: check-host-libraries
check-host-libraries:
	$(PYTHON) -m py_compile lineage/host-libraries/export.py lineage/host-libraries/jpeg.py lineage/host-libraries/prepare.py lineage/host-libraries/check.py
	$(PYTHON) -m json.tool lineage/host-libraries/recipes.json > /dev/null
	$(PYTHON) -m unittest discover -s tools -p test_select_host_libraries.py -v
	$(PYTHON) lineage/host-libraries/check.py --selection "$(HOST_LIBRARIES_SELECTION)" $(if $(HOST_LIBRARIES_REFERENCE_OUT),--reference-out "$(HOST_LIBRARIES_REFERENCE_OUT)")

.PHONY: check-boringssl
check-boringssl:
	$(PYTHON) -m py_compile lineage/boringssl/export.py lineage/boringssl/check.py
	$(PYTHON) -m unittest discover -s tools -p test_select_host_libraries.py -v
	$(PYTHON) lineage/boringssl/check.py --selection "$(BORINGSSL_SELECTION)" $(if $(BORINGSSL_REFERENCE_OUT),--reference-out "$(BORINGSSL_REFERENCE_OUT)")

.PHONY: check
check:
	$(PYTHON) -m py_compile lineage/swiftshader/import_termux.py lineage/termux-libraries/prepare.py lineage/termux-libraries/check.py
	$(PYTHON) -m py_compile lineage/apps/package.py lineage/apps/apply.py
	$(PYTHON) -m json.tool lineage/apps/recipes.json > /dev/null
	$(PYTHON) -m json.tool lineage/termux-libraries/recipes.json > /dev/null
	$(PYTHON) -m json.tool lineage/termux-libraries/termux-aarch64.lock.json > /dev/null
	$(PYTHON) -m json.tool repo.json > /dev/null
	$(PYTHON) -m json.tool soong.json > /dev/null
	$(PYTHON) -m json.tool templates/component.json > /dev/null
	$(PYTHON) -m json.tool templates/host-library-package.json > /dev/null
	$(PYTHON) -c 'from tools.select_host_libraries import load_policy; load_policy("templates/host-library-policy.json")'
	$(PYTHON) -c 'import json; from pathlib import Path; config = json.loads(Path("repo.json").read_text()); assert config["pkg_format"] == "debian"; entries = {k: v for k, v in config.items() if k != "pkg_format"}; assert entries; assert all(Path(k).is_dir() and all(v.get(field) for field in ("name", "distribution", "component", "url")) for k, v in entries.items()), "Invalid repository entry or missing recipe directory"'
	$(PYTHON) -c 'from pathlib import Path; import xml.etree.ElementTree as ET; [ET.parse(path) for path in Path("manifests").glob("*.xml")]'
	$(PYTHON) tools/check_soong_manifest.py
	$(PYTHON) -c 'from pathlib import Path; from tools.select_system_tools import load_policy; [load_policy(p) for p in Path("policies").glob("*.json")]'
	$(PYTHON) -m unittest discover -s tools -p 'test_*.py' -v
	git diff --check
	git diff --cached --check

.PHONY: check-pocket-images
check-pocket-images:
	$(PYTHON) -m py_compile lineage/pocket-images/package.py
	$(PYTHON) -m unittest discover -s tools -p test_pocket_images.py -v
