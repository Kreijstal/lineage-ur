# Automatic r8q package updates

`update.py` rebuilds and republishes the packages that come from the
`lineage_r8q` reference build (the leaf apps and the r8q target libraries) when
LineageOS moves. The SwiftShader and Termux packages are pinned to Termux and
SwiftShader revisions instead and are not part of this pipeline.

## Commands

```sh
# Compare upstream heads with manifests/reference-r8q-pinned.xml.
# Exit status 10 means an update is available.
python3 lineage/update/update.py check

# Sync, merge Soong, build, export and validate without publishing.
python3 lineage/update/update.py run

# Continue a failed or unpublished run, then publish it.
python3 lineage/update/update.py run --resume artifacts/update/runs/STAMP --publish

# Check every 24 hours and publish validated updates.
setsid nohup python3 lineage/update/update.py daemon >> artifacts/update/daemon.log 2>&1 < /dev/null &
```

`check` compares the branch or tag each synced project tracks (annotated tags
are dereferenced) and lists recipe packages whose own repository moved. Apps
also depend on about 45,000 inputs in other repositories, so any upstream move
can make a package stale; `run` re-exports all of them.

## Stages

Each run has a directory under `artifacts/update/runs/` with `state.json`, the
upstream report and one log per stage. A failed stage keeps the completed ones,
and `--resume` continues from it.

1. **sync**: a private shallow repo client in `artifacts/update/source`, with
   the r8q device manifest (`r8q.xml`) and the SM8250 kernel build patch. The
   reference checkout is never touched. Later runs sync the same client
   incrementally. `repo manifest -r` records the pins and the recipe revisions
   are updated from them.
2. **soong**: upstream `lineage-23.2` is merged into the fork in a separate
   worktree. A conflict stops the run and names the files. The fork's Go tests
   run against the new checkout, which then builds with the merged fork.
3. **build**: `m bacon` for `lineage_r8q-bp4a-userdebug`, with the shared
   ccache. It needs 150 GiB free for the first build and 40 GiB for later, incremental
   builds.
4. **export**: the app and target-library exporters with the newly computed
   contexts.
5. **validate**: the app packages are installed into a hard-linked copy of the
   checkout. Their packaged signed APKs must be byte-identical to the APKs
   built from source in the same checkout. Each target-library package set
   must pass `make check-target-libraries`.
6. **publish** (only with `--publish`): pushes the merged fork as a fast-forward,
   commits the new pins and `latest.json` to `main` from a separate worktree,
   and creates a pre-release `lineage-r8q-YYYYMMDD` with the three archives,
   `release-manifest.json` and `SHA256SUMS`. The local archives are deleted
   afterwards.

`daemon` runs `run --publish` on an interval. It skips an upstream state whose
run already failed until upstream moves again. A failed run waits for someone
to fix it and resume it.

`latest.json` names the newest automatic release, its archives and the Soong
fork revision it was validated with.
