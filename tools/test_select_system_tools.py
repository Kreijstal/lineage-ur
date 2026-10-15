import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import unittest

from select_system_tools import prepare


class SelectionTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name)
        self.policy = self.root / "policy.json"
        self.output = self.root / "generated"
        self.config = {"schema_version": 1, "host": "linux_glibc_x86_64", "tools": [{
            "module": "example-tool", "executable": shutil.which("echo"),
            "licenses": ["test_license"],
            "probes": [{"args": ["selector-fixture"], "output_regex": "^selector-fixture\\n$"}],
        }]}

    def run_selection(self, timeout=5):
        self.policy.write_text(json.dumps(self.config))
        return prepare(self.policy, self.output, timeout)["tools"][0]

    def test_select_snapshot_and_stable_repeat(self):
        record = self.run_selection()
        self.assertEqual(record["decision"], "system")
        snapshot = self.output / record["src"]
        self.assertEqual(hashlib.sha256(snapshot.read_bytes()).hexdigest(), record["sha256"])
        self.assertFalse(snapshot.is_symlink())
        self.assertTrue(os.access(snapshot, os.X_OK))
        before = {p: p.stat().st_mtime_ns for p in self.output.rglob("*") if p.is_file()}
        self.assertEqual(record, self.run_selection())
        self.assertEqual(before, {p: p.stat().st_mtime_ns for p in before})
        bp = (self.output / "Android.bp").read_text()
        self.assertIn('system_build_tool {', bp)
        self.assertIn('linux_glibc_x86_64: { enabled: true }', bp)
        self.assertIn('licenses: ["test_license"]', bp)

    def test_missing_tool_falls_back(self):
        self.config["tools"][0]["executable"] = str(self.root / "missing")
        self.assertEqual(self.run_selection()["decision"], "source")
        self.assertIn('src: "unavailable/example-tool"', (self.output / "Android.bp").read_text())

    def test_failed_probe_replaces_stale_selection(self):
        selected = self.run_selection()
        self.config["tools"][0]["probes"][0]["output_regex"] = "incompatible-version"
        self.assertEqual(self.run_selection()["reason"], "compatibility probe failed")
        self.assertNotIn(selected["src"], (self.output / "Android.bp").read_text())

    def test_hash_mismatch_falls_back(self):
        self.config["tools"][0]["sha256"] = "0" * 64
        self.assertEqual(self.run_selection()["reason"], "sha256 mismatch")

    def test_timeout_falls_back(self):
        self.config["tools"][0].update(executable=shutil.which("sleep"),
            probes=[{"args": ["5"], "output_regex": "anything"}])
        self.assertEqual(self.run_selection(0.02)["reason"], "compatibility probe timed out")

    def test_no_shell_interpretation(self):
        marker = self.root / "should-not-exist"
        self.config["tools"][0]["probes"] = [{"args": [f"$(touch {marker})"], "output_regex": "touch"}]
        self.assertEqual(self.run_selection()["decision"], "system")
        self.assertFalse(marker.exists())

    def test_reject_scripts(self):
        script = self.root / "script"
        script.write_text("#!/bin/sh\necho selector-fixture\n")
        script.chmod(0o755)
        self.config["tools"][0]["executable"] = str(script)
        self.assertEqual(self.run_selection()["decision"], "source")

    def test_invalid_policy_is_an_error_before_writes(self):
        baseline = copy.deepcopy(self.config)
        for mutate in [
            lambda c: c["tools"].append(copy.deepcopy(c["tools"][0])),
            lambda c: c["tools"][0].update(module="../escape"),
            lambda c: c["tools"][0].update(executable="relative/path"),
            lambda c: c["tools"][0].update(probes=[]),
            lambda c: c["tools"][0].update(licenses=[]),
            lambda c: c["tools"][0].update(typo=True),
        ]:
            self.config = copy.deepcopy(baseline)
            mutate(self.config)
            with self.assertRaises(ValueError):
                self.run_selection()
            self.assertFalse(self.output.exists())

    def test_preserve_handwritten_android_bp(self):
        self.output.mkdir()
        bp = self.output / "Android.bp"
        bp.write_text("// handwritten\n")
        with self.assertRaisesRegex(ValueError, "refusing to overwrite"):
            self.run_selection()
        self.assertEqual(bp.read_text(), "// handwritten\n")


if __name__ == "__main__":
    unittest.main()
