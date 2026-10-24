#!/usr/bin/env python3
"""Test the fork with reference checkout dependencies and an isolated Go cache."""

import argparse
import os
from pathlib import Path
import re
import subprocess


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, required=True)
    parser.add_argument("--soong-root", type=Path, required=True)
    parser.add_argument("--out-dir", type=Path, default=Path("artifacts/soong-tests"))
    parser.add_argument("--lz4-snapshot", type=Path, help="also check a prepared LZ4 package Android.bp")
    parser.add_argument("--system-tools-snapshot", type=Path, help="also check the generated system-lz4 Android.bp")
    parser.add_argument("--boringssl-snapshot", type=Path, help="also check the exported BoringSSL shared pair Android.bp")
    parser.add_argument("--c-libraries-overlay", type=Path, help="also check the six pinned C host library adapters")
    parser.add_argument("--target-overlay", type=Path, help="also check Android target object packages")
    parser.add_argument("--swiftshader-package", type=Path, help="also check the generated ARM64/Bionic Vulkan HAL package")
    parser.add_argument("--termux-libraries", type=Path, help="also check independent Termux target library adapters")
    parser.add_argument("--context-variables", type=Path, help="print target context instead of running tests")
    parser.add_argument("--context-out-dir", default="out")
    parser.add_argument("--context-source-dir", help="reference checkout path; prints the checkout-independent app context")
    parser.add_argument("--run", default="^(TestSystemBuildTool.*|TestPackagedHostLibrary.*|TestPackagedTarget.*|TestPackagedSharedTarget.*|TestTargetPackage.*|TestPrebuilt.*|TestAndroidPackagedApp.*)$", help="focused Go test name pattern")
    args = parser.parse_args()
    source = args.source_root.resolve()
    soong = args.soong_root.resolve()
    out = args.out_dir.resolve()
    go = source / "prebuilts/go/linux-x86/bin/go"
    if not go.is_file() or not (soong / "go.work").is_file():
        parser.error("need a synced reference checkout and the separate Soong fork")
    # `go test` discovers every Go file, while Soong bootstrap uses explicit
    # lists. Verify that the tested integration is also compiled by Soong.
    for package, files in {
        "android": ["target_package.go", "target_package_test.go"],
        "cc": ["packaged_target.go", "packaged_binary.go", "packaged_target_test.go",
               "packaged_target_overlay_test.go", "packaged_binary_test.go"],
        "apex": ["packaged_target_test.go", "packaged_binary_test.go"],
        "java": ["packaged_app.go", "packaged_app_test.go"],
    }.items():
        blueprint = (soong / package / "Android.bp").read_text()
        for filename in files:
            if '"' + filename + '"' not in blueprint:
                parser.error(package + "/" + filename + " is missing from Soong bootstrap inputs")
    # Rebase upstream's relative workspace paths onto the reference checkout,
    # replacing only its Soong module with our fork. Write nothing to that tree.
    def resolve(match):
        token = match.group()
        path = soong if token == "." else (source / "build/soong" / token).resolve()
        return str(path)
    workspace = re.sub(r"(?<!\S)\.{1,2}(?:/[^\s]+)?(?=\s|$)", resolve, (soong / "go.work").read_text())
    out.mkdir(parents=True, exist_ok=True)
    work = out / "go.work"
    work.write_text(workspace)
    env = os.environ | {"GOWORK": str(work), "GOCACHE": str(out / "cache"),
                        "GOPROXY": "off", "GOTOOLCHAIN": "local", "GOENV": "off", "GOMAXPROCS": "2"}
    env.pop("ANDROID_BUILD_TOP", None)
    if args.lz4_snapshot:
        env["LINEAGE_UR_LZ4_TEST_SNAPSHOT"] = str(args.lz4_snapshot.resolve())
    else:
        env.pop("LINEAGE_UR_LZ4_TEST_SNAPSHOT", None)
    if args.system_tools_snapshot:
        env["LINEAGE_UR_SYSTEM_TOOLS_TEST_SNAPSHOT"] = str(args.system_tools_snapshot.resolve())
    else:
        env.pop("LINEAGE_UR_SYSTEM_TOOLS_TEST_SNAPSHOT", None)
    if args.boringssl_snapshot:
        env["LINEAGE_UR_BORINGSSL_TEST_SNAPSHOT"] = str(args.boringssl_snapshot.resolve())
    else:
        env.pop("LINEAGE_UR_BORINGSSL_TEST_SNAPSHOT", None)
    if args.c_libraries_overlay:
        env["LINEAGE_UR_C_LIBRARIES_TEST_OVERLAY"] = str(args.c_libraries_overlay.resolve())
    else:
        env.pop("LINEAGE_UR_C_LIBRARIES_TEST_OVERLAY", None)
    if args.target_overlay:
        env["LINEAGE_UR_TARGET_TEST_OVERLAY"] = str(args.target_overlay.resolve())
    else:
        env.pop("LINEAGE_UR_TARGET_TEST_OVERLAY", None)
    if args.swiftshader_package:
        env["LINEAGE_UR_SWIFTSHADER_PACKAGE"] = str(args.swiftshader_package.resolve())
    else:
        env.pop("LINEAGE_UR_SWIFTSHADER_PACKAGE", None)
    if args.termux_libraries:
        env["LINEAGE_UR_TERMUX_LIBRARIES"] = str(args.termux_libraries.resolve())
    else:
        env.pop("LINEAGE_UR_TERMUX_LIBRARIES", None)
    if args.context_variables:
        subprocess.run([str(go), "run", "./cmd/target_package_context", "--variables", str(args.context_variables.resolve()),
                        "--out-dir", args.context_out_dir,
                        *(["--source-dir", args.context_source_dir] if args.context_source_dir else [])],
                       cwd=soong, env=env, check=True)
        return
    test_packages = ["./android", "./genrule", "./cc", "./java"]
    if args.target_overlay or args.swiftshader_package:
        test_packages.append("./apex")
    subprocess.run([str(go), "test", "-p", "2", *test_packages,
                    "-run", args.run, "-count=1"],
                   cwd=soong, env=env, check=True)


if __name__ == "__main__":
    main()
