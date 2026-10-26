import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.database import init_db
from animelab.services.i18n_service import (
    i18n_service,
    t,
    current_lang,
    resolve_language,
    detect_client_language,
    SUPPORTED_LANGUAGES,
)

@pytest.fixture(autouse=True)
def mock_source_feeds(monkeypatch):
    from unittest.mock import AsyncMock
    from animelab.services.scraping_service import scraping_service
    from animelab.services.voiranime_service import voiranime_service
    from animelab.services.animepahe_service import animepahe_service
    for service in (scraping_service, voiranime_service, animepahe_service):
        monkeypatch.setattr(service, "get_latest_releases", AsyncMock(return_value=[]))

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

class TestI18nService:
    def test_supported_languages(self):
        assert "fr" in SUPPORTED_LANGUAGES
        assert "en" in SUPPORTED_LANGUAGES

    def test_default_translations(self):
        # Test both underscore and dot notation
        assert t("nav_home", "fr") == "Accueil"
        assert t("nav.home", "en") == "Home"
        assert t("nav_downloads", "fr") == "Téléchargements"
        assert t("nav.downloads", "en") == "Downloads"

    def test_variable_interpolation(self):
        msg_fr = t("palette_results_count", "fr", count=5)
        assert "5" in msg_fr
        assert "résultat" in msg_fr

        msg_en = t("palette_results_count", "en", count=5)
        assert "5" in msg_en
        assert "result" in msg_en

    def test_missing_key_fallback(self):
        # Non-existent key should return the key itself
        assert t("non.existent.key.xyz", "en") == "non.existent.key.xyz"
        assert t("non.existent.key.xyz", "fr") == "non.existent.key.xyz"

    def test_detect_client_language(self):
        # Francophone accept-language
        assert detect_client_language("fr-FR,fr;q=0.9,en;q=0.8") == "fr"
        assert detect_client_language("fr-CA,fr;q=0.8") == "fr"
        assert detect_client_language("fr") == "fr"

        # Anglophone or other non-francophone
        assert detect_client_language("en-US,en;q=0.9") == "en"
        assert detect_client_language("de-DE,de;q=0.9,es;q=0.8") == "en"
        assert detect_client_language("ja,en;q=0.5") == "en"

    def test_resolve_language_precedence(self):
        # 1. Query parameter has highest priority
        lang = resolve_language("en", "fr", "fr-FR")
        assert lang == "en"

        # 2. Cookie has second priority
        lang = resolve_language(None, "en", "fr-FR")
        assert lang == "en"

        # 3. Accept-Language header francophone detection
        lang = resolve_language(None, None, "fr-FR,fr;q=0.9,en;q=0.8")
        assert lang == "fr"

        # 4. Accept-Language header non-francophone detection (defaults to en)
        lang = resolve_language(None, None, "de-DE,de;q=0.9")
        assert lang == "en"

    def test_catalog_key_parity(self):
        fr_keys = set(i18n_service.get_translations("fr").keys())
        en_keys = set(i18n_service.get_translations("en").keys())
        # All French keys should have an English translation
        missing_in_en = fr_keys - en_keys
        assert not missing_in_en, f"Keys in FR missing in EN: {missing_in_en}"


class TestI18nApi:
    def test_get_i18n_catalog(self, client):
        resp = client.get("/api/i18n?lang=en")
        assert resp.status_code == 200
        data = resp.json()
        assert data["language"] == "en"
        assert "translations" in data
        assert data["translations"]["nav_home"] == "Home"

    def test_set_language_valid(self, client):
        resp = client.post("/api/i18n/set-language", json={"language": "en"})
        assert resp.status_code == 200
        data = resp.json()
        assert data["success"] is True
        assert data["language"] == "en"
        assert "animan_lang" in resp.cookies
        assert resp.cookies["animan_lang"] == "en"

    def test_set_language_invalid(self, client):
        resp = client.post("/api/i18n/set-language", json={"language": "es"})
        assert resp.status_code == 400
        assert "error" in resp.json()


class TestSpaLanguageHandoff:
    @pytest.mark.parametrize('path', ['/', '/downloads', '/library', '/history', '/settings', '/extensions'])
    @pytest.mark.parametrize('lang', ['fr', 'en'])
    def test_legacy_pages_preserve_language(self, client, path, lang):
        response = client.get(path + '?lang=' + lang, follow_redirects=False)
        assert response.status_code == 303
        assert response.cookies.get('animan_lang') == lang
        assert response.headers['location'].endswith('?lang=' + lang)

    @pytest.mark.parametrize('header, lang', [('fr-FR,fr;q=0.9', 'fr'), ('en-US,en;q=0.9', 'en')])
    def test_middleware_auto_language_detection(self, header, lang):
        with TestClient(app) as fresh:
            response = fresh.get('/downloads', headers={'accept-language': header}, follow_redirects=False)
            assert response.status_code == 303
            assert response.cookies.get('animan_lang') == lang


def test_catalog_uses_request_language_when_no_override(client):
    client.cookies.clear()
    response = client.get('/api/i18n', headers={'Accept-Language': 'en-GB,en;q=0.9'})
    assert response.status_code == 200
    assert response.json()['language'] == 'en'
    assert response.json()['translations']['nav_home'] == 'Home'


def test_legacy_home_preserves_english_preference_for_spa(client):
    response = client.get('/?lang=en', follow_redirects=False)
    assert response.headers['location'] == '/app/?lang=en'
    assert response.cookies.get('animan_lang') == 'en'
