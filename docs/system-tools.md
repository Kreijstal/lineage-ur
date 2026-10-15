# Selecting system host tools

The Soong fork provides `system_build_tool`, an opt-in replacement for a matching
source-built host executable. The Python helper resolves tools before Soong
sanitizes `PATH`, runs explicit compatibility probes, copies accepted binaries
into hash-named snapshots, and generates `Android.bp` plus `selection.json`.
It works across Linux distributions using glibc on x86-64; no package-manager
integration is required. Other host architectures and operating systems need
additional adapters.

Selection has two gates: the candidate must pass the recipe's probes and
`LINEAGE_USE_SYSTEM_TOOLS=true` must be supplied to the build. Missing tools,
failed probes, timeouts, optional hash mismatches, and deleted snapshots all
leave the matching source module selected. Malformed policy is an error.
There is no implicit search for arbitrary replacements.

The ready-to-test [system LZ4 policy](../lineage/lz4-system/README.md) checks real
Android compression commands and formats. It uses the installed executable;
no `liblz4` package build is required to select the CLI.

## Experimental setup

Use a **separate, idle Android checkout**. First select the Soong fork with
`manifests/lineage-ur-soong.xml` as described in the main README, and sync it.
Keep the source module: it supplies the fallback. The adapter must share its
Soong namespace and must not collide with an existing `prebuilt_<name>`.

From that checkout's root, with this repository at `vendor/kreijstal/lineage-ur`:

```sh
python3 vendor/kreijstal/lineage-ur/tools/select_system_tools.py \
  --policy vendor/kreijstal/lineage-ur/policies/dtc.example.json \
  --output external/dtc/lineage-ur-generated

# After the usual envsetup/lunch for your build:
LINEAGE_USE_SYSTEM_TOOLS=true m dtc
```

The example accepts DTC 1.8.1 and checks the presence of its symbols option.
It is a demonstration policy, **not a claim of compatibility with all Android
device trees**. Differential tests against the pinned LineageOS DTC and builds
of its actual consumers are still required before enabling it in a ROM build.
No policy is enabled automatically. The output is below `external/dtc` so its
`external_dtc_license` is visible; do not relabel imported binaries with this
repository's license.

For each tool policy specify:

- `module`: the exact source Soong module name.
- `executable`: a name to resolve on `PATH`, or an absolute executable path.
- `licenses`: applicable existing Soong license modules, visible from the
  generated directory and appropriate for the selected packaged implementation.
- `probes`: argument arrays and required regular expressions over combined
  stdout/stderr. Every command must exit zero. No shell is invoked; probes run
  in an empty temporary working directory, with a five-second timeout per probe
  by default. They execute trusted local binaries and are not a security sandbox.
- `sha256` (optional): require an exact, previously reviewed executable hash.
- `compatibility` (optional): `android-lz4` adds functional compression-format,
  roundtrip and corruption checks after the version/feature probes. Unknown
  profiles are configuration errors.

The helper accepts native x86-64 ELF executables only. Probe checks are necessary
but do not prove complete behavioral compatibility. Use component-specific
functional tests and pin hashes when reusing a validated selection.

## Build behavior and limits

`system_build_tool` uses Soong's normal source/prebuilt selection, host-tool
provider, sandbox packaging and Make export. It installs at the normal host
`bin/<module>` location. Only the host variant is replaced; device executables,
target libraries, compiler toolchains and bootstrap tools are outside this
adapter's scope. Modules needing Java/Go-specific providers or additional
runtime files require their own adapters. It assumes the installed executable
name matches the module name; custom stems and symlink aliases need more work.

Normal consumers use the selected prebuilt rather than depending on the source
executable's compilation. Explicit source/checkbuild targets may still compile
the original. A full ROM build speedup has not been measured.

Snapshots are real copies, not symlinks into `/usr/bin`. Their content hash,
resolved original path, probe output and policy hash are recorded. Ninja tracks
the snapshot as an input, and Soong tracks the opt-in environment variable plus
snapshot existence. Repeating an identical selection preserves timestamps.
Rerun the helper after policy/package changes; failed new candidates replace
the previous selection with a source fallback. Old hash-named files remain
available for review but are no longer referenced. Never regenerate inputs
while a build is running.

Host runtime libraries, the ELF loader and environment are **not snapshotted**.
This first adapter is for local builds; it is not a fully hermetic package cache
or a remotely executable tool bundle. Run selection again after host runtime
updates and revalidate affected consumers. Tools requiring `$ORIGIN` libraries,
scripts, data files or special installation layouts need a dedicated recipe.
Generated snapshots are local build inputs; do not commit or publish them as
packages without their corresponding source/license material.

Disable selection by omitting/unsetting `LINEAGE_USE_SYSTEM_TOOLS` on the next
build. Removing the generated directory also removes the adapters. Upstream
`prebuilt_build_tool` behavior is unchanged.

## Validation

```sh
make check
python3 tools/test_soong.py \
  --source-root /path/to/synced/reference-android \
  --soong-root /path/to/android_build_soong
```

The second command uses the reference checkout's pinned Go and local Go
dependencies, with the fork substituted through an isolated workspace/cache
under `artifacts/soong-tests`. It writes nothing into the reference checkout and
disables dependency downloads. It compiles the changed packages and runs focused
source/prebuilt and genrule tests, including a real `cc_binary` host replacement,
unchanged device variant and Make export. CI runs `make check`; it does not sync
Android sources or claim a complete platform build.
