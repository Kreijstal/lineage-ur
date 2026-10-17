import hashlib
import importlib.util
import json
from pathlib import Path
import tempfile
import unittest


def module(name):
    path = Path(__file__).resolve().parents[1] / "lineage/target-libraries" / (name + ".py")
    spec = importlib.util.spec_from_file_location("target_" + name, path)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


class TargetPackageTest(unittest.TestCase):
    def test_source_definition_keeps_existing_defaults(self):
        source = 'cc_library {\n    name: "libz",\n    defaults: ["original"],\n    srcs: ["z.c"],\n}\n'
        updated = module("package").inject_default(source, "libz")
        self.assertEqual(updated.count("defaults:"), 1)
        self.assertIn('"lineage_ur_target_libz", "original"', updated)
        self.assertIn('srcs: ["z.c"]', updated)
        no_defaults = source.replace('    defaults: ["original"],\n', '')
        self.assertEqual(module("package").inject_default(no_defaults, "libz").count("defaults:"), 1)

    def test_guarded_apply_preserves_reference_and_rejects_changes(self):
        apply = module("apply")
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            donor, checkout, packages = root / "reference", root / "experimental", root / "packages"
            (donor / "external/example").mkdir(parents=True)
            (checkout / "external/example").mkdir(parents=True)
            (checkout / "build/soong/cc").mkdir(parents=True)
            (checkout / "build/soong/cc/packaged_target.go").write_text("target support")
            original = b'cc_library { name: "libexample" }\ncc_library { name: "libother" }\n'
            for base in (donor, checkout):
                (base / "external/example/Android.bp").write_bytes(original)
                (base / "external/example/example.c").write_text("original code")
            modified = b'cc_library { name: "libexample", defaults: ["target"] }\ncc_library { name: "libother", defaults: ["other"] }\n'
            overlay = packages / "overlay/external/example"
            overlay.mkdir(parents=True)
            (overlay / "Android.bp").write_bytes(modified)
            digest = lambda raw: hashlib.sha256(raw).hexdigest()
            inventory = {"libraries": []}
            for name in ["libexample", "libother"]:
                package = packages / "packages" / name
                (package / "reference").mkdir(parents=True)
                state = package / "reference/build-state.json"
                state.write_text(json.dumps({"source_root": str(donor)}))
                manifest = {"module": name, "files": {"reference/build-state.json": apply.sha(state)},
                            "inputs": {"external/example/Android.bp": digest(modified),
                                       "external/example/example.c": digest(b"original code")}}
                (package / "package.json").write_text(json.dumps(manifest))
                inventory["libraries"].append({"module": name, "repository": "external/example",
                                              "manifest_sha256": apply.sha(package / "package.json"),
                                              "original_android_bp_sha256": digest(original)})
            (packages / "inventory.json").write_text(json.dumps(inventory))
            with self.assertRaisesRegex(ValueError, "protected reference"):
                apply.install(packages, donor)
            other = packages / "packages/libother/package.json"
            original_manifest = other.read_text()
            conflicting = json.loads(original_manifest)
            conflicting["inputs"]["external/example/example.c"] = digest(b"different dependency version")
            other.write_text(json.dumps(conflicting))
            inventory["libraries"][1]["manifest_sha256"] = apply.sha(other)
            (packages / "inventory.json").write_text(json.dumps(inventory))
            with self.assertRaisesRegex(ValueError, "source/toolchain input differs"):
                apply.install(packages, checkout, True)
            other.write_text(original_manifest)
            inventory["libraries"][1]["manifest_sha256"] = apply.sha(other)
            (packages / "inventory.json").write_text(json.dumps(inventory))
            (checkout / "external/example/example.c").write_text("changed code")
            with self.assertRaisesRegex(ValueError, "source/toolchain input differs"):
                apply.install(packages, checkout)
            self.assertEqual((checkout / "external/example/Android.bp").read_bytes(), original)
            (checkout / "external/example/example.c").write_text("original code")
            self.assertEqual(apply.install(packages, checkout, True), 2)
            self.assertFalse((checkout / "external/example/lineage-ur-target").exists())
            self.assertEqual(apply.install(packages, checkout), 2)
            self.assertEqual((checkout / "external/example/Android.bp").read_bytes(), modified)
            self.assertEqual((donor / "external/example/Android.bp").read_bytes(), original)
            definitions = (checkout / "external/example/lineage-ur-target/Android.bp").read_text()
            self.assertIn('name: "lineage_ur_target_libexample"', definitions)
            self.assertIn('name: "lineage_ur_target_libother"', definitions)
            self.assertEqual(len(list((checkout / "external/example/lineage-ur-target/snapshots").iterdir())), 2)


if __name__ == "__main__":
    unittest.main()
