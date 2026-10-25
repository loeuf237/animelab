import json
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from animelab.services.extractors.base import BaseVideoExtractor, ExtractorResult
from animelab.services.extractors.registry import extractor_registry
from animelab.services.extractors.vidmoly import VidmolyExtractor
from animelab.services.extractors.sibnet import SibnetExtractor
from animelab.services.extractors.sendvid import SendvidExtractor
from animelab.services.extractors.streamtape import StreamtapeExtractor
from animelab.services.extractors.voe import VoeExtractor
from animelab.services.extractors.uqload import UqloadExtractor
from animelab.services.extractors.filemoon import FilemoonExtractor
from animelab.services.extractors.doodstream import DoodstreamExtractor
from animelab.services.extractors.mp4upload import Mp4uploadExtractor
from animelab.services.extractors.mailru import MailRuExtractor
from animelab.services.extractors.kwik import KwikExtractor
from animelab.services.extractors.ytdlp_fallback import YtDlpFallbackExtractor

def test_extractor_result_to_download_info():
    res = ExtractorResult(
        video_url="https://example.com/video.mp4",
        server_name="TestServer",
        quality="1080p",
        qualities={"1080p": "https://example.com/video.mp4"},
        size=1024,
    )
    info = res.to_download_info()
    assert info["videoUrl"] == "https://example.com/video.mp4"
    assert info["serverType"] == "TestServer"
    assert info["selectedQuality"] == "1080p"
    assert json.loads(info["videoQualities"]) == {"1080p": "https://example.com/video.mp4"}
    assert info["size"] == 1024

def test_registry_find_and_known_embed():
    assert extractor_registry.is_known_embed("https://video.sibnet.ru/shell.php?videoid=123") is True
    assert extractor_registry.is_known_embed("https://ansembed.net/v/abc123") is True
    assert extractor_registry.is_known_embed("https://streamtape.com/e/xyz") is True
    assert extractor_registry.is_known_embed("https://voe.sx/e/12345") is True
    assert extractor_registry.is_known_embed("https://uqload.is/embed-abc.html") is True
    assert extractor_registry.is_known_embed("https://filemoon.sx/e/foo") is True
    assert extractor_registry.is_known_embed("https://dood.to/e/bar") is True
    assert extractor_registry.is_known_embed("https://www.mp4upload.com/embed-baz.html") is True
    assert extractor_registry.is_known_embed("https://my.mail.ru/video/embed/42") is True
    assert extractor_registry.is_known_embed("https://kwik.cx/e/token") is True
    assert extractor_registry.is_known_embed("https://unknown-domain.org/video") is False

def test_registry_get_headers_for_url():
    h_sibnet = extractor_registry.get_headers_for_url("https://video.sibnet.ru/v/123.mp4")
    assert h_sibnet["Referer"] == "https://video.sibnet.ru/"

    h_stape = extractor_registry.get_headers_for_url("https://tapecontent.net/video/123.mp4")
    assert h_stape["Referer"] == "https://streamtape.com/"

    h_custom_server = extractor_registry.get_headers_for_url("https://example.com/stream", server_type="stape")
    assert h_custom_server["Referer"] == "https://streamtape.com/"

@pytest.mark.asyncio
async def test_vidmoly_extractor():
    extractor = VidmolyExtractor()
    assert extractor.matches("https://ansembed.net/v/12345") is True

    fake_html = 'var player = new Player({ file: "https://vidmoly.net/hls/master.m3u8" });'
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.text = fake_html

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://ansembed.net/v/12345")
        assert res is not None
        assert res.video_url == "https://vidmoly.net/hls/master.m3u8"
        assert res.server_name == "Vidmoly"

@pytest.mark.asyncio
async def test_sibnet_extractor():
    extractor = SibnetExtractor()
    assert extractor.matches("https://video.sibnet.ru/shell.php?videoid=555") is True

    fake_html = '<div id="video">src: "/v/sample_555.mp4"</div>'
    mock_html_resp = MagicMock(status_code=200, text=fake_html)
    mock_range_resp = MagicMock(status_code=206, headers={"Content-Range": "bytes 0-0/998877"})

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [mock_html_resp, mock_range_resp]
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://video.sibnet.ru/shell.php?videoid=555")
        assert res is not None
        assert res.video_url == "https://video.sibnet.ru/v/sample_555.mp4"
        assert res.server_name == "Sibnet"
        assert res.size == 998877

@pytest.mark.asyncio
async def test_sendvid_extractor():
    extractor = SendvidExtractor()
    assert extractor.matches("https://sendvid.com/abcdef") is True

    fake_html = 'var video_source = "https://sendvid.com/storage/sample.mp4";'
    mock_html_resp = MagicMock(status_code=200, text=fake_html)
    mock_head_resp = MagicMock(status_code=200, headers={"Content-Length": "123456"})

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_html_resp
        mock_client.head.return_value = mock_head_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://sendvid.com/abcdef")
        assert res is not None
        assert res.video_url == "https://sendvid.com/storage/sample.mp4"
        assert res.size == 123456

@pytest.mark.asyncio
async def test_streamtape_extractor():
    extractor = StreamtapeExtractor()
    assert extractor.matches("https://streamtape.com/e/abc1234") is True

    fake_html = '''
    <div id="videolink" style="display:none;">//streamtape.com/get_video?id=abc1234&stream=1</div>
    '''
    mock_html_resp = MagicMock(status_code=200, text=fake_html)
    mock_redir_resp = MagicMock(status_code=302, headers={"location": "https://tapecontent.net/video/direct.mp4"})
    mock_head_resp = MagicMock(status_code=200, headers={"Content-Length": "543210"})

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [mock_html_resp, mock_redir_resp]
        mock_client.head.return_value = mock_head_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://streamtape.com/e/abc1234")
        assert res is not None
        assert res.video_url == "https://tapecontent.net/video/direct.mp4"
        assert res.server_name == "Streamtape"
        assert res.size == 543210

@pytest.mark.asyncio
async def test_voe_extractor():
    extractor = VoeExtractor()
    assert extractor.matches("https://voe.sx/e/xyz987") is True

    fake_html = 'var sources = {"hls": "https://delivery-node.voe.sx/hls/playlist.m3u8"};'
    mock_html_resp = MagicMock(status_code=200, text=fake_html, url="https://voe.sx/e/xyz987")

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_html_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://voe.sx/e/xyz987")
        assert res is not None
        assert res.video_url == "https://delivery-node.voe.sx/hls/playlist.m3u8"
        assert res.server_name == "VOE"

@pytest.mark.asyncio
async def test_uqload_extractor():
    extractor = UqloadExtractor()
    assert extractor.matches("https://uqload.is/embed-foo.html") is True

    fake_html = 'sources: ["https://uqload.is/videos/sample.mp4"]'
    mock_html_resp = MagicMock(status_code=200, text=fake_html)
    mock_head_resp = MagicMock(status_code=200, headers={"Content-Length": "887766"})

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_html_resp
        mock_client.head.return_value = mock_head_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://uqload.is/embed-foo.html")
        assert res is not None
        assert res.video_url == "https://uqload.is/videos/sample.mp4"
        assert res.size == 887766

@pytest.mark.asyncio
async def test_filemoon_extractor():
    extractor = FilemoonExtractor()
    assert extractor.matches("https://filemoon.sx/e/testfile") is True

    fake_html = 'sources: [{file: "https://filemoon.sx/hls/master.m3u8"}]'
    mock_html_resp = MagicMock(status_code=200, text=fake_html)

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_html_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://filemoon.sx/e/testfile")
        assert res is not None
        assert res.video_url == "https://filemoon.sx/hls/master.m3u8"
        assert res.server_name == "Filemoon"

@pytest.mark.asyncio
async def test_doodstream_extractor():
    extractor = DoodstreamExtractor()
    assert extractor.matches("https://dood.to/e/dood123") is True

    fake_html = '''
    /pass_md5/dood_token_abc
    function makePlay() { return a + "?token=suffix"; }
    '''
    mock_page_resp = MagicMock(status_code=200, text=fake_html)
    mock_token_resp = MagicMock(status_code=200, text="https://video-delivery.dood.to/stream/")

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.side_effect = [mock_page_resp, mock_token_resp]
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://dood.to/e/dood123")
        assert res is not None
        assert "https://video-delivery.dood.to/stream/" in res.video_url
        assert "token=dood_token_abc" in res.video_url
        assert res.server_name == "Doodstream"

@pytest.mark.asyncio
async def test_mp4upload_extractor():
    extractor = Mp4uploadExtractor()
    assert extractor.matches("https://www.mp4upload.com/embed-999.html") is True

    fake_html = 'player.src("https://mp4upload.com/storage/vid999.mp4");'
    mock_html_resp = MagicMock(status_code=200, text=fake_html)
    mock_head_resp = MagicMock(status_code=200, headers={"Content-Length": "777888"})

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_html_resp
        mock_client.head.return_value = mock_head_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://www.mp4upload.com/embed-999.html")
        assert res is not None
        assert res.video_url == "https://mp4upload.com/storage/vid999.mp4"
        assert res.size == 777888

@pytest.mark.asyncio
async def test_mailru_extractor():
    extractor = MailRuExtractor()
    assert extractor.matches("https://my.mail.ru/video/embed/1234567") is True

    fake_meta = {
        "videos": [
            {"key": "1080", "url": "https://cdn.mail.ru/1080p.mp4"},
            {"key": "720", "url": "https://cdn.mail.ru/720p.mp4"},
        ]
    }
    mock_api_resp = MagicMock(status_code=200)
    mock_api_resp.json.return_value = fake_meta

    with patch.object(extractor, "create_async_client") as mock_client_factory:
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_api_resp
        mock_client_factory.return_value.__aenter__.return_value = mock_client

        res = await extractor.extract("https://my.mail.ru/video/embed/1234567")
        assert res is not None
        assert res.video_url == "https://cdn.mail.ru/1080p.mp4"
        assert res.quality == "1080p"
        assert res.qualities["720p"] == "https://cdn.mail.ru/720p.mp4"

@pytest.mark.asyncio
async def test_kwik_extractor():
    extractor = KwikExtractor()
    assert extractor.matches("https://kwik.cx/e/stream_token") is True

    with patch("animelab.services.animepahe_service.animepahe_service.extract_kwik_stream", new_callable=AsyncMock) as mock_extract:
        mock_extract.return_value = "https://kwik.cx/direct/stream.mp4"
        res = await extractor.extract("https://kwik.cx/e/stream_token")
        assert res is not None
        assert res.video_url == "https://kwik.cx/direct/stream.mp4"
        assert res.server_name == "Kwik"

@pytest.mark.asyncio
async def test_ytdlp_fallback_extractor():
    extractor = YtDlpFallbackExtractor()
    mock_info = {
        "url": "https://unknown.host/direct_stream.m3u8",
        "extractor": "generic",
        "filesize": 1234567,
    }

    with patch("yt_dlp.YoutubeDL") as mock_ydl_cls:
        mock_ydl_instance = MagicMock()
        mock_ydl_instance.extract_info.return_value = mock_info
        mock_ydl_cls.return_value.__enter__.return_value = mock_ydl_instance

        res = await extractor.extract("https://unknown.host/video_page")
        assert res is not None
        assert res.video_url == "https://unknown.host/direct_stream.m3u8"
        assert res.size == 1234567
