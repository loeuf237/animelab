from animelab.api_contracts import ContractRoute
from animelab.services.source_http import source_http, VerificationRequired
import asyncio
import json
import logging
import mimetypes
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Response, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse

import httpx
from animelab.config import settings
from animelab.security import is_safe_url, is_safe_url_async, is_safe_path
from animelab.media_policy import validate_media_url
from animelab.services.download_manager import download_manager
from animelab.services.proxy_service import proxy_service
from animelab.services.library_service import library_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.scraping_service import scraping_service
from animelab.services.animepahe_service import animepahe_service
from animelab.services.extension_service import extension_service
from animelab.services.extractors import extractor_registry

import hashlib

logger = logging.getLogger("animelab.router.media")
router = APIRouter(route_class=ContractRoute)

import os
from collections import OrderedDict

IMAGE_CACHE: OrderedDict[str, tuple[bytes, str]] = OrderedDict()
IMAGE_CACHE_CURRENT_BYTES = 0
MAX_IMAGE_CACHE_BYTES = 50 * 1024 * 1024  # 50 Mo max en mémoire vive
MAX_IMAGE_CACHE_ITEMS = 200
IMAGE_DISK_CACHE_DIR = settings.CACHE_DIR / "images"
IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 Mo max pour prévenir les attaques OOM
CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, immutable"}

def _get_memory_cached_image(url: str) -> Optional[tuple[bytes, str]]:
    global IMAGE_CACHE
    if url in IMAGE_CACHE:
        IMAGE_CACHE.move_to_end(url)
        return IMAGE_CACHE[url]
    return None

def _put_memory_cached_image(url: str, content: bytes, ctype: str):
    global IMAGE_CACHE, IMAGE_CACHE_CURRENT_BYTES
    if url in IMAGE_CACHE:
        old_data, _ = IMAGE_CACHE.pop(url)
        IMAGE_CACHE_CURRENT_BYTES -= len(old_data)

    item_len = len(content)
    while IMAGE_CACHE and (IMAGE_CACHE_CURRENT_BYTES + item_len > MAX_IMAGE_CACHE_BYTES or len(IMAGE_CACHE) >= MAX_IMAGE_CACHE_ITEMS):
        _, (evicted_data, _) = IMAGE_CACHE.popitem(last=False)
        IMAGE_CACHE_CURRENT_BYTES -= len(evicted_data)

    IMAGE_CACHE[url] = (content, ctype)
    IMAGE_CACHE_CURRENT_BYTES += item_len

def _get_disk_cached_image(url: str) -> Optional[tuple[bytes, str]]:
    try:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        cache_bin = IMAGE_DISK_CACHE_DIR / f"{url_hash}.bin"
        cache_meta = IMAGE_DISK_CACHE_DIR / f"{url_hash}.meta"
        if cache_bin.exists() and cache_meta.exists():
            content = cache_bin.read_bytes()
            ctype = cache_meta.read_text(encoding="utf-8").strip() or "image/jpeg"
            return content, ctype
    except Exception as e:
        logger.debug("[media] Error reading image disk cache: %s", e)
    return None

def _save_disk_cached_image(url: str, content: bytes, ctype: str):
    try:
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        cache_bin = IMAGE_DISK_CACHE_DIR / f"{url_hash}.bin"
        cache_meta = IMAGE_DISK_CACHE_DIR / f"{url_hash}.meta"
        tmp_bin = IMAGE_DISK_CACHE_DIR / f"{url_hash}.bin.tmp.{os.getpid()}"
        tmp_meta = IMAGE_DISK_CACHE_DIR / f"{url_hash}.meta.tmp.{os.getpid()}"
        tmp_bin.write_bytes(content)
        tmp_meta.write_text(ctype, encoding="utf-8")
        os.replace(tmp_bin, cache_bin)
        os.replace(tmp_meta, cache_meta)
    except Exception as e:
        logger.debug("[media] Error writing image disk cache: %s", e)

async def _validate_media_request(request: httpx.Request):
    # HTTPX runs request hooks for every redirect, before sending it.
    await asyncio.to_thread(validate_media_url, str(request.url))
    if not await is_safe_url_async(str(request.url)):
        raise HTTPException(status_code=400, detail="URL non autorisée ou non sécurisée")


def _get_media_async_client(timeout: float = 10.0) -> httpx.AsyncClient:
    return source_http.async_client(timeout=timeout, follow_redirects=True,
                                    url_validator=validate_media_url,
                                    event_hooks={"request": [_validate_media_request]})


@router.api_route('/api/media/extension-resource/{token}', methods=['GET', 'HEAD'])
async def extension_resource(token: str, request: Request):
    from animelab.services.extension_media import extension_media
    from animelab.services.subtitle_service import to_webvtt
    try:
        resource = extension_media.get(token)
    except ValueError as error:
        raise HTTPException(410, str(error)) from error
    headers = dict(resource.headers)
    if request.headers.get('range'):
        headers['Range'] = request.headers['range']
    client = _get_media_async_client(timeout=60)
    stream = client.stream(request.method, resource.url, headers=headers)
    response = None
    handed_off = False
    try:
        response = await stream.__aenter__()
        ctype = response.headers.get('content-type', 'application/octet-stream')
        path = urllib.parse.urlsplit(str(response.url)).path.lower()
        manifest = path.endswith('.m3u8') or 'mpegurl' in ctype.lower()
        if response.status_code >= 400:
            raise HTTPException(response.status_code, 'Ressource média indisponible.')
        output_headers = {'Cache-Control':'private, no-store'}
        for key in ('content-range', 'accept-ranges'):
            if key in response.headers:
                output_headers[key] = response.headers[key]
        if request.method == 'HEAD':
            if 'content-length' in response.headers:
                output_headers['Content-Length'] = response.headers['content-length']
            return Response(status_code=response.status_code, headers=output_headers, media_type=ctype)
        if manifest or resource.kind == 'subtitle':
            body = bytearray()
            async for chunk in response.aiter_bytes():
                body.extend(chunk)
                if len(body) > 8*1024*1024:
                    raise HTTPException(413, 'Playlist ou sous-titre trop volumineux.')
            if manifest:
                content = extension_media.playlist(body.decode('utf-8-sig'), resource, str(response.url))
                ctype = 'application/vnd.apple.mpegurl'
            else:
                content = to_webvtt(body.decode('utf-8-sig'), format_hint=path.rsplit('.', 1)[-1])
                ctype = 'text/vtt'
            return Response(content=content, media_type=ctype, headers=output_headers)
        if path.endswith('.mpd') or 'dash+xml' in ctype.lower():
            raise HTTPException(422, 'La lecture DASH avec en-têtes APK n’est pas encore prise en charge.')
        if 'content-length' in response.headers:
            output_headers['Content-Length'] = response.headers['content-length']
        upstream = response
        async def body_stream():
            try:
                async for chunk in upstream.aiter_bytes():
                    yield chunk
            finally:
                await stream.__aexit__(None, None, None)
                await client.aclose()
        result = StreamingResponse(body_stream(), status_code=response.status_code, media_type=ctype, headers=output_headers)
        response = None  # body_stream now owns the upstream stream and client.
        handed_off = True
        return result
    except ValueError as error:
        raise HTTPException(400, str(error)) from error
    finally:
        if not handed_off:
            if response is not None:
                await stream.__aexit__(None, None, None)
            await client.aclose()

@router.get("/api/media/image-proxy")
async def proxy_image(url: str):
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL d'image invalide")
    await asyncio.to_thread(validate_media_url, url)

    # Protection SSRF
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on image-proxy for URL: %s", url)
        raise HTTPException(status_code=400, detail="URL d'image non autorisée ou non sécurisée")

    # 1. Cache mémoire ultra-rapide (0 ms)
    mem_data = _get_memory_cached_image(url)
    if mem_data:
        content, ctype = mem_data
        return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

    # 2. Cache disque persistant (survit aux redémarrages)
    disk_data = _get_disk_cached_image(url)
    if disk_data:
        content, ctype = disk_data
        _put_memory_cached_image(url, content, ctype)
        return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

    try:
        parsed_url = urllib.parse.urlparse(url)
        host = (parsed_url.hostname or "").lower()
        is_animepahe = any(host == d or host.endswith("." + d) for d in [
            "animepahe.com", "animepahe.org", "animepahe.pw", "animepahe.ru",
            "animepahe.si", "animepahe.su", "kwik.cx", "kwik.si", "kwik.link",
            "kwik.top", "pahe.win", "owocdn.top", "kwikcdn.com"
        ])
        if host in ("themoviedb.org", "image.tmdb.org", "api.themoviedb.org") or host.endswith(".tmdb.org") or host.endswith(".themoviedb.org"):
            referer = "https://www.themoviedb.org/"
        elif is_animepahe:
            referer = f"{settings.ANIMEPAHE_URL}/"
        elif any(host == d or host.endswith("." + d) for d in ["voir-anime.to", "voiranime.to", "voiranime.io", "voiranime.homes", "voembed.net", "vidmoly.to"]):
            referer = "https://voir-anime.to/"
        else:
            referer = "https://french-manga.net/"
            for cs in extension_service.get_enabled_container_sources():
                if cs.base_url:
                    try:
                        cs_host = (urllib.parse.urlparse(cs.base_url).hostname or "").lower()
                        if cs_host and (host == cs_host or host.endswith("." + cs_host)):
                            referer = cs.base_url.rstrip("/") + "/"
                            break
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass

        if is_animepahe and os.getenv('ANIMELAB_SHARED_WORKER') != '1':
            media_data = await animepahe_service.fetch_media_bytes(url, referer=referer)
            if media_data:
                final_bytes, ctype = media_data
                if len(final_bytes) > MAX_IMAGE_SIZE:
                    raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")
                _save_disk_cached_image(url, final_bytes, ctype)
                _put_memory_cached_image(url, final_bytes, ctype)
                return Response(content=final_bytes, media_type=ctype, headers=CACHE_HEADERS)

        headers = {
            "User-Agent": proxy_service.get_user_agent(),
            "Referer": referer,
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        }
        async with _get_media_async_client(timeout=10.0) as client:
            async with client.stream("GET", url, headers=headers) as resp:
                if resp.status_code != 200:
                    raise HTTPException(status_code=resp.status_code, detail="Image inaccessible")

                ctype = resp.headers.get("content-type", "image/jpeg")
                if not (ctype.startswith("image/") or ctype == "application/octet-stream"):
                    raise HTTPException(status_code=400, detail="Le contenu distant n'est pas une image valide")

                clength = resp.headers.get("content-length")
                if clength and int(clength) > MAX_IMAGE_SIZE:
                    raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")

                content = bytearray()
                async for chunk in resp.aiter_bytes(65536):
                    content.extend(chunk)
                    if len(content) > MAX_IMAGE_SIZE:
                        raise HTTPException(status_code=413, detail="Image trop volumineuse (max 10 Mo)")

                final_bytes = bytes(content)
                _save_disk_cached_image(url, final_bytes, ctype)
                _put_memory_cached_image(url, final_bytes, ctype)

                return Response(content=final_bytes, media_type=ctype, headers=CACHE_HEADERS)
    except HTTPException:
        raise
    except VerificationRequired:
        raise
    except Exception as e:
        logger.debug("Error in image-proxy: %s", e)
        raise HTTPException(status_code=502, detail="Erreur proxy image")

def parse_subtitle_paths(path_field: Optional[str]) -> List[str]:
    if not path_field:
        return []
    if path_field.startswith("[") and path_field.endswith("]"):
        try:
            return json.loads(path_field)
        except Exception:
            pass
    return [path_field]

@router.get("/api/media/stream/resolve")
async def resolve_stream(
    animeName: str = Query(...),
    episodeNumber: int = Query(...),
    episodeUrl: str = Query(...),
    animeUrl: Optional[str] = Query(""),
    version: Optional[str] = Query(""),
    source: Optional[str] = Query("voir-anime"),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
):
    """
    Résout le flux de lecture pour un épisode :
    1. Si l'épisode est déjà téléchargé sur le disque dur, renvoie le flux local (/api/media/stream/{task_id}).
    2. S'il n'est pas téléchargé, résout le flux en ligne direct sur les serveurs d'hébergement.
    """
    logger.info("Streaming resolution: %s - Ep %s (source=%s, server=%s, quality=%s)",
                animeName, episodeNumber, source, server, quality)

    # 1. Vérification si l'épisode est déjà téléchargé sur le disque dur
    local_task = await asyncio.to_thread(
        library_service.find_downloaded_episode,
        anime_name=animeName,
        episode_number=episodeNumber,
        version=version or "",
        episode_url=episodeUrl,
    )

    if local_task:
        logger.info("Episode found on hard disk: %s (task_id=%s)", local_task.savePath, local_task.id)
        # Récupérer les sous-titres locaux s'ils existent
        subtitles = []
        try:
            subtitles = await get_subtitles_list(local_task.id)
        except VerificationRequired:
            raise
        except Exception:
            pass

        return {
            "success": True,
            "isDownloaded": True,
            "sourceType": "local",
            "taskId": local_task.id,
            "streamUrl": f"/api/media/stream/{local_task.id}",
            "filePath": local_task.savePath,
            "title": f"{animeName} - Épisode {episodeNumber}",
            "subtitles": subtitles,
            "serverType": "Disque dur (Local)",
            "selectedQuality": "Original (Local)",
            "qualities": {},
        }

    # 2. Épisode non téléchargé -> Résolution du streaming direct sur les serveurs d'hébergement
    logger.info("Episode not downloaded on hard disk. Extracting remote stream...")
    video_url = ""
    server_type = server or "auto"
    selected_quality = quality or "auto"
    qualities_dict: Dict[str, str] = {}
    tracks: List[Dict[str, Any]] = []
    native_media = None

    container_source = None
    if source not in ("voir-anime", "animepahe", "french-manga"):
        container_source = extension_service.get_container_source_by_id(source)
        if not container_source:
            try:
                parsed_ep = urllib.parse.urlparse(episodeUrl)
                ep_host = (parsed_ep.hostname or "").lower()
                if ep_host:
                    for src in extension_service.get_enabled_container_sources():
                        if src.base_url and ep_host in src.base_url.lower():
                            container_source = src
                            break
            except VerificationRequired:
                raise
            except Exception:
                pass

    if container_source:
        try:
            container_sources = await container_source.get_episode_sources(episodeUrl)
        except VerificationRequired:
            raise
        except Exception as e:
            logger.warning("[media] Error getting episode sources from container: %s", e)
            container_sources = []

        if container_sources:
            for idx, vs in enumerate(container_sources):
                srv_name = vs.get("server") if isinstance(vs, dict) else getattr(vs, "server", None)
                q_name = vs.get("quality") if isinstance(vs, dict) else getattr(vs, "quality", None)
                label = srv_name or q_name or f"Serveur {idx + 1}"
                v_url = vs.get("url") if isinstance(vs, dict) else getattr(vs, "url", "")
                if label not in qualities_dict:
                    qualities_dict[label] = v_url

            # Priorité au serveur demandé s'il est spécifié
            candidates = list(container_sources)
            if server and server != "auto":
                matched = [
                    cs for cs in container_sources
                    if (cs.get("server") if isinstance(cs, dict) else getattr(cs, "server", "")).lower() == server.lower()
                    or (cs.get("name") if isinstance(cs, dict) else getattr(cs, "name", "")).lower() == server.lower()
                ]
                if matched:
                    candidates = matched + [cs for cs in container_sources if cs not in matched]

            for cand in candidates:
                cand_url = cand.get("url") if isinstance(cand, dict) else getattr(cand, "url", "")
                cand_srv = cand.get("server") if isinstance(cand, dict) else getattr(cand, "server", "imported")
                cand_q = cand.get("quality") if isinstance(cand, dict) else getattr(cand, "quality", "HD")

                if not cand_url:
                    continue

                try:
                    if getattr(container_source, 'runtime', '') == 'android-apk':
                        resolved = await container_source.resolve_candidate(cand)
                    else:
                        resolved = await download_manager.resolve_imported_video_stream(
                            cand_url, referer=episodeUrl, preferred_quality=quality or cand_q)
                    if resolved and resolved.get("videoUrl"):
                        if getattr(container_source, 'runtime', '') == 'android-apk':
                            native_media = resolved
                        video_url = resolved["videoUrl"]
                        server_type = resolved.get("serverType") or cand_srv
                        selected_quality = resolved.get("selectedQuality") or cand_q or "HD"
                        break
                except VerificationRequired:
                    raise
                except Exception as ex:
                    logger.debug("[media] Error resolving candidate %s: %s", cand_url, ex)

        # Si toujours non résolu, tenter directement sur episodeUrl
        if not video_url and episodeUrl and getattr(container_source, 'runtime', '') != 'android-apk':
            try:
                resolved = await download_manager.resolve_imported_video_stream(
                    episodeUrl,
                    referer=episodeUrl,
                    preferred_quality=quality,
                )
                if resolved and resolved.get("videoUrl"):
                    video_url = resolved["videoUrl"]
                    server_type = resolved.get("serverType") or (container_source.name if container_source else "imported")
                    selected_quality = resolved.get("selectedQuality") or "HD"
            except VerificationRequired:
                raise
            except Exception as ex:
                logger.debug("[media] Error resolving direct episodeUrl fallback: %s", ex)
    elif source == "voir-anime":
        pref_srv = server if (server and server != "auto") else None
        pref_q = quality if (quality and quality != "auto") else None
        info = await asyncio.to_thread(
            voiranime_service.extract_download_info,
            episodeUrl,
            preferred_server=pref_srv,
            preferred_quality=pref_q,
        )
        video_url = info.get("videoUrl") or ""
        server_type = info.get("serverType") or server_type
        selected_quality = info.get("selectedQuality") or selected_quality
        raw_qualities = info.get("videoQualities")
        if isinstance(raw_qualities, str):
            try:
                qualities_dict = json.loads(raw_qualities)
            except VerificationRequired:
                raise
            except Exception:
                qualities_dict = {}
        elif isinstance(raw_qualities, dict):
            qualities_dict = raw_qualities

        sub_url = info.get("subtitleUrl")
        if sub_url:
            tracks.append({
                "kind": "captions",
                "label": "Français",
                "srclang": "fr",
                "src": f"/api/media/subtitle-proxy?url={urllib.parse.quote(sub_url)}",
                "default": True,
            })
    elif source == "animepahe" or "animepahe" in episodeUrl or "kwik." in episodeUrl or "pahe." in episodeUrl:
        # AnimePahe
        server_type = "kwik"
        pref_srv = server if (server and server != "auto") else None
        pref_q = quality if (quality and quality != "auto") else None

        if ("kwik." in episodeUrl or "pahe." in episodeUrl) and ("/e/" in episodeUrl or "/d/" in episodeUrl):
            extracted = await animepahe_service.extract_kwik_stream(episodeUrl)
            if extracted:
                video_url = extracted
                selected_quality = pref_q or "HD"
        elif pref_srv and ("kwik." in pref_srv or "pahe." in pref_srv):
            extracted = await animepahe_service.extract_kwik_stream(pref_srv)
            if extracted:
                video_url = extracted
                selected_quality = pref_q or "HD"
        else:
            sources = await animepahe_service.get_episode_sources(episodeUrl)
            if sources:
                target_src = None
                for s in sources:
                    q_label = s.get("name") or f"{s.get('quality', 'HD')} ({s.get('audio', 'sub')})"
                    kwik_link = s.get("url", "")
                    qualities_dict[q_label] = kwik_link
                    if pref_q and (pref_q.lower() in q_label.lower() or pref_q.lower() in s.get("quality", "").lower()):
                        if not target_src:
                            target_src = s

                if not target_src and sources:
                    target_src = sources[0]

                if target_src:
                    selected_quality = target_src.get("name") or target_src.get("quality", "HD")
                    target_kwik_url = target_src.get("url", "")
                    if target_kwik_url:
                        video_url = await animepahe_service.extract_kwik_stream(target_kwik_url) or ""
    elif source == "french-manga" or "french-manga" in episodeUrl:
        # french-manga
        info = await asyncio.to_thread(scraping_service.extract_download_info, episodeUrl)
        video_url = info.get("videoUrl") or info.get("directUrl") or ""
        server_type = "vidzy"
        sub_url = info.get("subtitleUrl")
        if sub_url:
            tracks.append({
                "kind": "captions",
                "label": "Français",
                "srclang": "fr",
                "src": f"/api/media/subtitle-proxy?url={urllib.parse.quote(sub_url)}",
                "default": True,
            })
    else:
        # Source générique ou importée non matchée par id
        try:
            resolved = await download_manager.resolve_imported_video_stream(
                episodeUrl,
                referer=episodeUrl,
                preferred_quality=quality,
            )
            if resolved and resolved.get("videoUrl"):
                video_url = resolved["videoUrl"]
                server_type = resolved.get("serverType") or "imported"
                selected_quality = resolved.get("selectedQuality") or "HD"
        except VerificationRequired:
            raise
        except Exception as ex:
            logger.debug("[media] Generic resolve error: %s", ex)

    if not video_url:
        logger.warning("No direct video stream found for remote episode: %s", episodeUrl)
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "Impossible de trouver un flux vidéo direct sur les serveurs d'hébergement.",
                "isDownloaded": False,
                "sourceType": "remote",
                "serverType": server_type,
            }
        )

    # Si le flux provient de Kwik / Owocdn HLS, le router via le proxy HLS local
    if native_media:
        from animelab.services.extension_media import extension_media
        if native_media.get('unsupportedArguments'):
            raise HTTPException(422, 'Cette vidéo exige des options de lecteur non prises en charge.')
        if urllib.parse.urlsplit(video_url).path.lower().endswith('.mpd'):
            raise HTTPException(422, 'La lecture DASH avec en-têtes APK exige un lecteur compatible.')
        if native_media.get('audioTracks'):
            raise HTTPException(422, 'La lecture de pistes audio APK séparées n’est pas encore prise en charge.')
        video_url = extension_media.issue(video_url, native_media['headers'])
        tracks = [{'kind':'captions', 'label':track['label'], 'srclang':track['lang'],
                   'src':extension_media.issue(track['url'], {**native_media['headers'], **track['headers']}, kind='subtitle'),
                   'default':index==0} for index, track in enumerate(native_media['subtitles'])]
        qualities_dict = {}  # Selecting a new quality must rerun the actual source callback.
    elif video_url and (".m3u8" in video_url.lower()) and any(d in video_url for d in ["owocdn.top", "kwik"]):
        video_url = f"/api/media/hls-proxy/playlist.m3u8?url={urllib.parse.quote(video_url)}"
    elif (
        video_url
        and video_url.startswith("http")
        and not video_url.lower().endswith(".m3u8")
        and ".m3u8" not in video_url.lower()
        and source != "animepahe"
        and not (source == "voir-anime" and server_type == "myTV")
    ):
        # Router les flux vidéo distants (MP4, WebM...) via le proxy de streaming pour injecter les bons referers et headers
        # et garantir le fonctionnement fluide des Range requests (seeking) sans blocage CORS / 403
        video_url = f"/api/media/stream-proxy?url={urllib.parse.quote(video_url)}&server={urllib.parse.quote(server_type or 'imported')}"

    return {
        "success": True,
        "isDownloaded": False,
        "sourceType": "remote",
        "streamUrl": video_url,
        "serverType": server_type,
        "selectedQuality": selected_quality,
        "qualities": qualities_dict,
        "title": f"{animeName} - Épisode {episodeNumber}",
        "subtitles": tracks,
    }

@router.api_route("/api/media/stream/{task_id}", methods=["GET", "HEAD"])
async def stream_video(task_id: str, request: Request, range: Optional[str] = Header(None)):
    task = download_manager.get_task(task_id)
    if not task or not task.savePath:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    file_path = Path(task.savePath)
    # Protection Path Traversal
    if not is_safe_path(file_path):
        logger.warning("Path Traversal blocked on streaming: %s", file_path)
        raise HTTPException(status_code=403, detail="Accès refusé : fichier hors du répertoire autorisé")

    if not file_path.is_file():
        raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque")

    file_size = file_path.stat().st_size
    content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

    # Media players may probe metadata without downloading the video body.
    if request.method == "HEAD":
        return Response(media_type=content_type, headers={
            "Content-Length": str(file_size), "Accept-Ranges": "bytes",
        })

    if not range:
        def iter_full():
            with open(file_path, "rb") as f:
                while chunk := f.read(65536):
                    yield chunk

        return StreamingResponse(
            iter_full(),
            media_type=content_type,
            headers={
                "Content-Length": str(file_size),
                "Accept-Ranges": "bytes",
            }
        )

    # HTTP Range handling: "bytes=0-1024" or "bytes=1024-"
    range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", range.strip())
    if not range_match or not any(range_match.groups()) or file_size == 0:
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})

    first, last = range_match.groups()
    if first:
        start = int(first)
        end = min(int(last), file_size - 1) if last else file_size - 1
    else:
        suffix_length = int(last)
        start = max(0, file_size - suffix_length)
        end = file_size - 1

    if start >= file_size or start > end:
        return Response(
            status_code=416,
            headers={"Content-Range": f"bytes */{file_size}"}
        )

    content_length = end - start + 1

    def iter_range():
        with open(file_path, "rb") as f:
            f.seek(start)
            remaining = content_length
            chunk_size = 65536
            while remaining > 0:
                to_read = min(chunk_size, remaining)
                data = f.read(to_read)
                if not data:
                    break
                remaining -= len(data)
                yield data

    return StreamingResponse(
        iter_range(),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        }
    )

@router.get("/api/media/subtitles/{task_id}")
async def get_subtitles_list(task_id: str):
    task = download_manager.get_task(task_id)
    if not task or not task.savePathSubtitle:
        return []

    paths = parse_subtitle_paths(task.savePathSubtitle)
    result = []

    video_stem = Path(task.savePath).stem if task.savePath else ""
    metadata = {item['path']: item for item in json.loads(task.mediaJson).get('outputState', {}).get('sidecarTracks', [])}
    for idx, p in enumerate(paths):
        sf = Path(p)
        if sf.exists():
            lbl = sf.name.replace(video_stem, "").strip(".")
            if not lbl:
                lbl = f"Sous-titres {idx + 1}"
            track = metadata.get(str(sf), {})
            lbl = track.get('label') or lbl
            lang = track.get('lang') or ("fr" if "fr" in lbl.lower() else "und")
            result.append({
                "label": lbl,
                "srclang": lang,
                "src": f"/api/media/subtitle/{task_id}/{idx}",
                "default": bool(track.get('default')),
            })

    return result

@router.get("/api/media/subtitle/{task_id}")
async def stream_subtitle_default(task_id: str):
    return await stream_subtitle_at_index(task_id, 0)

@router.get("/api/media/subtitle/{task_id}/{index}")
async def stream_subtitle_at_index(task_id: str, index: int):
    task = download_manager.get_task(task_id)
    if not task or not task.savePathSubtitle:
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")

    paths = parse_subtitle_paths(task.savePathSubtitle)
    if index < 0 or index >= len(paths):
        raise HTTPException(status_code=404, detail="Index de sous-titre invalide")

    file_path = Path(paths[index])
    if not is_safe_path(file_path):
        logger.warning("Path Traversal blocked on subtitles: %s", file_path)
        raise HTTPException(status_code=403, detail="Accès refusé : fichier de sous-titres hors du répertoire autorisé")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="Fichier de sous-titres introuvable")

    content_type = "text/vtt"
    if file_path.suffix == ".srt":
        content_type = "text/srt"
    elif file_path.suffix == ".ass":
        content_type = "text/ass"

    return FileResponse(path=file_path, media_type=content_type)

@router.get("/api/media/subtitle-proxy")
async def proxy_subtitle(url: str = Query(...)):
    """
    Proxy pour sous-titres distants avec en-têtes CORS universels pour HTML5 <track>.
    """
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL de sous-titre invalide")
    await asyncio.to_thread(validate_media_url, url)
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on subtitle-proxy: %s", url)
        raise HTTPException(status_code=400, detail="URL de sous-titre non autorisée")

    headers = {
        "User-Agent": proxy_service.get_user_agent(),
        "Referer": "https://voir-anime.to/" if "voir-anime" in url else "https://vidzy.org/",
    }
    try:
        async with _get_media_async_client(timeout=10.0) as client:
            resp = await client.get(url, headers=headers)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Sous-titres distants inaccessibles")
            content = resp.text
            content_type = "text/vtt; charset=utf-8" if "WEBVTT" in content.upper() else "text/plain; charset=utf-8"
            return Response(
                content=content,
                media_type=content_type,
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Cache-Control": "public, max-age=86400",
                }
            )
    except HTTPException:
        raise
    except VerificationRequired:
        raise
    except Exception as e:
        logger.debug("Error in subtitle-proxy: %s", e)
        raise HTTPException(status_code=502, detail="Erreur lors de la récupération des sous-titres")


HLS_KEY_CACHE: Dict[str, bytes] = {}

@router.api_route("/api/media/hls-proxy/playlist.m3u8", methods=["GET", "HEAD"])
async def hls_proxy_playlist(request: Request, url: str = Query(...)):
    """
    Proxy M3U8 pour Kwik / Owocdn :
    - Récupère la playlist avec impersonation TLS Chrome
    - Extrait et met en cache la clé AES-128
    - Retire la directive #EXT-X-KEY (le déchiffrement sera fait par segment.ts)
    - Réécrit les segments vers /api/media/hls-proxy/segment.ts
    """
    await asyncio.to_thread(validate_media_url, url)
    if request.method == "HEAD":
        return Response(content=b"", media_type="application/vnd.apple.mpegurl", headers={"Access-Control-Allow-Origin": "*"})

    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL HLS invalide")
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on hls-proxy/playlist: %s", url)
        raise HTTPException(status_code=400, detail="URL non autorisée")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://kwik.cx/",
    }

    try:
        async with _get_media_async_client(timeout=20.0) as session:
            resp = await session.get(url, headers=headers, timeout=20.0)
            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Échec récupération playlist HLS")

            m3u8_text = resp.text
            key_url = ""
            m_key = re.search(r'#EXT-X-KEY:METHOD=AES-128,URI="([^"]+)"', m3u8_text)
            if m_key:
                key_url = urllib.parse.urljoin(url, m_key.group(1))
                await asyncio.to_thread(validate_media_url, key_url)
                if key_url not in HLS_KEY_CACHE:
                    r_k = await session.get(key_url, headers=headers, timeout=15.0)
                    if r_k.status_code == 200 and len(r_k.content) == 16:
                        HLS_KEY_CACHE[key_url] = r_k.content

            lines = []
            seq = 1
            for line in m3u8_text.splitlines():
                s = line.strip()
                if not s:
                    continue
                if s.startswith("#EXT-X-MEDIA-SEQUENCE"):
                    try:
                        seq = int(s.split(":")[-1])
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass
                    lines.append(line)
                elif s.startswith("#EXT-X-KEY"):
                    # Omission : déchiffrement transparent assuré par le proxy
                    continue
                elif not s.startswith("#"):
                    seg_abs = urllib.parse.urljoin(url, s)
                    await asyncio.to_thread(validate_media_url, seg_abs)
                    key_param = f"&key={urllib.parse.quote(key_url)}" if key_url else ""
                    seg_proxy = f"/api/media/hls-proxy/segment.ts?url={urllib.parse.quote(seg_abs)}{key_param}&seq={seq}"
                    lines.append(seg_proxy)
                    seq += 1
                else:
                    lines.append(line)

            data = "\n".join(lines).encode("utf-8")
            return Response(
                content=data,
                media_type="application/vnd.apple.mpegurl",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Cache-Control": "no-cache",
                    "Content-Length": str(len(data)),
                }
            )
    except HTTPException:
        raise
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error("Error in hls_proxy_playlist: %s", e)
        raise HTTPException(status_code=502, detail="Erreur proxying playlist HLS")


@router.api_route("/api/media/hls-proxy/segment.ts", methods=["GET", "HEAD"])
async def hls_proxy_segment(
    request: Request,
    url: str = Query(...),
    key: Optional[str] = Query(None),
    seq: int = Query(1),
):
    """
    Proxy pour les segments vidéo :
    - Télécharge les chunks .jpg chiffrés via curl_cffi Chrome
    - Déchiffre en AES-128-CBC
    - Retourne les octets propres MPEG-TS (video/MP2T)
    """
    await asyncio.to_thread(validate_media_url, url)
    if key:
        await asyncio.to_thread(validate_media_url, key)
    if request.method == "HEAD":
        return Response(
            content=b"",
            media_type="video/MP2T",
            headers={
                "Content-Length": "550000",
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            }
        )

    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL de segment invalide")
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on hls-proxy/segment: %s", url)
        raise HTTPException(status_code=400, detail="URL non autorisée")

    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36",
        "Referer": "https://kwik.cx/",
    }

    try:
        # Session rapide sans surcoût d'impersonation (téléchargement 2x plus rapide sur les CDN)
        async with _get_media_async_client(timeout=120.0) as session:
            resp = await session.get(url, headers=headers, timeout=120.0)

            if resp.status_code != 200:
                raise HTTPException(status_code=resp.status_code, detail="Échec récupération segment")

            seg_bytes = resp.content

            if key:
                key_bytes = HLS_KEY_CACHE.get(key)
                if not key_bytes:
                    r_k = await session.get(key, headers=headers, timeout=15.0)
                    if r_k.status_code == 200 and len(r_k.content) == 16:
                        key_bytes = r_k.content
                        HLS_KEY_CACHE[key] = key_bytes

                if key_bytes and len(key_bytes) == 16:
                    from animelab.media_tools import decrypt_aes_cbc
                    iv = seq.to_bytes(16, "big")
                    seg_bytes = decrypt_aes_cbc(seg_bytes, key_bytes, iv)

            return Response(
                content=seg_bytes,
                media_type="video/MP2T",
                headers={
                    "Access-Control-Allow-Origin": "*",
                    "Access-Control-Allow-Methods": "GET, OPTIONS",
                    "Content-Length": str(len(seg_bytes)),
                }
            )
    except HTTPException:
        raise
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error("Error in hls_proxy_segment: %s", e)
        raise HTTPException(status_code=502, detail="Erreur proxying segment")


@router.api_route("/api/media/stream-proxy", methods=["GET", "HEAD", "OPTIONS"])
async def stream_proxy(
    request: Request,
    url: str = Query(...),
    server: Optional[str] = Query(None),
    referer: Optional[str] = Query(None),
    range: Optional[str] = Header(None),
):
    """
    Proxy universel de flux vidéo distant :
    - Injecte les en-têtes requis (Referer, User-Agent) via extractor_registry
    - Gère les requêtes HTTP Range pour le scrubbing / seeking fluide dans le lecteur
    - Évite les blocages CORS et 403 Forbidden des hébergeurs vidéo (Sibnet, Sendvid, Vidmoly, etc.)
    """
    await asyncio.to_thread(validate_media_url, url)
    if request.method == "OPTIONS":
        return Response(
            status_code=200,
            headers={
                "Access-Control-Allow-Origin": "*",
                "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
                "Access-Control-Allow-Headers": "Range, Content-Range, Accept-Ranges, Content-Type",
                "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
            },
        )

    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL de flux vidéo invalide")

    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on stream-proxy: %s", url)
        raise HTTPException(status_code=400, detail="URL non autorisée ou non sécurisée")

    upstream_headers = extractor_registry.get_headers_for_url(url, server)
    if referer:
        upstream_headers["Referer"] = referer
    if range:
        upstream_headers["Range"] = range

    proxy = proxy_service.get_active_proxy()
    client = source_http.async_client(
        timeout=httpx.Timeout(connect=15.0, read=60.0, write=15.0, pool=60.0),
        follow_redirects=True,
        verify=settings.SSL_VERIFY,
        proxy=proxy,
        url_validator=validate_media_url,
        event_hooks={"request": [_validate_media_request]},
    )

    if request.method == "HEAD":
        try:
            head_resp = await client.head(url, headers=upstream_headers)
            if head_resp.status_code not in (200, 206):
                # Certains hébergeurs (ex: Sibnet) refusent HEAD -> repli Range: bytes=0-0
                head_resp = await client.get(url, headers={**upstream_headers, "Range": "bytes=0-0"})
        except HTTPException:
            raise
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("[stream-proxy] HEAD failed for %s, trying GET range: %s", url, e)
            head_resp = await client.get(url, headers={**upstream_headers, "Range": "bytes=0-0"})
        finally:
            await client.aclose()

        resp_headers = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Range, Accept-Ranges, Content-Type",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        }
        if "content-range" in head_resp.headers:
            resp_headers["Content-Range"] = head_resp.headers["content-range"]
        if "content-length" in head_resp.headers:
            resp_headers["Content-Length"] = head_resp.headers["content-length"]
        c_type = head_resp.headers.get("content-type") or "video/mp4"
        return Response(status_code=head_resp.status_code, headers=resp_headers, media_type=c_type)

    try:
        req = client.build_request("GET", url, headers=upstream_headers)
        upstream_resp = await client.send(req, stream=True)

        if upstream_resp.status_code not in (200, 206):
            status = upstream_resp.status_code
            await upstream_resp.aclose()
            await client.aclose()
            raise HTTPException(status_code=status, detail="Erreur du serveur d'hébergement vidéo")

        async def stream_generator():
            try:
                async for chunk in upstream_resp.aiter_bytes(chunk_size=65536):
                    yield chunk
            finally:
                await upstream_resp.aclose()
                await client.aclose()

        resp_headers = {
            "Accept-Ranges": "bytes",
            "Access-Control-Allow-Origin": "*",
            "Access-Control-Allow-Methods": "GET, HEAD, OPTIONS",
            "Access-Control-Allow-Headers": "Range, Content-Range, Accept-Ranges, Content-Type",
            "Access-Control-Expose-Headers": "Content-Range, Content-Length, Accept-Ranges",
        }
        if "content-range" in upstream_resp.headers:
            resp_headers["Content-Range"] = upstream_resp.headers["content-range"]
        if "content-length" in upstream_resp.headers:
            resp_headers["Content-Length"] = upstream_resp.headers["content-length"]
        c_type = upstream_resp.headers.get("content-type") or "video/mp4"

        return StreamingResponse(
            stream_generator(),
            status_code=upstream_resp.status_code,
            media_type=c_type,
            headers=resp_headers,
        )
    except HTTPException:
        await client.aclose()
        raise
    except VerificationRequired:
        raise
    except Exception as e:
        await client.aclose()
        logger.error("[stream-proxy] Error streaming %s: %s", url, e)
        raise HTTPException(status_code=502, detail="Erreur proxying flux vidéo")


