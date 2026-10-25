import json
import pytest
from unittest.mock import patch, MagicMock
from animelab.services.voiranime_service import VoirAnimeScrapingService

SAMPLE_SOURCES_HTML = """
<!DOCTYPE html>
<html>
<head>
<script>
var thisChapterSources = {
    "myTV": "https://voembed.net/embed-12345.html",
    "stape": "https://streamtape.com/e/stape12345/",
    "voe": "https://voe.sx/e/voe12345",
    "moon": "https://gn1r5n.org/e/moon12345"
};
</script>
</head>
<body>
</body>
</html>
"""

def test_resolve_voe_download_page_and_html_unescape():
    service = VoirAnimeScrapingService()
    mock_client = MagicMock()

    # 1. Embed page with JS redirect
    embed_resp = MagicMock()
    embed_resp.status_code = 200
    embed_resp.text = '<script>window.location.href = "https://katherineschoolphone.com/e/voe12345";</script>'

    # 2. Redirected page
    redir_resp = MagicMock()
    redir_resp.status_code = 200
    redir_resp.text = '<html><body>VOE player</body></html>'
    redir_resp.url = MagicMock()
    redir_resp.url.host = "katherineschoolphone.com"

    # 3. Download page with HTML-escaped &amp; parameters
    dl_resp = MagicMock()
    dl_resp.status_code = 200
    dl_resp.text = """
    <html>
    <body>
      <a href="https://ugc-cdn.cloudwindow-route.com/engine/download/voe.mp4?t=token123&amp;s=12345&amp;d=1">
        Quality 720p <small>Direct Download Link</small>
      </a>
      <a href="https://ugc-cdn.cloudwindow-route.com/engine/download/voe_1080.mp4?t=token456&amp;s=67890&amp;d=1">
        Quality 1080p <small>Direct Download Link</small>
      </a>
    </body>
    </html>
    """

    mock_client.get.side_effect = [embed_resp, redir_resp, dl_resp]

    best, qualities = service._resolve_voe("https://voe.sx/e/voe12345", "https://voir-anime.to/", mock_client)

    assert "720p (VOE)" in qualities
    assert "1080p (VOE)" in qualities
    assert "&amp;" not in qualities["720p (VOE)"]
    assert "&s=12345" in qualities["720p (VOE)"]
    assert best == qualities["1080p (VOE)"]


def test_quality_selection_closest_match():
    service = VoirAnimeScrapingService()

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = SAMPLE_SOURCES_HTML
        mock_client.get.return_value = page_resp

        # myTV only has 1080p and 480p
        mytv_qualities = {
            "1080p": "https://cdn.example.com/1080p.m3u8",
            "480p": "https://cdn.example.com/480p.m3u8",
        }

        with patch.object(service, "_resolve_mytv", return_value=("https://cdn.example.com/1080p.m3u8", mytv_qualities, "", {})):
            # 1. Requesting 720p should pick 480p (closest available, distance 240 < 360)
            res_720 = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="myTV",
                preferred_quality="720p"
            )
            assert res_720["serverType"] == "myTV"
            assert res_720["selectedQuality"] == "480p"
            assert res_720["videoUrl"] == "https://cdn.example.com/480p.m3u8"

            # 2. Requesting 360p should pick 480p (closest available)
            res_360 = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="myTV",
                preferred_quality="360p"
            )
            assert res_360["selectedQuality"] == "480p"
            assert res_360["videoUrl"] == "https://cdn.example.com/480p.m3u8"

            # 3. Requesting 1080p should pick 1080p
            res_1080 = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="myTV",
                preferred_quality="1080p"
            )
            assert res_1080["selectedQuality"] == "1080p"
            assert res_1080["videoUrl"] == "https://cdn.example.com/1080p.m3u8"


def test_server_selection_preferred_voe_and_moon():
    service = VoirAnimeScrapingService()

    with patch.object(service, "_get_client") as mock_get_client:
        mock_client = MagicMock()
        mock_get_client.return_value.__enter__.return_value = mock_client

        page_resp = MagicMock()
        page_resp.status_code = 200
        page_resp.text = SAMPLE_SOURCES_HTML
        mock_client.get.return_value = page_resp

        # Mock VOE
        voe_qualities = {"720p (VOE)": "https://ugc-cdn.com/voe720.mp4"}
        with patch.object(service, "_resolve_voe", return_value=("https://ugc-cdn.com/voe720.mp4", voe_qualities)):
            res_voe = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="voe"
            )
            assert res_voe["serverType"] == "voe"
            assert res_voe["videoUrl"] == "https://ugc-cdn.com/voe720.mp4"
            assert res_voe["selectedQuality"] == "720p (VOE)"

        # Mock MOON
        moon_qualities = {"1080p (MOON)": "https://gn1r5n.org/api/videos/stream/moon123"}
        with patch.object(service, "_resolve_moon", return_value=("https://gn1r5n.org/api/videos/stream/moon123", moon_qualities)):
            res_moon = service.extract_download_info(
                "https://voir-anime.to/anime/test/ep-1",
                preferred_server="moon"
            )
            assert res_moon["serverType"] == "moon"
            assert res_moon["videoUrl"] == "https://gn1r5n.org/api/videos/stream/moon123"
            assert res_moon["selectedQuality"] == "1080p (MOON)"
