import pytest
import io
import struct
import zipfile
import ipaddress
import os
import socket

# App middleware is configured during collection, before fixtures run. These
# names are test-only; production defaults accept localhost and 127.0.0.1.
os.environ.setdefault("ANIMAN_ALLOWED_HOSTS", "localhost,127.0.0.1,testserver,test")
from animan.config import settings

_system_getaddrinfo = socket.getaddrinfo


@pytest.fixture(autouse=True)
def offline_dns(monkeypatch):
    """Resolve fixture domains offline while preserving numeric/loopback sockets.

    HTTP responses remain mocked by each test. Security tests can override DNS
    to exercise failed resolution or private addresses; SSRF checks stay active.
    """
    from animan import security

    def resolve(host, port, family=0, type=0, proto=0, flags=0):
        if host is not None:
            hostname = host.decode("ascii") if isinstance(host, bytes) else host
            try:
                ipaddress.ip_address(hostname)
            except ValueError:
                if hostname.lower().rstrip(".") == "localhost" or hostname.lower().rstrip(".").endswith(".localhost"):
                    host = "::1" if family == socket.AF_INET6 else "127.0.0.1"
                elif flags & socket.AI_NUMERICHOST:
                    raise socket.gaierror(socket.EAI_NONAME, "Expected a numeric host")
                else:
                    host = "2606:4700:4700::1111" if family == socket.AF_INET6 else "93.184.216.34"
        return _system_getaddrinfo(host, port, family, type, proto, flags)

    # A fresh cache prevents DNS results from one test masking the next one's
    # mocked failure or private address. monkeypatch restores it on teardown.
    monkeypatch.setattr(security, "_DNS_CACHE", {})
    monkeypatch.setattr(socket, "getaddrinfo", resolve)


@pytest.fixture
def extension_apk():
    """Small DEX string table in an APK; exercises the real recipe parser offline."""
    def build(base_url='https://source.example', selector='.new-card'):
        strings = [base_url, selector]
        dex = bytearray(112 + 4 * len(strings))
        dex[:8] = b'dex\n035\0'
        struct.pack_into('<II', dex, 0x38, len(strings), 112)
        for index, value in enumerate(strings):
            struct.pack_into('<I', dex, 112 + index * 4, len(dex))
            encoded = value.encode()
            assert len(encoded) < 128
            dex.extend(bytes([len(value)]) + encoded + b'\0')
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, 'w') as archive:
            archive.writestr('classes.dex', dex)
        return buffer.getvalue()
    return build


@pytest.fixture(autouse=True)
def _tmdb_test_key(monkeypatch):
    """Les tests TMDB mockent le réseau mais exigent une clé non vide.

    La clé n'est plus codée en dur dans la configuration : on injecte une valeur
    factice uniquement pour la durée des tests.
    """
    monkeypatch.setattr(settings, "TMDB_API_KEY", "test-key", raising=False)
