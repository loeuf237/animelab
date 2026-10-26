from animelab.services.extension_service import extension_service
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
import json
from unittest.mock import patch, AsyncMock
import pytest
from fastapi.testclient import TestClient

from run import app
from animelab.security import is_safe_url
from animelab.services.animepahe_service import animepahe_service
from animelab.models.anime import AnimeResult, AnimeDetail


@pytest.fixture(autouse=True)
def isolated_feed_cache(monkeypatch):
    # Mocked API payloads must never overwrite the application's persistent feed.
    original = animepahe_service.latest_cache, animepahe_service.last_cache_time
    monkeypatch.setattr(animepahe_service, '_save_persistent_cache', lambda: None)
    yield
    animepahe_service.latest_cache, animepahe_service.last_cache_time = original


@pytest.mark.asyncio
async def test_animepahe_search_parsing():
    mock_payload = {
        "total": 2,
        "data": [
            {
                "id": 101,
                "title": "Sousou no Frieren",
                "session": "frieren123",
                "poster": "https://i.animepahe.ru/posters/frieren.jpg",
                "type": "TV",
                "episodes": 28,
                "status": "Finished",
                "season": "Fall",
                "year": 2023
            },
            {
                "id": 102,
                "title": "Frieren Special",
                "session": "frieren_sp",
                "poster": "https://i.animepahe.ru/posters/frieren_sp.jpg",
                "type": "Special",
                "episodes": 1,
                "status": "Finished",
                "season": "",
                "year": 2024
            }
        ]
    }

    with patch.object(animepahe_service, "_fetch_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_payload
        results = await animepahe_service.search_anime("frieren")

        assert len(results) == 2
        assert results[0].title == "Sousou no Frieren"
        assert results[0].source == "animepahe"
        assert "frieren123" in results[0].url
        assert "28" in results[0].episodeInfo
        assert "Fall 2023" in results[0].episodeInfo


@pytest.mark.asyncio
async def test_animepahe_airing_releases():
    mock_airing = {
        "total": 1,
        "data": [
            {
                "id": 201,
                "anime_id": 55,
                "anime_title": "Oshi no Ko Season 2",
                "anime_session": "oshisession",
                "episode": 11,
                "snapshot": "https://i.animepahe.ru/snapshots/oshi.jpg"
            }
        ]
    }

    with patch.object(animepahe_service, "_fetch_api", new_callable=AsyncMock) as mock_api:
        mock_api.return_value = mock_airing
        await animepahe_service.refresh_cache()
        releases = await animepahe_service.get_latest_releases()

        assert len(releases) >= 1
        found = [r for r in releases if r.title == "Oshi no Ko Season 2"]
        assert len(found) == 1
        assert found[0].episodeInfo == "Épisode 11"
        assert found[0].source == "animepahe"


@pytest.mark.asyncio
async def test_animepahe_detail_and_multi_page_episodes():
    sample_detail_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <meta name="id" content="98765">
    </head>
    <body>
        <h1 class="title-wrapper">Sousou no Frieren</h1>
        <div class="anime-synopsis">L'histoire suit l'elfe Frieren après la défaite du roi démon.</div>
        <div class="anime-genre">
            <a href="/genre/adventure">Adventure</a>
            <a href="/genre/fantasy">Fantasy</a>
        </div>
        <div class="anime-poster">
            <a href="https://i.animepahe.ru/posters/frieren_large.jpg"></a>
        </div>
    </body>
    </html>
    """

    page_1_releases = {
        "current_page": 1,
        "last_page": 2,
        "data": [
            {"id": 1, "episode": 1, "session": "ep1session", "snapshot": "https://i.animepahe.ru/ep1.jpg", "title": "Épisode 1"}
        ]
    }
    page_2_releases = {
        "current_page": 2,
        "last_page": 2,
        "data": [
            {"id": 2, "episode": 2, "session": "ep2session", "snapshot": "https://i.animepahe.ru/ep2.jpg", "title": "Épisode 2"}
        ]
    }

    async def mock_fetch_api_side_effect(path, timeout=8.0):
        if "page=1" in path:
            return page_1_releases
        if "page=2" in path:
            return page_2_releases
        return None

    class MockResponse:
        status_code = 200
        text = sample_detail_html

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            return MockResponse()

    with patch.object(animepahe_service, "_get_async_client", return_value=MockAsyncClient()):
        with patch.object(animepahe_service, "_fetch_api", side_effect=mock_fetch_api_side_effect):
            detail = await animepahe_service.get_anime_detail("https://animepahe.ru/anime/oshisession")

            assert detail is not None
            assert detail.title == "Sousou no Frieren"
            assert "Frieren" in detail.synopsis
            assert "Adventure" in detail.genres
            assert len(detail.episodes) == 2
            assert detail.episodes[0].number == 1
            assert detail.episodes[1].number == 2
            assert "ep1session" in detail.episodes[0].playerUrl
            assert "ep2session" in detail.episodes[1].playerUrl


@pytest.mark.asyncio
async def test_animepahe_get_episode_sources():
    sample_play_html = """
    <div id="resolutionMenu">
        <button class="dropdown-item" data-src="https://kwik.cx/e/abc1" data-resolution="720" data-audio="jpn">720p</button>
        <button class="dropdown-item" data-src="https://kwik.cx/e/abc2" data-resolution="1080" data-audio="jpn">1080p</button>
    </div>
    """

    class MockResponse:
        status_code = 200
        text = sample_play_html

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            return MockResponse()

    with patch.object(animepahe_service, "_get_async_client", return_value=MockAsyncClient()):
        sources = await animepahe_service.get_episode_sources("https://animepahe.ru/play/frieren/ep1")

        assert len(sources) == 2
        assert sources[0]["quality"] == "720p"
        assert sources[0]["url"] == "https://kwik.cx/e/abc1"
        assert sources[1]["quality"] == "1080p"
        assert sources[1]["url"] == "https://kwik.cx/e/abc2"


@pytest.mark.asyncio
async def test_kwik_stream_extraction_unpack():
    # Dean Edwards packed JavaScript embedding a direct .mp4 URL
    # eval(function(p,a,c,k,e,d)...)
    # Using try_unpack to unpack and find the mp4 stream
    packed_html = """
    <!DOCTYPE html>
    <html>
    <head><title>Kwik</title></head>
    <body>
    <script type='text/javascript'>
    eval(function(p,a,c,k,e,d){while(c--)if(k[c])p=p.replace(new RegExp('\\b'+c+'\\b','g'),k[c]);return p;}('const 0="1://2.3/4.5";',6,6,'video_src|https|na-01.kwik|cx|teststream|mp4'.split('|')))
    </script>
    </body>
    </html>
    """

    class MockResponse:
        status_code = 200
        text = packed_html
        def raise_for_status(self): pass

    class MockAsyncClient:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url):
            return MockResponse()

    with patch("animelab.services.animepahe_service.source_http.async_client", side_effect=MockAsyncClient):
        stream_url = await animepahe_service.extract_kwik_stream("https://kwik.cx/e/testembed")
        assert stream_url is not None
        assert "https://na-01.kwik.cx/teststream.mp4" in stream_url


def test_animepahe_security_ssrf_whitelist():
    from animelab.security import ALLOWED_SCRAPING_DOMAINS

    # Whitelisted legitimate AnimePahe and Kwik domains
    assert is_safe_url("https://animepahe.ru/anime/test", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is True
    assert is_safe_url("https://animepahe.com/api?m=search&q=naruto", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is True
    assert is_safe_url("https://kwik.cx/e/123456", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is True
    assert is_safe_url("https://i.animepahe.com/posters/123.jpg", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is True

    # Malicious or SSRF payloads must be rejected
    assert is_safe_url("http://127.0.0.1:8080/admin") is False
    assert is_safe_url("http://169.254.169.254/latest/meta-data/") is False
    assert is_safe_url("https://evil-animepahe.com.attacker.com/steal", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is False
    assert is_safe_url("https://animepahe.com.evil.com/phish", allowed_domains=ALLOWED_SCRAPING_DOMAINS) is False
    assert is_safe_url("file:///etc/passwd") is False


def test_routes_animepahe_search_integration(monkeypatch):
    from animelab.routers import anime as anime_router
    monkeypatch.setattr(scraping_service, 'search_anime', AsyncMock(return_value=[]))
    monkeypatch.setattr(voiranime_service, 'search_anime', AsyncMock(return_value=[]))
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [])
    client = TestClient(app)

    # 1. Search with source=animepahe
    mock_results = [
        AnimeResult(
            id="1",
            title="Dandadan",
            imageUrl="https://i.animepahe.ru/dandadan.jpg",
            url="https://animepahe.ru/anime/dandadan",
            version="VOST / Sub",
            type="Anime",
            episodeInfo="Épisode 12",
            source="animepahe"
        )
    ]

    with patch.object(animepahe_service, "search_anime", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        resp = client.get('/search?q=dandadan&source=animepahe', follow_redirects=False)
        assert resp.status_code == 303
        assert resp.headers['location'] == '/app/?q=dandadan&source=animepahe&search=1'
        mock_search.assert_not_awaited()

    # 2. Search API with source=all includes animepahe
    with patch.object(animepahe_service, "search_anime", new_callable=AsyncMock) as mock_search:
        mock_search.return_value = mock_results

        resp = client.get("/api/search?q=dandadan&source=all")
        assert resp.status_code == 200
        data = resp.json()
        assert any(item.get("source") == "animepahe" and "Dandadan" in item.get("title", "") for item in data)


@pytest.mark.asyncio
async def test_resolve_stream_animepahe():
    client = TestClient(app)

    with patch.object(animepahe_service, "get_episode_sources", new_callable=AsyncMock) as mock_sources:
        mock_sources.return_value = [
            {"name": "Kwik 720p (VO (Sub))", "server": "kwik", "quality": "720p", "url": "https://kwik.cx/e/ep720", "audio": "jpn"},
            {"name": "Kwik 1080p (VO (Sub))", "server": "kwik", "quality": "1080p", "url": "https://kwik.cx/e/ep1080", "audio": "jpn"},
        ]
        with patch.object(animepahe_service, "extract_kwik_stream", new_callable=AsyncMock) as mock_kwik:
            mock_kwik.return_value = "https://stream.kwik.cx/video720.mp4"

            resp = client.get(
                "/api/media/stream/resolve",
                params={
                    "animeName": "Test Anime",
                    "episodeNumber": 1,
                    "episodeUrl": "https://animepahe.ru/play/session/ep1",
                    "source": "animepahe"
                }
            )
            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["serverType"] == "kwik"
            assert data["streamUrl"] == "https://stream.kwik.cx/video720.mp4"
            assert "Kwik 720p (VO (Sub))" in data["qualities"]


@pytest.mark.asyncio
async def test_animepahe_episode_size_estimation_avoids_kwik_spam():
    from animelab.services.download_manager import download_manager

    with patch.object(animepahe_service, "get_episode_sources", new_callable=AsyncMock) as mock_sources:
        mock_sources.return_value = [
            {"name": "Kwik 360p (VO (Sub))", "server": "kwik", "quality": "360p", "url": "https://kwik.cx/e/ep360", "audio": "jpn"},
            {"name": "Kwik 720p (VO (Sub))", "server": "kwik", "quality": "720p", "url": "https://kwik.cx/e/ep720", "audio": "jpn"},
            {"name": "Kwik 1080p (VO (Sub))", "server": "kwik", "quality": "1080p", "url": "https://kwik.cx/e/ep1080", "audio": "jpn"},
        ]
        with patch.object(animepahe_service, "extract_kwik_stream", new_callable=AsyncMock) as mock_kwik:
            info = await download_manager.get_or_resolve_episode_info(
                "https://animepahe.ru/play/session/ep1",
                preferred_quality="720p"
            )

            # extract_kwik_stream must NOT be called to avoid rate-limiting Kwik
            mock_kwik.assert_not_called()

            assert info is not None
            assert info.size > 0
            assert "MB" in info.formatted_size or "Mo" in info.formatted_size
            qualities_sizes = json.loads(info.qualities_sizes_json)
            assert "Kwik 360p (VO (Sub))" in qualities_sizes
            assert "Kwik 720p (VO (Sub))" in qualities_sizes
            assert "Kwik 1080p (VO (Sub))" in qualities_sizes

