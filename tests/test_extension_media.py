import re
import pytest
from fastapi import HTTPException

from animelab.services.extension_media import ExtensionMedia
from animelab.services.subtitle_service import to_webvtt


@pytest.fixture
def media(monkeypatch):
    def validate(url):
        if not url.startswith(('https://fixture.example/','https://cdn.example/')):
            raise HTTPException(400,'forbidden')
    monkeypatch.setattr('animelab.services.extension_media.validate_media_url',validate)
    return ExtensionMedia()


def test_media_capability_contains_no_url_or_credentials_and_expires(media):
    now=[1]
    media.clock=lambda:now[0]
    url=media.issue('https://fixture.example/movie?token=private',{'Authorization':'Bearer secret','Host':'evil'})
    assert 'private' not in url and 'secret' not in url
    assert media.get(url.rsplit('/',1)[1]).headers=={'Authorization':'Bearer secret'}
    now[0]=3602
    with pytest.raises(ValueError,match='expiré'):
        media.get(url.rsplit('/',1)[1])


def test_hls_preserves_keys_maps_ranges_and_strips_cross_origin_credentials(media):
    original=media.issue('https://fixture.example/master.m3u8',{'Authorization':'secret','Referer':'https://fixture.example/'})
    entry=media.get(original.rsplit('/',1)[1])
    text='#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="key",IV=0x01\n#EXT-X-MAP:URI="init.mp4"\n#EXT-X-BYTERANGE:100@0\nhttps://cdn.example/chunk.ts\n'
    output=media.playlist(text,entry,entry.url)
    assert 'METHOD=AES-128' in output and 'IV=0x01' in output and '#EXT-X-BYTERANGE:100@0' in output
    tokens=re.findall(r'/api/media/extension-resource/([\w-]+)',output)
    assert len(tokens)==3
    assert media.get(tokens[0]).url=='https://fixture.example/key'
    assert media.get(tokens[0]).headers['Authorization']=='secret'
    assert 'Authorization' not in media.get(tokens[2]).headers


def test_hls_children_cannot_bypass_destination_policy(media):
    original=media.issue('https://fixture.example/master.m3u8')
    with pytest.raises(HTTPException):
        media.playlist('#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="http://127.0.0.1/private"',media.get(original.rsplit('/',1)[1]),'https://fixture.example/a')


def test_capability_pool_is_bounded_and_headers_reject_injection(media):
    media.limit=2
    first=media.issue('https://fixture.example/a')
    media.issue('https://fixture.example/b')
    media.issue('https://fixture.example/c')
    with pytest.raises(ValueError):
        media.get(first.rsplit('/',1)[1])
    with pytest.raises(ValueError):
        media.issue('https://fixture.example/a',{'X-Header':'value\r\ninjection'})


def test_browser_subtitles_convert_srt_without_silently_stripping_ass_styles():
    assert to_webvtt('1\n00:00:01,250 --> 00:00:02,500\nBonjour\n').startswith('WEBVTT\n\n1\n00:00:01.250 --> 00:00:02.500')
    with pytest.raises(ValueError,match='ASS'):
        to_webvtt('[Events]\nDialogue: 0,0:00:01.00,0:00:02.00,Default,,0,0,0,,Hello')
