import json
import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from fastapi import FastAPI
from animelab.routers import media
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager

@pytest.fixture
def client(tmp_path, monkeypatch):
    tmp_dir = tmp_path
    fake_video = tmp_dir / "test_video.mp4"
    fake_data = b"0123456789ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz" * 100
    fake_video.write_bytes(fake_data)

    fake_sub = tmp_dir / "test_video.fr.vtt"
    fake_sub.write_text("WEBVTT\n\n1\n00:00:01.000 --> 00:00:04.000\nHello world", encoding="utf-8")

    task = DownloadTask(
        id="media-test-task-1",
        animeName="Media Test Anime",
        episodeNumber=1,
        fileName="test_video.mp4",
        savePath=str(fake_video),
        savePathSubtitle=json.dumps([str(fake_sub)]),
        status=DownloadStatus.COMPLETED,
        totalBytes=len(fake_data),
    )
    monkeypatch.setattr(download_manager, 'get_task', lambda task_id: task if task_id == task.id else None)
    app = FastAPI()
    app.include_router(media.router)
    with TestClient(app) as c:
        yield c, task, fake_data

def test_full_video_stream(client):
    c, task, fake_data = client
    resp = c.get(f"/api/media/stream/{task.id}")
    assert resp.status_code == 200
    assert resp.headers.get("Accept-Ranges") == "bytes"
    assert int(resp.headers.get("Content-Length")) == len(fake_data)
    assert resp.content == fake_data

def test_range_video_stream(client):
    c, task, fake_data = client
    start = 10
    end = 49
    resp = c.get(
        f"/api/media/stream/{task.id}",
        headers={"Range": f"bytes={start}-{end}"}
    )
    assert resp.status_code == 206
    assert resp.headers.get("Content-Range") == f"bytes {start}-{end}/{len(fake_data)}"
    assert resp.headers.get("Accept-Ranges") == "bytes"
    expected_len = end - start + 1
    assert int(resp.headers.get("Content-Length")) == expected_len
    assert resp.content == fake_data[start:end+1]

def test_subtitles_endpoints(client):
    c, task, _ = client
    resp = c.get(f"/api/media/subtitles/{task.id}")
    assert resp.status_code == 200
    subs = resp.json()
    assert len(subs) == 1
    assert subs[0]["srclang"] == "fr"

    # Stream subtitle
    sub_resp = c.get(subs[0]["src"])
    assert sub_resp.status_code == 200
    assert "WEBVTT" in sub_resp.text


def test_head_and_seek_to_end(client):
    c, task, data = client
    head = c.head(f"/api/media/stream/{task.id}")
    assert head.status_code == 200
    assert head.content == b""
    assert int(head.headers['content-length']) == len(data)
    assert head.headers['content-type'] == 'video/mp4'
    tail = c.get(f"/api/media/stream/{task.id}", headers={'Range': 'bytes=-32'})
    assert tail.status_code == 206
    assert tail.content == data[-32:]
    assert tail.headers['content-range'] == f'bytes {len(data)-32}-{len(data)-1}/{len(data)}'
    beyond = c.get(f"/api/media/stream/{task.id}", headers={'Range': f'bytes={len(data)}-'})
    assert beyond.status_code == 416
    assert beyond.headers['content-range'] == f'bytes */{len(data)}'


def test_missing_or_directory_video_is_404(client):
    c, task, _ = client
    assert c.get('/api/media/stream/not-a-task').status_code == 404
    video = Path(task.savePath)
    video.unlink()
    assert c.get(f'/api/media/stream/{task.id}').status_code == 404
    task.savePath = str(video.parent)
    assert c.get(f'/api/media/stream/{task.id}').status_code == 404


def test_webm_has_its_own_mime_type_and_absent_subtitles_have_no_track(client):
    c, task, _ = client
    old = Path(task.savePath)
    new = old.with_suffix('.webm')
    old.rename(new)
    task.savePath = str(new)
    task.savePathSubtitle = None
    assert c.get(f'/api/media/stream/{task.id}').headers['content-type'] == 'video/webm'
    assert c.get(f'/api/media/subtitles/{task.id}').json() == []


def test_completed_downloads_remain_playable_after_restart(monkeypatch, tmp_path):
    import importlib
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from animelab.database import Base
    from animelab.models.download_task import ExportStatus
    from animelab.services.download_manager import DownloadManagerService
    from animelab.services.library_service import library_service
    from animelab.services.verification_service import verification_service
    engine = create_engine(f'sqlite:///{tmp_path / "restore.sqlite"}')
    Base.metadata.create_all(engine)
    monkeypatch.setattr(importlib.import_module('animelab.services.library_service'), 'SessionLocal', sessionmaker(bind=engine))
    video = tmp_path / 'completed.mp4'
    video.write_bytes(b'verified video' * 100000)
    completed = DownloadTask(id='completed', savePath=str(video), status=DownloadStatus.COMPLETED)
    pending_export = DownloadTask(id='pending-export', savePath=str(video), status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.PENDING)
    cancelled = DownloadTask(id='cancelled', status=DownloadStatus.CANCELLED)
    for task in (completed, pending_export, cancelled):
        library_service.save_task(task)
    monkeypatch.setattr(verification_service, 'verify_file', lambda *a, **k: pytest.fail('Completed media was scanned again during startup'))
    manager = DownloadManagerService()
    manager.init_from_db()
    assert {t.id for t in manager.get_all_tasks()} == {'completed', 'pending-export'}
    assert manager.get_task('completed').status == DownloadStatus.COMPLETED
    assert manager.get_task('pending-export').exportStatus == ExportStatus.PENDING
    assert manager.task_order.count('pending-export') == 1
    engine.dispose()
