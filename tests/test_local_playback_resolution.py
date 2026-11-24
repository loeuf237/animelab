"""Regressions for PC disk fallback, mirror/URL mismatches, and Android exported-copy playback."""
import importlib
import json
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from animelab import config as app_config, platform_events
from animelab.api_errors import install_error_handlers
from animelab.database import Base
from animelab.models.anime import AnimeDetail, Episode
from animelab.models.download_task import DownloadStatus, DownloadTask
from animelab.routers import anime, media
from animelab.services.download_manager import download_manager
from animelab.services.extension_service import extension_service
from animelab.services.library_service import library_service
from animelab.services.local_media import find_downloaded_file_on_disk, local_media
from animelab.services.playback_service import PlaybackOpen, playback_service
from animelab.services.voiranime_service import voiranime_service

database_module = importlib.import_module("animelab.database")
library_module = importlib.import_module("animelab.services.library_service")


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "local_playback.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    monkeypatch.setattr(library_module, "SessionLocal", factory)
    monkeypatch.setattr(app_config.settings, "DOWNLOAD_DIR", str(dl_dir))
    monkeypatch.setattr(app_config.settings, "VOIR_ANIME_URL", "https://voiranime.cx")
    monkeypatch.setattr("tempfile.gettempdir", lambda: str(tmp_path / "isolated-temp"))
    monkeypatch.setattr(download_manager, "tasks", {})
    with local_media._lock:
        local_media._entries.clear()

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(media.router)
    with TestClient(app) as client:
        yield client, dl_dir

    with local_media._lock:
        local_media._entries.clear()
    engine.dispose()


@pytest.mark.asyncio
async def test_pc_cleaned_download_on_disk_resolves_and_streams_locally(isolated_env):
    client, dl_dir = isolated_env
    anime_dir = dl_dir / "One Punch Man (VF)"
    anime_dir.mkdir()
    video_file = anime_dir / "One Punch Man (VF) - Episode 1 [VF].mp4"
    video_file.write_bytes(b"0123456789ABCDEF" * 4)
    sub_file = anime_dir / "One Punch Man (VF) - Episode 1 [VF].fr.vtt"
    sub_file.write_text("WEBVTT\n\n00:00:00.000 --> 00:00:02.000\nSalut\n", encoding="utf-8")

    # Simulate WatchProgress left behind after cleaning download_tasks table.
    library_service.mark_as_downloaded(
        "https://voir-anime.to/anime/one-punch-man-vf/", "One Punch Man (VF)", 1, "VF"
    )

    detail = AnimeDetail(
        title="One Punch Man (VF)",
        url="https://voiranime.cx/anime/one-punch-man-vf/",
        version="VF",
        episodes=[
            Episode(
                number=1,
                title="Épisode 1",
                version="VF",
                playerUrl="https://voiranime.cx/anime/one-punch-man-vf/ep-1/",
                downloadPageUrl="https://voiranime.cx/anime/one-punch-man-vf/ep-1/",
            )
        ],
    )
    with patch.object(anime, "is_safe_url", return_value=True), \
         patch.object(anime, "detect_source_from_url", return_value="voir-anime"), \
         patch.object(voiranime_service, "get_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(anime.tmdb_service, "enrich_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None):
        enriched = await anime.fetch_enriched_anime_detail(
            "https://voiranime.cx/anime/one-punch-man-vf/", "voir-anime"
        )

    assert enriched is not None
    ep_payload = enriched["anime"]["episodes"][0]
    assert ep_payload["isDownloaded"] is True
    task_id = ep_payload["downloadTaskId"]
    assert isinstance(task_id, str) and task_id.startswith("local-")

    # Playback session opening also supports disk-registered entries without DB rows.
    state = playback_service.open(PlaybackOpen(taskId=task_id))
    assert state.source == "voir-anime"
    assert state.episodeNumber == 1

    with patch.object(media.voiranime_service, "extract_download_info", side_effect=AssertionError("Must not scrape online")):
        resolved = client.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "One Punch Man (VF)",
                "episodeNumber": 1,
                "episodeUrl": "https://voiranime.cx/anime/one-punch-man-vf/ep-1/",
                "animeUrl": "https://voiranime.cx/anime/one-punch-man-vf/",
                "version": "VF",
                "source": "voir-anime",
                "taskId": task_id,
            },
        )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["isDownloaded"] is True
    assert body["sourceType"] == "local"
    assert body["taskId"] == task_id
    assert body["streamUrl"] == f"/api/media/stream/{task_id}"
    assert len(body["subtitles"]) == 1
    assert body["subtitles"][0]["src"] == f"/api/media/subtitle/{task_id}/0"

    head = client.head(body["streamUrl"])
    assert head.status_code == 200
    assert head.headers["content-length"] == "64"

    full = client.get(body["streamUrl"])
    assert full.status_code == 200
    assert full.content == b"0123456789ABCDEF" * 4

    partial = client.get(body["streamUrl"], headers={"Range": "bytes=4-9"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == "bytes 4-9/64"
    assert partial.content == b"456789"

    sub_resp = client.get(body["subtitles"][0]["src"])
    assert sub_resp.status_code == 200
    assert "WEBVTT" in sub_resp.text


def test_disk_lookup_enforces_strict_version_and_prefers_hardsub(isolated_env):
    _, dl_dir = isolated_env
    anime_dir = dl_dir / "Frieren" / "Season 01"
    anime_dir.mkdir(parents=True)
    vf_orig = anime_dir / "Frieren - S01E01 [VF].mp4"
    vf_hard = anime_dir / "Frieren - S01E01 [VF].hardsub.mp4"
    vf_orig.write_bytes(b"orig")
    vf_hard.write_bytes(b"hardsub")

    assert find_downloaded_file_on_disk("Frieren", 1, version="VF", season=1) == vf_hard.resolve()
    assert find_downloaded_file_on_disk("Frieren", 1, version="VOSTFR", season=1) is None
    assert find_downloaded_file_on_disk("Frieren", 1, version="", season=1) is None


def test_mirror_domain_and_player_url_mismatch_match_db_task(isolated_env):
    client, dl_dir = isolated_env
    video = dl_dir / "opm_ep1.mp4"
    video.write_bytes(b"LOCAL_VIDEO_BYTES")

    task = DownloadTask(
        id="db-only-task-1",
        animeName="One Punch Man (VF)",
        animeUrl="https://voir-anime.to/anime/one-punch-man-vf/",
        episodeNumber=1,
        version="VF",
        source="voir-anime",
        fileName="opm_ep1.mp4",
        savePath=str(video),
        downloadPageUrl="https://voir-anime.to/anime/one-punch-man-vf/download-1/",
        status=DownloadStatus.COMPLETED,
    )
    library_service.save_task(task)
    # Force DB-only path (task absent from in-memory download_manager.tasks).
    download_manager.tasks.clear()

    resolved = client.get(
        "/api/media/stream/resolve",
        params={
            "animeName": "One Punch Man (VF)",
            "episodeNumber": 1,
            "episodeUrl": "https://voiranime.cx/anime/one-punch-man-vf/watch-1/",
            "animeUrl": "https://voiranime.cx/anime/one-punch-man-vf/",
            "version": "VF",
            "source": "voir-anime",
        },
    )
    assert resolved.status_code == 200
    data = resolved.json()
    assert data["isDownloaded"] is True
    assert data["sourceType"] == "local"
    assert data["taskId"] == "db-only-task-1"
    assert client.get(data["streamUrl"]).content == b"LOCAL_VIDEO_BYTES"


def test_android_exported_content_uri_playback_without_private_copy(isolated_env, monkeypatch):
    client, _ = isolated_env
    exported_video = b"ANDROID_EXPORTED_MP4_STREAM_DATA"
    exported_sub = b"WEBVTT\n\n00:00:01.000 --> 00:00:03.000\nAndroid SAF\n"
    storage = {
        "content://downloads/video-1": exported_video,
        "content://downloads/sub-1": exported_sub,
    }

    monkeypatch.setattr(platform_events, "exported_copy_exists_handler", lambda uri: uri in storage)
    monkeypatch.setattr(
        platform_events,
        "exported_copy_size_handler",
        lambda uri: len(storage[uri]) if uri in storage else -1,
    )
    monkeypatch.setattr(
        platform_events,
        "read_exported_copy_handler",
        lambda uri, offset, length: storage[uri][offset : offset + length] if uri in storage else b"",
    )

    task = DownloadTask(
        id="android-exported-1",
        animeName="Dandadan",
        animeUrl="https://voiranime.cx/anime/dandadan/",
        episodeNumber=2,
        version="VOSTFR",
        source="voir-anime",
        fileName="Dandadan - Episode 2 [VOSTFR].mp4",
        savePath="/data/user/0/com.animan.app/files/downloads/Dandadan/ep2.mp4",
        savePathSubtitle="/data/user/0/com.animan.app/files/downloads/Dandadan/ep2.vtt",
        exportUrisJson=json.dumps(["content://downloads/video-1", "content://downloads/sub-1"]),
        status=DownloadStatus.COMPLETED,
    )
    library_service.save_task(task)
    download_manager.tasks.clear()

    resolved = client.get(
        "/api/media/stream/resolve",
        params={
            "animeName": "Dandadan",
            "episodeNumber": 2,
            "episodeUrl": "https://voiranime.cx/anime/dandadan/ep-2/",
            "animeUrl": "https://voiranime.cx/anime/dandadan/",
            "version": "VOSTFR",
            "source": "voir-anime",
        },
    )
    assert resolved.status_code == 200
    body = resolved.json()
    assert body["isDownloaded"] is True
    assert body["sourceType"] == "local"
    assert body["taskId"] == "android-exported-1"
    assert body["streamUrl"] == "/api/media/stream/android-exported-1"
    assert len(body["subtitles"]) == 1

    head = client.head(body["streamUrl"])
    assert head.status_code == 200
    assert head.headers["content-length"] == str(len(exported_video))

    full = client.get(body["streamUrl"])
    assert full.status_code == 200
    assert full.content == exported_video

    partial = client.get(body["streamUrl"], headers={"Range": "bytes=8-15"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == f"bytes 8-15/{len(exported_video)}"
    assert partial.content == exported_video[8:16]

    assert client.get(body["streamUrl"], headers={"Range": "bytes=9999-"}).status_code == 416

    sub_resp = client.get(body["subtitles"][0]["src"])
    assert sub_resp.status_code == 200
    assert "Android SAF" in sub_resp.text

    # If the user deletes the exported file on Android, local match cleanly returns None.
    storage.clear()
    assert library_service.find_downloaded_episode(
        anime_name="Dandadan",
        episode_number=2,
        version="VOSTFR",
        anime_url="https://voiranime.cx/anime/dandadan/",
    ) is None


def test_delete_downloaded_episode_removes_files_tasks_and_flag_while_preserving_watched(
    isolated_env, monkeypatch
):
    client, dl_dir = isolated_env
    season_dir = dl_dir / "Frieren" / "Season 01"
    season_dir.mkdir(parents=True)
    video_file = season_dir / "Frieren - S01E01 [VF].mp4"
    sub_file = season_dir / "Frieren - S01E01 [VF].fr.vtt"
    video_file.write_bytes(b"VIDEO")
    sub_file.write_text("WEBVTT\n", encoding="utf-8")

    anime_url = "https://voiranime.cx/anime/frieren-vf/"
    library_service.mark_as_watched(anime_url, "Frieren", 1, "VF", watched=True)
    library_service.mark_as_downloaded(anime_url, "Frieren", 1, "VF")

    task = DownloadTask(
        id="del-task-1",
        animeName="Frieren",
        animeUrl=anime_url,
        episodeNumber=1,
        version="VF",
        source="voir-anime",
        fileName="Frieren - S01E01 [VF].mp4",
        savePath=str(video_file),
        savePathSubtitle=json.dumps([str(sub_file)]),
        status=DownloadStatus.COMPLETED,
    )
    library_service.save_task(task)
    download_manager.tasks[task.id] = task

    resp = client.post(
        "/api/media/downloaded/delete",
        json={
            "taskId": "del-task-1",
            "animeUrl": anime_url,
            "animeName": "Frieren",
            "episodeNumber": 1,
            "version": "VF",
            "season": 1,
        },
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["success"] is True
    assert body["deletedFiles"] == 2
    assert "del-task-1" in body["removedTaskIds"]
    assert not video_file.exists()
    assert not sub_file.exists()
    assert not season_dir.exists()
    assert not (dl_dir / "Frieren").exists()
    assert dl_dir.exists()
    assert library_service.get_task_entity("del-task-1") is None
    assert library_service.get_downloaded_episodes_set(anime_url) == set()
    assert library_service.get_watched_episodes_set(anime_url) == {"1-VF"}

    # Missing target returns 404 cleanly.
    assert (
        client.post(
            "/api/media/downloaded/delete",
            json={"animeUrl": anime_url, "animeName": "Frieren", "episodeNumber": 1, "version": "VF"},
        ).status_code
        == 404
    )

    # Disk-only local-* entry without DB task also deletes cleanly.
    solo_dir = dl_dir / "Solo Leveling"
    solo_dir.mkdir(parents=True)
    solo_ep = solo_dir / "Solo Leveling - Episode 3 [VOSTFR].mp4"
    solo_ep.write_bytes(b"SOLO")
    entry = local_media.register(
        solo_ep,
        anime_name="Solo Leveling",
        episode_number=3,
        version="VOSTFR",
        anime_url="https://voiranime.cx/anime/solo-leveling/",
    )
    disk_resp = client.post(
        "/api/media/downloaded/delete",
        json={
            "taskId": entry.id,
            "animeUrl": "https://voiranime.cx/anime/solo-leveling/",
            "animeName": "Solo Leveling",
            "episodeNumber": 3,
            "version": "VOSTFR",
        },
    )
    assert disk_resp.status_code == 200
    assert disk_resp.json()["deletedFiles"] == 1
    assert not solo_ep.exists()
    assert local_media.get(entry.id) is None

    # Path traversal outside DOWNLOAD_DIR is rejected with 403.
    evil_file = dl_dir.parent / "secret.mp4"
    evil_file.write_bytes(b"SECRET")
    evil_task = DownloadTask(
        id="evil-del-task",
        animeName="Evil",
        animeUrl="https://voiranime.cx/anime/evil/",
        episodeNumber=1,
        version="VF",
        source="voir-anime",
        fileName="secret.mp4",
        savePath=str(evil_file),
        status=DownloadStatus.COMPLETED,
    )
    library_service.save_task(evil_task)
    assert client.post("/api/media/downloaded/delete", json={"taskId": "evil-del-task"}).status_code == 403
    assert evil_file.exists()

    # Android exported URIs trigger delete_exported_copy_handler.
    deleted_uris: list[str] = []
    monkeypatch.setattr(platform_events, "delete_exported_copy_handler", lambda uri: deleted_uris.append(uri) or True)
    android_task = DownloadTask(
        id="android-del-1",
        animeName="Dandadan",
        animeUrl="https://voiranime.cx/anime/dandadan/",
        episodeNumber=5,
        version="VF",
        source="voir-anime",
        fileName="ep5.mp4",
        savePath=str(dl_dir / "missing_priv_ep5.mp4"),
        exportUrisJson=json.dumps(["content://downloads/v5", "content://downloads/s5"]),
        status=DownloadStatus.COMPLETED,
    )
    library_service.save_task(android_task)
    android_resp = client.post("/api/media/downloaded/delete", json={"taskId": "android-del-1"})
    assert android_resp.status_code == 200
    assert deleted_uris == ["content://downloads/v5", "content://downloads/s5"]
