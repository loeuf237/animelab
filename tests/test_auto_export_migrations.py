import asyncio
import importlib
import json
import threading

import httpx
import pytest
from fastapi import FastAPI
from sqlalchemy import MetaData, Table, create_engine
from sqlalchemy.orm import sessionmaker

from animelab import database, platform_events
from animelab.database import Base
from animelab.models.download_task import DownloadTask, DownloadTaskEntity, DownloadStatus, ExportStatus
from animelab.models.favorite import FavoriteAnime
from animelab.services.library_service import library_service
from animelab.services.download_manager import DownloadManagerService
from animelab.services.verification_service import verification_service, VerificationResult

library_module = importlib.import_module("animelab.services.library_service")


@pytest.fixture
def exports(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'exports.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(library_module, "SessionLocal", sessions)
    manager = DownloadManagerService()
    monkeypatch.setattr(manager, "broadcast_update", lambda task: None)
    monkeypatch.setattr(manager, "_trigger_process_queue", lambda: None)
    monkeypatch.setattr(platform_events, "storage_status_handler", lambda: {"authorized": True, "destination": "Downloads/AnimeLab"})
    monkeypatch.setattr(platform_events, "completed_handler", None)
    monkeypatch.setattr(verification_service, "verify_file", lambda **kwargs: VerificationResult(valid=True, status="VALID"))
    source = tmp_path / "private.mp4"
    source.write_bytes(b"verified private file")
    task = DownloadTask(animeName="Series", animeUrl="https://example.com/series", fileName=source.name,
        savePath=str(source), status=DownloadStatus.DOWNLOADING, totalBytes=source.stat().st_size)
    yield manager, task, sessions
    engine.dispose()


@pytest.mark.asyncio
async def test_failed_export_is_independent_persistent_and_retryable_offline(exports, monkeypatch, tmp_path):
    manager, task, sessions = exports
    def denied(task):
        assert task.exportStatus == ExportStatus.EXPORTING
        raise PermissionError("Folder access revoked")
    monkeypatch.setattr(platform_events, "completed_handler", denied)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED and task.progress == 100
    assert task.error is None and task.exportStatus == ExportStatus.EXPORT_FAILED
    assert "revoked" in task.exportError and task.exportAttempts == 1
    assert library_service.get_task_entity(task.id).exportStatus == "EXPORT_FAILED"
    restored = DownloadManagerService()
    monkeypatch.setattr(restored, "broadcast_update", lambda task: None)
    restored.init_from_db()
    again = restored.get_task(task.id)
    assert again.exportStatus == ExportStatus.EXPORT_FAILED
    public = tmp_path / "shared.mp4"
    def copy_local(task):
        from pathlib import Path
        public.write_bytes(Path(task.savePath).read_bytes())
        return {"uris": ["content://downloads/7"], "destination": "Downloads/AnimeLab"}
    monkeypatch.setattr(platform_events, "completed_handler", copy_local)
    # A retry operates only on the existing private file.
    from animelab.services.source_http import source_http
    monkeypatch.setattr(source_http, "request", lambda *a, **k: pytest.fail("Export fetched network media"))
    await restored.export_task(again, manual=True)
    assert public.read_bytes() == b"verified private file"
    assert again.exportStatus == ExportStatus.EXPORTED and again.exportError is None
    assert again.exportAttempts == 2 and again.exportedAt
    assert again.to_dict()["exportUris"] == ["content://downloads/7"]
    assert library_service.get_task_entity(task.id).to_task().exportDestination == "Downloads/AnimeLab"


@pytest.mark.asyncio
async def test_export_refuses_revoked_permissions_and_unconfirmed_results(exports, monkeypatch):
    manager, task, _ = exports
    task.status = DownloadStatus.COMPLETED
    monkeypatch.setattr(platform_events, "completed_handler", lambda task: pytest.fail("Copy started without permission"))
    monkeypatch.setattr(platform_events, "storage_status_handler", lambda: {"authorized": False, "destination": "SD card"})
    with pytest.raises(PermissionError):
        await manager.export_task(task, manual=True)
    assert task.exportStatus == ExportStatus.EXPORT_FAILED and task.exportDestination == "SD card"
    monkeypatch.setattr(platform_events, "storage_status_handler", None)
    monkeypatch.setattr(platform_events, "completed_handler", lambda task: None)
    with pytest.raises(ValueError, match="confirm"):
        await manager.export_task(task, manual=True)
    assert task.status == DownloadStatus.COMPLETED and task.exportedAt is None


@pytest.mark.asyncio
async def test_two_simultaneous_exports_do_not_start_two_native_copies(exports, monkeypatch):
    manager, task, _ = exports
    task.status = DownloadStatus.COMPLETED
    started, finish = threading.Event(), threading.Event()
    def blocked(task):
        started.set()
        assert finish.wait(5)
        return {"uris": ["content://downloads/8"], "destination": "Downloads/AnimeLab"}
    monkeypatch.setattr(platform_events, "completed_handler", blocked)
    first = asyncio.create_task(manager.export_task(task, manual=True))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        with pytest.raises(ValueError, match="already in progress"):
            await manager.export_task(task, manual=True)
        assert task.exportAttempts == 1
    finally:
        finish.set()
        await first
    assert task.exportStatus == ExportStatus.EXPORTED


def test_interrupted_exports_restore_as_pending_and_cleanup_preserves_attention(exports):
    manager, task, _ = exports
    task.status, task.exportStatus = DownloadStatus.COMPLETED, ExportStatus.EXPORTING
    task.exportAttempts = 1
    library_service.save_task(task)
    manager.init_from_db()
    restored = manager.get_task(task.id)
    assert restored.exportStatus == ExportStatus.PENDING
    assert "interrupted" in restored.exportError
    manager.clear_inactive_tasks()
    assert manager.get_task(task.id) is not None
    # An unfinished Android download has no verified copy to preserve for export.
    failed = DownloadTask(status=DownloadStatus.FAILED, exportStatus=ExportStatus.PENDING)
    library_service.save_task(failed)
    manager.tasks[failed.id] = failed
    manager.task_order.append(failed.id)
    manager.clear_inactive_tasks()
    assert library_service.get_task_entity(failed.id) is None
    assert library_service.get_task_entity(task.id).exportAttempts == 1
    library_service.clear_history()
    manager.clear_history_tasks()
    assert library_service.get_task_entity(task.id) is not None
    assert manager.get_task(task.id) is not None


@pytest.mark.asyncio
async def test_cancelled_export_preserves_verified_completion_and_blocks_new_copy_until_native_exit(exports, monkeypatch):
    manager, task, _ = exports
    started, finish = threading.Event(), threading.Event()
    def blocked(task):
        started.set()
        assert finish.wait(5)
        assert task.paused
        raise ValueError("Export was paused or cancelled")
    monkeypatch.setattr(platform_events, "completed_handler", blocked)
    finalization = asyncio.create_task(manager._finalize_task(task))
    try:
        assert await asyncio.to_thread(started.wait, 3)
        assert task.status == DownloadStatus.COMPLETED
        finalization.cancel()
        with pytest.raises(asyncio.CancelledError):
            await finalization
        assert task.exportStatus == ExportStatus.PENDING
        assert task.status == DownloadStatus.COMPLETED and task.paused
        assert library_service.get_task_entity(task.id).status == "COMPLETED"
        with pytest.raises(ValueError, match="already in progress"):
            await manager.export_task(task, manual=True)
        with pytest.raises(ValueError, match="current export"):
            manager.remove_task(task.id)
        with pytest.raises(ValueError, match="current export"):
            manager.redownload_task(task.id, force=True)
    finally:
        native = manager._native_exports.get(task.id)
        finish.set()
        if native:
            with pytest.raises(ValueError, match="paused"):
                await native
    monkeypatch.setattr(platform_events, "completed_handler", lambda task: {"uris": ["content://downloads/9"]})
    await manager.export_task(task, manual=True)
    assert task.status == DownloadStatus.COMPLETED and task.exportStatus == ExportStatus.EXPORTED


def test_upgrade_preserves_legacy_favorites_and_splits_legacy_export_errors(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'legacy.sqlite'}")
    old = MetaData()
    export_columns = {"exportStatus", "exportUrisJson", "exportDestination", "exportError", "exportAttempts", "exportedAt"}
    tasks = Table("download_tasks", old, *(c._copy() for c in DownloadTaskEntity.__table__.columns if c.name not in export_columns))
    favorites = Table("favorites", old, *(c._copy() for c in FavoriteAnime.__table__.columns if not c.name.startswith("autoDownload") or c.name == "autoDownload"))
    old.create_all(engine)
    with engine.begin() as conn:
        conn.execute(tasks.insert().values(id="legacy", animeName="Series", fileName="episode.mp4",
            status="COMPLETED", error="Android export failed; media is available in the library: denied"))
        conn.execute(favorites.insert().values(url="https://example.com/series", title="Series",
            source="animepahe", autoDownload=True, lastKnownEpisode=12))
    monkeypatch.setattr(database, "engine", engine)
    database.init_db()
    database.init_db()  # Existing databases can be opened repeatedly.
    with engine.connect() as conn:
        row = conn.exec_driver_sql('SELECT * FROM download_tasks').mappings().one()
        assert row["id"] == "legacy" and row["status"] == "COMPLETED" and row["error"] is None
        assert row["exportStatus"] == "EXPORT_FAILED" and row["exportAttempts"] == 1
        assert "denied" in row["exportError"] and json.loads(row["exportUrisJson"]) == []
        row = conn.exec_driver_sql('SELECT * FROM favorites').mappings().one()
        assert row["source"] == "animepahe" and row["lastKnownEpisode"] == 12 and row["autoDownload"]
        assert not row["autoDownloadInitialized"]
    engine.dispose()


@pytest.mark.asyncio
async def test_tracking_preferences_api_validates_and_roundtrips(exports):
    from animelab.routers.library import router
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
        payload = {"url": "https://example.com/series", "title": "Series", "source": "animepahe",
                   "autoDownload": True, "autoDownloadVersion": "VF", "autoDownloadSubtitles": True}
        assert (await client.post('/api/favorites', json=payload)).status_code == 200
        result = (await client.get('/api/favorites')).json()[0]
        assert result["autoDownloadVersion"] == "VF" and result["autoDownloadSubtitles"]
        response = await client.patch('/api/favorites/auto-download', json={"url": payload["url"], "autoDownload": "false"})
        assert response.status_code == 200 and response.json()["favorite"]["autoDownload"] is False
        assert response.json()["favorite"]["autoDownloadVersion"] == "VF"
        assert (await client.patch('/api/favorites/auto-download', json={"url": payload["url"], "autoDownload": "invalid"})).status_code == 422
        assert (await client.patch('/api/favorites/auto-download', json={"url": 'https://example.com/missing', "autoDownload": True})).status_code == 404
