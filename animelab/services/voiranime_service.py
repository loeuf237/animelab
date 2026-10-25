from urllib.parse import urlparse
from animelab.services.source_http import source_http, VerificationRequired
import asyncio
from animelab.services.background import spawn
import base64
import json
import logging
import re
import time
import urllib.parse
from typing import List, Optional, Dict, Tuple, Any
from urllib.parse import urljoin

import html
import httpx
from bs4 import BeautifulSoup

from animelab.config import settings
from animelab.models.anime import AnimeResult, AnimeDetail, Episode
from animelab.models.download_task import format_bytes
from animelab.services.proxy_service import proxy_service
from animelab.security import is_safe_url

logger = logging.getLogger("animelab.voiranime")

class VoirAnimeScrapingService:
    def __init__(self):
        self.base_url = settings.VOIR_ANIME_URL
        self.default_server = settings.VOIRANIME_DEFAULT_SERVER
        self.latest_cache: List[AnimeResult] = []
        self.last_cache_time: float = 0.0
        self.is_refreshing: bool = False
        self._load_persistent_cache()

    def _load_persistent_cache(self):
        try:
            cache_file = settings.CACHE_DIR / "latest_voir_anime.json"
            if cache_file.exists():
                with open(cache_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    self.latest_cache = [AnimeResult(**item) for item in data.get("items", [])]
                    self.last_cache_time = float(data.get("timestamp", 0))
                    logger.info("[voir-anime] Disk cache loaded (%d animes)", len(self.latest_cache))
        except Exception as e:
            logger.warning("[voir-anime] Error loading disk cache: %s", e)

    def _save_persistent_cache(self):
        try:
            settings.CACHE_DIR.mkdir(parents=True, exist_ok=True)
            cache_file = settings.CACHE_DIR / "latest_voir_anime.json"
            tmp_file = cache_file.with_suffix(".tmp")
            data = {
                "timestamp": self.last_cache_time,
                "items": [item.model_dump() for item in self.latest_cache]
            }
            with open(tmp_file, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False)
            tmp_file.replace(cache_file)
        except Exception as e:
            logger.warning("[voir-anime] Error saving disk cache: %s", e)

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer or (self.base_url + "/"),
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def _get_client(self, follow_redirects: bool = True, referer: Optional[str] = None, timeout: Optional[float] = None) -> httpx.Client:
        return source_http.client(
            headers={"Referer": referer or (self.base_url + "/"), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"},
            timeout=timeout or settings.READ_TIMEOUT, follow_redirects=follow_redirects,
        )

    def _get_async_client(self, follow_redirects: bool = True, referer: Optional[str] = None, timeout: Optional[float] = None) -> httpx.AsyncClient:
        return source_http.async_client(
            headers={"Referer": referer or (self.base_url + "/"), "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                     "Accept-Language": "fr-FR,fr;q=0.9,en;q=0.7"},
            timeout=timeout or settings.READ_TIMEOUT, follow_redirects=follow_redirects,
        )

    async def get_latest_releases(self) -> List[AnimeResult]:
        state = source_http.state(self.base_url)
        if state.blocked_url:
            blocked = state.blocked_url
            if not source_http.rotate_proxy(urlparse(blocked).hostname or "", automatic=True):
                raise VerificationRequired(blocked)
            self.last_cache_time = 0
        if not self.latest_cache or time.time() - self.last_cache_time > 15 * 60:
            task = getattr(self, "_refresh_task", None)
            if task is None or task.done():
                self._refresh_task = task = spawn(self._safe_refresh_cache(), name="refresh-cache")
            # Keep the refresh alive if a caller times out, and share it with other callers.
            await asyncio.shield(task)
        return list(self.latest_cache)

    async def _safe_refresh_cache(self):
        self.is_refreshing = True
        try:
            await self.refresh_cache()
        finally:
            self.is_refreshing = False

    async def refresh_cache(self):
        try:
            logger.info("[voir-anime] Loading latest releases from %s", self.base_url)
            async with self._get_async_client() as client:
                resp = await client.get(self.base_url)
                resp.raise_for_status()
                if resp.status_code == 200:
                    results = self.parse_cards(resp.text)
                    if results:
                        self.latest_cache = results
                        self.last_cache_time = time.time()
                        self._save_persistent_cache()
                        logger.info("[voir-anime] Cache updated (%d animes)", len(self.latest_cache))
        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[voir-anime] Cache update error: %s", e)
            raise

    def parse_asp_html(self, html: str, default_version: str = "VOSTFR") -> List[AnimeResult]:
        if not html:
            return []
        if "___ASPSTART_HTML___" in html:
            html = html.split("___ASPSTART_HTML___")[1].split("___ASPEND_HTML___")[0]
        soup = BeautifulSoup(html, "html.parser")
        results: List[AnimeResult] = []

        for rank, item in enumerate(soup.select(".item")):
            try:
                title_el = item.select_one("h3 a.asp_res_url, h3, a.asp_res_url")
                if not title_el:
                    continue
                # Supprimer les éventuels spans d'overlap générés par ASP
                for span in title_el.select(".overlap"):
                    span.decompose()
                title = title_el.get_text().strip()
                if not title:
                    continue

                link = item.select_one("a.asp_res_url, a.asp_res_image_url, a")
                url = link.get("href", "").strip() if link else ""
                if not url:
                    continue
                if not url.startswith("http"):
                    url = urljoin(self.base_url, url)

                img = item.select_one(".asp_image img, img")
                image_url = (img.get("src") or img.get("data-src") or "").strip() if img else ""
                if image_url and not image_url.startswith("http"):
                    image_url = urljoin(self.base_url, image_url)

                version = default_version
                if "(VF)" in title.upper() or "-vf/" in url.lower() or "/vf/" in url.lower():
                    version = "VF"
                elif "(VOSTFR)" in title.upper() or "-vostfr/" in url.lower():
                    version = "VOSTFR"

                m_id = re.search(r"/anime/([^/]+)/?", url)
                anime_id = m_id.group(1) if m_id else str(hash(url))[:8]

                anime_res = AnimeResult(
                    id=anime_id,
                    title=title,
                    imageUrl=image_url,
                    url=url,
                    version=version,
                    type="Anime",
                    episodeInfo="",
                    source="voir-anime",
                )
                setattr(anime_res, "_asp_rank", rank)
                results.append(anime_res)
            except Exception as e:
                logger.debug("Erreur parsing item ASP: %s", e)
        return results

    async def search_via_asp(self, query: str) -> List[AnimeResult]:
        user_wants_vf = bool(re.search(r"\bvf\b", query, re.IGNORECASE))
        user_wants_vostfr = bool(re.search(r"\bvostfr\b", query, re.IGNORECASE))
        q_clean = re.sub(r"\b(vf|vostfr)\b", "", query, flags=re.IGNORECASE).strip() or query
        q_lower = q_clean.lower()

        options_str = urllib.parse.urlencode([
            ("current_page_id", "15"),
            ("qtranslate_lang", "0"),
            ("filters_changed", "0"),
            ("filters_initial", "1"),
            ("asp_gen[]", "title"),
            ("asp_gen[]", "content"),
            ("asp_gen[]", "excerpt"),
            ("aspf[vf__1]", "vf"),
        ])

        asp_endpoint = f"{self.base_url}/wp-admin/admin-ajax.php"
        extra_headers = {
            "X-Requested-With": "XMLHttpRequest",
            "Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
        }

        async with self._get_async_client() as client:
            client.headers.update(extra_headers)
            async def fetch_asp(asid: int) -> str:
                try:
                    data = {
                        "action": "ajaxsearchpro_search",
                        "aspp": q_clean,
                        "asid": str(asid),
                        "asp_inst_id": f"{asid}_1",
                        "options": options_str,
                    }
                    resp = await client.post(asp_endpoint, data=data, retry_safe=True)
                    if resp.status_code == 200:
                        return resp.text
                except VerificationRequired:
                    raise
                except Exception as e:
                    logger.warning("[voir-anime] Erreur fetch ASP asid=%d: %s", asid, e)
                return ""

            # asid=2 pour instance VF, asid=3 pour instance VOSTFR
            resp_vf, resp_vostfr = await asyncio.gather(fetch_asp(2), fetch_asp(3))

        vf_items = self.parse_asp_html(resp_vf, default_version="VF")
        vostfr_items = self.parse_asp_html(resp_vostfr, default_version="VOSTFR")

        # Fusionner selon l'intention de l'utilisateur
        combined: List[AnimeResult] = []
        seen_urls = set()

        if user_wants_vf:
            order = vf_items + vostfr_items
        elif user_wants_vostfr:
            order = vostfr_items + vf_items
        else:
            # Si aucune version spécifiée : entrelacer VF et VOSTFR en respectant le rang natif du site
            order = []
            max_len = max(len(vf_items), len(vostfr_items))
            for i in range(max_len):
                if i < len(vf_items):
                    order.append(vf_items[i])
                if i < len(vostfr_items):
                    order.append(vostfr_items[i])

        for it in order:
            if it.url not in seen_urls:
                seen_urls.add(it.url)
                combined.append(it)

        # Tri intelligent par pertinence du titre tout en préservant le classement original d'Ajax Search Pro
        def sort_key(item: AnimeResult):
            cleaned = re.sub(r"\s*\((VF|VOSTFR)\)", "", item.title, flags=re.IGNORECASE).strip().lower()
            ver_pref = 0
            if user_wants_vf and item.version != "VF":
                ver_pref = 1
            elif user_wants_vostfr and item.version != "VOSTFR":
                ver_pref = 1

            if cleaned == q_lower:
                match_rank = 0
            elif cleaned.startswith(q_lower):
                match_rank = 1
            elif re.search(r"\b" + re.escape(q_lower) + r"\b", cleaned):
                match_rank = 2
            elif q_lower in cleaned:
                match_rank = 3
            else:
                match_rank = 4

            asp_rank = getattr(item, "_asp_rank", 999)
            return (ver_pref, match_rank, asp_rank)

        return sorted(combined, key=sort_key)

    async def search_anime(self, query: str) -> List[AnimeResult]:
        logger.info("[voir-anime] Search: '%s'", query)
        results: List[AnimeResult] = []
        try:
            # 1. Moteur officiel Ajax Search Pro (identique au moteur live du site voir-anime.to)
            results = await self.search_via_asp(query)
        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[voir-anime] ASP search error: %s", e)

        # 2. Fallback vers la recherche standard WordPress si ASP ne renvoie rien
        if not results:
            try:
                search_url = f"{self.base_url}/?s={query.replace(' ', '+')}&post_type=wp-manga"
                async with self._get_async_client() as client:
                    resp = await client.get(search_url)
                    resp.raise_for_status()
                    if resp.status_code == 200:
                        results = self.parse_cards(resp.text)
                    if not results:
                        fallback_url = f"{self.base_url}/?s={query.replace(' ', '+')}"
                        resp2 = await client.get(fallback_url)
                        resp2.raise_for_status()
                        if resp2.status_code == 200:
                            results = self.parse_cards(resp2.text)
            except VerificationRequired:
                raise
            except Exception as e:
                logger.error("[voir-anime] Fallback search error: %s", e)
                raise

        logger.info("[voir-anime] %d result(s) for '%s'", len(results), query)
        return results

    def parse_cards(self, html: str) -> List[AnimeResult]:
        soup = BeautifulSoup(html, "html.parser")
        # Select individual cards before fallback wrappers; wrappers can contain several series.
        cards = soup.select(".page-item-detail.video, .page-item-detail, .c-tabs-item__content, .flw-item")
        if not cards:
            cards = soup.select(".page-listing-item .item-summary, .search-wrap .row")
        results: List[AnimeResult] = []
        seen_urls = set()

        for card in cards:
            try:
                link_el = card.select_one(".post-title a[href], .item-thumb a[href], .tab-thumb a[href], h3 a[href], h4 a[href], a.film-poster-ahref")
                if not link_el:
                    continue

                url = link_el.get("href", "").strip()
                if not url:
                    continue
                if not url.startswith("http"):
                    url = urljoin(self.base_url, url)

                # Si c'est un lien direct d'épisode, retrouver l'URL de la série si possible
                ep_match = re.search(r"^(.*/anime/[^/]+/).*$", url)
                if ep_match and url != ep_match.group(1):
                    main_link = card.select_one("a[href*='/anime/']:not([href*='-vostfr']):not([href*='-vf'])")
                    if main_link and main_link.get("href"):
                        m_href = main_link["href"]
                        url = m_href if m_href.startswith("http") else urljoin(self.base_url, m_href)
                    else:
                        url = ep_match.group(1)

                if url in seen_urls:
                    continue
                seen_urls.add(url)

                title_el = card.select_one(".post-title a, h3.h4 a, h3 a, h4 a, .item-title a, .dynamic-name")
                title = ""
                if title_el:
                    title = title_el.get_text().strip()
                if not title:
                    title = link_el.get("title", "").strip()
                if not title or title.upper() in ["VF", "VOSTFR"]:
                    title_attr = card.select_one("[title]")
                    if title_attr and title_attr.get("title"):
                        title = title_attr["title"].strip()

                if not title:
                    continue

                # Image / poster
                img = card.select_one("img")
                image_url = ""
                if img:
                    image_url = img.get("data-src", "") or img.get("data-lazy-src", "") or img.get("src", "")
                    if not image_url and img.get("srcset"):
                        image_url = img["srcset"].split()[0]
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)

                # Episode badge
                ep_el = card.select_one(".list-chapter .chapter a, .chapter-item a.btn-link, .chapter a, .tick-eps, .latest-chap, a.btn-link, .chapter-item")
                ep_info = ""
                if ep_el:
                    ep_text = ep_el.get_text().strip()
                    ep_info = ep_text.split("\n")[0].strip()
                    if ep_info and not ep_info.lower().startswith("ep"):
                        ep_info = f"Ep {ep_info}"

                # Version
                version = "VOSTFR"
                vf_flag = card.select_one(".manga-vf-flag, .badge-vf")
                if vf_flag or "(vf)" in title.lower() or "-vf" in url.lower():
                    version = "VF"

                # ID
                m_id = re.search(r"/anime/([^/]+)/?", url)
                anime_id = m_id.group(1) if m_id else str(hash(url))[:8]

                results.append(
                    AnimeResult(
                        id=anime_id,
                        title=title,
                        imageUrl=image_url,
                        url=url,
                        version=version,
                        type="Anime",
                        episodeInfo=ep_info,
                        source="voir-anime",
                    )
                )
            except Exception as e:
                logger.debug("Erreur parsing card voir-anime: %s", e)

        return results

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        if not is_safe_url(anime_url):
            logger.warning("[voir-anime] SSRF blocked for URL: %s", anime_url)
            return None
        logger.info("[voir-anime] Anime detail: %s", anime_url)
        try:
            async with self._get_async_client() as client:
                resp = await client.get(anime_url)
                if resp.status_code != 200:
                    logger.warning("[voir-anime] HTTP %d pour %s", resp.status_code, anime_url)
                    return None

                soup = BeautifulSoup(resp.text, "html.parser")
                title_el = soup.select_one(".post-title h1, h1.entry-title, h2.film-name, h1")
                title = title_el.get_text().strip() if title_el else ""
                if not title and soup.title:
                    title = soup.title.string.split("|")[0].split("-")[0].strip()

                # Sélectionner l'image de couverture principale en évitant le logo header (.vato.png)
                img = soup.select_one(".summary_image img, .thumb img, .c-image-hover img, .film-poster img, .tab-summary img")
                if not img:
                    for cand in soup.select("img.img-responsive, img[src*='uploads']"):
                        src_chk = (cand.get("src", "") or cand.get("data-src", "")).lower()
                        alt_chk = cand.get("alt", "").lower()
                        if "vato" not in src_chk and "logo" not in src_chk and "voiranime" not in alt_chk:
                            img = cand
                            break

                image_url = ""
                if img:
                    image_url = img.get("data-src", "") or img.get("src", "") or img.get("data-lazy-src", "")
                    if not image_url and img.get("srcset"):
                        image_url = img["srcset"].split()[0]
                    if image_url and not image_url.startswith("http"):
                        image_url = urljoin(self.base_url, image_url)

                syn_el = soup.select_one(".description-summary .summary__content, .description-summary, .film-description .text")
                synopsis = syn_el.get_text().strip() if syn_el else ""

                genres = [g.get_text().strip() for g in soup.select(".genres-content a, .item-list a[href*=genre]") if g.get_text().strip()]

                version = "VF" if ("(vf)" in title.lower() or "-vf" in anime_url.lower()) else "VOSTFR"

                episodes = await self.fetch_episodes(anime_url, soup, client)

                return AnimeDetail(
                    title=title,
                    imageUrl=image_url,
                    synopsis=synopsis,
                    genres=genres,
                    url=anime_url,
                    version=version,
                    episodes=episodes,
                    source="voir-anime",
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[voir-anime] Erreur détail anime: %s", e)
            return None

    def _parse_episode_number(self, title: str, url: str, fallback: int) -> int:
        # Pattern 1: format explicite dans le titre " - 11" ou "VOSTFR - 11"
        m = re.search(r"(?:VOSTFR|VF|\bEp|\bEpisode|\bÉpisode|-)\s*[:#-]?\s*(\d+)\b", title, re.IGNORECASE)
        if m:
            return int(m.group(1))
        # Pattern 2: slug d'URL (ex: "...-11-vostfr/")
        m_url = re.search(r"[-_](\d+)[-_](?:vostfr|vf)/?$", url, re.IGNORECASE)
        if m_url:
            return int(m_url.group(1))
        # Pattern 3: nombre en fin d'URL
        m_url_end = re.search(r"[-_](\d+)/?$", url)
        if m_url_end:
            return int(m_url_end.group(1))
        # Pattern 4: dernier nombre trouvé dans le titre
        nums = re.findall(r"\b\d+\b", title)
        if nums:
            return int(nums[-1])
        return fallback

    async def fetch_episodes(self, anime_url: str, soup: BeautifulSoup, client: Optional[httpx.AsyncClient] = None) -> List[Episode]:
        episodes: List[Episode] = []
        try:
            # 1. Sélecteur principal WordPress Madara
            ep_items = soup.select("li.wp-manga-chapter, .wp-manga-chapter, li.chapter-li, .listing-chapters .chapter-item")

            # 2. Fallback liens directs d'épisodes
            if not ep_items:
                ep_items = soup.select("a[href*='/anime/'][href*='-vostfr'], a[href*='/anime/'][href*='-vf'], .ep-item, a[href*=regarder]")

            if not ep_items:
                ep_items = soup.select("select.single-chapter-select option[data-redirect], select.selectpicker_chapter option[data-redirect]")
            seen = set()
            for idx, item in enumerate(ep_items, start=1):
                link = item if item.name in ("a", "option") else item.select_one("a")
                if not link or not (link.get("href") or link.get("data-redirect")):
                    continue

                ep_url = (link.get("href") or link.get("data-redirect")).strip()
                if not ep_url.startswith("http"):
                    ep_url = urljoin(self.base_url, ep_url)

                raw_title = link.get_text().strip()
                ep_num = self._parse_episode_number(raw_title, ep_url, fallback=idx)

                ep_version = "VF" if ("(vf)" in raw_title.lower() or "-vf" in ep_url.lower()) else "VOSTFR"
                clean_title = f"Épisode {ep_num}"
                if "film" in raw_title.lower():
                    clean_title = f"Film - {ep_num}"
                elif "oav" in raw_title.lower():
                    clean_title = f"OAV - {ep_num}"

                key = (ep_num, ep_version)
                if key in seen:
                    continue
                seen.add(key)

                episodes.append(
                    Episode(
                        number=ep_num,
                        title=clean_title,
                        playerUrl=ep_url,
                        downloadPageUrl=ep_url,
                        version=ep_version,
                    )
                )
        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[voir-anime] fetch_episodes error: %s", e)

        # Trier en ordre chronologique ascendant (1, 2, ... N)
        episodes.sort(key=lambda x: (x.number, x.version))
        return episodes

    def get_episode_servers(self, episode_url: str) -> Dict[str, Any]:
        """Retourne rapidement la liste des serveurs disponibles pour un épisode sans résoudre les flux vidéo."""
        if not is_safe_url(episode_url):
            logger.warning("[voir-anime] SSRF bloqué pour l'URL épisode: %s", episode_url)
            return {"servers": ["myTV"], "defaultServer": self.default_server}
        try:
            with self._get_client(follow_redirects=True, referer=self.base_url) as client:
                resp = client.get(episode_url)
                if resp.status_code != 200:
                    return {"servers": ["myTV"], "defaultServer": self.default_server}
                sources = self._parse_episode_sources(resp.text)
                server_keys = list(sources.keys()) if sources else ["myTV"]
                return {
                    "servers": server_keys,
                    "defaultServer": self.default_server
                }
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] get_episode_servers error: %s", e)
            return {"servers": ["myTV"], "defaultServer": self.default_server}

    def _decode_base64_mirror(self, value: str) -> Optional[str]:
        """Décode une valeur Base64 issue d'une balise option d'un sélecteur miroir (voiranime.io / voiranime.homes)."""
        if not value or not isinstance(value, str):
            return None
        cleaned = value.strip()
        if len(cleaned) < 8 or not re.match(r"^[A-Za-z0-9+/=_-]+$", cleaned):
            return None
        try:
            std_b64 = cleaned.replace("-", "+").replace("_", "/")
            pad_len = len(std_b64) % 4
            if pad_len:
                std_b64 += "=" * (4 - pad_len)
            decoded_bytes = base64.b64decode(std_b64)
            decoded_str = decoded_bytes.decode("utf-8", errors="ignore")

            # Extraction de la source iframe
            src_m = re.search(r"""<iframe[^>]*\ssrc=["']([^"']+)["']""", decoded_str, re.IGNORECASE)
            if src_m:
                iframe_url = src_m.group(1).replace(r"\/", "/")
                if iframe_url.startswith("//"):
                    iframe_url = "https:" + iframe_url
                return iframe_url

            # Si le texte décodé est directement une URL
            if decoded_str.strip().startswith("http://") or decoded_str.strip().startswith("https://") or decoded_str.strip().startswith("//"):
                direct_u = decoded_str.strip()
                if direct_u.startswith("//"):
                    direct_u = "https:" + direct_u
                return direct_u
        except Exception as e:
            logger.debug("[voir-anime] Échec décodage Base64 miroir: %s", e)
        return None

    def _normalize_server_name(self, label: str, url: str) -> str:
        s_lower = (label + " " + url).lower()
        if any(h in s_lower for h in ["mytv", "voembed", "vidmoly"]):
            return "myTV"
        elif any(h in s_lower for h in ["streamtape", "stape"]):
            return "stape"
        elif "voe" in s_lower:
            return "voe"
        elif any(h in s_lower for h in ["mail.ru", "fhd"]):
            return "fhd1"
        elif any(h in s_lower for h in ["gn1r5n", "byse", "moon"]):
            return "moon"
        return label or "server"

    def _parse_episode_sources(self, html: str) -> Dict[str, str]:
        """Extrait la cartographie {nom_serveur: embed_url} depuis les scripts, sélecteurs miroirs ou iframes de la page."""
        sources: Dict[str, str] = {}
        m = re.search(r"(?:var|let|const)\s+thisChapterSources\s*=\s*(\{.+?\})\s*;", html, re.DOTALL)
        if m:
            try:
                raw_dict = json.loads(m.group(1))
                for k, v in raw_dict.items():
                    raw_src = ""
                    src_m = re.search(r"""(?:data-src|src)=["\x27]([^"\x27]+)["\x27]""", v)
                    if src_m:
                        raw_src = src_m.group(1).replace(r"\/", "/")
                    elif v.strip().startswith("http") or v.strip().startswith("//") or "/e/" in v:
                        raw_src = v.strip().replace(r"\/", "/")
                    if raw_src:
                        if not raw_src.startswith("http"):
                            raw_src = urljoin(self.base_url, raw_src)
                        norm_k = k.replace("LECTEUR", "").strip()
                        key = self._normalize_server_name(norm_k, raw_src)
                        sources[key] = raw_src
            except Exception as e:
                logger.debug("[voir-anime] Erreur parsing thisChapterSources: %s", e)

        # 2. Parsing des sélecteurs miroirs en Base64 (clones voiranime.io / voiranime.homes)
        if not sources:
            soup = BeautifulSoup(html, "html.parser")
            mirror_options = soup.select("select.mirror option, select#select-mirror option, option[data-index], .mirror option")
            for idx, opt in enumerate(mirror_options):
                val = opt.get("value", "").strip()
                label = opt.get_text().strip() or opt.get("data-name", "").strip() or f"Lecteur {idx + 1}"
                if val:
                    iframe_url = self._decode_base64_mirror(val)
                    if not iframe_url and (val.startswith("http") or val.startswith("//")):
                        iframe_url = "https:" + val if val.startswith("//") else val

                    if iframe_url:
                        if not iframe_url.startswith("http"):
                            iframe_url = urljoin(self.base_url, iframe_url)
                        key = self._normalize_server_name(label, iframe_url)
                        sources[key] = iframe_url

        # 3. Fallback direct sur les balises iframes
        if not sources:
            soup = BeautifulSoup(html, "html.parser")
            for ifr in soup.select("iframe"):
                src = ifr.get("src") or ifr.get("data-src")
                if src and not src.startswith("about:"):
                    if not src.startswith("http"):
                        src = urljoin(self.base_url, src)
                    key = self._normalize_server_name(f"server_{len(sources)+1}", src)
                    sources[key] = src
        return sources

    def extract_download_info(
        self,
        episode_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
        quality_strategy: Optional[str] = None,
    ) -> Dict[str, Any]:
        if not is_safe_url(episode_url):
            logger.warning("[voir-anime] SSRF bloqué pour l'URL épisode dans extract_download_info: %s", episode_url)
            return {
                "directUrl": "",
                "subtitleUrl": "",
                "formattedSize": "Taille inconnue",
                "size": -1,
                "serverType": "unknown",
            }
        logger.info("[voir-anime] extract_download_info: %s (pref_server=%s, pref_quality=%s)",
                    episode_url, preferred_server, preferred_quality)
        result = {
            "videoUrl": "",
            "videoChunks": "[]",
            "videoQualities": "{}",
            "subtitleUrl": "",
            "subtitles": "[]",
            "serverType": "unknown",
            "availableServers": "[]",
            "selectedQuality": "",
            "size": -1,
            "formattedSize": "Taille inconnue",
            "qualitiesSizes": "{}",
        }

        try:
            with self._get_client(follow_redirects=True, referer=self.base_url) as client:
                resp = client.get(episode_url)
                if resp.status_code != 200:
                    return result
                html = resp.text

                # 1. Identifier tous les serveurs disponibles
                sources = self._parse_episode_sources(html)
                avail_servers = list(sources.keys())
                result["availableServers"] = json.dumps(avail_servers)

                if not sources:
                    return result

                # 2. Déterminer l'ordre des serveurs à tenter
                target_server = preferred_server or self.default_server
                if target_server and target_server.lower() == "auto":
                    target_server = None

                default_priority = ["myTV", "fhd1", "voe", "moon", "stape"]
                try_order: List[str] = []

                # Si un serveur préféré est spécifié et disponible, le tenter en premier
                if target_server:
                    for s_key in sources.keys():
                        if s_key.lower() == target_server.lower():
                            try_order.append(s_key)
                            break

                # Ajouter les autres serveurs disponibles dans l'ordre de priorité
                for s_prio in default_priority:
                    for s_key in sources.keys():
                        if s_key.lower() == s_prio.lower() and s_key not in try_order:
                            try_order.append(s_key)

                # Ajouter les éventuels serveurs restants
                for s_key in sources.keys():
                    if s_key not in try_order:
                        try_order.append(s_key)

                best_url = ""
                qualities: Dict[str, str] = {}
                subtitle_url = ""
                resolved_server = "unknown"
                qualities_sizes_bytes: Dict[str, int] = {}
                qualities_sizes_formatted: Dict[str, str] = {}
                detected_size: int = -1

                # 3. Résolution selon l'ordre de priorité (avec fallback automatique si indisponible)
                for s_name in try_order:
                    s_url = sources[s_name]
                    logger.info("[voir-anime] Attempting resolution on server '%s' (%s)", s_name, s_url)
                    s_lower = s_name.lower()

                    if s_lower == "mytv" or any(h in s_url for h in ["voembed", "vidmoly"]):
                        mytv_res = self._resolve_mytv(s_url, episode_url, client)
                        if len(mytv_res) >= 4:
                            u, q, sub, q_sizes_bytes = mytv_res[:4]
                        else:
                            u, q, sub = mytv_res[:3]
                            q_sizes_bytes = {}
                        if u:
                            best_url, qualities, subtitle_url = u, q, sub
                            resolved_server = "myTV"
                            qualities_sizes_bytes = q_sizes_bytes
                            for qk, qsz in q_sizes_bytes.items():
                                if qsz > 0:
                                    qualities_sizes_formatted[qk] = format_bytes(qsz)
                            break

                    elif s_lower in ["stape", "streamtape"] or "streamtape" in s_url:
                        mp4_url = self._resolve_streamtape(s_url, episode_url, client)
                        if mp4_url:
                            best_url = mp4_url
                            qualities = {"1080p (Streamtape)": mp4_url}
                            resolved_server = "stape"
                            try:
                                hr = client.head(mp4_url, headers={"Referer": "https://streamtape.com/"}, timeout=5.0, follow_redirects=True)
                                cl = hr.headers.get("Content-Length")
                                if cl and cl.isdigit() and int(cl) > 0:
                                    detected_size = int(cl)
                                    qualities_sizes_bytes["1080p (Streamtape)"] = detected_size
                                    qualities_sizes_formatted["1080p (Streamtape)"] = format_bytes(detected_size)
                            except VerificationRequired:
                                raise
                            except Exception:
                                pass
                            break

                    elif s_lower == "voe" or "voe" in s_url:
                        u, q = self._resolve_voe(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "voe"
                            if ".m3u8" in u.lower():
                                q_sizes = self._estimate_m3u8_sizes_sync(u, qualities, {}, client, referer="https://voe.sx/")
                                if q_sizes:
                                    qualities_sizes_bytes = q_sizes
                                    for qk, qsz in q_sizes.items():
                                        if qsz > 0:
                                            qualities_sizes_formatted[qk] = format_bytes(qsz)
                            else:
                                try:
                                    parsed_voe = urllib.parse.urlparse(u)
                                    v_ref = f"{parsed_voe.scheme}://{parsed_voe.netloc}/" if parsed_voe.netloc else "https://voe.sx/"
                                    hr = client.head(u, headers={"Referer": v_ref}, timeout=5.0, follow_redirects=True)
                                    cl = hr.headers.get("Content-Length")
                                    if cl and cl.isdigit() and int(cl) > 0:
                                        detected_size = int(cl)
                                        for qk in qualities.keys():
                                            qualities_sizes_bytes[qk] = detected_size
                                            qualities_sizes_formatted[qk] = format_bytes(detected_size)
                                except VerificationRequired:
                                    raise
                                except Exception:
                                    pass
                            break

                    elif s_lower == "fhd1" or "mail.ru" in s_url:
                        u, q = self._resolve_fhd1(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "fhd1"
                            try:
                                hr = client.head(u, headers={"Referer": "https://my.mail.ru/"}, timeout=5.0, follow_redirects=True)
                                cl = hr.headers.get("Content-Length")
                                if cl and cl.isdigit() and int(cl) > 0:
                                    detected_size = int(cl)
                                    for qk in qualities.keys():
                                        qualities_sizes_bytes[qk] = detected_size
                                        qualities_sizes_formatted[qk] = format_bytes(detected_size)
                            except VerificationRequired:
                                raise
                            except Exception:
                                pass
                            break

                    elif s_lower == "moon" or "gn1r5n" in s_url or "byse" in s_url:
                        u, q = self._resolve_moon(s_url, episode_url, client)
                        if u:
                            best_url, qualities = u, q
                            resolved_server = "moon"
                            break

                # 4. Sélection de la qualité souhaitée
                selected_q_label = ""
                if qualities:
                    if not quality_strategy:
                        try:
                            from animelab.services.source_settings_service import source_settings_service
                            va_settings = source_settings_service.get_source_settings("voir-anime")
                            quality_strategy = va_settings.get("quality_strategy", "highest")
                        except VerificationRequired:
                            raise
                        except Exception:
                            quality_strategy = "highest"

                    is_lowest_strategy = (
                        str(quality_strategy).lower() in ["lowest", "faible", "min"]
                        or (preferred_quality and str(preferred_quality).lower() in ["lowest", "faible", "min"])
                    )

                    if preferred_quality and preferred_quality.lower() not in ["auto", "max", "highest", "lowest", "faible", "min"]:
                        pq_clean = preferred_quality.strip().lower()
                        # 4.1 Correspondance textuelle directe
                        for q_k, q_v in qualities.items():
                            if pq_clean == q_k.lower() or pq_clean in q_k.lower():
                                best_url = q_v
                                selected_q_label = q_k
                                break

                        # 4.2 Recherche numérique la plus proche (ex: 720p, 480p, 360p, 1080p)
                        if not selected_q_label:
                            pref_num_m = re.search(r"(\d{3,4})", pq_clean)
                            if pref_num_m:
                                target_res = int(pref_num_m.group(1))
                                parsed_qualities = []
                                for q_k, q_v in qualities.items():
                                    res_m = re.search(r"(\d{3,4})", q_k)
                                    res_val = int(res_m.group(1)) if res_m else 0
                                    parsed_qualities.append((res_val, q_k, q_v))

                                # Trier par distance absolue avec la cible, puis priorité pour <= target_res
                                parsed_qualities.sort(key=lambda item: (abs(item[0] - target_res), -(target_res >= item[0])))
                                if parsed_qualities:
                                    selected_q_label = parsed_qualities[0][1]
                                    best_url = parsed_qualities[0][2]

                    # 4.3 Fallback si aucune préférence ou aucune qualité sélectionnée : respecter la stratégie (lowest vs highest)
                    if not selected_q_label:
                        ordered_candidates = ["360p", "480p", "720p", "1080p"] if is_lowest_strategy else ["1080p", "720p", "480p", "360p"]
                        for q_cand in ordered_candidates:
                            for q_k, q_v in qualities.items():
                                if q_cand in q_k.lower():
                                    best_url = q_v
                                    selected_q_label = q_k
                                    break
                            if selected_q_label:
                                break

                    if not selected_q_label:
                        numeric_items = []
                        for q_k, q_v in qualities.items():
                            m_num = re.search(r"(\d{3,4})", q_k)
                            val = int(m_num.group(1)) if m_num else 0
                            numeric_items.append((val, q_k, q_v))
                        numeric_items.sort(key=lambda x: x[0], reverse=not is_lowest_strategy)
                        selected_q_label = numeric_items[0][1]
                        best_url = numeric_items[0][2]

                if selected_q_label in qualities_sizes_bytes and qualities_sizes_bytes[selected_q_label] > 0:
                    detected_size = qualities_sizes_bytes[selected_q_label]
                elif detected_size <= 0 and qualities_sizes_bytes:
                    detected_size = next((sz for sz in qualities_sizes_bytes.values() if sz > 0), -1)

                formatted_sz = format_bytes(detected_size) if detected_size > 0 else "Taille inconnue"

                result["videoUrl"] = best_url
                result["videoQualities"] = json.dumps(qualities)
                result["videoChunks"] = json.dumps([best_url] if best_url else [])
                result["subtitleUrl"] = subtitle_url
                result["subtitles"] = json.dumps([{"label": "Sous-titres FR", "srclang": "fr", "url": subtitle_url}]) if subtitle_url else "[]"
                result["serverType"] = resolved_server
                result["selectedQuality"] = selected_q_label
                result["size"] = detected_size
                result["formattedSize"] = formatted_sz
                result["qualitiesSizes"] = json.dumps(qualities_sizes_formatted)

        except VerificationRequired:
            raise
        except Exception as e:
            logger.error("[voir-anime] extract_download_info error: %s", e)

        return result

    def _resolve_mytv(
        self, ifr_url: str, episode_url: str, client: httpx.Client
    ) -> Tuple[str, Dict[str, str], str, Dict[str, int]]:
        """Résout le lecteur myTV (Voembed / Vidmoly) en playlist HLS m3u8 et extrait toutes les résolutions avec tailles estimées."""
        code_m = re.search(r"embed-([a-zA-Z0-9]+)\.html", ifr_url)
        file_code = code_m.group(1) if code_m else ""

        domains = ["voembed.net", "vidmoly.to", "vidmoly.me", "vidmoly.biz"]
        tried_urls = [ifr_url]
        if file_code:
            for d in domains:
                cand = f"https://{d}/embed-{file_code}.html"
                if cand not in tried_urls:
                    tried_urls.append(cand)

        embed_html = ""
        for cand_url in tried_urls:
            try:
                emb_resp = client.get(cand_url, headers={"Referer": episode_url}, timeout=10)
                if emb_resp.status_code == 200 and len(emb_resp.text) > 500:
                    embed_html = emb_resp.text
                    js_redir = re.search(r"window\.location\.replace\(\x27([^\x27]+)\x27\)", embed_html)
                    if js_redir:
                        redir_resp = client.get(js_redir.group(1), headers={"Referer": episode_url}, timeout=10)
                        if redir_resp.status_code == 200:
                            embed_html = redir_resp.text
                    break
            except VerificationRequired:
                raise
            except Exception:
                try:
                    c_requests = source_http.client()
                    c_resp = c_requests.get(cand_url, headers={"Referer": episode_url}, timeout=10)
                    if c_resp.status_code == 200 and len(c_resp.text) > 500:
                        embed_html = c_resp.text
                        js_redir = re.search(r"window\.location\.replace\(\x27([^\x27]+)\x27\)", embed_html)
                        if js_redir:
                            r2 = c_requests.get(js_redir.group(1), headers={"Referer": episode_url}, timeout=10)
                            if r2.status_code == 200:
                                embed_html = r2.text
                        break
                except VerificationRequired:
                    raise
                except Exception:
                    pass

        qualities: Dict[str, str] = {}
        bandwidths: Dict[str, int] = {}
        qualities_sizes: Dict[str, int] = {}
        best_url = ""
        subtitle_url = ""

        if embed_html:
            m_sources = re.search(r"sources\s*:\s*\[\s*\{\s*file\s*:\s*[\x27\x22]([^\x27\x22]+)[\x27\x22]", embed_html)
            master_m3u8 = m_sources.group(1) if m_sources else ""
            if not master_m3u8:
                m_gen = re.search(r"[\x27\x22](https?://[^\x27\x22]+\.m3u8[^\x27\x22]*)[\x27\x22]", embed_html)
                if m_gen:
                    master_m3u8 = m_gen.group(1)

            if master_m3u8:
                parsed_q, parsed_bw = self._extract_qualities_and_bandwidths_from_m3u8(master_m3u8, client)
                if parsed_q:
                    qualities.update(parsed_q)
                    bandwidths.update(parsed_bw)
                    for q_key in ["1080p", "720p", "480p", "360p"]:
                        if q_key in qualities:
                            best_url = qualities[q_key]
                            break
                    if not best_url:
                        best_url = next(iter(qualities.values()))
                else:
                    best_url = master_m3u8
                    qualities["Auto"] = master_m3u8

            sub_m = re.search(r"[\x27\x22](https?://[^\x27\x22]+\.(?:vtt|srt)[^\x27\x22]*)[\x27\x22]", embed_html, re.IGNORECASE)
            if sub_m:
                subtitle_url = sub_m.group(1)

            if best_url:
                try:
                    q_sizes = self._estimate_m3u8_sizes_sync(best_url, qualities, bandwidths, client)
                    if q_sizes:
                        qualities_sizes.update(q_sizes)
                except VerificationRequired:
                    raise
                except Exception as e:
                    logger.debug("[voir-anime] Erreur estimation taille myTV: %s", e)

        return best_url, qualities, subtitle_url, qualities_sizes

    def _resolve_streamtape(self, ifr_url: str, referer: str, client: httpx.Client) -> Optional[str]:
        """Résout l'URL directe d'une vidéo Streamtape en neutralisant les pièges d'obfuscation."""
        try:
            vid_m = re.search(r"/[ev]/([a-zA-Z0-9]+)", ifr_url)
            video_id = vid_m.group(1) if vid_m else ""

            st_html = ""
            try:
                c_requests = source_http.client()
                c_resp = c_requests.get(ifr_url, headers={"Referer": referer}, timeout=12)
                if c_resp.status_code == 200:
                    st_html = c_resp.text
            except VerificationRequired:
                raise
            except Exception:
                pass

            if not st_html:
                st_resp = client.get(ifr_url, headers={"Referer": referer}, timeout=12)
                if st_resp.status_code == 200:
                    st_html = st_resp.text

            if not st_html or "Video not found" in st_html or "deleted by the creator" in st_html or "has been removed" in st_html:
                return None

            pattern = r"innerHTML\s*=\s*['\"]([^'\"]+)['\"]\s*\+\s*(?:''\s*\+\s*)?\(\s*['\"]([^'\"]+)['\"]\s*\)((?:\s*\.substring\(\s*\d+\s*\))+)"
            for m in re.finditer(pattern, st_html):
                prefix = m.group(1)
                raw_str = m.group(2)
                sub_ops = re.findall(r"\.substring\((\d+)\)", m.group(3))
                s = raw_str
                for op in sub_ops:
                    s = s[int(op):]
                cand = prefix + s

                # Normaliser schéma et domaine
                if cand.startswith("//"):
                    cand = "https:" + cand
                elif cand.startswith("https://") or cand.startswith("http://"):
                    pass
                elif cand.startswith("streamtape.com/"):
                    cand = "https://" + cand
                elif cand.startswith("/"):
                    cand = "https://streamtape.com/" + cand.lstrip("/")
                else:
                    cand = "https://streamtape.com/" + cand
                cand = re.sub(r"https?://[^/]*tape[^/]*/(?:streamtape\.com/)+", "https://streamtape.com/", cand)
                cand = re.sub(r"https?://[^/]*tape[^/]*/", "https://streamtape.com/", cand)

                # Nettoyer les chemins et paramètres piégés
                cand = cand.replace("/bget_video", "/get_video").replace("/get_videbo", "/get_video").replace("/get_vidbo", "/get_video")
                if video_id:
                    cand = re.sub(r"([?&])(?:b?id=)[^&]+", r"\1id=" + video_id, cand)

                if "streamtape.com/get_video?" in cand:
                    redir_url = None
                    try:
                        c_requests = source_http.client()
                        r_c = c_requests.get(cand, headers={"Referer": "https://streamtape.com/"}, allow_redirects=False, timeout=8)
                        if r_c.status_code in [301, 302, 303, 307, 308]:
                            redir_url = r_c.headers.get("location")
                        elif r_c.status_code == 200 and "text/html" not in (r_c.headers.get("content-type") or ""):
                            return cand
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass

                    if not redir_url:
                        try:
                            redir_resp = client.get(cand, headers={"Referer": "https://streamtape.com/"}, follow_redirects=False, timeout=8)
                            if redir_resp.status_code in [301, 302, 303, 307, 308]:
                                redir_url = redir_resp.headers.get("location")
                            elif redir_resp.status_code == 200 and "text/html" not in (redir_resp.headers.get("content-type") or ""):
                                return cand
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                    if redir_url:
                        return redir_url
                    logger.debug("[voir-anime] Piège HTML ou erreur 404 sur candidat Streamtape ignoré: %s", cand)

            m_tape = re.search(r"document\.getElementById\(['\"]videolink['\"]\)\.innerHTML\s*=\s*['\"]([^'\"]+)['\"]", st_html)
            if m_tape:
                cand = "https:" + m_tape.group(1) if m_tape.group(1).startswith("//") else m_tape.group(1)
                if video_id:
                    cand = re.sub(r"([?&])(?:b?id=)[^&]+", r"\1id=" + video_id, cand)
                try:
                    c_requests = source_http.client()
                    r_c = c_requests.get(cand, headers={"Referer": "https://streamtape.com/"}, allow_redirects=False, timeout=8)
                    if r_c.status_code in [301, 302, 303, 307, 308] and r_c.headers.get("location"):
                        return r_c.headers.get("location")
                except VerificationRequired:
                    raise
                except Exception:
                    pass
                return cand
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] Erreur résolution Streamtape: %s", e)
        return None

    def _resolve_voe(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur VOE vers sa source vidéo directe."""
        try:
            resp = client.get(ifr_url, headers={"Referer": referer}, timeout=10)
            if resp.status_code != 200:
                return "", {}
            html_text = resp.text
            redir_m = re.search(r"window\.location\.href\s*=\s*['\"]([^'\"]+)['\"]", html_text)
            curr_url = redir_m.group(1) if redir_m else str(resp.url)
            if redir_m:
                redir_resp = client.get(curr_url, headers={"Referer": ifr_url}, timeout=10)
                if redir_resp.status_code == 200:
                    html_text = redir_resp.text
                    curr_url = str(redir_resp.url)

            # 1. Tenter la page /download de VOE (direct MP4 unescaped)
            vid_m = re.search(r"/e/([a-zA-Z0-9]+)", curr_url) or re.search(r"/e/([a-zA-Z0-9]+)", ifr_url)
            if vid_m:
                vid = vid_m.group(1)
                parsed_u = urllib.parse.urlparse(curr_url)
                host = parsed_u.netloc or "voe.sx"
                dl_page_url = f"https://{host}/{vid}/download"
                try:
                    r_dl = client.get(dl_page_url, headers={"Referer": curr_url}, timeout=8)
                    if r_dl.status_code == 200:
                        dl_html = r_dl.text
                        qualities: Dict[str, str] = {}
                        for a_m in re.finditer(
                            r"<a[^>]+href=[\x27\x22](https?://[^\x27\x22]+)[\x27\x22][^>]*>(.*?)</a>",
                            dl_html,
                            re.DOTALL,
                        ):
                            href = html.unescape(a_m.group(1))
                            text = a_m.group(2).strip()
                            if ".mp4" in href or "download" in href:
                                q_m = re.search(r"(\d{3,4}p)", text, re.IGNORECASE)
                                q_label = f"{q_m.group(1)} (VOE)" if q_m else "720p (VOE)"
                                qualities[q_label] = href
                        if qualities:
                            best = (
                                qualities.get("1080p (VOE)")
                                or qualities.get("720p (VOE)")
                                or next(iter(qualities.values()))
                            )
                            return best, qualities
                except VerificationRequired:
                    raise
                except Exception as e:
                    logger.debug("[voir-anime] VOE download page error: %s", e)

            # 2. Fallback classique regex m3u8 / mp4
            m3u8_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.m3u8[^\s'\"<>]*)['\"]", html_text)
            mp4_matches = re.findall(r"['\"](https?://[^\s'\"<>]+\.mp4[^\s'\"<>]*)['\"]", html_text)

            valid_mp4 = [html.unescape(u) for u in mp4_matches if "test-videos" not in u and "google" not in u]
            valid_m3u8 = [html.unescape(u) for u in m3u8_matches if "google" not in u]

            if valid_m3u8:
                m3u8_url = valid_m3u8[0]
                qualities = self._extract_qualities_from_m3u8(m3u8_url, client)
                if not qualities:
                    qualities["Auto (VOE)"] = m3u8_url
                best = qualities.get("1080p") or qualities.get("720p") or next(iter(qualities.values()))
                return best, qualities
            elif valid_mp4:
                return valid_mp4[0], {"Original (VOE)": valid_mp4[0]}

            m_src = re.search(r"sources\s*=\s*(\{[^{}]+\})", html_text)
            if m_src:
                try:
                    data = json.loads(m_src.group(1))
                    hls = data.get("hls") or data.get("mp4")
                    if hls:
                        hls = html.unescape(hls)
                        return hls, {"VOE": hls}
                except VerificationRequired:
                    raise
                except Exception:
                    pass
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] _resolve_voe error: %s", e)
        return "", {}

    def _resolve_fhd1(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur FHD1 (Mail.ru) vers les résolutions MP4."""
        try:
            m_id = re.search(r"/video/embed/(\d+)", ifr_url)
            if not m_id:
                return "", {}
            vid_id = m_id.group(1)
            meta_url = f"https://my.mail.ru/+/video/meta/{vid_id}"
            headers = {"User-Agent": proxy_service.get_user_agent(), "Referer": ifr_url}
            r = client.get(meta_url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                videos = data.get("videos", [])
                qualities: Dict[str, str] = {}
                for v in videos:
                    key = str(v.get("key", "HD"))
                    label = f"{key}p" if key.isdigit() else key
                    u = v.get("url")
                    if u:
                        if u.startswith("//"):
                            u = "https:" + u
                        qualities[label] = u
                if qualities:
                    best = qualities.get("1080p") or qualities.get("720p") or next(iter(qualities.values()))
                    return best, qualities
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] _resolve_fhd1 error: %s", e)
        return "", {}

    def _resolve_moon(self, ifr_url: str, referer: str, client: httpx.Client) -> Tuple[str, Dict[str, str]]:
        """Résout le lecteur MOON (Byse) vers son flux de streaming."""
        try:
            m_code = re.search(r"/e/([a-zA-Z0-9]+)", ifr_url)
            if not m_code:
                return "", {}
            code = m_code.group(1)
            base_moon = "https://gn1r5n.org"
            headers = {
                "User-Agent": proxy_service.get_user_agent(),
                "Referer": ifr_url,
                "X-Embed-Origin": "voir-anime.to",
                "X-Embed-Referer": self.base_url + "/",
                "X-Embed-Parent": self.base_url + "/",
            }
            det_url = f"{base_moon}/api/videos/{code}/embed/details"
            r_det = client.get(det_url, headers=headers, timeout=8)
            if r_det.status_code == 200:
                stream_url = f"{base_moon}/api/videos/stream/{code}"
                return stream_url, {"1080p (MOON)": stream_url}
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] _resolve_moon error: %s", e)
        return "", {}

    def _extract_qualities_and_bandwidths_from_m3u8(
        self, master_url: str, client: httpx.Client, referer: Optional[str] = None
    ) -> Tuple[Dict[str, str], Dict[str, int]]:
        qualities: Dict[str, str] = {}
        bandwidths: Dict[str, int] = {}
        try:
            try:
                resp = client.get(master_url, headers={"Referer": referer or "https://voembed.net/"})
            except TypeError:
                resp = client.get(master_url)
            if resp.status_code == 200:
                lines = resp.text.strip().split("\n")
                current_bw = 0
                for i, line in enumerate(lines):
                    line_s = line.strip()
                    if line_s.startswith("#EXT-X-STREAM-INF:"):
                        res_m = re.search(r"RESOLUTION=\d+x(\d+)", line_s)
                        bw_m = re.search(r"BANDWIDTH=(\d+)", line_s)
                        current_bw = int(bw_m.group(1)) if bw_m else 0
                        label = f"{res_m.group(1)}p" if res_m else "Stream"
                        if i + 1 < len(lines):
                            stream_url = lines[i + 1].strip()
                            if not stream_url.startswith("#"):
                                full_url = urljoin(master_url, stream_url)
                                qualities[label] = full_url
                                if current_bw > 0:
                                    bandwidths[label] = current_bw
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] _extract_qualities_and_bandwidths_from_m3u8: %s", e)
        return qualities, bandwidths

    def _extract_qualities_from_m3u8(self, master_url: str, client: httpx.Client) -> Dict[str, str]:
        qualities, _ = self._extract_qualities_and_bandwidths_from_m3u8(master_url, client)
        return qualities

    def _estimate_m3u8_sizes_sync(
        self,
        sample_url: str,
        qualities: Dict[str, str],
        bandwidths: Dict[str, int],
        client: httpx.Client,
        referer: Optional[str] = None,
    ) -> Dict[str, int]:
        qualities_sizes: Dict[str, int] = {}
        if not sample_url:
            return qualities_sizes

        ref = referer or "https://voembed.net/"
        try:
            try:
                resp = client.get(sample_url, headers={"Referer": ref})
            except TypeError:
                resp = client.get(sample_url)
            if resp.status_code != 200:
                return qualities_sizes

            text = resp.text
            durations = [float(d) for d in re.findall(r"#EXTINF:([\d.]+)", text)]
            total_duration = sum(durations)
            segs = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]

            if total_duration <= 0 and segs:
                td_m = re.search(r"#EXT-X-TARGETDURATION:(\d+)", text)
                target_dur = float(td_m.group(1)) if td_m else 10.0
                total_duration = len(segs) * target_dur

            # 1. Calcul exact via débits binaires
            if bandwidths and total_duration > 0:
                for q_label, bw in bandwidths.items():
                    if bw > 0:
                        qualities_sizes[q_label] = int((bw * total_duration) / 8)

            # 2. Fallback: échantillonnage parallèle HEAD sur 2 segments
            if not qualities_sizes and segs:
                sample_indices = list(set([0, len(segs) // 2, max(0, len(segs) - 2)]))
                sample_sizes: List[int] = []
                for idx in sample_indices:
                    seg_u = segs[idx]
                    if not seg_u.startswith("http"):
                        seg_u = urljoin(sample_url, seg_u)
                    try:
                        try:
                            hr = client.head(seg_u, headers={"Referer": ref})
                        except TypeError:
                            hr = client.head(seg_u)
                        cl = hr.headers.get("Content-Length")
                        if cl and cl.isdigit() and int(cl) > 0:
                            sample_sizes.append(int(cl))
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass
                if sample_sizes:
                    avg_sz = sum(sample_sizes) / len(sample_sizes)
                    estimated_sz = int(avg_sz * len(segs))
                    for q_label in (qualities.keys() if qualities else ["Stream"]):
                        qualities_sizes[q_label] = estimated_sz
                elif total_duration > 0:
                    for q_label in (qualities.keys() if qualities else ["Stream"]):
                        qualities_sizes[q_label] = int((1_800_000 * total_duration) / 8)

        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[voir-anime] _estimate_m3u8_sizes_sync error: %s", e)

        return qualities_sizes

    def extract_video_chunks(self, episode_url: str) -> List[str]:
        info = self.extract_download_info(episode_url)
        try:
            return json.loads(info.get("videoChunks", "[]"))
        except VerificationRequired:
            raise
        except Exception:
            return []

    def extract_video_qualities(self, episode_url: str) -> Dict[str, str]:
        info = self.extract_download_info(episode_url)
        try:
            return json.loads(info.get("videoQualities", "{}"))
        except VerificationRequired:
            raise
        except Exception:
            return {}

voiranime_service = VoirAnimeScrapingService()
