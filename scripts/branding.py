"""Derive web, Android and desktop icons from the selected AnimeLab artwork.

Install Pillow, then run `python scripts/branding.py` from any directory.
The generated artwork itself is kept in docs/branding/concepts.
"""
from pathlib import Path
import hashlib
import json
import re
from PIL import Image, ImageOps

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "docs/branding/animelab-logo-source.png"


def generate():
    with Image.open(SOURCE) as image:
        artwork = image.convert("RGBA")
    if artwork.width != artwork.height:
        raise ValueError("App icon master must be square")
    # Keep the supplied full artwork intact. Small app icons use its flask,
    # without the wordmark, so the mark stays legible at launcher/favicon sizes.
    width, height = artwork.size
    flask = artwork.crop((round(width * .24), round(height * .035),
                          round(width * .76), round(height * .766)))
    master = Image.new("RGBA", (1024, 1024), "white")
    flask = ImageOps.contain(flask, (880, 880), Image.Resampling.LANCZOS)
    master.alpha_composite(flask, ((1024 - flask.width) // 2, (1024 - flask.height) // 2))
    artwork.save(ROOT / 'docs/branding/animelab-wordmark.png')

    def save(path, size, **options):
        path.parent.mkdir(parents=True, exist_ok=True)
        source = master
        if path.name == 'icon-maskable.png':
            source = Image.new('RGBA', (1024, 1024), 'white')
            safe = master.resize((820, 820), Image.Resampling.LANCZOS)
            source.alpha_composite(safe, (102, 102))
        # Adaptive launchers crop the outer 108dp layer to a 72dp safe area.
        if path.name == 'ic_launcher_foreground.png':
            source = Image.new('RGBA', (1024, 1024), (255, 255, 255, 0))
            safe = master.resize((682, 682), Image.Resampling.LANCZOS)
            source.alpha_composite(safe, (171, 171))
        icon = source.resize((size, size), Image.Resampling.LANCZOS)
        if path.suffix == ".jpg":
            icon = icon.convert("RGB")
        icon.save(path, **options)

    for base in (ROOT / "frontend/public", ROOT / "animelab/static"):
        for name, size in {"icon-192.png": 192, "icon-512.png": 512,
                           "icon-maskable.png": 512, "favicon.png": 64,
                           "apple-touch-icon.png": 180, "logo.jpg": 512}.items():
            save(base / "img" / name, size)
        save(base / "favicon.ico", 256, sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])

    # Vite gives imported artwork a content-hashed URL. An old service worker
    # must never be able to substitute the former /img/icon-192.png response.
    save(ROOT / "frontend/src/assets/brand-icon.png", 192)
    public = ROOT / "frontend/public"
    def versioned(url):
        path = url.split("?", 1)[0]
        digest = hashlib.sha256((public / path.lstrip("/")).read_bytes()).hexdigest()[:12]
        return f"{path}?v={digest}"

    for base in (public, ROOT / "animelab/static"):
        manifest = base / "manifest.json"
        data = json.loads(manifest.read_text())
        for group in [data.get("icons", []), *(s.get("icons", []) for s in data.get("shortcuts", []))]:
            for icon in group:
                icon["src"] = versioned(icon["src"])
        manifest.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n")
    for path in [ROOT / "frontend/index.html"]:
        text = re.sub(r'(?P<prefix>(?:src|href)=")(?P<url>/img/(?:icon-[^"?]+\.png|favicon\.png|apple-touch-icon\.png))(?:\?[^"\s]*)?"',
                      lambda match: match["prefix"] + versioned(match["url"]) + '"', path.read_text())
        text = re.sub(r'href="/manifest\.json(?:\?[^"\s]*)?"',
                      'href="' + versioned('/manifest.json') + '"', text)
        path.write_text(text)

    res = ROOT / "android/app/src/main/res"
    for density, size, foreground in (("mdpi", 48, 108), ("hdpi", 72, 162),
                                       ("xhdpi", 96, 216), ("xxhdpi", 144, 324),
                                       ("xxxhdpi", 192, 432)):
        for name in ("ic_launcher.png", "ic_launcher_round.png"):
            save(res / f"mipmap-{density}" / name, size)
        save(res / f"mipmap-{density}/ic_launcher_foreground.png", foreground)

    for name in ("ic_launcher.xml", "ic_launcher_round.xml"):
        path = res / "mipmap-anydpi-v26" / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('<?xml version="1.0" encoding="utf-8"?>\n'
                        '<adaptive-icon xmlns:android="http://schemas.android.com/apk/res/android">\n'
                        '    <background android:drawable="@color/launcher_background" />\n'
                        '    <foreground android:drawable="@mipmap/ic_launcher_foreground" />\n'
                        '</adaptive-icon>\n')
    colors = res / "values/launcher_colors.xml"
    colors.write_text('<?xml version="1.0" encoding="utf-8"?>\n<resources>\n'
                      '    <color name="launcher_background">#FFFFFF</color>\n</resources>\n')
    save(ROOT / "docs/branding/animelab.ico", 256,
         sizes=[(s, s) for s in (16, 24, 32, 48, 64, 128, 256)])
    save(ROOT / "docs/branding/animelab.icns", 1024)
    print("Generated AnimeLab icons for web, Android, Windows and macOS")


if __name__ == "__main__":
    generate()
