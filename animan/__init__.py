"""AnimeLab - Anime Downloader in Python (FastAPI)."""
import os

__version__ = "0.1.3"

def _sanitize_proxy_env():
    """Normalise automatiquement les URLs de proxy SOCKS de socks:// vers socks5://
    pour assurer la compatibilité complète avec httpx et requests,
    notamment sous Linux/GNOME qui exporte souvent socks://host:port."""
    for var in ("all_proxy", "ALL_PROXY", "socks_proxy", "SOCKS_PROXY"):
        val = os.environ.get(var)
        if val and val.startswith("socks://"):
            os.environ[var] = "socks5://" + val[len("socks://"):]

_sanitize_proxy_env()
