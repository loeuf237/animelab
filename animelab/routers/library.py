from animelab.api_contracts import ContractRoute
import asyncio
import logging
import shutil
from pathlib import Path
from typing import Optional
from pydantic import BaseModel, Field
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse

from animelab.config import settings
from animelab.services.download_manager import download_manager
from animelab.services.library_service import library_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.watchdog_service import watchdog_service
from animelab.security import anonymize_path
from animelab import platform_events
from animelab.models.download_task import DownloadStatus

logger = logging.getLogger("animelab.router.library")
router = APIRouter(route_class=ContractRoute)


class AutoDownloadRequest(BaseModel):
    url: str = Field(min_length=1, max_length=4096)
    autoDownload: Optional[bool] = None
    autoDownloadVersion: str = Field(default="", max_length=40)
    autoDownloadSubtitles: bool = False
    autoDownloadServer: Optional[str] = Field(default=None, max_length=100)
    autoDownloadQuality: Optional[str] = Field(default=None, max_length=100)


class FavoriteRequest(AutoDownloadRequest):
    title: str = ""
    imageUrl: str = ""
    source: str = "french-manga"


# -------------------------------------------------------------------------
# Favoris API
# -------------------------------------------------------------------------

@router.post("/api/favorites")
async def add_favorite(body: FavoriteRequest):
    fav = library_service.add_favorite(body.url, body.title, body.imageUrl, body.source, body.autoDownloadVersion)
    options = body.model_dump(exclude_unset=True, include={"autoDownloadVersion", "autoDownloadSubtitles",
                                                         "autoDownloadServer", "autoDownloadQuality"})
    if body.autoDownload is not None or options:
        fav = library_service.update_auto_download(body.url,
            body.autoDownload if body.autoDownload is not None else fav.autoDownload, **options)
    return {"success": True, "id": fav.id, "message": "Favori ajouté", "favorite": fav.to_dict()}

@router.delete("/api/favorites")
async def remove_favorite(request: Request):
    body = await request.json()
    url = body.get("url")
    if url:
        library_service.remove_favorite(url)
    return {"success": True}

@router.get("/api/favorites/check")
async def check_favorite(url: str = Query(...)):
    return {"isFavorite": library_service.is_favorite(url)}

@router.get("/api/favorites")
async def get_favorites():
    return [f.to_dict() for f in library_service.get_all_favorites()]

@router.patch("/api/favorites/auto-download")
async def toggle_auto_download(body: AutoDownloadRequest):
    current = library_service.get_favorite(body.url)
    if current is None:
        raise HTTPException(404, "Ajoutez cet animé à la bibliothèque avant d'activer le suivi.")
    options = body.model_dump(exclude_unset=True, exclude={"url", "autoDownload"})
    fav = library_service.update_auto_download(body.url,
        body.autoDownload if body.autoDownload is not None else current.autoDownload, **options)
    return {"success": True, "favorite": fav.to_dict()}

@router.delete("/api/favorites/all")
async def clear_all_favorites():
    library_service.remove_all_favorites()
    return {"success": True, "message": "Bibliothèque vidée"}

# -------------------------------------------------------------------------
# Progression API
# -------------------------------------------------------------------------

@router.post("/api/progress/watched")
async def mark_watched(request: Request):
    body = await request.json()
    anime_url = body.get("animeUrl")
    anime_name = body.get("animeName", "")
    ep_num = int(body.get("episodeNumber", 0))
    version = body.get("version", "")
    watched = body.get("watched", True)
    if not isinstance(watched, bool):
        return JSONResponse(status_code=400, content={"error": "watched doit être un booléen"})
    if anime_url:
        library_service.mark_as_watched(anime_url, anime_name, ep_num, version, watched=watched)
    return {"success": True}

@router.get("/api/progress")
async def get_progress(animeUrl: str = Query(...)):
    return [p.to_dict() for p in library_service.get_progress_for_anime(animeUrl)]

@router.get("/api/progress/downloaded")
async def get_downloaded_set(animeUrl: str = Query(...)):
    return list(library_service.get_downloaded_episodes_set(animeUrl))

# -------------------------------------------------------------------------
# Historique API
# -------------------------------------------------------------------------

@router.get("/api/history")
async def get_history(animeName: Optional[str] = Query(None)):
    tasks = library_service.get_history(animeName)
    return [t.to_task().to_dict() for t in tasks]

@router.delete("/api/history/{task_id}")
async def delete_history_entry(task_id: str):
    try:
        success = download_manager.remove_task(task_id)
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if success:
        return {"success": True}
    return JSONResponse(status_code=400, content={"error": "Entrée introuvable"})

@router.delete("/api/history")
async def clear_history(
    status: Optional[str] = Query(None),
    animeName: Optional[str] = Query(None)
):
    library_service.clear_history(status=status, anime_name=animeName)
    download_manager.clear_history_tasks(status=status, anime_name=animeName)
    return {"success": True, "message": "Historique nettoyé"}

# -------------------------------------------------------------------------
# voir-anime.to API
# -------------------------------------------------------------------------

@router.get("/api/voiranime/search")
async def search_voiranime(q: str = Query(...)):
    return await voiranime_service.search_anime(q)

@router.get("/api/voiranime/anime")
async def get_voiranime_detail(url: str = Query(...)):
    return await voiranime_service.get_anime_detail(url)

@router.get("/api/voiranime/download-info")
async def get_voiranime_download_info(
    episodeUrl: str = Query(...),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
):
    return await asyncio.to_thread(
        voiranime_service.extract_download_info,
        episodeUrl,
        preferred_server=server,
        preferred_quality=quality,
    )

@router.get("/api/voiranime/qualities")
async def get_voiranime_qualities(episodeUrl: str = Query(...)):
    return await asyncio.to_thread(voiranime_service.extract_video_qualities, episodeUrl)

# -------------------------------------------------------------------------
# Système & Stockage API
# -------------------------------------------------------------------------

@router.get("/api/system/storage")
async def get_system_storage():
    download_dir = Path(settings.DOWNLOAD_DIR)
    try:
        download_dir.mkdir(parents=True, exist_ok=True)
        total, used, free = shutil.disk_usage(download_dir)
        percent = round((used / total) * 100, 1) if total > 0 else 0
        return {
            "totalBytes": total,
            "usedBytes": used,
            "freeBytes": free,
            "usedPercent": percent,
            "downloadDir": anonymize_path(str(download_dir)),
            "native": await asyncio.to_thread(platform_events.storage_status),
        }
    except Exception as e:
        logger.error("Error reading disk usage: %s", e)
        return {
            "totalBytes": None,
            "usedBytes": None,
            "freeBytes": None,
            "usedPercent": None,
            "downloadDir": anonymize_path(str(download_dir)),
            "error": str(e),
            "native": await asyncio.to_thread(platform_events.storage_status),
        }


@router.get("/api/system/android/storage")
async def android_storage_status():
    return await asyncio.to_thread(platform_events.storage_status)


@router.post("/api/system/android/storage")
async def android_storage_action(request: Request):
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid permission request")
    action = body.get("action")
    if not isinstance(action, str) or action not in {"choose_directory", "use_downloads", "notifications", "app_settings", "open_downloads"}:
        raise HTTPException(400, "Unknown permission action")
    if platform_events.storage_action_handler is None:
        raise HTTPException(404, "Android storage controls are unavailable")
    try:
        return await asyncio.to_thread(platform_events.storage_action_handler, action)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post("/api/system/android/export")
async def android_export_download(request: Request):
    if platform_events.completed_handler is None:
        raise HTTPException(404, "Android export is unavailable")
    body = await request.json()
    if not isinstance(body, dict):
        raise HTTPException(400, "Invalid export request")
    task_id = body.get("taskId")
    if not isinstance(task_id, str) or len(task_id) > 36:
        raise HTTPException(400, "Invalid download ID")
    task = download_manager.get_task(task_id)
    if task is None:
        raise HTTPException(404, "Download not found")
    if task.status != DownloadStatus.COMPLETED:
        raise HTTPException(409, "Complete and verify the download before exporting it")
    try:
        result = await download_manager.export_task(task, manual=True)
    except Exception as exc:
        return JSONResponse(status_code=409, content={"success": False, "code": "export_failed",
            "error": str(exc), "task": task.to_dict()})
    return {"success": True, **result, "task": task.to_dict()}

@router.post("/api/watchdog/check")
async def trigger_watchdog_check():
    try:
        new_count = await watchdog_service.check_new_episodes()
        return {"success": True, "newEpisodes": new_count}
    except Exception as e:
        logger.error("Error running manual watchdog check: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})
