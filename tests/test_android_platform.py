import base64
import json
import subprocess

import httpx
import pytest

from animelab import media_tools
from animelab.android_security import AndroidSessionMiddleware


@pytest.fixture
def native(monkeypatch):
    class Bridge:
        result = {"returncode": 0, "stdout": "native output", "stderr": ""}
        calls = []
        @classmethod
        def execute(cls, tool, arguments, timeout):
            cls.calls.append((tool, json.loads(arguments), timeout))
            return json.dumps(cls.result)
    monkeypatch.setattr(media_tools, "_native_media", Bridge)
    return Bridge


def test_native_media_preserves_argument_boundaries_and_failure(native):
    result = media_tools.run(["ffmpeg", "-i", "/private/episode with spaces.mp4"], check=True, timeout=12)
    assert result.stdout == "native output"
    assert native.calls == [("ffmpeg", ["-i", "/private/episode with spaces.mp4"], 12000)]
    native.result = {"returncode": 1, "stderr": "bad subtitle"}
    with pytest.raises(subprocess.CalledProcessError):
        media_tools.run(["ffmpeg", "-version"], check=True)
    native.result = {"returncode": -1, "timedOut": True}
    with pytest.raises(subprocess.TimeoutExpired):
        media_tools.run(["ffprobe", "input.mp4"], timeout=1)


def test_native_media_rejects_global_working_directory(native):
    with pytest.raises(ValueError):
        media_tools.run(["ffmpeg", "-version"], cwd="/private")


def test_android_hls_assembly_uses_absolute_paths_without_process_cwd(tmp_path, monkeypatch):
    from animelab.models.download_task import DownloadTask
    from animelab.services.download_manager import DownloadManagerService
    from pathlib import Path

    folder = tmp_path / "episode's segments"
    folder.mkdir()
    (folder / "seg_00000.ts").write_bytes(b"transport segment")
    output = tmp_path / "episode.mp4"
    old_cwd = Path.cwd()
    calls = []
    class NativeRemux:
        def executeManaged(self, tool, arguments, timeout, job):
            return self.execute(tool, arguments, timeout)
        def pollManaged(self, job):
            return '{}'
        def cancelManaged(self, job):
            pass
        def releaseManaged(self, job):
            pass
        def execute(self, tool, arguments, timeout):
            args = json.loads(arguments)
            calls.append(args)
            manifest = Path(args[args.index("-i") + 1])
            assert tool == "ffmpeg" and timeout == 300000
            assert manifest.is_absolute() and Path(args[-1]).is_absolute()
            assert manifest.read_text() == "file 'seg_00000.ts'\n"
            assert (manifest.parent / "seg_00000.ts").read_bytes() == b"transport segment"
            Path(args[-1]).write_bytes(b"native remuxed output")
            return json.dumps({"returncode": 0, "stdout": "", "stderr": ""})
    monkeypatch.setattr(media_tools, "_native_media", NativeRemux())
    manager = DownloadManagerService()
    task = DownloadTask(fileName="episode.mp4", savePath=str(output))
    manager.media_pipeline._assemble_hls(task, output, folder, 1)
    assert len(calls) == 1
    assert output.read_bytes() == b"native remuxed output"
    assert Path.cwd() == old_cwd


def test_aes_platforms_match_nist_vector(monkeypatch):
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    ciphertext = bytes.fromhex("7649abac8119b246cee98e9b12e9197d")
    plaintext = bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    assert media_tools.decrypt_aes_cbc(ciphertext, key, iv) == plaintext
    class AES:
        @staticmethod
        def decrypt(data, encoded_key, encoded_iv, unpad):
            assert base64.b64decode(data) == ciphertext
            assert base64.b64decode(encoded_key) == key
            assert base64.b64decode(encoded_iv) == iv
            assert not unpad
            return base64.b64encode(plaintext).decode()
    monkeypatch.setattr(media_tools, "_native_aes", AES)
    assert media_tools.decrypt_aes_cbc(ciphertext, key, iv) == plaintext
    with pytest.raises(ValueError):
        media_tools.decrypt_aes_cbc(b"short", key, iv)


@pytest.mark.asyncio
async def test_android_loopback_authentication_includes_assets():
    async def endpoint(scope, receive, send):
        await send({"type": "http.response.start", "status": 200, "headers": []})
        await send({"type": "http.response.body", "body": b"ok"})
    token = "a" * 64
    app = AndroidSessionMiddleware(endpoint, token)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://127.0.0.1") as client:
        assert (await client.get("/spa/")).status_code == 401
        assert (await client.get("/assets/app.js", headers={"X-Animan-Session": "wrong"})).status_code == 401
        assert (await client.get("/spa/", headers={"Cookie": b'animan_android_session="\xff"'})).status_code == 401
        assert (await client.get("/spa/", headers={"X-Animan-Session": token})).status_code == 200
        client.cookies.set("animan_android_session", token)
        assert (await client.get("/api/download/status")).status_code == 200


@pytest.mark.asyncio
async def test_android_rejects_unauthenticated_websocket():
    async def endpoint(*args):
        raise AssertionError("Unauthenticated socket reached the engine")
    output = []
    async def send(message): output.append(message)
    await AndroidSessionMiddleware(endpoint, "a" * 64)({"type": "websocket", "headers": []}, None, send)
    assert output == [{"type": "websocket.close", "code": 1008}]


@pytest.mark.asyncio
async def test_paused_native_export_keeps_the_private_video_completed(monkeypatch, tmp_path):
    from animelab import platform_events
    from animelab.models.download_task import DownloadTask, DownloadStatus
    from animelab.services.download_manager import DownloadManagerService
    from animelab.services.library_service import library_service
    from animelab.services.verification_service import verification_service, VerificationResult
    manager = DownloadManagerService()
    task = DownloadTask(status=DownloadStatus.DOWNLOADING, savePath=str(tmp_path / "episode.mp4"))
    monkeypatch.setattr(verification_service, "verify_file", lambda **kwargs: VerificationResult(valid=True, status="VALID"))
    monkeypatch.setattr(library_service, "save_task", lambda task: None)
    monkeypatch.setattr(library_service, "mark_as_downloaded", lambda *args: None)
    monkeypatch.setattr(platform_events, "storage_status_handler", None)
    def export(task):
        assert task.status == DownloadStatus.COMPLETED
        task.paused = True
    monkeypatch.setattr(platform_events, "completed_handler", export)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED
    assert task.completedAt is not None
    assert task.exportStatus.value == "PENDING"
    assert task.error is None


def test_interrupted_mux_is_restored_as_paused(monkeypatch, tmp_path):
    from animelab.models.download_task import DownloadTask, DownloadStatus
    from animelab.services.download_manager import DownloadManagerService
    from animelab.services.library_service import library_service
    manager = DownloadManagerService()
    task = DownloadTask(status=DownloadStatus.MUXING, savePath=str(tmp_path / "missing.mp4"))
    class Entity:
        def to_task(self): return task
    monkeypatch.setattr(library_service, "get_unfinished_tasks", lambda: [Entity()])
    monkeypatch.setattr(library_service, "get_completed_tasks", lambda: [])
    monkeypatch.setattr(library_service, "recover_interrupted_exports", lambda: None)
    monkeypatch.setattr(library_service, "save_task", lambda task: None)
    manager.init_from_db()
    assert task.status == DownloadStatus.PAUSED
    task.status = DownloadStatus.MUXING
    monkeypatch.setattr(manager, "_trigger_process_queue", lambda: None)
    manager.pause_all_downloads()
    assert task.paused and task.status == DownloadStatus.PAUSED


@pytest.mark.asyncio
async def test_storage_controls_validate_actions_and_retry_export(monkeypatch, tmp_path):
    from fastapi import FastAPI
    from animelab import platform_events
    from animelab.routers.library import router
    from animelab.routers.download import router as downloads_router
    from animelab.services.download_manager import download_manager
    from animelab.services.library_service import library_service
    from animelab.models.download_task import DownloadTask, DownloadStatus
    app = FastAPI()
    app.include_router(router)
    app.include_router(downloads_router)
    calls = []
    monkeypatch.setattr(platform_events, 'storage_status_handler', lambda: {'android': True, 'authorized': False})
    monkeypatch.setattr(platform_events, 'storage_action_handler', lambda action: calls.append(action) or {'authorized': True})
    source = tmp_path / 'download.mp4'
    source.write_bytes(b'private media')
    task = DownloadTask(status=DownloadStatus.COMPLETED, savePath=str(source))
    monkeypatch.setattr(download_manager, 'tasks', {task.id: task})
    monkeypatch.setattr(download_manager, 'broadcast_update', lambda task: None)
    monkeypatch.setattr(library_service, 'save_task', lambda task: None)
    def failed_export(task):
        raise PermissionError('Folder access was revoked')
    monkeypatch.setattr(platform_events, 'completed_handler', failed_export)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        assert (await client.get('/api/system/android/storage')).json()['authorized'] is False
        assert (await client.post('/api/download', json={})).status_code == 409
        assert (await client.post('/api/system/android/storage', json={'action': 'arbitrary_command'})).status_code == 400
        assert (await client.post('/api/system/android/storage', json={'action': {}})).status_code == 400
        assert calls == []
        assert (await client.post('/api/system/android/storage', json={'action': 'choose_directory'})).json()['authorized'] is True
        assert calls == ['choose_directory']
        monkeypatch.setattr(platform_events, 'storage_status_handler', lambda: {'android': True, 'authorized': True})
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).status_code == 409
        assert task.status == DownloadStatus.COMPLETED and source.read_bytes() == b'private media'
        assert task.error is None and 'Folder access was revoked' in task.exportError
        monkeypatch.setattr(platform_events, 'completed_handler', lambda task: {'uris': ['content://downloads/1'], 'destination': 'Downloads/AnimeLab'})
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).json()['success']
        assert task.error is None and task.exportError is None and task.exportStatus == 'EXPORTED' and source.exists()
        task.status = DownloadStatus.PAUSED
        assert (await client.post('/api/system/android/export', json={'taskId': task.id})).status_code == 409


@pytest.mark.asyncio
async def test_storage_failure_never_invents_available_capacity(monkeypatch, tmp_path):
    from animelab.routers.library import get_system_storage
    from animelab.config import settings
    from animelab import platform_events
    import shutil
    monkeypatch.setattr(settings, 'DOWNLOAD_DIR', str(tmp_path))
    monkeypatch.setattr(platform_events, 'storage_status_handler', None)
    def denied(path): raise PermissionError('Storage unavailable')
    monkeypatch.setattr(shutil, 'disk_usage', denied)
    result = await get_system_storage()
    assert result['totalBytes'] is None and result['freeBytes'] is None
    assert result['error'] == 'Storage unavailable'


@pytest.mark.asyncio
async def test_remove_task_and_history_purge_private_files_only_on_android(monkeypatch, tmp_path):
    import importlib
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from animelab.database import Base
    from animelab import platform_events
    from animelab.models.download_task import DownloadTask, DownloadStatus, ExportStatus
    from animelab.routers.library import router
    from animelab.services.download_manager import DownloadManagerService
    lib_mod = importlib.import_module('animelab.services.library_service')
    dm_mod = importlib.import_module('animelab.services.download_manager')

    engine = create_engine(f"sqlite:///{tmp_path / 'storage.sqlite'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(lib_mod, 'SessionLocal', sessions)

    dl_dir = tmp_path / 'downloads'
    dl_dir.mkdir()
    manager = DownloadManagerService()
    manager.download_dir = str(dl_dir)
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    monkeypatch.setattr(dm_mod, 'download_manager', manager)

    # Desktop keeps completed media untouched on remove_task.
    monkeypatch.setattr(platform_events, 'completed_handler', None)
    desktop_video = dl_dir / 'Anime' / 'ep1.mp4'
    desktop_video.parent.mkdir()
    desktop_video.write_bytes(b'keep-desktop')
    t_desktop = DownloadTask(animeName='Anime', fileName='ep1.mp4', savePath=str(desktop_video), status=DownloadStatus.COMPLETED)
    manager.tasks[t_desktop.id] = t_desktop
    manager.task_order.append(t_desktop.id)
    assert manager.remove_task(t_desktop.id)
    assert desktop_video.is_file()

    # Android deletes private video copy and prunes empty parent directory on remove_task.
    monkeypatch.setattr(platform_events, 'completed_handler', lambda task: {'uris': ['content://downloads/1']})
    android_video = dl_dir / 'Show' / 'ep1.mp4'
    android_video.parent.mkdir()
    android_video.write_bytes(b'private-android-copy')
    t_android = DownloadTask(animeName='Show', fileName='ep1.mp4', savePath=str(android_video),
                             status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.EXPORTED)
    manager.tasks[t_android.id] = t_android
    manager.task_order.append(t_android.id)
    assert manager.remove_task(t_android.id)
    assert not android_video.exists()
    assert not android_video.parent.exists()

    # DELETE /api/history cleans private files of exported tasks while keeping PENDING-export tasks.
    exported_file = dl_dir / 'Series' / 'exported.mp4'
    pending_file = dl_dir / 'Series' / 'pending.mp4'
    exported_file.parent.mkdir()
    exported_file.write_bytes(b'exported-data')
    pending_file.write_bytes(b'pending-data')
    t_exp = DownloadTask(animeName='Series', fileName='exported.mp4', savePath=str(exported_file),
                         status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.EXPORTED)
    t_pend = DownloadTask(animeName='Series', fileName='pending.mp4', savePath=str(pending_file),
                          status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.PENDING)
    lib_mod.library_service.save_task(t_exp)
    lib_mod.library_service.save_task(t_pend)
    monkeypatch.setattr(dm_mod, 'download_manager', manager)

    from animelab.routers import library as lib_router
    monkeypatch.setattr(lib_router, 'download_manager', manager)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        resp = await client.delete('/api/history')
        assert resp.status_code == 200
    assert not exported_file.exists()
    assert pending_file.is_file()
    engine.dispose()


@pytest.mark.asyncio
async def test_android_storage_cleanup_and_startup_gc(monkeypatch, tmp_path):
    import importlib
    import os
    import time
    from fastapi import FastAPI
    from sqlalchemy import create_engine
    from sqlalchemy.orm import sessionmaker
    from animelab.database import Base
    from animelab import platform_events
    from animelab.models.download_task import DownloadTask, DownloadStatus, ExportStatus
    from animelab.routers.library import router
    from animelab.routers import library as lib_router
    from animelab.services import android_extensions
    from animelab.services.download_manager import DownloadManagerService
    ext_mod = importlib.import_module('animelab.services.extension_service')
    lib_mod = importlib.import_module('animelab.services.library_service')

    engine = create_engine(f"sqlite:///{tmp_path / 'gc.sqlite'}", connect_args={'check_same_thread': False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(lib_mod, 'SessionLocal', sessions)

    dl_dir = tmp_path / 'downloads'
    apks_dir = tmp_path / 'apks'
    dl_dir.mkdir()
    apks_dir.mkdir()
    manager = DownloadManagerService()
    manager.download_dir = str(dl_dir)
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    monkeypatch.setattr(ext_mod, 'APKS_DIR', apks_dir)

    class Bridge:
        @staticmethod
        def operations():
            return json.dumps([{'id': 'op-active', 'state': 'waiting_user', 'sha256': 'keephash'}])

    monkeypatch.setattr(android_extensions, '_bridge', Bridge())
    monkeypatch.setattr(platform_events, 'completed_handler', lambda task: {'uris': ['content://downloads/1']})
    monkeypatch.setattr(platform_events, 'storage_status_handler', lambda: {
        'android': True, 'apiLevel': 29, 'mode': 'downloads', 'destination': 'Downloads/AnimeLab',
        'authorized': True, 'selectionPending': False, 'notificationsGranted': True,
        'installAppsGranted': False, 'batteryUnrestricted': False,
    })

    kept_exported = dl_dir / 'exported_kept.mp4'
    ghost_exported = dl_dir / 'exported_ghost.mp4'
    protected_pending = dl_dir / 'pending_export.mp4'
    orphan_file = dl_dir / 'native-probe' / 'old_probe.mp4'
    orphan_file.parent.mkdir()
    for p, content in [
        (kept_exported, b'k' * 100),
        (ghost_exported, b'g' * 200),
        (protected_pending, b'p' * 300),
        (orphan_file, b'o' * 400),
    ]:
        p.write_bytes(content)
    old_ts = time.time() - 600
    os.utime(orphan_file, (old_ts, old_ts))

    old_apk = apks_dir / 'stalehash.apk'
    active_apk = apks_dir / 'keephash.apk'
    old_apk.write_bytes(b'a' * 500)
    active_apk.write_bytes(b'b' * 600)
    os.utime(old_apk, (old_ts, old_ts))
    os.utime(active_apk, (old_ts, old_ts))

    lib_mod.library_service.save_task(DownloadTask(
        id='t-kept', fileName='exported_kept.mp4', savePath=str(kept_exported),
        status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.EXPORTED,
        exportUrisJson='["content://downloads/keep"]',
    ))
    lib_mod.library_service.save_task(DownloadTask(
        id='t-ghost', fileName='exported_ghost.mp4', savePath=str(ghost_exported),
        status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.EXPORTED,
        exportUrisJson='["content://downloads/deleted"]',
    ))
    lib_mod.library_service.save_task(DownloadTask(
        id='t-pend', fileName='pending_export.mp4', savePath=str(protected_pending),
        status=DownloadStatus.COMPLETED, exportStatus=ExportStatus.PENDING,
    ))

    # Startup GC removes ghost exported video, old orphans and old non-active staged APKs, keeping valid exported & pending copies.
    startup_res = manager.startup_android_storage_cleanup(lambda uri: uri.endswith('keep'))
    assert startup_res['removedFiles'] == 3
    assert startup_res['freedBytes'] == 200 + 400 + 500
    assert not ghost_exported.exists()
    assert not orphan_file.exists()
    assert not old_apk.exists()
    assert kept_exported.is_file()
    assert protected_pending.is_file()
    assert active_apk.is_file()

    # Manual cleanup API reports reclaimableBytes and frees remaining exported duplicates cleanly.
    monkeypatch.setattr(lib_router, 'download_manager', manager)
    app = FastAPI()
    app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://127.0.0.1') as client:
        status_res = (await client.get('/api/system/android/storage')).json()
        assert status_res['reclaimableBytes'] == 100
        assert status_res['exportedPrivateCount'] == 1
        clean_res = (await client.post('/api/system/android/storage/cleanup')).json()
        assert clean_res['success'] is True
        assert clean_res['removedFiles'] == 1
        assert clean_res['freedBytes'] == 100
        assert clean_res['storage']['reclaimableBytes'] == 0
    assert not kept_exported.exists()
    assert protected_pending.is_file()
    assert active_apk.is_file()
    engine.dispose()
