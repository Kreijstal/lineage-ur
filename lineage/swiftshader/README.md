# ARM64/Bionic SwiftShader package

This recipe builds current upstream SwiftShader as Android's `vulkan.pastel.so`
HAL, reusing **Termux's prebuilt ARM64/Bionic LLVM 21.1.8** and its dependency
closure. It supplies a hash-pinned package and an opt-in Soong adapter. LLVM is
not rebuilt. The initial host LLVM 22 experiment is retained separately below.

The upstream revision is `cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5` (2026-10-14).
The package targets ARM64, Android API 36 and the vendor partition. Its C++ code
uses the NDK `__ndk1` ABI expected by Termux LLVM; its private C++ runtime remains
separate from platform `libc++.so`. Android HAL exports, native-buffer functions
and Android hardware-buffer support are retained.

**Validation:** the packaged HAL opens through `HMI` under ARM64/Bionic QEMU,
reports LLVM 21.1.8, exposes AHB entry points, returns gralloc usage, and compiles
and executes a compute shader with all 256 output values checked. This does not
validate display presentation, actual AHardwareBuffer allocation/import/export,
SELinux, linker namespaces in a booted ROM, or physical hardware. See
[validation-android.json](validation-android.json) for exact commands and scope.

## Why reuse LLVM rather than the existing Termux SwiftShader binary?

Termux already ships `swiftshader` version `2025.06.25-2` for ARM64/Bionic.
Its existing binary passed our standalone Vulkan compute test and reports
LLVM 10. Its [Android-disable patch](https://github.com/termux/termux-packages/blob/4e6a496b172798099f963aa81d2d5b55fd6c395c/packages/swiftshader/swiftshader-no-android.patch)
removes the platform HAL interface. It therefore serves as a standalone ICD
reference rather than the packaged Android HAL. The new HAL instead uses the
newer source and Termux's separately packaged LLVM 21.

## Build and package

Prerequisites: Git, Python 3.12+, curl, ar, CMake, Ninja, patchelf, readelf,
glslangValidator, an ARM64 QEMU user executable, and the completed reference
`lineage_r8q` build. The recipe reads its platform headers, NDK sysroot, CRTs,
Clang and system libraries. It copies required sysroot files into the experiment
and writes nothing to the Android checkout or its build outputs. It does not
invoke the ROM's Ninja process or change its configuration.

Use a separate upstream checkout outside Android. All output paths below must
be fresh; select other paths when repeating an export.

```sh
# From Lineage UR; choose your completed Android checkout:
ANDROID_SOURCE=/path/to/android
SWIFTSHADER_SOURCE=/path/to/separate/swiftshader-android

git clone --filter=blob:none https://swiftshader.googlesource.com/SwiftShader "$SWIFTSHADER_SOURCE"
git -C "$SWIFTSHADER_SOURCE" checkout --detach cddb5c91b23ff70a1f607ea31610aa0d7f4b5ad5
git -C "$SWIFTSHADER_SOURCE" apply "$PWD/lineage/swiftshader/patches/android-bionic.patch"

python3 lineage/swiftshader/import_termux.py --output artifacts/swiftshader-termux-aarch64
python3 lineage/swiftshader/build_android.py \
  --android-source "$ANDROID_SOURCE" --swiftshader-source "$SWIFTSHADER_SOURCE" \
  --termux artifacts/swiftshader-termux-aarch64 \
  --output artifacts/swiftshader-bionic-arm64 --jobs 2
python3 lineage/swiftshader/package_android.py \
  --build artifacts/swiftshader-bionic-arm64 \
  --termux artifacts/swiftshader-termux-aarch64 \
  --swiftshader-source "$SWIFTSHADER_SOURCE" \
  --output artifacts/swiftshader-package
```

The importer verifies pinned `.deb` hashes, extracts them into staging and runs
no package scripts. Build/package helpers compare consumed LLVM headers and
libraries with the original archives. The build rejects a different SwiftShader
revision or patch. The standalone cross build uses Linux's CMake platform rules
with an explicit Android Clang target and Bionic sysroot; the patch selects the
Android HAL code independently of those CMake kernel conventions.

The package contains eight shared libraries: SwiftShader, LLVM, the NDK C++
runtime, libffi, zlib, Zstandard, libxml2 and libiconv. Private dependencies get
`liblineage_ur_*` SONAMEs and matching `DT_NEEDED` references. Build/Termux RPATHs
are removed. It includes checksums, provenance, component notices/licenses,
SwiftShader's patch and libiconv's original source archive. Component licenses
retain their individual terms.

## Validate the finished package

```sh
python3 lineage/swiftshader/check_android.py \
  --android-source "$ANDROID_SOURCE" --swiftshader-source "$SWIFTSHADER_SOURCE" \
  --build artifacts/swiftshader-bionic-arm64 \
  --library artifacts/swiftshader-package/package/lib64/hw/vulkan.pastel.so \
  --library-dir artifacts/swiftshader-package/package/lib64 \
  --qemu /path/to/qemu-aarch64 --output artifacts/swiftshader-runtime

python3 tools/test_soong.py \
  --source-root "$ANDROID_SOURCE" --soong-root /path/to/android_build_soong \
  --swiftshader-package artifacts/swiftshader-package \
  --run '^TestPackagedSharedTarget.*$'
```

The runtime test uses the completed ROM's Bionic loader and libraries. The
Soong tests exercise the actual generated package, consumer selection, missing
or corrupt dependency fallback, API/architecture/partition checks, unsupported
instrumentation and vendor APEX dependency inclusion. They also ensure the
custom Go files appear in Soong's bootstrap input lists.

## Integrate into a separate experimental ROM checkout

Install the matching Lineage UR Soong fork first. Copy the generated package
into a new directory under SwiftShader's source namespace, for example:

```sh
cp -a artifacts/swiftshader-package /path/to/experimental/android/external/swiftshader/lineage-ur-generated
export LINEAGE_USE_PACKAGED_TARGET_BINARIES=true
```

Then build the intended consumer using that checkout's normal product setup.
Keep the source modules. The adapter uses the module type
`cc_packaged_library_shared_target` and replaces the matching shared library
only when its complete package passes the manifest and content checks. It
preserves the `vulkan.pastel` module name and `hw` installation path. Builds
must already request this software Vulkan driver; this does not replace an
S20 FE's Qualcomm GPU driver or change product configuration.

The new flag is independent of object reuse's
`LINEAGE_USE_PACKAGED_TARGET_LIBS`. Leaving it unset, unavailable package files,
modified content, another API/architecture/partition or unsupported
instrumentation keeps the source implementation. This package covers ARM64
only. ARM32, host and debug SwiftShader builds retain their original sources.
Mesa's llvmpipe/lavapipe also consume LLVM 16 separately. Consequently this
package does not remove every LLVM 16 build or establish a measured ROM
build-time improvement. A full ROM build/boot using it remains unvalidated.

## Earlier host LLVM 22 probe

`patches/system-llvm22.patch` and the top-level check `CMakeLists.txt` retain the
separate Linux/glibc experiment. Its 156 upstream Reactor tests passed with
packaged LLVM 22.1.8 and IR verification enabled; see [validation.json](validation.json).
Use its patch in another clean upstream checkout. The Android patch already
contains its applicable compatibility changes, so do not apply both patches.
