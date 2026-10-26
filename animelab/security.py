import ipaddress
import logging
import socket
from pathlib import Path
from typing import Iterable, Optional, Union
from urllib.parse import urlparse

from animelab.config import settings

logger = logging.getLogger("animelab.security")

# Domaines autorisés de référence pour le scraping et les médias
ALLOWED_SCRAPING_DOMAINS = {
    "french-manga.net",
    "w16.french-manga.net",
    "voir-anime.to",
    "voiranime.to",
    "voiranime.io",
    "voiranime.homes",
    "api.themoviedb.org",
    "image.tmdb.org",
    "voembed.net",
    "vidmoly.to",
    "streamtape.com",
    "tapecontent.net",
    "voe.sx",
    "johnfullwonder.com",
    "my.mail.ru",
    "cloud.mail.ru",
    "gn1r5n.org",
    # AnimePahe et miroirs
    "animepahe.com",
    "animepahe.org",
    "animepahe.pw",
    "animepahe.ru",
    "animepahe.si",
    "animepahe.su",
    "i.animepahe.ru",
    "i.animepahe.com",
    # Hébergeurs et lecteurs Kwik / Pahe
    "kwik.cx",
    "kwik.si",
    "kwik.link",
    "kwik.top",
    "pahe.win",
    "owocdn.top",
    "kwikcdn.com",
    # Extensions et hébergeurs populaires
    "anime-sama.to",
    "anime-sama.org",
    "anime-sama.pw",
    "jetanimes.com",
    "animesz.xyz",
    "animevostfr.tv",
}

def get_all_allowed_domains() -> set:
    """Retourne la liste complète des domaines autorisés incluant les extensions dynamiques actives."""
    domains = set(ALLOWED_SCRAPING_DOMAINS)
    try:
        from animelab.services.extension_service import extension_service
        domains.update(extension_service.get_allowed_domains())
    except Exception:
        pass
    return domains

import time

_DNS_CACHE: dict[str, tuple[float, list[str]]] = {}
_DNS_CACHE_TTL = 60.0

def is_ip_blocked(ip_obj: Union[ipaddress.IPv4Address, ipaddress.IPv6Address]) -> bool:
    """
    Vérifie si une adresse IP est privée, de boucle locale, réservée ou de lien local.
    Bloque les tentatives de SSRF vers le réseau interne ou les métadonnées cloud.
    """
    if (
        ip_obj.is_loopback
        or ip_obj.is_private
        or ip_obj.is_reserved
        or ip_obj.is_link_local
        or ip_obj.is_multicast
        or ip_obj == ipaddress.IPv4Address("0.0.0.0")
        or str(ip_obj) == "::"
        or (hasattr(ip_obj, "is_unspecified") and ip_obj.is_unspecified)
    ):
        return True
    return False

def _resolve_dns(hostname: str) -> list[str]:
    """Résout le nom d'hôte avec cache TTL pour minimiser la latence réseau."""
    now = time.time()
    cached = _DNS_CACHE.get(hostname)
    if cached and (now - cached[0]) < _DNS_CACHE_TTL:
        return cached[1]

    try:
        addr_info = socket.getaddrinfo(hostname, None)
        ips = [item[4][0] for item in addr_info if item and len(item) > 4 and item[4]]
        # Éviter la croissance infinie du cache
        if len(_DNS_CACHE) > 500:
            _DNS_CACHE.clear()
        _DNS_CACHE[hostname] = (now, ips)
        return ips
    except Exception as e:
        logger.debug("DNS resolution failed for '%s': %s", hostname, e)
        return []

def is_safe_url(
    url: str,
    allowed_domains: Optional[Iterable[str]] = None,
    allow_private: bool = False
) -> bool:
    """
    Valide une URL contre les attaques SSRF :
    - Protocole http ou https uniquement
    - Hôte non vide
    - Résolution DNS filtrée (aucune IP privée/locale sauf si explicitement autorisée)
    - Filtrage optionnel par liste de domaines
    """
    if not url or not isinstance(url, str):
        return False

    url = url.strip()
    try:
        parsed = urlparse(url)
    except Exception:
        return False

    if parsed.scheme not in ("http", "https"):
        return False

    hostname = parsed.hostname
    if not hostname:
        return False

    hostname = hostname.lower().strip()

    # Vérification des domaines autorisés si spécifiés
    if allowed_domains is not None:
        domain_match = False
        for d in allowed_domains:
            d = d.lower().strip()
            if hostname == d or hostname.endswith("." + d):
                domain_match = True
                break
        if not domain_match:
            logger.warning("SSRF blocked: Hostname '%s' not in allowed domains", hostname)
            return False

    if not allow_private:
        # Vérification si le hostname est directement une IP
        try:
            ip = ipaddress.ip_address(hostname)
            if is_ip_blocked(ip):
                logger.warning("SSRF blocked: IP '%s' is private/loopback", ip)
                return False
        except ValueError:
            # Nom de domaine : résolution DNS pour inspecter les adresses réelles
            resolved_ips = _resolve_dns(hostname)
            if not resolved_ips:
                logger.debug("DNS resolution empty for '%s'", hostname)
                return False
            for ip_str in resolved_ips:
                try:
                    ip = ipaddress.ip_address(ip_str)
                    if is_ip_blocked(ip):
                        logger.warning("SSRF blocked: Resolved IP '%s' for '%s' is private/loopback", ip, hostname)
                        return False
                except ValueError:
                    return False

    return True

async def is_safe_url_async(
    url: str,
    allowed_domains: Optional[Iterable[str]] = None,
    allow_private: bool = False
) -> bool:
    """Version non bloquante de :func:`is_safe_url` (résolution DNS dans un thread)."""
    import asyncio
    return await asyncio.to_thread(is_safe_url, url, allowed_domains, allow_private)

def is_safe_path(
    target_path: Union[str, Path],
    allowed_base_dirs: Optional[Iterable[Union[str, Path]]] = None
) -> bool:
    """
    Vérifie qu'un chemin de fichier résolu reste strictement confiné dans un répertoire autorisé.
    Protège contre les attaques de type Path Traversal.
    """
    if not target_path:
        return False

    try:
        resolved_target = Path(target_path).resolve()
    except Exception:
        return False

    if allowed_base_dirs is None:
        import tempfile
        allowed_base_dirs = [
            Path(settings.DOWNLOAD_DIR).resolve(),
            Path(tempfile.gettempdir()).resolve()
        ]
        # Shared engines receive their own TMPDIR. Never fall back to the
        # machine-wide temporary directory when serving another user's media.
        import os
        if os.getenv("ANIMELAB_SHARED_WORKER") == "1":
            allowed_base_dirs = [Path(settings.DOWNLOAD_DIR).resolve()]
    else:
        allowed_base_dirs = [Path(d).resolve() for d in allowed_base_dirs]

    for base in allowed_base_dirs:
        try:
            if resolved_target.is_relative_to(base):
                return True
        except (ValueError, AttributeError):
            # Compatibilité et fallback
            try:
                resolved_target.relative_to(base)
                return True
            except ValueError:
                pass

    logger.warning("Path Traversal blocked: Path '%s' is outside allowed directories", resolved_target)
    return False

def anonymize_path(path_str: str) -> str:
    """
    Anonymise un chemin absolu système en masquant le répertoire personnel de l'utilisateur.
    """
    if not path_str:
        return ""
    try:
        home_str = str(Path.home())
        if path_str.startswith(home_str):
            return "~" + path_str[len(home_str):]
    except Exception:
        pass
    return path_str
