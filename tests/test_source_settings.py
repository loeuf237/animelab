import json
import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.services.source_settings_service import source_settings_service
from animelab.services.voiranime_service import VoirAnimeScrapingService


@pytest.fixture
def client():
    return TestClient(app)


def test_source_settings_service_persistence():
    """Vérifie la persistance SQLite et la récupération des paramètres par source."""
    # Test pour VoirAnime
    saved = source_settings_service.save_source_settings("voir-anime", {
        "quality_strategy": "lowest",
        "default_server": "voe"
    })
    assert saved["quality_strategy"] == "lowest"
    assert saved["default_server"] == "voe"

    retrieved = source_settings_service.get_source_settings("voir-anime")
    assert retrieved["quality_strategy"] == "lowest"
    assert retrieved["default_server"] == "voe"

    # Test pour une extension importée
    saved_ext = source_settings_service.save_source_settings("eu.kanade.tachiyomi.animeextension.fr.vostfree", {
        "preferred_host": "sibnet"
    })
    assert saved_ext["preferred_host"] == "sibnet"

    retrieved_ext = source_settings_service.get_source_settings("eu.kanade.tachiyomi.animeextension.fr.vostfree")
    assert retrieved_ext["preferred_host"] == "sibnet"

    # Vérification dans la liste globale
    all_sources = source_settings_service.get_all_sources_with_settings()
    va = next((s for s in all_sources if s["id"] == "voir-anime"), None)
    assert va is not None
    assert va["settings"]["quality_strategy"] == "lowest"


def test_sources_api_endpoints(client):
    """Teste les endpoints GET et POST de /api/sources/settings."""
    # 1. GET /api/sources/settings
    resp = client.get("/api/sources/settings")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert "sources" in data
    assert any(s["id"] == "voir-anime" for s in data["sources"])
    assert any(s["id"] == "animepahe" for s in data["sources"])
    assert any(s["id"] == "french-manga" for s in data["sources"])

    # 2. POST /api/sources/settings/voir-anime
    post_resp = client.post(
        "/api/sources/settings/voir-anime",
        json={"quality_strategy": "highest", "default_server": "myTV"}
    )
    assert post_resp.status_code == 200
    pdata = post_resp.json()
    assert pdata["success"] is True
    assert pdata["settings"]["quality_strategy"] == "highest"

    # 3. Vérification GET unitaire
    get_resp = client.get("/api/sources/settings/voir-anime")
    assert get_resp.status_code == 200
    assert get_resp.json()["settings"]["quality_strategy"] == "highest"


def test_voiranime_quality_strategy_lowest_vs_highest(monkeypatch):
    """Vérifie que VoirAnime sélectionne la qualité la plus faible ou la plus élevée selon la stratégie configurée."""
    service = VoirAnimeScrapingService()

    fake_html = """
    <html>
    <script>
    var thisChapterSources = {
        "LECTEUR myTV": "<iframe src='https://voembed.net/embed-xyz123.html'></iframe>"
    };
    </script>
    </html>
    """

    class DummyResp:
        status_code = 200
        text = fake_html

    class DummyClient:
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def get(self, *args, **kwargs): return DummyResp()

    monkeypatch.setattr(service, "_get_client", lambda *args, **kwargs: DummyClient())

    # Mock _resolve_mytv renvoyant 3 qualités : 1080p, 720p, 480p
    monkeypatch.setattr(
        service,
        "_resolve_mytv",
        lambda *args, **kwargs: (
            "https://cdn.example.com/1080p.m3u8",
            {
                "1080p (myTV)": "https://cdn.example.com/1080p.m3u8",
                "720p (myTV)": "https://cdn.example.com/720p.m3u8",
                "480p (myTV)": "https://cdn.example.com/480p.m3u8",
            },
            "",
            {"1080p (myTV)": 900000000, "720p (myTV)": 500000000, "480p (myTV)": 250000000}
        )
    )

    # 1. Stratégie "lowest" : doit choisir 480p
    res_lowest = service.extract_download_info(
        "https://voir-anime.to/anime/test/ep-1/",
        quality_strategy="lowest"
    )
    assert "480p" in res_lowest["selectedQuality"]
    assert res_lowest["videoUrl"] == "https://cdn.example.com/480p.m3u8"

    # 2. Stratégie "highest" : doit choisir 1080p
    res_highest = service.extract_download_info(
        "https://voir-anime.to/anime/test/ep-1/",
        quality_strategy="highest"
    )
    assert "1080p" in res_highest["selectedQuality"]
    assert res_highest["videoUrl"] == "https://cdn.example.com/1080p.m3u8"


def test_streamtape_anti_trap_resolution(monkeypatch):
    """Vérifie que les pièges d'obfuscation de Streamtape sont éliminés et que le flux 302 est extrait."""
    service = VoirAnimeScrapingService()

    fake_stape_html = """
    <html>
    <script>
    document.getElementById('robotlink').innerHTML = '//streamtape.com/get_videbo?id=3AGWmP37V1idwQG&expires=123' + ('xyz').substring(3);
    document.getElementById('robotlink').innerHTML = '//streamtape.com/get_video?id=b3AGWmP37V1idwQG&expires=123' + ('xyz').substring(3);
    document.getElementById('robotlink').innerHTML = '//streamtape.com/get_video?id=3AGWmP37V1idwQG&expires=123' + ('xyz').substring(3);
    </script>
    </html>
    """

    class DummyClient:
        def get(self, url, *args, **kwargs):
            class Resp:
                def __init__(self, code, loc="", text="", content_type="text/html"):
                    self.status_code = code
                    self.headers = {"location": loc, "content-type": content_type}
                    self.text = text

            if "/e/" in url:
                return Resp(200, text=fake_stape_html, content_type="text/html")
            # Faux pièges
            if "get_videbo" in url or "id=b3AGWm" in url or "bid=" in url:
                return Resp(200, text="<html>Piège 200 HTML</html>", content_type="text/html")
            # Vrai lien désobfusqué
            if "id=3AGWmP37V1idwQG" in url:
                return Resp(302, loc="https://tapecontent.net/video.mp4")
            return Resp(404, text="<html>404</html>")

    client = DummyClient()
    try:
        import curl_cffi.requests
        monkeypatch.setattr(curl_cffi.requests, "get", client.get)
    except Exception:
        pass
    # Test unitaire sur _resolve_streamtape
    res = service._resolve_streamtape("https://streamtape.com/e/3AGWmP37V1idwQG", "https://voir-anime.to/", client)
    assert res == "https://tapecontent.net/video.mp4"
