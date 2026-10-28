"""Versioned media contracts; contain resources, never executable recipes.

Network headers stay private. Public inventories deliberately omit URLs and
credentials; a track ID identifies a selection independently of an expiring URL.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
import hashlib
import json
from typing import Any, Callable, Protocol
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit


class TrackKind(str, Enum):
    VIDEO = 'video'
    AUDIO = 'audio'
    SUBTITLE = 'subtitle'
    FONT = 'font'


class UnsupportedMedia(ValueError):
    """A required capability/track cannot be preserved, never silently dropped."""


def normalize_tracks(value: object, base_url: str = '', *, kind: str = 'audio') -> list[dict[str, Any]]:
    if isinstance(value, str):
        value = json.loads(value or '[]')
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError('Les pistes doivent être une liste')
    tracks, seen = [], set()
    for item in value:
        if not isinstance(item, dict):
            raise ValueError('Piste invalide')
        url = item.get('url') or item.get('src') or item.get('file')
        if not isinstance(url, str) or not url.strip():
            raise ValueError('URL de piste manquante')
        url = urljoin(base_url, url.strip())
        headers = item.get('headers') or {}
        if not isinstance(headers, dict) or any(not isinstance(k, str) or not isinstance(v, str)
                                               or '\n' in k + v or '\r' in k + v for k, v in headers.items()):
            raise ValueError('En-têtes de piste invalides')
        track = dict(item, url=url, kind=kind, headers=dict(headers),
                     lang=item.get('lang') or item.get('srclang') or item.get('language') or 'und',
                     label=item.get('label') or item.get('name') or kind)
        identity = (url, track['lang'], track['label'], track.get('role'),
                    bool(track.get('automatic')), bool(track.get('forced')), track.get('groupId'))
        if identity in seen:
            continue
        seen.add(identity)
        parsed = urlsplit(url)
        volatile = {'token', 'expires', 'expiry', 'signature', 'sig', 'policy', 'key-pair-id'}
        query = [(key, value) for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                 if key.lower() not in volatile and not key.lower().startswith(('x-amz-', 'x-goog-'))]
        stable_identity = (parsed._replace(query=urlencode(query), fragment='').geturl(), *identity[1:])
        track.setdefault('id', hashlib.sha256(json.dumps(stable_identity).encode()).hexdigest()[:24])
        track.setdefault('provenance', 'source')
        if base_url:
            track.setdefault('referer', base_url)
        tracks.append(track)
    return tracks


@dataclass(frozen=True)
class MediaTrack:
    id: str
    kind: TrackKind
    url: str = field(default='', repr=False)
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    lang: str = 'und'
    label: str = ''
    role: str = ''
    automatic: bool = False
    required: bool = False
    format: str = ''
    group_id: str = ''

    def public(self) -> dict[str, Any]:
        return dict(id=self.id, kind=self.kind.value, lang=self.lang, label=self.label,
                    role=self.role, automatic=self.automatic, required=self.required,
                    format=self.format, groupId=self.group_id)


@dataclass(frozen=True)
class ResolvedMedia:
    url: str = field(repr=False)
    protocol: str = 'http'
    tracks: tuple[MediaTrack, ...] = ()
    headers: dict[str, str] = field(default_factory=dict, repr=False)
    session_ref: str | None = field(default=None, repr=False)
    requirements: frozenset[str] = frozenset()
    chunks: tuple[str, ...] = field(default=(), repr=False)

    @classmethod
    def from_info(cls, info: dict[str, Any], base_url: str = '') -> ResolvedMedia:
        url = info.get('videoUrl') or info.get('url') or ''
        tracks = []
        for name, kind in (('subtitles', TrackKind.SUBTITLE), ('audioTracks', TrackKind.AUDIO)):
            for track in normalize_tracks(info.get(name), base_url or url, kind=kind.value):
                tracks.append(MediaTrack(id=track['id'], kind=kind, url=track['url'],
                    headers=track['headers'], lang=track['lang'], label=track['label'],
                    role=track.get('role', ''), automatic=bool(track.get('automatic')),
                    required=bool(track.get('required')), format=track.get('format', ''),
                    group_id=track.get('groupId', '')))
        path = urlsplit(url).path.lower()
        protocol = 'hls' if path.endswith('.m3u8') else 'dash' if path.endswith('.mpd') else 'http'
        requirements = set(info.get('requirements') or ())
        if any(track.kind == TrackKind.AUDIO and track.required for track in tracks):
            requirements.add('separate_audio')
        return cls(url=url, protocol=protocol, tracks=tuple(tracks),
                   headers=dict(info.get('headers') or {}),
                   requirements=frozenset(requirements))


@dataclass(frozen=True)
class BackendCapabilities:
    protocols: frozenset[str]
    features: frozenset[str] = frozenset()
    resume: bool = True

    def accepts(self, media: ResolvedMedia) -> bool:
        return media.protocol in self.protocols and media.requirements <= self.features


@dataclass(frozen=True)
class MediaEvent:
    kind: str  # started, network, encoding, checkpoint, stopped, cancelled, error
    bytes_received: int = 0
    media_seconds: float | None = None
    detail: str = ''


@dataclass(frozen=True)
class TransferResult:
    backend: str
    path: str
    complete: bool
    checkpoint: dict[str, Any] = field(default_factory=dict)


class DownloadBackend(Protocol):
    name: str
    capabilities: BackendCapabilities

    async def transfer(self, task: Any, media: ResolvedMedia,
                       emit: Callable[[MediaEvent], None]) -> TransferResult: ...


def validate_hls_capabilities(text: str) -> None:
    """Conservative boundary of the existing native HLS implementation."""
    unsupported = ('#EXT-X-MAP:', '#EXT-X-BYTERANGE:', '#EXT-X-DISCONTINUITY')
    if any(tag in text for tag in unsupported):
        raise UnsupportedMedia('HLS : variante non prise en charge par le moteur natif')
    for line in text.splitlines():
        if line.startswith('#EXT-X-MEDIA:') and ('TYPE=AUDIO' in line or 'TYPE=SUBTITLES' in line) and 'URI=' in line:
            raise UnsupportedMedia('HLS : pistes séparées non prises en charge ; aucune piste ne sera ignorée')
        if line.startswith('#EXT-X-KEY:') and 'METHOD=NONE' not in line and 'METHOD=AES-128,' not in line:
            raise UnsupportedMedia('HLS : chiffrement non pris en charge')


def merge_stream_metadata(info: dict[str, Any], source: dict[str, Any] | None,
                          base_url: str) -> dict[str, Any]:
    """Attach metadata to the candidate it belongs to, never another mirror."""
    from animelab.services.subtitle_service import normalize_subtitles
    source = source or {}
    result = dict(info)
    inherited = source.get('subtitles') or source.get('subtitleTracks') or []
    result['subtitles'] = normalize_tracks(normalize_subtitles(inherited, base_url)
        + normalize_subtitles(info.get('subtitles'), base_url),
        kind='subtitle')
    result['audioTracks'] = normalize_tracks(
        normalize_tracks(source.get('audioTracks'), base_url)
        + normalize_tracks(info.get('audioTracks'), base_url))
    result['headers'] = {**(info.get('headers') or {}), **(source.get('headers') or {})}
    result['requirements'] = sorted(set(source.get('requirements') or ()) | set(info.get('requirements') or ()))
    return result
