# Design and maintenance

This is an integration layer for LineageOS, with the source build retained as the
reference. It is not an independent replacement for Soong.

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
repository URL. Publication is not configured. The initial CI checks metadata
only; it neither builds Android nor uploads packages or deploys a Pages site.

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
