import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from pathlib import Path

from run import app
from animan.models.anime import AnimeDetail, Episode, AnimeResult

@pytest.fixture
def client():
    return TestClient(app)

def test_cors_headers(client):
    """Vérifie que les requêtes cross-origin reçoivent les en-têtes CORS nécessaires."""
    resp = client.options(
        "/api/anime/detail",
        headers={
            "Origin": "http://localhost:5173",
            "Access-Control-Request-Method": "GET",
            "Access-Control-Request-Headers": "Authorization,Content-Type",
        },
    )
    assert resp.status_code == 200
    assert resp.headers.get("access-control-allow-origin") == "http://localhost:5173"
    assert "GET" in resp.headers.get("access-control-allow-methods", "")

@pytest.mark.asyncio
async def test_api_anime_detail_success(client):
    mock_detail = AnimeDetail(
        title="Solo Leveling",
        url="https://anime-sama.fr/catalogue/solo-leveling",
        imageUrl="https://anime-sama.fr/images/solo.jpg",
        synopsis="Chasseur de rang E devenant invincible.",
        genres=["Action", "Fantasy"],
        version="VOSTFR",
        episodes=[
            Episode(
                number=1,
                title="Épisode 01",
                playerUrl="https://video.sibnet.ru/shell.php?videoid=111",
                downloadPageUrl="https://video.sibnet.ru/shell.php?videoid=111",
                version="VOSTFR",
            ),
            Episode(
                number=2,
                title="Épisode 02",
                playerUrl="https://video.sibnet.ru/shell.php?videoid=222",
                downloadPageUrl="https://video.sibnet.ru/shell.php?videoid=222",
                version="VOSTFR",
            ),
        ],
    )

    with patch("animan.services.extension_service.extension_service.get_container_source_by_id", return_value=None):
        with patch("animan.services.scraping_service.scraping_service.get_anime_detail", new_callable=AsyncMock) as mock_get:
            mock_get.return_value = mock_detail

            resp = client.get(
                "/api/anime/detail",
                params={
                    "url": "https://french-manga.net/anime/solo-leveling",
                    "source": "french-manga",
                },
            )

            assert resp.status_code == 200
            data = resp.json()
            assert data["success"] is True
            assert data["source"] == "french-manga"
            assert data["anime"]["title"] == "Solo Leveling"
            assert data["totalEpisodes"] == 2
            assert len(data["anime"]["episodes"]) == 2
            ep1 = data["anime"]["episodes"][0]
            assert ep1["number"] == 1
            assert "Épisode 1" in ep1["title"] or "Épisode 01" in ep1["title"]
            assert "isWatched" in ep1
            assert "isDownloaded" in ep1

@pytest.mark.asyncio
async def test_api_anime_detail_not_found(client):
    with patch("animan.services.scraping_service.scraping_service.get_anime_detail", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = None

        resp = client.get(
            "/api/anime/detail",
            params={
                "url": "https://french-manga.net/anime/introuvable",
                "source": "french-manga",
            },
        )
        assert resp.status_code == 404
        assert resp.json()["detail"] == "Anime introuvable ou URL invalide"

@pytest.mark.asyncio
async def test_api_home_feed(client):
    mock_releases = [
        AnimeResult(
            id="1",
            title="Dandadan",
            url="https://french-manga.net/anime/dandadan",
            imageUrl="https://french-manga.net/dandadan.jpg",
            episodeInfo="Épisode 01",
            source="french-manga",
        )
    ]

    with patch("animan.services.scraping_service.scraping_service.get_latest_releases", new_callable=AsyncMock) as m_fm:
        with patch("animan.services.voiranime_service.voiranime_service.get_latest_releases", new_callable=AsyncMock) as m_va:
            with patch("animan.services.animepahe_service.animepahe_service.get_latest_releases", new_callable=AsyncMock) as m_ap:
                m_fm.return_value = mock_releases
                m_va.return_value = []
                m_ap.return_value = []

                resp = client.get("/api/home/feed")
                assert resp.status_code == 200
                data = resp.json()
                assert data["success"] is True
                assert len(data["latestFrenchManga"]) == 1
                assert data["latestFrenchManga"][0]["title"] == "Dandadan"
                assert "favorites" in data
                assert "enabledExtensions" in data

@pytest.mark.asyncio
async def test_api_source_feed(client):
    mock_releases = [
        AnimeResult(
            id="1",
            title="Bleach TYBW",
            url="https://voir-anime.to/anime/bleach",
            imageUrl="https://voir-anime.to/bleach.jpg",
            episodeInfo="Épisode 27",
            source="voir-anime",
        )
    ]

    with patch("animan.services.voiranime_service.voiranime_service.get_latest_releases", new_callable=AsyncMock) as mock_va:
        mock_va.return_value = mock_releases

        resp = client.get("/api/sources/voir-anime/feed")
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["source"] == "voir-anime"
        assert len(data["releases"]) == 1
        assert data["releases"][0]["title"] == "Bleach TYBW"

@pytest.mark.skipif(
    not (Path(__file__).resolve().parents[1] / "frontend/dist/index.html").is_file(),
    reason="SPA not built: cd frontend && npm ci && npm run build",
)
def test_spa_serving(client):
    """Vérifie que la SPA Vue 3 est servie par FastAPI sous /spa et /app."""
    resp = client.get("/spa")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "AnimeLab" in resp.text

    resp_sub = client.get("/spa/favorites")
    assert resp_sub.status_code == 200
    assert "text/html" in resp_sub.headers.get("content-type", "")

