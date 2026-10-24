"""Incoming Host validation must run before routes, CORS and CSRF handling."""
import pytest
from fastapi import FastAPI
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.testclient import TestClient

from animan.config import parse_allowed_hosts, settings
from run import app


@pytest.fixture
def client():
    # Exercise the middleware without starting background download services.
    instance = TestClient(app)
    yield instance
    instance.close()


def test_production_defaults_only_allow_loopback_hosts():
    assert parse_allowed_hosts(None) == ["127.0.0.1", "localhost"]


def test_host_configuration_normalizes_and_deduplicates():
    assert parse_allowed_hosts(" localhost, ANIME.example.org,localhost, *.example.org, ") == [
        "localhost", "anime.example.org", "*.example.org",
    ]


@pytest.mark.parametrize("value", ["", " , ", "https://anime.example.org", "localhost:8080",
                                   "example.org/path", "*example.org", "*.example.*", "bad host"])
def test_invalid_host_configuration_fails_closed(value):
    with pytest.raises(ValueError, match="ANIMAN_ALLOWED_HOSTS"):
        parse_allowed_hosts(value)


@pytest.mark.parametrize("host", ["localhost", "localhost:8080", "127.0.0.1:8080", "testserver"])
def test_app_accepts_configured_hosts(client, host):
    response = client.get("/favicon.ico", headers={"Host": host})
    assert response.status_code == 200


@pytest.mark.parametrize("method,headers", [
    ("GET", {}),
    ("GET", {"X-Forwarded-Host": "localhost"}),
    ("POST", {"Origin": "http://attacker.example"}),
    ("OPTIONS", {"Origin": "http://localhost:5173", "Access-Control-Request-Method": "GET"}),
])
def test_app_rejects_untrusted_hosts_before_other_middleware(client, method, headers):
    # No lifespan needed: a rejected request must never reach the application.
    response = client.request(method, "/favicon.ico", headers={"Host": "attacker.example", **headers})
    assert response.status_code == 400
    assert response.text == "Invalid host header"
    assert app.user_middleware[0].cls is TrustedHostMiddleware
    assert app.user_middleware[0].kwargs["allowed_hosts"] == settings.ALLOWED_HOSTS


@pytest.mark.parametrize("host,expected", [
    ("192.168.1.50:8080", 200),
    ("anime.example.org", 200),
    ("media.example.net", 200),
    ("example.net", 400),
    ("media.example.net.attacker.org", 400),
    ("unlisted.example.org", 400),
])
def test_custom_lan_domain_and_subdomain_configuration(host, expected):
    application = FastAPI()
    application.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=parse_allowed_hosts("192.168.1.50,anime.example.org,*.example.net"),
        www_redirect=False,
    )

    @application.get("/")
    async def index():
        return {"ok": True}

    with TestClient(application, base_url=f"http://{host}") as client:
        assert client.get("/").status_code == expected
