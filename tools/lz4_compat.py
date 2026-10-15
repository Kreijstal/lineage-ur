"""Functional checks for the host lz4 commands used by Android builds."""

import argparse
import hashlib
import json
from pathlib import Path
import random
import subprocess


class Lz4CompatibilityError(ValueError):
    pass


def corpus():
    return {
        "empty": b"",
        "ramdisk-like": b"070701LineageOS ramdisk entry\0" * 2048,
        "incompressible": random.Random(8250).randbytes(65536),
        "legacy-block-boundary": b"\0" * (8 * 1024 * 1024 + 113),
    }


def run(executable, flags, payload, timeout):
    result = subprocess.run([str(executable), *flags], input=payload,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    if result.returncode:
        raise Lz4CompatibilityError(
            f"{Path(executable).name} {flags}: exit {result.returncode}: "
            + result.stderr.decode(errors="replace")[:500])
    return result.stdout


def check(executable, timeout=5, reference=None):
    executable = Path(executable).absolute()
    reference = Path(reference).absolute() if reference else None
    modes = (
        ("frame", ["-9"], b"\x04\x22\x4d\x18"),
        ("android-ramdisk", ["-l", "-12", "--favor-decSpeed"], b"\x02\x21\x4c\x18"),
        ("legacy-level9", ["-l", "-9"], b"\x02\x21\x4c\x18"),
    )
    records = []
    for mode, flags, magic in modes:
        for name, payload in corpus().items():
            compressed = run(executable, flags, payload, timeout)
            if not compressed.startswith(magic):
                raise Lz4CompatibilityError(f"{mode}/{name}: wrong compression format magic")
            if run(executable, ["-d", "-c"], compressed, timeout) != payload:
                raise Lz4CompatibilityError(f"{mode}/{name}: roundtrip mismatch")
            record = {"mode": mode, "corpus": name, "args": flags,
                      "input_bytes": len(payload), "compressed_bytes": len(compressed),
                      "input_sha256": hashlib.sha256(payload).hexdigest(),
                      "compressed_sha256": hashlib.sha256(compressed).hexdigest()}
            if reference:
                if run(reference, ["-d", "-c"], compressed, timeout) != payload:
                    raise Lz4CompatibilityError(f"{mode}/{name}: reference could not decode system output")
                baseline = run(reference, flags, payload, timeout)
                if not baseline.startswith(magic) or run(executable, ["-d", "-c"], baseline, timeout) != payload:
                    raise Lz4CompatibilityError(f"{mode}/{name}: system could not decode reference output")
                record["reference_compressed_sha256"] = hashlib.sha256(baseline).hexdigest()
                record["byte_identical"] = baseline == compressed
            records.append(record)
    # The default modern frame includes a checksum. A decoder must reject its
    # corruption instead of silently reporting successful decompression.
    frame = bytearray(run(executable, ["-9"], b"checksum validation" * 100, timeout))
    frame[-1] ^= 1
    result = subprocess.run([str(executable), "-d", "-c"], input=frame,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=timeout, check=False)
    if result.returncode == 0:
        raise Lz4CompatibilityError("corrupt frame checksum was accepted")
    report = {"profile": "android-lz4-v1", "cases": records, "corrupt_frame_rejected": True}
    if reference:
        report["reference_sha256"] = hashlib.sha256(reference.read_bytes()).hexdigest()
    return report


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--reference", type=Path)
    parser.add_argument("--report", type=Path)
    parser.add_argument("--timeout", type=float, default=5)
    args = parser.parse_args()
    try:
        report = check(args.candidate, args.timeout, args.reference)
    except (Lz4CompatibilityError, OSError, subprocess.SubprocessError) as error:
        parser.exit(1, f"LZ4 compatibility failed: {error}\n")
    if args.report:
        args.report.write_text(json.dumps(report, indent=2) + "\n")
    print(f'LZ4 compatibility: PASS ({len(report["cases"])} cases, '
          + ("bidirectional reference checks, " if args.reference else "")
          + "corrupt-frame rejection)")


if __name__ == "__main__":
    main()
