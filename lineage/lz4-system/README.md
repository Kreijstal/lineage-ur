# Reusing the system LZ4 executable

Use the installed distro `lz4` for the host CLI, without rebuilding its CLI or
private library dependency just to supply that executable. Other consumers can
still require source or packaged `liblz4`; this policy replaces only `lz4`.

Install your distribution's LZ4 CLI package. In a separate, idle Android checkout
with the Soong fork and this integration repository selected:

```sh
python3 vendor/kreijstal/lineage-ur/tools/select_system_tools.py \
  --policy vendor/kreijstal/lineage-ur/policies/lz4.json \
  --output external/lz4/programs/lineage-ur-generated

# After the normal envsetup/lunch:
LINEAGE_USE_SYSTEM_TOOLS=true m lz4
```

The selector searches `PATH` before Soong sanitizes it. It accepts a native
Linux x86-64 executable, checks the LZ4 1.x version banner, then functionally
tests the snapshot with Android's commands. Version presence alone cannot
select it. Failed probes, incompatible behavior or missing executables emit
a source-fallback adapter. Keep the original `external/lz4` source modules.

The `android-lz4` compatibility profile runs twelve cases: empty input,
ramdisk-like input, deterministic incompressible bytes and input crossing the
legacy 8 MiB block boundary, each compressed with:

- `-9` (modern frames; used by LineageOS's device-tree compression task).
- `-l -12 --favor-decSpeed` (Android ramdisk compression).
- `-l -9` (legacy compression).

It verifies format magic, byte-exact decompression, and corrupt modern-frame
checksum rejection. Reports and binary hashes are written in `selection.json`.
The tests derive their command contract from `build/make/core/Makefile`,
`build/soong/filesystem/ramdisk_16k.go`,
`system/tools/mkbootimg/repack_bootimg.py`, and
`vendor/lineage/build/tasks/dt_image.mk` in the pinned checkout.

Make's `LZ4` variable and Soong's usual host-tool consumers resolve to the
selected installed host `bin/lz4`. Hardcoded vendor prebuilt paths require
their own adapters. `lz4c` and basename-sensitive aliases need separate policies;
they are not implicitly substituted. See [system tool limits](../../docs/system-tools.md).

## Reference comparison

The following builds a CLI reference once for validation. Normal tool selection
does not compile it. The helper reads a clean, pinned `external/lz4` checkout,
uses the translation units listed in its Android build files, and writes all
outputs outside that checkout. This is a native reference build, not a full
Soong platform build.

```sh
python3 lineage/lz4-system/build_reference.py \
  --source-dir /path/to/reference/android/external/lz4 \
  --output artifacts/lz4-reference
python3 tools/lz4_compat.py --candidate /usr/bin/lz4 \
  --reference artifacts/lz4-reference/lz4 \
  --report artifacts/lz4-reference/comparison.json
```

Each executable must decode the other's output to the original bytes. Compressed
byte identity is recorded as additional evidence, not required for compatibility.
Locally, the selected system LZ4 1.10.0 snapshot passed all twelve cross-decoding
cases against source revision `2fe12748754b3c4f6456b63207fe39d9bffa56c2`; all
twelve compressed outputs were also identical.

To exercise the actual generated adapter through Soong's graph tests:

```sh
python3 tools/test_soong.py --source-root /path/to/reference/android \
  --soong-root /path/to/android_build_soong \
  --system-tools-snapshot /path/to/generated/system-lz4 \
  --run '^(TestSystemBuildTool.*|TestPrebuiltTool)$'
```

The generated-adapter test covers selection, opt-out, deleted-snapshot source
fallback, and Make's `lz4` executable name. Full ROM build savings and complete
device-image compatibility have not been measured.
