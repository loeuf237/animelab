# AnimeLab identity

The current artwork was supplied by the owner on 26 October 2026. The original
image is preserved unchanged as [animelab-logo-source.png](animelab-logo-source.png).
It combines a flask, an anime illustration and the AnimeLab wordmark.

The full image is used for the README/wordmark. Launcher icons use only the flask
region, with white padding and safe areas for Android adaptive and PWA maskable
icons. This is a deterministic crop/resize of the supplied image; no generative
redrawing is involved. The former A, fox and comet concepts remain in `concepts/`
as historical proposals, and are no longer the icon-generation source.

To regenerate the derived assets, install Pillow (`python -m pip install 'Pillow>=10,<13'`) and run `python scripts/branding.py`. The script creates:

- Web favicons, Apple touch icon, 192px and 512px PWA icons, and the maskable icon, in both `frontend/public` and `animelab/static`.
- Android launcher resources for all five density buckets and adaptive launcher icons for Android 8+.
- Windows `.ico` and macOS `.icns` files in this directory, referenced by the desktop packaging specification.

The wordmark is supplied separately as `animelab-wordmark.png`. Keep clear space around the mark. For app icons, use the square master rather than the horizontal wordmark. Check the launcher silhouette at small sizes and with circular masks when changing the master.

The Vue navigation imports `frontend/src/assets/brand-icon.png`, so Vite generates a new URL whenever its bytes change. The generator also fingerprints the legacy page icons, favicon, touch icon and manifest references. Branding requests use network-first service-worker caching, with an offline fallback. SPA visits check for updates to an existing worker without forcing a page reload. This prevents an older installed cache from continuing to display the previous Animan logo after an upgrade.

## Upgrade compatibility

The displayed product name is **AnimeLab**. The repository is `loeuf237/animelab`. New binary packages use `AnimeLab` filenames. Historical release assets and validation evidence keep their original filenames.

The Python import namespace is now `animelab`. New desktop downloads and Android shared exports use `Downloads/AnimeLab`; existing files are not moved, and explicitly chosen folders remain selected. The following existing identifiers deliberately remain stable: legacy environment settings `ANIMAN_*` (with `ANIMELAB_*` preferred), API/session headers, language/session cookies, `.animan` data directory, Android application ID and Kotlin namespace `com.animan.app`, MediaStore export registry and document-provider grants, and Android signing identity. Changing these would require a separate migration and could otherwise disconnect existing libraries or prevent an APK update. The local checkout may keep its current directory name. See [the inventory and migration options](../legacy-identifiers.md).

The generated branding URLs change with the artwork digest so installed web clients can refresh their assets. Branding changes take effect in Android and desktop packages when those packages are rebuilt; they do not modify already published APKs.
