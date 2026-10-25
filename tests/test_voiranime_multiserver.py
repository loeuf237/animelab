import json
import pytest
from unittest.mock import patch, MagicMock
from fastapi.testclient import TestClient

from run import app
from animelab.database import init_db
from animelab.models.download_task import DownloadTask, DownloadTaskEntity, DownloadStatus
from animelab.services.voiranime_service import voiranime_service, VoirAnimeScrapingService
from animelab.services.download_manager import download_manager

init_db()
client = TestClient(app)

SAMPLE_MULTI_SERVER_HTML = """
<!DOCTYPE html>
<html>
<head>
<script>
var thisChapterSources = {
    "myTV": "https://voembed.net/embed-abc12345.html",
    "stape": "https://streamtape.com/e/stape67890/",
    "voe": "https://voe.sx/e/voe111213",
    "fhd1": "https://my.mail.ru/video/embed/456789",
    "moon": "https://gn1r5n.org/e/moon999"
};
</script>
</head>
<body>
<div class="entry-content">
  <iframe src="https://voembed.net/embed-abc12345.html"></iframe>
</div>
</body>
</html>
"""

SAMPLE_M3U8_MASTER = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=3500000,RESOLUTION=1920x1080
https://cdn.example.com/hls/1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720
https://cdn.example.com/hls/720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=700000,RESOLUTION=852x480
https://cdn.example.com/hls/480p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=350000,RESOLUTION=640x360
https://cdn.example.com/hls/360p/index.m3u8
"""

def test_parse_episode_sources():
    sources = voiranime_service._parse_episode_sources(SAMPLE_MULTI_SERVER_HTML)
    assert "myTV" in sources
    assert "stape" in sources
    assert "voe" in sources
    assert "fhd1" in sources
    assert "moon" in sources
    assert sources["myTV"] == "https://voembed.net/embed-abc12345.html"
    assert sources["stape"] == "https://streamtape.com/e/stape67890/"


def test_extract_qualities_from_m3u8():
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_M3U8_MASTER
    mock_client.get.return_value = mock_resp

    qualities = voiranime_service._extract_qualities_from_m3u8("https://cdn.example.com/hls/master.m3u8", mock_client)
    assert "1080p" in qualities
    assert "720p" in qualities
    assert "480p" in qualities
    assert "360p" in qualities
    assert qualities["1080p"] == "https://cdn.example.com/hls/1080p/index.m3u8"
    assert qualities["480p"] == "https://cdn.example.com/hls/480p/index.m3u8"


def test_resolve_streamtape_obfuscation():
    sample_stape_html = """
    <html>
    <body>
    <div id="videolink" style="display:none;"></div>
    <script>
    document.getElementById('videolink').innerHTML = "//streamtape.com/get_video?id=xyz" + ('&token=secrettoken').substring(1);
    </script>
    </body>
    </html>
    """
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = sample_stape_html

    # Redirect response
    mock_redir = MagicMock()
    mock_redir.status_code = 302
    mock_redir.headers = {"location": "https://direct.streamtape.com/storage/video.mp4"}

    mock_client.get.side_effect = [mock_resp, mock_redir]

    url = voiranime_service._resolve_streamtape("https://streamtape.com/e/test", "https://voir-anime.to/", mock_client)
    assert url == "https://direct.streamtape.com/storage/video.mp4"


def test_extract_download_info_with_preferred_server_and_quality():
    service = VoirAnimeScrapingService()

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        # 1. Page request
        mock_page_resp = MagicMock()
        mock_page_resp.status_code = 200
        mock_page_resp.text = SAMPLE_MULTI_SERVER_HTML
        mock_client.get.return_value = mock_page_resp

        # Mock _resolve_mytv
        fake_qualities = {
            "1080p": "https://cdn.example.com/1080p.m3u8",
            "480p": "https://cdn.example.com/480p.m3u8",
        }
        with patch.object(service, "_resolve_mytv", return_value=("https://cdn.example.com/1080p.m3u8", fake_qualities, "")):
            # Test requesting 480p
            res = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="myTV",
                preferred_quality="480p"
            )
            assert res["serverType"] == "myTV"
            assert res["selectedQuality"] == "480p"
            assert res["videoUrl"] == "https://cdn.example.com/480p.m3u8"
            avail = json.loads(res["availableServers"])
            assert "myTV" in avail
            assert "stape" in avail


def test_extract_download_info_fallback_when_preferred_fails():
    service = VoirAnimeScrapingService()

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        mock_page_resp = MagicMock()
        mock_page_resp.status_code = 200
        mock_page_resp.text = SAMPLE_MULTI_SERVER_HTML
        mock_client.get.return_value = mock_page_resp

        # Streamtape fails
        with patch.object(service, "_resolve_streamtape", return_value=None):
            # myTV succeeds
            with patch.object(service, "_resolve_mytv", return_value=("https://cdn.example.com/mytv.m3u8", {"1080p": "https://cdn.example.com/mytv.m3u8"}, "")):
                res = service.extract_download_info(
                    "https://voir-anime.to/anime/test/ep-1",
                    preferred_server="stape"
                )
                # Should fall back to myTV
                assert res["serverType"] == "myTV"
                assert res["videoUrl"] == "https://cdn.example.com/mytv.m3u8"


def test_download_task_server_and_quality_serialization():
    task = DownloadTask(
        animeName="Test Anime",
        episodeNumber=1,
        fileName="Test Anime - Episode 1.mp4",
        selectedServer="myTV",
        selectedQuality="480p"
    )
    assert task.selectedServer == "myTV"
    assert task.selectedQuality == "480p"

    t_dict = task.to_dict()
    assert t_dict["selectedServer"] == "myTV"
    assert t_dict["selectedQuality"] == "480p"

    entity = task.to_entity()
    assert entity.selectedServer == "myTV"
    assert entity.selectedQuality == "480p"

    restored = entity.to_task()
    assert restored.selectedServer == "myTV"
    assert restored.selectedQuality == "480p"


def test_settings_api_voiranime_default_server():
    # Test GET settings
    r = client.get("/api/download/settings")
    assert r.status_code == 200
    data = r.json()
    assert "voiranimeDefaultServer" in data

    # Test POST settings with new default server
    payload = {
        "maxConcurrentDownloads": 4,
        "globalSpeedLimit": 0,
        "plexOrganization": False,
        "selectedUserAgent": "Chrome",
        "voiranimeDefaultServer": "stape"
    }
    r_post = client.post("/api/download/settings", json=payload)
    assert r_post.status_code == 200

    assert download_manager.voiranime_default_server == "stape"
    assert voiranime_service.default_server == "stape"

    # Reset
    download_manager.update_settings(3, 0, False, "Chrome", "auto")


def test_api_episode_size_and_servers_endpoints():
    # Test /api/episode/servers with mocked response
    with patch("animelab.services.voiranime_service.voiranime_service.get_episode_servers", return_value=["myTV", "stape", "voe"]):
        r_servers = client.get("/api/episode/servers?url=https://voir-anime.to/anime/test/ep-1")
        assert r_servers.status_code == 200
        res_data = r_servers.json()
        assert res_data["success"] is True
        assert res_data["servers"] == ["myTV", "stape", "voe"]

    # Test /api/episode/size with quality and server query params
    mock_resolved = MagicMock()
    mock_resolved.formatted_size = "250.0 MB"
    mock_resolved.size = 250 * 1024 * 1024
    mock_resolved.direct_url = "https://cdn.example.com/480p.m3u8"
    mock_resolved.subtitle_url = ""
    mock_resolved.server_type = "myTV"
    mock_resolved.available_servers = ["myTV", "stape"]
    mock_resolved.video_qualities_json = json.dumps({"1080p": "https://cdn/1080.m3u8", "480p": "https://cdn/480.m3u8"})
    mock_resolved.selected_quality = "480p"
    mock_resolved.selected_server = "myTV"

    with patch.object(download_manager, "get_or_resolve_episode_info", return_value=mock_resolved):
        r_size = client.get("/api/episode/size?url=https://voir-anime.to/ep-1&server=myTV&quality=480p")
        assert r_size.status_code == 200
        size_data = r_size.json()
        assert size_data["success"] is True
        assert size_data["formattedSize"] == "250.0 MB"
        assert size_data["currentQuality"] == "480p"
        assert "480p" in size_data["qualities"]
        assert "1080p" in size_data["qualities"]
