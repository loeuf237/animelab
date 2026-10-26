"""Shared accounts may watch supported sources, never relay arbitrary public URLs."""
import asyncio
from types import SimpleNamespace

from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
import httpx
import pytest

from animelab.media_policy import media_domains, validate_media_url
from animelab.routers import media
from animelab.shared.workers import Workers


@pytest.mark.parametrize('method,path,params', [
    ('GET', '/api/media/image-proxy', {'url': 'https://outside.example/picture.png'}),
    ('GET', '/api/media/subtitle-proxy', {'url': 'https://outside.example/subtitle.vtt'}),
    ('GET', '/api/media/stream-proxy', {'url': 'https://outside.example/movie.mp4'}),
    ('HEAD', '/api/media/stream-proxy', {'url': 'https://outside.example/movie.mp4'}),
    ('GET', '/api/media/hls-proxy/playlist.m3u8', {'url': 'https://outside.example/list.m3u8'}),
    ('HEAD', '/api/media/hls-proxy/playlist.m3u8', {'url': 'https://outside.example/list.m3u8'}),
    ('GET', '/api/media/hls-proxy/segment.ts', {'url': 'https://outside.example/segment.ts'}),
    ('GET', '/api/media/hls-proxy/segment.ts', {'url': 'https://voir-anime.to/segment.ts', 'key': 'https://outside.example/key'}),
])
def test_shared_media_rejects_unapproved_destinations_before_network_or_cache(method, path, params, monkeypatch):
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    def unexpected(*args, **kwargs):
        pytest.fail('Forbidden URLs must never reach the network or media cache')
    monkeypatch.setattr(media.source_http, 'async_client', unexpected)
    monkeypatch.setattr(media, '_get_memory_cached_image', unexpected)
    monkeypatch.setattr(media, '_get_disk_cached_image', unexpected)
    app = FastAPI()
    app.include_router(media.router)
    with TestClient(app) as client:
        result = client.request(method, path, params=params)
    assert result.status_code == 400


def test_personal_mode_and_operator_approved_cdn_preserve_access(monkeypatch, tmp_path):
    monkeypatch.delenv('ANIMELAB_SHARED_WORKER', raising=False)
    validate_media_url('https://outside.example/public.mp4')
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    monkeypatch.setenv('ANIMELAB_MEDIA_DOMAINS', 'cdn.operator.example')
    validate_media_url('https://cdn.operator.example/video.mp4')
    validate_media_url('https://shard.cdn.operator.example/video.mp4')
    with pytest.raises(HTTPException):
        validate_media_url('https://cdn.operator.example.evil.example/video.mp4')
    with pytest.raises(HTTPException):
        validate_media_url('http://127.0.0.1/video.mp4')
    # Only the operator can supply this setting; it survives worker isolation.
    env = Workers(tmp_path).environment(tmp_path / 'worker', 'secret')
    assert env['ANIMELAB_MEDIA_DOMAINS'] == 'cdn.operator.example'
    assert 'vidmoly' not in media_domains()  # Loose extractor fragments grant nothing.


@pytest.mark.asyncio
async def test_shared_cover_delivery_remains_available_without_download_grant(monkeypatch):
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    monkeypatch.setenv('ANIMELAB_SHARED_DOWNLOAD', '0')
    monkeypatch.setattr(media, '_get_memory_cached_image', lambda url: (b'cover', 'image/png'))
    response = await media.proxy_image('https://image.tmdb.org/cover.png')
    assert response.body == b'cover' and response.media_type == 'image/png'


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['key', 'segment'])
async def test_hls_child_urls_cannot_escape_the_media_policy(monkeypatch, target):
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    visited = []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            visited.append(url)
            if target == 'key':
                content = '#EXTM3U\n#EXT-X-KEY:METHOD=AES-128,URI="https://outside.example/key"\nsegment.ts'
            else:
                content = '#EXTM3U\n#EXTINF:10,\nhttps://outside.example/segment.ts'
            return httpx.Response(200, text=content, request=httpx.Request('GET', url))
    monkeypatch.setattr(media, '_get_media_async_client', lambda **kwargs: Client())
    with pytest.raises(HTTPException) as error:
        await media.hls_proxy_playlist(SimpleNamespace(method='GET'), 'https://kwik.cx/main.m3u8')
    assert error.value.status_code == 400
    assert visited == ['https://kwik.cx/main.m3u8']
