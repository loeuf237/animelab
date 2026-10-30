"""Output policy snapshots. Unsupported processors cannot be queued early."""
import json
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class TrackSelection(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    trackId: str = Field(min_length=1, max_length=128)
    offsetSeconds: float = Field(default=0, ge=-86400, le=86400)
    default: bool = False
    forced: bool = False
    required: bool = True


class OutputProfile(BaseModel):
    model_config = ConfigDict(extra='forbid')
    version: Literal[1] = 1
    mode: Literal['ORIGINAL', 'SIDECAR', 'MKV_SOFT', 'MP4_HARD'] = 'ORIGINAL'
    selections: list[TrackSelection] = Field(default_factory=list, max_length=100)
    burnTrackId: str | None = Field(default=None, max_length=128)
    keepOriginals: bool = False
    strict: bool = True

    @model_validator(mode='after')
    def valid_selection(self):
        ids = [selection.trackId for selection in self.selections]
        if len(ids) != len(set(ids)):
            raise ValueError('Une piste ne peut être sélectionnée plusieurs fois')
        if self.mode == 'ORIGINAL' and (self.selections or self.burnTrackId):
            raise ValueError('Choisissez un format de traitement pour sélectionner des pistes')
        if self.burnTrackId and self.mode != 'MP4_HARD':
            raise ValueError('La piste incrustée ne concerne que le MP4 hardsub')
        return self


def snapshot(value=None, *, legacy_subtitles=False) -> str:
    explicit = value is not None
    if value is None:
        value = dict(mode='MKV_SOFT' if legacy_subtitles else 'ORIGINAL', keepOriginals=False, strict=False)
    if isinstance(value, str):
        value = json.loads(value)
    profile = OutputProfile.model_validate(value)
    if explicit:
        profile = profile.model_copy(update={'strict': True})
    return profile.model_dump_json()


def require_available(value) -> OutputProfile:
    profile = OutputProfile.model_validate_json(value) if isinstance(value, str) else OutputProfile.model_validate(value)
    if profile.strict and profile.mode in ('SIDECAR', 'MKV_SOFT'):
        from animelab import media_tools
        if not (media_tools.which('ffmpeg') and media_tools.which('ffprobe')):
            raise ValueError('FFmpeg et FFprobe sont requis')
    if profile.mode == 'MP4_HARD':
        from animelab import media_tools
        if media_tools.is_native():
            status = media_tools.native_hardsub_status()
            if not status['available']:
                raise ValueError(status['reason'])
        caps = media_tools.capabilities()
        if not (caps['ffprobe'] and 'subtitles' in caps['filters'] and 'libx264' in caps['encoders'] and 'aac' in caps['encoders']):
            raise ValueError('Le MP4 incrusté requiert FFmpeg avec libass, libx264, AAC et FFprobe')
    return profile


def available_profiles() -> list[dict]:
    from animelab import media_tools
    mux_available = bool(media_tools.which('ffmpeg') and media_tools.which('ffprobe'))
    hard_available = False
    native_status = media_tools.native_hardsub_status() if media_tools.is_native() else None
    if mux_available and (native_status is None or native_status['available']):
        caps = media_tools.capabilities()
        hard_available = 'subtitles' in caps['filters'] and 'libx264' in caps['encoders'] and 'aac' in caps['encoders']
    profiles = []
    for mode in ('ORIGINAL', 'SIDECAR', 'MKV_SOFT', 'MP4_HARD'):
        available = mode == 'ORIGINAL' or mode in ('MKV_SOFT', 'SIDECAR') and mux_available or mode == 'MP4_HARD' and hard_available
        reason = '' if available else (native_status['reason'] if mode == 'MP4_HARD' and native_status and not native_status['available']
                  else 'FFmpeg avec libass/libx264/AAC et FFprobe sont requis' if mode == 'MP4_HARD' else 'FFmpeg et FFprobe sont requis')
        profiles.append(dict(mode=mode, available=available, reason=reason, trackSelectionAvailable=available and mode != 'ORIGINAL'))
    return profiles


def private_snapshot(value):
    """Persist resource metadata, not session credentials. Refresh on resolution."""
    if isinstance(value, list):
        return [private_snapshot(item) for item in value]
    if isinstance(value, dict):
        return {key: ({k: v for k, v in item.items()
                       if k.lower() in ('referer', 'user-agent', 'origin', 'accept')}
                      if key == 'headers' and isinstance(item, dict) else private_snapshot(item))
                for key, item in value.items() if key not in ('session_ref', 'sessionRef')}
    return value
