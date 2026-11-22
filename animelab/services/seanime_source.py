"""SourceProvider adapter wrapping an installed Seanime streaming extension."""

from __future__ import annotations

import asyncio
from collections import OrderedDict
import contextvars
import logging
import re
import time
from typing import Any, Callable
from urllib.parse import quote, unquote, urlparse

from animelab.models.anime import AnimeDetail, AnimeResult, Episode
from animelab.security import is_safe_url_async
from animelab.services.extension_references import NativeReferences
from animelab.services.media_contracts import normalize_tracks
from animelab.services.seanime_runtime import SeanimeRuntimeError
from animelab.services.source_http import VerificationRequired, source_http

logger = logging.getLogger(__name__)

_SYNTHETIC_HOST = "seanime.local"
_USES_MEDIA_RE = re.compile(
    r"\bmedia\s*\.\s*(?:id|idMal|startDate|synonyms|episodeCount|englishTitle|romajiTitle)\b"
)
_NO_RESULTS_RE = re.compile(
    r"(?i)\b(?:no\s+(?:results?|anime|matches?|items?)\s+found|nothing\s+found|aucun\s+r[ée]sultat)\b"
)
_ANILIST_URL = "https://graphql.anilist.co"
_ANILIST_QUERY = """
query ($search: String) {
  Media(search: $search, type: ANIME) {
    id
    idMal
    status
    format
    episodes
    isAdult
    title {
      romaji
      english
    }
    synonyms
    startDate {
      year
      month
      day
    }
  }
}
"""
_ANILIST_CACHE: OrderedDict[str, tuple[float, dict[str, Any] | None]] = OrderedDict()
_ANILIST_CACHE_TTL = 3600.0
_ANILIST_CACHE_MAX = 128
_DIAGNOSE_LOG_SINK: contextvars.ContextVar[list[str] | None] = contextvars.ContextVar(
    "_seanime_diagnose_logs", default=None
)


async def _lookup_anilist_media(query: str) -> dict[str, Any] | None:
    """Fetch basic AniList media metadata for extensions requiring AniList/MAL IDs."""
    key = (query or "").strip().lower()
    if not key:
        return None
    now = time.monotonic()
    cached = _ANILIST_CACHE.get(key)
    if cached is not None:
        ts, data = cached
        if (now - ts) < _ANILIST_CACHE_TTL:
            _ANILIST_CACHE.move_to_end(key)
            return dict(data) if data is not None else None
        _ANILIST_CACHE.pop(key, None)

    try:
        async with source_http.async_client(timeout=2.5) as client:
            resp = await client.request(
                "POST",
                _ANILIST_URL,
                headers={"Content-Type": "application/json", "Accept": "application/json"},
                json={"query": _ANILIST_QUERY, "variables": {"search": query.strip()}},
            )
        if resp.status_code != 200:
            return None
        payload = resp.json()
        media = payload.get("data", {}).get("Media") if isinstance(payload, dict) else None
        if not isinstance(media, dict):
            parsed: dict[str, Any] | None = None
        else:
            title_obj = media.get("title") if isinstance(media.get("title"), dict) else {}
            start_obj = media.get("startDate") if isinstance(media.get("startDate"), dict) else {}
            parsed = {
                "id": int(media.get("id") or 0),
                "idMal": int(media.get("idMal") or 0),
                "status": str(media.get("status") or "RELEASING"),
                "format": str(media.get("format") or "TV"),
                "englishTitle": str(
                    title_obj.get("english") or title_obj.get("romaji") or query.strip()
                ),
                "romajiTitle": str(
                    title_obj.get("romaji") or title_obj.get("english") or query.strip()
                ),
                "synonyms": [str(s) for s in (media.get("synonyms") or []) if isinstance(s, str) and s],
                "isAdult": bool(media.get("isAdult", False)),
                "episodeCount": int(media.get("episodes") or 0),
                "startDate": {
                    "year": int(start_obj.get("year") or 0),
                    "month": int(start_obj.get("month") or 1),
                    "day": int(start_obj.get("day") or 1),
                },
            }
        _ANILIST_CACHE[key] = (now, parsed)
        _ANILIST_CACHE.move_to_end(key)
        while len(_ANILIST_CACHE) > _ANILIST_CACHE_MAX:
            _ANILIST_CACHE.popitem(last=False)
        return dict(parsed) if parsed is not None else None
    except Exception as exc:
        logger.debug("Optional AniList lookup skipped for %r: %s", query, exc)
        return None


def _normalize_sub_or_dub(raw: Any) -> str:
    val = str(raw or "").strip().lower()
    if val in ("dub", "vf", "french-dub"):
        return "VF"
    if val == "both":
        return "VOSTFR / VF"
    return "VOSTFR"


def _parse_episode_number(raw: Any, fallback: int) -> int:
    if isinstance(raw, bool):
        return fallback
    if isinstance(raw, (int, float)):
        return max(0, int(raw))
    text = str(raw or "").strip()
    if text:
        m = re.search(r"\d+", text)
        if m:
            try:
                return max(0, int(m.group(0)))
            except ValueError:
                pass
    return fallback


class SeanimeSource:
    """Adapter exposing a Seanime ``onlinestream-provider`` as an AnimeLab source."""

    runtime = "seanime"
    supports_latest = False
    supports_popular = False

    def __init__(
        self,
        *,
        db_path: str,
        extension_id: str,
        name: str,
        lang: str = "en",
        icon: str = "",
        base_url: str = "",
        version: str = "1.0.0",
        runtime_backend: Any,
        state_loader: Callable[[str], dict[str, Any]],
        store_saver: Callable[[str, dict[str, Any]], None],
    ) -> None:
        self.db_path = db_path
        self.extension_id = extension_id
        self.source_id = f"seanime:{extension_id}".lower()
        self.id = self.source_id
        self.pkg = self.source_id
        self.name = name
        self.lang = lang or "en"
        self.icon = icon or ""
        self.base_url = base_url or f"https://{_SYNTHETIC_HOST}/{extension_id}"
        self.version = version or "1.0.0"
        self.supports_dub = False
        self.episode_servers: list[str] = ["default"]
        self._runtime = runtime_backend
        self._state_loader = state_loader
        self._store_saver = store_saver
        self.references = NativeReferences(db_path, self.source_id)

    def _synthetic_anime_url(self, item_id: str) -> str:
        return f"https://{_SYNTHETIC_HOST}/{self.extension_id}/anime/{quote(item_id, safe='')}"

    def _synthetic_episode_url(self, ep_id: str) -> str:
        return f"https://{_SYNTHETIC_HOST}/{self.extension_id}/episode/{quote(ep_id, safe='')}"

    def has_reference(self, url: str) -> bool:
        """Return True if *url* belongs to a known reference or synthetic Seanime URI."""
        if not url:
            return False
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() == _SYNTHETIC_HOST and parsed.path.startswith(
            f"/{self.extension_id}/"
        ):
            return True
        return bool(
            self.references.get("anime", url) is not None
            or self.references.get("episode", url) is not None
        )

    def _extract_id_from_synthetic(self, url: str, kind: str) -> str | None:
        prefix = f"/{self.extension_id}/{kind}/"
        parsed = urlparse(url)
        if (parsed.hostname or "").lower() == _SYNTHETIC_HOST and parsed.path.startswith(prefix):
            return unquote(parsed.path[len(prefix):])
        return None

    async def _invoke(
        self,
        method: str,
        args: list[Any] | None = None,
        *,
        timeout: float = 30.0,
    ) -> tuple[Any, list[str]]:
        state = self._state_loader(self.extension_id)
        if not state or not state.get("payload"):
            raise RuntimeError(f"Extension Seanime '{self.extension_id}' introuvable ou non installée.")

        sink = _DIAGNOSE_LOG_SINK.get()
        try:
            result, new_store, logs = await self._runtime.invoke(
                extension_id=self.extension_id,
                source=str(state["payload"]),
                language=str(state.get("language") or "javascript"),
                method=method,
                args=args or [],
                user_config=dict(state.get("saved_config") or {}),
                defaults=dict(state.get("defaults") or {}),
                store=dict(state.get("store") or {}),
                timeout=timeout,
            )
        except SeanimeRuntimeError as exc:
            if sink is not None and exc.logs:
                sink.extend(exc.logs)
            raise
        if sink is not None and logs:
            sink.extend(logs)
        try:
            self._store_saver(self.extension_id, new_store)
        except Exception as exc:
            logger.debug("Failed to persist $store for %s: %s", self.extension_id, exc)
        return result, logs

    async def get_settings(self) -> dict[str, Any]:
        """Return provider ``getSettings()`` metadata and update cached server list."""
        raw, _ = await self._invoke("getSettings", [], timeout=15.0)
        if not isinstance(raw, dict):
            raw = {}
        servers = [
            str(s).strip()
            for s in (raw.get("episodeServers") or [])
            if isinstance(s, str) and s.strip()
        ]
        if not servers:
            servers = ["default"]
        self.episode_servers = servers
        self.supports_dub = bool(raw.get("supportsDub", False))
        return {"episodeServers": servers, "supportsDub": self.supports_dub}

    async def get_latest_releases(self) -> list[AnimeResult]:
        return []

    async def search_anime(
        self,
        query: str,
        *,
        dub: bool = False,
        year: int | None = None,
    ) -> list[AnimeResult]:
        cleaned = (query or "").strip()
        if not cleaned:
            return []

        media_payload: dict[str, Any] = {
            "id": 0,
            "idMal": 0,
            "status": "RELEASING",
            "format": "TV",
            "englishTitle": cleaned,
            "romajiTitle": cleaned,
            "synonyms": [],
            "isAdult": False,
            "episodeCount": 0,
            "startDate": {"year": int(year or 0), "month": 1, "day": 1},
        }
        effective_year = int(year) if year else 0
        state = self._state_loader(self.extension_id)
        payload = str((state or {}).get("payload") or "")
        backend = getattr(self._runtime, "backend", self._runtime)
        if getattr(backend, "_client_factory", None) is None and _USES_MEDIA_RE.search(payload):
            ani = await _lookup_anilist_media(cleaned)
            if ani:
                media_payload.update(
                    {
                        "id": ani.get("id", 0),
                        "idMal": ani.get("idMal", 0),
                        "status": ani.get("status") or media_payload["status"],
                        "format": ani.get("format") or media_payload["format"],
                        "englishTitle": ani.get("englishTitle") or cleaned,
                        "romajiTitle": ani.get("romajiTitle") or cleaned,
                        "synonyms": list(ani.get("synonyms") or []),
                        "isAdult": bool(ani.get("isAdult", False)),
                        "episodeCount": int(ani.get("episodeCount") or 0),
                        "startDate": dict(ani.get("startDate") or media_payload["startDate"]),
                    }
                )
                if not effective_year and int(media_payload["startDate"].get("year") or 0):
                    effective_year = int(media_payload["startDate"]["year"])

        opts: dict[str, Any] = {
            "media": media_payload,
            "query": cleaned,
            "dub": bool(dub),
            "year": effective_year,
        }
        try:
            raw, _ = await self._invoke("search", [opts], timeout=35.0)
        except SeanimeRuntimeError as exc:
            if _NO_RESULTS_RE.search(str(exc)):
                return []
            raise
        if not isinstance(raw, list):
            return []

        results: list[AnimeResult] = []
        refs: list[tuple[str, str, dict[str, Any]]] = []
        seen_urls: set[str] = set()

        for item in raw:
            if not isinstance(item, dict):
                continue
            item_id = str(item.get("id") or "").strip()
            title = str(item.get("title") or item_id).strip()
            if not item_id and not title:
                continue
            if not item_id:
                item_id = title

            raw_url = str(item.get("url") or "").strip()
            public_url = (
                raw_url
                if raw_url.startswith(("http://", "https://")) and raw_url not in seen_urls
                else self._synthetic_anime_url(item_id)
            )
            if public_url in seen_urls:
                public_url = self._synthetic_anime_url(f"{item_id}-{len(seen_urls)}")
            seen_urls.add(public_url)

            image = str(
                item.get("image")
                or item.get("coverImage")
                or item.get("poster")
                or ""
            ).strip()
            version = _normalize_sub_or_dub(item.get("subOrDub"))

            ref_meta = dict(item)
            ref_meta["id"] = item_id
            ref_meta["title"] = title
            ref_meta["url"] = raw_url or public_url
            ref_meta["image"] = image
            refs.append(("anime", public_url, ref_meta))

            results.append(
                AnimeResult(
                    id=item_id,
                    title=title,
                    imageUrl=image,
                    url=public_url,
                    version=version,
                    type="Anime",
                    source=self.source_id,
                )
            )

        if refs:
            self.references.remember_many(refs)
        return results

    async def get_anime_detail(self, anime_url: str) -> AnimeDetail:
        ref = self.references.get("anime", anime_url)
        anime_id = str(
            (ref or {}).get("id")
            or self._extract_id_from_synthetic(anime_url, "anime")
            or anime_url
        )
        title = str((ref or {}).get("title") or anime_id)
        image = str((ref or {}).get("image") or "")
        version = _normalize_sub_or_dub((ref or {}).get("subOrDub"))

        try:
            settings_info = await self.get_settings()
            servers = settings_info["episodeServers"]
        except Exception:
            servers = list(self.episode_servers)

        raw_eps, _ = await self._invoke("findEpisodes", [anime_id], timeout=35.0)
        if not isinstance(raw_eps, list):
            raw_eps = []

        episodes: list[Episode] = []
        ep_refs: list[tuple[str, str, dict[str, Any]]] = []
        seen_ep_urls: set[str] = set()

        for idx, ep in enumerate(raw_eps, start=1):
            if not isinstance(ep, dict):
                continue
            ep_id = str(ep.get("id") or "").strip()
            if not ep_id:
                continue
            ep_num = _parse_episode_number(ep.get("number"), idx)
            ep_title = str(ep.get("title") or "").strip() or f"Épisode {ep_num}"
            raw_ep_url = str(ep.get("url") or "").strip()

            use_raw = (
                raw_ep_url.startswith(("http://", "https://"))
                and raw_ep_url != anime_url
                and raw_ep_url not in seen_ep_urls
            )
            public_ep_url = raw_ep_url if use_raw else self._synthetic_episode_url(ep_id)
            if public_ep_url in seen_ep_urls:
                public_ep_url = self._synthetic_episode_url(f"{ep_id}#{idx}")
            seen_ep_urls.add(public_ep_url)

            ep_meta = dict(ep)
            ep_meta["id"] = ep_id
            ep_meta["number"] = ep.get("number", ep_num)
            ep_meta["title"] = ep_title
            ep_meta["url"] = raw_ep_url or public_ep_url
            ep_meta["anime_id"] = anime_id
            ep_meta["anime_url"] = anime_url
            ep_refs.append(("episode", public_ep_url, ep_meta))

            ep_thumb = str(ep.get("image") or ep.get("thumbnail") or "").strip() or None
            episodes.append(
                Episode(
                    number=ep_num,
                    title=ep_title,
                    playerUrl=public_ep_url,
                    downloadPageUrl=public_ep_url,
                    version=version,
                    thumbnailUrl=ep_thumb,
                    nativeMetadata={
                        "seanimeId": ep_id,
                        "rawNumber": ep.get("number", ep_num),
                        "servers": servers,
                    },
                )
            )

        if ep_refs:
            self.references.remember_many(ep_refs)

        return AnimeDetail(
            title=title,
            imageUrl=image,
            version=version,
            url=anime_url,
            episodes=episodes,
            source=self.source_id,
            nativeMetadata={
                "extensionId": self.extension_id,
                "episodeServers": servers,
                "supportsDub": self.supports_dub,
            },
        )

    async def get_episode_sources(
        self,
        episode_url: str,
        *,
        preferred_server: str | None = None,
        episode_payload: dict[str, Any] | None = None,
    ) -> list[dict[str, Any]]:
        ref = self.references.get("episode", episode_url) or episode_payload or {}
        ep_id = str(
            ref.get("id")
            or self._extract_id_from_synthetic(episode_url, "episode")
            or episode_url
        )
        ep_arg = {k: v for k, v in ref.items() if k not in ("anime_url", "anime_id")}
        ep_arg.setdefault("id", ep_id)
        ep_arg.setdefault("number", 1)
        ep_arg.setdefault("url", str(ref.get("url") or episode_url))
        ep_arg.setdefault("title", str(ref.get("title") or ""))

        try:
            settings_info = await self.get_settings()
            servers = list(settings_info["episodeServers"])
        except VerificationRequired:
            raise
        except Exception:
            servers = list(self.episode_servers or ["default"])

        if not servers:
            servers = ["default"]

        preferred_canonical: str | None = None
        if preferred_server and preferred_server.strip() and preferred_server.strip().lower() != "auto":
            pref = preferred_server.strip()
            matched = next((s for s in servers if s.lower() == pref.lower()), None)
            preferred_canonical = matched or pref
            remaining_servers = [s for s in servers if s.lower() != preferred_canonical.lower()]
        else:
            remaining_servers = list(servers)

        sem = asyncio.Semaphore(3)
        verification_exc: VerificationRequired | None = None
        last_error: Exception | None = None

        async def _query_server(server_name: str) -> list[dict[str, Any]]:
            nonlocal verification_exc, last_error
            async with sem:
                try:
                    data, _ = await self._invoke(
                        "findEpisodeServer",
                        [ep_arg, server_name],
                        timeout=25.0,
                    )
                except VerificationRequired as exc:
                    verification_exc = exc
                    return []
                except Exception as exc:
                    last_error = exc
                    logger.debug(
                        "Seanime %s findEpisodeServer(%s) failed: %s",
                        self.extension_id,
                        server_name,
                        exc,
                    )
                    return []

            if not isinstance(data, dict):
                return []
            srv_label = str(data.get("server") or server_name).strip() or server_name
            common_headers = {
                str(k): str(v)
                for k, v in (data.get("headers") or {}).items()
                if isinstance(k, str) and isinstance(v, (str, int, float))
            }
            sources = data.get("videoSources")
            if not isinstance(sources, list):
                return []

            out: list[dict[str, Any]] = []
            for vs in sources:
                if not isinstance(vs, dict):
                    continue
                vurl = str(vs.get("url") or "").strip()
                if not vurl or not vurl.startswith(("http://", "https://")):
                    continue
                if not await is_safe_url_async(vurl, allow_private=False):
                    logger.warning("Blocked unsafe Seanime stream URL: %s", vurl)
                    continue

                quality = str(vs.get("quality") or vs.get("label") or "").strip() or "auto"
                vtype = str(vs.get("type") or "").strip().lower()
                if not vtype or vtype == "unknown":
                    lower_u = vurl.lower()
                    if ".m3u8" in lower_u:
                        vtype = "hls"
                    elif ".mp4" in lower_u:
                        vtype = "mp4"
                    else:
                        vtype = "unknown"

                vs_headers = dict(common_headers)
                if isinstance(vs.get("headers"), dict):
                    for k, v in vs["headers"].items():
                        if k and v is not None:
                            vs_headers[str(k)] = str(v)

                raw_subs = vs.get("subtitles") or []
                clean_subs_in: list[dict[str, Any]] = []
                if isinstance(raw_subs, list):
                    for sub in raw_subs:
                        if not isinstance(sub, dict):
                            continue
                        surl = str(sub.get("url") or "").strip()
                        if not surl or not await is_safe_url_async(surl, allow_private=False):
                            continue
                        lang = str(sub.get("language") or "und").strip() or "und"
                        clean_subs_in.append(
                            {
                                "id": str(sub.get("id") or "") or None,
                                "url": surl,
                                "language": lang,
                                "label": str(sub.get("label") or lang),
                                "default": bool(sub.get("isDefault", False)),
                            }
                        )
                normalized_subs = (
                    normalize_tracks(
                        [
                            {k: v for k, v in item.items() if v is not None}
                            for item in clean_subs_in
                        ],
                        base_url=vurl,
                        kind="subtitle",
                    )
                    if clean_subs_in
                    else []
                )

                display_label = f"{srv_label} — {quality}" if quality != "auto" else srv_label
                out.append(
                    {
                        "url": vurl,
                        "label": display_label,
                        "server": srv_label,
                        "quality": quality,
                        "type": vtype,
                        "headers": vs_headers,
                        "tracks": normalized_subs,
                        "subtitles": normalized_subs,
                        "source_type": "seanime",
                    }
                )
            return out

        candidates: list[dict[str, Any]] = []
        seen_keys: set[tuple[str, str]] = set()

        if preferred_canonical is not None:
            pref_batch = await _query_server(preferred_canonical)
            for cand in pref_batch:
                key = (cand["url"], cand["server"])
                if key not in seen_keys:
                    seen_keys.add(key)
                    candidates.append(cand)
            if candidates:
                return candidates

        if remaining_servers:
            pending: set[asyncio.Task[list[dict[str, Any]]]] = {
                asyncio.create_task(_query_server(s)) for s in remaining_servers
            }
            grace_deadline: float | None = None
            try:
                while pending:
                    wait_timeout: float | None = None
                    if grace_deadline is not None:
                        wait_timeout = max(0.0, grace_deadline - time.monotonic())
                        if wait_timeout <= 0.0:
                            break
                    done, pending = await asyncio.wait(
                        pending,
                        timeout=wait_timeout,
                        return_when=asyncio.FIRST_COMPLETED,
                    )
                    if not done:
                        break
                    for finished in done:
                        batch = finished.result()
                        for cand in batch:
                            key = (cand["url"], cand["server"])
                            if key not in seen_keys:
                                seen_keys.add(key)
                                candidates.append(cand)
                    if candidates and grace_deadline is None and pending:
                        grace_deadline = time.monotonic() + 3.0
            finally:
                if pending:
                    for leftover in pending:
                        leftover.cancel()
                    await asyncio.gather(*pending, return_exceptions=True)

        if not candidates:
            if verification_exc is not None:
                raise verification_exc
            if last_error is not None:
                raise last_error
        return candidates

    async def resolve_candidate(self, candidate: dict[str, Any]) -> dict[str, Any]:
        """Validate a stream candidate returned by ``get_episode_sources``."""
        url = str(candidate.get("url") or "").strip()
        if not url or not await is_safe_url_async(url, allow_private=False):
            raise ValueError(f"URL vidéo Seanime invalide ou bloquée : {url}")
        subtitles = list(candidate.get("subtitles") or candidate.get("tracks") or [])
        return {
            "videoUrl": url,
            "url": url,
            "headers": dict(candidate.get("headers") or {}),
            "subtitles": subtitles,
            "tracks": subtitles,
            "audioTracks": [],
            "serverType": str(candidate.get("server") or self.name),
            "selectedQuality": str(candidate.get("quality") or "auto"),
            "type": str(candidate.get("type") or "unknown"),
            "timestamps": [],
            "provenance": "seanime",
            "unsupportedArguments": False,
        }

    async def diagnose(self, query: str = "naruto") -> dict[str, Any]:
        """Run end-to-end health checks against this Seanime provider."""
        started = time.monotonic()
        state = self._state_loader(self.extension_id)
        payload = str((state or {}).get("payload") or "")
        language = str((state or {}).get("language") or "javascript")

        syntax_ok, syntax_err = self._runtime.validate_syntax(
            payload,
            language=language,
            extension_id=self.extension_id,
            user_config=dict((state or {}).get("saved_config") or {}),
            defaults=dict((state or {}).get("defaults") or {}),
        )
        report: dict[str, Any] = {
            "extension_id": self.extension_id,
            "source_id": self.source_id,
            "engine": self._runtime.engine_name(),
            "syntax_ok": syntax_ok,
            "syntax_error": syntax_err,
            "settings": None,
            "search_count": 0,
            "sample_titles": [],
            "episode_count": 0,
            "stream_count": 0,
            "ok": False,
            "error": syntax_err,
            "logs": [],
        }
        if not syntax_ok:
            report["duration_ms"] = int((time.monotonic() - started) * 1000)
            return report

        collected_logs: list[str] = []
        token = _DIAGNOSE_LOG_SINK.set(collected_logs)
        try:
            report["settings"] = await self.get_settings()
            search_results = await self.search_anime(query or "naruto")
            report["search_count"] = len(search_results)
            report["sample_titles"] = [item.title for item in search_results[:5]]
            if search_results:
                detail = await self.get_anime_detail(search_results[0].url)
                report["episode_count"] = len(detail.episodes)
                if detail.episodes:
                    streams = await self.get_episode_sources(detail.episodes[0].playerUrl)
                    report["stream_count"] = len(streams)
            report["ok"] = bool(
                syntax_ok
                and report["search_count"] > 0
                and report["episode_count"] > 0
                and report["stream_count"] > 0
            )
            if report["ok"]:
                report["error"] = None
            elif report["search_count"] == 0:
                report["error"] = "La recherche n'a renvoyé aucun résultat pour ce titre."
            elif report["episode_count"] == 0:
                report["error"] = "La recherche a réussi mais aucun épisode n'a été trouvé."
            else:
                report["error"] = "Les épisodes ont été trouvés mais aucun flux vidéo jouable n'a été extrait."
        except Exception as exc:
            report["ok"] = False
            report["error"] = str(exc)
        finally:
            _DIAGNOSE_LOG_SINK.reset(token)

        report["logs"] = collected_logs[-10:]
        report["duration_ms"] = int((time.monotonic() - started) * 1000)
        return report
