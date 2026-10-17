# Reusing packaged host libraries

`cc_packaged_library_host` extends reuse to native C static and shared libraries,
with exported headers, link dependencies and source fallback. It is opt-in via
`LINEAGE_USE_PACKAGED_HOST_LIBS=true` and supports Linux x86-64/glibc hosts.
Android device variants continue to use their source definitions. The current
scope does not include target Bionic libraries or arbitrary C++ ABIs.

The package preparer does not choose libraries from `/usr/lib` by name. A recipe
must supply a reviewed manifest describing the artifacts, headers, configuration
and exact dependency versions. Distro artifacts can be imported through this
format after validation; we do not infer ABI compatibility from their presence.

## Preparing a package

Start with `templates/host-library-package.json`. Put `package.json` beside the
package's `lib/` and `include/` directories. Replace all placeholder hashes with
SHA-256 values for the actual files and record the exact source revision,
compiler identity and configuration. Inventory every required header, including
generated and transitive headers owned by this package. Omit `static` or `shared`
if the package provides only one linkage variant.

The preparer checks every inventoried file, native object architecture and
shared-library SONAME. Static archives must contain regular x86-64 ELF objects;
thin archives and LLVM bitcode are rejected. Shared artifacts must be named
`<module>.so` with that same SONAME. Packages may set the boolean
`unique_host_soname: true` to preserve Android's `<module>-host.so` naming
instead (without appending `-host` twice). The generated Soong adapter uses
the same property; binaries and SONAMEs are never rewritten. Libraries using
versioned SONAMEs, other custom stems or special runtime layouts require a dedicated adapter. The preparer uses
`readelf` for shared-library inspection (`--readelf` can select an explicit tool).

Dependencies are pinned inside the parent package, for example:

```json
"dependencies": {
  "libdependency": {
    "sha256": "SHA256_OF_DEPENDENCY_PACKAGE_JSON",
    "linkage": "static",
    "reexport_headers": true
  }
}
```

Declare each dependency in the selection policy too. The preparer requires its
exact manifest hash, requested linkage variant and complete dependency closure.
Missing, corrupt or mismatched dependencies send the parent back to source.
Dependency cycles are configuration errors. Runtime libraries supplied by glibc
remain host dependencies; this is not a complete runtime isolation mechanism.

## Selecting packages in an experimental checkout

Keep the original source modules and use the optional Soong fork manifest in a
separate, idle Android checkout. Copy `templates/host-library-policy.json` to a
local policy and fill in the package manifest path, its reviewed SHA-256 and the
appropriate existing Soong licenses. Relative manifest paths are resolved from
the policy directory. A hash pins the entire manifest, including its file hashes
and dependency requirements.

```sh
python3 tools/select_host_libraries.py \
  --policy /path/to/local-host-libraries.json \
  --output /path/to/experimental/android/external/example/lineage-ur-generated

# In the experimental Android checkout, after envsetup/lunch:
LINEAGE_USE_PACKAGED_HOST_LIBS=true m your_host_consumer
```

The generated directory must be in the same Soong namespace as the matching
source modules, with access to their licenses. By default all policy modules are
emitted in one directory. Use repeatable `--module NAME` arguments to emit only
selected modules while validating and staging their dependency closure. This
supports separate adapters under each source directory without duplicate module
declarations. Regenerate the complete set together when dependencies change;
availability checks on local snapshot copies do not coordinate other adapters.
Existing `prebuilt_<module>`
definitions must be reconciled before adding another replacement.

The helper writes hash-named snapshots, `Android.bp` and `selection.json`.
Snapshots include manifests and headers as well as binaries. Selection logs
record package decisions, rejection reasons and provenance. It never overwrites
a handwritten `Android.bp`; identical inputs preserve timestamps.

Normal static/shared consumers receive native Soong library providers, exported
include directories and declared dependency/header reexports. `package_files`
contains the full transitive snapshot inventory. Soong tracks their existence,
so deleting a header, artifact or dependency snapshot switches back to source
on the next graph generation. Unsupported linkage variants retain their source
implementation. Host sanitizer builds also retain source implementations.

## Compatibility and maintenance

The hashes verify identity, not semantic compatibility. Source revision,
toolchain and configuration fields record the reviewed recipe; this adapter
does not derive a complete cache key from Soong's resolved graph or automatically
prove those fields match a new upstream build. Revalidate and repin packages
when the source baseline, compiler, flags or ABI requirements change. Validate
consumers against source builds before enabling packages in a ROM build.

Run preparation before the build, never concurrently with it. File checksums
are verified at preparation time; later manual modification of a snapshot is
not a supported update mechanism. Rerun preparation after package changes.
Removing the opt-in flag selects source again. Explicit source/checkbuild goals
may still compile the original sources.

No binary package publishing or automatic downloading is enabled. The tests
compile and run real C consumers against staged static and shared fixtures and
exercise the Soong selection graph separately. Full ROM build savings have not
been measured.

`lineage/liblz4/` includes a working experimental recipe for the pinned
LineageOS LZ4 sources, with compression/decompression checks against both
packaged linkage variants. See [its commands and configuration](../lineage/liblz4/README.md).

`lineage/boringssl/` exports the reference build's host shared BoringSSL pair
without recompilation and validates certificate-verified TLS 1.3 against both
the selected packages and reference libraries. See [its scope and commands](../lineage/boringssl/README.md).

`lineage/host-libraries/` prepares pinned bzip2, zlib, Expat, Zstandard, PNG and
JPEG packages, including static libraries and a directory-correct integration
overlay. See [the recipes, validation and limits](../lineage/host-libraries/README.md).

## Validation

`make check` runs package selection checks and compiles/runs small host consumer
fixtures; it requires native `cc`, `ar` and `readelf` in addition to Python/Git.
`python3 tools/test_soong.py --source-root /path/to/reference-android
--soong-root /path/to/android_build_soong` checks the fork's library/tool
selection and prebuilt regressions in an isolated Go workspace.
Add `--lz4-snapshot /path/to/generated/selection` to load the actual generated
LZ4 `Android.bp` and verify both host consumer dependencies through Soong.
