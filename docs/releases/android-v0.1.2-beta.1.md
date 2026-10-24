# AnimeLab 0.1.2 — Android beta 1

Android 10+ · ARM64 · package `com.animan.app` · version code **216**.

## Changes since 0.1.1 beta 1

- Imported source upgrades now replace recipes atomically, use version-specific APK caches and preserve source domains.
- Catalogue filters, ordering and pagination are corrected. Supported imported sources use the shared declarative recipe interpreter in place of redundant per-source runtime adapters.
- French Anime's recipe is kept separate from Hanime; contaminated saved recipes are repaired so the correct source catalogue and filters are used.
- The embedded HTTP server validates incoming hosts. Default loopback access used by the Android interface remains authorized.
- Locked dependencies, CI quality checks and centralized offline DNS improve reproducibility and regression coverage. The project is licensed under **GPL-3.0-only**.
- Existing responsive layouts, resumable downloads, local playback, storage permissions and export handling remain included.

## Install or update

Install `AnimeLab-v0.1.2-Android-arm64.apk` over the existing app. Version code **216** is higher than the previous release's **215**. The application ID and production signing identity are preserved, allowing a normal update to retain the library, settings and storage grants without an uninstall.

GitHub Actions compiles and signs the APK with the existing identity, validates the signing certificate and native alignment, runs emulator checks, and publishes only after those gates succeed. The release includes `Android-build-info.json` and `SHA256SUMS.txt` for source provenance and integrity verification. Source code is available from the `android-v0.1.2-beta.1` tag in this repository.

## Validation limits

Publication requires API **29, 30 and 35** checks. API 29 exercises the shared native media/storage probe. API 30/35 exercise the ARM64 Python/Vue engine through native translation; media/storage probes use the shared JNI implementations built for x86_64.

**This APK has not been tested on a physical phone.** Browser checks and emulator tests do not certify every Android WebView or the complete ARM64 media pipeline on real hardware. External sources may require manual verification, be unavailable or remain unsupported by the recipe interpreter. This Android release remains a **prerelease**.
