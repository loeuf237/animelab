import pytest
import json
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient

from run import app
from animelab.services.extension_service import extension_service
from animelab.services.download_manager import download_manager
from animelab.models.download_task import DownloadStatus

@pytest.fixture
def client():
    return TestClient(app)

def test_stream_proxy_ssrf_blocked(client):
    # Test SSRF protection on stream-proxy
    resp = client.get("/api/media/stream-proxy", params={"url": "http://127.0.0.1:8080/secret.mp4"})
    assert resp.status_code == 400
    assert "non autorisée" in resp.json()["detail"]

def test_stream_proxy_options_cors(client):
    resp = client.options("/api/media/stream-proxy", params={"url": "https://example.com/video.mp4"})
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "*"

@pytest.mark.asyncio
async def test_resolve_stream_imported_container_source(client):
    mock_container = MagicMock()
    mock_container.name = "Anime-Sama"
    mock_container.source_id = "animesama"
    mock_container.get_episode_sources = AsyncMock(return_value=[
        {"name": "Anime-Sama - Sibnet", "server": "Sibnet", "url": "https://video.sibnet.ru/shell.php?videoid=12345", "quality": "HD"},
        {"name": "Anime-Sama - Sendvid", "server": "Sendvid", "url": "https://sendvid.com/embed/abcde", "quality": "HD"},
    ])

    resolved_mock = {
        "videoUrl": "https://video.sibnet.ru/v/hash/12345.mp4",
        "serverType": "Sibnet",
        "selectedQuality": "HD",
        "size": 50000000,
    }

    with patch.object(extension_service, "get_container_source_by_id", return_value=mock_container):
        with patch.object(download_manager, "resolve_imported_video_stream", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = resolved_mock

            resp = client.get("/api/media/stream/resolve", params={
                "animeName": "Solo Leveling",
                "episodeNumber": 1,
                "episodeUrl": "https://anime-sama.fr/catalogue/solo-leveling/ep1",
                "source": "animesama",
            })

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["isDownloaded"] is False
            assert data["sourceType"] == "remote"
            assert data["serverType"] == "Sibnet"
            assert "/api/media/stream-proxy" in data["streamUrl"]
            assert "12345.mp4" in data["streamUrl"]
            assert "Sibnet" in data["qualities"]
            assert "Sendvid" in data["qualities"]

@pytest.mark.asyncio
async def test_download_imported_source_task_creation(client):
    mock_container = MagicMock()
    mock_container.name = "Anime-Sama"
    mock_container.source_id = "animesama"
    mock_container.get_episode_sources = AsyncMock(return_value=[
        {"name": "Anime-Sama - Sibnet", "server": "Sibnet", "url": "https://video.sibnet.ru/shell.php?videoid=99999", "quality": "HD"},
    ])

    resolved_mock = {
        "videoUrl": "https://video.sibnet.ru/v/hash/99999.mp4",
        "serverType": "Sibnet",
        "selectedQuality": "HD",
        "size": 120000000,
    }

    with patch.object(extension_service, "get_container_source_by_id", return_value=mock_container):
        with patch.object(download_manager, "resolve_imported_video_stream", new_callable=AsyncMock) as mock_resolve:
            mock_resolve.return_value = resolved_mock

            # 1. Test get_or_resolve_episode_info
            info = await download_manager.get_or_resolve_episode_info(
                "https://anime-sama.fr/catalogue/solo-leveling/ep2",
                source="animesama",
            )
            assert info is not None
            assert info.direct_url == "https://video.sibnet.ru/v/hash/99999.mp4"
            assert info.server_type == "Sibnet"
            assert "Sibnet" in info.available_servers

            # 2. Test start download via API
            resp = client.post("/api/download", json={
                "animeName": "Solo Leveling Test",
                "episodeNumber": 2,
                "url": "https://anime-sama.fr/catalogue/solo-leveling/ep2",
                "fileName": "Solo_Leveling_Test_E02.mp4",
                "source": "animesama",
                "selectedServer": "Sibnet",
            })
            assert resp.status_code == 200
            task_id = resp.json()["taskId"]
            task = download_manager.get_task(task_id)
            assert task is not None
            assert task.source == "animesama"
            assert task.selectedServer == "Sibnet"
            download_manager.cancel_download(task_id)
