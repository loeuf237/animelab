import logging
import re
import unicodedata
from typing import Optional, Dict, Any
from urllib.parse import quote_plus

import httpx

from animelab.config import settings
from animelab.models.anime import AnimeDetail, Episode
from animelab.services.proxy_service import proxy_service

logger = logging.getLogger("animelab.tmdb")

TMDB_BASE_URL = "https://api.themoviedb.org/3"
TMDB_IMAGE_BASE = "https://image.tmdb.org/t/p"

GENERIC_EP_REGEX = re.compile(r"(?i)^(Episode|Épisode)\s*\d+$|^第\d+[話回]$|^\d+$")
SEASON_REGEX = re.compile(r"(?i)(?:Saison|Season)\s*(\d+)")

class TmdbService:
    def __init__(self):
        self._cache: Dict[str, Any] = {}

    @property
    def api_key(self) -> str:
        return settings.TMDB_API_KEY

    @property
    def is_enabled(self) -> bool:
        return bool(settings.TMDB_ENABLED and self.api_key)

    def sanitize_title(self, title: str) -> str:
        """Nettoie le titre d'un anime pour optimiser la recherche TMDB."""
        if not title:
            return ""
        t = re.sub(r"(?i)\((TV|Films?|OAVs?|ONAs?|Specials?|VF|VOSTFR|VF\+VOSTFR|VF\s*/\s*VOSTFR|VOST|UNCUT)\)", "", title)
        t = re.sub(r"(?i)\s*(?:Saison|Season|Part(?:ie)?)\s*\d+.*", "", t)
        t = re.sub(r"\s+-\s+.*$", "", t)
        t = re.sub(r"\s+\d+$", "", t)
        t = re.sub(r"\s+", " ", t).strip(" -:;,")
        return t

    def extract_season_number(self, title: str) -> int:
        """Extrait le numéro de saison depuis le titre (ex: 'Saison 2' -> 2)."""
        m = SEASON_REGEX.search(title)
        if m:
            try:
                return int(m.group(1))
            except ValueError:
                pass
        return 1

    def calculate_similarity(self, query: str, candidate: str) -> int:
        """Calcule un score de similarité (0-100) pour filtrer les faux positifs."""
        def normalize(s: str) -> str:
            n = unicodedata.normalize("NFD", s.lower())
            n = "".join(c for c in n if unicodedata.category(c) != "Mn")
            n = re.sub(r"[^\w\s]", "", n)
            return re.sub(r"\s+", " ", n).strip()

        s1 = normalize(query)
        s2 = normalize(candidate)
        if not s1 or not s2:
            return 0
        if s1 == s2:
            return 100
        if s1.replace(" ", "") == s2.replace(" ", ""):
            return 95
        if s1 in s2 or s2 in s1:
            longer = max(len(s1), len(s2))
            shorter = min(len(s1), len(s2))
            ratio = shorter / longer if longer > 0 else 0
            return int(65 + ratio * 30)

        w1 = [w for w in s1.split() if len(w) >= 2]
        w2 = [w for w in s2.split() if len(w) >= 2]
        if not w1 or not w2:
            return 0
        matches = sum(1 for w in w1 if any(w == cw for cw in w2))
        return int((matches / max(len(w1), len(w2))) * 70)

    async def search_anime(self, title: str, client: httpx.AsyncClient) -> Optional[Dict[str, Any]]:
        """Recherche l'anime sur TMDB."""
        clean = self.sanitize_title(title)
        if not clean:
            return None

        cache_key = f"search:{clean.lower()}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        url = f"{TMDB_BASE_URL}/search/multi?api_key={self.api_key}&query={quote_plus(clean)}&language=fr-FR"
        try:
            resp = await client.get(url, timeout=3.5)
            if resp.status_code != 200:
                return None
            data = resp.json()
            results = data.get("results", [])
            if not results:
                return None

            best_candidate = None
            best_score = -1

            for item in results:
                media_type = item.get("media_type", "")
                if media_type not in ["tv", "movie"]:
                    continue
                cand_title = item.get("name") or item.get("title") or item.get("original_name") or ""
                orig_title = item.get("original_name") or item.get("original_title") or ""
                score = max(self.calculate_similarity(clean, cand_title), self.calculate_similarity(clean, orig_title))
                if score > best_score and score >= 45:
                    best_score = score
                    best_candidate = item

            self._cache[cache_key] = best_candidate
            return best_candidate
        except Exception as e:
            logger.debug("Erreur recherche TMDB pour '%s': %s", clean, e)
            return None

    async def get_season_episodes(
        self, tv_id: int, season_num: int, client: httpx.AsyncClient
    ) -> Dict[int, Dict[str, Optional[str]]]:
        """Récupère les métadonnées de chaque épisode de la saison (titre, image, résumé)."""
        cache_key = f"season:{tv_id}:{season_num}"
        if cache_key in self._cache:
            return self._cache[cache_key]

        ep_map: Dict[int, Dict[str, Optional[str]]] = {}
        fr_url = f"{TMDB_BASE_URL}/tv/{tv_id}/season/{season_num}?api_key={self.api_key}&language=fr-FR"

        try:
            resp = await client.get(fr_url, timeout=3.5)
            if resp.status_code == 200:
                fr_data = resp.json()
                episodes = fr_data.get("episodes", [])
                for ep in episodes:
                    num = ep.get("episode_number")
                    if num is None:
                        continue
                    name = (ep.get("name") or "").strip()
                    overview = (ep.get("overview") or "").strip()
                    still_path = ep.get("still_path")
                    still_url = f"{TMDB_IMAGE_BASE}/w500{still_path}" if still_path else None

                    ep_map[num] = {
                        "title": name if name and not GENERIC_EP_REGEX.match(name) else None,
                        "synopsis": overview if overview else None,
                        "thumbnail": still_url,
                    }

            # Si des titres ou résumés manquent en français, repli sur l'anglais
            needs_en = any(not info["title"] or not info["synopsis"] for info in ep_map.values())
            if needs_en or not ep_map:
                en_url = f"{TMDB_BASE_URL}/tv/{tv_id}/season/{season_num}?api_key={self.api_key}&language=en-US"
                en_resp = await client.get(en_url, timeout=3.0)
                if en_resp.status_code == 200:
                    en_data = en_resp.json()
                    for ep in en_data.get("episodes", []):
                        num = ep.get("episode_number")
                        if num is None:
                            continue
                        name = (ep.get("name") or "").strip()
                        overview = (ep.get("overview") or "").strip()
                        still_path = ep.get("still_path")
                        still_url = f"{TMDB_IMAGE_BASE}/w500{still_path}" if still_path else None

                        curr = ep_map.setdefault(num, {"title": None, "synopsis": None, "thumbnail": None})
                        if not curr["title"] and name and not GENERIC_EP_REGEX.match(name):
                            curr["title"] = name
                        if not curr["synopsis"] and overview:
                            curr["synopsis"] = overview
                        if not curr["thumbnail"] and still_url:
                            curr["thumbnail"] = still_url

        except Exception as e:
            logger.debug("Erreur récupération saison TMDB (tv_id=%d, s=%d): %s", tv_id, season_num, e)

        self._cache[cache_key] = ep_map
        return ep_map

    async def enrich_anime_detail(self, detail: AnimeDetail) -> AnimeDetail:
        """Enrichit un AnimeDetail avec les métadonnées TMDB (non-bloquant et tolérant aux pannes)."""
        if not self.is_enabled or not detail:
            return detail

        try:
            async with httpx.AsyncClient(headers={"User-Agent": "Animan/2.0"}, verify=settings.SSL_VERIFY, proxy=proxy_service.get_active_proxy()) as client:
                candidate = await self.search_anime(detail.title, client)
                if not candidate:
                    return detail

                detail.tmdbId = candidate.get("id")
                tmdb_overview = (candidate.get("overview") or "").strip()
                if tmdb_overview and (not detail.synopsis or len(detail.synopsis) < 40):
                    detail.synopsis = tmdb_overview

                backdrop = candidate.get("backdrop_path")
                if backdrop and not detail.bannerUrl:
                    detail.bannerUrl = f"{TMDB_IMAGE_BASE}/original{backdrop}"

                poster = candidate.get("poster_path")
                if poster and not detail.imageUrl:
                    detail.imageUrl = f"{TMDB_IMAGE_BASE}/w500{poster}"

                air_date = candidate.get("first_air_date") or candidate.get("release_date")
                if air_date and not detail.releaseDate:
                    detail.releaseDate = air_date

                media_type = candidate.get("media_type", "tv")
                if media_type == "tv" and detail.episodes:
                    season_num = self.extract_season_number(detail.title)
                    ep_meta = await self.get_season_episodes(candidate["id"], season_num, client)
                    if ep_meta:
                        for ep in detail.episodes:
                            meta = ep_meta.get(ep.number)
                            if meta:
                                if meta.get("title"):
                                    ep.title = f"Épisode {ep.number} - {meta['title']}"
                                if meta.get("synopsis") and not ep.synopsis:
                                    ep.synopsis = meta["synopsis"]
                                if meta.get("thumbnail") and not ep.thumbnailUrl:
                                    ep.thumbnailUrl = meta["thumbnail"]

        except Exception as e:
            logger.warning("Échec de l'enrichissement TMDB pour '%s': %s", detail.title, e)

        return detail

tmdb_service = TmdbService()
