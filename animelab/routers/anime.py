from animelab.services.source_registry import source_registry
from animelab.api_contracts import ContractRoute
from animelab.services.source_http import VerificationRequired
import asyncio
import logging
from typing import Optional, Dict, Any
from urllib.parse import urlparse
from fastapi import APIRouter, Query, HTTPException
from animelab.security import is_safe_url
from animelab.services.library_service import library_service
from animelab.services.tmdb_service import tmdb_service

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
        recipe = getattr(getattr(service, 'service', service), 'recipe', None)
        expands = bool(recipe and recipe.runtime.get('listing_expansion'))
        source_id = getattr(service, 'id', getattr(service, 'pkg', ''))
        timeout = 45 if expands or source_id.endswith('.franime') else 12
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
            errors.append({"source": sid, "url": service.base_url, "domain": urlparse(service.base_url).hostname or '',
                           "message": "La source est momentanément inaccessible"})
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

async def fetch_enriched_anime_detail(url: str, source: str = "french-manga") -> Optional[Dict[str, Any]]:
    """Récupère et enrichit la fiche complète d'un animé (TMDB, épisodes, favoris, progression)."""
    if not url or not is_safe_url(url):
        return None

    detected_source = detect_source_from_url(url, fallback=source)
    if detected_source != source:
        source = detected_source

    provider = source_registry.get(source)
    detail = await provider.get_anime_detail(url)

    if not detail:
        return None

    detail.source = source
    detail = await tmdb_service.enrich_anime_detail(detail)
    downloaded_set = library_service.get_downloaded_episodes_set(url)
    watched_set = library_service.get_watched_episodes_set(url)
    progress_by_episode = {
        (p.episodeNumber, p.version or ""): p
        for p in library_service.get_progress_for_anime(url)
    }
    fav = library_service.get_favorite(url)
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
        local_task = library_service.find_downloaded_episode(
            anime_name=detail.title,
            episode_number=num,
            version=ep.version or detail.version or "",
            episode_url=ep.downloadPageUrl or ep.playerUrl or "",
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
        "isFavorite": is_favorite,
        "autoDownload": auto_download,
        "downloadedEpisodes": list(downloaded_set),
        "watchedEpisodes": list(watched_set),
        "totalEpisodes": len(episodes_data),
        "downloadedCount": sum(1 for e in episodes_data if e["isDownloaded"]),
        "watchedCount": sum(1 for e in episodes_data if e["isWatched"]),
    }


@router.get("/api/anime/detail")
@router.get("/api/anime")
async def api_anime_detail(
    url: str = Query(..., alias="url"),
    source: str = Query("french-manga", alias="source")
):
    """Retourne la fiche anime complète avec épisodes et métadonnées en JSON pur."""
    if not is_safe_url(url):
        raise HTTPException(status_code=400, detail="URL d'animé invalide ou non sécurisée")
    res = await fetch_enriched_anime_detail(url, source)
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
    latest_fm = all_res[0] if not isinstance(all_res[0], Exception) else []
    latest_va = all_res[1] if not isinstance(all_res[1], Exception) else []
    latest_ap = all_res[2] if not isinstance(all_res[2], Exception) else []

    ext_releases = {}
    for idx, ext in enumerate(enabled_extensions):
        res = all_res[3 + idx]
        if not isinstance(res, Exception) and res:
            ext_releases[getattr(ext,'source_id',ext.pkg)] = {
                "name": ext.name,
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
        "french-manga": [r.model_dump() for r in latest_fm],
        "voir-anime": [r.model_dump() for r in latest_va],
        "animepahe": [r.model_dump() for r in latest_ap],
    }
    for pkg, ext_info in ext_releases.items():
        releases_map[pkg] = ext_info["releases"]

    return {
        "success": True,
        "challenges": challenges, "errors": errors,
        "latestReleases": releases_map,
        "latestFrenchManga": [r.model_dump() for r in latest_fm],
        "latestVoirAnime": [r.model_dump() for r in latest_va],
        "latestAnimePahe": [r.model_dump() for r in latest_ap],
        "extensionsReleases": ext_releases,
        "favorites": favorites,
        "recentHistory": history_items,
        "enabledExtensions": [
            {
                "id": getattr(ext,'source_id',ext.pkg),
                "pkg": ext.pkg,
                "name": ext.name,
                "lang": getattr(ext, "lang", "fr"),
                "baseUrl": getattr(ext, "base_url", ""),
                "supportsLatest": source_registry.describe(getattr(ext,'source_id',ext.pkg), ext).capabilities.latest,
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
