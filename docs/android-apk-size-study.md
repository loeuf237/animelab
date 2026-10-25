# Android APK size study

The study below records the original October 15 baseline and simulations.
The A11 implementation now enables native-symbol stripping, R8/resource
shrinking, public-asset deduplication and removal of the unused Android XML stack.
See [A11 implementation and validation](architecture/a11-validation.md) for actual
build comparisons and device-test coverage. The historical estimates below are
not measurements of the new build.

Measured on 15 October 2026 against the signed, ARM64-only Android 0.1.0 beta
(version code 212, application source `c1d47fc5bacdf737ca49ed666051049654986ef8`).
The published APK is **77,688,756 bytes: 77.69 MB / 74.09 MiB**.
SHA-256: `8e1f9113cfb040ace1da088c79030bbca7e6955fe46b8426d97ade856be70a6c`.

This is an analysis, with stripping and compression experiments on copies. No
production dependency, build flag, signing identity or published APK was changed.
The objective is to keep the complete embedded Python engine and Vue interface.

## What occupies the APK

All MB figures below use 1 MB = 1,000,000 bytes. Contributions are actual ZIP
payload sizes, including the compression already applied inside Chaquopy's `.imy`
archives. Nested entries must not be added to their parent archive a second time.

| Component | APK contribution | Share |
| --- | ---: | ---: |
| Python dependencies (`requirements-common.imy`) | 27.37 MB | 35.2% |
| Native libraries under `lib/arm64-v8a/` | 28.77 MB | 37.0% |
| Remaining Python runtime archives and bootstrap | 8.21 MB | 10.6% |
| Android bytecode (`classes.dex`) | 8.72 MB | 11.2% |
| Application Python, legacy web assets and Vue (`app.imy`) | 2.66 MB | 3.4% |
| Android resources, other entries, ZIP/signing/alignment overhead | 1.96 MB | 2.5% |

The native group includes **14.66 MB of FFmpeg libraries and JNI bridges**; it
also contains CPython, OpenSSL, SQLite and the C++ runtime. The complete Vue
distribution contributes approximately **1.00 MB inside `app.imy`**, including
images; its bundled JS/CSS assets contribute only 0.335 MB. Frontend work alone
will therefore have a limited effect on this APK.

Large Python packages, measured inside the requirements archive:

| Package | Compressed payload |
| --- | ---: |
| `curl_cffi` | 8.21 MB, plus 0.50 MB for its private C++ library |
| `yt_dlp` | 5.66 MB |
| `sqlalchemy` | 3.45 MB |
| `lxml` | 1.95 MB, plus its native XML/XSLT dependencies |
| `pydantic_core` | 1.90 MB |

## Recommended first changes

**1. Strip debug information and unused static symbols from native wheel copies.**
The upstream `curl_cffi/_wrapper.abi3.so` is 24.01 MB before ZIP compression. Its
ELF sections contain 16.42 MB of debug information and 1.21 MB of static symbol
tables. These are shipped even though the application is not debuggable.

Using LLVM 21.1.8 on a copy produced these results. The ZIP comparison uses
DEFLATE level 6, which reproduces the original wrapper's compressed size exactly.

| Wrapper variant | ELF file | Compressed APK payload | Payload saving |
| --- | ---: | ---: | ---: |
| Current | 24,010,785 B | 7,993,991 B | — |
| `--strip-debug` | 7,433,968 B | 3,016,784 B | 4,977,207 B |
| `--strip-unneeded` | 6,383,992 B | 2,750,969 B | 5,243,022 B |

All allocated sections retained identical names, addresses, types, flags,
alignment, sizes and content hashes, including `.text`, `.dynsym`, `.dynstr` and
`.dynamic`. This is static evidence; the stripped variant has **not** been tested
inside a rebuilt Android application. LLVM documents the distinction between
[debug stripping and removal of unneeded symbols](https://llvm.org/docs/CommandGuide/llvm-strip.html).

Applying `--strip-unneeded` to the other symbol-bearing libraries adds about
0.59 MB, for a combined simulated payload reduction of **5.84 MB**. Most of the
97 libraries are already stripped. Broad stripping of every binary is unnecessary.
Compression and stripping savings are alternatives for the same bytes, so they
must not be blindly added together.

Implementation should preserve the official wheel's provenance, regenerate wheel
`RECORD` hashes if repacking it, retain license material and keep unstripped
symbols outside the APK for diagnostics. Recheck ELF load/RELRO alignment and
exercise actual Python imports, TLS, browser impersonation and JNI after building.

**2. Deduplicate web images and manifests.**
Seven identical-content entries account for **882,510 B** of redundant compressed
payload. About 0.66 MB is a second set of assets under `frontend/dist/` while the
same files are served from `animelab/static/`. The remaining major duplicate is
`icon-maskable.png`, currently byte-identical to `icon-512.png`.

Remove redundant Android build inputs and preserve the `/img/*` and manifest URLs
used by the SPA and PWA. Verify the actual URL mapping rather than deleting the
legacy static directory: `run.py` still mounts it and the legacy template routes.

**3. Enable R8 and Android resource shrinking, with bridge keep rules.**
The release configuration explicitly disables minification and does not enable
resource shrinking. The affected DEX/resources currently occupy **10.18 MB**;
that is an upper bound on their combined contribution, not a promised saving.
The gain requires a release-build comparison. R8 will not shrink Python packages
or native code hidden inside Chaquopy archives.

Start with AGP 8.8's `isMinifyEnabled = true`, `isShrinkResources = true` and its
default optimized ProGuard configuration. Preserve Chaquopy/FFmpeg consumer rules
and the classes/methods called by Python through string-based `jclass`, including
`MediaBridge`, `CryptoBridge`, `NativeHooks`, `VerificationBridge` and
`StorageAccess`. Otherwise, a smaller build could break downloads or permissions.
See the [official R8 configuration guide](https://developer.android.com/topic/performance/app-optimization/enable-app-optimization).

## Dependency cleanup to validate next

**`lxml` and XML/XSLT libraries: 2.64 MB of candidate payload.** The only direct
`lxml` import found in application source is in the Android instrumentation probe.
The production scrapers explicitly use BeautifulSoup's built-in `html.parser`.
This makes removing `lxml`, `chaquopy-libxml2` and `chaquopy-libxslt` from the
Android dependency set a strong candidate. Confirm optional dependency behavior
and every built-in/imported source adapter before removal; update the probe to
exercise the production parser. Do not count the shared C++ runtime as removable
without checking its remaining users. Licenses for removed dependencies can be
updated only after confirming they are absent from the complete APK.

**Tests, build sources and unused dialects: smaller secondary opportunities.**
`greenlet` embeds 0.214 MB of tests/platform headers/C++ build sources. Non-SQLite
SQLAlchemy dialects total 0.564 MB, while Android configures SQLite. Prune only
after dependency/import tests, preserving runtime metadata and license notices.
Replacing the entire ORM or FastAPI solely to save space would have a much larger
maintenance and regression cost.

**Narrow extraction: 0.194 MB of duplicated Python source.**
`extractPackages("animelab")` includes `.py` files alongside `.pyc` files. Investigate
whether automatic data-file extraction is sufficient for the static/template
directories. Verify filesystem paths, Jinja templates and startup before changing
this option. Chaquopy documents [extraction and bytecode packaging](https://chaquo.com/chaquopy/doc/current/android.html#packaging);
this option also affects startup time and installed storage.

## Larger reductions and their tradeoffs

**Compressing native libraries: 16.57 MB less APK payload in a simulation.**
The current 28.77 MB of top-level native libraries are stored uncompressed for
direct loading. DEFLATE level 9 reduces their payload to 12.20 MB. Android's
`jniLibs.useLegacyPackaging = true` can use compressed packaging, but Android then
extracts the libraries to a second location. The simplified native-only storage
balance is approximately **12.20 MB more installed disk usage** than direct
loading: compressed APK bytes plus 28.77 MB extracted. Installation time and
temporary disk requirements also need measurement. This conflicts with a goal
of low installed footprint. Keep ELF 16 KB compatibility in either configuration.
Google explicitly documents the [installed-storage tradeoff](https://developer.android.com/guide/practices/page-sizes#update-the-packaging-of-your-shared-libraries).

Compressing the current DEX payload separately saves 5.48 MB at DEFLATE level 9.
AGP 8.8 exposes [`dex.useLegacyPackaging`](https://developer.android.com/reference/tools/gradle-api/8.8/com/android/build/api/dsl/DexPackaging#useLegacyPackaging()).
Measure startup and installed storage on API 29/30/35 before considering it.
This saving overlaps with R8, which would first reduce the DEX itself.

**A custom FFmpeg build could reduce the current 14.66 MB media component.**
Animan already uses `ffmpeg-kit-min`, the smallest standard feature family in
the [maintained project's artifact matrix](https://github.com/ffmpegkit-maintained/ffmpeg#the-full-artifact-matrix--free-on-maven-central).
A further reduction requires a purpose-built configuration, retaining MP4/TS/MKV,
HLS-related remuxing, subtitle handling, FFprobe and the decoders needed for file
integrity checks. [FFmpeg supports selecting individual decoders](https://www.ffmpeg.org/ffmpeg-all.html#Decoders).
Measure the actual streams served by the sources, then benchmark a custom build;
there is no measured saving yet. Removing decoding indiscriminately would weaken
the existing corrupt-media checks. Maintain a separate test fixture generator if
test-only encoders/filters are excluded from production.

**Trimming `yt_dlp` or downloading an engine later changes capability/distribution.**
Extractors account for 4.95 MB of `yt_dlp`'s 5.66 MB compressed payload. An allowlist
could save space but would limit fallback extraction for imported extensions and
new hosts. Deferring a media/engine module to first use reduces the initial APK
but leaves total installed functionality dependent on a later download and adds
versioning, integrity and recovery work. Neither is the first choice for the
requested complete embedded engine.

**ABI splitting and AAB are not the main opportunity here.**
The production APK already includes only `arm64-v8a`, with no x86 test application
or instrumentation APK embedded. Chaquopy also cautions that its native packaging
limits automatic splitting gains. An AAB can be useful for future Play delivery,
but does not by itself remove this single-ABI Python payload. See
[Chaquopy's size guidance](https://chaquo.com/chaquopy/doc/current/faq.html#how-can-i-make-my-app-smaller).
System WebView is already used; there is no bundled Chromium engine to remove.

## Practical targets and verification

Native stripping plus complete identical-asset deduplication removes about
**6.72 MB of payload**, placing the same-functionality APK near **71 MB**, subject
to rebuild, alignment/signing overhead and Android tests. If the `lxml` dependency
audit passes, its additional 2.64 MB puts the arithmetic projection near **68 MB**,
before any measured R8 gain. These are projections, not newly built APK sizes.

Prioritize native stripping and R8, then asset/dependency cleanup. Evaluate custom
FFmpeg only after those measurements. Keep compressed-native packaging as a
separate smaller-download experiment, with installed size reported alongside it.

For each candidate compare APK bytes, installed size after first launch, startup
time and memory. Run the Python engine/import/TLS probes and the media/storage
matrix: direct/HLS resume, proxy changes, AES, subtitle muxing, file verification,
MediaStore export and persisted folder permissions. Include a physical ARM64
Android 10 device: this study does not establish runtime validity of optimized
binaries and does not extend the published build's device-test coverage.

To reproduce the inventory and optional stripping experiments without modifying
the APK:

```bash
python3 scripts/android_apk_size.py \
  build/android-signed-release/Animan-v0.1.0-Android-arm64.apk \
  --output build/apk-size-study \
  --llvm-strip /path/to/android-ndk/toolchains/llvm/prebuilt/linux-x86_64/bin/llvm-strip
```

Omit `--llvm-strip` for an inventory/compression-only run. The report is written to
`build/apk-size-study/measurements.json`; stripping creates `.so` copies there,
never an installable APK. The original signed APK's hash remains unchanged.
