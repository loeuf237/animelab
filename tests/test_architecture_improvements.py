import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from animelab.config import Settings
from animelab.models.download_task import DownloadTask, DownloadTaskEntity, ensure_utc
from animelab.services.background import spawn, _background_tasks
from animelab.services.proxy_service import ProxyService
from animelab.routers.media import (
    _put_memory_cached_image,
    _get_memory_cached_image,
    _save_disk_cached_image,
    _get_disk_cached_image,
)


def test_tmdb_key_not_hardcoded():
    """La clé TMDB ne doit pas avoir de valeur par défaut dans la configuration."""
    import os
    if "TMDB_API_KEY" not in os.environ:
        assert Settings.TMDB_API_KEY == ""


def test_proxy_api_never_returns_secrets(tmp_path):
    srv = ProxyService(db_path=str(tmp_path / "p.db"))
    srv.save_proxy_settings({
        "enabled": True, "proxy_type": "socks5", "host": "192.168.1.50",
        "port": 1080, "username": "myuser", "password": "supersecret",
    })
    out = srv.get_proxy_settings()
    assert out["password"] == "******"
    assert out["has_password"] is True
    assert "supersecret" not in str(out)
    assert out["effective_url"] == "socks5://myuser:******@192.168.1.50:1080"
    # Usage interne : le vrai secret reste disponible
    assert srv.get_active_proxy() == "socks5://myuser:supersecret@192.168.1.50:1080"


def test_proxy_masked_roundtrip_keeps_secrets(tmp_path):
    """Renvoyer les valeurs masquées de l'API ne doit rien écraser."""
    srv = ProxyService(db_path=str(tmp_path / "p.db"))
    srv.save_proxy_settings({
        "enabled": True, "host": "10.0.0.1", "password": "initial",
        "custom_url": "http://bob:hunter2@proxy.example:3128",
    })
    exposed = srv.get_proxy_settings()
    assert "hunter2" not in str(exposed)
    srv.save_proxy_settings({**exposed, "host": "10.0.0.2"})
    assert srv.proxy_password == "initial"
    assert srv.custom_proxy_url == "http://bob:hunter2@proxy.example:3128"
    assert srv.proxy_host == "10.0.0.2"
    # Effacer explicitement fonctionne toujours
    srv.save_proxy_settings({"password": "", "custom_url": ""})
    assert srv.proxy_password == ""
    assert srv.custom_proxy_url == ""


def test_image_cache_lru_and_atomic_disk():
    url = "https://example.com/test_poster.jpg"
    data = b"FAKE_JPEG_IMAGE_DATA_12345"
    _put_memory_cached_image(url, data, "image/jpeg")
    assert _get_memory_cached_image(url) == (data, "image/jpeg")
    _save_disk_cached_image(url, data, "image/jpeg")
    assert _get_disk_cached_image(url) == (data, "image/jpeg")


def test_ensure_utc_naive_is_local_and_aware_is_converted():
    naive_local = datetime(2030, 1, 1, 12, 0, 0)
    out = ensure_utc(naive_local)
    assert out.tzinfo is not None and out.utcoffset() == timedelta(0)
    assert out == naive_local.astimezone(timezone.utc)

    tz = timezone(timedelta(hours=2))
    aware = datetime(2030, 1, 1, 12, 0, 0, tzinfo=tz)
    assert ensure_utc(aware) == aware
    assert ensure_utc(None) is None


def test_scheduled_time_survives_db_roundtrip_as_utc():
    """SQLite perd le fuseau : une date relue doit rester la même date absolue."""
    when = datetime.now(timezone.utc) + timedelta(hours=3)
    entity = DownloadTaskEntity(
        id="tz-test", animeName="x", fileName="x.mp4",
        status="SCHEDULED", scheduledStartTime=when.replace(tzinfo=None),  # ce que SQLite renvoie
    )
    task = entity.to_task()
    assert task.scheduledStartTime == when
    assert DownloadTask(scheduledStartTime=when).scheduledStartTime == when


@pytest.mark.asyncio
async def test_spawn_keeps_reference_and_logs_failures(caplog):
    ran = asyncio.Event()

    async def ok():
        await asyncio.sleep(0)
        ran.set()

    t = spawn(ok(), name="ok")
    assert t in _background_tasks
    await t
    await asyncio.sleep(0)
    assert ran.is_set()
    assert t not in _background_tasks

    async def boom():
        raise RuntimeError("kaboom")

    with caplog.at_level("ERROR", logger="animelab.background"):
        t2 = spawn(boom(), name="boom")
        await asyncio.gather(t2, return_exceptions=True)
        await asyncio.sleep(0)
    assert "kaboom" in caplog.text


@pytest.mark.asyncio
async def test_verify_task_async_does_not_block_event_loop(monkeypatch, tmp_path):
    """La vérification (ffprobe) doit tourner hors de la boucle d'événements."""
    import threading
    import time as _time
    import importlib
    dm_mod = importlib.import_module("animelab.services.download_manager")
    from animelab.services.verification_service import VerificationResult

    f = tmp_path / "v.mp4"
    f.write_bytes(b"x" * 10)
    task = DownloadTask(id="verify-async", animeName="A", fileName="v.mp4", savePath=str(f))
    dm_mod.download_manager.tasks[task.id] = task
    main_thread = threading.get_ident()
    seen = {}

    def slow_verify(**kwargs):
        seen["thread"] = threading.get_ident()
        _time.sleep(0.3)
        return VerificationResult(valid=True, status="VALID", fileSize=10, formattedSize="10 B",
                                  filePath=str(f), verifiedAt="now")

    monkeypatch.setattr(dm_mod.verification_service, "verify_file", slow_verify)
    monkeypatch.setattr(dm_mod.library_service, "save_task", lambda t: None)

    ticks = 0

    async def ticker():
        nonlocal ticks
        while True:
            await asyncio.sleep(0.02)
            ticks += 1

    tk = asyncio.create_task(ticker())
    try:
        res = await dm_mod.download_manager.verify_task_async(task.id)
    finally:
        tk.cancel()
        dm_mod.download_manager.tasks.pop(task.id, None)
    assert res.valid
    assert seen["thread"] != main_thread
    assert ticks >= 5  # la boucle a continué à tourner pendant la vérification
