# Six reusable host C libraries

These pinned recipes prepare Linux x86-64/glibc packages for the existing
`cc_packaged_library_host` adapter. They keep Android's configuration headers,
module names and SONAMEs. They are local opt-in build inputs; no binary
repository has been published or ROM speedup measured.

| Component | Soong module | Packaged variants | Preparation |
| --- | --- | --- | --- |
| bzip2 | `libbz` | static | Export completed reference output |
| zlib | `libz` | static, shared | Export completed reference outputs |
| Expat | `libexpat` | static | Export completed reference output |
| Zstandard | `libzstd` | static | Export completed reference output |
| libpng | `libpng` | static, with shared `libz` dependency | Export completed reference output |
| libjpeg-turbo | `libjpeg` | static | Build pinned Android sources with native tools |

`recipes.json` pins source revisions and header/license inventories. The five
exports preserve reference artifacts byte for byte, including Android changes
and compiler configuration. Packages record artifact/header/manifest/compiler
hashes, product variables and Ninja commands. `ninja -t commands` reads the graph
without executing build commands. This is observed provenance, not an independent
build attestation.

Host JPEG was absent from the reference outputs. Its recipe uses the pinned
Android default and x86-64 source lists, original configuration headers, native
`cc`/`ar`/NASM, PIC, SIMD and arithmetic encoding/decoding. It records commands
and tool identities. This does not reproduce the complete Soong flag set.
The parser deliberately supports only the pinned Android.bp layout; source
revision changes require review.

## Prepare and validate

Run from Lineage UR. Reference outputs must be completed and idle. Export never
writes to Android sources/outputs. JPEG compilation uses a temporary directory
outside Android, with two workers by default. All six repositories must be clean
and agree with the recipes and pinned manifest. Use new export/overlay directories.

```sh
python3 lineage/host-libraries/export.py \
  --source-root /path/to/android \
  --reference-out /path/to/android/out \
  --product lineage_r8q \
  --build-state /path/to/reference/state.json \
  --reference-manifest /path/to/reference/manifest-pinned.xml \
  --output artifacts/packages/host-libraries --jobs 2

python3 tools/select_host_libraries.py \
  --policy artifacts/packages/host-libraries/policy.json \
  --output artifacts/host-libraries-selection

make check-host-libraries HOST_LIBRARIES_REFERENCE_OUT=/path/to/android/out

python3 lineage/host-libraries/prepare.py \
  --policy artifacts/packages/host-libraries/policy.json \
  --output artifacts/host-libraries-overlay

python3 tools/test_soong.py \
  --source-root /path/to/android \
  --soong-root /path/to/android_build_soong \
  --c-libraries-overlay artifacts/host-libraries-overlay \
  --run '^TestPackagedHostLibraryGeneratedCLibraries$'
```

The checker compiles and executes consumers of all seven packaged linkage
variants: bzip2 compression and invalid input, zlib/gzip streams, incremental
XML parsing with namespaces/entities, Zstandard dictionaries, PNG RGBA/alpha
preservation, and JPEG Huffman/arithmetic coding with a pixel-error bound.
Shared-library loader paths are checked. The optional reference output adds
six comparison runs for the five exports. No reference JPEG binary was available.
Results go to `consumer-check.json` in the selection directory.

The Soong test loads the actual six-directory overlay with upstream license
visibility boundaries. It checks enabled/disabled selection, consumer dependencies,
unchanged device variants, PNG's shared zlib dependency and source fallback when
zlib snapshots disappear. These are graph tests, not a complete Android consumer
or ROM build. Locally, the seven package consumers and six reference comparisons
passed, as did all three graph scenarios, on 2026-10-17.

## Integration boundary

The combined selection is for standalone validation. Upstream license modules
are restricted to their component directories, so use the prepared overlay for
Android integration. It emits one adapter per component through `--module`,
while checking/staging its complete dependency closure without duplicate modules.

Apply its six `external/*/lineage-ur-generated` directories only to a **separate,
idle checkout** with the Soong fork installed. Retain source modules. Compare the
checkout's source/configuration against package provenance before enabling
`LINEAGE_USE_PACKAGED_HOST_LIBS=true` and building actual host consumers.
The selector does not derive compatibility from the resolved consumer flags.
Removing the flag restores source selection. The active Samsung/VM checkout
has not been modified by this preparation.

Each adapter has local copies of its transitive inventory. Across separate
adapter directories, regenerate the whole overlay when dependency selections
change; local file-existence checks are not a global dependency-version resolver.

`libz_stable` remains source-built because legacy OTA consumers require specific
compressed output behavior. Unsupported linkage variants, Android/Bionic, musl,
Windows, ARM hosts, sanitizers, recovery and APEX configurations also retain
source definitions. API stability alone does not prove interchangeable build
outputs. These packages use the pinned Android implementations, not arbitrary
installed distro versions.
