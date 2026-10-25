import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock
from fastapi.testclient import TestClient

from run import app
from animelab.database import init_db
from animelab.services.voiranime_service import voiranime_service
from animelab.services.download_manager import download_manager, ResolvedVideoInfo

init_db()
client = TestClient(app)

SAMPLE_M3U8_MASTER_WITH_BW = """#EXTM3U
#EXT-X-STREAM-INF:BANDWIDTH=3500000,RESOLUTION=1920x1080
https://cdn.example.com/hls/1080p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=1500000,RESOLUTION=1280x720
https://cdn.example.com/hls/720p/index.m3u8
#EXT-X-STREAM-INF:BANDWIDTH=700000,RESOLUTION=852x480
https://cdn.example.com/hls/480p/index.m3u8
"""

SAMPLE_VARIANT_M3U8 = """#EXTM3U
#EXT-X-TARGETDURATION:10
#EXTINF:10.0,
segment0.ts
#EXTINF:10.0,
segment1.ts
#EXTINF:10.0,
segment2.ts
#EXT-X-ENDLIST
"""

def test_get_headers_for_url_domains():
    """Vérifie que les bons Referers et en-têtes sont générés pour chaque hébergeur."""
    # Streamtape
    st_hdrs = download_manager.get_headers_for_url("https://860.tapecontent.net/video.mp4")
    assert st_hdrs["Referer"] == "https://streamtape.com/"

    # myTV (Vidmoly / Voembed / Vmeas)
    mytv_hdrs = download_manager.get_headers_for_url("https://box.vmeas.cloud/hls/master.m3u8")
    assert mytv_hdrs["Referer"] == "https://voembed.net/"

    # Mail.ru
    fhd1_hdrs = download_manager.get_headers_for_url("https://my.mail.ru/video/123.mp4")
    assert fhd1_hdrs["Referer"] == "https://my.mail.ru/"

    # VOE
    voe_hdrs = download_manager.get_headers_for_url("https://johnfullwonder.com/video.mp4")
    assert voe_hdrs["Referer"] == "https://voe.sx/"

    # Moon (Byse / gn1r5n)
    moon_hdrs = download_manager.get_headers_for_url("https://gn1r5n.org/api/videos/stream/xyz")
    assert moon_hdrs["Referer"] == "https://gn1r5n.org/"
    assert moon_hdrs["X-Embed-Origin"] == "voir-anime.to"

    # Vidzy
    vidzy_hdrs = download_manager.get_headers_for_url("https://vidzy.live/stream/video.mp4")
    assert vidzy_hdrs["Referer"] == "https://vidzy.live/"


def test_extract_qualities_and_bandwidths_from_m3u8():
    """Vérifie l'extraction simultanée des qualités et débits binaires (bps)."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = SAMPLE_M3U8_MASTER_WITH_BW
    mock_client.get.return_value = mock_resp

    qualities, bandwidths = voiranime_service._extract_qualities_and_bandwidths_from_m3u8(
        "https://cdn.example.com/hls/master.m3u8", mock_client
    )
    assert "1080p" in qualities
    assert "720p" in qualities
    assert "480p" in qualities
    assert bandwidths["1080p"] == 3500000
    assert bandwidths["720p"] == 1500000
    assert bandwidths["480p"] == 700000


def test_estimate_m3u8_sizes_sync_via_bandwidth():
    """Vérifie le calcul direct exact de la taille par débit et durée."""
    mock_client = MagicMock()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    # 3 segments de 10s = 30s de vidéo
    mock_resp.text = SAMPLE_VARIANT_M3U8
    mock_client.get.return_value = mock_resp

    qualities = {
        "1080p": "https://cdn.example.com/hls/1080p/index.m3u8",
        "480p": "https://cdn.example.com/hls/480p/index.m3u8",
    }
    bandwidths = {
        "1080p": 8000000,  # 8 Mbps = 1 Mo/s -> 30 Mo pour 30s
        "480p": 800000,    # 800 kbps = 100 Ko/s -> 3 Mo pour 30s
    }

    q_sizes = voiranime_service._estimate_m3u8_sizes_sync(
        qualities["1080p"], qualities, bandwidths, mock_client
    )

    # 8 000 000 bps * 30s / 8 = 30 000 000 octets
    assert q_sizes["1080p"] == 30_000_000
    # 800 000 bps * 30s / 8 = 3 000 000 octets
    assert q_sizes["480p"] == 3_000_000


@pytest.mark.asyncio
async def test_estimate_hls_size_async():
    """Vérifie l'estimation asynchrone HLS dans download_manager."""
    # Simuler le client httpx dans estimate_hls_size
    with patch.object(download_manager, "_create_async_client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        master_resp = MagicMock()
        master_resp.status_code = 200
        master_resp.text = SAMPLE_M3U8_MASTER_WITH_BW

        variant_resp = MagicMock()
        variant_resp.status_code = 200
        variant_resp.text = SAMPLE_VARIANT_M3U8

        # 1er appel: master m3u8, 2eme appel: variante m3u8
        mock_client.get.side_effect = [master_resp, variant_resp]
        mock_client_cls.return_value = mock_client

        size = await download_manager.estimate_hls_size(
            "https://cdn.example.com/hls/master.m3u8", server_type="myTV"
        )
        # 3 500 000 bps * 30s / 8 = 13 125 000 octets
        assert size == 13_125_000


@pytest.mark.asyncio
async def test_get_remote_file_size_mp4_head():
    """Vérifie la détection de taille MP4 via HEAD Content-Length."""
    with patch.object(download_manager, "_create_async_client") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.__aenter__.return_value = mock_client
        mock_client.__aexit__.return_value = None

        head_resp = MagicMock()
        head_resp.status_code = 200
        head_resp.headers = {"Content-Length": "250000000"}
        mock_client.head.return_value = head_resp
        mock_client_cls.return_value = mock_client

        size = await download_manager.get_remote_file_size(
            "https://tapecontent.net/video.mp4", server_type="stape"
        )
        assert size == 250_000_000


def test_api_episode_size_returns_qualities_sizes():
    """Vérifie que l'endpoint /api/episode/size retourne formattedSize et qualitiesSizes."""
    fake_info = ResolvedVideoInfo()
    fake_info.server_type = "myTV"
    fake_info.direct_url = "https://cdn.example.com/1080p.m3u8"
    fake_info.size = 350_000_000
    fake_info.formatted_size = "333.8 MB"
    fake_info.selected_quality = "1080p"
    fake_info.selected_server = "myTV"
    fake_info.available_servers = ["myTV", "stape"]
    fake_info.video_qualities_json = json.dumps({"1080p": "url1", "480p": "url2"})
    fake_info.qualities_sizes_json = json.dumps({"1080p": "333.8 MB", "480p": "75.2 MB"})

    with patch.object(download_manager, "get_or_resolve_episode_info", return_value=fake_info):
        resp = client.get("/api/episode/size?url=https://voir-anime.to/anime/test/ep1/&server=myTV")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["formattedSize"] == "333.8 MB"
        assert data["size"] == 350_000_000
        assert data["currentQuality"] == "1080p"
        assert data["currentServer"] == "myTV"
        assert "1080p" in data["qualitiesSizes"]
        assert data["qualitiesSizes"]["1080p"] == "333.8 MB"
        assert data["qualitiesSizes"]["480p"] == "75.2 MB"
