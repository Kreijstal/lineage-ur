# Design and maintenance

This is an integration layer for LineageOS, with the source build retained as the
reference. It is not an independent replacement for Soong.

## Soong fork

The companion fork is
[Kreijstal/android_build_soong](https://github.com/Kreijstal/android_build_soong),
branch `lineage-ur-23.2`, based on upstream `lineage-23.2` commit
`9aa045a2aef10b8089e32e847fed26d9aa3d61be`. The small downstream patch adds opt-in
`system_build_tool` and `cc_packaged_library_host` selection. `soong.json` records this baseline and feature
status; [system tools](system-tools.md) and [host libraries](host-libraries.md)
describe configuration and limitations. Android target compilation reuse uses
the opt-in `target_package` library property; see the
[target package documentation](../lineage/target-libraries/README.md).

Use the fork for generic opt-in integration that existing module declarations
cannot express cleanly. Keep normal upstream source builds as the default.
System-tool selection must use explicit compatibility policies, resolved paths
and tool identity rather than a distro name or executable presence alone.

The optional `manifests/lineage-ur-soong.xml` removes the upstream project and
adds the fork at the same `build/soong` path. Changing only a remote with
`extend-project` would retain the upstream project name in the repository URL;
the replacement must select `Kreijstal/android_build_soong` explicitly.

For each upstream update:

1. Fetch the new upstream `lineage-23.2` revision in the fork checkout.
2. Rebase the small downstream patch stack and inspect the resulting diff.
3. Run focused Soong tests and the relevant source/prebuilt build comparisons.
4. Update the recorded base and optional manifest together after validation.

The manifest's `base-rev` guard stops selection if the checkout's upstream
manifest has moved beyond the reviewed baseline. Do not add or sync this
override in a checkout with an active build.

## Two dependency roles

Host tools execute on the build PC. Compatible distro packages may supply them;
Android-specific tools still need packaged builds or source compilation.

Target libraries are linked into Android outputs. Packages for these components
must match the Android architecture, Bionic interfaces, module variant and
platform configuration. Their binaries are build inputs on the PC, not programs
that need to execute there.

## Package identity

A component record starts from `templates/component.json`. Compatibility inputs
must eventually cover the source revision and patches, toolchain, generated
headers, relevant configuration and the actual dependency inputs. Native code,
Java and Rust will need different artifact and metadata handling. The initial
template is a record format, not a complete cache-key or ABI-validation scheme.

Package version equality and resolved ELF symbols do not by themselves prove
behavioral compatibility. Record the consumer rebuilds and functional tests
required for each replacement. Treat packaging and a change in implementation
or upstream version as separate review units.

## Staying close to upstream

- Follow a pinned LineageOS manifest; keep upstream source and build definitions
  authoritative for the baseline.
- Maintain recipes and adapters here, with small component-specific patches.
- Derive dependency metadata from the resolved build where possible rather than
  maintaining a second handwritten dependency graph.
- Compare the LineageOS baseline, original library upstream and local changes
  separately. Git subtree extraction is useful for components inside larger
  repositories; many Android projects are already separate repositories.
- On an upstream update, rebuild or source-build invalidated components rather
  than retaining a stale binary to keep the packaging layer working.
- Validate selected packages against source-built consumers. Add wider platform
  and physical device tests as the replacement scope expands.

## Repository publication

The intended layout follows TUR: recipes in Git, binary packages in GitHub
Releases, and signed APT metadata describing downloadable artifacts. Index
hosting and any redirector must agree with the package URLs in that metadata.

`repo.json` reserves the `lineage/` recipe collection and the planned binary
repository URL. The first experimental Android object bundles are manually
published as [GitHub release assets](https://github.com/Kreijstal/lineage-ur/releases/tag/target-libraries-r8q-20261017),
with SHA-256 checksums, compatibility metadata and runtime reports. They are
compressed archives for the guarded build-checkout installer, not Debian/APT
packages or flashable ROMs. There is no automated publisher, signed APT index,
or build-time downloader. CI checks metadata and host selectors, including small
compiled C consumers; it neither builds Android nor uploads packages or deploys
a Pages site.

The reference mechanisms are:

- [TUR recipe and repository configuration](https://github.com/termux-user-repository/tur/blob/master/repo.json)
- [Termux dependency download and source fallback](https://github.com/termux/termux-packages/blob/master/scripts/build/termux_step_get_dependencies.sh)
- [TUR publication scripts](https://github.com/termux-user-repository/dists/tree/master/scripts)
- [Soong source/prebuilt selection](https://android.googlesource.com/platform/build/soong/+/refs/heads/main/android/prebuilt.go)
- [repo local manifests](https://gerrit.googlesource.com/git-repo/+/HEAD/docs/manifest-format.md#local-manifests)

## First milestone

Choose one small component, pin its working source build and required variants,
then demonstrate a packaged replacement and a source fallback in an isolated
checkout. Record exact commands and outcomes before enabling it in a ROM build.
