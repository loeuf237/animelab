from animelab.api_contracts import ContractRoute
from animelab.api_errors import APIProblem
from animelab.services.source_http import source_http, VerificationRequired
import asyncio
import json
import logging
import mimetypes
import re
import urllib.parse
from pathlib import Path
from typing import List, Dict, Any, Literal, Optional
from fastapi import APIRouter, Request, Header, HTTPException, Response, Query
from fastapi.responses import StreamingResponse, FileResponse, JSONResponse
from pydantic import BaseModel, ConfigDict, Field

import httpx
from animelab import config as app_config, platform_events
from animelab.config import settings
from animelab.security import is_safe_url, is_safe_url_async, is_safe_path
from animelab.media_policy import validate_media_url
from animelab.routers.network import is_local
from animelab.services.download_manager import download_manager
from animelab.services.external_player import (
    append_media_ticket,
    build_player_command,
    external_media_tickets,
    external_player,
    extract_local_task_id,
    local_loopback_origin,
    sanitize_title,
    spawn_desktop_player,
    valid_ticket_format,
    validate_local_media_url,
)
from animelab.services.proxy_service import proxy_service
from animelab.services.library_service import library_service
from animelab.services.local_media import discover_sidecar_subtitles, local_media
from animelab.services.voiranime_service import voiranime_service, normalize_voiranime_url
from animelab.services.scraping_service import scraping_service
from animelab.services.french_stream_service import (
    french_stream_service,
    is_french_stream_host,
    is_french_stream_url,
)
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
MAX_IMAGE_DISK_CACHE_BYTES = 50 * 1024 * 1024
MAX_IMAGE_DISK_CACHE_FILES = 400
MAX_IMAGE_SIZE = 10 * 1024 * 1024  # 10 Mo max pour prévenir les attaques OOM
CACHE_HEADERS = {"Cache-Control": "public, max-age=604800, immutable"}
_IMAGE_FETCH_LOCKS: dict[tuple[int, str], list[Any]] = {}

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

def _prune_disk_image_cache():
    try:
        entries = []
        total_bytes = 0
        for bin_path in IMAGE_DISK_CACHE_DIR.glob("*.bin"):
            try:
                stat = bin_path.stat()
                total_bytes += stat.st_size
                entries.append((stat.st_mtime, stat.st_size, bin_path))
            except OSError:
                continue
        if len(entries) <= MAX_IMAGE_DISK_CACHE_FILES and total_bytes <= MAX_IMAGE_DISK_CACHE_BYTES:
            return
        entries.sort(key=lambda item: item[0])
        count = len(entries)
        for _, size, bin_path in entries:
            if count <= MAX_IMAGE_DISK_CACHE_FILES and total_bytes <= MAX_IMAGE_DISK_CACHE_BYTES:
                break
            bin_path.unlink(missing_ok=True)
            bin_path.with_suffix(".meta").unlink(missing_ok=True)
            total_bytes -= size
            count -= 1
    except Exception as e:
        logger.debug("[media] Error pruning image disk cache: %s", e)


def _save_disk_cached_image(url: str, content: bytes, ctype: str):
    try:
        IMAGE_DISK_CACHE_DIR.mkdir(parents=True, exist_ok=True)
        url_hash = hashlib.sha256(url.encode()).hexdigest()
        cache_bin = IMAGE_DISK_CACHE_DIR / f"{url_hash}.bin"
        cache_meta = IMAGE_DISK_CACHE_DIR / f"{url_hash}.meta"
        tmp_bin = IMAGE_DISK_CACHE_DIR / f"{url_hash}.bin.tmp.{os.getpid()}"
        tmp_meta = IMAGE_DISK_CACHE_DIR / f"{url_hash}.meta.tmp.{os.getpid()}"
        tmp_bin.write_bytes(content)
        tmp_meta.write_text(ctype, encoding="utf-8")
        os.replace(tmp_bin, cache_bin)
        os.replace(tmp_meta, cache_meta)
        _prune_disk_image_cache()
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
                params = getattr(request, 'query_params', {}) or {}
                ticket = valid_ticket_format(params.get('media_ticket'))
                suffix = f'?media_ticket={ticket}' if ticket else ''
                content = extension_media.playlist(
                    body.decode('utf-8-sig'), resource, str(response.url), query_suffix=suffix
                )
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

def _validate_image_url_policy(url: str, *, require_dns: bool) -> None:
    if require_dns:
        validate_media_url(url)
        return
    try:
        validate_media_url(url, require_dns=False)
    except TypeError:
        # Preserve compatibility with callers/tests monkeypatching validate_media_url as 1-arg lambda.
        validate_media_url(url)


@router.get("/api/media/image-proxy")
async def proxy_image(url: str):
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL d'image invalide")
    url = normalize_voiranime_url(url)
    # Enforce domain & literal policy before checking local caches so
    # unapproved shared-mode URLs never leak cached items offline.
    await asyncio.to_thread(_validate_image_url_policy, url, require_dns=False)

    # 1. Cache mémoire ultra-rapide (0 ms)
    mem_data = _get_memory_cached_image(url)
    if mem_data:
        content, ctype = mem_data
        return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

    # 2. Cache disque persistant (survit aux redémarrages et mode hors ligne)
    disk_data = _get_disk_cached_image(url)
    if disk_data:
        content, ctype = disk_data
        _put_memory_cached_image(url, content, ctype)
        return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

    # Protection SSRF DNS sur cache miss avant toute requête réseau sortante
    await asyncio.to_thread(validate_media_url, url)
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on image-proxy for URL: %s", url)
        raise HTTPException(status_code=400, detail="URL d'image non autorisée ou non sécurisée")

    lock_key = (id(asyncio.get_running_loop()), url)
    lock_entry = _IMAGE_FETCH_LOCKS.get(lock_key)
    if lock_entry is None:
        lock_entry = [asyncio.Lock(), 0]
        _IMAGE_FETCH_LOCKS[lock_key] = lock_entry
    lock_entry[1] += 1
    try:
        async with lock_entry[0]:
            mem_data = _get_memory_cached_image(url)
            if mem_data:
                content, ctype = mem_data
                return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

            disk_data = _get_disk_cached_image(url)
            if disk_data:
                content, ctype = disk_data
                _put_memory_cached_image(url, content, ctype)
                return Response(content=content, media_type=ctype, headers=CACHE_HEADERS)

            parsed_url = urllib.parse.urlparse(url)
            host = (parsed_url.hostname or "").lower()
            is_animepahe = any(host == d or host.endswith("." + d) for d in [
                "animepahe.com", "animepahe.org", "animepahe.pw", "animepahe.ru",
                "animepahe.si", "animepahe.su", "kwik.cx", "kwik.si", "kwik.link",
                "kwik.top", "pahe.win", "owocdn.top", "kwikcdn.com"
            ])
            va_host = (urllib.parse.urlparse(settings.VOIR_ANIME_URL).hostname or "").lower()
            va_domains = ["voiranime.cx", "voir-anime.to", "voiranime.to", "voiranime.io", "voiranime.homes", "voembed.net", "vidmoly.to"]
            if va_host and va_host not in va_domains:
                va_domains.append(va_host)
            if host in ("themoviedb.org", "image.tmdb.org", "api.themoviedb.org") or host.endswith(".tmdb.org") or host.endswith(".themoviedb.org"):
                referer = "https://www.themoviedb.org/"
            elif is_animepahe:
                referer = f"{settings.ANIMEPAHE_URL}/"
            elif any(host == d or host.endswith("." + d) for d in va_domains):
                referer = f"{settings.VOIR_ANIME_URL.rstrip('/')}/"
            elif is_french_stream_host(host):
                referer = f"{french_stream_service.base_url.rstrip('/')}/"
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
    finally:
        lock_entry[1] -= 1
        if lock_entry[1] <= 0 and _IMAGE_FETCH_LOCKS.get(lock_key) is lock_entry:
            _IMAGE_FETCH_LOCKS.pop(lock_key, None)

def parse_subtitle_paths(path_field: Optional[str]) -> List[str]:
    if not path_field:
        return []
    if path_field.startswith("[") and path_field.endswith("]"):
        try:
            return json.loads(path_field)
        except Exception:
            pass
    return [path_field]


def _exported_android_uris(task) -> list[str]:
    try:
        raw = json.loads(getattr(task, "exportUrisJson", "[]") or "[]")
        if isinstance(raw, list):
            return [u for u in raw if isinstance(u, str) and u.startswith("content://")]
    except (TypeError, ValueError):
        pass
    return []


def _resolve_local_media_record(task_id: str):
    """Resolve a task from active download manager, persisted DB rows, or disk registry."""
    task = download_manager.get_task(task_id)
    if task is not None:
        return task
    try:
        entity = library_service.get_task_entity(task_id)
        if entity is not None:
            return entity.to_task()
    except Exception:
        pass
    return local_media.get(task_id)


def _is_task_record_playable(task) -> bool:
    save_path = getattr(task, "savePath", None)
    if save_path:
        path = Path(save_path)
        if is_safe_path(path):
            try:
                if path.is_file() and path.stat().st_size > 0:
                    return True
            except OSError:
                pass
    for uri in _exported_android_uris(task):
        if platform_events.exported_copy_exists(uri) is True:
            return True
    return False


def _subtitle_content_type(suffix: str) -> str:
    ext = suffix.lower()
    if ext == ".srt":
        return "text/srt"
    if ext == ".ass":
        return "text/ass"
    if ext == ".ssa":
        return "text/ssa"
    return "text/vtt"


def _read_exported_bytes(uri: str, offset: int, total_bytes: int, chunk_size: int = 262144):
    pos = offset
    remaining = total_bytes
    while remaining > 0:
        data = platform_events.read_exported_copy(uri, pos, min(chunk_size, remaining))
        if not data:
            break
        pos += len(data)
        remaining -= len(data)
        yield data


def _serve_byte_stream(
    *,
    request: Request,
    range_header: Optional[str],
    file_size: int,
    content_type: str,
    iter_full,
    iter_range,
) -> Response:
    if request.method == "HEAD":
        return Response(
            media_type=content_type,
            headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"},
        )
    if not range_header:
        return StreamingResponse(
            iter_full(),
            media_type=content_type,
            headers={"Content-Length": str(file_size), "Accept-Ranges": "bytes"},
        )
    range_match = re.fullmatch(r"bytes=(\d*)-(\d*)", range_header.strip())
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
        return Response(status_code=416, headers={"Content-Range": f"bytes */{file_size}"})
    content_length = end - start + 1
    return StreamingResponse(
        iter_range(start, content_length),
        status_code=206,
        media_type=content_type,
        headers={
            "Content-Range": f"bytes {start}-{end}/{file_size}",
            "Accept-Ranges": "bytes",
            "Content-Length": str(content_length),
        },
    )


@router.get("/api/media/stream/resolve")
async def resolve_stream(
    animeName: str = Query(...),
    episodeNumber: int = Query(...),
    episodeUrl: str = Query(""),
    animeUrl: Optional[str] = Query(""),
    version: Optional[str] = Query(""),
    source: Optional[str] = Query("voir-anime"),
    server: Optional[str] = Query(None),
    quality: Optional[str] = Query(None),
    taskId: Optional[str] = Query(None),
):
    """
    Résout le flux de lecture pour un épisode :
    1. Si l'épisode est déjà téléchargé sur le disque dur, renvoie le flux local (/api/media/stream/{task_id}).
    2. S'il n'est pas téléchargé, résout le flux en ligne direct sur les serveurs d'hébergement.
    """
    logger.info("Streaming resolution: %s - Ep %s (source=%s, server=%s, quality=%s)",
                animeName, episodeNumber, source, server, quality)

    # 1. Vérification si l'épisode est déjà téléchargé (taskId explicite, base de données ou disque dur)
    local_task = None
    if taskId:
        candidate = await asyncio.to_thread(_resolve_local_media_record, taskId)
        if candidate is not None and await asyncio.to_thread(_is_task_record_playable, candidate):
            local_task = candidate

    if local_task is None:
        local_task = await asyncio.to_thread(
            library_service.find_downloaded_episode,
            anime_name=animeName,
            episode_number=episodeNumber,
            version=version or "",
            episode_url=episodeUrl,
            anime_url=animeUrl or "",
            source=source or "",
        )

    if local_task is None:
        local_task = await asyncio.to_thread(
            local_media.find_and_register,
            anime_name=animeName,
            episode_number=episodeNumber,
            version=version or "",
            anime_url=animeUrl or "",
            source=source or "",
        )

    if local_task:
        logger.info("Episode found locally: %s (task_id=%s)", local_task.savePath or local_task.fileName, local_task.id)
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
            "isHls": False,
            "sourceType": "local",
            "taskId": local_task.id,
            "streamUrl": f"/api/media/stream/{local_task.id}",
            "filePath": local_task.savePath or "",
            "title": f"{animeName} - Épisode {episodeNumber}",
            "subtitles": subtitles,
            "serverType": "Disque dur (Local)",
            "selectedQuality": "Original (Local)",
            "qualities": {},
        }

    if not (episodeUrl or "").strip():
        return JSONResponse(
            status_code=404,
            content={
                "success": False,
                "error": "Aucun lien de streaming disponible pour cet épisode.",
                "isDownloaded": False,
                "sourceType": "remote",
                "serverType": server or "auto",
            },
        )

    # 2. Épisode non téléchargé -> Résolution du streaming direct sur les serveurs d'hébergement
    logger.info("Episode not downloaded on hard disk. Extracting remote stream...")
    video_url = ""
    server_type = server or "auto"
    selected_quality = quality or "auto"
    qualities_dict: Dict[str, str] = {}
    available_servers: List[str] = []
    tracks: List[Dict[str, Any]] = []
    native_media = None

    container_source = None
    if source not in ("voir-anime", "animepahe", "french-manga", "french-stream"):
        container_source = extension_service.get_container_source_by_id(source)
        if not container_source:
            try:
                from animelab.services.seanime_service import seanime_service
                if source:
                    container_source = seanime_service.get_source_by_id(source)
                else:
                    parsed_ep = urllib.parse.urlparse(episodeUrl)
                    ep_host = (parsed_ep.hostname or "").lower()
                    for s_src in seanime_service.get_enabled_sources():
                        if s_src.has_reference(episodeUrl):
                            container_source = s_src
                            break
                        s_host = (urllib.parse.urlparse(s_src.base_url).hostname or "").lower()
                        if s_host and ep_host and (ep_host == s_host or ep_host.endswith("." + s_host)):
                            container_source = s_src
                            break
            except Exception:
                pass
        if not container_source and not source:
            try:
                parsed_ep = urllib.parse.urlparse(episodeUrl)
                ep_host = (parsed_ep.hostname or "").lower()
                if ep_host:
                    for src in extension_service.get_enabled_container_sources():
                        source_host = (urllib.parse.urlparse(src.base_url).hostname or '').lower()
                        if source_host and (ep_host == source_host or ep_host.endswith('.' + source_host)):
                            container_source = src
                            break
            except VerificationRequired:
                raise
            except Exception:
                pass

    if container_source:
        try:
            if getattr(container_source, 'runtime', '') == 'seanime':
                pref_srv = server if (server and server != "auto") else None
                container_sources = await container_source.get_episode_sources(
                    episodeUrl,
                    preferred_server=pref_srv,
                )
            else:
                container_sources = await container_source.get_episode_sources(episodeUrl)
        except (VerificationRequired, APIProblem):
            raise
        except Exception as e:
            logger.warning("[media] Error getting episode sources from container: %s", e)
            container_sources = []

        if container_sources:
            for idx, vs in enumerate(container_sources):
                srv_name = vs.get("server") if isinstance(vs, dict) else getattr(vs, "server", None)
                q_name = vs.get("quality") if isinstance(vs, dict) else getattr(vs, "quality", None)
                if srv_name and str(srv_name) not in available_servers:
                    available_servers.append(str(srv_name))
                label = srv_name or q_name or f"Serveur {idx + 1}"
                v_url = vs.get("url") if isinstance(vs, dict) else getattr(vs, "url", "")
                if label not in qualities_dict:
                    qualities_dict[label] = v_url
            if getattr(container_source, 'runtime', '') == 'seanime':
                for srv_name in getattr(container_source, 'episode_servers', []) or []:
                    if srv_name and str(srv_name) not in available_servers:
                        available_servers.append(str(srv_name))

            # Priorité au serveur demandé s'il est spécifié
            candidates = list(container_sources)
            from animelab.services.extension_media import prioritize_candidates
            candidates = prioritize_candidates(candidates, server, quality)

            candidate_failures = []
            for cand in candidates:
                cand_url = cand.get("url") if isinstance(cand, dict) else getattr(cand, "url", "")
                cand_srv = cand.get("server") if isinstance(cand, dict) else getattr(cand, "server", "imported")
                cand_q = cand.get("quality") if isinstance(cand, dict) else getattr(cand, "quality", "HD")

                if not cand_url:
                    continue

                try:
                    if getattr(container_source, 'runtime', '') in ('android-apk', 'seanime'):
                        resolved = await container_source.resolve_candidate(cand)
                    else:
                        resolved = await download_manager.resolve_imported_video_stream(
                            cand_url, referer=episodeUrl, preferred_quality=quality or cand_q)
                    if resolved and resolved.get("videoUrl"):
                        if getattr(container_source, 'runtime', '') in ('android-apk', 'seanime'):
                            native_media = resolved
                        video_url = resolved["videoUrl"]
                        server_type = resolved.get("serverType") or cand_srv
                        selected_quality = resolved.get("selectedQuality") or cand_q or "HD"
                        break
                except VerificationRequired:
                    raise
                except APIProblem as ex:
                    candidate_failures.append(ex)
                except Exception as ex:
                    logger.debug("[media] Error resolving candidate %s: %s", cand_url, ex)
            if not video_url and candidate_failures:
                raise candidate_failures[0]

        # Si toujours non résolu, tenter directement sur episodeUrl
        if not video_url and episodeUrl and getattr(container_source, 'runtime', '') not in ('android-apk', 'seanime'):
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
    elif source == "french-stream" or is_french_stream_url(episodeUrl):
        ep_lower = episodeUrl.lower()
        if any(h in ep_lower for h in ("vidzy", "luluvdo")) or "/d/" in ep_lower:
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
            try:
                resolved = await download_manager.resolve_imported_video_stream(
                    episodeUrl,
                    referer=f"{french_stream_service.base_url.rstrip('/')}/",
                    preferred_quality=quality,
                )
                if resolved and resolved.get("videoUrl"):
                    video_url = resolved["videoUrl"]
                    server_type = resolved.get("serverType") or "french-stream"
                    selected_quality = resolved.get("selectedQuality") or "HD"
            except VerificationRequired:
                raise
            except Exception as ex:
                logger.debug("[media] French-Stream resolve error: %s", ex)
    elif source == "french-manga" or "french-manga" in episodeUrl or "vidzy" in episodeUrl.lower():
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

    is_hls = bool(video_url and ".m3u8" in video_url.lower())

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

    payload: Dict[str, Any] = {
        "success": True,
        "isDownloaded": False,
        "isHls": is_hls,
        "sourceType": "remote",
        "streamUrl": video_url,
        "serverType": server_type,
        "selectedQuality": selected_quality,
        "qualities": qualities_dict,
        "title": f"{animeName} - Épisode {episodeNumber}",
        "subtitles": tracks,
    }
    if available_servers:
        payload["availableServers"] = available_servers
    return payload

@router.api_route("/api/media/stream/{task_id}", methods=["GET", "HEAD"])
async def stream_video(task_id: str, request: Request, range: Optional[str] = Header(None)):
    task = _resolve_local_media_record(task_id)
    if not task:
        raise HTTPException(status_code=404, detail="Vidéo introuvable")

    safe_disk = True
    if task.savePath:
        file_path = Path(task.savePath)
        safe_disk = is_safe_path(file_path)
        if safe_disk and file_path.is_file():
            file_size = file_path.stat().st_size
            content_type = mimetypes.guess_type(file_path.name)[0] or "application/octet-stream"

            def iter_full():
                with open(file_path, "rb") as f:
                    while chunk := f.read(65536):
                        yield chunk

            def iter_range(start: int, content_length: int):
                with open(file_path, "rb") as f:
                    f.seek(start)
                    remaining = content_length
                    chunk_size = 65536
                    while remaining > 0:
                        data = f.read(min(chunk_size, remaining))
                        if not data:
                            break
                        remaining -= len(data)
                        yield data

            return _serve_byte_stream(
                request=request,
                range_header=range,
                file_size=file_size,
                content_type=content_type,
                iter_full=iter_full,
                iter_range=iter_range,
            )

    # Fallback Android : lecture directe depuis le stockage partagé MediaStore / SAF
    export_uris = _exported_android_uris(task)
    if export_uris and platform_events.read_exported_copy_handler is not None:
        uri = export_uris[0]
        exported_size = platform_events.exported_copy_size(uri)
        if exported_size is not None and exported_size > 0:
            total_export_size = exported_size
            name_hint = getattr(task, "fileName", None) or task.savePath or ""
            content_type = mimetypes.guess_type(name_hint)[0] or "application/octet-stream"
            return _serve_byte_stream(
                request=request,
                range_header=range,
                file_size=total_export_size,
                content_type=content_type,
                iter_full=lambda: _read_exported_bytes(uri, 0, total_export_size),
                iter_range=lambda start, length: _read_exported_bytes(uri, start, length),
            )

    if task.savePath and not safe_disk:
        logger.warning("Path Traversal blocked on streaming: %s", task.savePath)
        raise HTTPException(status_code=403, detail="Accès refusé : fichier hors du répertoire autorisé")

    raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque")


@router.get("/api/media/subtitles/{task_id}")
async def get_subtitles_list(task_id: str):
    task = _resolve_local_media_record(task_id)
    if not task:
        return []

    paths = parse_subtitle_paths(getattr(task, "savePathSubtitle", None))
    sidecar_exports = _exported_android_uris(task)[1:]
    if not paths and not sidecar_exports:
        return []

    result = []
    video_stem = (
        Path(task.savePath).stem
        if getattr(task, "savePath", None)
        else (Path(task.fileName).stem if getattr(task, "fileName", None) else "")
    )
    try:
        media_payload = json.loads(getattr(task, "mediaJson", "{}") or "{}")
    except (TypeError, ValueError):
        media_payload = {}
    metadata = {
        item["path"]: item
        for item in media_payload.get("outputState", {}).get("sidecarTracks", [])
        if isinstance(item, dict) and "path" in item
    }

    total_slots = max(len(paths), len(sidecar_exports))
    for idx in range(total_slots):
        raw_path = paths[idx] if idx < len(paths) else ""
        sf = Path(raw_path) if raw_path else None
        disk_ok = sf is not None and is_safe_path(sf) and sf.is_file()
        export_ok = (
            not disk_ok
            and idx < len(sidecar_exports)
            and platform_events.exported_copy_exists(sidecar_exports[idx]) is True
        )
        if not disk_ok and not export_ok:
            continue

        lbl = sf.name.replace(video_stem, "").strip(".") if sf is not None else ""
        if not lbl:
            lbl = f"Sous-titres {idx + 1}"
        track = metadata.get(str(sf), {}) if sf is not None else {}
        lbl = track.get("label") or lbl
        lang = track.get("lang") or ("fr" if "fr" in lbl.lower() else "und")
        result.append({
            "label": lbl,
            "srclang": lang,
            "src": f"/api/media/subtitle/{task_id}/{idx}",
            "default": bool(track.get("default")) or (len(result) == 0 and idx == 0 and not paths),
        })

    return result


@router.get("/api/media/subtitle/{task_id}")
async def stream_subtitle_default(task_id: str):
    return await stream_subtitle_at_index(task_id, 0)


@router.get("/api/media/subtitle/{task_id}/{index}")
async def stream_subtitle_at_index(task_id: str, index: int):
    task = _resolve_local_media_record(task_id)
    if not task or index < 0:
        raise HTTPException(status_code=404, detail="Sous-titres introuvables")

    paths = parse_subtitle_paths(getattr(task, "savePathSubtitle", None))
    sidecar_exports = _exported_android_uris(task)[1:]
    if index >= max(len(paths), len(sidecar_exports)):
        raise HTTPException(status_code=404, detail="Index de sous-titre invalide")

    safe_sub = True
    if index < len(paths):
        file_path = Path(paths[index])
        safe_sub = is_safe_path(file_path)
        if safe_sub and file_path.is_file():
            return FileResponse(path=file_path, media_type=_subtitle_content_type(file_path.suffix))

    if index < len(sidecar_exports) and platform_events.read_exported_copy_handler is not None:
        uri = sidecar_exports[index]
        sub_size = platform_events.exported_copy_size(uri)
        if sub_size is not None and sub_size > 0:
            raw_bytes = b"".join(_read_exported_bytes(uri, 0, min(sub_size, 10 * 1024 * 1024)))
            suffix = Path(paths[index]).suffix if index < len(paths) else Path(uri).suffix
            return Response(content=raw_bytes, media_type=_subtitle_content_type(suffix))

    if index < len(paths) and not safe_sub:
        logger.warning("Path Traversal blocked on subtitles: %s", paths[index])
        raise HTTPException(status_code=403, detail="Accès refusé : fichier de sous-titres hors du répertoire autorisé")

    raise HTTPException(status_code=404, detail="Fichier de sous-titres introuvable")

@router.get("/api/media/subtitle-proxy")
async def proxy_subtitle(url: str = Query(...)):
    """
    Proxy pour sous-titres distants avec en-têtes CORS universels pour HTML5 <track>.
    """
    if not url or not url.startswith("http"):
        raise HTTPException(status_code=400, detail="URL de sous-titre invalide")
    url = normalize_voiranime_url(url)
    await asyncio.to_thread(validate_media_url, url)
    if not await is_safe_url_async(url):
        logger.warning("SSRF blocked on subtitle-proxy: %s", url)
        raise HTTPException(status_code=400, detail="URL de sous-titre non autorisée")

    is_va_sub = "voiranime" in url.lower() or "voir-anime" in url.lower()
    headers = {
        "User-Agent": proxy_service.get_user_agent(),
        "Referer": f"{settings.VOIR_ANIME_URL.rstrip('/')}/" if is_va_sub else "https://vidzy.org/",
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

            params = getattr(request, "query_params", {}) or {}
            ticket = valid_ticket_format(params.get("media_ticket"))
            ticket_param = f"&media_ticket={ticket}" if ticket else ""
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
                    seg_proxy = f"/api/media/hls-proxy/segment.ts?url={urllib.parse.quote(seg_abs)}{key_param}&seq={seq}{ticket_param}"
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


class ExternalPlayerSettingsBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    preset: Literal[
        "none",
        "system",
        "mpv",
        "vlc",
        "celluloid",
        "smplayer",
        "totem",
        "haruna",
        "iina",
        "custom",
    ] = "none"
    customPath: str = Field(default="", max_length=4096)
    preferExternal: bool = False


class ExternalPlayerSubtitleInput(BaseModel):
    model_config = ConfigDict(extra="allow")
    src: str = Field(min_length=1, max_length=4096)
    label: str = Field(default="", max_length=200)
    srclang: str = Field(default="", max_length=32)


class ExternalPlayerLaunchBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: str | None = Field(default=None, max_length=64)
    streamUrl: str | None = Field(default=None, max_length=4096)
    isHls: bool = False
    title: str = Field(default="", max_length=300)
    subtitles: list[ExternalPlayerSubtitleInput] = Field(default_factory=list, max_length=16)


def _guess_video_mime(filename: str | None) -> str:
    if not filename:
        return "video/*"
    lower = filename.lower()
    if lower.endswith(".mkv"):
        return "video/x-matroska"
    if lower.endswith((".mp4", ".m4v")):
        return "video/mp4"
    if lower.endswith(".webm"):
        return "video/webm"
    guessed = mimetypes.guess_type(filename)[0]
    if guessed and guessed.startswith("video/"):
        return guessed
    return "video/*"


async def _resolve_remote_or_local_subtitles(
    subtitles: list[ExternalPlayerSubtitleInput],
    *,
    origin: str,
    is_android: bool,
) -> list[str]:
    resolved: list[str] = []
    for sub in subtitles:
        src = sub.src.strip()
        if not src:
            continue
        if src.startswith("/api/media/"):
            try:
                scope_kind, scope_value = validate_local_media_url(src, allow_subtitle=True)
            except ValueError:
                continue
            full = f"{origin}{src}"
            if is_android:
                ticket = external_media_tickets.issue(scope_kind, scope_value)
                full = append_media_ticket(full, ticket)
            resolved.append(full)
        elif src.startswith(("http://", "https://")):
            try:
                await asyncio.to_thread(validate_media_url, src)
                if await is_safe_url_async(src):
                    resolved.append(src)
            except ValueError:
                continue
        if is_android and resolved:
            break
    return resolved


@router.get("/api/media/external-player/settings")
async def get_external_player_settings(request: Request):
    return external_player.snapshot(
        client_local=is_local(request),
        is_android=bool(app_config.IS_ANDROID),
    )


@router.post("/api/media/external-player/settings")
async def save_external_player_settings(body: ExternalPlayerSettingsBody, request: Request):
    if not is_local(request):
        raise HTTPException(
            status_code=403,
            detail="Le lecteur externe ne peut être configuré que depuis cette machine",
        )
    try:
        return await asyncio.to_thread(
            external_player.save,
            body.model_dump(),
            is_android=bool(app_config.IS_ANDROID),
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/api/media/external-player/launch")
async def launch_external_player(body: ExternalPlayerLaunchBody, request: Request):
    if not is_local(request):
        raise HTTPException(
            status_code=403,
            detail="Le lecteur externe ne peut être lancé que depuis cette machine",
        )

    is_android = bool(app_config.IS_ANDROID)
    effective_task_id = (body.taskId or "").strip() or extract_local_task_id(body.streamUrl)
    clean_title = sanitize_title(body.title)
    origin = local_loopback_origin(str(request.base_url), settings.PORT)

    if is_android:
        if effective_task_id:
            task = _resolve_local_media_record(effective_task_id)
            if not task:
                raise HTTPException(status_code=404, detail="Vidéo introuvable")
            title = clean_title or sanitize_title(f"{task.animeName} - Épisode {task.episodeNumber}")
            mime_type = _guess_video_mime(task.fileName or task.savePath)
            export_uris = _exported_android_uris(task)
            subtitle_uri: str | None = export_uris[1] if len(export_uris) > 1 else None
            if not subtitle_uri and task.savePathSubtitle:
                for p in parse_subtitle_paths(task.savePathSubtitle):
                    sf = Path(p)
                    if is_safe_path(sf) and sf.is_file():
                        sub_ticket = external_media_tickets.issue("task", task.id)
                        subtitle_uri = f"{origin}/api/media/subtitle/{urllib.parse.quote(task.id, safe='')}/0?media_ticket={sub_ticket}"
                        break

            if export_uris and platform_events.exported_copy_exists(export_uris[0]) is not False:
                return {
                    "success": True,
                    "mode": "android_intent",
                    "player": "Android",
                    "targetKind": "file",
                    "androidIntent": {
                        "kind": "uri",
                        "target": export_uris[0],
                        "mimeType": mime_type,
                        "title": title,
                        "subtitleUri": subtitle_uri,
                    },
                }

            if not task.savePath:
                raise HTTPException(status_code=404, detail="Fichier vidéo introuvable")
            file_path = Path(task.savePath)
            if not is_safe_path(file_path):
                raise HTTPException(status_code=403, detail="Accès refusé : fichier hors du répertoire autorisé")
            if not file_path.is_file():
                raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque")
            return {
                "success": True,
                "mode": "android_intent",
                "player": "Android",
                "targetKind": "file",
                "androidIntent": {
                    "kind": "file",
                    "target": str(file_path.resolve()),
                    "mimeType": mime_type,
                    "title": title,
                    "subtitleUri": subtitle_uri,
                },
            }

        raw_url = (body.streamUrl or "").strip()
        if not raw_url:
            raise HTTPException(status_code=400, detail="Cible vidéo manquante.")
        if raw_url.startswith("/api/media/"):
            try:
                scope_kind, scope_value = validate_local_media_url(raw_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            ticket = external_media_tickets.issue(scope_kind, scope_value)
            target_url = append_media_ticket(f"{origin}{raw_url}", ticket)
        else:
            try:
                await asyncio.to_thread(validate_media_url, raw_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=str(exc)) from exc
            if not await is_safe_url_async(raw_url):
                raise HTTPException(status_code=400, detail="URL média non autorisée ou non sécurisée")
            target_url = raw_url

        subs = await _resolve_remote_or_local_subtitles(body.subtitles, origin=origin, is_android=True)
        mime_type = (
            "application/vnd.apple.mpegurl"
            if (body.isHls or ".m3u8" in raw_url.lower())
            else "video/*"
        )
        return {
            "success": True,
            "mode": "android_intent",
            "player": "Android",
            "targetKind": "stream",
            "androidIntent": {
                "kind": "url",
                "target": target_url,
                "mimeType": mime_type,
                "title": clean_title,
                "subtitleUri": subs[0] if subs else None,
            },
        }

    # Desktop launch branch
    is_local_target = bool(effective_task_id)
    try:
        resolved_player = external_player.resolve_configured_executable(
            is_android=False,
            allow_auto_fallback=True,
            for_stream=not is_local_target,
        )
    except ValueError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    if resolved_player is None:
        raise HTTPException(status_code=409, detail="Aucun lecteur externe n’est configuré.")
    player_label, exe_path = resolved_player

    if effective_task_id:
        task = _resolve_local_media_record(effective_task_id)
        if not task or not task.savePath:
            raise HTTPException(status_code=404, detail="Vidéo introuvable")
        file_path = Path(task.savePath)
        if not is_safe_path(file_path):
            raise HTTPException(status_code=403, detail="Accès refusé : fichier hors du répertoire autorisé")
        if not file_path.is_file():
            raise HTTPException(status_code=404, detail="Fichier vidéo introuvable sur le disque")
        local_subs = [
            str(Path(p).resolve())
            for p in parse_subtitle_paths(task.savePathSubtitle)
            if p and is_safe_path(Path(p)) and Path(p).is_file()
        ]
        title = clean_title or sanitize_title(f"{task.animeName} - Épisode {task.episodeNumber}")
        try:
            argv = build_player_command(
                exe_path, str(file_path.resolve()), title=title, subtitles=local_subs
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        await asyncio.to_thread(spawn_desktop_player, argv)
        return {
            "success": True,
            "mode": "desktop_process",
            "player": player_label,
            "targetKind": "file",
        }

    raw_url = (body.streamUrl or "").strip()
    if not raw_url:
        raise HTTPException(status_code=400, detail="Cible vidéo manquante.")
    if raw_url.startswith("/api/media/"):
        try:
            validate_local_media_url(raw_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        target_url = f"{origin}{raw_url}"
    else:
        try:
            await asyncio.to_thread(validate_media_url, raw_url)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        if not await is_safe_url_async(raw_url):
            raise HTTPException(status_code=400, detail="URL média non autorisée ou non sécurisée")
        target_url = raw_url

    desktop_subs = await _resolve_remote_or_local_subtitles(
        body.subtitles, origin=origin, is_android=False
    )
    try:
        argv = build_player_command(exe_path, target_url, title=clean_title, subtitles=desktop_subs)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    await asyncio.to_thread(spawn_desktop_player, argv)
    return {
        "success": True,
        "mode": "desktop_process",
        "player": player_label,
        "targetKind": "stream",
    }


class DeleteDownloadedEpisodeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    taskId: str | None = Field(default=None, max_length=128)
    animeUrl: str = Field(default="", max_length=4096)
    animeName: str = Field(default="", max_length=500)
    episodeUrl: str = Field(default="", max_length=4096)
    episodeNumber: int | None = Field(default=None, ge=0)
    version: str = Field(default="", max_length=40)
    source: str = Field(default="", max_length=255)
    season: int | None = Field(default=None, ge=1)


def _prune_empty_download_dirs(candidate_dirs: set[Path], download_root: Path) -> None:
    try:
        resolved_root = download_root.resolve()
    except OSError:
        return
    ordered = sorted(candidate_dirs, key=lambda p: len(p.parts), reverse=True)
    for directory in ordered:
        cur = directory
        while cur != resolved_root and cur.parent != cur and is_safe_path(cur, [resolved_root]):
            try:
                cur.rmdir()
            except OSError:
                break
            cur = cur.parent


@router.post("/api/media/downloaded/delete")
async def delete_downloaded_episode(body: DeleteDownloadedEpisodeBody):
    """Delete local files, sidecar subtitles, DB tasks, and downloaded flag for one episode."""
    req_task_id = (body.taskId or "").strip()
    db_records: dict[str, Any] = {}
    local_entries: dict[str, Any] = {}

    if req_task_id:
        resolved = await asyncio.to_thread(_resolve_local_media_record, req_task_id)
        if resolved is not None:
            if req_task_id.startswith("local-"):
                local_entries[req_task_id] = resolved
            else:
                db_records[str(resolved.id)] = resolved

    eff_name = (body.animeName or "").strip()
    eff_url = (body.animeUrl or "").strip()
    eff_ep = body.episodeNumber
    eff_version = body.version or ""
    eff_ep_url = (body.episodeUrl or "").strip()
    eff_source = (body.source or "").strip()

    first_rec = next(iter(db_records.values()), None) or next(iter(local_entries.values()), None)
    if first_rec is not None:
        eff_name = eff_name or (getattr(first_rec, "animeName", "") or "").strip()
        eff_url = eff_url or (getattr(first_rec, "animeUrl", "") or "").strip()
        if eff_ep is None:
            eff_ep = getattr(first_rec, "episodeNumber", None)
        eff_version = eff_version or (getattr(first_rec, "version", "") or "")
        eff_source = eff_source or (getattr(first_rec, "source", "") or "")

    if eff_ep is not None and (eff_name or eff_url or eff_ep_url):
        matching_entities = await asyncio.to_thread(
            library_service.find_all_downloaded_episode_tasks,
            anime_name=eff_name,
            episode_number=eff_ep,
            version=eff_version,
            episode_url=eff_ep_url,
            anime_url=eff_url,
            source=eff_source,
        )
        for entity in matching_entities:
            tid = str(entity.id)
            if tid not in db_records:
                db_records[tid] = entity.to_task()

    extra_disk_files: list[Path] = []
    if eff_ep is not None and eff_name:
        extra_disk_files = await asyncio.to_thread(
            local_media.find_all_on_disk,
            anime_name=eff_name,
            episode_number=eff_ep,
            version=eff_version,
            season=body.season,
        )

    if not db_records and not local_entries and not extra_disk_files:
        raise HTTPException(status_code=404, detail="Épisode téléchargé introuvable")

    for tid in db_records:
        if download_manager._export_in_progress(tid):
            raise HTTPException(
                status_code=409,
                detail="Attendez la fin de l’export en cours avant de supprimer cet épisode",
            )

    all_records = [*db_records.values(), *local_entries.values()]
    for rec in all_records:
        save_path = getattr(rec, "savePath", None)
        if save_path and not is_safe_path(Path(save_path)):
            logger.warning("Path traversal blocked on downloaded delete: %s", save_path)
            raise HTTPException(
                status_code=403,
                detail="Accès refusé : fichier hors du répertoire autorisé",
            )

    download_root = Path(settings.DOWNLOAD_DIR).resolve()
    candidate_files: dict[Path, Path] = {}
    candidate_dirs: set[Path] = set()
    export_uris: list[str] = []

    def _add_file_target(raw_path: str | Path | None) -> None:
        if not raw_path:
            return
        try:
            p = Path(raw_path)
        except Exception:
            return
        if not is_safe_path(p):
            return
        try:
            resolved_p = p.resolve()
        except OSError:
            return
        candidate_files[resolved_p] = resolved_p

    for rec in all_records:
        for uri in _exported_android_uris(rec):
            if uri not in export_uris:
                export_uris.append(uri)
        save_path = getattr(rec, "savePath", None)
        if save_path:
            vp = Path(save_path)
            _add_file_target(vp)
            _add_file_target(f"{save_path}.part")
            _add_file_target(f"{save_path}.part.resume.json")
            _add_file_target(vp.with_suffix(".tmp.mp4"))
            if vp.parent.is_dir():
                for sc in discover_sidecar_subtitles(vp, download_root):
                    _add_file_target(sc)
        for sub_path in parse_subtitle_paths(getattr(rec, "savePathSubtitle", None)):
            _add_file_target(sub_path)
        try:
            media_payload = json.loads(getattr(rec, "mediaJson", "{}") or "{}")
            out_state = media_payload.get("outputState", {}) if isinstance(media_payload, dict) else {}
            if isinstance(out_state, dict):
                _add_file_target(out_state.get("source"))
                for sc in out_state.get("sidecars") or []:
                    _add_file_target(sc)
        except (TypeError, ValueError):
            pass

    for dp in extra_disk_files:
        _add_file_target(dp)
        if dp.parent.is_dir():
            for sc in discover_sidecar_subtitles(dp, download_root):
                _add_file_target(sc)

    deleted_files = 0
    for file_target in candidate_files.values():
        try:
            if file_target.is_file():
                file_target.unlink()
                deleted_files += 1
                candidate_dirs.add(file_target.parent)
        except OSError as exc:
            logger.warning("Unable to delete local media file %s: %s", file_target, exc)

    if candidate_dirs:
        await asyncio.to_thread(_prune_empty_download_dirs, candidate_dirs, download_root)

    for uri in export_uris:
        try:
            await asyncio.to_thread(platform_events.delete_exported_copy, uri)
        except Exception as exc:
            logger.debug("Unable to delete exported Android URI %s: %s", uri, exc)

    removed_task_ids: list[str] = []
    for tid in list(db_records):
        try:
            if await asyncio.to_thread(download_manager.remove_task, tid):
                removed_task_ids.append(tid)
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    for lid in list(local_entries):
        if local_media.remove(lid) is not None:
            removed_task_ids.append(lid)

    if candidate_files:
        with local_media._lock:
            stale_ids = [
                eid
                for eid, entry in local_media._entries.items()
                if Path(entry.savePath).resolve() in candidate_files
            ]
            for eid in stale_ids:
                local_media._entries.pop(eid, None)

    if eff_ep is not None and (eff_url or eff_name):
        await asyncio.to_thread(
            library_service.clear_downloaded,
            eff_url,
            eff_ep,
            eff_version,
            eff_name,
        )

    return {
        "success": True,
        "deletedFiles": deleted_files,
        "removedTaskIds": removed_task_ids,
    }


