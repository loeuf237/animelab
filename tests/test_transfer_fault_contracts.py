"""A08: faults at byte, segment, assembly, mux and export boundaries."""
import asyncio
from pathlib import Path
import threading
from unittest.mock import AsyncMock

import httpx
import pytest

from animelab.models.download_task import DownloadTask, DownloadStatus, ExportStatus
from animelab.services.download_manager import DownloadManagerService
from animelab.services.download_resume import write_metadata, media_resource
from animelab.services.library_service import library_service
from test_auto_export_migrations import exports


def test_resource_identity_includes_port_but_not_expired_signature():
    assert media_resource('https://cdn.example:443/video?token=old') == media_resource('https://cdn.example:443/video?token=new')
    assert media_resource('https://cdn.example:443/video') != media_resource('https://cdn.example:8443/video')


@pytest.fixture
def manager(tmp_path, monkeypatch):
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path)
    monkeypatch.setattr(manager, '_finalize_task', AsyncMock())
    monkeypatch.setattr(manager, 'broadcast_update', lambda task: None)
    return manager


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['https://cdn.example/video.mp4?signature=new', 'https://other.example/replacement.mp4'])
async def test_renewed_url_resumes_only_same_resource(manager, tmp_path, monkeypatch, url):
    data = b'original video bytes'
    episode = DownloadTask(fileName='video.mp4', savePath=str(tmp_path / 'video.mp4'))
    partial = Path(episode.savePath + '.part'); partial.write_bytes(data[:10])
    write_metadata(Path(episode.savePath + '.part.resume.json'), {'validator': '"same-etag"', 'total': len(data),
        'resource': media_resource('https://cdn.example/video.mp4?signature=old')})
    calls = []
    def reply(request):
        calls.append(request)
        headers = {'content-type': 'video/mp4', 'content-length': str(len(data)), 'etag': '"same-etag"'}
        if 'range' in request.headers:
            headers['content-range'] = f'bytes 0-{len(data)-1}/{len(data)}'
            return httpx.Response(206, headers=headers, content=data)
        return httpx.Response(200, headers=headers, content=data)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    await manager._download_single_file(episode, url)
    assert ('range' in calls[0].headers) is ('cdn.example' in url)
    assert Path(episode.savePath).read_bytes() == data


@pytest.mark.asyncio
async def test_unknown_range_total_cannot_publish_truncated_video(manager, tmp_path, monkeypatch):
    task = DownloadTask(fileName='video.mp4', savePath=str(tmp_path / 'video.mp4'))
    def reply(request):
        return httpx.Response(206, headers={'content-range': 'bytes 0-2/*', 'content-length': '3', 'content-type': 'video/mp4'}, content=b'abc')
    monkeypatch.setattr(manager, '_create_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    with pytest.raises(ConnectionError, match='unknown Content-Range'):
        await manager._download_single_file(task, 'https://cdn.example/video.mp4')
    assert not Path(task.savePath).exists()
    manager._finalize_task.assert_not_awaited()


@pytest.mark.asyncio
async def test_final_file_created_during_transfer_is_never_overwritten(manager, tmp_path, monkeypatch):
    final = tmp_path / 'video.mp4'
    task = DownloadTask(fileName=final.name, savePath=str(final))
    def reply(request):
        final.write_bytes(b'unrelated existing episode')
        return httpx.Response(200, headers={'content-type': 'video/mp4', 'content-length': '9'}, content=b'new-video')
    monkeypatch.setattr(manager, '_create_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    with pytest.raises(FileExistsError):
        await manager._download_single_file(task, 'https://cdn.example/video.mp4')
    assert final.read_bytes() == b'unrelated existing episode'
    assert final.with_name(final.name + '.part').read_bytes() == b'new-video'


@pytest.mark.asyncio
async def test_hls_interrupted_assembly_retains_cache_and_never_publishes_partial(manager, tmp_path, monkeypatch):
    task = DownloadTask(fileName='video.mp4', savePath=str(tmp_path / 'video.mp4'))
    calls = []
    def reply(request):
        if request.url.path.endswith('.m3u8'):
            return httpx.Response(200, text='#EXTM3U\n#EXTINF:5,\n0.ts\n#EXTINF:5,\n1.ts\n#EXT-X-ENDLIST')
        calls.append(request.url.path)
        return httpx.Response(200, content=b'first' if request.url.path.endswith('0.ts') else b'second')
    monkeypatch.setattr(manager, '_create_async_client', lambda **kw: httpx.AsyncClient(transport=httpx.MockTransport(reply)))
    monkeypatch.setattr(manager, 'is_ffmpeg_available', lambda: False)
    import shutil
    copy = shutil.copyfileobj
    def interrupted(src, dest, **kwargs):
        dest.write(src.read(2))
        raise OSError('simulated full disk / interrupted assembly')
    monkeypatch.setattr(shutil, 'copyfileobj', interrupted)
    with pytest.raises(OSError):
        await manager._download_hls_segments_native(task, 'https://cdn.example/video.m3u8')
    assert not Path(task.savePath).exists()
    assert len(calls) == 2
    # A same-size corrupt cached segment must also be fetched again.
    (tmp_path / '.video_segments/seg_00000.ts').write_bytes(b'WRONG')
    monkeypatch.setattr(shutil, 'copyfileobj', copy)
    await manager._download_hls_segments_native(task, 'https://cdn.example/video.m3u8')
    assert len(calls) == 3 and calls[-1].endswith('0.ts')
    assert Path(task.savePath).read_bytes() == b'firstsecond'


@pytest.mark.asyncio
async def test_cancellation_during_mux_retains_worker_and_prevents_parallel_publication(tmp_path, monkeypatch):
    manager = DownloadManagerService()
    monkeypatch.setattr(manager, 'broadcast_update', lambda task: None)
    monkeypatch.setattr(library_service, 'save_task', lambda task: None)
    monkeypatch.setattr(manager, 'is_ffmpeg_available', lambda: True)
    source = tmp_path / 'video.mp4'; source.write_bytes(b'original')
    task = DownloadTask(fileName=source.name, savePath=str(source), savePathSubtitle='subtitle.srt')
    started, finish = threading.Event(), threading.Event()
    def mux(task):
        started.set(); assert finish.wait(5)
        if not task.paused:
            source.with_suffix('.mkv').write_bytes(b'muxed')
    monkeypatch.setattr(manager, '_mux_subtitles_with_ffmpeg', mux)
    job = asyncio.create_task(manager._finalize_task(task))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
        assert task.status == DownloadStatus.PAUSED and task.paused
        with pytest.raises(ValueError, match='progress'): await manager._finalize_task(task)
        assert manager._export_in_progress(task.id)  # Protects remove/redownload.
    finally:
        worker = manager._media_jobs.get(task.id)
        finish.set()
        if worker: await worker
    assert source.read_bytes() == b'original'
    assert not source.with_suffix('.mkv').exists()


@pytest.mark.asyncio
async def test_repeated_finalization_does_not_duplicate_native_export(exports, monkeypatch):
    from animelab import platform_events
    manager, task, _ = exports
    calls = []
    monkeypatch.setattr(platform_events, 'completed_handler', lambda task: calls.append(task.id) or {'uris': ['content://downloads/1']})
    await manager._finalize_task(task)
    await manager._finalize_task(task)
    assert calls == [task.id]
    assert task.exportStatus == ExportStatus.EXPORTED and task.exportAttempts == 1
