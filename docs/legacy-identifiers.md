# Legacy Animan identifiers and refactoring options

Audit date: 2026-10-26. Scope: the current working tree's tracked source,
configuration, tests and documentation, excluding generated build trees. This
is a code inventory, not an inspection of users' private settings or credentials.

## Download destination change implemented

- Desktop engine: `~/Downloads/AnimeLab`, unless `ANIMAN_DOWNLOAD_DIR` is set.
- Native desktop launcher: the same default; a saved `downloadDir` wins over the
  environment default.
- Android: ongoing downloads still use private `files/downloads`. Newly published
  media uses `Downloads/AnimeLab`; providers which reject subtitle MIME types in
  Downloads use `Movies/AnimeLab` for separate subtitle files.
- Android's default-destination label and French/English settings text agree with
  the actual export location. The native folder name is centralized in
  `StorageAccess.MEDIA_DIRECTORY`.
- Existing files are not moved. Task paths, custom directories, persisted SAF
  grants, successful export URIs and pending-export recovery records remain
  intact. Retrying an already successful Android export reuses its recorded URI,
  even if that file is in the old folder, rather than making another copy.
- Docker's explicit `/downloads` mount and shared accounts' isolated `downloads`
  directories retain their configured locations.
- The change takes effect in rebuilt desktop/Android packages. It does not update
  already installed binaries or migrate a user's explicitly configured old path.

## First compatibility stage implemented

The runtime reads `ANIMELAB_*` before the corresponding `ANIMAN_*` variable. An
explicit empty modern value also wins. Engine, launcher and private-worker
settings share the dependency-light `animelab.environment` resolver. Controlled
child overrides set both aliases so an inherited modern setting cannot override
a selected port or an account's private storage. Reload behavior is unchanged.
The check runner removes both prefixes from its isolated test environment.

Browser local-storage preferences now use `animelab_theme`, `animelab_lang`,
`animelab_pinned_sources` and `animelab_default_source`. Missing new keys are copied
from the old keys without deleting them or replacing an existing modern value.
A read-only profile can continue using its old values. Language/session cookies,
API headers, private-data paths, Android application identity and signing secrets
remain stable during this first stage; a private-data move requires a separate
backup/recovery migration. Build/signing environment variables remain legacy
interfaces in this phase.

## Components and services still using the old name

| Area | Remaining identifiers | Main implementation locations | Why renaming needs care |
| --- | --- | --- | --- |
| Engine configuration and startup | `ANIMAN_*` environment variables | `animelab/config.py`, `run.py`, `run.sh`, `desktop.py`, `animelab/desktop/options.py`, `animelab/shared/__main__.py` | Existing launch scripts and configured environments depend on these names. `ANIMAN_RELOAD` behavior must remain unchanged. |
| Database and private application data | `~/.animan`, `animan.sqlite3` | `animelab/config.py`, `animelab/desktop/state.py`, `animelab/desktop/launcher_model.py`, `animelab/shared/workers.py`, `android_runtime.py` | Library, accounts' state, jobs, launcher configuration, lock/runtime files and backups must be located consistently. |
| Extensions | `~/.animan/extensions` | `animelab/services/extension_service.py` | A blind directory rename makes installed extensions disappear. This path is currently hard-coded separately from config. |
| HTTP session persistence | `# Animan route:` cookie-file metadata | `animelab/services/source_http.py` | The marker binds saved cookies to their proxy route; changing only the reader or writer would invalidate existing sessions. |
| Browser preferences | `animan_theme`, `animan_lang`, `animan_pinned_sources`, `animan_default_source` | `frontend/src/components/AppTopbar.vue`, `frontend/src/views/SettingsView.vue`, `frontend/src/stores/sourcePreferences.ts`, `frontend/src/utils/locale.ts` | Users could lose theme, language, pinned sources and preferred source. |
| Language cookie routing | `animan_lang` | `run.py`, `animelab/routers/i18n.py`, `animelab/shared/gateway.py` | The browser, engine and shared gateway must agree on forwarding, setting and clearing it. |
| Android local authentication | `X-Animan-Session`, `animan_android_session` | `animelab/android_security.py`, `android/app/src/main/java/com/animan/app/MainActivity.kt`, Android instrumentation | Kotlin and Python must agree; a cosmetic migration must not relax token validation. |
| Public API metadata | `X-Animan-API-Version` | `animelab/api_errors.py` | External clients may read the header. Its spelling is distinct from the actual API version. |
| Diagnostic internals | `_animan_safe`, `animan_session` redaction pattern | `animelab/diagnostics.py` | Renaming log markers is easy, but redaction should continue recognizing legacy secrets. |
| Media pipeline | `.animan-sub-`, `.animan-mux-` temporary prefixes | `animelab/services/download_stages/media.py` | Cosmetic names; do not rename a file still in use by a running media job. |
| TMDB requests | `User-Agent: Animan/2.0` | `animelab/services/tmdb_service.py` | Easy branding cleanup; keep independent from source browser fingerprints. |
| Android installation and bridges | `com.animan.app`, `com.animan.nativeprobe` | Android Gradle configuration, Kotlin packages, ProGuard, manifests, `android_runtime.py`, release inspectors | Installation ID, generated bindings, reflection/JNI bridge names and validation tools have different migration requirements. |
| Android stored preferences | `animan_exports`, `animan_storage` | `NativeHooks.kt`, `StorageAccess.kt`, instrumentation | These contain export recovery records and folder grants. Keep or migrate them before changing names. |
| Android UI/resource and service internals | `Theme.Animan`, `return_to_animan`, `animan-downloads`, `Animan:downloads`, `AnimanService`, `AnimanEngine`, thread names | Android resources, manifest, `VerificationActivity.kt`, `DownloadService.kt`, `EngineHost.kt`, `MediaBridge.kt` | Resource names and logging are cosmetic. Notification channel IDs preserve user notification preferences. Displayed return-button text already says AnimeLab. |
| Desktop distribution identity | `com.animan.desktop` | `animelab.spec` | Changing bundle identity can alter how the OS recognizes an installed application. |
| Docker and Compose | `ANIMAN_*`, `/data/.animan` | `Dockerfile`, `compose.yaml`, `scripts/docker_smoke.py` | Existing volumes must be read after upgrades; container mount points need not match product branding. |
| CI, signing and package validation | `ANIMAN_ANDROID_*`, `ANIMAN_FFMPEG_BINARY`, `ANIMAN_FFPROBE_BINARY`, legacy asset aliases, `animan-release.p12`, `CN=Animan` | `.github/workflows/*`, Android Gradle, `scripts/android_*.py`, `scripts/desktop_release.py` | Secrets must be migrated in GitHub separately from source edits. Do not regenerate or replace the signing certificate for a cosmetic rename. The local signing helper is legacy tooling, not the requested release path. |
| Development/test tooling | `animan_arm_api_*`, `animan-strip-*`, `animan-package-check-*`, `animan-uml.zip`, `fixtures.animan.invalid` | Build/probe scripts, `desktop.py`, `android_runtime.py`, test fixtures | Usually low-risk, but update consumers and expected artifact names together. |
| Comments and historical documentation | Old project paths, product references, dated release assets | Service comments, docs, tests | Keep historical filenames and release notes accurate; distinguish history from current instructions. |

The Python package itself is already `animelab`; restoring or retaining an
`animan` import package is not necessary. Generated copies under
`android/app/src/main/python/` are refreshed by Gradle's `syncPythonSource` task;
edit the root sources rather than maintaining a second hand-edited engine.
The checkout directory `animan-python` is a local filesystem name, not an import
namespace or repository identity.

## Refactoring options

### 1. Preserve compatibility identifiers; clean cosmetic names

Rename stale comments, TMDB product identification, resource names, thread/log
labels and temporary prefixes. Keep storage and wire identifiers stable.
This is the smallest change and has the lowest migration risk, but `animan` will
remain in technical identifiers indefinitely. This turn only changes the default
media destination; the other cleanups above are recommendations.

### 2. Gradual compatibility migration — recommended

Use one contract for each kind of identifier instead of a global text replacement:

1. Introduce one dependency-light path/settings resolver shared by the engine,
   launcher and extension loader. Avoid importing the engine just to render the
   launcher. Read `ANIMELAB_*` first, fall back to `ANIMAN_*`, and define the
   precedence when both are present. Apply aliases consistently to child workers,
   scripts, Docker and build tools. Preserve reload defaults and values.
2. Migrate browser preferences by reading new keys first, copying old keys only
   when new values are absent, and writing the new names. Include all theme,
   language and source keys; test older browser profiles and shared logout.
3. Add new API header/cookie spellings with a documented compatibility period.
   Update browser, Kotlin and gateway together. Accept legacy authentication only
   with the same token checks; reject conflicting tokens. Continue redacting both
   names. Cookie-file route markers should accept both historical and new forms.
4. Make a private-data migration opt-in or versioned, with backup, exclusive lock,
   interrupted-migration recovery and verification. Handle custom DB/cache paths,
   SQLite WAL, extension files, cookie jars, account isolation, launcher state and
   references to absolute task paths. Never create an empty new library and call
   that a successful migration. Keep old media locations readable without moving
   them automatically.
5. Keep Android's installed `applicationId = com.animan.app` and the existing
   signing identity. If desired, refactor the Kotlin `namespace`/packages and
   resource names separately, updating bridge lookups, R/binding imports,
   ProGuard, manifests and APK inspections in the same change. Retain preference
   store and notification-channel identifiers unless a tested migration exists.
6. Change GitHub secret names through a coordinated workflow transition with a
   fallback, without printing their values. Continue building/signing APKs in
   GitHub Actions. Remove old aliases only after installed-version upgrades and
   all supported launch modes have been verified.

Required evidence: fresh-install and old-profile tests; paused download resume
from the old path; no duplicate Android exports; persisted SAF access; proxy-bound
cookies retained; shared-account isolation; Windows/macOS/Linux packaged startup;
Android update over the previous signed APK. Compilation alone does not establish
that an on-device upgrade preserves state.

### 3. Rename every identifier immediately

This produces the cleanest text search, but breaks existing environments,
preferences, volumes and clients unless every migration is shipped atomically.
Changing Android's application ID creates a separate application identity; it is
not a simple in-place update of the existing install. This approach is not
recommended for the current project. Old release URLs, certificate identities and
historical documentation should not be rewritten merely to eliminate a word.

## Reproduce the inventory

```sh
git grep -n -i animan -- animelab frontend/src android scripts .github \
  Dockerfile compose.yaml animelab.spec run.py desktop.py run.sh
git grep -n -i animan -- docs tests README.md
```

These commands search the working versions of tracked files, so the list evolves
as the remaining compatibility migrations are implemented. Ignored caches,
installed dependencies, copied build sources and private runtime data are outside
this audit. An old directory name in a generated file is not evidence of a second
maintained Python package.
