# Experimental host LZ4 package

This recipe packages the clean, pinned LineageOS `external/lz4` C sources into
native x86-64/glibc static/shared libraries, headers and license material. It
records source revision, compiler hash/version, flags and file checksums. It is
independent of the Termux builder and any distro's package manager.

```sh
python3 lineage/liblz4/build.py --source-dir /path/to/reference/android/external/lz4 \
  --output artifacts/packages/liblz4
python3 tools/select_host_libraries.py --policy artifacts/packages/liblz4/policy.json \
  --output /path/to/experimental/android/external/lz4/lib/lineage-ur-generated
python3 lineage/liblz4/check.py \
  --selection /path/to/experimental/android/external/lz4/lib/lineage-ur-generated
```

Then enable `LINEAGE_USE_PACKAGED_HOST_LIBS=true` in the experimental Android
checkout to test its host consumers. The original Android library stays in the
build; the generated adapter replaces matching host variants only.

`--cc` and `--ar` accept explicit tool paths. Defaults use the native host tools.
The build uses `-O2 -fPIC -std=c99`, not the complete Soong-resolved flag set.
Consumer validation is required before adopting this recipe in production;
matching source revision alone does not prove ABI/configuration compatibility.
Use [the package format and maintenance notes](../../docs/host-libraries.md).

Locally exercised with LineageOS source revision
`2fe12748754b3c4f6456b63207fe39d9bffa56c2` (LZ4 1.10.0). Both static and shared
snapshot consumers passed the compression/decompression roundtrip. This is a
host package check; it does not establish full ROM compatibility.

Outputs are local experimental packages; this recipe does not upload releases
or publish a package index.
