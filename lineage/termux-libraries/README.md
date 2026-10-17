# Independent Termux libraries in LineageOS

This recipe reuses official ARM64/Bionic Termux binaries. It does not compile
the libraries or import LineageOS object files. It adapts SONAMEs and dependency
names to the existing Android module names and removes Termux's RUNPATH.
Android consumers retain the platform headers used during validation.

Download the [experimental package and audit reports](https://github.com/Kreijstal/lineage-ur/releases/tag/termux-libraries-android36-arm64-20261017)
and verify `SHA256SUMS` before integration.

| Android module | Termux package | Result on the reference r8q build |
| --- | --- | --- |
| libz | zlib 1.3.2 | Consumer passed; opt-in ARM64 vendor shared adapter |
| libzstd | zstd 1.5.7-1 | Consumer passed; opt-in ARM64 vendor shared adapter |
| libpng | libpng 1.6.59 | Consumer passed; opt-in ARM64 vendor shared adapter |
| libexpat | libexpat 2.9.0 | Consumer passed; adapter withheld because default Android variants use sanitizers |
| libbz | libbz2 1.0.8-8 | Consumer passed; shared binary cannot replace Android's static-only library |
| libjpeg | libjpeg-turbo 3.2.0 | Rejected: Termux uses JPEG ABI 80, Android expects 62 |

The [pinned package index entries](termux-aarch64.lock.json) record the official
repository, versions, sizes and SHA-256 digests. Upstream Termux recipes explain
the [JPEG8 configuration](https://github.com/termux/termux-packages/blob/master/packages/libjpeg-turbo/build.sh)
and [versioned Expat SONAME](https://github.com/termux/termux-packages/blob/master/packages/libexpat/build.sh).

## Reproduce the audit and package

Prerequisites: Python 3.12+, curl, ar, readelf, patchelf, zstd, ARM64 QEMU user,
and a completed reference r8q build. `--sysroot` points to a separate Android
sysroot with its API-36 libraries and CRT objects, such as the one prepared by
the [SwiftShader cross build](../swiftshader/README.md). Neither command below
writes to the Android source tree or runs its build process. Output directories
must be fresh.

```sh
ANDROID_SOURCE=/path/to/completed/android
ANDROID_SYSROOT=/path/to/separate/sysroot
QEMU=/path/to/qemu-aarch64

python3 lineage/swiftshader/import_termux.py \
  --lock lineage/termux-libraries/termux-aarch64.lock.json \
  --output artifacts/termux-c-libraries-import

python3 lineage/termux-libraries/prepare.py \
  --android-source "$ANDROID_SOURCE" --sysroot "$ANDROID_SYSROOT" \
  --termux artifacts/termux-c-libraries-import --qemu "$QEMU" \
  --output artifacts/termux-c-libraries-android36

python3 lineage/termux-libraries/check.py \
  --android-source "$ANDROID_SOURCE" \
  --adapter artifacts/termux-c-libraries-android36/adapter --qemu "$QEMU" \
  --output artifacts/termux-c-libraries-platform-consumers

python3 tools/test_soong.py \
  --source-root "$ANDROID_SOURCE" --soong-root /path/to/android_build_soong \
  --termux-libraries artifacts/termux-c-libraries-android36/adapter \
  --run '^TestPackagedSharedTargetTermuxLibraries$'
```

The importer verifies archives and runs no package scripts. Preparation verifies
consumed library bytes against their pinned archives, compiles functional
consumers with **LineageOS headers**, runs them using the actual Bionic loader,
and scans the reference product's installed ARM64 ELF dependencies for uses of
missing exports. The generated report records every input, compiler command,
runtime result and missing export. Expected rejection of JPEG does not fail the
audit command; rejected libraries are excluded from its adapter.

The second check runs Android's own ELF validation for SONAMEs, dependencies,
undefined symbols and 16 KiB alignment. It then runs the existing r8q `ziptool`
with `libziparchive` against Termux zlib and the existing Android `zstd` command
against Termux zstd/zlib. Both decompress independently generated archives and
compare all output bytes. These are synthetic ARM64/Bionic userspace tests.

The recorded audit scanned 2,284 installed ARM64 ELF files. Of the exports absent
from the three selected libraries, none were referenced by their installed direct
consumers. This symbol scan does not establish complete ABI compatibility:
structure layout, behavior, future consumers, namespaces and instrumentation
also matter. No full ROM boot, hardware validation or build-time improvement is
claimed. See [validation.json](validation.json) for exact commands and results.

## Integrate into an experimental checkout

Use the matching Lineage UR Soong fork. Copy **only** the generated `adapter`
directory into a new directory in that checkout's root Soong namespace, for
example `vendor/kreijstal/lineage-ur/lineage/termux-generated`. Keep the original
source modules and enable:

```sh
export LINEAGE_USE_PACKAGED_TARGET_BINARIES=true
```

This replaces eligible API-36 ARM64 **vendor shared** variants of `libz`,
`libzstd` and `libpng`. The source definitions and static, ARM32, core-system,
SDK, recovery and instrumented builds remain available. Selection verifies the
entire package manifest and payload, including exported headers. Missing or
modified payloads, an unset flag or unsupported variants retain source builds.
Soong tests check actual generated adapters, dependency selection, platform
header propagation and fallback after library/header corruption.

The package is intentionally experimental and scoped to the reviewed baseline.
Review the audit again when upgrading the Android source. In particular, a
successful vendor variant does not establish compatibility with core-system or
APEX variants. Extending that coverage, adapting Termux's JPEG build to Android's
ABI, and supplying independently built static archives are further unbundling
work; publishing cached Android objects does not accomplish those steps.
