import pytest
from pathlib import Path
from fastapi.testclient import TestClient
from run import app
from animelab.config import settings
from animelab.security import is_safe_url, is_safe_path, anonymize_path
from animelab.services.download_manager import download_manager

@pytest.fixture(scope="module")
def client():
    with TestClient(app) as c:
        yield c

# -------------------------------------------------------------------------
# Faille A : SSRF & Protection Proxy
# -------------------------------------------------------------------------

def test_ssrf_image_proxy_blocks_loopback(client):
    resp = client.get("/api/media/image-proxy?url=http://127.0.0.1:8080/api/download/status")
    assert resp.status_code == 400
    assert "non autorisée" in resp.json()["detail"].lower()

def test_ssrf_image_proxy_blocks_cloud_metadata(client):
    resp = client.get("/api/media/image-proxy?url=http://169.254.169.254/latest/meta-data/")
    assert resp.status_code == 400

def test_ssrf_image_proxy_blocks_private_ip(client):
    resp = client.get("/api/media/image-proxy?url=http://192.168.1.100/secret.jpg")
    assert resp.status_code == 400

def test_ssrf_anime_detail_blocks_internal(client):
    resp = client.get("/anime?url=http://127.0.0.1:8080/api/admin")
    assert resp.status_code == 200
    assert "invalide ou non sécurisée" in resp.text

def test_ssrf_voiranime_blocks_internal(client):
    resp = client.get("/voiranime?url=http://10.0.0.1/admin")
    assert resp.status_code == 200
    assert "invalide ou non sécurisée" in resp.text

def test_is_safe_url_helper():
    assert is_safe_url("http://127.0.0.1") is False
    assert is_safe_url("http://localhost:8080") is False
    assert is_safe_url("http://169.254.169.254") is False
    assert is_safe_url("ftp://voir-anime.to") is False
    assert is_safe_url("") is False

# -------------------------------------------------------------------------
# Faille B : Host de liaison sécurisé par défaut
# -------------------------------------------------------------------------

def test_default_host_is_local():
    assert settings.HOST in ("127.0.0.1", "localhost")

# -------------------------------------------------------------------------
# Faille C : Protection Anti-CSRF
# -------------------------------------------------------------------------

def test_csrf_blocks_cross_site_fetch(client):
    resp = client.post("/api/download/clean", headers={"Sec-Fetch-Site": "cross-site"})
    assert resp.status_code == 403
    assert "cross-site" in resp.json()["error"].lower()

def test_csrf_blocks_unauthorized_origin(client):
    resp = client.post(
        "/api/download/clean",
        headers={"Origin": "https://malicious-site.com"}
    )
    assert resp.status_code == 403
    assert "csrf" in resp.json()["error"].lower()

def test_csrf_allows_local_origin(client):
    resp = client.post(
        "/api/download/clean",
        headers={"Origin": "http://localhost:8080"}
    )
    assert resp.status_code == 200

# -------------------------------------------------------------------------
# Faille D : Validation SSL activée
# -------------------------------------------------------------------------

def test_ssl_verification_is_enabled():
    assert settings.SSL_VERIFY is True

# -------------------------------------------------------------------------
# Faille E : Protection OOM sur Image Proxy
# -------------------------------------------------------------------------

def test_image_proxy_rejects_non_http(client):
    resp = client.get("/api/media/image-proxy?url=file:///etc/passwd")
    assert resp.status_code == 400

# -------------------------------------------------------------------------
# Faille F : Path Traversal
# -------------------------------------------------------------------------

def test_sanitize_file_name_neutralizes_dotdot():
    res = download_manager.sanitize_file_name("../../../etc/shadow")
    assert ".." not in res
    assert "/" not in res
    assert "\\" not in res

def test_is_safe_path_blocks_system_dirs():
    assert is_safe_path("/etc/passwd") is False
    assert is_safe_path(Path.home() / ".ssh" / "id_rsa") is False

# -------------------------------------------------------------------------
# Faille H : Divulgation de chemin
# -------------------------------------------------------------------------

def test_anonymize_path():
    home = str(Path.home())
    test_path = f"{home}/Downloads/Animan"
    anon = anonymize_path(test_path)
    assert anon.startswith("~/")
    assert home not in anon

def test_storage_api_anonymizes_download_dir(client):
    resp = client.get("/api/system/storage")
    assert resp.status_code == 200
    dir_val = resp.json()["downloadDir"]
    assert str(Path.home()) not in dir_val or Path.home().name not in dir_val

# -------------------------------------------------------------------------
# En-têtes de sécurité
# -------------------------------------------------------------------------

def test_security_headers_present(client):
    resp = client.get("/")
    assert resp.headers.get("X-Content-Type-Options") == "nosniff"
    assert resp.headers.get("X-Frame-Options") == "SAMEORIGIN"
