"""Native scraper and stream resolver for French-Stream (fstream.net -> fs*.lol)."""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
import httpx

from animelab.config import settings
from animelab.models.anime import AnimeDetail, AnimeResult, Episode
from animelab.security import is_safe_url
from animelab.services.background import spawn
from animelab.services.extractors import extractor_registry
from animelab.services.scraping_service import scraping_service
from animelab.services.source_http import VerificationRequired, source_http

logger = logging.getLogger("animelab.french_stream")

_MIRROR_HOST_RE = re.compile(r"^fs\d+\.[a-z0-9-]+$", re.IGNORECASE)
_NEWSID_RE = re.compile(r"newsid=(\d+)")
_URL_ID_RE = re.compile(r"/(\d+)-")
_VIDZY_HOST_RE = re.compile(r"(vidzy\.[a-z0-9]+|luluvdo\.[a-z0-9]+)", re.IGNORECASE)

_STATIC_HOSTS = frozenset({
    "fstream.net",
    "www.fstream.net",
    "french-stream.net",
    "www.french-stream.net",
    "fs016.lol",
})
_IGNORED_PORTAL_PREFIXES = ("fstv.", "fsound.")
_HOSTER_PRIORITY = ("vidzy", "uqload", "voe", "filmoon", "filemoon", "dood", "netu", "premium")

_FILM_VERSION_MAP = {
    "vff": "VFF",
    "vfq": "VFQ",
    "vf": "VF",
    "french": "VF",
    "truefrench": "VFF",
    "vostfr": "VOSTFR",
    "vo": "VO",
}


def is_french_stream_host(host: Optional[str]) -> bool:
    """Return True if *host* belongs to French-Stream or one of its known mirrors."""
    clean = (host or "").strip().lower().rstrip(".")
    if not clean:
        return False
    if clean in _STATIC_HOSTS or _MIRROR_HOST_RE.fullmatch(clean):
        return True
    return (
        clean.endswith(".fstream.net")
        or clean.endswith(".french-stream.net")
        or clean in _configured_hosts()
    )


def _configured_hosts() -> set[str]:
    hosts: set[str] = set()
    for candidate in (
        settings.FRENCH_STREAM_URL,
        settings.FRENCH_STREAM_PORTAL_URL,
        *getattr(settings, "FRENCH_STREAM_BACKUP_URLS", ()),
    ):
        host = (urlparse(candidate).hostname or "").lower()
        if host:
            hosts.add(host)
    return hosts


def is_french_stream_url(url: Optional[str]) -> bool:
    """Return True if *url* points to French-Stream or a dynamic mirror."""
    if not url or not isinstance(url, str):
        return False
    try:
        parsed = urlparse(url.strip())
    except Exception:
        return False
    return parsed.scheme in ("http", "https") and is_french_stream_host(parsed.hostname)


def extract_mirror_from_portal_html(html: str) -> Optional[str]:
    """Extract the active streaming mirror origin from fstream.net portal HTML."""
    if not html:
        return None
    soup = BeautifulSoup(html, "html.parser")
    candidates: list[tuple[int, str]] = []
    for link in soup.select("a[href]"):
        href = str(link.get("href") or "").strip()
        if not href.startswith(("http://", "https://")):
            continue
        parsed = urlparse(href)
        host = (parsed.hostname or "").lower()
        if not host or any(host.startswith(p) for p in _IGNORED_PORTAL_PREFIXES):
            continue
        if parsed.path and parsed.path not in ("", "/"):
            continue
        if _MIRROR_HOST_RE.fullmatch(host):
            candidates.append((0, f"{parsed.scheme}://{parsed.netloc}".rstrip("/")))
        elif "french-stream" in host and host != "fstream.net":
            candidates.append((1, f"{parsed.scheme}://{parsed.netloc}".rstrip("/")))
    if candidates:
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1]

    for match in re.finditer(r"https?://(fs\d+\.[a-z0-9-]+)(?:[/?#\"'\s<>]|$)", html, re.IGNORECASE):
        origin = f"https://{match.group(1).lower()}"
        return origin
    return None


def _is_vidzy_url(url: str) -> bool:
    return bool(url and _VIDZY_HOST_RE.search(url))


def _vidzy_download_url(player_url: str) -> str:
    if not _is_vidzy_url(player_url):
        return ""
    dl = player_url.replace("/embed-", "/d/").replace(".html", "").replace("/e/", "/d/")
    if "/d/" in dl and not dl.endswith("_n"):
        dl += "_n"
    return dl


def _clean_player_url(raw: str) -> str:
    url = str(raw or "").strip()
    if url.startswith("//"):
        url = "https:" + url
    return url if url.startswith(("http://", "https://")) else ""


def _pick_best_player(players: Dict[str, Any]) -> tuple[str, Dict[str, str]]:
    clean: Dict[str, str] = {}
    for name, raw_url in players.items():
        url = _clean_player_url(str(raw_url or ""))
        if url:
            clean[str(name).lower()] = url
    if not clean:
        return ("", {})
    for preferred in _HOSTER_PRIORITY:
        for p_name, p_url in clean.items():
            if preferred in p_name or (preferred == "vidzy" and _is_vidzy_url(p_url)):
                return (p_url, clean)
    return (next(iter(clean.values())), clean)


def normalize_french_stream_url(url: str, base_url: Optional[str] = None) -> str:
    """Normalize known French-Stream portal/mirror URLs to the active streaming mirror."""
    if not url or not isinstance(url, str):
        return url
    stripped = url.strip()
    try:
        parsed = urlparse(stripped)
    except Exception:
        return url
    host = (parsed.hostname or "").lower()
    if parsed.scheme not in ("http", "https") or not is_french_stream_host(host):
        return url
    target = urlparse((base_url or settings.FRENCH_STREAM_URL).rstrip("/"))
    if not target.scheme or not target.netloc:
        return url
    # Do not rewrite fstream.net portal root unless targeting an actual item path.
    if host in ("fstream.net", "www.fstream.net") and (parsed.path in ("", "/") and not parsed.query):
        return stripped
    return urlunparse(parsed._replace(scheme=target.scheme, netloc=target.netloc))


class FrenchStreamService:
    """Scraper and stream resolver for French-Stream (`fstream.net` -> `fs*.lol`)."""

    def __init__(self) -> None:
        self.base_url: str = settings.FRENCH_STREAM_URL.rstrip("/")
        self.portal_url: str = settings.FRENCH_STREAM_PORTAL_URL.rstrip("/")
        self.lang: str = "fr"
        self._known_hosts: set[str] = set(_STATIC_HOSTS) | _configured_hosts()
        self.latest_cache: List[AnimeResult] = []
        self.last_cache_time: float = 0.0
        self.last_mirror_check: float = 0.0
        self.is_refreshing: bool = False
        self._refresh_task: Optional[asyncio.Task[Any]] = None
        self._load_persistent_cache()

    def get_allowed_domains(self) -> set[str]:
        """Return known French-Stream portal and mirror hostnames for SSRF allowlisting."""
        hosts = set(_STATIC_HOSTS) | _configured_hosts() | set(self._known_hosts)
        active_host = (urlparse(self.base_url).hostname or "").lower()
        if active_host:
            hosts.add(active_host)
        return {h for h in hosts if h}

    def _register_host(self, url: str) -> None:
        host = (urlparse(url).hostname or "").lower()
        if host:
            self._known_hosts.add(host)

    def _normalize_url(self, url: str) -> str:
        return normalize_french_stream_url(url, self.base_url)

    def _load_persistent_cache(self) -> None:
        try:
            cache_file = settings.CACHE_DIR / "latest_french_stream.json"
            if cache_file.exists():
                data = json.loads(cache_file.read_text(encoding="utf-8"))
                self.latest_cache = [AnimeResult(**item) for item in data.get("items", [])]
                self.last_cache_time = float(data.get("timestamp", 0))
                logger.info("Disk cache loaded (french-stream: %d items)", len(self.latest_cache))
        except Exception as exc:
            logger.warning("Error loading disk cache french-stream: %s", exc)

    def _save_persistent_cache(self) -> None:
        try:
            settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = settings.CACHE_DIR / "latest_french_stream.json"
            tmp_file = cache_file.with_suffix(".tmp")
            payload = {
                "timestamp": self.last_cache_time,
                "items": [item.model_dump() for item in self.latest_cache],
            }
            tmp_file.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            tmp_file.replace(cache_file)
        except Exception as exc:
            logger.warning("Error saving disk cache french-stream: %s", exc)

    def _headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "Referer": referer or (self.base_url + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7",
        }

    def _get_async_client(
        self, follow_redirects: bool = True, timeout: Optional[float] = None, referer: Optional[str] = None
    ) -> httpx.AsyncClient:
        return source_http.async_client(
            headers=self._headers(referer),
            timeout=timeout or settings.READ_TIMEOUT,
            follow_redirects=follow_redirects,
        )

    async def resolve_active_base_url(self, force: bool = False) -> str:
        """Resolve the current French-Stream mirror URL from the fstream.net portal."""
        now = time.monotonic()
        if not force and (now - self.last_mirror_check) < 600:
            return self.base_url
        self.last_mirror_check = now
        if not is_safe_url(self.portal_url):
            return self.base_url
        try:
            async with self._get_async_client(timeout=10.0, referer=self.portal_url + "/") as client:
                resp = await client.get(self.portal_url + "/")
                if resp.status_code == 200:
                    mirror = extract_mirror_from_portal_html(resp.text)
                    if mirror and is_safe_url(mirror):
                        self._register_host(mirror)
                        if mirror != self.base_url:
                            logger.info("Updated french-stream mirror: %s -> %s", self.base_url, mirror)
                            self.base_url = mirror
        except VerificationRequired:
            raise
        except Exception as exc:
            logger.debug("Unable to resolve french-stream mirror from %s: %s", self.portal_url, exc)
        return self.base_url

    async def _request(
        self,
        method: str,
        path_or_url: str,
        *,
        data: Optional[Dict[str, str]] = None,
        retry_safe: bool = False,
        referer: Optional[str] = None,
    ) -> httpx.Response:
        target = (
            path_or_url
            if path_or_url.startswith(("http://", "https://"))
            else urljoin(self.base_url + "/", path_or_url.lstrip("/"))
        )
        try:
            async with self._get_async_client(referer=referer) as client:
                resp = await client.request(method, target, data=data, retry_safe=retry_safe)
                if resp.status_code < 500:
                    return resp
                old_base = self.base_url
                new_base = await self.resolve_active_base_url(force=True)
                if new_base != old_base:
                    retried_target = self._normalize_url(target)
                    async with self._get_async_client(referer=new_base + "/") as retry_client:
                        return await retry_client.request(method, retried_target, data=data, retry_safe=retry_safe)
                return resp
        except VerificationRequired:
            raise
        except httpx.HTTPError:
            old_base = self.base_url
            new_base = await self.resolve_active_base_url(force=True)
            if new_base != old_base:
                retried_target = self._normalize_url(target)
                async with self._get_async_client(referer=new_base + "/") as client:
                    return await client.request(method, retried_target, data=data, retry_safe=retry_safe)
            raise

    # -------------------------------------------------------------------------
    # Latest releases / Popular / Search
    # -------------------------------------------------------------------------

    async def get_latest_releases(self) -> List[AnimeResult]:
        state = source_http.state(self.base_url)
        if state.blocked_url:
            self.last_cache_time = 0
            raise VerificationRequired(state.blocked_url)
        if not self.latest_cache or time.time() - self.last_cache_time > 15 * 60:
            task = self._refresh_task
            if task is None or task.done():
                self._refresh_task = task = spawn(self._safe_refresh_cache(), name="refresh-french-stream")
            await asyncio.shield(task)
        return list(self.latest_cache)

    async def _safe_refresh_cache(self) -> None:
        self.is_refreshing = True
        try:
            await self.refresh_cache()
        finally:
            self.is_refreshing = False

    async def refresh_cache(self) -> None:
        try:
            logger.info("Loading latest releases from %s", self.base_url)
            resp = await self._request("GET", "/", retry_safe=True)
            resp.raise_for_status()
            if resp.status_code == 200:
                results = self.parse_search_results(resp.text)
                if results:
                    self.latest_cache = results
                    self.last_cache_time = time.time()
                    self._save_persistent_cache()
                    logger.info("Cache updated (french-stream: %d items)", len(self.latest_cache))
        except VerificationRequired:
            raise
        except Exception as exc:
            logger.error("Error updating french-stream cache: %s", exc)
            raise

    async def get_popular_anime(self, page: int = 1) -> List[AnimeResult]:
        path = "/s-tv/sries-du-moment/" if page <= 1 else f"/index.php?cstart={page}&do=cat&category=sries-du-moment"
        resp = await self._request("GET", path, retry_safe=True)
        resp.raise_for_status()
        return self.parse_search_results(resp.text)

    async def search_anime(self, query: str) -> List[AnimeResult]:
        cleaned = (query or "").strip()
        if not cleaned:
            return []
        logger.info("Searching french-stream: '%s'", cleaned)
        results: List[AnimeResult] = []
        try:
            resp = await self._request(
                "POST",
                "/engine/ajax/search.php",
                data={"query": cleaned, "page": "1"},
                retry_safe=True,
            )
            if resp.status_code == 200:
                results = self.parse_search_results(resp.text)
            if not results:
                results = await self.search_via_listing(cleaned)
        except VerificationRequired:
            raise
        except Exception as exc:
            logger.error("Error searching french-stream: %s", exc)
            results = await self.search_via_listing(cleaned)
        return results

    async def search_via_listing(self, query: str) -> List[AnimeResult]:
        results: List[AnimeResult] = []
        lower_q = query.lower()
        seen_urls: set[str] = set()
        for path in ("/s-tv/", "/films/"):
            try:
                resp = await self._request("GET", path, retry_safe=True)
                if resp.status_code == 200:
                    for item in self.parse_search_results(resp.text):
                        if lower_q in item.title.lower() and item.url not in seen_urls:
                            seen_urls.add(item.url)
                            results.append(item)
            except VerificationRequired:
                raise
            except Exception as exc:
                logger.debug("Fallback listing %s failed: %s", path, exc)
        return results[:30]

    def parse_search_results(self, html: str) -> List[AnimeResult]:
        soup = BeautifulSoup(html, "html.parser")
        results: List[AnimeResult] = []
        articles = soup.select(".short, .mov, .shortstory, .short-story, article, .search-item")
        seen_urls: set[str] = set()
        for article in articles:
            try:
                res = self.parse_anime_card(article)
                if res and res.title and res.url and res.url not in seen_urls:
                    seen_urls.add(res.url)
                    results.append(res)
            except Exception as exc:
                logger.debug("Error parsing french-stream card: %s", exc)
        return results

    def parse_anime_card(self, card: Any) -> Optional[AnimeResult]:
        url, title, image_url, version, episode_info, anime_id = "", "", "", "", "", ""
        anime_type = "Film"
        classes = card.get("class", []) or []

        if "search-item" in classes or card.get("onclick"):
            onclick = str(card.get("onclick") or "")
            m = re.search(r"location\.href\s*=\s*['\"]([^'\"]+)['\"]", onclick)
            if not m:
                return None
            url = urljoin(self.base_url + "/", m.group(1).strip())
            title_el = card.select_one(".search-title")
            title = title_el.get_text(" ", strip=True) if title_el else ""
            img = card.select_one(".search-poster img")
            if img:
                image_url = str(img.get("src") or img.get("data-src") or "").strip()
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url + "/", image_url)
            if "saison" in title.lower() or "/s-tv/" in url:
                anime_type = "Série"
        else:
            link = card.select_one("a.short-poster[href]") or card.select_one("a[href*='newsid=']")
            if not link:
                link = card.select_one("a[href$='.html']:not([href*='xfsearch']):not([href*='do=search'])")
            if not link:
                return None
            href = str(link.get("href") or "").strip()
            if not href or href == "#" or "xfsearch" in href or "do=search" in href:
                return None
            url = urljoin(self.base_url + "/", href)

            title_el = card.select_one(".short-title, h2, h3, h4, .movie-title, .title")
            if title_el:
                title = title_el.get_text(" ", strip=True)
            else:
                title = str(link.get("title") or link.get("alt") or link.get_text(" ", strip=True)).strip()

            img = card.select_one(".short-poster img[src], img[src], img[data-src]")
            if img:
                image_url = str(img.get("src") or img.get("data-src") or "").strip()
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url + "/", image_url)

            ver_el = card.select_one(".film-version a, .film-version, a[href*='version-serie'], a[href*='version-film'], .version")
            if ver_el:
                version = ver_el.get_text(" ", strip=True)

            ep_el = card.select_one(".mli-eps")
            if ep_el:
                episode_info = " ".join(ep_el.get_text(" ", strip=True).split())
                anime_type = "Série"
            elif "/s-tv/" in url or "saison" in title.lower() or card.select_one("a[href*='version-serie']"):
                anime_type = "Série"

            if not episode_info:
                qual_el = card.select_one(".film-quality a, .film-quality, .quality")
                if qual_el:
                    episode_info = qual_el.get_text(" ", strip=True)

        if not title or len(title) < 2 or not url:
            return None

        url = self._normalize_url(url)
        m_newsid = _NEWSID_RE.search(url)
        if m_newsid:
            anime_id = m_newsid.group(1)
        else:
            m_id = _URL_ID_RE.search(url)
            anime_id = m_id.group(1) if m_id else str(abs(hash(url)))[:8]

        return AnimeResult(
            id=anime_id,
            title=title,
            imageUrl=image_url,
            url=url,
            version=version,
            type=anime_type,
            episodeInfo=episode_info,
            source="french-stream",
        )

    # -------------------------------------------------------------------------
    # Anime / Series / Film Detail
    # -------------------------------------------------------------------------

    def _extract_news_id(self, url: str, soup: BeautifulSoup) -> str:
        for selector in ("#serie-data[data-newsid]", "#film-data[data-newsid]", "#serie-config[data-news-id]"):
            el = soup.select_one(selector)
            if el:
                nid = str(el.get("data-newsid") or el.get("data-news-id") or "").strip()
                if nid.isdigit():
                    return nid
        return scraping_service.extract_news_id(url, soup)

    def _extract_json_ld(self, soup: BeautifulSoup) -> Dict[str, Any]:
        for script in soup.select("script[type='application/ld+json']"):
            raw = (script.string or "").strip()
            if not raw:
                continue
            try:
                parsed = json.loads(raw)
                if isinstance(parsed, list) and parsed:
                    parsed = parsed[0]
                if isinstance(parsed, dict) and parsed.get("@type") in ("Movie", "TVSeries", "CreativeWork", None):
                    return parsed
            except Exception:
                continue
        return {}

    def _content_scope(self, soup: BeautifulSoup) -> BeautifulSoup:
        """Clone/select main article container without nav/header so menu links never pollute genres."""
        container = soup.select_one("#dle-content, .full-story, .fstory, main")
        target = BeautifulSoup(str(container or soup), "html.parser")
        for noise in target.select("nav, header, footer, .menu, .navbar, .sidebar"):
            noise.decompose()
        return target

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        target_url = self._normalize_url(anime_url)
        if not is_safe_url(target_url):
            logger.warning("[french-stream] SSRF blocked for URL: %s", anime_url)
            return None
        logger.info("Loading french-stream details: %s", target_url)
        try:
            resp = await self._request("GET", target_url, retry_safe=True)
            if resp.status_code != 200:
                return None
            final_url = self._normalize_url(str(resp.url)) if resp.url else target_url
            soup = BeautifulSoup(resp.text, "html.parser")
            content_soup = self._content_scope(soup)
            json_ld = self._extract_json_ld(soup)

            serie_node = soup.select_one("#serie-data")
            film_node = soup.select_one("#film-data")

            title = ""
            if film_node and film_node.get("data-title"):
                title = str(film_node["data-title"]).strip()
            elif serie_node and serie_node.get("data-title"):
                title = str(serie_node["data-title"]).strip()
            if not title:
                title_el = content_soup.select_one("h1, #s-title, .full-title, .movie-title")
                if title_el:
                    title = title_el.get_text(" ", strip=True)
                elif json_ld.get("name"):
                    title = str(json_ld["name"]).strip()
                elif soup.title and soup.title.string:
                    title = soup.title.string.split("|")[0].split("- French")[0].strip()

            image_url = ""
            for node in (film_node, serie_node):
                if node and node.get("data-affiche"):
                    image_url = str(node["data-affiche"]).strip()
                    break
            if not image_url:
                poster_img = content_soup.select_one(
                    ".dvd-thumbnail, .fposter img, #dvdPosterImage, .movie-poster img, img[src*='image.tmdb.org'], img[src*='uploads/posts']"
                )
                if poster_img:
                    image_url = str(poster_img.get("src") or poster_img.get("data-src") or "").strip()
            if not image_url and isinstance(json_ld.get("image"), str):
                image_url = json_ld["image"].strip()
            if image_url and not image_url.startswith("http"):
                image_url = urljoin(self.base_url + "/", image_url)

            banner_url = None
            if film_node and film_node.get("data-affiche2"):
                banner_url = str(film_node["data-affiche2"]).strip() or None

            synopsis = ""
            syn_el = content_soup.select_one(".fdesc, .full-text, .story-text, .movie-description, #s-desc")
            if syn_el:
                synopsis = syn_el.get_text(" ", strip=True)
            elif json_ld.get("description"):
                synopsis = str(json_ld["description"]).strip()
            else:
                meta_desc = soup.select_one("meta[name='description']")
                if meta_desc and meta_desc.get("content"):
                    synopsis = str(meta_desc["content"]).strip()

            genres = list(dict.fromkeys(
                g.get_text(" ", strip=True)
                for g in content_soup.select(
                    "a[href*='xfname=genre'], a[href*='/films/'][href$='/'], a[href*='-serie-'], a[href*='-series-']"
                )
                if g.get_text(strip=True) and len(g.get_text(strip=True)) < 40
            ))
            directors = list(dict.fromkeys(
                d.get_text(" ", strip=True)
                for d in content_soup.select("a[href*='director']")
                if d.get_text(strip=True)
            ))
            if not directors and isinstance(json_ld.get("director"), list):
                directors = [str(d["name"]).strip() for d in json_ld["director"] if isinstance(d, dict) and d.get("name")]

            actors = list(dict.fromkeys(
                a.get_text(" ", strip=True)
                for a in content_soup.select("a[href*='actors']")
                if a.get_text(strip=True)
            ))
            if not actors and isinstance(json_ld.get("actor"), list):
                actors = [str(a["name"]).strip() for a in json_ld["actor"] if isinstance(a, dict) and a.get("name")]

            version_el = content_soup.select_one("a[href*='version-serie'], a[href*='version-film']")
            page_version = version_el.get_text(" ", strip=True) if version_el else ""

            news_id = self._extract_news_id(final_url, soup)
            episodes: List[Episode] = []
            is_series = bool(serie_node or soup.select_one("#vf-episodes, #vostfr-episodes"))

            if news_id and is_series:
                ep_resp = await self._request("GET", f"/ep-data.php?id={news_id}", referer=final_url, retry_safe=True)
                if ep_resp.status_code == 200:
                    episodes = self.parse_series_episodes_json(ep_resp.text)

            if not episodes and news_id and film_node is not None:
                film_resp = await self._request(
                    "GET", f"/engine/ajax/film_api.php?id={news_id}", referer=final_url, retry_safe=True
                )
                if film_resp.status_code == 200:
                    episodes, meta_override = self.parse_film_api_json(film_resp.text, page_version=page_version)
                    if not image_url and meta_override.get("affiche"):
                        image_url = meta_override["affiche"]
                    if not banner_url and meta_override.get("affiche2"):
                        banner_url = meta_override["affiche2"]

            # Cross-fallback if page layout lacked #serie-data / #film-data marker
            if not episodes and news_id and not is_series and film_node is None:
                ep_resp = await self._request("GET", f"/ep-data.php?id={news_id}", referer=final_url, retry_safe=True)
                if ep_resp.status_code == 200:
                    episodes = self.parse_series_episodes_json(ep_resp.text)
                if not episodes:
                    film_resp = await self._request(
                        "GET", f"/engine/ajax/film_api.php?id={news_id}", referer=final_url, retry_safe=True
                    )
                    if film_resp.status_code == 200:
                        episodes, _ = self.parse_film_api_json(film_resp.text, page_version=page_version)

            if not episodes:
                episodes = self.parse_episodes_from_dom(soup, page_version=page_version)

            episodes.sort(key=lambda ep: (ep.number, 0 if "VOST" in ep.version.upper() else 1))

            versions_found = [ep.version.upper() for ep in episodes if ep.version]
            has_vf = any("VF" in v for v in versions_found)
            has_vostfr = any("VOSTFR" in v for v in versions_found)
            if has_vf and has_vostfr:
                version = "VF + VOSTFR"
            elif has_vf:
                version = "VF"
            elif has_vostfr:
                version = "VOSTFR"
            elif versions_found:
                version = versions_found[0]
            else:
                version = page_version

            return AnimeDetail(
                title=title,
                synopsis=synopsis,
                imageUrl=image_url,
                bannerUrl=banner_url,
                version=version,
                url=final_url,
                genres=genres,
                directors=directors,
                actors=actors,
                episodes=episodes,
                source="french-stream",
            )
        except VerificationRequired:
            raise
        except Exception as exc:
            logger.error("Error loading french-stream detail: %s", exc)
            return None

    def parse_series_episodes_json(self, json_str: str) -> List[Episode]:
        """Parse French-Stream `/ep-data.php?id=...` payload into Episode objects."""
        episodes: List[Episode] = []
        try:
            data = json.loads(json_str)
        except Exception as exc:
            logger.error("Error parsing french-stream ep-data JSON: %s", exc)
            return episodes
        if not isinstance(data, dict):
            return episodes

        info_node = data.get("info") if isinstance(data.get("info"), dict) else {}
        for v_key in ("vf", "vostfr", "vo", "vff", "vfq"):
            v_node = data.get(v_key)
            if not isinstance(v_node, dict):
                continue
            display_ver = v_key.upper()
            for ep_str, players in v_node.items():
                if not isinstance(players, dict):
                    continue
                try:
                    ep_num = int(ep_str)
                except (TypeError, ValueError):
                    continue
                player_url, clean_players = _pick_best_player(players)
                if not player_url:
                    continue
                ep_meta = info_node.get(ep_str) if isinstance(info_node.get(ep_str), dict) else {}
                ep_title = str(ep_meta.get("title") or "").strip() or f"Épisode {ep_num}"
                ep_synopsis = str(ep_meta.get("synopsis") or "").strip() or None
                ep_thumb = str(ep_meta.get("poster") or "").strip() or None
                dl_url = _vidzy_download_url(player_url) or player_url
                episodes.append(
                    Episode(
                        number=ep_num,
                        title=ep_title,
                        synopsis=ep_synopsis,
                        thumbnailUrl=ep_thumb,
                        playerUrl=player_url,
                        downloadPageUrl=dl_url,
                        version=display_ver,
                        nativeMetadata={"players": clean_players},
                    )
                )
        episodes.sort(key=lambda x: (x.number, x.version))
        return episodes

    def parse_film_api_json(
        self, json_str: str, *, page_version: str = ""
    ) -> tuple[List[Episode], Dict[str, str]]:
        """Parse French-Stream `/engine/ajax/film_api.php?id=...` payload."""
        meta_out: Dict[str, str] = {}
        try:
            data = json.loads(json_str)
        except Exception as exc:
            logger.error("Error parsing french-stream film_api JSON: %s", exc)
            return ([], meta_out)
        if not isinstance(data, dict):
            return ([], meta_out)

        meta = data.get("meta") if isinstance(data.get("meta"), dict) else {}
        for key in ("affiche", "affiche2"):
            if isinstance(meta.get(key), str) and meta[key].strip():
                meta_out[key] = meta[key].strip()

        raw_players = data.get("players")
        if not isinstance(raw_players, dict):
            return ([], meta_out)

        pv = page_version.upper()
        default_ver = "VOSTFR" if ("VOSTFR" in pv and "VF" not in pv) else "VF"
        by_version: Dict[str, Dict[str, str]] = {}
        for hoster, variants in raw_players.items():
            if not isinstance(variants, dict):
                continue
            for slot, raw_url in variants.items():
                url = _clean_player_url(str(raw_url or ""))
                if not url or "multiup.us" in url:
                    continue
                slot_key = str(slot).strip().lower()
                if slot_key == "default":
                    ver_label = default_ver
                else:
                    ver_label = _FILM_VERSION_MAP.get(slot_key, slot_key.upper() or default_ver)
                by_version.setdefault(ver_label, {})[str(hoster).lower()] = url

        episodes: List[Episode] = []
        seen_primary_urls: set[str] = set()
        order_pref = ("VF", "VFF", "VFQ", "VOSTFR", "VO")
        sorted_versions = sorted(
            by_version,
            key=lambda v: (order_pref.index(v) if v in order_pref else len(order_pref), v),
        )
        for ver_label in sorted_versions:
            hoster_urls = by_version[ver_label]
            primary_url, clean_players = _pick_best_player(hoster_urls)
            if not primary_url or primary_url in seen_primary_urls:
                continue
            seen_primary_urls.add(primary_url)
            episodes.append(
                Episode(
                    number=1,
                    title="Film complet",
                    synopsis=None,
                    thumbnailUrl=meta_out.get("affiche"),
                    playerUrl=primary_url,
                    downloadPageUrl=_vidzy_download_url(primary_url) or primary_url,
                    version=ver_label,
                    nativeMetadata={"players": clean_players, "isFilm": True},
                )
            )

        if len(episodes) > 1:
            for ep in episodes:
                ep.title = f"Film complet ({ep.version})"
        return (episodes, meta_out)

    def parse_episodes_from_dom(
        self, soup: BeautifulSoup, *, page_version: str = ""
    ) -> List[Episode]:
        """Fallback episode parser for pages embedding `.option[data-url]` or standard links."""
        options = soup.select("[data-url]")
        episodes: List[Episode] = []
        seen_urls: set[str] = set()
        fallback_ver = "VOSTFR" if "VOSTFR" in page_version.upper() else "VF"
        for idx, opt in enumerate(options, 1):
            raw_url = _clean_player_url(str(opt.get("data-url") or ""))
            if not raw_url or raw_url in seen_urls:
                continue
            seen_urls.add(raw_url)
            text = opt.get_text(" ", strip=True)
            ver = "VOSTFR" if "vostfr" in text.lower() else fallback_ver
            episodes.append(
                Episode(
                    number=idx,
                    title="Film complet" if "télécharger" in text.lower() else (text or f"Épisode {idx}"),
                    playerUrl=raw_url,
                    downloadPageUrl=_vidzy_download_url(raw_url) or raw_url,
                    version=ver,
                )
            )
        if episodes:
            return episodes
        return scraping_service.parse_episodes_from_dom(soup)

    # -------------------------------------------------------------------------
    # Video resolution
    # -------------------------------------------------------------------------

    def extract_download_info(self, url: str) -> Dict[str, Any]:
        """Synchronously resolve a Vidzy / Luluvdo URL via the shared Vidzy extractor."""
        return scraping_service.extract_download_info(url)

    async def resolve_episode_stream(
        self, url: str, preferred_quality: Optional[str] = None
    ) -> Dict[str, Any]:
        """Resolve a French-Stream embed URL (Vidzy or generic hoster like Uqload/VOE)."""
        clean_url = _clean_player_url(url)
        if not clean_url:
            return {}
        if _is_vidzy_url(clean_url):
            info = await asyncio.to_thread(scraping_service.extract_download_info, clean_url)
            return {
                **info,
                "serverType": "vidzy",
                "selectedQuality": preferred_quality or "HD",
            }
        extracted = await extractor_registry.extract(
            clean_url,
            referer=f"{self.base_url}/",
            preferred_quality=preferred_quality,
        )
        if extracted and extracted.video_url:
            return {
                "videoUrl": extracted.video_url,
                "serverType": extracted.server_name or "imported",
                "selectedQuality": extracted.quality or preferred_quality or "HD",
                "videoQualities": json.dumps(extracted.qualities) if extracted.qualities else "{}",
                "subtitles": json.dumps(extracted.subtitles) if extracted.subtitles else "[]",
                "subtitleUrl": extracted.subtitles[0]["url"] if extracted.subtitles else "",
                "headers": extracted.headers or {},
                "size": extracted.size,
            }
        return {}


french_stream_service = FrenchStreamService()
