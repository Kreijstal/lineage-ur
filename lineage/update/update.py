#!/usr/bin/env python3
"""Rebuild and republish the r8q packages when LineageOS moves.

`check` compares upstream branch heads with the pinned baseline manifest.
`run` syncs a private workspace checkout, merges upstream Soong into the fork,
builds the product, re-exports the app and target-library packages, validates
them in a hard-linked copy and, with --publish, pushes the fork, commits the new
pins and creates a GitHub release. `daemon` repeats `run --publish` on a timer.
A failed stage leaves its run directory for `run --resume`.
"""

import argparse
import concurrent.futures
import datetime
import fcntl
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import time
import xml.etree.ElementTree as ET

ROOT = Path(__file__).resolve().parents[2]
HERE = Path(__file__).resolve().parent
STAGES = ("sync", "soong", "build", "export", "validate", "publish")


def sha(path):
    result = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            result.update(block)
    return result.hexdigest()


def load_config(path):
    config = json.loads(Path(path).read_text())
    for key in ("baseline_manifest", "repo_tool", "ccache_dir", "workspace", "runs"):
        config[key] = (ROOT / config[key]).resolve()
    config["soong"]["fork"] = (ROOT / config["soong"]["fork"]).resolve()
    return config


def log(message):
    print(f"[{datetime.datetime.now().isoformat(timespec='seconds')}] {message}", flush=True)


def run(command, cwd=None, env=None, logfile=None, capture=False):
    """Run a command; long build steps stream into their own log file."""
    log("$ " + " ".join(map(str, command)) + (f"  (log: {logfile})" if logfile else ""))
    env = os.environ | (env or {}) | {"GIT_TERMINAL_PROMPT": "0"}
    if capture:
        return subprocess.run(command, cwd=cwd, env=env, check=True, text=True, stdout=subprocess.PIPE).stdout
    if logfile:
        with open(logfile, "a") as stream:
            result = subprocess.run(command, cwd=cwd, env=env, stdout=stream, stderr=subprocess.STDOUT)
        if result.returncode:
            raise RuntimeError(f"{command[0]} failed ({result.returncode}); see {logfile}")
        return None
    subprocess.run(command, cwd=cwd, env=env, check=True)
    return None


def git(repo, *args):
    return run(["git", "-C", str(repo), *args], capture=True).strip()


# Upstream comparison ---------------------------------------------------------

def tracked_projects(manifest_path):
    """Synced projects of a `repo manifest -r` file: (path, url, tracked ref, pinned revision)."""
    root = ET.parse(manifest_path).getroot()
    remotes = {r.get("name"): r for r in root.iter("remote")}
    default = root.find("default")
    projects = []
    for project in root.iter("project"):
        if "notdefault" in (project.get("groups") or "").split(","):
            continue
        remote = remotes[project.get("remote") or default.get("remote")]
        fetch = remote.get("fetch")
        base = "https://github.com" if fetch == ".." else fetch.rstrip("/")
        ref = (project.get("upstream") or project.get("dest-branch") or remote.get("revision")
               or default.get("revision"))
        projects.append((project.get("path") or project.get("name"), f"{base}/{project.get('name')}",
                         ref, project.get("revision")))
    return projects


def remote_head(url, ref):
    """Commit a branch or (annotated) tag points to, or None if unreachable."""
    for _ in range(3):
        result = subprocess.run(["git", "ls-remote", url, ref, ref + "^{}"], capture_output=True, text=True,
                                timeout=120, env=os.environ | {"GIT_TERMINAL_PROMPT": "0"})
        if result.returncode == 0:
            refs = dict(reversed(line.split("\t")) for line in result.stdout.splitlines())
            short = ref.removeprefix("refs/heads/").removeprefix("refs/tags/")
            for name in (ref + "^{}", ref, "refs/tags/" + short + "^{}", "refs/tags/" + short, "refs/heads/" + short):
                if name in refs:
                    return refs[name]
            return None
        time.sleep(5)
    return None


def published(config, relative):
    """A file as of origin/main, where publish commits new pins; the local copy if it isn't there yet."""
    fetched = subprocess.run(["git", "-C", str(ROOT), "fetch", "-q", "origin", "main"], capture_output=True)
    shown = subprocess.run(["git", "-C", str(ROOT), "show", "origin/main:" + relative], capture_output=True)
    if fetched.returncode == 0 and shown.returncode == 0:
        return shown.stdout
    return (ROOT / relative).read_bytes()


def compare(config):
    baseline = config["runs"].parent / "baseline-manifest.xml"
    baseline.parent.mkdir(parents=True, exist_ok=True)
    baseline.write_bytes(published(config, config["baseline_manifest"].relative_to(ROOT).as_posix()))
    projects = tracked_projects(baseline)
    with concurrent.futures.ThreadPoolExecutor(32) as pool:
        heads = list(pool.map(lambda p: remote_head(p[1], p[2]), projects))
    changed = [{"path": p[0], "from": p[3], "to": head} for p, head in zip(projects, heads) if head and head != p[3]]
    unresolved = [p[0] for p, head in zip(projects, heads) if not head]
    soong = json.loads(published(config, "soong.json"))
    soong_head = remote_head(config["soong"]["upstream_url"], "refs/heads/" + config["soong"]["upstream_branch"])
    report = {"checked_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(timespec="seconds"),
              "projects": len(projects), "changed": changed, "unresolved": unresolved,
              "soong_upstream": {"pinned": soong["upstream"]["revision"], "head": soong_head}}
    report["key"] = hashlib.sha256(json.dumps([changed, soong_head], sort_keys=True).encode()).hexdigest()
    return report


def affected_packages(changed):
    """Recipe modules whose own repository moved (others may still be stale through shared inputs)."""
    paths = {c["path"] for c in changed}
    result = []
    for recipes, key in ((ROOT / "lineage/apps/recipes.json", "apps"),
                         (ROOT / "lineage/target-libraries/recipes.json", "libraries")):
        result += [r["module"] for r in json.loads(recipes.read_text())[key] if r["repository"] in paths]
    return result


# Pipeline stages -------------------------------------------------------------

class Run:
    def __init__(self, config, directory, publish):
        self.config, self.dir, self.publish = config, directory, publish
        self.state_path = directory / "state.json"
        self.state = json.loads(self.state_path.read_text())
        self.ws = config["workspace"]

    def save(self):
        temporary = self.state_path.with_suffix(".tmp")
        temporary.write_text(json.dumps(self.state, indent=2) + "\n")
        temporary.replace(self.state_path)

    def logfile(self, name):
        return self.dir / "logs" / (name + ".log")

    def android(self, script, logname, extra_env=None):
        """Run a shell snippet after envsetup/lunch in a checkout."""
        body = f'source build/envsetup.sh >/dev/null && lunch {self.config["lunch"]} && {script}'
        run(["bash", "-c", body], cwd=extra_env.pop("_cwd") if extra_env and "_cwd" in extra_env else self.ws,
            env=(extra_env or {}) | {"LANG": "C.UTF-8", "LC_ALL": "C.UTF-8"}, logfile=self.logfile(logname))

    def execute(self):
        for stage in STAGES:
            if stage in self.state["done"]:
                continue
            if stage == "publish" and not self.publish:
                self.state["status"] = "validated"
                self.save()
                log("validation passed; rerun with --resume and --publish to release")
                return
            self.state["stage"], self.state["status"] = stage, "running"
            self.state.pop("error", None)
            self.save()
            log("stage " + stage)
            getattr(self, "stage_" + stage)()
            self.state["done"].append(stage)
            self.save()
        self.state["status"] = "complete"
        self.save()

    # sync: a private shallow repo client. Git can't borrow objects from the
    # shallow reference checkout ("Failed to traverse parents"), so it fetches.
    def stage_sync(self):
        repo, ws = str(self.config["repo_tool"]), self.ws
        ws.mkdir(parents=True, exist_ok=True)
        if not (ws / ".repo/manifests.git/HEAD").is_file():
            shutil.rmtree(ws / ".repo", ignore_errors=True)
            run([repo, "init", "-u", self.config["manifest_url"], "-b", self.config["branch"], "--git-lfs",
                 "--no-clone-bundle", "--depth=1"], cwd=ws, logfile=self.logfile("sync"))
        (ws / ".repo/local_manifests").mkdir(exist_ok=True)
        shutil.copy2(HERE / self.config["local_manifest"], ws / ".repo/local_manifests" / self.config["local_manifest"])
        for path, patch in self.config["patches"].items():
            # A previously applied build patch would make repo refuse to update the project.
            if (ws / path).is_dir() and subprocess.run(["git", "-C", str(ws / path), "apply", "--reverse", "--check",
                                                         str(HERE / patch)], capture_output=True).returncode == 0:
                run(["git", "-C", str(ws / path), "apply", "--reverse", str(HERE / patch)])
        run([repo, "sync", "-c", "--no-clone-bundle", "--no-tags", "--optimized-fetch", "--retry-fetches=3",
             "--force-sync", "-j" + str(self.config["sync_jobs"])], cwd=ws, logfile=self.logfile("sync"))
        self.pull_lfs(repo)
        run([repo, "manifest", "-r", "-o", str(self.dir / "manifest-pinned.xml")], cwd=ws, logfile=self.logfile("sync"))
        for path, patch in self.config["patches"].items():
            run(["git", "-C", str(ws / path), "apply", str(HERE / patch)])
        pinned = ET.parse(self.dir / "manifest-pinned.xml").getroot()
        revisions = {p.get("path") or p.get("name"): p.get("revision") for p in pinned.iter("project")}
        (self.dir / "recipes").mkdir(exist_ok=True)
        for name, key in (("apps", "apps"), ("target-libraries", "libraries")):
            recipes = json.loads((ROOT / "lineage" / name / "recipes.json").read_text())
            for recipe in recipes[key]:
                recipe["revision"] = revisions[recipe["repository"]]
            (self.dir / "recipes" / (name + ".json")).write_text(json.dumps(recipes, indent=2) + "\n")

    def pull_lfs(self, repo):
        """repo leaves Git LFS files (e.g. the WebView APKs) as pointers; fetch them and refuse leftovers."""
        allowed = set(self.config["lfs_pointers_allowed"])
        left = []
        for path in run([repo, "list", "-p"], cwd=self.ws, capture=True).split():
            project = self.ws / path
            if not subprocess.run(["git", "-C", str(project), "lfs", "ls-files", "-n"],
                                  capture_output=True, text=True).stdout.strip():
                continue
            run(["git", "-C", str(project), "lfs", "install", "--local"], logfile=self.logfile("sync"))
            run(["git", "-C", str(project), "lfs", "pull"], logfile=self.logfile("sync"))
            # `git lfs ls-files` marks files still checked out as pointers with "-".
            for line in git(project, "lfs", "ls-files").splitlines():
                oid, mark, name = line.split(" ", 2)
                if mark == "-" and f"{path}/{name}" not in allowed:
                    left.append(f"{path}/{name}")
        if left:
            raise RuntimeError("Git LFS pointers were not replaced: " + ", ".join(left))

    # soong: merge upstream into the fork in a private worktree, test, check out in the workspace.
    def stage_soong(self):
        soong = self.config["soong"]
        fork, tree = soong["fork"], self.dir / "soong"
        git(fork, "fetch", "--no-tags", soong["upstream_url"], soong["upstream_branch"])
        upstream = git(fork, "rev-parse", "FETCH_HEAD")
        base = git(fork, "rev-parse", "refs/heads/" + soong["branch"])
        if not tree.exists():
            git(fork, "worktree", "add", "--detach", str(tree), base)
        if subprocess.run(["git", "-C", str(tree), "merge-base", "--is-ancestor", upstream, "HEAD"]).returncode:
            merged = subprocess.run(["git", "-C", str(tree), "merge", "--no-edit", "-m",
                                     f"Merge LineageOS {soong['upstream_branch']} {upstream[:12]}", upstream],
                                    capture_output=True, text=True)
            if merged.returncode:
                conflicts = git(tree, "diff", "--name-only", "--diff-filter=U").split()
                subprocess.run(["git", "-C", str(tree), "merge", "--abort"])
                raise RuntimeError("upstream Soong conflicts with the fork in: " + ", ".join(conflicts or ["?"]))
        self.state["soong"] = {"upstream": upstream, "base": base, "revision": git(tree, "rev-parse", "HEAD")}
        self.save()
        run([sys.executable, str(ROOT / "tools/test_soong.py"), "--source-root", str(self.ws), "--soong-root", str(tree),
             "--out-dir", str(self.dir / "soong-tests")], cwd=ROOT, logfile=self.logfile("soong-tests"))
        run(["git", "-C", str(self.ws / "build/soong"), "fetch", "--no-tags", str(tree), "HEAD"])
        run(["git", "-C", str(self.ws / "build/soong"), "checkout", "--detach", self.state["soong"]["revision"]])

    def stage_build(self):
        free = shutil.disk_usage(self.ws).free / 2**30
        # A build from scratch writes about 140 GiB; later builds reuse out/.
        needed = self.config["min_free_gib" if not (self.ws / "out/soong").is_dir() else "min_free_gib_incremental"]
        if free < needed:
            raise RuntimeError(f"only {free:.0f} GiB free; need {needed} GiB to build")
        ccache = self.config["ccache_dir"]
        ccache.mkdir(parents=True, exist_ok=True)
        env = {"USE_CCACHE": "1", "CCACHE_EXEC": shutil.which("ccache") or "", "CCACHE_DIR": str(ccache),
               "CCACHE_MAXSIZE": "30G"}
        self.android(f'm -j{self.config["build_jobs"]} {self.config["build_target"]}', "build", env)
        (self.dir / "build-state.json").write_text(json.dumps({
            "updated_utc": datetime.datetime.now(datetime.timezone.utc).isoformat(), "status": "complete",
            "stage": "complete", "exit_code": 0, "source_root": str(self.ws), "branch": self.config["branch"],
            "device": self.config["device"], "lunch": self.config["lunch"]}, indent=2) + "\n")

    def context(self, app):
        variables = self.ws / "out/soong" / ("soong." + self.config["product"] + ".variables")
        output = run([sys.executable, str(ROOT / "tools/test_soong.py"), "--source-root", str(self.ws),
                      "--soong-root", str(self.dir / "soong"), "--out-dir", str(self.dir / "soong-tests"),
                      "--context-variables", str(variables), "--context-out-dir", "out",
                      *(["--context-source-dir", str(self.ws)] if app else [])], cwd=ROOT, capture=True)
        return re.findall(r"\b[0-9a-f]{64}\b", output)[-1]

    def stage_export(self):
        packages = self.dir / "packages"
        if packages.exists():
            shutil.rmtree(packages)
        packages.mkdir()
        self.state["context"] = {"apps": self.context(True), "target": self.context(False)}
        self.save()
        common = ["--source-root", str(self.ws), "--reference-out", str(self.ws / "out"), "--product",
                  self.config["product"], "--build-state", str(self.dir / "build-state.json"),
                  "--reference-manifest", str(self.dir / "manifest-pinned.xml")]
        run([sys.executable, str(ROOT / "lineage/apps/package.py"), *common, "--context", self.state["context"]["apps"],
             "--recipes", str(self.dir / "recipes/apps.json"), "--output", str(packages / "apps-r8q")],
            cwd=ROOT, logfile=self.logfile("export"))
        for name, modules in self.config["target_libraries"].items():
            run([sys.executable, str(ROOT / "lineage/target-libraries/package.py"), *common,
                 "--context", self.state["context"]["target"], "--recipes", str(self.dir / "recipes/target-libraries.json"),
                 "--output", str(packages / name), *[a for m in modules for a in ("--module", m)]],
                cwd=ROOT, logfile=self.logfile("export"))

    def stage_validate(self):
        copy = self.dir / "validate"
        if copy.exists():
            shutil.rmtree(copy)
        copy.mkdir()
        # Hard links: the packaged build only adds adapter directories and writes into its own out/.
        for entry in self.ws.iterdir():
            if entry.name != ".repo" and not entry.name.startswith("out"):
                run(["cp", "-al", str(entry), str(copy / entry.name)])
        packages = self.dir / "packages"
        run([sys.executable, str(ROOT / "lineage/apps/apply.py"), "--packages", str(packages / "apps-r8q"),
             "--checkout", str(copy)], cwd=ROOT, logfile=self.logfile("validate"))
        apps = json.loads((packages / "apps-r8q/inventory.json").read_text())["apps"]
        targets = {a["module"]: f'out/soong/.intermediates/{a["path"]}/lineage-ur-app/prebuilt_{a["module"]}'
                                f'/android_common/signed/{a["module"]}.apk' for a in apps}
        self.android("LINEAGE_USE_PACKAGED_APPS=true m -j16 " + " ".join(targets.values()), "validate",
                     {"_cwd": copy})
        identical = {}
        for app in apps:
            source = self.ws / f'out/soong/.intermediates/{app["path"]}/{app["module"]}/android_common/{app["module"]}.apk'
            identical[app["module"]] = sha(copy / targets[app["module"]]) == sha(source)
        self.state["apps_identical"] = identical
        self.save()
        if not all(identical.values()):
            raise RuntimeError("packaged APKs differ from source builds: " +
                               ", ".join(m for m, same in identical.items() if not same))
        for name in self.config["target_libraries"]:
            run(["make", "check-target-libraries", f"TARGET_SOURCE_ROOT={self.ws}",
                 f"TARGET_SOONG_ROOT={self.dir / 'soong'}", f"TARGET_PACKAGES={packages / name}",
                 f"TARGET_RUNTIME_OUT={self.dir / 'runtime' / name}"], cwd=ROOT, logfile=self.logfile("validate"))
        shutil.rmtree(copy)

    def stage_publish(self):
        config, soong = self.config, self.state["soong"]
        date = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%d")
        tag = f"lineage-{config['device']}-{date}"
        existing = run(["gh", "release", "list", "--repo", config["github_repository"], "--limit", "200",
                        "--json", "tagName", "-q", ".[].tagName"], capture=True).split()
        suffix = 2
        while tag in existing:
            tag, suffix = f"lineage-{config['device']}-{date}-{suffix}", suffix + 1
        release = self.dir / "release"
        if release.exists():
            shutil.rmtree(release)
        release.mkdir()
        archives = {"apps-r8q": f"lineage-r8q-apps-{date}.tar.zst",
                    "target-libraries-r8q-v2": f"lineage-r8q-core-libraries-{date}.tar.zst",
                    "target-libraries-r8q-graphics-tracing": f"lineage-r8q-graphics-tracing-{date}.tar.zst"}
        for directory, name in archives.items():
            run(["tar", "--zstd", "--sort=name", "--owner=0", "--group=0", "--numeric-owner", "-C",
                 str(self.dir / "packages"), "-cf", str(release / name), directory])

        # Fork first: the release names the fork revision it was validated with.
        fork = config["soong"]["fork"]
        if soong["revision"] != soong["base"]:
            run(["git", "-C", str(fork), "push", "origin", f"{soong['revision']}:refs/heads/{config['soong']['branch']}"])
            if git(fork, "symbolic-ref", "-q", "--short", "HEAD") == config["soong"]["branch"]:
                if not git(fork, "status", "--porcelain", "--untracked-files=no"):
                    run(["git", "-C", str(fork), "merge", "--ff-only", soong["revision"]])
            else:
                run(["git", "-C", str(fork), "update-ref", "refs/heads/" + config["soong"]["branch"], soong["revision"],
                     soong["base"]])

        # Commit the new pins on a fresh worktree of origin/main, leaving the user's checkout alone.
        tree = self.dir / "lineage-ur"
        if tree.exists():
            run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)])
        run(["git", "-C", str(ROOT), "fetch", "origin", "main"])
        run(["git", "-C", str(ROOT), "worktree", "add", "--detach", str(tree), "origin/main"])
        soong_json = json.loads((tree / "soong.json").read_text())
        soong_json["upstream"]["revision"] = soong["upstream"]
        soong_json["fork"]["base_revision"] = soong["upstream"]
        soong_json["fork"]["revision"] = soong["revision"]
        (tree / "soong.json").write_text(json.dumps(soong_json, indent=2) + "\n")
        for name in ("apps", "target-libraries"):
            shutil.copy2(self.dir / "recipes" / (name + ".json"), tree / "lineage" / name / "recipes.json")
        shutil.copy2(self.dir / "manifest-pinned.xml", tree / config["baseline_manifest"].relative_to(ROOT))
        manifest = {"schema_version": 1, "tag": tag, "product": config["product"], "lunch": config["lunch"],
                    "soong_fork": {"repository": soong_json["fork"]["repository"], "revision": soong["revision"]},
                    "context": self.state["context"], "pinned_manifest_sha256": sha(self.dir / "manifest-pinned.xml"),
                    "apps_identical": self.state["apps_identical"],
                    "archives": {d: {"name": n, "sha256": sha(release / n), "bytes": (release / n).stat().st_size}
                                 for d, n in archives.items()}}
        latest = tree / "lineage/update/latest.json"
        latest.write_text(json.dumps(manifest, indent=2) + "\n")
        run(["git", "-C", str(tree), "add", "-A", "soong.json", "lineage", "manifests"])
        message = (f"Update r8q packages to LineageOS {config['branch']} as of {date}\n\n"
                   f"Release {tag}; Soong fork {soong['revision']}.\n")
        run(["git", "-C", str(tree), "commit", "-q", "-m", message])
        commit = git(tree, "rev-parse", "HEAD")
        run(["git", "-C", str(tree), "push", "origin", "HEAD:main"])

        manifest["lineage_ur_commit"] = commit
        (release / "release-manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")
        (release / "SHA256SUMS").write_text("".join(f"{sha(release / n)}  {n}\n" for n in
                                                    [*archives.values(), "release-manifest.json"]))
        identical = sum(self.state["apps_identical"].values())
        notes = (f"Automatic rebuild of the r8q packages from LineageOS `{config['branch']}` "
                 f"(`{config['lunch']}`), pinned by `manifests/reference-r8q-pinned.xml` at {commit[:12]}.\n\n"
                 f"- `{archives['apps-r8q']}`: {len(self.state['apps_identical'])} leaf apps\n"
                 f"- `{archives['target-libraries-r8q-v2']}`: core C libraries\n"
                 f"- `{archives['target-libraries-r8q-graphics-tracing']}`: Skia and Perfetto libraries\n\n"
                 f"Validation: the packaged signed APKs of {identical} of {len(self.state['apps_identical'])} apps were "
                 "byte-identical to the APKs built from source in the same checkout; the target library packages "
                 "passed `make check-target-libraries`; the Soong fork tests passed.\n\n"
                 f"Use Soong fork `{soong['revision']}`. Extract with `tar --zstd -xf ARCHIVE -C artifacts` and install "
                 "as described in `lineage/apps/README.md` and `lineage/target-libraries/README.md`. Checksums verify "
                 "downloads; they are not signatures.\n")
        (release / "notes.md").write_text(notes)
        run(["gh", "release", "create", tag, "--repo", config["github_repository"], "--target", commit,
             "--prerelease", "--title", f"r8q LineageOS packages {date} (automatic)", "--notes-file",
             str(release / "notes.md"), *[str(release / n) for n in [*archives.values(), "release-manifest.json",
                                                                    "SHA256SUMS"]]])
        self.state["release"] = {"tag": tag, "commit": commit}
        self.save()
        run(["git", "-C", str(ROOT), "worktree", "remove", "--force", str(tree)])
        # The archives are on GitHub now; keep only state, logs and the pinned manifest.
        for name in ("packages", "release", "runtime", "soong-tests"):
            shutil.rmtree(self.dir / name, ignore_errors=True)


# Commands --------------------------------------------------------------------

def locked(config):
    config["runs"].mkdir(parents=True, exist_ok=True)
    stream = (config["runs"].parent / "update.lock").open("w")
    try:
        fcntl.flock(stream, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit("another update holds the lock")
    return stream


def start(config, args):
    if args.resume:
        directory = Path(args.resume).resolve()
        return Run(config, directory, args.publish)
    report = compare(config)
    if not report["changed"] and report["soong_upstream"]["head"] == report["soong_upstream"]["pinned"] and not args.force:
        log(f"up to date ({report['projects']} projects checked)")
        return None
    stamp = datetime.datetime.now(datetime.timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    directory = config["runs"] / stamp
    (directory / "logs").mkdir(parents=True)
    (directory / "upstream.json").write_text(json.dumps(report, indent=2) + "\n")
    (directory / "state.json").write_text(json.dumps({"key": report["key"], "status": "new", "done": []}) + "\n")
    log(f"{len(report['changed'])} projects changed; run directory {directory}")
    return Run(config, directory, args.publish)


def command_check(config, args):
    report = compare(config)
    print(json.dumps({**report, "changed": len(report["changed"]),
                      "changed_paths": [c["path"] for c in report["changed"]][:200],
                      "packages_with_moved_repositories": affected_packages(report["changed"])}, indent=2))
    moved = report["changed"] or report["soong_upstream"]["head"] != report["soong_upstream"]["pinned"]
    return 10 if moved else 0


def command_run(config, args):
    lock = locked(config)
    pipeline = start(config, args)
    if pipeline is None:
        return 0
    try:
        pipeline.execute()
    except Exception as error:
        pipeline.state["status"], pipeline.state["error"] = "failed", str(error)
        pipeline.save()
        log(f"failed in {pipeline.state['stage']}: {error}")
        return 1
    finally:
        lock.close()
    return 0


def command_daemon(config, args):
    """Check on an interval; skip upstream states that already failed until upstream moves again."""
    while True:
        try:
            failed = {json.loads(p.read_text()).get("key") for p in config["runs"].glob("*/state.json")
                      if json.loads(p.read_text()).get("status") == "failed"}
            report = compare(config)
            if report["key"] in failed:
                log("upstream unchanged since the last failed run; waiting")
            else:
                command_run(config, argparse.Namespace(resume=None, publish=True, force=False))
        except Exception as error:  # Keep the scheduler alive across network errors.
            log(f"check failed: {error}")
        time.sleep(args.interval_hours * 3600)


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--config", type=Path, default=HERE / "config.json")
    commands = parser.add_subparsers(dest="command", required=True)
    commands.add_parser("check", help="report upstream changes; exit 10 when an update is available")
    run_parser = commands.add_parser("run", help="rebuild, export and validate; release with --publish")
    run_parser.add_argument("--publish", action="store_true")
    run_parser.add_argument("--force", action="store_true", help="run even if upstream did not move")
    run_parser.add_argument("--resume", help="continue a failed or unpublished run directory")
    daemon = commands.add_parser("daemon", help="run --publish every --interval-hours")
    daemon.add_argument("--interval-hours", type=float, default=24)
    args = parser.parse_args()
    config = load_config(args.config)
    return {"check": command_check, "run": command_run, "daemon": command_daemon}[args.command](config, args)


if __name__ == "__main__":
    sys.exit(main())
