import hashlib
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import unittest

APPS = Path(__file__).resolve().parents[1] / "lineage/apps"


def module(name):
    # apply.py imports helpers from package.py beside it.
    if str(APPS) not in sys.path:
        sys.path.insert(0, str(APPS))
    spec = importlib.util.spec_from_file_location("apps_" + name, APPS / (name + ".py"))
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def record(module_name, checksum, **overrides):
    result = {"module": module_name, "path": "packages/apps/Example", "manifest_sha256": checksum,
              "apk": module_name + ".apk", "partition_property": "product_specific", "overrides": [],
              "required": [], "auto_generated_rros": [], "uses_libs": [], "optional_uses_libs": []}
    result.update(overrides)
    return result


class AppPackageTest(unittest.TestCase):
    def test_adapter_carries_resolved_app_properties(self):
        text = module("package").adapter(record("Example", "a" * 64, overrides=["Old"],
                                                auto_generated_rros=["Example__p__auto_generated_rro_vendor"],
                                                optional_uses_libs=["androidx.window.extensions"]))
        self.assertIn("android_packaged_app {", text)
        self.assertIn(f'apk: "snapshots/{"a" * 64}/Example.apk"', text)
        self.assertIn(f'package_sha256: "{"a" * 64}"', text)
        self.assertIn("default_dev_cert: true", text)
        self.assertIn("product_specific: true", text)
        self.assertIn('overrides: ["Old"]', text)
        self.assertIn('optional_uses_libs: ["androidx.window.extensions"]', text)
        self.assertIn('auto_generated_rros: ["Example__p__auto_generated_rro_vendor"]', text)
        self.assertNotIn("required:", text)
        self.assertNotIn("uses_libs: []", text)
        system = module("package").adapter(record("Example", "a" * 64, partition_property=None))
        self.assertNotIn("_specific", system)

    def test_uses_libraries_follow_manifest_order(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "AndroidManifest.xml"
            manifest.write_text(
                '<manifest xmlns:android="http://schemas.android.com/apk/res/android"><application>'
                '<uses-library android:name="b.optional" android:required="false"/>'
                '<uses-library android:name="a.required"/>'
                '<uses-library android:name="c.optional" android:required="false"/>'
                '</application></manifest>')
            self.assertEqual(module("package").uses_libraries(manifest),
                             (["a.required"], ["b.optional", "c.optional"]))

    def test_make_entries_select_the_source_app(self):
        makefile = ("include $(CLEAR_VARS)\nLOCAL_MODULE := Example\nLOCAL_SOONG_MODULE_TYPE := android_app_import\n"
                    "include $(CLEAR_VARS)\nLOCAL_MODULE := Example\nLOCAL_SOONG_MODULE_TYPE := android_app\n"
                    "LOCAL_OVERRIDES_PACKAGES := Old\nLOCAL_REQUIRED_MODULES :=\n")
        entry = module("package").make_entries(makefile, "Example")
        self.assertEqual(entry["LOCAL_OVERRIDES_PACKAGES"], "Old")
        self.assertEqual(entry["LOCAL_REQUIRED_MODULES"], "")
        with self.assertRaisesRegex(ValueError, "no android_app entry"):
            module("package").make_entries(makefile, "Missing")

    def test_apply_adds_adapters_and_skips_stale_apps(self):
        apply = module("apply")
        digest = lambda raw: hashlib.sha256(raw).hexdigest()
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            donor, checkout, packages = root / "reference", root / "experimental", root / "packages"
            for base in (donor, checkout):
                for name in ("Example", "Stale"):
                    (base / "packages/apps" / name).mkdir(parents=True)
                    (base / "packages/apps" / name / "Main.java").write_text("class Main {}")
            (checkout / "packages/apps/Stale/Main.java").write_text("class Main { int changed; }")
            (checkout / "build/soong/java").mkdir(parents=True)
            (checkout / "build/soong/java/packaged_app.go").write_text("packaged app support")
            inventory = {"apps": []}
            for name in ("Example", "Stale"):
                package = packages / "packages" / name
                (package / "reference").mkdir(parents=True)
                (package / "reference/build-state.json").write_text(json.dumps({"source_root": str(donor)}))
                (package / (name + ".apk")).write_bytes(b"apk " + name.encode())
                manifest = {"module": name, "apk": name + ".apk",
                            "files": {p.relative_to(package).as_posix(): apply.sha(p)
                                      for p in package.rglob("*") if p.is_file()},
                            "inputs": {f"packages/apps/{name}/Main.java": digest(b"class Main {}")}}
                (package / "package.json").write_text(json.dumps(manifest))
                inventory["apps"].append(record(name, apply.sha(package / "package.json"),
                                                path="packages/apps/" + name))
            (packages / "inventory.json").write_text(json.dumps(inventory))
            reference_before = {p: p.read_bytes() for p in donor.rglob("*") if p.is_file()}
            with self.assertRaisesRegex(ValueError, "protected reference"):
                apply.install(packages, donor)
            ready, stale = apply.install(packages, checkout, check_only=True)
            self.assertEqual([r["module"] for r, _, _ in ready], ["Example"])
            self.assertEqual(stale, [("Stale", ["packages/apps/Stale/Main.java"])])
            self.assertFalse((checkout / "packages/apps/Example/lineage-ur-app").exists())
            apply.install(packages, checkout)
            adapter = checkout / "packages/apps/Example/lineage-ur-app"
            checksum = inventory["apps"][0]["manifest_sha256"]
            self.assertTrue((adapter / "snapshots" / checksum / "Example.apk").is_file())
            self.assertIn('name: "Example"', (adapter / "Android.bp").read_text())
            self.assertFalse((checkout / "packages/apps/Stale/lineage-ur-app").exists())
            # A second installation must not overwrite the existing adapter.
            with self.assertRaisesRegex(ValueError, "already exists"):
                apply.install(packages, checkout)
            # Corrupt package content is rejected before anything is written.
            (adapter).rename(root / "moved")
            (packages / "packages/Example/Example.apk").write_bytes(b"modified")
            with self.assertRaisesRegex(ValueError, "package content mismatch"):
                apply.install(packages, checkout)
            self.assertFalse(adapter.exists())
            self.assertEqual(reference_before, {p: p.read_bytes() for p in donor.rglob("*") if p.is_file()})


if __name__ == "__main__":
    unittest.main()
