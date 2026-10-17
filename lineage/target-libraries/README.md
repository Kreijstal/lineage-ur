# Android target-library packages

This is the Android/Bionic dependency-reuse path. It packages compiled Android
objects for bzip2 (`libbz`), zlib (`libz`), Expat, Zstandard, PNG, JPEG,
Skia (`libskia`, `libskia_renderengine`) and Perfetto (`libperfetto_c`,
`libperfetto_client_experimental`), and
lets the original Soong library consume them instead of compiling C/assembly
again. These objects go into the libraries shipped in Android. They are not
Linux/glibc host libraries.

Final archives and shared libraries are still linked by the original Soong
module. This preserves its dependencies, symbol maps, header exports, Android
STL and sanitizer runtimes, APEX metadata, ABI checks and installation rules.
Shared variants continue to reuse static compilation objects normally. The
upstream source declarations remain authoritative and supply fallback.

## Implemented and validated

The paired Soong fork adds a `target_package` property to native libraries and
the opt-in flag `LINEAGE_USE_PACKAGED_TARGET_LIBS=true`. It checks:

- A pinned manifest and SHA-256 hashes for package contents and source inputs.
- Product variables, including device, CPU configuration, build and API settings.
  Only output-directory references are normalized so isolated outputs work.
- Exact final Soong variation names, including architecture, image, API/APEX,
  profile and instrumentation distinctions.
- Recorded compiler/linker binaries, global compiler configuration sources,
  component sources/headers/build definitions, and selected compiler environment
  overrides.

Missing, modified or incompatible packages/inputs retain source compilation.
API stubs and LLNDK/vendor-public stubs retain their normal compilation. ABI
dump builds need corresponding packaged dumps or retain source. Explicit tidy,
coverage and cross-reference requests also retain source where detected; disable
package selection when running source analysis tools independently.

The completed `lineage_r8q` reference yielded **44 compilation variants and 1,114
objects**, including ARM64 LLVM bitcode for ThinLTO and native 32-bit ARM objects.
Packages preserve existing optimized variants rather than rebuilding with native
Linux compiler flags. `libz_stable` is excluded. A package for the S20 FE is not
automatically compatible with the generic Cuttlefish CPU/configuration.

The separate graphics/tracing bundle adds **18 compilation variants and 10,916
objects**: 3,592 for `libskia`, 1,870 for `libskia_renderengine`, 924 for
`libperfetto_c`, and 4,530 for `libperfetto_client_experimental`. These include
ARM64/ARM32 ThinLTO, AFDO profiles, and available Perfetto APEX/CFI variants.
This packages four libraries, not every binary or Rust dependency in the Skia
and Perfetto repositories. Their original Soong dependencies still build normally.

Recipes now live in `recipes.json`, independently of the host recipes. Export
uses Ninja's read-only `inputs` and `deps` tools to record actual preprocessor
inputs, AFDO data, and checked-in leaves of generated-code dependencies. Source
inputs are checksum guards; generated reference outputs are recorded separately
as provenance. Soong retains responsibility for generation and header exports.
Generated Perfetto public C++ headers are included for standalone consumers.
Skia's Android configuration headers preserve their directory layout.

Multiple libraries from one repository share one combined source overlay and
adapter directory. Each manifest hashes that same final source definition.

Checks performed on 2026-10-17:

- Soong graph tests prove compile actions disappear for matched packages, shared
  libraries consume the packaged static objects, host variants retain source,
  and changed/missing/corrupt inputs, configuration or environment retain source.
- APEX tests use distinct platform/API-31 objects and retain source for an
  unpackaged API-32 variant. The generated source overlays also pass Blueprint
  parsing with duplicate-property checks.
- All six libraries were relinked from packaged ARM64 objects with the Android
  compiler/sysroot/CRTs. Six Bionic consumers passed under QEMU user emulation:
  compression, gzip, XML namespaces/entities, dictionary compression, PNG alpha
  and JPEG arithmetic/Huffman coding. Expat's integer/bounds instrumentation
  requires the original minimal UBSan runtime, which the check links explicitly.
- The installer was exercised against separate local component clones. It
  refuses the reference checkout, checks inputs before edits, and rolls back
  applied definitions if an installation fails.
- The graphics/tracing bundle passed `make check-graphics-tracing` with all four
  ARM64/Bionic consumers, Soong fixtures, generated-overlay parsing, and guarded
  installer regression tests. The four final adapters also installed into fresh
  private Skia/Perfetto working copies. The six earlier runtime consumers still
  pass after the checker changes. The r8q protection check reports unchanged
  metadata for all 49,922 tracked reference output files.

Runtime results are **synthetic userspace evidence**, not hardware validation.
Only core ARM64 consumers were executed; the package inventory is broader than
the runtime coverage. No full ROM with these packages has been built or booted,
and no ROM build-time saving is measured. The reference and running VM checkout
remain unchanged.

## Download the experimental r8q packages

The [2026-10-17 experimental release](https://github.com/Kreijstal/lineage-ur/releases/tag/target-libraries-r8q-20261017)
contains two compressed bundles: the six core libraries and the four
graphics/tracing libraries. Each contains `packages/`, `overlay/` and
`inventory.json` under its original bundle directory. The release also includes
`SHA256SUMS`, `release-manifest.json` and the two ARM64 runtime reports.

```sh
mkdir -p artifacts/downloads
gh release download target-libraries-r8q-20261017 \
  --repo Kreijstal/lineage-ur --dir artifacts/downloads
cd artifacts/downloads
sha256sum --check SHA256SUMS
tar --zstd -xf lineage-r8q-core-libraries-20261017.tar.zst -C ..
tar --zstd -xf lineage-r8q-graphics-tracing-20261017.tar.zst -C ..
```

Return to the repository root and use `apply.py --check-only` against a separate
checkout before installation. These are Android build inputs pinned to the
reference r8q configuration; source/toolchain inputs must still be available.
The graphics standalone canvas check additionally needs the reference build's
Rust and codec link inputs described below. The archives are not installable
Termux/Debian packages or flashable system images. Release checksums verify
downloaded file identity; they are not a signed APT repository or an independent
build attestation. The reference firmware, proprietary device binaries, user
data and recovery backups are not included in these bundles.

## Generate packages from a reference build

Use the Soong fork revision recorded in `soong.json`, which includes target
object-package support. The optional integration manifest selects that fork's
branch; pin its recorded commit when creating a reproducible checkout.

```sh
python3 tools/test_soong.py \
  --source-root /path/to/android \
  --soong-root /path/to/android_build_soong \
  --context-variables /path/to/android/out/soong/soong.lineage_r8q.variables \
  --context-out-dir out

python3 lineage/target-libraries/package.py \
  --source-root /path/to/android --reference-out /path/to/android/out \
  --product lineage_r8q \
  --build-state /path/to/reference/state.json \
  --reference-manifest /path/to/reference/manifest-pinned.xml \
  --context CONTEXT_SHA256_FROM_PREVIOUS_COMMAND \
  --output artifacts/target-libraries-r8q-v2 \
  --module libbz --module libz --module libexpat \
  --module libzstd --module libpng --module libjpeg

make check-target-libraries TARGET_SOURCE_ROOT=/path/to/android
```

The exporter requires clean, pinned component repositories and completed,
idle reference outputs. It copies existing compiler objects; it does not write
to the reference checkout or launch its build. Output includes `packages/`,
`overlay/` and `inventory.json`. QEMU must already be available at `TARGET_QEMU`
or supplied as a Make override; nothing is installed system-wide by the checks.

## Integrate into a separate checkout

```sh
python3 lineage/target-libraries/apply.py \
  --packages artifacts/target-libraries-r8q-v2 \
  --checkout /path/to/separate/android --check-only

python3 lineage/target-libraries/apply.py \
  --packages artifacts/target-libraries-r8q-v2 \
  --checkout /path/to/separate/android

# After envsetup/lunch matching the packaged reference configuration:
LINEAGE_USE_PACKAGED_TARGET_LIBS=true m libbz libz libexpat libzstd libpng libjpeg
```

The installer adds one defaults reference to each original library and places
its snapshot/defaults beneath that component's directory. Existing defaults
and dependency definitions are preserved. The original source inputs are still
needed for validation and fallback. This is a first dependency-package reuse
implementation, not a source-free standalone Android distribution.

The package context is deliberately conservative. Source/manifests and recorded
inputs must be reviewed again on upstream updates; environment checks cover
known overrides, not every possible future build-system input. This is not yet
a complete automatically derived cache key or arbitrary-version ABI resolver.
Keep the flag off for source/checkbuild baselines or unmatched build modes.

## Skia and Perfetto experiment

Export only the four graphics/tracing libraries with the same reference/context
arguments shown above, replacing the output argument and adding:

```sh
--output artifacts/target-libraries-r8q-graphics-tracing \
--module libskia --module libskia_renderengine \
--module libperfetto_c --module libperfetto_client_experimental
```

The Android-specific runtime checks are:

- Skia: rasterize a clipped rectangle into a 16x16 bitmap and check every pixel,
  separately with each packaged Skia library. This exercises CPU rendering;
  GPU paths, codecs, font rendering and display integration remain untested.
- Perfetto: separately exercise the C and C++ SDKs with two in-process sessions,
  flush/stop each session, and require the emitted event name in the resulting
  trace bytes. The C API needs explicitly enabled categories. No system tracing
  daemon or physical device is used.

These consumers link native test objects against archives made from the packaged
Android objects. LLD still compiles packaged ThinLTO inputs with their recorded
module flags; the test consumer introduces no conflicting split-LTO policy.
The C++ test consumers disable RTTI to match the platform libraries. The small
generated Perfetto flag archive is copied from the same reference build and used
as a standalone test dependency. Skia's canvas test also uses the reference
WebP/Wuffs archives and the Rust-only aggregate generated for libhwui; it does
not link the reference libhwui shared library. Those retained link inputs are
listed in the recipe and SHA-256 recorded in the runtime report. They are not
additional replacement packages. Android shared libraries come from the
reference image, including its APEX lib64 directories. Standalone QEMU execution
does not validate Android's full linker namespace configuration.

```sh
make check-graphics-tracing TARGET_SOURCE_ROOT=/path/to/android

python3 lineage/target-libraries/apply.py \
  --packages artifacts/target-libraries-r8q-graphics-tracing \
  --checkout /path/to/separate/android --check-only

python3 lineage/target-libraries/apply.py \
  --packages artifacts/target-libraries-r8q-graphics-tracing \
  --checkout /path/to/separate/android

# Matching lunch/configuration, in that separate checkout:
LINEAGE_USE_PACKAGED_TARGET_LIBS=true \
  m libskia libskia_renderengine libperfetto_c libperfetto_client_experimental
```

Runtime output is written to `artifacts/target-graphics-tracing-runtime/report.json`.
The installer experiment uses private Git working copies of Skia and Perfetto;
the rest of its inputs refer to the reference checkout. It is a component-install
workspace, not a full standalone ROM checkout. No full ROM build, boot test,
hardware validation, or end-to-end build-time saving has been established.
