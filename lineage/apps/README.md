# Packaged leaf apps

Leaf apps are APKs nothing else in the platform compiles against. Clock, Calendar,
Calculator, Recorder, the browser, camera, music, gallery and messaging apps are
examples. This component packages each app's unsigned APK from a completed
reference build and lets that build skip compiling the app again (Java/Kotlin
compilation, R8 and resource processing). The build still signs the APK with its
own key and dexpreopts it against its current boot image.

Each package is a cache of the pinned LineageOS app source, not an independently
built release of the app.

## Selection and fallback

The paired Soong fork adds `android_packaged_app`. It behaves like
`android_app_import` and replaces the source `android_app` with the same name
only when `LINEAGE_USE_PACKAGED_APPS=true` and all of the following match:

- The manifest SHA-256 and every packaged file.
- Every checked-in input of the reference APK. Ninja's `inputs` tool recorded these
  across the app, its static libraries, SDK stubs and the host tools built from
  source (aapt2, R8 wrappers, ...). Every tracked file in the app's repository is
  also included, so `Android.bp` changes count.
- The product configuration. The hash normalizes the checkout and output paths and
  omits values Soong derives while loading, so another checkout of the same
  product matches.
- Java/dex-related build environment variables such as `RUN_ERROR_PRONE`,
  `EMMA_INSTRUMENT` and `ANDROID_JAVA_HOME`, and whether SDK stubs are built from
  API text (`m --build-from-source-stub` changes it).

Anything else keeps the source app.

Soong checks the source inputs when it analyzes the build, but they don't trigger
a new analysis: around 45,000 inputs per app overflow Ninja's deps log as Soong
regeneration dependencies. Instead, each packaged app gets a build-time check that
hashes its inputs again whenever one changes. If a source file changes after
selection, the build fails and names the file:

```text
packaged app DeskClock: source inputs changed after Soong selected it; remove its lineage-ur-app adapter or unset LINEAGE_USE_PACKAGED_APPS
packages/apps/DeskClock/src/com/android/alarmclock/AnalogAppWidgetProvider.java: FAILED
```

The next Soong analysis then selects the source app for that module. The packaged
files themselves are regeneration dependencies, so replacing or removing a
package re-runs selection. A few inputs have paths Soong can't represent (gson's
`$Gson$Preconditions.java` and one other per app): `apply.py` checks these, Soong
doesn't.

The adapter carries the source app's resolved Make properties: partition,
`overrides`, `required` and the uses-library lists that rebuild the same
class-loader context. The exporter rejects an app whose class-loader context
would differ.

Some integration details:

- Auto-generated RROs are still created from the source app. The packaged app
  requires them from Make only, as the source app does.
- The packaged app provides the source app's merged manifest as `{.manifest.xml}`.
- Instrumentation tests (`instrumentation_for`) keep compiling against the source
  app's classes.

Packaged apps are limited to apps that are:

- signed with the default certificate,
- not privileged,
- installed under `app/<name>/<name>.apk`,
- containing code,
- without separately installed JNI libraries.

Platform-signed apps, priv-apps and apps such as Gallery2 and LatinIME, whose JNI
libraries are installed as separate modules, keep building from source.
SystemUI, Settings and Launcher3 are excluded on purpose: they compile against
the framework's hidden APIs, so a package of them is only valid for one framework
build.

## Packaged r8q apps

Packaged from the 2026-10-16 `lineage_r8q` (bp4a, userdebug) reference build. The
saved time is the step time that reference build recorded for each app's own
compilation, resource and R8 steps; signing and dexpreopt still run.

| App | Guarded inputs | Saved step time |
| --- | ---: | ---: |
| Aperture | 42,421 | 22.2 min |
| Twelve | 42,723 | 20.7 min |
| Glimpse | 42,316 | 18.5 min |
| Jelly | 41,728 | 16.6 min |
| DeskClock | 42,219 | 15.0 min |
| Etar | 43,717 | 13.2 min |
| Camelot | 11,758 | 10.5 min |
| Recorder | 11,837 | 9.3 min |
| messaging | 45,054 | 8.4 min |
| ExactCalculator | 11,859 | 5.5 min |
| PhotoTable | 24,663 | 1.9 min |
| ApertureLensLauncher | 9,144 | 1.3 min |

In total that's 2.4 hours of build-step time. These steps run in parallel with the
rest of the build, so the wall-clock saving is smaller and hasn't been measured.
All 12 apps are installed to `product`.

Each package contains the APK, its license texts, the merged manifest, and
`package.json` with the input inventory and source revision. It also holds copies
of the reference product variables, pinned manifest and build state.

## Validation (2026-10-24)

The packages were exported from the reference checkout and installed into a
separate hard-linked copy of it with a fresh output directory. That copy used the
Soong fork, and `apply.py` refused the reference checkout. The reference app
repositories remained clean.

- Full Soong and Kati analysis of `lineage_r8q-bp4a-userdebug` with
  `LINEAGE_USE_PACKAGED_APPS=true` passed. All 12 apps were exported to Make as
  `android_packaged_app`.
- Building the 12 packaged signed APKs from that fresh output directory took
  3 min 43 s (995 steps, including the host tools). Each APK is **byte-identical**
  to the APK the reference build compiled from source and signed. The source
  apps' `javac` steps did not run.
- Editing one DeskClock source file after analysis made the build-time check fail
  with the message above. After the next analysis DeskClock was exported as its
  source `android_app` again, and the other 11 apps stayed packaged.
- The Go tests cover selection, fallback for each checked condition, the
  build-time check, Make-only RRO requirements, the manifest output and
  instrumentation tests.

The dexpreopted install files and a flashed image have not been built or booted
with these packages.

## Download the r8q packages

The [2026-10-24 release](https://github.com/Kreijstal/lineage-ur/releases/tag/apps-r8q-20261024)
holds one archive with `apps-r8q/packages/`, `overlay/` and `inventory.json`, plus
`SHA256SUMS` and `release-manifest.json`.

```sh
mkdir -p artifacts/downloads
gh release download apps-r8q-20261024 --repo Kreijstal/lineage-ur --dir artifacts/downloads
cd artifacts/downloads
sha256sum --check SHA256SUMS
tar --zstd -xf lineage-r8q-apps-20261024.tar.zst -C ..
```

The APKs are unsigned builds of the LineageOS app sources at the revisions
recorded in each `package.json`. The build signs them with its own key. Release
checksums verify the downloaded files; they are not signatures.

## Export from a reference build

```sh
python3 tools/test_soong.py --source-root /path/to/android \
  --soong-root /path/to/android_build_soong \
  --context-variables /path/to/android/out/soong/soong.lineage_r8q.variables \
  --context-out-dir out --context-source-dir /path/to/android

python3 lineage/apps/package.py \
  --source-root /path/to/android --reference-out /path/to/android/out \
  --product lineage_r8q --build-state /path/to/reference/state.json \
  --reference-manifest /path/to/reference/manifest-pinned.xml \
  --context CONTEXT_SHA256_FROM_PREVIOUS_COMMAND \
  --output artifacts/apps-r8q
```

The exporter requires clean, manifest-pinned app repositories and a completed,
idle reference build. It only reads the reference checkout and its Ninja graph.

## Install into a separate checkout

```sh
python3 lineage/apps/apply.py --packages artifacts/apps-r8q \
  --checkout /path/to/separate/android --check-only
python3 lineage/apps/apply.py --packages artifacts/apps-r8q \
  --checkout /path/to/separate/android

# After envsetup/lunch for the same product and release:
LINEAGE_USE_PACKAGED_APPS=true m
```

The installer refuses the reference checkout and requires the Soong fork. It
adds one `lineage-ur-app/` directory beside each app and changes no existing
file. Apps whose recorded inputs differ from the checkout are reported and
skipped. Remove the directories, or unset the flag, to build from source again.

Use the Soong fork revision recorded in `soong.json`. A package from an r8q
reference build only matches checkouts configured for the same product,
release and variant.
