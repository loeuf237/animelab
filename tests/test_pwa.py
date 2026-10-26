from animelab.services.animepahe_service import animepahe_service
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
import pytest
import hashlib
from urllib.parse import parse_qs, urlparse
from fastapi.testclient import TestClient
from run import app
from animelab.database import init_db
from unittest.mock import AsyncMock

@pytest.fixture(scope="module")
def client():
    init_db()
    from animelab.routers import anime
    with pytest.MonkeyPatch.context() as patch:
        for source in (scraping_service, voiranime_service, animepahe_service):
            patch.setattr(source, "get_latest_releases", AsyncMock(return_value=[]))
        with TestClient(app) as c:
            yield c

def test_pwa_manifest(client):
    resp = client.get("/manifest.json")
    assert resp.status_code == 200
    assert "application/manifest+json" in resp.headers.get("content-type", "")

    manifest = resp.json()
    assert manifest["name"] == "AnimeLab - Anime Downloader & Player"
    assert manifest["short_name"] == "AnimeLab"
    assert manifest["start_url"] == "/app/?source=pwa"
    assert manifest["display"] == "standalone"
    assert manifest["theme_color"] == "#0e121d"
    assert manifest["background_color"] == "#0e121d"

    # Validate icons
    icons = manifest.get("icons", [])
    assert len(icons) >= 3
    icon_sizes = {icon["sizes"] for icon in icons}
    assert "192x192" in icon_sizes
    assert "512x512" in icon_sizes

    # Check maskable icon
    has_maskable = any("maskable" in icon.get("purpose", "") for icon in icons)
    assert has_maskable
    for icon in icons:
        image = client.get(icon["src"])
        assert image.status_code == 200
        assert parse_qs(urlparse(icon["src"]).query)["v"] == [hashlib.sha256(image.content).hexdigest()[:12]]

def test_pwa_service_worker(client):
    resp = client.get("/sw.js")
    assert resp.status_code == 200
    assert resp.headers.get("service-worker-allowed") == "/"
    assert "application/javascript" in resp.headers.get("content-type", "")

    content = resp.text
    # Ensure cache engine and safety exclusions are present
    assert "animelab-cache" in content
    assert 'url.pathname.startsWith("/api/")' in content
    assert "m3u8" in content
    assert "/offline.html" in content

def test_pwa_offline_page(client):
    resp = client.get("/offline.html")
    assert resp.status_code == 200
    assert "text/html" in resp.headers.get("content-type", "")
    assert "hors connexion" in resp.text.lower() or "offline" in resp.text.lower()

def test_pwa_static_assets(client):
    # Legacy assets must not survive removal of the Jinja frontend.
    for path in ('/js/pwa.js', '/js/app.js', '/css/style.css'):
        assert client.get(path).status_code == 404

    # Icons
    for icon_name in ["icon-192.png", "icon-512.png", "icon-maskable.png", "apple-touch-icon.png"]:
        resp_icon = client.get(f"/img/{icon_name}")
        assert resp_icon.status_code == 200
        assert resp_icon.headers.get("content-type") == "image/png"

    favicon = client.get("/favicon.ico")
    assert favicon.status_code == 200
    assert favicon.headers["content-type"] == "image/x-icon"
    assert favicon.content.startswith(b"\x00\x00\x01\x00")

def test_pwa_integration_in_html_pages(client):
    pages = ["/", "/downloads", "/library", "/history", "/settings"]
    for path in pages:
        resp = client.get(path)
        assert resp.status_code == 200
        html = resp.text
        assert 'rel="manifest"' in html
        assert 'href="/manifest.json?v=' in html
        assert 'name="theme-color"' in html
        assert 'name="apple-mobile-web-app-capable"' in html
        assert 'id="app"' in html
        assert '/assets/' in html
        assert '/js/app.js' not in html
