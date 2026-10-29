from animelab.api_contracts import ContractRoute
from animelab.api_errors import APIProblem
from animelab.services.source_http import VerificationRequired
import asyncio
import json
import logging
from datetime import datetime
from typing import Optional
from fastapi import APIRouter, Request, Query, HTTPException
from fastapi.responses import JSONResponse, StreamingResponse

from animelab.models.download_task import DownloadStatus
from animelab.services.download_manager import download_manager
from animelab.services.proxy_service import proxy_service
from animelab.services.voiranime_service import voiranime_service
from animelab import platform_events
from animelab.services.output_profiles import OutputProfile

logger = logging.getLogger("animelab.router.download")
router = APIRouter(route_class=ContractRoute)


@router.post("/api/download")
async def start_download(request: Request):
    storage = await asyncio.to_thread(platform_events.storage_status)
    if storage is not None and not storage.get("authorized"):
        return JSONResponse(status_code=409, content={"error": "Storage access unavailable; authorize a folder in Settings > Storage", "code": "storage_permission_required"})
    body = await request.json()
    from animelab.services.output_profiles import snapshot, require_available
    try:
        require_available(snapshot(body.get('outputProfile'), legacy_subtitles=body.get('downloadSubtitles', False)))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    anime_name = body.get("animeName", "Unknown")
    episode_number = int(body.get("episodeNumber", 0))
    url = body.get("url", "").strip()
    file_name = body.get("fileName", f"{anime_name} - Episode {episode_number}.mp4")
    version = body.get("version") or ""
    subtitle_url = body.get("subtitleUrl")
    download_subtitles = str(body.get("downloadSubtitles", "false")).lower() == "true"
    selected_server = body.get("selectedServer")
    selected_quality = body.get("selectedQuality")
    source = body.get("source", "french-manga")

    scheduled_time_str = body.get("scheduledTime")
    scheduled_time = None
    if scheduled_time_str:
        try:
            scheduled_time = datetime.fromisoformat(scheduled_time_str)
        except VerificationRequired:
            raise
        except Exception:
            pass

    speed_limit = 0
    if body.get("speedLimit"):
        try:
            speed_limit = int(body["speedLimit"])
        except VerificationRequired:
            raise
        except Exception:
            pass

    if not url:
        return JSONResponse(status_code=400, content={"error": "URL manquante"})

    # Vérification doublon
    existing = download_manager.check_existing_file(anime_name, file_name, episode_number, version)
    if existing:
        info = await download_manager.get_or_resolve_episode_info(url, preferred_server=selected_server, preferred_quality=selected_quality, source=source)
        if info and info.size > 0 and existing.stat().st_size == info.size:
            return JSONResponse(
                status_code=400,
                content={
                    "success": False,
                    "alreadyExists": True,
                    "error": f"L'épisode existe déjà sur le disque avec la même taille ({info.formatted_size})."
                }
            )

    task = download_manager.start_download(
        anime_name=anime_name,
        episode_number=episode_number,
        download_page_url=url,
        file_name=file_name,
        subtitle_url=subtitle_url,
        scheduled_start_time=scheduled_time,
        speed_limit=speed_limit,
        download_subtitles=download_subtitles,
        selected_server=selected_server,
        selected_quality=selected_quality,
        source=source,
        version=version,
        anime_url=body.get("animeUrl") or "",
        output_profile=body.get('outputProfile'),
    )

    msg = (
        f"Téléchargement planifié pour : {scheduled_time_str}"
        if task.status == DownloadStatus.SCHEDULED
        else f"Téléchargement démarré: {task.fileName}"
    )

    return {"success": True, "taskId": task.id, "message": msg}

@router.post("/api/download/limit-speed")
async def set_global_speed_limit(request: Request):
    body = await request.json()
    try:
        limit = int(body.get("limit", 0))
        download_manager.set_global_speed_limit(limit)
        return {"success": True, "message": "Vitesse globale mise à jour"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Format de limite invalide: {e}"})

@router.post("/api/download/batch")
async def start_batch_download(request: Request):
    body = await request.json()
    from animelab.services.output_profiles import snapshot, require_available
    try:
        for episode in body.get('episodes', []):
            require_available(snapshot(episode.get('outputProfile'), legacy_subtitles=episode.get('downloadSubtitles', False)))
    except ValueError as exc:
        raise HTTPException(422, str(exc)) from exc
    anime_name = body.get("animeName", "Unknown")
    source = body.get("source", "french-manga")
    episodes = body.get("episodes", [])
    if not episodes:
        return JSONResponse(status_code=400, content={"error": "Aucun épisode sélectionné"})

    from bs4 import BeautifulSoup
    from animelab.services.extension_service import extension_service
    from animelab.services.aniyomi_container import _safe_select
    from animelab.services.extension_observability import InvalidSelector,extension_observability
    for source_id in {ep.get('source') or source for ep in episodes}:
        container=extension_service.get_container_source_by_id(source_id)
        if container:
            visible=next((ext for ext in extension_service.get_visible_extensions() if ext['pkg']==container.pkg),None)
            if visible and any(check['recipe_revision']==visible['recipe_revision'] and check['status'] in ('selector_error','parse_error','unsupported') for check in visible.get('health',[]) if check['operation'] in ('load','latest','detail')):
                return JSONResponse(status_code=409,content={'code':'source_recipe_invalid','error':'Testez ou corrigez cette recette avant de télécharger une série.'})
            try:
                for key,value in container.recipe.to_dict().items():
                    if key.endswith('selector') and value: _safe_select(BeautifulSoup('', 'html.parser'),value)
            except InvalidSelector as exc:
                extension_observability.record(container.pkg,'detail',error=exc,db_path=extension_service.db_path)
                return JSONResponse(status_code=409,content={'code':'source_recipe_invalid','error':'La recette de cette source doit être corrigée avant le téléchargement.'})
    for ep in episodes:
        if "source" not in ep:
            ep["source"] = source
        if "selectedServer" not in ep:
            ep["selectedServer"] = body.get("preferredServer")
        if "selectedQuality" not in ep:
            ep["selectedQuality"] = body.get("preferredQuality")

    tasks = download_manager.start_batch_download(anime_name, episodes, source=source)
    return {
        "success": True,
        "count": len(tasks),
        "message": f"{len(tasks)} téléchargement(s) démarré(s)"
    }


@router.get('/api/download/output-profiles')
async def get_output_profiles():
    from animelab.services.output_profiles import available_profiles
    return await asyncio.to_thread(available_profiles)


@router.get('/api/download/media-capabilities')
async def get_media_capabilities():
    from animelab import media_tools
    return await asyncio.to_thread(media_tools.capabilities)


@router.get('/api/download/{task_id}/media-inventory')
async def get_output_inventory(task_id: str):
    try:
        return await download_manager.output_inventory(task_id)
    except KeyError as exc:
        raise HTTPException(404, 'Tâche introuvable') from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(409, str(exc)) from exc


@router.post('/api/download/{task_id}/output')
async def reprocess_output(task_id: str, profile: OutputProfile):
    try:
        task = await download_manager.reprocess_output(task_id, profile.model_dump())
        return {'success': True, 'taskId': task.id}
    except KeyError as exc:
        raise HTTPException(404, 'Tâche introuvable') from exc
    except (ValueError, OSError) as exc:
        raise HTTPException(422, str(exc)) from exc

@router.delete("/api/download/{task_id}")
async def cancel_download(task_id: str, remove: bool = False):
    if download_manager._export_in_progress(task_id):
        raise HTTPException(status_code=409, detail="Wait for the current export before removing this download")
    if remove:
        removed = download_manager.remove_task(task_id)
        if removed:
            return {"success": True, "message": "Téléchargement supprimé"}
        return JSONResponse(status_code=404, content={"error": "Tâche introuvable"})

    cancelled = download_manager.cancel_download(task_id)
    if cancelled:
        return {"success": True, "message": "Téléchargement annulé"}

    removed = download_manager.remove_task(task_id)
    if removed:
        return {"success": True, "message": "Tâche supprimée"}

    return JSONResponse(status_code=400, content={"error": "Impossible d'annuler ou supprimer ce téléchargement"})

@router.post("/api/download/{task_id}/pause")
async def pause_download(task_id: str):
    paused = download_manager.pause_download(task_id)
    if paused:
        return {"success": True, "message": "Téléchargement mis en pause"}
    return JSONResponse(status_code=400, content={"error": "Impossible de mettre en pause ce téléchargement"})

@router.post("/api/download/{task_id}/resume")
async def resume_download(task_id: str):
    resumed = download_manager.resume_download(task_id)
    if resumed:
        return {"success": True, "message": "Téléchargement repris"}
    task = download_manager.get_task(task_id)
    return JSONResponse(status_code=400, content={"error": task.error if task and task.error else "Impossible de reprendre ce téléchargement"})

@router.delete("/api/download/{task_id}/remove")
async def remove_task(task_id: str):
    try:
        removed = download_manager.remove_task(task_id)
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    if removed:
        return {"success": True, "message": "Tâche supprimée"}
    return JSONResponse(status_code=404, content={"error": "Tâche introuvable"})

@router.get("/api/download/stream")
async def stream_download_updates(request: Request):
    queue = download_manager.subscribe_sse()

    async def event_generator():
        try:
            while True:
                if await request.is_disconnected():
                    break
                data = await queue.get()
                yield f"event: download-update\ndata: {json.dumps(data)}\n\n"
        finally:
            download_manager.unsubscribe_sse(queue)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

@router.get("/api/download/status")
async def get_all_status():
    return [t.to_dict() for t in download_manager.get_all_tasks()]

@router.post("/api/download/{task_id}/speed-limit")
async def set_task_speed_limit(task_id: str, request: Request):
    body = await request.json()
    try:
        limit = int(body.get("limit", 0))
        updated = download_manager.set_task_speed_limit(task_id, limit)
        if updated:
            return {"success": True, "message": "Limite de vitesse mise à jour"}
        return JSONResponse(status_code=400, content={"error": "Tâche introuvable"})
    except Exception:
        return JSONResponse(status_code=400, content={"error": "Format de limite invalide"})

@router.post("/api/download/pause-all")
async def pause_all():
    download_manager.pause_all_downloads()
    return {"success": True, "message": "Tous les téléchargements actifs ont été mis en pause"}

@router.post("/api/download/resume-all")
async def resume_all():
    download_manager.resume_all_downloads()
    return {"success": True, "message": "Tous les téléchargements en pause ont été repris"}

@router.post("/api/download/cancel-all")
async def cancel_all():
    count = download_manager.cancel_all_downloads()
    return {"success": True, "count": count, "message": f"{count} téléchargement(s) annulé(s)"}

@router.post("/api/download/clean")
async def clear_inactive():
    download_manager.clear_inactive_tasks()
    return {"success": True, "message": "Tâches inactives nettoyées"}

@router.get("/api/download/settings")
async def get_settings():
    return download_manager.get_settings()

@router.post("/api/download/settings")
async def save_settings(request: Request):
    body = await request.json()
    try:
        max_concurrent = int(body.get("maxConcurrentDownloads", 3))
        global_limit = int(body.get("globalSpeedLimit", 0))
        plex_org = bool(body.get("plexOrganization", False))
        user_agent = body.get("selectedUserAgent")
        voiranime_default_server = body.get("voiranimeDefaultServer")
        download_manager.update_settings(
            max_concurrent, global_limit, plex_org, user_agent, voiranime_default_server
        )
        return {"success": True, "message": "Paramètres mis à jour"}
    except Exception as e:
        return JSONResponse(status_code=400, content={"error": f"Paramètres invalides: {e}"})

@router.get("/api/proxy/settings")
async def get_proxy_settings():
    return proxy_service.get_proxy_settings()

@router.post("/api/proxy/settings")
async def save_proxy_settings(request: Request):
    try:
        data = await request.json()
        previous_proxy = (proxy_service.proxy_enabled, proxy_service.get_active_proxy())
        saved = proxy_service.save_proxy_settings(data)
        if previous_proxy != (proxy_service.proxy_enabled, proxy_service.get_active_proxy()):
            from animelab.services.source_http import source_http
            source_http.apply_proxy_settings()
        return {"success": True, "settings": saved, "message": "Paramètres proxy enregistrés"}
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error(f"Error saving proxy settings: {e}")
        return JSONResponse(status_code=400, content={"error": f"Erreur lors de l'enregistrement: {e}"})

@router.post("/api/proxy/test")
async def test_proxy(request: Request):
    try:
        body = await request.json()
        url = body.get("proxyUrl")
        if isinstance(body.get("settings"), dict):
            config = dict(body["settings"])
            if config.get("password") == proxy_service.MASK:
                config["password"] = proxy_service.proxy_password
            if config.get("custom_url") == proxy_service.mask_url(proxy_service.custom_proxy_url):
                config["custom_url"] = proxy_service.custom_proxy_url
            url = proxy_service.build_proxy_url(config)
        res = await proxy_service.test_proxy_connection(url)
        return res
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error(f"Error testing proxy connection: {e}")
        return {"success": False, "error": str(e)}

@router.get("/api/episode/servers")
async def get_episode_servers(url: str = Query(...), source: Optional[str] = Query(None)):
    try:
        from animelab.services.extension_service import extension_service
        from animelab.services.android_extensions import AndroidAPKSource
        selected=extension_service.get_container_source_by_id(source) if source else None
        if isinstance(selected,AndroidAPKSource):
            candidates=await selected.get_episode_sources(url)
            return {'success':True,'servers':list(dict.fromkeys(item['server'] for item in candidates)),
                    'qualities':list(dict.fromkeys(item['quality'] for item in candidates)), 'defaultServer':'auto'}
        is_voir_anime = ("voir-anime" in url) or ("voiranime" in url)
        if is_voir_anime:
            data = await asyncio.to_thread(voiranime_service.get_episode_servers, url)
            servers = data.get("servers", []) if isinstance(data, dict) else data
            return {
                "success": True,
                "servers": servers,
                "defaultServer": download_manager.voiranime_default_server,
            }
        return {
            "success": True,
            "servers": [],
            "defaultServer": "auto",
        }
    except (VerificationRequired, APIProblem):
        raise
    except Exception as e:
        logger.error("Error get_episode_servers: %s", e)
        return {"success": False, "servers": [], "error": str(e)}

@router.get("/api/episode/size")
async def get_episode_size(
    url: str = Query(...),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
):
    try:
        info = await download_manager.get_or_resolve_episode_info(
            url, preferred_server=server, preferred_quality=quality, source=source
        )
        if info:
            qualities_dict = {}
            if info.video_qualities_json:
                try:
                    qualities_dict = json.loads(info.video_qualities_json)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
            qualities_sizes_dict = {}
            if getattr(info, "qualities_sizes_json", None):
                try:
                    qualities_sizes_dict = json.loads(info.qualities_sizes_json)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
            subtitles_list = []
            if getattr(info, "subtitles_json", None):
                try:
                    subtitles_list = json.loads(info.subtitles_json)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
            if not subtitles_list and info.subtitle_url:
                subtitles_list = [{"label": "Sous-titres", "srclang": "fr", "url": info.subtitle_url}]

            return {
                "success": True,
                "formattedSize": info.formatted_size,
                "size": info.size,
                "directUrl": info.direct_url,
                "subtitleUrl": info.subtitle_url,
                "subtitles": subtitles_list,
                "serverType": info.server_type,
                "availableServers": info.available_servers,
                "qualities": list(qualities_dict.keys()),
                "qualitiesSizes": qualities_sizes_dict,
                "currentQuality": info.selected_quality,
                "currentServer": info.selected_server,
            }
        return {"success": False, "formattedSize": "Taille inconnue", "size": -1}
    except VerificationRequired:
        raise
    except Exception:
        return {"success": False, "formattedSize": "Erreur résolution", "size": -1}

@router.post("/api/download/{task_id}/move-to-top")
async def move_task_to_top(task_id: str):
    download_manager.move_task_to_top(task_id)
    return {"success": True, "message": "Tâche montée en haut de la file"}

@router.post("/api/download/move-series-to-top")
async def move_series_to_top(request: Request):
    body = await request.json()
    anime_name = body.get("animeName")
    if not anime_name:
        return JSONResponse(status_code=400, content={"error": "Nom de la série manquant"})
    download_manager.move_series_to_top(anime_name)
    return {"success": True, "message": f"Série {anime_name} montée en haut de la file"}

@router.post("/api/download/reorder")
async def reorder_tasks(request: Request):
    ordered_ids = await request.json()
    download_manager.reorder_tasks(ordered_ids)
    return {"success": True, "message": "File d'attente réorganisée"}

@router.post("/api/download/{task_id}/verify")
async def verify_task(task_id: str):
    res = await download_manager.verify_task_async(task_id)
    if not res:
        return JSONResponse(status_code=404, content={"error": "Tâche introuvable"})
    return {
        "success": True,
        "valid": res.valid,
        "status": res.status,
        "duration": res.duration,
        "formattedDuration": res.formattedDuration,
        "formattedSize": res.formattedSize,
        "hasVideo": res.hasVideo,
        "hasAudio": res.hasAudio,
        "formatName": res.formatName,
        "error": res.error,
        "filePath": res.filePath,
        "relocated": bool(res.relocatedPath),
    }

@router.post("/api/download/verify-all")
async def verify_all_tasks():
    summary = await download_manager.verify_all_completed_async()
    return {
        "success": True,
        **summary
    }

@router.post("/api/download/{task_id}/redownload")
async def redownload_task(task_id: str):
    try:
        task = download_manager.redownload_task(task_id)
    except ValueError as exc:
        return JSONResponse(status_code=409, content={"error": str(exc)})
    if not task:
        return JSONResponse(status_code=404, content={"error": "Tâche introuvable pour re-téléchargement"})
    return {
        "success": True,
        "message": f"Téléchargement relancé pour : {task.fileName}",
        "task": task.to_dict(),
    }
