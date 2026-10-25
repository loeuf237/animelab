from animelab.database import init_db, sqlite_connection
import asyncio
import logging
import os
import random
import re
import time
from pathlib import Path
from typing import List, Optional, Dict, Any, Union
from urllib.parse import quote

import httpx
from animelab.config import settings

logger = logging.getLogger("animelab.proxy_service")

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15",
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0",
]

class ProxyService:
    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self.selected_user_agent: str = "Random (Rotator)"
        self.proxies: List[str] = []
        
        # Paramètres du proxy configuré
        self.proxy_enabled: bool = False
        self.proxy_type: str = "http"
        self.proxy_host: str = ""
        self.proxy_port: Optional[int] = None
        self.proxy_username: str = ""
        self.proxy_password: str = ""
        self.custom_proxy_url: str = ""

        self._init_db()
        self._load_from_db()
        self._load_proxies()

    def _get_conn(self):
        return sqlite_connection(self.db_path)

    def _init_db(self):
        init_db(self.db_path)

    def _load_from_db(self):
        """Charge les paramètres de proxy depuis SQLite."""
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT * FROM network_proxy_settings WHERE id = 1;")
                row = cursor.fetchone()
                if row:
                    self.proxy_enabled = bool(row["enabled"])
                    self.proxy_type = str(row["proxy_type"] or "http").lower()
                    self.proxy_host = str(row["host"] or "").strip()
                    self.proxy_port = row["port"]
                    self.proxy_username = str(row["username"] or "").strip()
                    self.proxy_password = str(row["password"] or "")
                    self.custom_proxy_url = str(row["custom_url"] or "").strip()
                    from animelab.diagnostics import remember_secret
                    remember_secret(self.proxy_password)
        except Exception as e:
            logger.debug("[proxy_service] Impossible de charger les réglages de proxy depuis SQLite: %s", e)

    def _load_proxies(self):
        """Charge les listes statiques de proxy si définies."""
        # 1. From settings
        if settings.PROXIES_CONFIG:
            for p_str in settings.PROXIES_CONFIG.split(","):
                self.add_proxy_str(p_str)

        # 2. From proxies.txt (base dir or current working dir)
        proxies_paths = [
            Path(settings.BASE_DIR).parent / "proxies.txt",
            Path(settings.BASE_DIR) / "proxies.txt",
            Path.cwd() / "proxies.txt",
        ]
        for p_path in proxies_paths:
            if p_path.exists():
                try:
                    with open(p_path, "r", encoding="utf-8") as f:
                        for line in f:
                            self.add_proxy_str(line)
                    break
                except Exception as e:
                    logger.debug("[proxy_service] Erreur lecture proxies.txt: %s", e)

    def add_proxy_str(self, p_str: str):
        p_str = p_str.strip()
        if not p_str or p_str.startswith("#"):
            return
        if p_str.startswith("socks://"):
            p_str = "socks5://" + p_str[len("socks://"):]
        elif not p_str.startswith(("http://", "https://", "socks5://", "socks5h://", "socks4://", "socks4a://")):
            p_str = f"http://{p_str}"
        if p_str not in self.proxies:
            self.proxies.append(p_str)

    def get_selected_user_agent(self) -> str:
        return self.selected_user_agent

    def set_selected_user_agent(self, ua: str):
        if ua and ua.strip():
            self.selected_user_agent = ua.strip()
        else:
            self.selected_user_agent = "Random (Rotator)"

    def get_user_agent(self) -> str:
        ua = self.selected_user_agent
        if not ua or ua == "Random (Rotator)":
            return random.choice(USER_AGENTS)
        if ua == "Chrome":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36"
        if ua == "Firefox":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:126.0) Gecko/20100101 Firefox/126.0"
        if ua == "Safari":
            return "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.4 Safari/605.1.15"
        if ua == "Edge":
            return "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36 Edg/125.0.0.0"
        return ua

    # -------------------------------------------------------------------------
    # Gestion du Proxy Utilisateur (Configuration & Persistance)
    # -------------------------------------------------------------------------

    def build_proxy_url(
        self,
        proxy_type: Union[str, Dict[str, Any]] = "http",
        host: Optional[str] = None,
        port: Optional[int] = None,
        username: str = "",
        password: str = "",
        custom_url: str = ""
    ) -> Optional[str]:
        """Construit l'URL complète du proxy d'après les composants ou un dictionnaire de configuration."""
        if isinstance(proxy_type, dict):
            d = proxy_type
            custom_url = d.get("custom_url") or d.get("customUrl") or ""
            ptype_raw = d.get("proxy_type") or d.get("proxyType") or "http"
            host = d.get("host", "")
            port = d.get("port")
            username = d.get("username", "")
            password = d.get("password", "")
        else:
            ptype_raw = proxy_type

        if custom_url and str(custom_url).strip():
            url = str(custom_url).strip()
            if not url.startswith(("http://", "https://", "socks5://", "socks5h://", "socks4://", "socks4a://")):
                url = f"http://{url}"
            return url

        host = str(host or "").strip()
        if not host:
            return None

        # Nettoyage du protocole
        ptype = (ptype_raw or "http").strip().lower()
        if ptype not in ["http", "https", "socks5", "socks5h", "socks4", "socks4a"]:
            ptype = "http"

        auth = ""
        if username:
            user_quoted = quote(str(username).strip(), safe="")
            pass_quoted = quote(str(password), safe="") if password else ""
            auth = f"{user_quoted}:{pass_quoted}@" if pass_quoted else f"{user_quoted}@"

        if port is not None and str(port).strip() and int(port) > 0:
            port_str = f":{int(port)}"
        elif ":" in host:
            port_str = ""
        else:
            default_ports = {"http": 8080, "https": 8443, "socks5": 1080, "socks5h": 1080, "socks4": 1080, "socks4a": 1080}
            port_str = f":{default_ports.get(ptype, 8080)}"

        return f"{ptype}://{auth}{host}{port_str}"

    MASK = "******"

    @classmethod
    def mask_url(cls, url: str) -> str:
        """Masque le mot de passe d'une URL de proxy (scheme://user:pass@host -> user:******@host)."""
        if not url:
            return ""
        return re.sub(r"(://[^/@:]+):[^/@]*@", r"\1:" + cls.MASK + "@", url)

    def get_masked_proxy_url(self) -> str:
        """Retourne l'URL active du proxy avec le mot de passe masqué."""
        return self.mask_url(self.get_active_proxy() or "")

    def get_proxy_settings(self) -> Dict[str, Any]:
        """Retourne la configuration du proxy pour l'API.

        Aucun secret n'est renvoyé : le mot de passe et les identifiants intégrés
        aux URL sont masqués. Le client renvoie ``******`` pour conserver la valeur.
        """
        masked_effective = self.get_masked_proxy_url()
        masked_custom = self.mask_url(self.custom_proxy_url)
        masked_password = self.MASK if self.proxy_password else ""
        return {
            "enabled": self.proxy_enabled,
            "proxy_type": self.proxy_type,
            "proxyType": self.proxy_type,
            "host": self.proxy_host,
            "port": self.proxy_port,
            "username": self.proxy_username,
            "password": masked_password,
            "has_password": bool(self.proxy_password),
            "hasPassword": bool(self.proxy_password),
            "custom_url": masked_custom,
            "customUrl": masked_custom,
            "effective_url": masked_effective,
            "effectiveUrl": masked_effective,
            "effective_url_masked": masked_effective,
            "effectiveUrlMasked": masked_effective,
        }

    def save_proxy_settings(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """Enregistre la configuration du proxy dans SQLite et recharge l'état en mémoire."""
        if "enabled" in data:
            self.proxy_enabled = bool(data["enabled"])
        if "proxy_type" in data or "proxyType" in data:
            self.proxy_type = str(data.get("proxy_type") or data.get("proxyType") or "http").strip().lower()
        if "host" in data:
            self.proxy_host = str(data.get("host", "") or "").strip()
        
        if "port" in data:
            raw_port = data.get("port")
            try:
                self.proxy_port = int(raw_port) if raw_port is not None and str(raw_port).strip() else None
            except (ValueError, TypeError):
                self.proxy_port = None

        if "username" in data:
            self.proxy_username = str(data.get("username", "") or "").strip()
        if "password" in data:
            pwd = str(data.get("password") or "")
            # Le placeholder renvoyé par l'API signifie « ne pas modifier »
            if pwd != self.MASK:
                self.proxy_password = pwd
        if "custom_url" in data or "customUrl" in data:
            new_custom = str(data.get("custom_url") or data.get("customUrl") or "").strip()
            # Une URL masquée (user:******@host) est ce que l'API renvoie : on garde l'originale
            if new_custom != self.mask_url(self.custom_proxy_url) or not new_custom:
                self.custom_proxy_url = new_custom

        from animelab.diagnostics import remember_secret
        remember_secret(self.proxy_password)
        try:
            with self._get_conn() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    INSERT INTO network_proxy_settings (
                        id, enabled, proxy_type, host, port, username, password, custom_url, updated_at
                    ) VALUES (1, ?, ?, ?, ?, ?, ?, ?, CURRENT_TIMESTAMP)
                    ON CONFLICT(id) DO UPDATE SET
                        enabled = excluded.enabled,
                        proxy_type = excluded.proxy_type,
                        host = excluded.host,
                        port = excluded.port,
                        username = excluded.username,
                        password = excluded.password,
                        custom_url = excluded.custom_url,
                        updated_at = CURRENT_TIMESTAMP;
                """, (
                    1 if self.proxy_enabled else 0,
                    self.proxy_type,
                    self.proxy_host,
                    self.proxy_port,
                    self.proxy_username,
                    self.proxy_password,
                    self.custom_proxy_url,
                ))
                conn.commit()
            logger.info("[proxy_service] Paramètres de proxy enregistrés : enabled=%s, type=%s, host=%s:%s",
                        self.proxy_enabled, self.proxy_type, self.proxy_host, self.proxy_port)
        except Exception as e:
            logger.error("[proxy_service] Erreur sauvegarde dans SQLite: %s", e)
            raise

        return self.get_proxy_settings()

    def get_active_proxy(self) -> Optional[str]:
        """Renvoie l'URL du proxy actif s'il est activé et configuré, sinon None."""
        if not self.proxy_enabled:
            return None
        return self.build_proxy_url(
            proxy_type=self.proxy_type,
            host=self.proxy_host,
            port=self.proxy_port,
            username=self.proxy_username,
            password=self.proxy_password,
            custom_url=self.custom_proxy_url
        )

    def get_random_proxy(self) -> Optional[str]:
        """Renvoie en priorité le proxy utilisateur actif s'il est configuré et activé."""
        active = self.get_active_proxy()
        if active:
            return active
        if not self.proxies:
            return None
        return random.choice(self.proxies)

    def get_proxy_dict(self) -> Optional[Dict[str, str]]:
        p = self.get_active_proxy() or self.get_random_proxy()
        if p:
            return {"http://": p, "https://": p, "all://": p}
        return None

    async def test_proxy_connection(self, proxy_url: Optional[str] = None) -> Dict[str, Any]:
        """Teste la connectivité d'une URL de proxy en direct."""
        # Le client ne connaît que l'URL masquée : retrouver l'URL réelle correspondante
        if proxy_url and self.custom_proxy_url and proxy_url.strip() == self.mask_url(self.custom_proxy_url):
            proxy_url = self.custom_proxy_url
        url_to_test = (proxy_url or self.get_active_proxy() or "").strip()
        if not url_to_test:
            return {
                "success": False,
                "error": "Aucune URL de proxy configurée ou fournie pour le test.",
                "latencyMs": 0,
            }

        start_time = time.perf_counter()
        test_endpoints = [
            "https://api.ipify.org?format=json",
            "https://httpbin.org/ip",
            "https://icanhazip.com",
        ]

        last_error = None
        for endpoint in test_endpoints:
            try:
                async with httpx.AsyncClient(
                    proxy=url_to_test,
                    timeout=httpx.Timeout(connect=5.0, read=5.0, write=5.0, pool=5.0),
                    verify=settings.SSL_VERIFY,
                    headers={"User-Agent": self.get_user_agent()}
                ) as client:
                    resp = await client.get(endpoint)
                    latency = int((time.perf_counter() - start_time) * 1000)
                    if resp.status_code == 200:
                        ip_found = ""
                        try:
                            data = resp.json()
                            ip_found = data.get("ip") or data.get("origin", "")
                        except Exception:
                            ip_found = resp.text.strip()
                        return {
                            "success": True,
                            "ip": ip_found or "Inconnue",
                            "latencyMs": latency,
                            "latency_ms": latency,
                            "proxyUrl": self.mask_url(url_to_test),
                            "proxy_url": self.mask_url(url_to_test),
                            "endpoint": endpoint,
                        }
            except Exception as e:
                last_error = e

        latency = int((time.perf_counter() - start_time) * 1000)
        return {
            "success": False,
            "error": f"{type(last_error).__name__}: {str(last_error).replace(url_to_test, self.mask_url(url_to_test))}",
            "latencyMs": latency,
            "latency_ms": latency,
            "proxyUrl": self.mask_url(url_to_test),
            "proxy_url": self.mask_url(url_to_test),
        }

proxy_service = ProxyService()
