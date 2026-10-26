# Android distribution and validation

The [0.1.4 release](https://github.com/loeuf237/animelab/releases/tag/v0.1.4)
includes a signed ARM64 APK alongside the desktop archives, build provenance and
checksums. It is a standalone application, not a wrapper requiring a desktop
server. Full ARM64 physical-device validation remains pending for this APK;
earlier A11 device validation is documented separately below.

`release-desktop.yml` orchestrates the unified release and calls
`release-android.yml` with the exact same tag. The reusable Android workflow
compiles, signs and tests the APK before exposing its public release artifact.
Publication waits for both the Android validation matrix and all desktop builds.

The current target is Android 10+ / ARM64, Python 3.13 and Chaquopy 17.1.0.
`android/requirements.txt` pins the runtime. `scripts/android_native_wheels.py`
builds cffi 2.0.0 and pydantic-core 2.41.5 against a pinned Chaquopy toolchain;
curl_cffi 0.16.3 uses its official ARM64 wheel. The wheel stays unchanged; A11
strips debug/static symbols from copies inside the generated requirements archive.
Android source adapters use BeautifulSoup with `html.parser`, so lxml and its
native XML/XSLT libraries are no longer installed. Desktop wheels are never
renamed into Android artifacts. AES uses javax.crypto rather than an outdated
Android cryptography/OpenSSL wheel.

`release-android.yml` builds Vue, the shared backend, native media libraries and
instrumentation. Without a production key it builds a **validation APK with a
temporary debug identity** and refuses publication. With the release identity it
tests the signed release APK. Both paths inspect the actual packaged engine and
ELF page alignment and RELRO mapping. Android 11/15 Google APIs x86 guests test
the ARM64 Python/Vue runtime via native translation; a separate test application
executes the **same Kotlin media bridge** using genuine x86_64 FFmpeg libraries.
It also tests the real storage/export code on Android 10, 11 and 15; the Android
10 x86 guest cannot execute the full ARM64 engine through native translation.
These are separate checks, not a completed ARM64 download-pipeline test. The
software ARM64 guest probe is retained for diagnosis: current SDK system
services crash during boot in that environment. A physical ARM64 test is needed.

Run locally with Python 3.13, JDK 17+, Android SDK 35, NDK and native build tools.
LLVM `llvm-strip` must be on `PATH`, or `ANIMAN_LLVM_STRIP` must point to the NDK's
LLVM strip executable. `ANIMAN_BUILD_PYTHON` can select a Python 3.13 executable:

```bash
python3.13 scripts/android_native_wheels.py
cd frontend
npm ci
npm run build
cd ../android
./gradlew assembleValidation assembleValidationAndroidTest
```

The compiled Vue distribution must exist before Gradle synchronizes Python
resources. Test an installed target with:

```bash
python scripts/android_instrumentation.py \
  android/app/build/outputs/apk/validation/app-validation.apk \
  android/app/build/outputs/apk/androidTest/validation/app-validation-androidTest.apk \
  build/android-test-results
```

Release and validation builds enable R8 and resource shrinking. Python/JNI bridge
names are kept explicitly; native allocation sections and segment mappings are
checked before stripping. Original binaries and hashes are retained under
`android/app/build/reports/native-optimization/`, and R8 maps under
`android/app/build/outputs/mapping/`. CI uploads these diagnostic artifacts.
The source synchronization removes only byte-identical public copies served
from `animelab/static`; it retains SPA assets and all extractors. The legacy Jinja
frontend and its runtime dependency are no longer included.
Native libraries remain uncompressed for direct loading.

The A11 source build passed the complete direct/HLS/subtitle/export probe on a
physical Android 10 ARM64 phone using a separate test package. Its DEX and all
Python/native engine entries are identical to the normal signed deliverable.
The test APK is 61.31 MB; the normal signed APK is 61.36 MB. Installed app and
data after first render measured 97.37 MB versus 137.52 MB for the unoptimized
control. These are clean-test-data snapshots, not the size of a personal library.
See [A11 validation](architecture/a11-validation.md) for evidence and limits.

For a controlled comparison, `-Paniman.optimizeApk=false` disables stripping,
asset deduplication and R8/resource shrinking. To also restore an older dependency
set for a benchmark, point `ANIMAN_ANDROID_REQUIREMENTS` to a saved requirements
file. These overrides are for measurements; the release workflow requires the
optimized packaging checks in `scripts/android_release.py --optimized`.

On a personal phone, add `-Paniman.isolatedValidation=true` to build an independent
`com.animan.app.a11test` application, labelled **AnimeLab A11 test**. Pass
`--package com.animan.app.a11test` to the instrumentation script. This keeps the
production library and preferences separate. Use a fresh test installation for
each size measurement. Instrumentation records `footprint.json` after the first
render, before media probes: APK bytes, installed application bytes and private
data (including cache). Do not add the cache figure to the data figure again.
Compare these device measurements separately from APK ZIP bytes.

CI signing uses the encrypted Actions secrets `ANIMAN_ANDROID_KEYSTORE_BASE64`,
`ANIMAN_ANDROID_STORE_PASSWORD`, `ANIMAN_ANDROID_KEY_PASSWORD` and
`ANIMAN_ANDROID_KEY_ALIAS`. The workflow restores the key temporarily, exposes
passwords only to the Gradle build step, and removes the temporary key even after
failure. It verifies the production certificate on both APKs and checks it again
before publication. The existing identity is retained for in-place updates. The
`android/keystore/` directory is ignored; never commit or publish its contents.
Preserve a secure local backup of the release identity for updates. Starting with `v0.1.4`, the APK is published in the same release as desktop assets.
Legacy `android-v...-beta.N` tags remain available for standalone Android betas.

Local signing avoids transferring the private identity to GitHub:

```bash
python scripts/android_sign_release.py build/android-candidate build/android-signed \
  --build-tools "$ANDROID_HOME/build-tools/35.0.0"
```

The validation variant inherits release flags and is not debuggable. The script
verifies those flags and input hashes, signs both app and instrumentation with a
dedicated RSA identity, and preserves build provenance. The identity and its
configuration stay in the ignored, private `android/keystore/` directory. Signed
APKs must be tested again before publication. No private key is a release asset.

As an alternative to CI signing, `android-assemble-signed.yml` reconstructs the already signed APK
from checksummed transfer chunks and checks its signature and alignment.
`android-signed-validate.yml` reads its Actions artifact with read-only permissions
and tests the signed app and matching instrumentation on API 30 and 35, plus
the native media/storage probe on API 29. Transfer
chunks and instrumentation are excluded from the public release. The default
`release-android.yml` now performs compilation, signing, the same API matrix and
publication directly, without local signing or transfer chunks.

Release checks cover native imports, Chrome/TLS, SQLite, rendered Vue, loopback
authentication, Activity recreation, Java AES and byte-checked MediaStore export.
The native media probe covers actual encode, TS/MP4 remux, subtitle mux, decode
and failure reporting on x86_64; shared direct/HLS resume logic has Python
regression coverage. Logs and screenshots are Actions artifacts. Metadata must
record both test ABIs and `full_arm64_media_pipeline_tested: false` while this
limitation remains. Real-device power management and playback are not validated.

Media copies in the private library and shared Downloads occupy space twice.
Private partials/cookies/database are excluded from Android backup. Engine state
(including installed extensions and imported proxy lists) uses persistent private
storage rather than the evictable Android cache. No broad
storage permission is requested. Android 15's dataSync time budget and background
start restrictions are handled by pausing the queue, not by bypassing OS policy.

FFmpeg/FFprobe are native JNI libraries, with the LGPL package and corresponding
source link recorded in [the release notes](releases/android-v0.1.0-beta.1.md).
APK checks inspect Python extension libraries inside Chaquopy's nested archives
as well as normal `lib/arm64-v8a` libraries.
Native media commands are serialized; diagnostic collection is bounded before
storage rather than by truncating an already unbounded FFmpegKit session log.
A native worker which fails to stop after cancellation prevents subsequent
commands until the application restarts.

## Storage permissions and recovery

Use **Settings → Storage → Android permissions** to check access, authorize a
folder through the system picker, return to `Downloads/AnimeLab`, or change
notification permissions. Downloads remain in private app storage while they
are transferring, merging or being verified. Shared files appear after export.
The MediaStore default requires no broad storage permission on Android 10+.
A chosen folder uses a persistent read/write URI grant rather than an arbitrary
filesystem path; if access is revoked, choose and authorize the folder again.
Android 11+ does not allow selecting the Downloads root in the folder picker;
choose a subfolder or use the MediaStore default.

Completed tasks offer **Export to storage** to retry a failed export or copy the
private download into a newly selected folder. The private copy is retained on
export failure. In the current source checkout (A02), the verified video is
`COMPLETED` independently of `exportStatus`: `PENDING`, `EXPORTING`, `EXPORTED`
or `EXPORT_FAILED`. Destination, confirmed URIs, attempts, date and errors are
persisted. **Retry export** reads the private files without fetching the media
again. Interrupted exports return to `PENDING`; unresolved exports remain visible
and are preserved by bulk cleanup. Legacy tasks without export evidence remain
`NOT_REQUESTED` and show an unknown export state. These changes require rebuilding
the app; they do not update the previously published beta APK.

A subtitle mux failing at the publication stage with `Errno 13`
is handled by reserving a filename and renaming, without Android hard links.
Some Android 11 MediaProvider versions only accept subtitle MIME types in
`Movies/AnimeLab`; AnimeLab falls back there for separate subtitles and displays
that location. A folder authorized through the system picker keeps videos and
subtitles together, independently of MediaStore's MIME/directory restrictions.
