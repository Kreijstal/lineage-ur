import importlib.util
import json
from pathlib import Path
import subprocess
import tempfile
import unittest

UPDATE = Path(__file__).resolve().parents[1] / "lineage/update/update.py"


def module():
    spec = importlib.util.spec_from_file_location("lineage_update", UPDATE)
    result = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(result)
    return result


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True, text=True).stdout.strip()


class UpdateTest(unittest.TestCase):
    def test_tracked_projects_resolve_refs_and_skip_notdefault(self):
        with tempfile.TemporaryDirectory() as temporary:
            manifest = Path(temporary) / "pinned.xml"
            manifest.write_text(
                '<manifest><remote name="aosp" fetch="https://android.googlesource.com" revision="refs/tags/t1"/>'
                '<remote name="github" fetch=".."/><default remote="github" revision="refs/heads/lineage-23.2"/>'
                '<project name="LineageOS/a" path="a" revision="1" upstream="refs/heads/lineage-23.2"/>'
                '<project name="platform/b" path="b" remote="aosp" revision="2"/>'
                '<project name="LineageOS/c" revision="3"/>'
                '<project name="LineageOS/wiki" path="wiki" revision="4" groups="notdefault"/></manifest>')
            self.assertEqual(module().tracked_projects(manifest), [
                ("a", "https://github.com/LineageOS/a", "refs/heads/lineage-23.2", "1"),
                ("b", "https://android.googlesource.com/platform/b", "refs/tags/t1", "2"),
                ("LineageOS/c", "https://github.com/LineageOS/c", "refs/heads/lineage-23.2", "3")])

    def test_remote_head_dereferences_annotated_tags(self):
        with tempfile.TemporaryDirectory() as temporary:
            repo = Path(temporary) / "repo"
            repo.mkdir()
            git(repo, "init", "-q", "-b", "main")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "commit", "-q", "--allow-empty", "-m", "one")
            commit = git(repo, "rev-parse", "HEAD")
            git(repo, "-c", "user.name=t", "-c", "user.email=t@t", "tag", "-a", "-m", "tag", "t1")
            self.assertNotEqual(git(repo, "rev-parse", "t1"), commit)
            update = module()
            self.assertEqual(update.remote_head(str(repo), "refs/tags/t1"), commit)
            self.assertEqual(update.remote_head(str(repo), "refs/heads/main"), commit)
            self.assertIsNone(update.remote_head(str(repo), "refs/heads/missing"))

    def test_moved_recipe_repositories_are_reported(self):
        changed = [{"path": "packages/apps/DeskClock"}, {"path": "external/zlib"}, {"path": "vendor/apn"}]
        self.assertEqual(module().affected_packages(changed), ["DeskClock", "libz"])

    def test_config_paths_resolve_and_stages_are_ordered(self):
        update = module()
        config = update.load_config(UPDATE.with_name("config.json"))
        self.assertTrue(config["baseline_manifest"].is_file())
        self.assertTrue((UPDATE.parent / config["local_manifest"]).is_file())
        for patch in config["patches"].values():
            self.assertTrue((UPDATE.parent / patch).is_file())
        self.assertEqual(update.STAGES, ("sync", "soong", "build", "export", "validate", "publish"))
        for modules in config["target_libraries"].values():
            known = {r["module"] for r in json.loads((UPDATE.parents[1] / "target-libraries/recipes.json")
                                                     .read_text())["libraries"]}
            self.assertLessEqual(set(modules), known)


if __name__ == "__main__":
    unittest.main()
