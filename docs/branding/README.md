# AnimeLab identity

The owner selected **01 — Orbit A**, the violet and mint folded A with a play symbol, on 21 October 2026. The application and repository were previously called Animan.

| Concept | Original artwork | Decision |
| --- | --- | --- |
| 01 — Orbit A | [Violet and mint A](concepts/01-orbit-a.png) | Selected |
| 02 — Fox | [Coral origami fox](concepts/02-fox.png) | Alternative retained |
| 03 — Comet | [Cyan and cobalt comet](concepts/03-comet.png) | Alternative retained |

Artwork was created with the built-in `image_gen` tool. Exact generation prompts and the selection are recorded in [prompts.json](prompts.json). The selected PNG is the canonical raster master; it is not an editable vector source. No font or character from an anime franchise is used as an app mascot.

To regenerate the derived assets, install Pillow (`python -m pip install 'Pillow>=10,<13'`) and run `python scripts/branding.py`. The script creates:

- Web favicons, Apple touch icon, 192px and 512px PWA icons, and the maskable icon, in both `frontend/public` and `animelab/static`.
- Android launcher resources for all five density buckets and adaptive launcher icons for Android 8+.
- Windows `.ico` and macOS `.icns` files in this directory, referenced by the desktop packaging specification.

The wordmark is supplied separately as `animelab-wordmark.png`. Keep clear space around the mark. For app icons, use the square master rather than the horizontal wordmark. Check the launcher silhouette at small sizes and with circular masks when changing the master.

The Vue navigation imports `frontend/src/assets/brand-icon.png`, so Vite generates a new URL whenever its bytes change. The generator also fingerprints the legacy page icons, favicon, touch icon and manifest references. Branding requests use network-first service-worker caching, with an offline fallback. SPA visits check for updates to an existing worker without forcing a page reload. This prevents an older installed cache from continuing to display the previous Animan logo after an upgrade.

## Upgrade compatibility

The displayed product name is **AnimeLab**. The repository is `loeuf237/animelab`. New binary packages use `AnimeLab` filenames. Historical release assets and validation evidence keep their original filenames.

The following existing identifiers deliberately remain stable: Python imports from `animan`, environment settings `ANIMAN_*`, API/session headers, browser preferences/cookies, `.animan` data directory, `Downloads/Animan`, Android application ID and Kotlin namespace `com.animan.app`, MediaStore export registry and document-provider grants, and Android signing identity. Changing these would require a separate migration and could otherwise disconnect existing libraries or prevent an APK update. The local checkout may keep its current directory name.

The service worker cache revision changes with the branding update so installed web clients can refresh their assets. Branding changes take effect in Android and desktop packages when those packages are rebuilt; they do not modify already published APKs.
