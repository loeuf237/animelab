from animelab.services.source_http import source_http, VerificationRequired
import json
import asyncio
import logging
import re
from typing import List, Dict, Any, Optional
from urllib.parse import urljoin, quote_plus, urlparse
from bs4 import BeautifulSoup
import httpx

from animelab.config import settings
from animelab.services.extension_observability import InvalidSelector, SelectorMismatch
from animelab.models.anime import AnimeResult, AnimeDetail, Episode
from animelab.security import is_safe_url
from animelab.services.aniyomi_dex_parser import SourceRecipe
from animelab.services.proxy_service import proxy_service

logger = logging.getLogger("animelab.container")

from animelab.services.recipe_runtime import RecipeRuntime
from animelab.services.recipe_plans import compile_operations, repair_legacy_recipe
from animelab.services.extractors import extractor_registry


KNOWN_EMBED_HOSTS = {
    "sibnet": "Sibnet",
    "sendvid": "Sendvid",
    "vidmoly": "Vidmoly",
    "ansembed": "Vidmoly",
    "voembed": "Vidmoly",
    "vmeas": "Vidmoly",
    "vmpx": "Vidmoly",
    "streamtape": "Streamtape",
    "stape": "Streamtape",
    "tapecontent": "Streamtape",
    "voe": "VOE",
    "uqload": "Uqload",
    "filemoon": "Filemoon",
    "dood": "Doodstream",
    "mp4upload": "Mp4upload",
    "mail.ru": "MailRu",
    "my.mail.ru": "MailRu",
    "kwik": "Kwik",
    "owocdn": "Kwik",
}


def _clean_selector(sel: Optional[str]) -> str:
    if not sel:
        return ""
    # Nettoie les virgules orphelines ou espaces en fin de chaîne
    return sel.strip().rstrip(",; ").strip()

def _safe_select(parent: Any, selector: str) -> List[Any]:
    s = _clean_selector(selector)
    if s.startswith("api:"):
        raise NotImplementedError("This APK operation needs a supported data recipe; API markers are not CSS selectors")
    if not s:
        return []
    try:
        return parent.select(s)
    except VerificationRequired:
        raise
    except Exception:
        # Si le sélecteur composé échoue (syntaxe invalide), essayer chaque sous-sélecteur séparé par virgule
        valid: List[Any] = []
        any_valid = False
        for part in s.split(","):
            p = _clean_selector(part)
            if p:
                try:
                    elements = parent.select(p)
                    any_valid = True
                    for el in elements:
                        if el not in valid:
                            valid.append(el)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
        if not any_valid:
            raise InvalidSelector("Invalid extension selector")
        return valid

def _safe_select_one(parent: Any, selector: str) -> Optional[Any]:
    results=_safe_select(parent,selector)
    return results[0] if results else None


def _item_title(card, link, selector, image=None):
    # A union CSS selector returns DOM order: badges/images may precede h3.
    # Prefer a real text title, rather than flattening an entire card's labels.
    nodes = _safe_select(card, selector)
    for node in nodes:
        if node.name != 'img':
            title = node.get_text(' ', strip=True)
            if title:
                return title
    owner = card if card.get('data-nom') else card.parent
    if owner and owner.get('data-nom'):
        return owner['data-nom'].strip()
    return (link.get('title') or link.get('aria-label') or
            (image.get('alt') if image else '') or link.get_text(' ', strip=True)).strip()


class AniyomiContainerSource:
    """Conteneur d'exécution dynamique qui exécute une SourceRecipe extraite d'une extension Aniyomi."""

    def __init__(self, recipe: SourceRecipe):
        # Upgrade the old built-in VoirAnime recipe without replacing custom selectors.
        host = (urlparse(recipe.base_url).hostname or "").lower()
        if host in ("voir-anime.to", "www.voir-anime.to"):
            current_cards = ".page-item-detail.video, .page-item-detail, .c-tabs-item__content"
            for field in ("search_selector", "popular_selector", "latest_selector"):
                if getattr(recipe, field) in ("", "div.c-tabs-item__content, article"):
                    setattr(recipe, field, current_cards)
            if not recipe.item_title_selector:
                recipe.item_title_selector = ".post-title a, h3.h5 a, h3 a"
            if not recipe.item_link_selector:
                recipe.item_link_selector = ".post-title a[href], .item-thumb a[href], .tab-thumb a[href]"
        # Repair known incomplete paths emitted by older DEX imports without
        # replacing user-configured selectors or arbitrary request paths.
        if recipe.pkg.endswith(".jetanime"):
            if recipe.latest_request_path == "/page/":
                recipe.latest_request_path = "/page/1/"
            if recipe.latest_selector == "div.content article > div.poster":
                recipe.latest_selector = "div.content article"
            if recipe.episode_list_selector == "ul.episodios > li":
                recipe.episode_list_selector = "ul.episodios > li, .episodiotitle a"
        if recipe.pkg.endswith(".vostfree") and recipe.search_request_path == "/animes-vostfr/page/":
            recipe.search_request_path = "/index.php?do=search"
        for field in ("popular_request_path", "latest_request_path"):
            path = getattr(recipe, field)
            if path.endswith("?page="):
                setattr(recipe, field, path + "1")
        repair_legacy_recipe(recipe)
        compile_operations(recipe)
        self.recipe = recipe
        self.name = recipe.name or recipe.pkg.split(".")[-1].capitalize()
        self.base_url = recipe.base_url.rstrip("/")
        self.pkg = recipe.pkg
        self.lang = recipe.lang
        self.last_error = None
        self.source_id = recipe.pkg  # Identifiant unique de la source
        self.data_runtime = RecipeRuntime(self)

    def _get_headers(self, referer: Optional[str] = None) -> Dict[str, str]:
        return {
            "User-Agent": settings.DEFAULT_USER_AGENT,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
            "Accept-Language": "fr-FR,fr;q=0.9,en-US;q=0.8,en;q=0.7",
            "Referer": referer or (self.base_url + "/"),
        }

    async def _fetch_html(self, url: str, method: str = "GET", data: Optional[Dict[str, Any]] = None, timeout: float = 10.0) -> str:
        headers = self._get_headers(referer=self.base_url + "/")
        headers["Origin"] = self.base_url
        headers["X-Requested-With"] = "XMLHttpRequest"
        try:
            # The common transport checks initial and redirected URLs before any I/O.
            async with source_http.async_client(headers=headers, timeout=timeout) as client:
                response = await client.request(method, url, data=data, retry_safe=method.upper() == "POST")
                response.raise_for_status()
                self.last_error = None
                return response.text
        except VerificationRequired as exc:
            self.last_error = str(exc)
            raise
        except Exception as exc:
            self.last_error = str(exc)
            logger.warning("[container:%s] Échec requête %s: %s", self.name, url, exc)
            raise

    # -------------------------------------------------------------------------
    # Recherche
    # -------------------------------------------------------------------------

    async def search_anime(self, query: str) -> List[AnimeResult]:
        clean_q = query.strip()
        if not clean_q or not self.base_url:
            return []

        if self.recipe.runtime.get('catalogue') or self.recipe.runtime.get('search'):
            return await self.data_runtime.search(clean_q)

        return await self._search_anime_html(clean_q)

    async def _search_anime_html(self, clean_q: str) -> List[AnimeResult]:
        logger.info("[container:%s] Recherche: '%s'", self.name, clean_q)
        results: List[AnimeResult] = []

        method = self.recipe.search_method or "GET"
        post_data = None
        if method == "POST":
            target_url = urljoin(self.base_url, self.recipe.search_request_path or "/index.php?do=search")
            post_data = {
                "do": "search",
                "subaction": "search",
                "search_start": "1",
                "story": clean_q,
                "full_search": "0",
                "result_from": "1",
                **{k: v.replace("{query}", clean_q) for k, v in self.recipe.search_post_params.items()},
                self.recipe.search_query_param or "story": clean_q,
            }
        else:
            path_tmpl = self.recipe.search_request_path or f"/?{self.recipe.search_query_param or 's'}={{query}}"
            if "{query}" in path_tmpl:
                rel_path = path_tmpl.replace("{query}", quote_plus(clean_q))
            else:
                sep = "&" if "?" in path_tmpl else "?"
                param = self.recipe.search_query_param or "s"
                rel_path = f"{path_tmpl}{sep}{param}={quote_plus(clean_q)}"
            target_url = urljoin(self.base_url, rel_path)

        html = await self._fetch_html(target_url, method=method, data=post_data)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        selector = self.recipe.search_selector or self.recipe.popular_selector or ".search-result, .movie-poster, .anime-card, article, .item"
        items = _safe_select(soup, selector)

        # Si le sélecteur strict n'a rien trouvé, repli heuristique étendu
        if not items:
            fallbacks = [
                "#list_catalog > div", "#list_catalog > div a", ".catalog-card",
                "#containerAjoutsAnimes > div", "div.ml-item", ".film_list article",
                "div#archive-content > article", ".search-page .result-item",
                ".c-tabs-item__content", "div.movie-poster", ".search-result",
                "article", ".short-story", ".item"
            ]
            for fallback_sel in fallbacks:
                items = _safe_select(soup, fallback_sel)
                if items:
                    break

        seen_hrefs = set()
        for it in items[:30]:
            link_el = _safe_select_one(it, self.recipe.item_link_selector or "a[href]") or (it if it.name == "a" else None)
            if not link_el or not link_el.get("href"):
                continue

            href = urljoin(self.base_url, link_el.get("href"))
            if any(part in href for part in self.recipe.runtime.get("exclude_urls", [])):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)

            img_el = _safe_select_one(it, self.recipe.item_thumb_selector or "img[src], img[data-src], img")
            img_url = ""
            if img_el:
                raw_img = img_el.get("src") or img_el.get("data-src") or img_el.get("data-lazy-src", "")
                if raw_img:
                    img_url = urljoin(self.base_url, raw_img)

            title = _item_title(it, link_el, self.recipe.item_title_selector or
                                'h2, h3, .title, .movie-title, .card-title', img_el)

            if title:
                results.append(
                    AnimeResult(
                        id=str(hash(href))[-8:],
                        title=title,
                        imageUrl=img_url,
                        url=href,
                        version="VF" if "/vf/" in href else "VOSTFR" if "/vostfr/" in href else self.lang.upper(),
                        type="Anime",
                        episodeInfo=self.name,
                        source=self.source_id,
                    )
                )

        logger.info("[container:%s] Trouvé %d résultat(s)", self.name, len(results))
        return await self.data_runtime.expand_listing(results)

    # -------------------------------------------------------------------------
    # Dernières sorties
    # -------------------------------------------------------------------------

    async def get_latest_releases(self) -> List[AnimeResult]:
        if not self.base_url:
            return []

        if self.recipe.runtime.get('catalogue'):
            from animelab.services.source_catalogue import source_catalogue
            return (await source_catalogue.api_catalogue(self, order=self.recipe.runtime['catalogue']['latest_order']))[:24]

        return await self._latest_html()

    def _parse_list_items(self, items: List[Any], info_label: str = "Récents", limit: int = 24) -> List[AnimeResult]:
        results: List[AnimeResult] = []
        seen_hrefs = set()
        for it in items[:limit]:
            link_el = _safe_select_one(it, self.recipe.item_link_selector or "a[href]") or (it if it.name == "a" else None)
            if not link_el or not link_el.get("href"):
                continue
            href = urljoin(self.base_url, link_el.get("href"))
            if any(part in href for part in self.recipe.runtime.get("exclude_urls", [])):
                continue
            if href in seen_hrefs:
                continue
            seen_hrefs.add(href)
            img_el = _safe_select_one(it, self.recipe.item_thumb_selector or "img[src], img[data-src]")
            title = _item_title(it, link_el, self.recipe.item_title_selector or
                                'h2, h3, .title, .movie-title', img_el)
            img_url = urljoin(self.base_url, img_el.get("data-src") or img_el.get("data-lazy-src") or img_el.get("src", "")) if img_el else ""

            if title:
                results.append(
                    AnimeResult(
                        id=str(hash(href))[-8:],
                        title=title,
                        imageUrl=img_url,
                        url=href,
                        version="VF" if "/vf/" in href else "VOSTFR" if "/vostfr/" in href else self.lang.upper(),
                        type="Anime",
                        episodeInfo=info_label,
                        source=self.source_id,
                    )
                )
        return results

    async def _latest_html(self) -> List[AnimeResult]:
        rel_path = self.recipe.latest_request_path or self.recipe.popular_request_path or "/"
        target_url = urljoin(self.base_url, rel_path.replace("{page}", "1"))
        html = await self._fetch_html(target_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        selector = self.recipe.latest_selector or self.recipe.popular_selector or ".movie-poster, .c-tabs-item__content, article"
        items = _safe_select(soup, selector)
        if not items and html.strip() and not re.search(r'(?i)no (?:results|anime)|aucun (?:résultat|anime)', soup.get_text(' ', strip=True)):
            raise SelectorMismatch('Expected catalogue elements were not found')

        return await self.data_runtime.expand_listing(self._parse_list_items(items, info_label="Récents", limit=18))

    # -------------------------------------------------------------------------
    # Séries populaires & Recettes spécifiques à la source
    # -------------------------------------------------------------------------

    async def get_popular_anime(self, page: int = 1) -> List[AnimeResult]:
        if not self.base_url:
            return []

        if self.recipe.runtime.get('catalogue'):
            from animelab.services.source_catalogue import source_catalogue
            items = await source_catalogue.api_catalogue(self, order=self.recipe.runtime['catalogue']['popular_order'])
            return items[(page-1)*24:page*24]

        return await self._popular_html(page=page)

    async def _popular_html(self, page: int = 1) -> List[AnimeResult]:
        rel_path = (self.recipe.popular_request_path or self.recipe.latest_request_path or "/").replace("{page}", str(page))
        target_url = urljoin(self.base_url, rel_path)
        html = await self._fetch_html(target_url)
        if not html:
            return []

        soup = BeautifulSoup(html, "html.parser")
        selector = self.recipe.popular_selector or self.recipe.latest_selector or ".movie-poster, .c-tabs-item__content, article"
        items = _safe_select(soup, selector)
        if not items and html.strip() and not re.search(r'(?i)no (?:results|anime)|aucun (?:résultat|anime)', soup.get_text(' ', strip=True)):
            raise SelectorMismatch('Expected popular catalogue elements were not found')

        return await self.data_runtime.expand_listing(self._parse_list_items(items, info_label="Populaires", limit=24))

    async def get_custom_feed(self, feed_id: str, page: int = 1) -> List[AnimeResult]:
        if not self.base_url:
            return []

        return await self._custom_feed_html(feed_id, page=page)

    async def _custom_feed_html(self, feed_id: str, page: int = 1) -> List[AnimeResult]:
        feed = next((f for f in (self.recipe.custom_feeds or []) if f.get("id") == feed_id), None)
        if not feed:
            return await self.get_popular_anime(page=page)
        rel_path = (feed.get("path") or "/").replace("{page}", str(page))
        target_url = urljoin(self.base_url, rel_path)
        html = await self._fetch_html(target_url)
        if not html:
            return []
        soup = BeautifulSoup(html, "html.parser")
        selector = feed.get("selector") or self.recipe.popular_selector or self.recipe.latest_selector or "article"
        items = _safe_select(soup, selector)
        return await self.data_runtime.expand_listing(self._parse_list_items(items, info_label=feed.get("label") or feed_id, limit=24))

    # -------------------------------------------------------------------------
    # Détails & Épisodes
    # -------------------------------------------------------------------------

    async def get_anime_detail(self, anime_url: str) -> Optional[AnimeDetail]:
        if not is_safe_url(anime_url):
            return None

        if self.recipe.runtime.get('catalogue'):
            return await self.data_runtime.detail(anime_url)
        if self.recipe.runtime.get('listing_expansion'):
            section = await self.data_runtime.section_detail(anime_url)
            if section is not None:
                return section

        html = await self._fetch_html(anime_url)
        if not html:
            return None

        soup = BeautifulSoup(html, "html.parser")

        # Titre
        title_el = _safe_select_one(soup, self.recipe.details_title_selector or "h1.title, h1.entry-title, h1, .movie-title")
        title = title_el.get_text().strip() if title_el else (soup.title.string if soup.title else self.name)

        # Synopsis
        syn_el = _safe_select_one(soup, self.recipe.details_synopsis_selector or ".synopsis, .description, .entry-content p, #dle-content .full-text")
        synopsis = (syn_el.get("data-full-description") or syn_el.get_text().strip()) if syn_el else ""

        # Affiche
        img_el = _safe_select_one(soup, self.recipe.details_thumb_selector or ".poster img, .fposter img, meta[property='og:image']")
        img_url = ""
        if img_el:
            img_src = img_el.get("content") if img_el.name == "meta" else (img_el.get("src") or img_el.get("data-src"))
            if img_src:
                img_url = urljoin(self.base_url, img_src)

        # Genres
        genres = [g.get_text().strip() for g in _safe_select(soup, self.recipe.details_genre_selector or ".genre a, .genres a, a[href*='/genre/']") if g.get_text().strip()]

        # Épisodes
        episodes: List[Episode] = []
        ep_selector = self.recipe.episode_list_selector or "li.wp-manga-chapter, select.new_player_selector option, .episodes a, a[href*='episode']"
        ep_items = _safe_select(soup, ep_selector)

        ep_idx = 1
        for ep_el in ep_items:
            href = ""
            ep_title = ep_el.get_text().strip()
            if ep_el.name == "option":
                val = ep_el.get("value") or ""
                # Si option a une url ou un index d'épisode
                if val.startswith("http") or val.startswith("/"):
                    href = urljoin(self.base_url, val)
                elif "vostfree" in self.pkg:
                    match = re.search(r"\d+", ep_title)
                    if not match and ep_title.casefold() != "film":
                        continue
                    from urllib.parse import urlencode, parse_qsl, urlunparse
                    parsed = urlparse(anime_url)
                    params = dict(parse_qsl(parsed.query))
                    params["episode"] = match.group(0) if match else "1"
                    href = urlunparse(parsed._replace(query=urlencode(params)))
                else:
                    continue
            else:
                a_tag = ep_el if ep_el.name == "a" else ep_el.select_one("a[href]")
                if a_tag and a_tag.get("href"):
                    href = urljoin(anime_url, a_tag.get("href"))

            if not href:
                continue

            # Numéro d'épisode extrait par regex
            num_match = re.search(r"(?:ep|épisode|episode|ch)[\s\-_]*(\d+)", ep_title + " " + href, re.IGNORECASE)
            ep_num = int(num_match.group(1)) if num_match else ep_idx

            episodes.append(
                Episode(
                    number=ep_num,
                    title=ep_title or f"Épisode {ep_num}",
                    version="VF" if re.search(r"(?<![a-z])vf(?![a-z])", anime_url + " " + title, re.I) else "VOSTFR",
                    downloadPageUrl=href,
                    playerUrl=href,
                    thumbnailUrl=img_url,
                )
            )
            ep_idx += 1

        episodes.sort(key=lambda ep: ep.number)

        version = "VF" if re.search(r"(?<![a-z])vf(?![a-z])", anime_url + " " + title, re.I) else "VOSTFR"
        interpreted = await self.data_runtime.episodes(anime_url, soup, version)
        if interpreted is not None:
            episodes = interpreted

        return AnimeDetail(
            id=str(hash(anime_url))[-8:],
            title=title,
            imageUrl=img_url,
            synopsis=synopsis,
            genres=genres[:6],
            episodes=episodes,
            source=self.source_id,
            url=anime_url,
            version=version,
        )

    # -------------------------------------------------------------------------
    # Sources Vidéo & Hébergeurs
    # -------------------------------------------------------------------------

    async def get_episode_sources(self, play_url: str) -> List[Dict[str, Any]]:
        if not is_safe_url(play_url):
            return []

        from urllib.parse import parse_qs, unquote_plus
        fragment = parse_qs(urlparse(play_url).fragment)
        if 'players' in fragment or 'servers' in fragment:
            raw = fragment.get('players', fragment.get('servers'))[0]
            players = json.loads(raw)
            links = players.values() if isinstance(players, dict) else players
            if not isinstance(players, (dict, list)) or len(players) > 100:
                raise ValueError('Invalid recipe player list')
            results = []
            for link in links:
                if not isinstance(link, str) or not is_safe_url(link):
                    continue
                extractor = extractor_registry.find_extractor(link)
                results.append(self.data_runtime.stream(link, extractor.name if extractor else 'Player'))
            return results
        interpreted = await self.data_runtime.players(play_url)
        if interpreted is not None:
            return interpreted

        # 2. Si l'URL de lecture est déjà un lien d'intégration vidéo direct via le hub d'extracteurs
        matched_ext = extractor_registry.find_extractor(play_url)
        if matched_ext:
            return [{
                "name": f"{self.name} - {matched_ext.name}",
                "server": matched_ext.name,
                "url": play_url,
                "quality": "HD",
                "format": "embed",
            }]

        html = await self._fetch_html(play_url)
        if not html:
            return []

        sources: List[Dict[str, Any]] = []

        # 1. Détection des balises iframe vidéo
        regex = self.recipe.video_iframe_regex or r'<iframe[^>]*\ssrc=["\']([^"\']+)["\']'
        iframes = re.findall(regex, html, re.IGNORECASE)
        soup = BeautifulSoup(html, "html.parser")
        iframes.extend(tag.get("src") or tag.get("data-src") for tag in soup.select("iframe[src], iframe[data-src]"))
        for player in soup.select("#playeroptionsul li[data-post][data-nume]"):
            if player.get("data-nume") == "trailer":
                continue
            from urllib.parse import urlencode
            endpoint = urljoin(self.base_url, f"/wp-json/dooplayer/v1/post/{player['data-post']}")
            payload = await self._fetch_html(endpoint + "?" + urlencode({"type": player.get("data-type", "tv"), "source": player["data-nume"]}))
            try:
                embed = json.loads(payload).get("embed_url", "")
                if embed.startswith("<"):
                    tag = BeautifulSoup(embed, "html.parser").find("iframe")
                    embed = tag.get("src", "") if tag else ""
                if embed:
                    iframes.append(embed)
            except (ValueError, AttributeError):
                pass

        if "vostfree" in self.pkg:
            from urllib.parse import parse_qs
            number = parse_qs(urlparse(play_url).query).get("episode", ["1"])[0]
            prefixes = {"ok": "https://ok.ru/videoembed/", "sibnet": "https://video.sibnet.ru/shell.php?videoid=", "uqload": "https://uqload.io/embed-"}
            for button in soup.select(f"div[id='buttons_{number}'] div[id]"):
                content = soup.find("div", id="content_" + button["id"])
                if not content:
                    continue
                link = content.get_text(strip=True)
                name = button.get_text(strip=True).lower()
                if link and not link.startswith(("http://", "https://")):
                    link = prefixes.get(name, "") + link + (".html" if name == "uqload" else "")
                if link.startswith(("http://", "https://")):
                    iframes.append(link)
        if "animevostfr" in self.pkg:
            from urllib.parse import parse_qs, urlencode
            shortlink = soup.select_one('link[rel="shortlink"]')
            film_id = parse_qs(urlparse(shortlink.get("href", "") if shortlink else "").query).get("p", [""])[0]
            if film_id:
                for server in soup.select(".list-server select option[value]"):
                    endpoint = urljoin(self.base_url, "/ajax-get-link-stream/") + "?" + urlencode({"server": server["value"], "filmId": film_id})
                    raw = await self._fetch_html(endpoint)
                    try:
                        raw = json.loads(raw)
                    except ValueError:
                        raw = raw.strip()
                    if isinstance(raw, str) and raw.startswith(("http://", "https://")):
                        iframes.append(raw)

        # 2. Détection d'hébergeurs courants (Vidmoly, Streamtape, Uqload, Sendvid, Sibnet, Voe, etc.)
        for iframe_url in set(iframes):
            if iframe_url.startswith("//"):
                iframe_url = "https:" + iframe_url
            elif not iframe_url.startswith("http"):
                iframe_url = urljoin(play_url, iframe_url)

            # Identification du nom de l'hébergeur
            matched_ext = extractor_registry.find_extractor(iframe_url)
            if matched_ext:
                host_name = matched_ext.name
            else:
                host_name = "Lecteur Externe"
                i_domain = urlparse(iframe_url).netloc.lower()
                for k_domain, s_name in KNOWN_EMBED_HOSTS.items():
                    if k_domain in i_domain:
                        host_name = s_name
                        break
                else:
                    host_name = i_domain.replace("www.", "").split(".")[0].capitalize()

            sources.append({
                "name": f"{self.name} - {host_name}",
                "server": host_name,
                "url": iframe_url,
                "quality": "HD",
                "format": "iframe",
            })

        # 3. Si aucun iframe trouvé mais que la page contient des flux vidéo / sources directs
        if not sources:
            m_m3u8 = re.findall(r'sources:\s*\[\s*\{\s*file:\s*["\']([^"\']+)["\']', html) or re.findall(r'file:\s*["\'](https?://[^"\']+\.m3u8[^"\']*)["\']', html)
            for m_url in set(m_m3u8):
                sources.append({
                    "name": f"{self.name} - HLS",
                    "server": "HLS",
                    "url": m_url,
                    "quality": "HD",
                    "format": "hls",
                })
            m_mp4 = re.findall(r'<video[^>]*src=["\']([^"\']+\.mp4[^"\']*)["\']', html) or re.findall(r'<source[^>]*src=["\']([^"\']+\.mp4[^"\']*)["\']', html)
            for mp4_url in set(m_mp4):
                full_mp4 = urljoin(play_url, mp4_url)
                sources.append({
                    "name": f"{self.name} - MP4",
                    "server": "Direct",
                    "url": full_mp4,
                    "quality": "HD",
                    "format": "mp4",
                })

        return sources
