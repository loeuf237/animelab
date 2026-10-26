import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from fastapi.testclient import TestClient
from animelab.services.proxy_service import ProxyService, proxy_service
from run import app


@pytest.fixture
def clean_proxy_service(tmp_path):
    """Crée une instance isolée de ProxyService avec sa propre base de test."""
    db_file = tmp_path / "test_proxy.db"
    return ProxyService(db_path=db_file)


def test_build_proxy_url_variations():
    srv = ProxyService()
    # Cas 1 : vide
    assert srv.build_proxy_url({"host": ""}) is None
    assert srv.build_proxy_url({}) is None

    # Cas 2 : custom_url prioritaire
    custom = "socks5://custom-proxy.internal:9999"
    assert srv.build_proxy_url({"custom_url": custom, "host": "127.0.0.1"}) == custom

    # Cas 3 : socks5 simple
    url = srv.build_proxy_url({"proxy_type": "socks5", "host": "127.0.0.1", "port": 1080})
    assert url == "socks5://127.0.0.1:1080"

    # Cas 4 : http avec port par défaut
    url = srv.build_proxy_url({"proxy_type": "http", "host": "proxy.mycorp.net"})
    assert url == "http://proxy.mycorp.net:8080"

    # Cas 5 : socks5 avec authentification
    url = srv.build_proxy_url({
        "proxy_type": "socks5",
        "host": "192.168.1.100",
        "port": 9050,
        "username": "alice",
        "password": "secret/password!#",
    })
    assert "alice" in url
    assert "secret%2Fpassword%21%23" in url  # URL encoded
    assert url.startswith("socks5://alice:secret")
    assert url.endswith("@192.168.1.100:9050")

    # Cas 6 : socks5h pour résolution DNS distante
    url = srv.build_proxy_url({"proxy_type": "socks5h", "host": "127.0.0.1", "port": 9050})
    assert url == "socks5h://127.0.0.1:9050"


def test_sqlite_persistence(clean_proxy_service):
    srv = clean_proxy_service
    # État initial
    initial = srv.get_proxy_settings()
    assert initial["enabled"] is False
    assert srv.get_active_proxy() is None

    # Sauvegarde
    saved = srv.save_proxy_settings({
        "enabled": True,
        "proxy_type": "socks5",
        "host": "10.0.0.1",
        "port": 1080,
        "username": "user",
        "password": "pass",
    })
    assert saved["enabled"] is True
    assert saved["host"] == "10.0.0.1"
    assert saved["port"] == 1080
    assert saved["username"] == "user"
    # L'API ne renvoie jamais le mot de passe en clair
    assert saved["password"] == "******"
    assert saved["has_password"] is True
    assert "pass" not in saved["effective_url"].replace("password", "")
    assert srv.get_active_proxy() == "socks5://user:pass@10.0.0.1:1080"

    # Rechargement depuis la base
    srv2 = ProxyService(db_path=srv.db_path)
    loaded = srv2.get_proxy_settings()
    assert loaded["enabled"] is True
    assert loaded["host"] == "10.0.0.1"
    assert loaded["port"] == 1080
    assert loaded["username"] == "user"
    assert srv2.get_active_proxy() == "socks5://user:pass@10.0.0.1:1080"

    # Désactivation
    srv.save_proxy_settings({"enabled": False})
    assert srv.get_proxy_settings()["enabled"] is False
    assert srv.get_active_proxy() is None
    # Les champs host et port sont conservés
    assert srv.get_proxy_settings()["host"] == "10.0.0.1"


@pytest.mark.asyncio
async def test_proxy_connection_success():
    srv = ProxyService()
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ip": "198.51.100.42"}

    mock_client = AsyncMock()
    mock_client.__aenter__.return_value = mock_client
    mock_client.get.return_value = mock_resp

    with patch("httpx.AsyncClient", return_value=mock_client):
        res = await srv.test_proxy_connection("socks5://127.0.0.1:1080")
        assert res["success"] is True
        assert res["ip"] == "198.51.100.42"
        assert res["latency_ms"] >= 0


@pytest.mark.asyncio
async def test_proxy_connection_failure():
    srv = ProxyService()
    with patch("httpx.AsyncClient", side_effect=Exception("Connection refused")):
        res = await srv.test_proxy_connection("socks5://127.0.0.1:1080")
        assert res["success"] is False
        assert "Connection refused" in res["error"]


def test_api_proxy_endpoints():
    with TestClient(app) as client:
        # GET settings
        get_res = client.get("/api/proxy/settings")
        assert get_res.status_code == 200
        data = get_res.json()
        assert "enabled" in data
        assert "proxy_type" in data
        assert "host" in data
        assert "port" in data

        # POST settings
        save_res = client.post("/api/proxy/settings", json={
            "enabled": True,
            "proxy_type": "socks5",
            "host": "127.0.0.1",
            "port": 9050,
            "username": "",
            "password": "",
        })
        assert save_res.status_code == 200
        saved_data = save_res.json()
        assert saved_data["success"] is True
        assert saved_data["settings"]["enabled"] is True
        assert saved_data["settings"]["port"] == 9050

        # Proxy configuration is displayed by Vue; the old bookmark redirects.
        page_res = client.get('/settings', follow_redirects=False)
        assert page_res.status_code == 303
        assert page_res.headers['location'] == '/app/settings'

        # Cleanup: disable proxy in shared singleton
        client.post("/api/proxy/settings", json={"enabled": False, "host": ""})


def test_one_click_proxy_enable_and_offline_i18n():
    with TestClient(app) as client:
        # Configuration initiale avec proxy désactivé
        client.post("/api/proxy/settings", json={
            "enabled": False,
            "proxy_type": "socks5",
            "host": "127.0.0.1",
            "port": 1080,
            "username": "tg_user",
            "password": "tg_password",
        })

        # 1-Click activation (comme le bouton Télégram)
        res = client.post("/api/proxy/settings", json={"enabled": True})
        assert res.status_code == 200
        settings = res.json()["settings"]
        assert settings["enabled"] is True
        assert settings["host"] == "127.0.0.1"
        assert settings["port"] == 1080
        assert settings["username"] == "tg_user"
        assert settings["effective_url"] == "socks5://tg_user:******@127.0.0.1:1080"
        assert "tg_password" not in str(settings)
        # Le secret réel reste utilisé en interne
        from animelab.services.proxy_service import proxy_service as _ps
        assert _ps.get_active_proxy() == "socks5://tg_user:tg_password@127.0.0.1:1080"

        # Vérification des traductions i18n du bandeau hors-ligne
        from animelab.services.i18n_service import i18n_service
        for lang in ["fr", "en"]:
            catalog = i18n_service.get_catalog(lang)
            assert "offline_waiting" in catalog
            assert "offline_prompt" in catalog
            assert "offline_btn_enable" in catalog
            assert "offline_btn_configure" in catalog
            assert "offline_reconnected" in catalog

        # Cleanup
        client.post("/api/proxy/settings", json={"enabled": False, "host": ""})
