"""Shared subtitle representation used by extractors and downloads."""
import html
import json
from urllib.parse import urljoin
from typing import Any


def normalize_subtitles(value: object, base_url: str = "") -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = json.loads(value or "[]")
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError("Les sous-titres doivent être une liste")
    tracks = []
    seen = set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("Piste de sous-titres invalide")
        url = item.get("url") or item.get("src") or item.get("file")
        if not isinstance(url, str) or not url.strip():
            raise ValueError("URL de sous-titres manquante")
        url = urljoin(base_url, html.unescape(url.strip().replace("\\/", "/")))
        if url in seen:
            continue
        seen.add(url)
        track = dict(item)
        track.update(url=url, label=item.get("label") or "Sous-titres",
                     lang=item.get("lang") or item.get("srclang") or "und")
        if base_url:
            track.setdefault("referer", base_url)
        tracks.append(track)
    return tracks


def subtitle_language(lang: str | None) -> str:
    primary = (lang or "und").lower().replace("_", "-").split("-")[0]
    return {"fr": "fra", "en": "eng", "ja": "jpn", "de": "deu",
            "es": "spa", "it": "ita", "pt": "por", "ar": "ara",
            "ru": "rus", "zh": "zho", "ko": "kor"}.get(primary, primary if len(primary) == 3 else "und")


def subtitle_extension(content: bytes) -> str:
    text = content.decode("utf-8-sig", errors="replace").strip()
    if text.startswith("WEBVTT"):
        return ".vtt"
    import re
    if re.search(r"\d{1,2}:\d{2}:\d{2}[,.]\d{3}\s*-->\s*\d{1,2}:\d{2}:\d{2}[,.]\d{3}", text):
        return ".srt"
    if "[Events]" in text and "Dialogue:" in text:
        return ".ass"
    raise ValueError("Contenu de sous-titres invalide (VTT, SRT ou ASS attendu)")
