# Experimental host BoringSSL reuse

This recipe exports the already built **Linux x86-64/glibc shared** `libcrypto`
and `libssl` from a completed LineageOS reference build. It preserves their
`libcrypto-host.so` / `libssl-host.so` filenames and SONAMEs, copies the matching
headers, and pins the crypto package as a dependency of SSL. It does not rebuild
BoringSSL with a different standalone configuration.

The package records the source revision, binary and header hashes, compiler
hashes, resolved Ninja commands, product variables, completed build state and
pinned source manifest. These describe the observed reference build; they are
not an independently verified build attestation. It includes BoringSSL and
statically incorporated libc++ license material. No publication is configured.

## Export and validate

Run from the Lineage UR repository. Use completed, idle reference outputs;
the exporter reads the checkout and executes `ninja -t commands` only. It never
executes the recorded build commands, writes into Android sources/outputs,
or changes the active ROM configuration. The output directory must be new and
outside the Android checkout. The pinned manifest must agree with a clean
`external/boringssl` repository, and the completed state must name the same
checkout and product.

```sh
python3 lineage/boringssl/export.py \
  --source-root /path/to/android \
  --reference-out /path/to/android/out \
  --product lineage_r8q \
  --build-state /path/to/reference/state.json \
  --reference-manifest /path/to/reference/manifest-pinned.xml \
  --output artifacts/packages/boringssl-host

python3 tools/select_host_libraries.py \
  --policy artifacts/packages/boringssl-host/policy.json \
  --output artifacts/boringssl-host-selection

python3 lineage/boringssl/check.py \
  --selection artifacts/boringssl-host-selection \
  --reference-out /path/to/android/out

python3 tools/test_soong.py \
  --source-root /path/to/android \
  --soong-root /path/to/android_build_soong \
  --boringssl-snapshot artifacts/boringssl-host-selection \
  --run '^TestPackagedHostLibraryGeneratedBoringSsl$'
```

`check.py` revalidates snapshot hashes, compiles a C consumer against the packaged
headers, and runs a SHA-256 known-answer test, a TLS 1.3 handshake with certificate
and hostname verification, and bidirectional application data. It checks the
dynamic loader's actual paths so an unrelated installed SSL library cannot
silently satisfy the test. `--reference-out` runs the same consumer against the
original shared libraries for comparison. It opens no network sockets.

`make check-boringssl BORINGSSL_REFERENCE_OUT=/path/to/android/out` runs Python
syntax checks, the focused package-selector regression tests, and both runtime
consumers using `artifacts/boringssl-host-selection`. Override
`BORINGSSL_SELECTION` to test another prepared selection.

The Soong test loads the generated adapters and snapshots. It checks opt-in
selection, disabled selection retaining source, the SSL-to-crypto dependency,
distinct host library filenames, and unchanged device variants. It validates
the dependency graph; it does not compile an entire Android consumer or ROM.

Locally exercised at source revision
`1e3b727981831886a0910cd9e82d5bbee4cc7029` on 2026-10-17. Packaged and reference
runtime consumers passed. The generated-adapter Soong test passed with selection
both enabled and disabled.

## Integration boundary

In a **separate, idle experimental checkout** with the Soong fork installed,
generate the selection under `external/boringssl/lineage-ur-generated` so it shares
the source namespace and can access `external_boringssl_license`. Keep the source
modules. Opt in with `LINEAGE_USE_PACKAGED_HOST_LIBS=true` and build the relevant
host consumer. Removing the flag retains source selection.

This first package deliberately covers shared host variants only. Host static,
Linux/musl, Windows, ARM hosts, device/Bionic, APEX, recovery and FIPS-specific
variants retain their existing source builds. Many Android tools link BoringSSL
statically, so this experiment does not yet eliminate their compilation. No full
ROM build-time saving is measured or claimed.

Export again and revalidate after changes to the pinned source, compiler,
configuration or runtime dependencies. The selector verifies the reviewed package
and dependency hashes, but does not automatically compare the package's provenance
against every consumer's resolved Soong configuration. An unchanged API is not
proof of compatible configuration or behavior. Distro OpenSSL is not substituted.
