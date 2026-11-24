from animelab.services.source_registry import source_registry, source_identity
from animelab.api_contracts import ContractRoute
from animelab.api_errors import APIProblem
from animelab.services.source_http import VerificationRequired
import asyncio
import json
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import APIRouter, Query, HTTPException
from animelab.models.anime import AnimeDetail
from animelab.security import is_safe_url
from animelab.services.library_service import equivalent_url_variants, library_service
from animelab.services.local_media import local_media
from animelab.services.tmdb_service import tmdb_service
from animelab.services.french_stream_service import normalize_french_stream_url
from animelab.services.voiranime_service import normalize_voiranime_url

logger = logging.getLogger("animelab.router.anime")
router = APIRouter(route_class=ContractRoute)

def detect_source_from_url(url: str, fallback: str = "french-manga") -> str:
    return source_registry.detect(url, fallback)


@router.get("/api/releases/latest")
async def api_latest_releases(source: Optional[str] = None):
    """Retourne les dernières sorties en JSON pour hydratation dynamique instantanée."""
    norm_source = (source or "all").lower().strip()
    if norm_source != "all":
        provider = source_registry.get(norm_source)
        return {"source": provider.id, "releases": await provider.get_latest_releases()}
    providers = [source_registry.get(sid) for sid in source_registry.natives()]
    responses = await asyncio.gather(*(provider.get_latest_releases() for provider in providers))
    return {provider.id: releases for provider, releases in zip(providers, responses)}


@router.get("/api/search")
async def search_api(
    q: str = Query(..., max_length=250),
    source: str = Query("all"),
    include_challenges: bool = Query(False),
):
    """Keep partial results and identify every source awaiting verification."""
    norm_source = (source or "all").lower().strip()
    selected = source_registry.all() if norm_source == "all" else [source_registry.get(norm_source)]
    providers = [(provider.id, provider) for provider in selected if provider.capabilities.search]
    if norm_source != "all" and not providers:
        selected[0].require('search')

    async def run(service):
        provider = getattr(service, 'service', service)
        recipe = getattr(provider, 'recipe', None)
        expands = bool(recipe and recipe.runtime.get('listing_expansion'))
        source_id = getattr(service, 'id', getattr(service, 'pkg', ''))
        # APK searches can expand seasons and films using several HTTP calls.
        # Let their bounded search worker (90 s) and parent (105 s) finish;
        # cancelling them after 12 s turns a healthy source into an error.
        timeout = 120 if getattr(provider, 'runtime', '') == 'android-apk' else (
            45 if expands or source_id.endswith('.franime') else (
                35 if getattr(provider, 'runtime', '') == 'seanime' else 12
            )
        )
        return await asyncio.wait_for(service.search_anime(q.strip()), timeout=timeout)

    responses = await asyncio.gather(*(run(service) for _, service in providers), return_exceptions=True)
    results, challenges, errors, seen = [], [], [], set()
    first_challenge = None
    for (sid, service), response in zip(providers, responses):
        if isinstance(response, VerificationRequired):
            first_challenge = first_challenge or response
            challenges.append({**response.to_dict(), "source": sid})
        elif isinstance(response, BaseException):
            logger.debug("Search source %s failed: %s", sid, response)
            warning = {"source": sid, "url": service.base_url, "domain": urlparse(service.base_url).hostname or '',
                       "message": "La source est momentanément inaccessible"}
            if isinstance(response, APIProblem):
                warning.update(code=response.problem.code, message=response.problem.messageKey)
            errors.append(warning)
        else:
            for item in response or []:
                item.source = sid
                key = (sid, item.url)
                if key not in seen:
                    seen.add(key)
                    results.append(item)
    if include_challenges is True:
        return {"results": results, "challenges": challenges, "errors": errors}
    if first_challenge:
        raise first_challenge
    return results

def _is_seanime_reference(url: str, source: str) -> bool:
    if not source.lower().startswith("seanime:") or not url.startswith(("http://", "https://")):
        return False
    try:
        seanime_svc = source_registry.seanime()
        src = seanime_svc.get_source_by_id(source) if seanime_svc is not None else None
        return bool(src and src.has_reference(url))
    except Exception:
        return False


def _resolve_detail_context(url: str, source: str):
    """Resolve normalized fetch URL, equivalent lookup URLs, favorite row, and cached snapshot."""
    is_seanime = source.lower().startswith("seanime:")
    fetch_url = (
        (url or "").strip()
        if is_seanime
        else normalize_french_stream_url(normalize_voiranime_url(url))
    )
    lookup_urls = list(dict.fromkeys([
        *equivalent_url_variants(url),
        *equivalent_url_variants(fetch_url),
    ]))
    fav = None
    for candidate_url in lookup_urls:
        candidate_fav = library_service.get_favorite(candidate_url)
        if candidate_fav is not None:
            fav = candidate_fav
            break
    try:
        snapshot = library_service.get_anime_detail_snapshot(lookup_urls)
    except Exception as exc:
        logger.debug("Snapshot lookup unavailable for '%s': %s", fetch_url, exc)
        snapshot = None
    return is_seanime, fetch_url, lookup_urls, fav, snapshot


def _build_enriched_detail_payload(
    *,
    detail: AnimeDetail,
    source: str,
    source_name: str,
    lookup_urls: list[str],
    fetch_url: str,
    fav: Any,
    from_cache: bool,
    cached_at: Optional[str],
) -> Dict[str, Any]:
    """Attach live watched, downloaded, favorite, and local disk/task playback flags."""
    downloaded_set = set()
    watched_set = set()
    progress_by_episode = {}
    for candidate_url in lookup_urls:
        downloaded_set.update(library_service.get_downloaded_episodes_set(candidate_url))
        watched_set.update(library_service.get_watched_episodes_set(candidate_url))
        for p in library_service.get_progress_for_anime(candidate_url):
            progress_by_episode[(p.episodeNumber, p.version or "")] = p
        if fav is None:
            fav = library_service.get_favorite(candidate_url)

    is_favorite = fav is not None
    auto_download = fav.autoDownload if fav else False

    episodes_data = []
    for ep in detail.episodes:
        num = ep.number
        version = ep.version or detail.version or ""
        progress = progress_by_episode.get((num, version))
        if progress is None:
            progress = progress_by_episode.get((num, ""))
        is_dl = bool(progress and progress.downloaded)
        is_watched = bool(progress and progress.watched)
        raw_season = ep.nativeMetadata.get("season") if isinstance(getattr(ep, "nativeMetadata", None), dict) else None
        try:
            ep_season = int(raw_season) if raw_season is not None else None
        except (TypeError, ValueError):
            ep_season = None
        if ep_season is not None and ep_season <= 0:
            ep_season = None
        local_task = library_service.find_downloaded_episode(
            anime_name=detail.title,
            episode_number=num,
            version=version,
            episode_url=ep.downloadPageUrl or ep.playerUrl or "",
            anime_url=fetch_url,
            source=source,
        )
        if local_task is None:
            local_task = local_media.find_and_register(
                anime_name=detail.title,
                episode_number=num,
                version=version,
                season=ep_season,
                anime_url=fetch_url,
                source=source,
            )
        task_id = local_task.id if local_task else None
        ep_dict = ep.model_dump()
        ep_dict["version"] = version
        ep_dict["isDownloaded"] = is_dl or local_task is not None
        ep_dict["isWatched"] = is_watched
        ep_dict["downloadTaskId"] = task_id
        episodes_data.append(ep_dict)

    anime_dump = detail.model_dump()
    anime_dump["episodes"] = episodes_data

    return {
        "detail_obj": detail,
        "anime": anime_dump,
        "source": source,
        "sourceName": source_name,
        "isFavorite": is_favorite,
        "autoDownload": auto_download,
        "downloadedEpisodes": list(downloaded_set),
        "watchedEpisodes": list(watched_set),
        "totalEpisodes": len(episodes_data),
        "downloadedCount": sum(1 for e in episodes_data if e["isDownloaded"]),
        "watchedCount": sum(1 for e in episodes_data if e["isWatched"]),
        "fromCache": from_cache,
        "cachedAt": cached_at,
    }


async def fetch_enriched_anime_detail(
    url: str,
    source: str = "french-manga",
    *,
    refresh: bool = False,
) -> Optional[Dict[str, Any]]:
    """Récupère et enrichit la fiche complète d'un animé (cache bibliothèque hors-ligne + TMDB + progression)."""
    is_seanime, fetch_url, lookup_urls, fav, snapshot = _resolve_detail_context(url, source)
    if not fetch_url or not fetch_url.startswith(("http://", "https://")):
        return None

    # 1. Offline-first fast path for library entries with a saved snapshot
    if not refresh and fav is not None and snapshot is not None:
        resolved_source = snapshot.source or fav.source or source
        syntactic_ok = (
            _is_seanime_reference(fetch_url, resolved_source)
            or resolved_source.lower().startswith("seanime:")
            or is_safe_url(fetch_url, require_dns=False)
        )
        if syntactic_ok:
            try:
                cached_detail = AnimeDetail.model_validate(json.loads(snapshot.detailJson))
                cached_detail.source = resolved_source
                try:
                    source_name = source_registry.get(resolved_source).name
                except Exception:
                    source_name = snapshot.sourceName or resolved_source
                cached_at = snapshot.updatedAt.isoformat() if snapshot.updatedAt else None
                return _build_enriched_detail_payload(
                    detail=cached_detail,
                    source=resolved_source,
                    source_name=source_name,
                    lookup_urls=lookup_urls,
                    fetch_url=fetch_url,
                    fav=fav,
                    from_cache=True,
                    cached_at=cached_at,
                )
            except Exception as exc:
                logger.debug("Corrupt or unreadable cached snapshot for '%s': %s", fetch_url, exc)

    # 2. Live online path (explicit refresh, non-favorite, or first-time load)
    if is_seanime:
        url_safe = _is_seanime_reference(fetch_url, source) or is_safe_url(fetch_url)
        syntactic_safe = _is_seanime_reference(fetch_url, source) or is_safe_url(fetch_url, require_dns=False)
    else:
        url_safe = is_safe_url(fetch_url)
        syntactic_safe = is_safe_url(fetch_url, require_dns=False)

    if not url_safe:
        if refresh and snapshot is not None and syntactic_safe:
            raise HTTPException(
                status_code=503,
                detail="Connexion Internet indisponible pour actualiser la fiche.",
            )
        return None

    if not is_seanime:
        detected_source = detect_source_from_url(fetch_url, fallback=source)
        if detected_source != source:
            source = detected_source

    provider = source_registry.get(source)
    detail = await provider.get_anime_detail(fetch_url)

    if not detail:
        return None

    detail.source = source
    detail = await tmdb_service.enrich_anime_detail(detail)

    cached_at: Optional[str] = None
    try:
        saved = library_service.save_anime_detail_snapshot(
            fetch_url,
            source,
            provider.name,
            detail.model_dump(),
            pinned=(fav is not None),
        )
        if saved is not None and saved.updatedAt is not None:
            cached_at = saved.updatedAt.isoformat()
    except Exception as exc:
        logger.debug("Unable to persist anime detail snapshot for '%s': %s", fetch_url, exc)

    return _build_enriched_detail_payload(
        detail=detail,
        source=source,
        source_name=provider.name,
        lookup_urls=lookup_urls,
        fetch_url=fetch_url,
        fav=fav,
        from_cache=False,
        cached_at=cached_at,
    )


@router.get("/api/anime/detail")
@router.get("/api/anime")
async def api_anime_detail(
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source"),
    refresh: bool = Query(False, alias="refresh"),
):
    """Retourne la fiche anime complète avec épisodes et métadonnées en JSON pur."""
    is_seanime, fetch_url, _, fav, snapshot = _resolve_detail_context(url, source)
    if not fetch_url or not fetch_url.startswith(("http://", "https://")):
        raise HTTPException(status_code=400, detail="URL d'animé invalide ou non sécurisée")

    has_library_snapshot = fav is not None and snapshot is not None
    if not _is_seanime_reference(url, source):
        if is_seanime and has_library_snapshot and not refresh:
            pass
        elif not is_safe_url(fetch_url, require_dns=False):
            raise HTTPException(status_code=400, detail="URL d'animé invalide ou non sécurisée")
        elif not refresh and not has_library_snapshot and not is_safe_url(fetch_url):
            raise HTTPException(status_code=400, detail="URL d'animé invalide ou non sécurisée")

    res = await fetch_enriched_anime_detail(url, source, refresh=refresh)
    if not res:
        raise HTTPException(status_code=404, detail="Anime introuvable ou URL invalide")

    output = dict(res)
    output.pop("detail_obj", None)
    return {"success": True, **output}

@router.get("/api/home/feed")
async def api_home_feed():
    """
    Flux d'accueil consolidé pour le frontend SPA :
    - Dernières sorties des sources natives et extensions
    - Favoris de l'utilisateur
    - Historique récent
    - Extensions actives
    """
    registered = source_registry.all()
    enabled_extensions = [provider.service for provider in registered if provider.imported]

    async def fetch(service):
        return await asyncio.wait_for(service.get_latest_releases(), timeout=45 if getattr(service, "id", getattr(service, "pkg", "")).endswith(".franime") else 12)

    # Every enabled source receives a result or a visible error; no first-four cutoff.
    providers = [(provider.id, provider) for provider in registered]
    async def fetch_supported(provider):
        if not provider.capabilities.latest:
            return []
        return await fetch(provider)
    all_res = await asyncio.gather(*(fetch_supported(service) for _, service in providers), return_exceptions=True)
    results_by_id = {sid: res for (sid, _), res in zip(providers, all_res)}

    def _safe_items(source_id: str) -> list:
        res = results_by_id.get(source_id)
        return [] if res is None or isinstance(res, BaseException) else list(res)

    latest_fm = _safe_items("french-manga")
    latest_fs = _safe_items("french-stream")
    latest_va = _safe_items("voir-anime")
    latest_ap = _safe_items("animepahe")

    ext_releases = {}
    for sid, provider in providers:
        if not provider.imported:
            continue
        res = results_by_id.get(sid)
        if not isinstance(res, BaseException) and res:
            ext_releases[sid] = {
                "name": provider.service.name,
                "releases": [r.model_dump() for r in res[:24]],
            }

    challenges, errors = [], []
    for (sid, service), response in zip(providers, all_res):
        if isinstance(response, VerificationRequired):
            challenges.append({**response.to_dict(), "source": sid})
        elif isinstance(response, BaseException):
            errors.append({"source": sid, "message": "La source est momentanément inaccessible",
                           "url": service.base_url, "domain": urlparse(service.base_url).hostname or ""})

    favorites = [f.to_dict() for f in library_service.get_all_favorites()]
    history_items = [t.to_task().to_dict() for t in library_service.get_history()[:15]]

    releases_map = {
        sid: [r.model_dump() for r in _safe_items(sid)]
        for sid, provider in providers
        if not provider.imported
    }
    for pkg, ext_info in ext_releases.items():
        releases_map[pkg] = ext_info["releases"]

    return {
        "success": True,
        "challenges": challenges, "errors": errors,
        "latestReleases": releases_map,
        "latestFrenchManga": [r.model_dump() for r in latest_fm],
        "latestFrenchStream": [r.model_dump() for r in latest_fs],
        "latestVoirAnime": [r.model_dump() for r in latest_va],
        "latestAnimePahe": [r.model_dump() for r in latest_ap],
        "extensionsReleases": ext_releases,
        "favorites": favorites,
        "recentHistory": history_items,
        "enabledExtensions": [
            {
                "id": source_identity(ext,ext.pkg),
                "pkg": ext.pkg,
                "name": ext.name,
                "lang": getattr(ext, "lang", "fr"),
                "baseUrl": getattr(ext, "base_url", ""),
                "supportsLatest": source_registry.describe(source_identity(ext,ext.pkg), ext).capabilities.latest,
            }
            for ext in enabled_extensions
        ],
    }

@router.get("/api/sources/{source_id}/feed")
async def api_source_feed(source_id: str):
    """Retourne les dernières sorties / le catalogue d'une source spécifique."""
    provider = source_registry.get(source_id)
    releases = await provider.get_latest_releases()
    return {"success": True, "source": provider.id, "releases": releases}
