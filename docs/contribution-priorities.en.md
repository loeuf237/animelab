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
area and describe what you would like to take on. To contact the maintainer
directly: **[Telegram — @loeuf237](https://t.me/loeuf237)**. Record technical
decisions and test results in the issue or PR so other contributors can find them.

See the [contribution guide](../CONTRIBUTING.en.md) for setup, checks and pull
requests.

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

## 4. Validate Aniyomi/Anikku extension integration

**Goal:** verify and improve compatibility with original extension APKs on
Android, with reproducible results.

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

## 5. Create the Tools tab and a subtitle workspace

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

**Goal:** let contributors offer themes and let users choose AnimeLab’s
appearance beyond the existing light/dark modes.

Define a palette format reusing existing style variables, previews and a theme
selector. Initial deliverables can be a documented palette and mockups, followed
by an integrated theme. Support persistent selection, restoring the default and
consistency across Android, desktop and web screens. Any theme import should
use validated declarative data with resources available offline.

**Expected validation:** screenshots of the player, library, extensions and
settings; readable contrast, focus, error states and text on mobile and desktop.
Verify selection survives restart, invalid palettes fall back to the default,
and existing themes keep working.

## 10. Choose an external folder on first Android launch

**Goal:** offer a user-selected AnimeLab folder for media, subtitles and exports
on first launch, reusing the folder selection already available in Android
settings.

Add this step to initial onboarding: explain the destination, open the system
picker, confirm the selection or keep the default. Preserve the persistent
permission and allow changing the folder later. Clearly define exported data;
databases, cookies and secrets remain in private application storage.

**Expected validation:** first launch, picker cancellation, an authorized,
unwritable or unavailable folder, restart and revoked permission. Respect the
Android picker's restrictions and offer a valid folder or the default
destination. Changing the folder must not silently move or delete existing
media; any migration needs an explicit, verified user flow.

## 11. Improve the Android video player

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

Issues and first tasks for all thirteen areas are linked from the
[contribution tracker #12](https://github.com/loeuf237/animelab/issues/12).

## Propose another idea

These areas do not exclude other relevant proposals. Describe the need, an
example use case, affected platforms, tradeoffs and a first verifiable step.
An architecture redesign should explain which problems it solves and how to
migrate existing data and behavior.

People who test, design, translate and document are as welcome as those who
write code. Choose a scope you can validate and state where you need help.
