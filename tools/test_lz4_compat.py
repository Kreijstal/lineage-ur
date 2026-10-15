import copy
import json
from pathlib import Path
import shutil
import tempfile
import unittest

from lz4_compat import check, Lz4CompatibilityError
from select_system_tools import prepare


class Lz4CompatibilityTest(unittest.TestCase):
    def test_non_lz4_rejected(self):
        with self.assertRaises(Lz4CompatibilityError):
            check(shutil.which("echo"))

    def test_profile_failure_falls_back_after_successful_version_probe(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = {"schema_version": 1, "host": "linux_glibc_x86_64", "tools": [{
                "module": "lz4", "executable": shutil.which("echo"), "licenses": ["fixture_license"],
                "compatibility": "android-lz4", "probes": [{"args": ["fake-version"], "output_regex": "fake-version"}],
            }]}
            path = root / "policy.json"
            path.write_text(json.dumps(policy))
            record = prepare(path, root / "output")["tools"][0]
            self.assertEqual(record["decision"], "source")
            self.assertIn("compatibility failed", record["reason"])
            self.assertIn('src: "unavailable/lz4"', (root / "output/Android.bp").read_text())

    @unittest.skipUnless(shutil.which("lz4"), "install lz4 to run native compatibility checks")
    def test_installed_lz4_selected_with_functional_report(self):
        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary)
            policy = json.loads((Path(__file__).parents[1] / "policies/lz4.json").read_text())
            policy["tools"][0]["executable"] = shutil.which("lz4")
            path = root / "policy.json"
            path.write_text(json.dumps(policy))
            record = prepare(path, root / "output")["tools"][0]
            self.assertEqual(record["decision"], "system", record)
            self.assertEqual(len(record["compatibility"]["cases"]), 12)
            self.assertTrue(record["compatibility"]["corrupt_frame_rejected"])
            # Repeat selection with a missing candidate must remove the stale
            # successful adapter path, leaving source fallback in the graph.
            policy = copy.deepcopy(policy)
            policy["tools"][0]["executable"] = str(root / "missing-lz4")
            path.write_text(json.dumps(policy))
            self.assertEqual(prepare(path, root / "output")["tools"][0]["decision"], "source")
            self.assertNotIn(record["src"], (root / "output/Android.bp").read_text())


if __name__ == "__main__":
    unittest.main()
