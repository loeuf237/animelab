# AnimeLab is looking for contributors

[Français](contribution-priorities.md) | [English](contribution-priorities.en.md)

We are looking for people to improve AnimeLab through design, Android/Kotlin,
Python/FastAPI, Vue/TypeScript, device testing, translations and documentation.
A mockup, a reproduction scenario or a precise test report is already a useful
contribution.

The items below are **proposed work**, to be refined with contributors. They
are not a list of completed features. Feature and architecture proposals are
welcome.

To participate, open or join an
[issue](https://github.com/loeuf237/animelab/issues), mention the relevant work
area and describe what you would like to take on. You can also connect with the
community in **[Telegram — AnimeLab Group](https://t.me/AnimeLabGroup)** or
contact the maintainer directly at **[Telegram — @loeuf237](https://t.me/loeuf237)**.
Record technical decisions and test results in the issue or PR so other
contributors can find them.

See the [contribution guide](../CONTRIBUTING.en.md) for setup, checks and pull
requests.

## Current starting points — 24 November 2026 (post-v0.2.0)

Release [`v0.2.0`](releases/v0.2.0.md) delivered in-app release download/verification/installation, duplicate-download and path fixes, Anime-Sama BDD support, Codeberg-compatible headers, and light/dark hero contrast fixes.

Start with the [three practical briefs](first-contribution.en.md):
Linux walkthrough #21, theme palette #28, or focused `good first issue` tasks such as #51, #57, #58, #60, #62, #68, #71, #74, or #78.
Ask for help in the chosen issue; an annotated report or mockup is a valid contribution.
Version comparison (#14), the library title filter (#31), and the Android offline report (#32) are already completed.
The sixteen areas below include both existing functionality and remaining work;
read their status before proposing an implementation.

## 1. Redesign the Android loading screen

**Goal:** make startup more pleasant and understandable, with a design that
fits AnimeLab’s identity.

We welcome design proposals followed by an Android implementation. Show the
startup stages the application can actually observe, handle long waits and
offer recovery when startup fails. Avoid invented percentages that give a
misleading impression of progress.

**Expected validation:** mockups and screenshots, readability on small screens,
light/dark themes, accessibility and normal, slow and failed startup tests on
Android. Starting point:
[`MainActivity.kt`](../android/app/src/main/java/com/animan/app/MainActivity.kt).

## 2. Detect and automatically download new versions

**Already available:** version checks, numeric version comparison, stable/beta
filtering, release links, in-app download with progress, `SHA256SUMS.txt`
verification, Android `PackageInstaller` self-updates, and desktop archive
extraction landed in `v0.2.0` in
[`app_updates.py`](../animelab/services/app_updates.py) and
[`startup.py`](../animelab/routers/startup.py), with tests in
[`test_app_startup.py`](../tests/test_app_startup.py). See
[setup and updates](startup-and-updates.md).
**Remaining (#54):** atomic in-place replacement for frozen desktop builds
(with backup/rollback), automatic cleanup of older downloaded update packages,
and an Android "Wi-Fi only" update toggle. Extend the existing service; do not
build a second version comparator.

**Goal:** provide an in-app update flow inspired by Mihon/Aniyomi, starting on
Android: detect a new version, show its changes, offer configurable automatic
downloads and install through the Android installation mechanism.

The module should select the correct package for the platform and architecture,
compare versions correctly and distinguish beta/stable channels. GitHub’s
pre-release status must not be the only criterion: a beta version may be
published as a regular release.

**Expected validation:** test no update, a new version, channels, network errors
and interrupted downloads. Respect network and download preferences, verify
file integrity and signing compatibility before installation, preserve user
data and let Android request its normal installation confirmation. Keep a
downloaded update distinct from an update that has actually been installed.

## 3. Fix duplicate downloads and saved files

**Already available:** PR #33 corrected unnecessary retained final copies.
**Remaining:** use #15 to check whether a distinct duplication case still occurs
on beta.5; record a non-reproduction as such. Do not assume the historical bug
still exists or remove intentional editions/qualities.

**Reported problem:** the same file can be downloaded or saved multiple times
with the built-in **French-Manga** source. Reproduce the case, identify the
responsible stage and check whether other sources are affected.

The fix should cover repeated requests, batch and automatic additions,
concurrent requests, resuming after restart and saving/exporting the final
file. Examine the existing safeguards in
[`download_manager.py`](../animelab/services/download_manager.py) before adding
a parallel mechanism.

**Expected validation:** regression tests showing that the same request does
not create multiple unintended tasks or final copies, including after restart.
Preserve intentionally different downloads: VF/VOSTFR/VO editions, qualities
and output profiles. Do not identify an episode solely by its filename, number
or a temporary video URL. Add cases for French-Manga and the other affected
paths; keep an explicit action for users who want to download again.

## 4. Improve Aniyomi / Anikku / Animiru extension compatibility (Android & PC)

**Already available:** isolated Android APK execution via `:extension-runtime`,
and the cross-platform DEX-to-recipe translation engine for PC/Server/Web in
[`aniyomi_dex_parser.py`](../animelab/services/aniyomi_dex_parser.py),
[`recipe_plans.py`](../animelab/services/recipe_plans.py),
[`recipe_runtime.py`](../animelab/services/recipe_runtime.py), and
[`aniyomi_container.py`](../animelab/services/aniyomi_container.py) (including
Anime-Sama’s new `lien:` / `epsJeton` BDD format added in `v0.2.0`).
**Remaining (#61, #62):** fix broken **Anikku**, **Animiru**, and **Aniyomi**
extensions by improving DEX bytecode/inheritance decoding and recipe operations
(#61 — JSON/GraphQL APIs, POST payloads, filters, external subtitles) and
expanding video hoster extractors (#62).

**Goal:** improve real-world compatibility with Aniyomi/Anikku/Animiru
repositories and extensions across both the Android APK runtime and the
PC/Server recipe translation engine, with reproducible results.

Test already installed packages, repository installation and updates, trust,
multiple sources, search, catalogues, episodes, filters, preferences, video
resolution, playback and downloads. Also verify the WebView session flow and
resuming the extension, without concurrent browser-emulation requests during
verification.

**Expected validation:** a matrix recording AnimeLab version, APK/version,
Android version, device or emulator, successful operations and errors.
Distinguish website blocking from runtime incompatibility. A package being
present does not prove that the complete flow works. Document desktop/server
recipes separately from the Android APK runtime.

Start with the [existing study](studies/aniyomi-anikku/README.md) and
[validation guide](studies/aniyomi-anikku/UTILISATION.md). Test APKs are built
in GitHub Actions; physical-device testing is still needed.

## 5. Create the Tools tab and a subtitle workspace (#17, #18, #66)

**Related issues:** #17 (Tools navigation entry), #18 (subtitle UI mockup),
and **#66** (full Subtitle Workshop). See also area **16 (#67)** for the
PC audio-to-subtitle transcription workshop.

**Goal:** add **Tools** to the navigation bar and bring media tools
together there. The first area is a complete subtitle tool for series or
episodes that have already been downloaded.

The desired flow includes:

- selecting a series or episodes from the library;
- searching for, comparing and downloading matching subtitles, or importing
  them from files;
- selecting the language, episode and edition, previewing, adjusting timing
  and managing tracks and available tools/providers;
- translating subtitles with a **personal API key** for Gemini, DeepL, OpenAI
  or another proposed provider;
- exporting separate subtitles or including them in a video output using
  compatible profiles.

Reuse the subtitle and profile services already present in `animelab/services/`
rather than creating a second independent pipeline. Support navigation on
mobile and desktop.

**Expected validation:** first deliver a complete flow using a local video,
without downloading the video again, then integrate providers. Preserve
originals, cue boundaries and timestamps during translation, flag any style
loss and verify synchronization on export. Keys must remain private and
specific to the user; sending text to a provider must be explicit. Show errors,
quotas and costs reported by the provider, and support cancellation or resuming
processing.

## 6. Add an audio workspace and multi-audio MKV creation

**Goal:** extend Tools with a flow for downloading and editing audio tracks
from sources provided by audio extensions, then combining them with an existing
video into a **multi-audio MKV**.

Start with an architecture proposal defining a supported audio extension,
its data contracts and its differences from a video extension. This
compatibility still needs to be defined and validated.

The intended flow covers discovering and downloading tracks, previewing audio,
matching an episode, selecting languages, adjusting offsets, audio editing and
assembly. A proposal may describe later stages of the editor.

**Expected validation:** a playable MKV containing multiple selectable audio
tracks with correct languages, titles and default track, and verified duration
and synchronization. Reuse existing media contracts, output profiles and
FFmpeg processing; preserve originals. Work in small, testable steps before
extending the tool.

## 7. Redesign the Extensions page

**Already available:** beta.5 has Sources/Extensions navigation, language lists,
pins, search, package preferences and update actions.
**Remaining:** audit the current screens for concrete accessibility, small-screen
or state-clarity problems. #20 now starts from this implementation, rather than
a blank redesign. See also **#52** (source health dashboard and anonymized
broken-source diagnostics) and **#53** (periodic new-episode checks).

**Goal:** improve usability and appearance with inspiration from Mihon/Aniyomi:
clear navigation, readable lists and easy-to-find actions.

Propose mockups for repositories, installed/available extensions, updates,
search and language filters. Make useful states visible: installed, disabled,
trust approval needed, update available, error or verification required.
Clearly distinguish a repository, an extension and the sources it provides.

**Expected validation:** mobile/desktop screenshots, light/dark themes,
accessibility and flows for adding a repository, installing, enabling,
updating and recovering from errors. Visual improvements must preserve
compatibility information and required confirmations. Use the reference as
inspiration while preserving AnimeLab’s identity and respecting the licenses
of any reused elements.

## 8. Improve the README and documentation

**Goal:** help new users install, start and understand AnimeLab, then enable
contributors to reproduce its checks.

We welcome Linux/Windows/Android/macOS guides, current screenshots, examples,
French/English translations and architecture explanations. Clarify the
differences between releases and source checkouts, known limitations,
extensions and troubleshooting. Look for outdated or contradictory information.

**Expected validation:** working links, commands verified on the platforms
claimed and a clear distinction between available, experimental and planned
features. A tutorial followed and corrected by someone new to the project is
particularly useful.

## 9. Create application themes

**Already available:** system/light/dark modes, teal/lavender/ember/AMOLED palettes,
a picker and persistent selection. Start with
[`themes.css`](../frontend/src/themes.css),
[`ThemePicker.vue`](../frontend/src/components/ThemePicker.vue) and
[`appearance.ts`](../frontend/src/stores/appearance.ts).
**Remaining:** document the existing token contract, propose an additional palette
in #28, and validate contrast and fallback behavior. Treat arbitrary theme import
as a separate proposal; reuse the current picker.

**Goal:** let contributors offer themes and let users choose AnimeLab’s
appearance beyond the existing light/dark modes.

Document the existing palette variables and picker integration. Initial
deliverables can be a documented extra palette and mockups, followed by an
integrated theme. Support persistent selection, restoring the default and
consistency across Android, desktop and web screens. Any theme import should
use validated declarative data with resources available offline.

**Expected validation:** screenshots of the player, library, extensions and
settings; readable contrast, focus, error states and text on mobile and desktop.
Verify selection survives restart, invalid palettes fall back to the default,
and existing themes keep working.

## 10. Choose an external folder on first Android launch

**Already available:** beta.4 introduced initial folder selection and beta.5
retains it in [`StartupFlow.vue`](../frontend/src/components/StartupFlow.vue),
using the Android storage bridge.
**Remaining:** #24 now tracks device evidence for cancellation, restart, export,
unavailable folders and revoked grants; #29 proposes wording/recovery improvements
to the actual screen. Do not implement another onboarding flow.

**Goal:** offer a user-selected AnimeLab folder for media, subtitles and exports
on first launch, reusing the folder selection already available in Android
settings.

Validate the existing onboarding step: destination explanation, system
picker, confirmed selection and explicit default. Preserve the persistent
permission and allow changing the folder later. Clearly define exported data;
databases, cookies and secrets remain in private application storage.

**Expected validation:** first launch, picker cancellation, an authorized,
unwritable or unavailable folder, restart and revoked permission. Respect the
Android picker's restrictions and offer a valid folder or the default
destination. Changing the folder must not silently move or delete existing
media; any migration needs an explicit, verified user flow.

## 11. Improve the Android video player

**Related issues:** #25, #30 (portrait/landscape controls audit), **#49**
(external players: mpv, VLC, Android Intent), **#50** (Skip Intro/Outro &
auto-play next), and **#51** (Desktop/Web keyboard shortcuts & Picture-in-Picture).

**Goal:** make playback more comfortable on phones, for streaming and downloaded
files, with accessible touch controls.

Propose and test a better control layout: play/pause, seeking, fullscreen,
orientation, speed, audio, subtitles and next episode. Additional gestures can
be separate small proposals. Reuse existing playback progress and media
contracts; justify any change to the playback engine.

**Expected validation:** small screens, portrait/landscape, usable controls and
menus, position restoration after closing or Activity recreation, decoding
errors and unavailable local media. Check which tracks actually work and state
format/codec limitations explicitly. Include local playback without a network
and preserve desktop/web behavior.

## 12. Improve library management

**Already available:** the non-destructive, accent-insensitive title filter
landed in PR #34; #31 is completed.
**Remaining:** choose one separate improvement such as source/watch-state filters,
sorting or verified local availability. Preserve the current filter and avoid
introducing a broad library migration as a first task. Related workstreams:
**#46** (full portable backup/restore), **#47** (migrate series across sources),
and **#48** (optional AniList / MyAnimeList progress tracking).

**Goal:** make series, episodes and downloaded media easier to find and organize
as the library grows.

Proposals may cover sorting, search, source or watch-state filters, categories,
bulk actions and local availability indicators. Distinguish a favorite, a
library entry and a file that is actually available. Preserve source, episode
and edition identities, playback progress and existing preferences.

**Expected validation:** empty and large libraries, same-name series from
different sources, VF/VOSTFR/VO editions, accented search, restart and bulk
operations with appropriate confirmation. Removing a series from the library
and deleting its files must remain clearly distinct actions. Schema changes
need a lossless migration; local media should remain discoverable offline.

## 13. Improve offline video use on Android

**Goal:** let users open AnimeLab, browse available episodes and play them
without Internet access, with useful metadata retained locally.

Identify startup, library and player network dependencies. Local playback must
not wait for a catalogue, update check or remote stream resolution. Clearly
show episodes that are actually available, their progress, audio tracks and
local subtitles. Support resuming after closing and reconnecting without
duplicating tasks.

**Expected validation:** download first, fully close the app, enable airplane
mode, reopen, browse and play local media with seeking and position restoration.
Also test a deleted file, unavailable external folder and partial download
without advertising them as available. Distinguish private media, exports and
authorized folder URIs; do not promise support for every format.

## 14. Make the Seanime extension engine work reliably on Android (#63)

**Already available:** Seanime JS/TS extensions run on Desktop/Server via
`mini-racer` (V8), and an initial offscreen `WebView` bridge exists in
[`SeanimeJsBridge.kt`](../android/app/src/main/java/com/animan/app/SeanimeJsBridge.kt),
[`seanime_runtime.py`](../animelab/services/seanime_runtime.py), and
[`android_runtime.py`](../android_runtime.py).

**Goal (#63):** fix Kotlin/Chaquopy interop (`@JvmStatic` on `SeanimeJsBridge`
entry points), stabilize the offscreen `WebView` sandbox across Android API
29–35 including R8/ProGuard release builds, ensure full shim parity with
[`seanime_shim.js`](../animelab/services/seanime_shim.js) (`fetch` round-trips,
`store`, TypeScript transpilation), and keep 100% of outbound HTTP traffic
routed through `android_runtime.seanime_fetch`.

**Expected validation:** `seanime_runtime.is_available()` returns `True` in
optimized Android release builds, importing/searching/resolving streams works
on Android, and instrumentation tests validate a Seanime fixture in CI.

## 15. Decode and run CloudStream (.cs3) extensions on PC and Android (#64, #65)

**Goal:** add repository indexing (`repo.json` / `plugins.json`) and `.cs3`
plugin support across platforms:

- **Desktop/Server / PC (#64):** inspect `.cs3` packages (`manifest.json` +
  `classes.dex`) and design/build a safe PC decoding or sandboxed execution
  engine (extending [`aniyomi_dex_parser.py`](../animelab/services/aniyomi_dex_parser.py) /
  [`recipe_runtime.py`](../animelab/services/recipe_runtime.py) or a constrained
  interpreter) without arbitrary host code execution, routing all HTTP requests
  through [`source_http.py`](../animelab/services/source_http.py).
- **Android (#65):** execute verified `.cs3` plugins natively inside the
  isolated `:extension-runtime` worker process behind explicit user trust and
  SHA-256 verification, implementing a `com.lagradost.cloudstream3.*` shim
  bridged to `IExtensionHttp`.

**Expected validation:** short architecture RFC for PC security boundaries,
consistent repository/source metadata across PC and Android, offline fixture
tests for `search` / `load` / `loadLinks`, and an Android instrumentation
fixture test.

## 16. Audio-to-Subtitle transcription workshop on PC — TurboScribe / Whisper (#67)

**Goal (#67):** inside the PC (Desktop/Server) **Tools** workspace (#17), allow
generating time-synced `.srt`/`.vtt`/`.ass` subtitles from downloaded episode
audio tracks using FFmpeg extraction ([`media_tools.py`](../animelab/media_tools.py),
[`output_processor.py`](../animelab/services/output_processor.py)) paired with
pluggable transcription backends:

- **Local offline Whisper** (`faster-whisper`, `whisper.cpp`, or user CLI)
  kept as an optional dependency without bloating PyInstaller or Android packages.
- **External / TurboScribe workflows** (TurboScribe audio export / `.srt`
  re-import flow or Whisper-compatible BYOK API endpoints).

Jobs run in the background with cancellation support and hand off generated
files directly into the Subtitle Workshop (#66).

**Expected validation:** PC-only visibility guard, unchanged original media,
cancellable background jobs, and automated tests with mocked/fixture backends.

## Other open post-v0.2.0 issues

- **Backup, Library & Discovery:** #46 (portable backup/import), #47 (migrate series across sources), #48 (AniList / MyAnimeList sync), #68 (auto-add anime card to library on press — `good first issue`), #75 (weekly Airing Schedule calendar), #77 (local folder / NAS scanner)
- **Player & Navigation:** #49 (external players), #50 (Skip Intro/Outro & auto-next), #51 (keyboard shortcuts & PiP — `good first issue`), #72 (native `.ass`/`.ssa` rendering via JASSUB/libass WASM), #73 (Android TV / D-Pad / gamepad navigation), #74 (opt-in Desktop Discord Rich Presence — `good first issue`)
- **Sources, WebView Verification & Updates:** #52 (source health & anonymized diagnostics), #53 (periodic episode checks & notifications), #54 (atomic desktop updates, cleanup & Wi-Fi only), #69 (Anikku/Mihon-style temporary system WebView verification with auto cookie capture), #70 (PC source verification via WebKitGTK/WebView2/WKWebView & Chromium fallback)
- **Storage, Naming & Community:** #71 (Telegram group prompt on first launch & Settings > About link — `good first issue`), #76 (disk-space dashboard, low-space guard & watched cleanup), #78 (Plex / Jellyfin / Kodi naming templates — `good first issue`)
- **Distribution, Android & Quality:** #55 (macOS hardware validation & `.dmg`), #56 (AppImage/Flatpak & Windows installer), #57 (Vite bundle code-splitting — `good first issue`), #58 (automated i18n checks — `good first issue`), #59 (split oversized core modules), #60 (roadmap docs refresh — `good first issue`), #79 (Android release APK size reduction)

Issues and first tasks for all sixteen areas are linked from the
[contribution tracker #12](https://github.com/loeuf237/animelab/issues/12).

## Propose another idea

These areas do not exclude other relevant proposals. Describe the need, an
example use case, affected platforms, tradeoffs and a first verifiable step.
An architecture redesign should explain which problems it solves and how to
migrate existing data and behavior.

People who test, design, translate and document are as welcome as those who
write code. Choose a scope you can validate and state where you need help.
