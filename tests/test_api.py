import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.database import init_db
from unittest.mock import AsyncMock

@pytest.fixture(scope="module")
def client():
    init_db()
    from animelab.routers import anime
    # Page rendering tests should not depend on a live source challenge.
    with pytest.MonkeyPatch.context() as patch:
        for source in (anime.scraping_service, anime.voiranime_service, anime.animepahe_service):
            patch.setattr(source, "get_latest_releases", AsyncMock(return_value=[]))
        with TestClient(app, headers={"Accept-Language": "fr"}) as c:
            yield c

def test_html_pages(client):
    # Home
    resp = client.get("/")
    assert resp.status_code == 200
    assert "AnimeLab" in resp.text

    # Downloads
    resp = client.get("/downloads")
    assert resp.status_code == 200
    assert "téléchargements" in resp.text.lower()

    # Library
    resp = client.get("/library")
    assert resp.status_code == 200
    assert "bibliothèque" in resp.text.lower()

    # History
    resp = client.get("/history")
    assert resp.status_code == 200
    assert "historique" in resp.text.lower()

def test_download_settings(client):
    # GET settings
    resp = client.get("/api/download/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert "maxConcurrentDownloads" in data
    assert "globalSpeedLimit" in data

    # POST settings
    resp = client.post("/api/download/settings", json={
        "maxConcurrentDownloads": 4,
        "globalSpeedLimit": 2048000,
        "plexOrganization": True,
        "selectedUserAgent": "Chrome"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Verify updated settings
    resp = client.get("/api/download/settings")
    data = resp.json()
    assert data["maxConcurrentDownloads"] == 4
    assert data["globalSpeedLimit"] == 2048000
    assert data["plexOrganization"] is True
    assert data["selectedUserAgent"] == "Chrome"

def test_favorites_api(client):
    url = "https://example.com/anime/test-api"
    title = "Test API Anime"

    # Add favorite
    resp = client.post("/api/favorites", json={
        "url": url,
        "title": title,
        "imageUrl": "https://img.com/pic.jpg",
        "source": "french-manga"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Check favorite
    resp = client.get(f"/api/favorites/check?url={url}")
    assert resp.status_code == 200
    assert resp.json().get("isFavorite") is True

    # Auto download toggle
    resp = client.patch("/api/favorites/auto-download", json={
        "url": url,
        "autoDownload": True
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Delete favorite
    resp = client.request("DELETE", "/api/favorites", json={"url": url})
    assert resp.status_code == 200
    assert resp.json().get("success") is True

def test_progress_api(client):
    url = "https://example.com/anime/progress-test"
    resp = client.post("/api/progress/watched", json={
        "animeUrl": url,
        "animeName": "Progress Test",
        "episodeNumber": "5",
        "version": "VOSTFR"
    })
    assert resp.status_code == 200
    assert resp.json().get("success") is True

    # Check progress
    resp = client.get(f"/api/progress?animeUrl={url}")
    assert resp.status_code == 200
    progs = resp.json()
    assert len(progs) > 0
    assert progs[0]["episodeNumber"] == 5
    assert progs[0]["watched"] is True

def test_download_controls(client):
    resp = client.post("/api/download/pause-all")
    assert resp.status_code == 200

    resp = client.post("/api/download/resume-all")
    assert resp.status_code == 200

    resp = client.post("/api/download/clean")
    assert resp.status_code == 200

    resp = client.get("/api/download/status")
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)

def test_system_storage_api(client):
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert "totalBytes" in data
    assert "usedBytes" in data
    assert "freeBytes" in data
    assert "usedPercent" in data

def test_watchdog_check_api(client):
    resp = client.post("/api/watchdog/check")
    assert resp.status_code == 200
    data = resp.json()
    assert data.get("success") is True
    assert "newEpisodes" in data

def test_downloads_page_and_storage_card_removal(client):
    resp = client.get("/downloads")
    assert resp.status_code == 200
    html = resp.text

    # Verify storage card was removed
    assert "sidebar-storage-card" not in html
    assert "storage-percent" not in html

    # Verify download tabs and badges
    assert 'id="tab-badge-queue"' in html
    assert 'id="tab-badge-done"' in html
    assert 'id="tab-badge-all"' in html

    # Verify empty notes exist
    assert 'id="active-empty-note"' in html
    assert 'id="queue-empty-note"' in html
    assert 'id="done-empty-note"' in html
    assert 'id="dl-empty"' in html

def test_settings_page(client):
    resp = client.get("/settings")
    assert resp.status_code == 200
    assert "Paramètres" in resp.text
    assert "settings-page-layout" in resp.text
    assert "save-settings-btn" in resp.text

def test_system_storage_real_stats(client):
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    data = resp.json()
    assert data["totalBytes"] > 0
    assert data["freeBytes"] > 0
    assert data["usedBytes"] >= 0
    assert "downloadDir" in data

def test_clear_history_memory_sync(client):
    from animelab.services.download_manager import download_manager
    from animelab.models.download_task import DownloadTask, DownloadStatus
    task = DownloadTask(
        id="test-clear-sync-1",
        animeName="Test Sync Anime",
        episodeNumber=1,
        fileName="test_sync.mp4",
        downloadPageUrl="https://example.com/test",
        status=DownloadStatus.COMPLETED
    )
    download_manager.tasks[task.id] = task
    download_manager.task_order.append(task.id)

    resp = client.request("DELETE", "/api/history?animeName=Test%20Sync%20Anime")
    assert resp.status_code == 200
    assert "test-clear-sync-1" not in download_manager.tasks

def test_detect_source_from_url():
    from animelab.routers.anime import detect_source_from_url
    assert detect_source_from_url("https://voir-anime.to/anime/toradora/") == "voir-anime"
    assert detect_source_from_url("https://voiranime.to/anime/toradora/") == "voir-anime"
    assert detect_source_from_url("https://w16.french-manga.net/anime/naruto/") == "french-manga"
    assert detect_source_from_url("https://unknown.com/anime/test", fallback="default-source") == "default-source"

def test_search_api_contextual_and_grouping(client, monkeypatch):
    from animelab.models.anime import AnimeResult

    # Mock French-Manga and VoirAnime results
    async def mock_fm_search(q):
        return [
            AnimeResult(id="fm1", title="FM Anime 1", url="https://french-manga.net/anime/1", source="french-manga"),
            AnimeResult(id="fm2", title="FM Anime 2", url="https://french-manga.net/anime/2", source="french-manga")
        ]

    async def mock_va_search(q):
        return [
            AnimeResult(id="va1", title="VA Anime 1", url="https://voir-anime.to/anime/1", source="voir-anime")
        ]

    async def mock_ap_search(q):
        return [
            AnimeResult(id="ap1", title="AP Anime 1", url="https://animepahe.ru/anime/1", source="animepahe")
        ]

    from animelab.services.scraping_service import scraping_service
    from animelab.services.voiranime_service import voiranime_service
    from animelab.services.animepahe_service import animepahe_service
    from animelab.services.extension_service import extension_service
    monkeypatch.setattr(scraping_service, "search_anime", mock_fm_search)
    monkeypatch.setattr(voiranime_service, "search_anime", mock_va_search)
    monkeypatch.setattr(animepahe_service, "search_anime", mock_ap_search)
    monkeypatch.setattr(extension_service, "get_enabled_container_sources", lambda: [])

    # 1. source=all -> Multi-sources grouped: French-Manga, VoirAnime, AnimePahe
    resp = client.get("/api/search?q=test&source=all")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 4
    assert data[0]["source"] == "french-manga"
    assert data[1]["source"] == "french-manga"
    assert data[2]["source"] == "voir-anime"
    assert data[3]["source"] == "animepahe"

    # 2. source=french-manga -> Only French-Manga results, no fallback
    resp = client.get("/api/search?q=test&source=french-manga")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 2
    assert all(d["source"] == "french-manga" for d in data)

    # 3. source=voir-anime -> Only VoirAnime results
    resp = client.get("/api/search?q=test&source=voir-anime")
    assert resp.status_code == 200
    data = resp.json()
    assert len(data) == 1
    assert data[0]["source"] == "voir-anime"

def test_tachiyomi_detail_page_and_source_correction(client, monkeypatch):
    from animelab.models.anime import AnimeDetail, Episode

    async def mock_va_detail(url):
        return AnimeDetail(
            title="Toradora!",
            url=url,
            imageUrl="https://example.com/poster.jpg",
            synopsis="Une histoire d'amour et de tigre de poche.",
            genres=["Comédie", "Romance", "Tranche de vie"],
            episodes=[
                Episode(number=1, title="Tigre et Dragon", version="VOSTFR", playerUrl="https://example.com/p1"),
                Episode(number=2, title="Ryuuji et Taiga", version="VOSTFR", playerUrl="https://example.com/p2"),
            ],
            source="voir-anime"
        )

    from animelab.routers import anime as anime_router
    monkeypatch.setattr(anime_router.voiranime_service, "get_anime_detail", mock_va_detail)

    # User gave a VoirAnime URL with wrong source=french-manga
    wrong_url = "/anime?url=https%3A%2F%2Fvoir-anime.to%2Fanime%2Ftoradora%2F&source=french-manga"
    resp = client.get(wrong_url)
    assert resp.status_code == 200
    html = resp.text

    # Verify content loaded completely (not empty!)
    assert "Toradora!" in html
    assert "Tigre et Dragon" in html
    assert "tigre de poche" in html

    # Verify Tachiyomi layout components are present
    assert "tachiyomi-container" in html
    assert "tachiyomi-topbar" in html
    assert "tach-dl-menu-btn" in html
    assert "tach-filter-btn" in html
    assert "tachiyomi-actions-grid" in html
    assert "tachiyomi-synopsis" in html
    assert "tachiyomi-genres-row" in html
    assert "tachiyomi-fab" in html
    assert "tachiyomi-download-menu" in html
    assert "tachiyomi-filter-sheet" in html

    # Verify restored batch and episode-level features
    assert "tachiyomi-select-bar" in html
    assert "batch-server-select" in html
    assert "batch-quality-select" in html
    assert "batch-subtitles-toggle" in html
    assert "episode-range-bar" in html
    assert "episode-search-input" in html
    assert "episode-check" in html
    assert "btn-play-ep" in html
    assert "btn-download-ep" in html
    assert "subtitle-check" in html

