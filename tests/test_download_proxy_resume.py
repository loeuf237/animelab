from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest
from curl_cffi.requests.exceptions import RequestException

from animelab.models.download_task import DownloadTask
from animelab.services.download_manager import DownloadManagerService
from animelab.services.download_resume import RESUME_OVERLAP, write_metadata
from animelab.services.source_http import SourceNetworkError
from test_proxy_pool import pool, entry
from test_source_http import transport


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path)
    monkeypatch.setattr(manager, '_finalize_task', AsyncMock())
    return manager


def task_at(tmp_path):
    return DownloadTask(fileName='episode.mp4', fileUrl='https://cdn.example/episode.mp4',
                        savePath=str(tmp_path / 'episode.mp4'))


@pytest.mark.asyncio
async def test_midstream_failure_rotates_after_release_and_resumes_exact_bytes(manager, tmp_path, pool, transport, monkeypatch):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    data = bytes(range(256)) * 1000
    calls, streams = [], []
    class Raw:
        def __init__(self, url, start, fail):
            self.url, self.status_code = url, 200 if fail else 206
            self.headers = httpx.Headers({'content-type':'video/mp4', 'etag':'"episode-v1"',
                                         'content-length':str(len(data) - start)})
            if not fail:
                self.headers['content-range'] = f'bytes {start}-{len(data)-1}/{len(data)}'
            self.start, self.fail, self.closed = start, fail, False
        def close(self): self.closed = True
        def iter_content(self):
            if self.fail:
                yield data[:100000]
                raise RequestException('connection reset by peer')
            yield data[self.start:]
    def handler(session, method, url, kwargs):
        headers = httpx.Headers(kwargs['headers'])
        start = int(headers['range'].split('=')[1].split('-')[0]) if 'range' in headers else 0
        calls.append((session.options['proxy'], headers))
        raw = Raw(url, start, fail=len(calls) == 1)
        streams.append(raw)
        return raw
    service = transport(handler)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: service.async_client(**kwargs))
    episode = task_at(tmp_path)
    with pytest.raises(SourceNetworkError):
        await manager._download_single_file(episode, episode.fileUrl)
    assert streams[0].closed and service.state(episode.fileUrl).leased == 0
    assert service.state(episode.fileUrl).proxy == 'http://8.8.8.8:8080'
    assert Path(episode.savePath + '.part').read_bytes() == data[:100000]
    await manager._download_single_file(episode, episode.fileUrl)
    assert calls[1][0] == 'http://8.8.8.8:8080'
    assert calls[1][1]['range'] == f'bytes={100000-RESUME_OVERLAP}-'
    assert calls[1][1]['if-range'] == '"episode-v1"'
    assert Path(episode.savePath).read_bytes() == data
    assert not Path(episode.savePath + '.part.resume.json').exists()
    assert manager._finalize_task.await_count == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('headers', [
    {'content-range':'bytes 6-9/10', 'content-length':'4'},
    {'content-range':'bytes 0-9/8', 'content-length':'10'},
    {'content-range':'bytes 0-9/10', 'content-length':'4'},
    {},
])
async def test_invalid_resume_response_does_not_touch_partial_file(manager, tmp_path, monkeypatch, headers):
    episode = task_at(tmp_path)
    part = Path(episode.savePath + '.part')
    part.write_bytes(b'prefix')
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(lambda request: httpx.Response(206, headers=headers, content=b'tail')),
        trust_env=False))
    with pytest.raises(ConnectionError, match='Content-Range'):
        await manager._download_single_file(episode, episode.fileUrl)
    assert part.read_bytes() == b'prefix'
    assert not Path(episode.savePath).exists()


@pytest.mark.asyncio
@pytest.mark.parametrize('reason', ['changed_validator', 'changed_overlap', 'range_ignored', 'range_rejected'])
async def test_changed_representation_restarts_without_mixing_bytes(manager, tmp_path, monkeypatch, reason):
    episode = task_at(tmp_path)
    part = Path(episode.savePath + '.part')
    part.write_bytes(b'old-prefix')
    write_metadata(Path(episode.savePath + '.part.resume.json'), {'validator':'"old"', 'total':20})
    data = b'new-prefix-and-video'
    calls = []
    def handler(request):
        calls.append(request)
        headers = {'content-type':'video/mp4', 'content-length':str(len(data))}
        if len(calls) == 1:
            if reason == 'range_rejected': return httpx.Response(416)
            if reason == 'range_ignored': return httpx.Response(200, headers=headers, content=data)
            headers['content-range'] = f'bytes 0-{len(data)-1}/{len(data)}'
            headers['etag'] = '"new"' if reason == 'changed_validator' else '"old"'
            return httpx.Response(206, headers=headers, content=data)
        assert 'range' not in request.headers and 'if-range' not in request.headers
        return httpx.Response(200, headers=headers, content=data)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(handler), trust_env=False))
    await manager._download_single_file(episode, episode.fileUrl)
    assert Path(episode.savePath).read_bytes() == data
    assert len(calls) == (1 if reason == 'range_ignored' else 2)


@pytest.mark.asyncio
async def test_hls_rotation_keeps_completed_segments_and_retries_only_interrupted_segment(manager, tmp_path, pool, transport, monkeypatch):
    pool.set_options({'automatic':True})
    pool.entries = {'http://8.8.8.8:8080':entry()}
    calls = []
    class Raw:
        status_code = 200
        def __init__(self, url, fail):
            self.url, self.fail = url, fail
            self.headers = httpx.Headers({'content-type':'video/mp2t', 'content-length':'5'})
        def close(self): pass
        def iter_content(self):
            if self.fail:
                yield b'cu'
                raise RequestException('connection reset')
            yield b'first' if self.url.endswith('0.ts') else b'other'
    def handler(session, method, url, kwargs):
        if url.endswith('m3u8'):
            return httpx.Response(200, text='#EXTM3U\n#EXTINF:5,\n0.ts\n#EXTINF:5,\n1.ts\n#EXT-X-ENDLIST',
                                  request=httpx.Request('GET', url))
        calls.append((url, session.options['proxy']))
        return Raw(url, fail=len(calls) == 2)
    service = transport(handler)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: service.async_client(**kwargs))
    monkeypatch.setattr(manager, 'is_ffmpeg_available', lambda:False)
    episode = task_at(tmp_path)
    await manager._download_hls_segments_native(episode, 'https://cdn.example/main.m3u8')
    assert [url.rsplit('/',1)[1] for url, _ in calls] == ['0.ts', '1.ts', '1.ts']
    assert calls[-1][1] == 'http://8.8.8.8:8080'
    assert Path(episode.savePath).read_bytes() == b'firstother'


@pytest.mark.asyncio
@pytest.mark.parametrize('changed_playlist', [False, True])
async def test_hls_resume_checks_playlist_identity_before_reusing_segments(manager, tmp_path, monkeypatch, changed_playlist):
    episode = task_at(tmp_path)
    calls = []
    new_playlist = False
    fail = True
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url):
            if url.endswith('m3u8'):
                first = 'new0.ts' if new_playlist else '0.ts'
                return httpx.Response(200, text=f'#EXTM3U\n#EXTINF:5,\n{first}\n#EXTINF:5,\n1.ts\n#EXT-X-ENDLIST')
            calls.append(url.rsplit('/',1)[1])
            if url.endswith('1.ts') and fail: raise ConnectionError('expired')
            return httpx.Response(200, content=b'new' if url.endswith('new0.ts') else b'old')
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs:Client())
    monkeypatch.setattr(manager, 'is_ffmpeg_available', lambda:False)
    with pytest.raises(ConnectionError):
        await manager._download_hls_segments_native(episode, 'https://cdn.example/main.m3u8')
    fail, new_playlist = False, changed_playlist
    await manager._download_hls_segments_native(episode, 'https://cdn.example/main.m3u8')
    expected = ['0.ts','1.ts','new0.ts','1.ts'] if changed_playlist else ['0.ts','1.ts','1.ts']
    assert calls == expected
    assert Path(episode.savePath).read_bytes() == (b'newold' if changed_playlist else b'oldold')
