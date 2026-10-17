# Lineage UR

An independent package and build-integration layer for progressively unbundling
LineageOS. Inspired by [msys2-ur](https://github.com/Kreijstal/msys2-ur) and the
[Termux User Repository](https://github.com/termux-user-repository/tur).

The goal is to reuse compatible packaged dependencies and system tools while
keeping a small, reviewable difference from upstream LineageOS. Initial target:
`lineage-23.2`, Android 16, Samsung Galaxy S20 FE `SM-G780G` / `r8q`.

**Status:** experimental host-tool, host C library and Android target-object
reuse are implemented and opt-in. Android object-package bundles are provided in
the [experimental r8q release](https://github.com/Kreijstal/lineage-ur/releases/tag/target-libraries-r8q-20261017).
There is no APT repository or automatic package downloader, and no ROM build-time
speedup is claimed yet. See [system tools](docs/system-tools.md) and
[host libraries](docs/host-libraries.md).

[System LZ4](lineage/lz4-system/README.md) is the first CLI policy with functional
Android format checks and a comparison against the pinned source implementation.

[BoringSSL](lineage/boringssl/README.md) adds an experimental read-only export of
the pinned reference build's host shared libraries, with a verified TLS 1.3
consumer and opt-in Soong selection. Static and Android device variants retain
their existing builds.

[Android target libraries](lineage/target-libraries/README.md) packages the
compiled Android/Bionic objects for ten libraries, including Skia and Perfetto.
Soong skips matched source
compilation and retains its Android linking/APEX/ABI rules. This is the path for
dependencies shipped in LineageOS. Download, checksum verification and integration
instructions are included in its documentation.

[Six host C libraries](lineage/host-libraries/README.md) adds pinned bzip2, zlib,
Expat, Zstandard, PNG and JPEG packages, including static variants, consumer
checks and an overlay that preserves each component's license visibility.

[Upstream SwiftShader](lineage/swiftshader/README.md) packages an ARM64/Bionic
Android Vulkan HAL using Termux's prebuilt LLVM 21, with checksum-guarded Soong
selection, vendor APEX checks and a Vulkan compute runtime test. Full ROM boot
and hardware/display validation remain outstanding.
Download the [experimental SwiftShader package](https://github.com/Kreijstal/lineage-ur/releases/tag/swiftshader-android36-arm64-20261017).

## Repository layout

| Path | Purpose |
| --- | --- |
| `lineage/` | Component recipes and patches, one directory per component. |
| `overlays/` | Soong prebuilt definitions and integration patches. |
| `manifests/` | Optional `repo` local manifest for adding this layer. |
| `templates/` | Component metadata and integration examples. |
| `repo.json` | Proposed Termux-style recipe collection and binary repository mapping. |
| `soong.json` | Soong upstream revision, fork branch and feature status. |
| `docs/design.md` | Package boundaries, compatibility and upstream maintenance policy. |

Run `make check` for local validation on Linux x86-64/glibc with Python 3.9+, Git
and standard `echo`/`sleep` executables, plus native `cc`, `ar` and `readelf`.
Install `lz4` to include its functional compatibility tests (CI installs it).
CI runs the same metadata and package consumer tests; it does not compile Android
or publish packages.

## How it will work

1. Pin a working upstream LineageOS manifest and build configuration.
2. Inspect one component's source, Android changes and build variants.
3. Package the existing implementation with its headers and required metadata.
4. Add a Soong prebuilt adapter or a narrowly scoped project-path override.
5. Validate consumers against the source-built baseline.
6. Publish reusable artifacts and build unmatched components from source.

Unbundling the current implementation and upgrading to another upstream version
are separate changes. GitHub Releases can hold package files; a signed APT index
and package download URLs will be added once an actual package is ready.

## Adding the layer to a checkout

For a separate experimental checkout, copy
`manifests/lineage-23.2.xml` to `.repo/local_manifests/lineage-ur.xml` and run
`repo sync vendor/kreijstal/lineage-ur`. This adds the repository only; it does
not replace a dependency or change build settings. Use a pinned commit instead
of `main` in reproducible builds.

The URLs in `repo.json` describe the intended publication layout. They are not
an active package source and should not be added to APT yet. A separate build
adapter is required: stock Termux packages and their application-specific paths
are not automatically interchangeable with Android platform dependencies.

## Soong fork

[Kreijstal/android_build_soong](https://github.com/Kreijstal/android_build_soong/tree/lineage-ur-23.2)
tracks LineageOS's Soong on `lineage-ur-23.2`. It adds opt-in
`system_build_tool` and `cc_packaged_library_host` adapters with source fallback.
The compatibility
selectors are documented in [system tools](docs/system-tools.md) and
[host libraries](docs/host-libraries.md).
Target object-package integration uses the `target_package` library property and
`LINEAGE_USE_PACKAGED_TARGET_LIBS=true`. The recorded fork revision in
`soong.json` includes this support. Default source builds retain upstream behavior.

For a separate experimental checkout, the optional
`manifests/lineage-ur-soong.xml` replaces only the `build/soong` project. It is
separate from the manifest that adds the recipe repository. Its `base-rev` guard
requires reconciling upstream changes before switching the checkout. See
[the design notes](docs/design.md#soong-fork) for the update procedure.

## Contributing

Keep upstream references, source changes, packaging and build integration
separate and reviewable. Record the exact validation command and result for each
component. Carry the smallest practical patch stack; unknown compatibility or
missing artifacts should keep the component on its source-build path.

Tooling and documentation created in this repository are MIT licensed. Imported
sources, patches and binary payloads retain their own licenses and require
appropriate attribution and redistribution review.
