from pathlib import Path

import pytest

from animelab.services.media_contracts import (
    BackendCapabilities, ResolvedMedia, TrackKind, UnsupportedMedia,
    normalize_tracks, validate_hls_capabilities,
)

FIXTURES = Path(__file__).parent / 'fixtures' / 'media_pipeline'


@pytest.mark.parametrize('name', ['simple', 'aes128'])
def test_current_native_hls_capabilities(name):
    validate_hls_capabilities((FIXTURES / (name + '.m3u8')).read_text())


@pytest.mark.parametrize('name', ['separate', 'fmp4'])
def test_native_hls_must_not_silently_discard_required_features(name):
    with pytest.raises(UnsupportedMedia):
        validate_hls_capabilities((FIXTURES / (name + '.m3u8')).read_text())


def test_track_boundaries_and_private_headers():
    info = {'videoUrl': 'https://video.example/episode.mp4', 'headers': {'Authorization': 'secret'},
            'audioTracks': [{'url': '/ja.m4a', 'lang': 'ja', 'headers': {'Cookie': 'private'}}],
            'subtitles': [{'url': '/fr.vtt', 'lang': 'fr'},
                          {'url': '/fr.vtt', 'lang': 'fr', 'role': 'forced'}]}
    media = ResolvedMedia.from_info(info)
    assert len(media.tracks) == 3
    assert media.tracks[0].kind == TrackKind.SUBTITLE
    assert media.tracks[-1].url == 'https://video.example/ja.m4a'
    assert 'secret' not in repr(media) and 'private' not in repr(media)
    assert all('headers' not in t.public() and 'url' not in t.public() for t in media.tracks)
    assert media.tracks[0].id != media.tracks[1].id


def test_capability_selection_rejects_dash_and_separate_audio():
    native = BackendCapabilities(frozenset({'hls'}), frozenset({'aes128'}))
    assert native.accepts(ResolvedMedia('https://example/a', 'hls', requirements=frozenset({'aes128'})))
    assert not native.accepts(ResolvedMedia('https://example/a', 'dash'))
    assert not native.accepts(ResolvedMedia('https://example/a', 'hls', requirements=frozenset({'separate_audio'})))


def test_reject_header_injection():
    with pytest.raises(ValueError):
        normalize_tracks([{'url': '/audio', 'headers': {'Referer': 'x\r\nCookie: secret'}}])


def test_track_identity_preserves_content_query_and_survives_token_refresh():
    def identity(query):
        return normalize_tracks([{'url': 'https://cdn.example/track?' + query}])[0]['id']
    assert identity('id=1&token=old') == identity('id=1&token=new')
    assert identity('id=1&token=old') != identity('id=2&token=old')
