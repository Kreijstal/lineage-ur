# Component recipes

Add one directory per component, containing its recipe, component metadata,
patches and validation notes. `liblz4/` contains an experimental native host
recipe and a static/shared consumer check; no recipes are automatically enabled.
`lz4-system/` documents reuse of the distro CLI and supplies its reference
validation helper; regular CLI selection does not rebuild LZ4.
`boringssl/` exports the reference host shared libraries and checks a verified
TLS 1.3 exchange against both the packages and original outputs.
`host-libraries/` packages bzip2, zlib, Expat, Zstandard, PNG and JPEG with
static-library consumers and per-component integration adapters.
`target-libraries/` packages Android/Bionic compilation objects for the six C
libraries plus four Skia/Perfetto libraries, with source-module defaults,
guarded integration and ARM64 runtime checks.
`swiftshader/` packages a pinned upstream Android/Bionic ARM64 Vulkan HAL using
Termux's LLVM 21, with an opt-in Soong adapter and compute execution checks.

Start from the existing LineageOS implementation. Record its repository and
commit, exact inputs, required variants and dependencies before attempting an
upstream-version substitution. Use `templates/component.json` as a checklist;
replace all placeholders before treating a component as buildable.

Termux/TUR-style `build.sh` recipes are a packaging model. Their builder is not
vendored here, and Android platform libraries may require the platform toolchain
and private headers rather than the stock Termux NDK build environment.
