import os
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from pathlib import Path
from fastapi.testclient import TestClient

from run import app
from animelab.database import init_db
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager
from animelab.services.library_service import library_service

@pytest.fixture(scope="module")
def stream_fixture(tmp_path_factory):
    init_db()
    tmp_dir = tmp_path_factory.mktemp("stream_resolve_test")

    # Fichier vidéo existant sur disque
    real_video = tmp_dir / "real_episode_01.mp4"
    real_video.write_bytes(b"FAKE_VIDEO_CONTENT_1234567890")

    # Tâche téléchargée avec fichier existant
    task_dl = DownloadTask(
        id="task-stream-dl-1",
        animeName="Test Anime Stream",
        episodeNumber=1,
        fileName="real_episode_01.mp4",
        savePath=str(real_video),
        downloadPageUrl="https://voir-anime.to/anime/test-anime-stream/ep-01-vostfr/",
        status=DownloadStatus.COMPLETED,
        totalBytes=len(b"FAKE_VIDEO_CONTENT_1234567890"),
    )
    library_service.save_task(task_dl)

    # Tâche avec fichier absent du disque
    missing_video = tmp_dir / "missing_episode_02.mp4"
    task_missing = DownloadTask(
        id="task-stream-missing-2",
        animeName="Test Anime Stream",
        episodeNumber=2,
        fileName="missing_episode_02.mp4",
        savePath=str(missing_video),
        downloadPageUrl="https://voir-anime.to/anime/test-anime-stream/ep-02-vostfr/",
        status=DownloadStatus.COMPLETED,
        totalBytes=1000,
    )
    library_service.save_task(task_missing)

    with TestClient(app) as c:
        yield c, task_dl, task_missing, tmp_dir

def test_find_downloaded_episode(stream_fixture):
    c, task_dl, task_missing, tmp_dir = stream_fixture

    # 1. Épisode téléchargé avec fichier réel sur le disque -> Doit être trouvé
    found = library_service.find_downloaded_episode(
        anime_name="Test Anime Stream",
        episode_number=1,
        episode_url="https://voir-anime.to/anime/test-anime-stream/ep-01-vostfr/"
    )
    assert found is not None
    assert found.id == task_dl.id
    assert os.path.exists(found.savePath)

    # 2. Épisode avec tâche en base mais fichier absent du disque -> Doit retourner None
    not_found_missing = library_service.find_downloaded_episode(
        anime_name="Test Anime Stream",
        episode_number=2,
        episode_url="https://voir-anime.to/anime/test-anime-stream/ep-02-vostfr/"
    )
    assert not_found_missing is None

    # 3. Épisode non téléchargé du tout -> Doit retourner None
    not_found_unknown = library_service.find_downloaded_episode(
        anime_name="Test Anime Stream",
        episode_number=99,
        episode_url="https://voir-anime.to/anime/test-anime-stream/ep-99-vostfr/"
    )
    assert not_found_unknown is None

def test_resolve_stream_local_playback(stream_fixture):
    c, task_dl, _, _ = stream_fixture

    # Appel de /api/media/stream/resolve pour l'épisode 1 (téléchargé sur disque)
    resp = c.get(
        "/api/media/stream/resolve",
        params={
            "animeName": "Test Anime Stream",
            "episodeNumber": 1,
            "episodeUrl": "https://voir-anime.to/anime/test-anime-stream/ep-01-vostfr/",
            "source": "voir-anime",
        }
    )
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["isDownloaded"] is True
    assert data["sourceType"] == "local"
    assert data["streamUrl"] == f"/api/media/stream/{task_dl.id}"
    assert data["taskId"] == task_dl.id
    assert "Disque dur" in data["serverType"]

def test_resolve_stream_remote_playback(stream_fixture):
    c, _, _, _ = stream_fixture

    # Simuler l'extraction distante pour un épisode non téléchargé (épisode 3)
    mock_info = {
        "videoUrl": "https://prx-stream.mockcdn.org/hls/master.m3u8",
        "videoQualities": json.dumps({"1080p": "https://prx-stream.mockcdn.org/hls/1080p.m3u8"}),
        "serverType": "myTV",
        "subtitleUrl": "https://voir-anime.to/subtitles/ep3.vtt",
        "selectedQuality": "1080p",
    }

    with patch("animelab.services.voiranime_service.voiranime_service.extract_download_info", return_value=mock_info):
        resp = c.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "Test Anime Stream",
                "episodeNumber": 3,
                "episodeUrl": "https://voir-anime.to/anime/test-anime-stream/ep-03-vostfr/",
                "source": "voir-anime",
                "server": "myTV",
                "quality": "1080p",
            }
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["isDownloaded"] is False
        assert data["sourceType"] == "remote"
        assert data["streamUrl"] == "https://prx-stream.mockcdn.org/hls/master.m3u8"
        assert data["serverType"] == "myTV"
        assert len(data["subtitles"]) == 1
        assert "subtitle-proxy" in data["subtitles"][0]["src"]

def test_subtitle_proxy(stream_fixture):
    c, _, _, _ = stream_fixture

    # 1. URL SSRF interdite
    resp_ssrf = c.get("/api/media/subtitle-proxy", params={"url": "http://127.0.0.1:8080/internal"})
    assert resp_ssrf.status_code == 400

    # 2. Mock d'un sous-titre distant valide
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = "WEBVTT\n\n1\n00:00:01.000 --> 00:00:03.000\nSous-titre test"

    with patch("animelab.services.source_http.AsyncSourceClient.get", new_callable=AsyncMock, return_value=mock_resp):
        resp = c.get("/api/media/subtitle-proxy", params={"url": "https://vidzy.org/srtproxy/sample.vtt"})
        assert resp.status_code == 200
        assert resp.headers.get("access-control-allow-origin") == "*"
        assert "WEBVTT" in resp.text
