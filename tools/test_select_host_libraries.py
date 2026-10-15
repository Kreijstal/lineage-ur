import copy
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile
import unittest

from select_host_libraries import prepare


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class HostLibraryTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.fixture.cleanup)
        cls.base = Path(cls.fixture.name)
        (cls.base / "include").mkdir()
        (cls.base / "include/reuse.h").write_text("int reusable_answer(void);\n")
        (cls.base / "reuse.c").write_text("int reusable_answer(void) { return 42; }\n")
        subprocess.run(["cc", "-fPIC", "-c", str(cls.base / "reuse.c"), "-o", str(cls.base / "reuse.o")], check=True)
        subprocess.run(["ar", "rcs", str(cls.base / "libreuse.a"), str(cls.base / "reuse.o")], check=True)
        subprocess.run(["cc", "-shared", "-Wl,-soname,libreuse.so", str(cls.base / "reuse.o"), "-o", str(cls.base / "libreuse.so")], check=True)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.package = self.root / "package"
        shutil.copytree(self.base, self.package)
        self.output = self.root / "generated"
        self.manifest = {
            "schema_version": 1, "module": "libreuse", "host": "linux_glibc_x86_64",
            "source_revision": "fixture-v1", "toolchain": "native C fixture compiler",
            "configuration": "C API, PIC, no LTO", "static": "libreuse.a", "shared": "libreuse.so",
            "files": {p: sha(self.package / p) for p in ("libreuse.a", "libreuse.so", "include/reuse.h")},
            "include_dirs": ["include"], "dependencies": {},
        }
        self.policy_path = self.root / "policy.json"
        self.policy = {"schema_version": 1, "host": "linux_glibc_x86_64", "libraries": []}
        self.update_manifest()

    def update_manifest(self):
        manifest = self.package / "package.json"
        manifest.write_text(json.dumps(self.manifest))
        self.policy["libraries"] = [{"module": "libreuse", "manifest": "package/package.json",
                                    "sha256": sha(manifest), "licenses": ["test_license"]}]

    def run_selection(self):
        self.policy_path.write_text(json.dumps(self.policy))
        return prepare(self.policy_path, self.output)["libraries"][0]

    def test_real_static_and_shared_consumers(self):
        record = self.run_selection()
        self.assertEqual(record["decision"], "package")
        snapshot = self.output / record["snapshot"]
        src = self.root / "consumer.c"
        src.write_text('#include "reuse.h"\nint main(void) { return reusable_answer() != 42; }\n')
        for kind, library in (("static", "libreuse.a"), ("shared", "libreuse.so")):
            exe = self.root / ("consumer-" + kind)
            subprocess.run(["cc", str(src), "-I", str(snapshot / "include"), str(snapshot / library),
                            "-Wl,-rpath," + str(snapshot), "-o", str(exe)], check=True)
            subprocess.run([str(exe)], check=True)
        bp = (self.output / "Android.bp").read_text()
        self.assertIn("cc_packaged_library_host", bp)
        self.assertIn("export_include_dirs", bp)
        self.assertIn("package_files", bp)

    def test_missing_and_corrupt_inputs_fall_back(self):
        self.run_selection()
        for filename in ("include/reuse.h", "libreuse.a", "libreuse.so"):
            with self.subTest(filename=filename):
                original = (self.package / filename).read_bytes()
                (self.package / filename).unlink()
                self.assertEqual(self.run_selection()["decision"], "source")
                (self.package / filename).write_bytes(original + b"corrupt")
                self.assertEqual(self.run_selection()["decision"], "source")
                (self.package / filename).write_bytes(original)

    def test_manifest_pin_and_identity(self):
        self.policy["libraries"][0]["sha256"] = "0" * 64
        self.assertEqual(self.run_selection()["decision"], "source")
        self.manifest["host"] = "android_arm64"
        self.update_manifest()
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_dependency_closure_and_version_pin(self):
        dep_dir = self.root / "dep"
        shutil.copytree(self.package, dep_dir)
        dep = copy.deepcopy(self.manifest)
        dep["module"] = "libdep"
        del dep["shared"]
        del dep["files"]["libreuse.so"]
        (dep_dir / "package.json").write_text(json.dumps(dep))
        requirement = {"sha256": sha(dep_dir / "package.json"), "linkage": "static", "reexport_headers": True}
        self.manifest["dependencies"]["libdep"] = requirement
        self.update_manifest()
        self.policy["libraries"].append({"module": "libdep", "manifest": "dep/package.json", "sha256": requirement["sha256"], "licenses": ["test_license"]})
        self.assertEqual(self.run_selection()["decision"], "package")
        bp = (self.output / "Android.bp").read_text()
        self.assertIn('static_libs: ["libdep"]', bp)
        self.assertIn('export_static_lib_headers: ["libdep"]', bp)
        self.assertIn("snapshots/libdep-", bp.split("cc_packaged_library_host")[1])
        (dep_dir / "include/reuse.h").unlink()
        self.assertEqual(self.run_selection()["decision"], "source")
        self.policy["libraries"][1]["sha256"] = "0" * 64
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_path_escape_rejected(self):
        self.manifest["files"]["../outside"] = "0" * 64
        self.update_manifest()
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_thin_archive_rejected(self):
        (self.package / "libreuse.a").write_bytes(b"!<thin>\n")
        self.manifest["files"]["libreuse.a"] = sha(self.package / "libreuse.a")
        self.update_manifest()
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_wrong_architecture_archive_rejected(self):
        path = self.package / "libreuse.a"
        payload = bytearray(path.read_bytes())
        elf = payload.index(b"\x7fELF")
        payload[elf + 18:elf + 20] = b"\xb7\x00"  # AArch64
        path.write_bytes(payload)
        self.manifest["files"]["libreuse.a"] = sha(path)
        self.update_manifest()
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_soname_mismatch_rejected(self):
        subprocess.run(["cc", "-shared", "-Wl,-soname,libreuse.so.1", str(self.package / "reuse.o"), "-o", str(self.package / "libreuse.so")], check=True)
        self.manifest["files"]["libreuse.so"] = sha(self.package / "libreuse.so")
        self.update_manifest()
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_invalid_policy_and_existing_bp_preserved(self):
        self.output.mkdir()
        bp = self.output / "Android.bp"
        bp.write_text("// handwritten\n")
        with self.assertRaises(ValueError):
            self.run_selection()
        self.assertEqual(bp.read_text(), "// handwritten\n")
        self.policy["libraries"].append(copy.deepcopy(self.policy["libraries"][0]))
        with self.assertRaises(ValueError):
            self.run_selection()

    def test_identical_selection_preserves_timestamps(self):
        self.run_selection()
        before = {p: p.stat().st_mtime_ns for p in self.output.rglob("*") if p.is_file()}
        self.run_selection()
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})


if __name__ == "__main__":
    unittest.main()
