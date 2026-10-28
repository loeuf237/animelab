# Implementation ledger

The user authorized implementation on 2026-10-28. The Android original-APK
requirement in EXIGENCES_ANDROID_APK.md is mandatory. This ledger distinguishes
source implementation from remote build/device evidence; it is not a release certificate.

## Current work

- E01: catalogue refresh preserves installed recipes, installed metadata and
  removed packages/history. Four reproduction cases converted to regression tests.
- E02–E05: migration 12 separates offers/artifacts/sources/operations/trust;
  multiple repositories, enable/disable, conservative refresh and numeric version
  ordering implemented. JSON/Protobuf/gzip/external-list reader implemented.
- E15 in progress: actual Aniyomi host API vendored at the study pin with Apache
  license and attribution, dedicated Android runtime service, package installer
  sessions and shared-package discovery/trust/class loading implemented in source.
- Remote compilation is being introduced in android-extensions.yml. APK builds
  and emulator validation must run in GitHub Actions; no local APK build.
- Remaining: complete Python/native source integration and UI, APK corpus and
  instrumented evidence, operation lifecycle, full contracts/backups/CI and all
  outstanding E01–E18 acceptance conditions. No claim of full compatibility yet.

## Evidence recorded so far

- 46 targeted Python tests passed after the catalogue/lifecycle changes.
- Android code is not yet build-validated or device-validated.
- Existing source helpers were adapted from the exact Aniyomi study commit.
- :extensions runs under the same app UID. It separates crashes/lifecycle but is
  not an OS security sandbox; only explicitly approved package/version/signers
  can be instantiated. Isolation acceptance remains to be established.
