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


class TestSSRTemplateTranslation:
    def test_home_page_fr_and_en(self, client):
        # French
        resp_fr = client.get("/?lang=fr")
        assert resp_fr.status_code == 200
        assert "Accueil" in resp_fr.text
        assert "Téléchargements" in resp_fr.text

        # English
        resp_en = client.get("/?lang=en")
        assert resp_en.status_code == 200
        assert "Home" in resp_en.text
        assert "Downloads" in resp_en.text
        assert "Your all-in-one anime platform" in resp_en.text

    def test_downloads_page_en(self, client):
        resp = client.get("/downloads?lang=en")
        assert resp.status_code == 200
        assert "Downloads" in resp.text
        assert "Completed" in resp.text

    def test_library_page_en(self, client):
        resp = client.get("/library?lang=en")
        assert resp.status_code == 200
        assert "Local Library" in resp.text

    def test_history_page_en(self, client):
        resp = client.get("/history?lang=en")
        assert resp.status_code == 200
        assert "History" in resp.text
        assert "All" in resp.text

    def test_settings_page_en(self, client):
        resp = client.get("/settings?lang=en")
        assert resp.status_code == 200
        assert "Configuration" in resp.text
        assert "General" in resp.text
        assert "Language" in resp.text

    def test_extensions_page_en(self, client):
        resp = client.get("/extensions?lang=en")
        assert resp.status_code == 200
        assert "Extension" in resp.text

    def test_sidebar_menu_translation(self, client):
        # When requesting English, sidebar items must be translated to English
        resp_en = client.get("/settings?lang=en")
        assert resp_en.status_code == 200
        assert 'id="nav-home"' in resp_en.text
        assert ">Home<" in resp_en.text or "<span>Home</span>" in resp_en.text
        assert ">Downloads<" in resp_en.text or "<span>Downloads</span>" in resp_en.text
        assert ">Library<" in resp_en.text or "<span>Library</span>" in resp_en.text
        assert ">History<" in resp_en.text or "<span>History</span>" in resp_en.text
        assert ">Extensions<" in resp_en.text or "<span>Extensions</span>" in resp_en.text
        assert ">Settings<" in resp_en.text or "<span>Settings</span>" in resp_en.text

        # When requesting French, sidebar items must be translated to French
        resp_fr = client.get("/settings?lang=fr")
        assert resp_fr.status_code == 200
        assert ">Accueil<" in resp_fr.text or "<span>Accueil</span>" in resp_fr.text
        assert ">Paramètres<" in resp_fr.text or "<span>Paramètres</span>" in resp_fr.text

    def test_settings_save_button_cleanup(self, client):
        resp = client.get("/settings")
        assert resp.status_code == 200
        # Exactly one save-settings-btn in the document
        assert resp.text.count('id="save-settings-btn"') == 1
        # No save-settings-btn-bottom proxy button
        assert "save-settings-btn-bottom" not in resp.text
        # No save button in the header
        assert '<header class="settings-header-pro">' in resp.text
        header_part = resp.text.split('<header class="settings-header-pro">')[1].split('</header>')[0]
        assert "save-settings-btn" not in header_part

    def test_middleware_auto_language_detection(self):
        # Fresh client without cookies
        with TestClient(app) as fresh_c:
            resp = fresh_c.get("/", headers={"accept-language": "fr-FR,fr;q=0.9"})
            assert resp.status_code == 200
            assert resp.cookies.get("animan_lang") == "fr"

        with TestClient(app) as fresh_c2:
            resp = fresh_c2.get("/downloads", headers={"accept-language": "en-US,en;q=0.9"})
            assert resp.status_code == 200
            assert resp.cookies.get("animan_lang") == "en"


def test_catalog_uses_request_language_when_no_override(client):
    client.cookies.clear()
    response = client.get('/api/i18n', headers={'Accept-Language': 'en-GB,en;q=0.9'})
    assert response.status_code == 200
    assert response.json()['language'] == 'en'
    assert response.json()['translations']['nav_home'] == 'Home'


def test_legacy_home_defaults_to_animepahe_for_english(client):
    import re
    response = client.get('/?lang=en')
    assert response.status_code == 200
    assert re.search(r'value="animepahe"\s+checked', response.text)
    assert not re.search(r'value="french-manga"\s+checked', response.text)
