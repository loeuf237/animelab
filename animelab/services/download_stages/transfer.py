"""TransferWorker: extracted stage with a compatibility coordinator context."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animelab.services.download_manager import DownloadManagerService

from animelab.services.download_stages.state import transition
from animelab.services.source_http import VerificationRequired, RateLimited
import asyncio
import json
import logging
import math
import re
import shutil
from animelab import media_tools
import time
from pathlib import Path
from typing import List
from urllib.parse import urljoin, urlparse

import httpx

from animelab.config import settings
from animelab.models.download_task import DownloadTask, DownloadStatus, format_bytes
from animelab.services.library_service import library_service
from animelab.services.proxy_service import proxy_service
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.verification_service import verification_service
from animelab.services.extractors import extractor_registry
from animelab.services.download_errors import SubtitleError
from animelab.services.download_resume import (RESUME_OVERLAP, ResumeMismatch, read_metadata,
    valid_cached_segment, commit_segment, publish_file, media_resource,
                                            write_metadata, representation, response_range, prepare_hls_cache)

logger = logging.getLogger("animelab.download.transfer")


class TransferWorker:
    def __init__(self, manager: DownloadManagerService):
        self.manager = manager

    async def _execute_download(self, task: DownloadTask):
        ctx = self.manager
        if task.status == DownloadStatus.PENDING and not (task.paused or task.cancelled):
            transition(task, DownloadStatus.DOWNLOADING)
        try:
            max_retries = 5  # Tolérance robuste face aux coupures réseau et expirations CDN
            task.retryCount = 0
            need_resolve = True
            skip_local = False

            while True:
                if task.cancelled:
                    transition(task, DownloadStatus.CANCELLED)
                    ctx.broadcast_update(task)
                    library_service.save_task(task)
                    return
                if task.paused:
                    transition(task, DownloadStatus.PAUSED)
                    task.speed = 0
                    ctx.broadcast_update(task)
                    library_service.save_task(task)
                    return

                local_finalization = False
                try:
                    # Retry finalization locally before asking a possibly expired player
                    # for another video URL. The file is still verified by the downloader.
                    await ctx.media_pipeline.budget.run(task, ctx._media_jobs, ctx._recover_muxed_file, task)
                    if not skip_local and task.savePath and Path(task.savePath).is_file():
                        local = await ctx.media_pipeline.budget.run(task, ctx._media_jobs, verification_service.verify_file, task.savePath,
                                                       expected_size=task.totalBytes or None)
                        if local.valid:
                            local_finalization = True
                            await ctx._download_single_file(task, task.directDownloadUrl or task.fileUrl or "")
                            return
                    task.phase = "resolving"
                    ctx.broadcast_update(task)
                    direct_url = task.fileUrl
                    clean_direct = (direct_url or "").split("#")[0].strip()
                    parsed_u = urlparse(clean_direct)
                    u_host = (parsed_u.hostname or "").lower()
                    is_known_embed = extractor_registry.is_known_embed(clean_direct)
                    is_imported = (
                        (task.source and (task.source not in ("french-manga", "voir-anime", "animepahe"))) or
                        is_known_embed
                    )
                    is_voir_anime = not is_imported and (("voir-anime" in (direct_url or "").lower()) or ("voiranime" in (direct_url or "").lower()) or task.source == "voir-anime")
                    is_animepahe = not is_imported and (any(k in (direct_url or "").lower() for k in ["animepahe", "kwik.", "pahe."]) or task.source == "animepahe")
                    server_type = "vidzy"
                    chunks_json = "[]"

                    # Réutiliser l'URL directe déjà résolue si disponible et valide (reprise)
                    # S'assurer qu'elle n'est PAS une page HTML (ne contient pas /d/vidzy ou similaire)
                    is_cached_valid = bool(
                        task.directDownloadUrl and
                        not ctx._needs_scraping_resolution(task.directDownloadUrl) and
                        not re.search(r"vidzy\.[a-z]+/d/", task.directDownloadUrl)
                    )

                    if is_cached_valid and not need_resolve:
                        direct_url = task.directDownloadUrl
                        logger.info("Reusing cached direct URL for %s", task.fileName)
                    elif is_imported:
                        matched_container = None
                        try:
                            from animelab.services.extension_service import extension_service
                            if task.source and task.source not in ("french-manga", "voir-anime", "animepahe"):
                                matched_container = extension_service.get_container_source_by_id(task.source)
                            if not matched_container and u_host:
                                for cs in extension_service.get_enabled_container_sources():
                                    if cs.base_url and u_host in cs.base_url.lower():
                                        matched_container = cs
                                        break
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                        target_url = direct_url
                        video_sources = []
                        target = None
                        if matched_container and not is_known_embed:
                            video_sources = await matched_container.get_episode_sources(direct_url)
                            target = None
                            if task.selectedServer and task.selectedServer != "auto":
                                for s in video_sources:
                                    s_srv = s.get("server") or s.get("name") or ""
                                    if task.selectedServer.lower() in s_srv.lower():
                                        target = s
                                        break
                            if not target and task.selectedQuality and task.selectedQuality != "auto":
                                for s in video_sources:
                                    q_name = s.get("quality") or s.get("server") or ""
                                    if task.selectedQuality.lower() in q_name.lower():
                                        target = s
                                        break
                            if not target and video_sources:
                                target = video_sources[0]
                            if target and target.get("url"):
                                target_url = target.get("url", "")

                        resolved = None
                        candidate_urls = []
                        if target and target.get("url"):
                            candidate_urls.append(target.get("url"))
                        if video_sources:
                            for vs in video_sources:
                                v_u = vs.get("url")
                                if v_u and v_u not in candidate_urls:
                                    candidate_urls.append(v_u)

                        for cand_u in (candidate_urls or [target_url]):
                            try:
                                cand_res = await ctx.resolve_imported_video_stream(
                                    cand_u, preferred_quality=task.selectedQuality
                                )
                                if cand_res and cand_res.get("videoUrl"):
                                    resolved = cand_res
                                    break
                            except VerificationRequired:
                                raise
                            except Exception:
                                pass

                        if not resolved or not resolved.get("videoUrl"):
                            clean_t = target_url.split("#")[0].strip()
                            if re.search(r"\.(mp4|m3u8|webm|mkv)(\?.*)?$", clean_t, re.IGNORECASE):
                                resolved = {
                                    "videoUrl": clean_t,
                                    "serverType": "direct",
                                    "selectedQuality": task.selectedQuality or "HD",
                                }
                            else:
                                raise ValueError(f"Impossible de résoudre le flux vidéo de la source importée pour {task.fileName}")

                        direct_url = resolved["videoUrl"]
                        server_type = resolved.get("serverType", "imported")
                        task.selectedServer = server_type
                        task.directDownloadUrl = direct_url
                        ctx._update_resolved_subtitles(task, resolved.get("subtitles", []), target_url)
                        task.subtitleUrl = resolved.get("subtitleUrl") or task.subtitleUrl
                        if resolved.get("size") and task.totalBytes <= 0:
                            task.totalBytes = resolved["size"]
                    elif is_voir_anime:
                        from animelab.services.source_settings_service import source_settings_service
                        va_settings = source_settings_service.get_source_settings("voir-anime")
                        va_strategy = va_settings.get("quality_strategy", "highest")
                        pref_srv = task.selectedServer or ctx.voiranime_default_server
                        # Si échec répété du serveur distant (client confirmé en ligne) ou erreur HTML, repli sur serveurs alternatifs
                        consec_errs = getattr(task, "consecutiveServerErrors", 0)
                        client_offline = getattr(task, "clientOffline", False)
                        has_html_err = "html" in (task.error or "").lower()
                        # Le basculement vers d'autres hébergeurs n'intervient que sur pannes serveur avérées répétées ou page HTML d'erreur
                        if not client_offline and (consec_errs >= 2 or has_html_err):
                            logger.info("[download_manager] Falling back to alternative servers for %s after confirmed failures on %s", task.fileName, pref_srv)
                            if pref_srv:
                                part_clean = Path(task.savePath + ".part")
                                if part_clean.exists():
                                    part_clean.unlink(missing_ok=True)
                                segments_clean = Path(task.savePath).parent / f".{Path(task.savePath).stem}_segments"
                                if segments_clean.exists():
                                    shutil.rmtree(segments_clean, ignore_errors=True)
                                task.downloadedBytes = 0
                                task.progress = 0.0
                            pref_srv = None
                            task.selectedServer = None
                            task.selectedQuality = None

                        info = await asyncio.to_thread(
                            voiranime_service.extract_download_info,
                            direct_url,
                            preferred_server=pref_srv,
                            preferred_quality=task.selectedQuality,
                            quality_strategy=va_strategy,
                        )
                        direct_url = info.get("videoUrl", "")
                        if not direct_url:
                            raise ValueError(f"Impossible d'extraire l'URL vidéo pour {task.fileName}")
                        server_type = info.get("serverType", "unknown")
                        chunks_json = info.get("videoChunks", "[]")
                        task.directDownloadUrl = direct_url
                        if (skip_local or not task.subtitleUrl) and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                        ctx._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
                    elif is_animepahe:
                        from animelab.services.animepahe_service import animepahe_service
                        server_type = "kwik"
                        if ("kwik." in direct_url or "pahe." in direct_url) and ("/e/" in direct_url or "/d/" in direct_url):
                            extracted = await animepahe_service.extract_kwik_stream(direct_url)
                            if not extracted:
                                raise ValueError(f"Impossible de résoudre le flux Kwik pour {task.fileName}")
                            direct_url = extracted
                        elif task.selectedServer and ("kwik." in task.selectedServer or "pahe." in task.selectedServer):
                            extracted = await animepahe_service.extract_kwik_stream(task.selectedServer)
                            if not extracted:
                                raise ValueError(f"Impossible de résoudre le flux Kwik sélectionné pour {task.fileName}")
                            direct_url = extracted
                        else:
                            sources = await animepahe_service.get_episode_sources(direct_url)
                            target = None
                            if task.selectedQuality and task.selectedQuality != "auto":
                                for s in sources:
                                    q_name = s.get("name") or s.get("quality", "")
                                    if task.selectedQuality.lower() in q_name.lower() or task.selectedQuality.lower() in s.get("quality", "").lower():
                                        target = s
                                        break
                            if not target and sources:
                                target = sources[0]
                            if not target or not target.get("url"):
                                raise ValueError(f"Aucune source Kwik trouvée pour {task.fileName}")
                            extracted = await animepahe_service.extract_kwik_stream(target["url"])
                            if not extracted:
                                raise ValueError(f"Échec d'extraction du flux vidéo Kwik pour {task.fileName}")
                            direct_url = extracted
                        task.directDownloadUrl = direct_url
                    elif direct_url and ctx._needs_scraping_resolution(direct_url):
                        info = await asyncio.to_thread(scraping_service.extract_download_info, direct_url)
                        direct_url = info.get("videoUrl", "")
                        if not direct_url:
                            raise ValueError(f"Impossible d'extraire l'URL vidéo directe pour {task.fileName}")
                        task.directDownloadUrl = direct_url
                        if (skip_local or not task.subtitleUrl) and info.get("subtitleUrl"):
                            task.subtitleUrl = info["subtitleUrl"]
                        if skip_local or not task.subtitlesJson or task.subtitlesJson == "[]":
                            ctx._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
                    else:
                        task.directDownloadUrl = direct_url

                    need_resolve = False  # Les retries suivants réutiliseront l'URL sauf si déconnexion

                    if server_type == "myTV" and chunks_json != "[]":
                        chunks = json.loads(chunks_json)
                        if len(chunks) > 1:
                            await ctx._download_mytv_chunks(task, chunks)
                            return

                    bytes_before = task.downloadedBytes
                    is_hls = bool(direct_url and (".m3u8" in direct_url.lower()))
                    if is_hls:
                        await ctx._download_hls_stream(task, direct_url)
                        return

                    await ctx._download_single_file(task, direct_url)
                    break

                except VerificationRequired as exc:
                    transition(task, DownloadStatus.VERIFICATION_REQUIRED)
                    task.verificationUrl = exc.url
                    task.error = str(exc)
                    task.speed = 0
                    ctx.broadcast_update(task)
                    library_service.save_task(task)
                    return
                except Exception as e:
                    from animelab.services.extension_observability import InvalidSelector, SelectorMismatch, extension_observability
                    if isinstance(e,(InvalidSelector,SelectorMismatch)):
                        transition(task, DownloadStatus.FAILED)
                        task.error = 'Les sélecteurs de la source sont incompatibles. Vérifiez sa recette dans les extensions.'
                        extension_observability.record(task.source,'detail',error=e)
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if isinstance(e, (httpx.RequestError, httpx.HTTPStatusError)) and not isinstance(e, RateLimited):
                        request = getattr(e, "request", None)
                        if request is not None:
                            task.verificationUrl = str(request.url)
                    if isinstance(e, RateLimited):
                        # A large Retry-After should not consume all download attempts.
                        transition(task, DownloadStatus.PAUSED)
                        task.error = f"Limitation de débit ; réessayez après {int(e.retry_after)} secondes"
                        task.speed = 0
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if isinstance(e, SubtitleError):
                        if local_finalization and e.refresh_required:
                            skip_local = True
                            need_resolve = True
                            continue
                        transition(task, DownloadStatus.FAILED)
                        task.error = str(e)
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if task.cancelled:
                        transition(task, DownloadStatus.CANCELLED)
                        task.speed = 0
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        return
                    if task.paused:
                        transition(task, DownloadStatus.PAUSED)
                        task.speed = 0
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        return

                    bytes_gained = task.downloadedBytes - bytes_before if 'bytes_before' in locals() else 0
                    if bytes_gained > 0:
                        logger.info("Progress of %s bytes for %s despite network interruption, keeping host %s and resetting server errors",
                                    format_bytes(bytes_gained), task.fileName, task.selectedServer)
                        task.retryCount = max(0, task.retryCount - 1)
                        task.consecutiveServerErrors = 0

                    err_msg = str(e).lower()

                    # 1. Tester d'abord si la machine locale est déconnectée d'Internet
                    client_online = await ctx.is_client_online()
                    if not client_online:
                        task.clientOffline = True
                        logger.warning(
                            "[download_manager] Local Internet disconnection detected for %s (error: %s). "
                            "Retaining host %s and partial data. Waiting for network recovery...",
                            task.fileName, err_msg, task.selectedServer
                        )
                        transition(task, DownloadStatus.RETRYING)
                        task.error = "Local Internet connection interrupted. Waiting for network recovery..."
                        task.speed = 0
                        ctx.broadcast_update(task)
                        library_service.save_task(task)

                        # Attente active du retour de la connexion sans consommer les retries serveur ni changer d'hôte
                        while not task.cancelled and not task.paused:
                            await asyncio.sleep(5.0)
                            if await ctx.is_client_online():
                                logger.info(
                                    "[download_manager] Internet connection restored for %s! Resuming download on host %s.",
                                    task.fileName, task.selectedServer
                                )
                                task.clientOffline = False
                                need_resolve = True  # Re-résoudre sur le même serveur en cas de token/lien direct expiré
                                task.directDownloadUrl = None
                                break
                        continue

                    task.clientOffline = False

                    if task.retryCount < max_retries:
                        task.retryCount += 1

                        # Détection des coupures réseau distantes, timeouts, expirations CDN ou réponses invalides de l'hébergeur
                        is_disconnect = (
                            "peer closed connection" in err_msg
                            or "remote protocol" in err_msg
                            or "connection reset" in err_msg
                            or "connection closed" in err_msg
                            or "incompleteread" in err_msg
                            or "broken pipe" in err_msg
                            or "readtimeout" in err_msg
                            or "connecttimeout" in err_msg
                            or "timeout" in err_msg
                            or "416" in err_msg
                            or "403" in err_msg
                            or "401" in err_msg
                            or "404" in err_msg
                            or "410" in err_msg
                            or "502" in err_msg
                            or "503" in err_msg
                            or "html" in err_msg
                        )
                        if is_disconnect:
                            if bytes_gained <= 0:
                                task.consecutiveServerErrors = getattr(task, "consecutiveServerErrors", 0) + 1
                                logger.info("Connection failure or expired link without progress (%s) for %s, consecutive server failures: %d",
                                            err_msg, task.fileName, task.consecutiveServerErrors)
                            else:
                                task.consecutiveServerErrors = 0
                            need_resolve = True
                            task.directDownloadUrl = None
                        elif task.retryCount >= 2:
                            need_resolve = True
                            task.directDownloadUrl = None

                        # Détection des pannes DNS transitoires
                        is_dns = (
                            "name resolution" in err_msg
                            or "gaierror" in err_msg
                            or "temporary failure" in err_msg
                            or "nodename nor servname" in err_msg
                        )
                        if is_dns:
                            logger.warning("Transient DNS failure (%s) for %s, waiting 5s", err_msg, task.fileName)
                            await asyncio.sleep(5.0)
                            if task.retryCount > 0:
                                task.retryCount -= 1

                        transition(task, DownloadStatus.RETRYING)
                        task.error = f"Erreur serveur hébergeur: {str(e)}. Reprise ({task.retryCount}/{max_retries})"
                        ctx.broadcast_update(task)
                        library_service.save_task(task)

                        backoff = min(15.0, 2.0 + math.pow(1.3, min(task.retryCount, 10)))
                        await asyncio.sleep(backoff)
                    else:
                        transition(task, DownloadStatus.FAILED)
                        task.error = str(e)
                        task.speed = 0
                        ctx.broadcast_update(task)
                        library_service.save_task(task)
                        break
        except asyncio.CancelledError:
            task.paused = True
            task.speed = 0
            if task.status != DownloadStatus.COMPLETED:
                transition(task, DownloadStatus.PAUSED)
            library_service.save_task(task)
            ctx.broadcast_update(task)
            raise
        finally:
            ctx.scheduler.release_network(task.id)


    async def _download_single_file(self, task: DownloadTask, direct_url: str):
        ctx = self.manager
        task.phase = "video"
        ctx.broadcast_update(task)
        output_path = Path(task.savePath)
        part_path = Path(task.savePath + ".part")
        metadata_path = Path(task.savePath + ".part.resume.json")

        # 1. Gestion propre du fichier existant et reprise
        existing_len = 0
        if output_path.exists():
            if output_path.stat().st_size < 1024 * 1024:
                try:
                    with open(output_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Corrupted final file (HTML) detected and deleted for %s", task.fileName)
                            output_path.unlink(missing_ok=True)
                except VerificationRequired:
                    raise
                except Exception:
                    pass

            if output_path.exists():
                verif = await asyncio.to_thread(
                    verification_service.verify_file,
                    file_path_str=str(output_path),
                    anime_name=task.animeName,
                    file_name=task.fileName,
                    expected_size=task.totalBytes if task.totalBytes and task.totalBytes > 0 else None
                )
                if verif.valid:
                    logger.info("Final file already exists and is valid for %s (%s)",
                                task.fileName, format_bytes(output_path.stat().st_size))
                    part_path.unlink(missing_ok=True)
                    if task.downloadSubtitles:
                        await ctx._download_subtitles(task)
                        await ctx._finalize_task(task)
                        return
                    task.downloadedBytes = output_path.stat().st_size
                    if not task.totalBytes or task.totalBytes <= 0:
                        task.totalBytes = output_path.stat().st_size
                    await ctx._finalize_task(task, verification=verif)
                    return
                else:
                    logger.warning("Existing final file invalid/corrupted for %s (%s), deleting: %s",
                                   task.fileName, format_bytes(output_path.stat().st_size), verif.error)
                    output_path.unlink(missing_ok=True)

        if not direct_url:
            raise ValueError("URL directe introuvable")

        if part_path.exists():
            part_size = part_path.stat().st_size
            if part_size < 1024 * 1024:
                try:
                    with open(part_path, "rb") as f_chk:
                        h = f_chk.read(100).lower()
                        if b"<html" in h or b"<!doctype" in h:
                            logger.warning("Corrupted .part file (HTML) detected and deleted for %s", task.fileName)
                            part_path.unlink(missing_ok=True)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
            elif task.totalBytes and task.totalBytes > 0 and part_size > task.totalBytes:
                logger.warning(".part file (%s) exceeds expected size (%s) for %s, deleting",
                               format_bytes(part_size), format_bytes(task.totalBytes), task.fileName)
                part_path.unlink(missing_ok=True)

            if part_path.exists():
                existing_len = part_path.stat().st_size

        headers = ctx.get_headers_for_url(direct_url, getattr(task, "selectedServer", None))
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=60.0, write=30.0, pool=None)
        async with ctx._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            req_headers = dict(headers)
            req_headers["Accept-Encoding"] = "identity"
            is_resume = existing_len > 0
            previous = read_metadata(metadata_path) if is_resume else {}
            resource = media_resource(direct_url)
            if previous.get("resource") and previous["resource"] != resource:
                # ETags are scoped to a resource, not globally comparable across
                # renewed CDN hosts/paths. Preserve the partial until GET succeeds.
                existing_len = 0
                is_resume = False
            request_start = max(0, existing_len - RESUME_OVERLAP) if is_resume else 0
            if is_resume:
                req_headers["Range"] = f"bytes={request_start}-"
                if previous.get("validator"):
                    req_headers["If-Range"] = previous["validator"]
                logger.info("Resume attempt for %s from %s", task.fileName, format_bytes(existing_len))

            while True:
                async with client.stream("GET", direct_url, headers=req_headers) as stream_resp:
                    # Gestion du code 416 Range Not Satisfiable
                    if stream_resp.status_code == 416:
                        logger.warning("HTTP 416 (Range Not Satisfiable) for %s with existing_len=%s",
                                       task.fileName, format_bytes(existing_len))
                        unsatisfied = re.fullmatch(r"bytes\s+\*/(\d+)",
                                                   stream_resp.headers.get("Content-Range", ""), re.IGNORECASE)
                        if part_path.exists() and unsatisfied and int(unsatisfied[1]) == existing_len:
                            verif_part = await asyncio.to_thread(
                                verification_service.verify_file,
                                file_path_str=str(part_path),
                                anime_name=task.animeName,
                                file_name=task.fileName,
                                expected_size=existing_len,
                            )
                            if verif_part.valid:
                                logger.info(".part file is actually complete and valid for %s, finalizing", task.fileName)
                                publish_file(part_path, output_path)
                                metadata_path.unlink(missing_ok=True)
                                await ctx._finalize_task(task)
                                return
                            else:
                                logger.warning("Invalid/corrupted .part file (%s), deleting for clean resume", verif_part.error)
                                part_path.unlink(missing_ok=True)

                        existing_len = 0
                        is_resume = False
                        task.downloadedBytes = 0
                        request_start = 0
                        had_range = "Range" in req_headers
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        metadata_path.unlink(missing_ok=True)
                        if had_range:
                            continue
                        raise ConnectionError("HTTP 416 (Range Not Satisfiable): Plage invalide, re-résolution requise")

                    if stream_resp.status_code not in [200, 206]:
                        raise ConnectionError(f"HTTP {stream_resp.status_code}")

                    # Contrôle strict du type de contenu (rejeter formellement le HTML)
                    content_type = stream_resp.headers.get("Content-Type", "").lower()
                    if "text/html" in content_type or "text/plain" in content_type or "application/json" in content_type:
                        raise ValueError(f"Réponse HTTP invalide : type '{content_type}' reçu au lieu d'un flux vidéo binaire")

                    # Le serveur ne supporte pas Range — on recommence depuis 0
                    if stream_resp.status_code == 200 and is_resume:
                        logger.warning("Server does not support resume for %s, downloading from beginning", task.fileName)
                        existing_len = 0
                        is_resume = False
                        request_start = 0

                    # Extraction et validation de la taille via Content-Range ou Content-Length
                    total_bytes = 0
                    response_length = None
                    if stream_resp.status_code == 206:
                        total_bytes, response_length = response_range(stream_resp.headers, request_start)
                    else:
                        cl = stream_resp.headers.get("Content-Length")
                        if cl and cl.isdigit():
                            total_bytes = response_length = int(cl)

                    if stream_resp.status_code == 206 and not total_bytes:
                        raise ConnectionError("Cannot confirm complete media from an unknown Content-Range total")
                    current = {**representation(stream_resp.headers, total_bytes), "resource": resource}
                    if is_resume and ((previous.get("validator") and current["validator"]
                                       and previous["validator"] != current["validator"])
                                      or (previous.get("total") and total_bytes
                                          and previous["total"] != total_bytes)):
                        # Keep the old partial intact until a full response is accepted.
                        existing_len = request_start = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        continue

                    if total_bytes > 0:
                        task.totalBytes = total_bytes
                        ctx.broadcast_update(task)

                    # Si le .part dépasse la taille totale, purge et reprise depuis 0
                    if total_bytes > 0 and existing_len > total_bytes:
                        logger.warning(".part file (%s) larger than total_bytes (%s) for %s, resetting",
                                       format_bytes(existing_len), format_bytes(total_bytes), task.fileName)
                        part_path.unlink(missing_ok=True)
                        existing_len = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        request_start = 0
                        continue

                    accept_ranges = "bytes" in stream_resp.headers.get("Accept-Ranges", "").lower() or stream_resp.status_code == 206
                    task.supportsResume = accept_ranges

                    # Vérifier si le .part est déjà complet
                    if total_bytes > 0 and existing_len >= total_bytes:
                        logger.info(".part file already complete for %s, verifying", task.fileName)
                        if part_path.exists():
                            verif_part = await asyncio.to_thread(
                                verification_service.verify_file,
                                file_path_str=str(part_path),
                                anime_name=task.animeName,
                                file_name=task.fileName
                            )
                            if verif_part.valid:
                                publish_file(part_path, output_path)
                                metadata_path.unlink(missing_ok=True)
                                await ctx._finalize_task(task)
                                return
                            else:
                                logger.warning(".part file complete but corrupted for %s, resetting", task.fileName)
                                part_path.unlink(missing_ok=True)
                                existing_len = 0
                                is_resume = False
                                req_headers.pop("Range", None)
                                req_headers.pop("If-Range", None)
                                request_start = 0
                                continue

                    # Check disk space
                    free_space = shutil.disk_usage(ctx.download_dir).free
                    req_space = (total_bytes - existing_len) if total_bytes > 0 else 500 * 1024 * 1024
                    if free_space < req_space:
                        raise OSError(f"Espace disque insuffisant (Requis: {format_bytes(req_space)}, Disponible: {format_bytes(free_space)})")

                    # Toujours écrire dans le fichier .part, jamais le fichier final
                    mode = "ab" if is_resume else "wb"
                    downloaded = existing_len
                    task.reset_speed()
                    if downloaded > 0:
                        task.speed_tracker.add_sample(downloaded)
                    last_time = time.time()
                    first_chunk = True
                    overlap = b""
                    if is_resume:
                        with open(part_path, "rb") as existing_file:
                            existing_file.seek(request_start)
                            overlap = existing_file.read(existing_len - request_start)
                    overlap_position = received = 0
                    metadata_written = False

                    if task.status != DownloadStatus.DOWNLOADING:
                        transition(task, DownloadStatus.DOWNLOADING)
                        task.error = None
                        ctx.broadcast_update(task)

                    try:
                        with open(part_path, mode) as f:
                            async for chunk in stream_resp.aiter_bytes(chunk_size=65536):
                                received += len(chunk)
                                if response_length is not None and received > response_length:
                                    raise ConnectionError("Media response exceeds its declared byte range")
                                if overlap_position < len(overlap):
                                    count = min(len(chunk), len(overlap) - overlap_position)
                                    if chunk[:count] != overlap[overlap_position:overlap_position + count]:
                                        raise ResumeMismatch("Media identity changed during resume")
                                    overlap_position += count
                                    chunk = chunk[count:]
                                    if not chunk:
                                        continue
                                if not metadata_written:
                                    write_metadata(metadata_path, current)
                                    metadata_written = True
                                # Vérification des premiers octets pour s'assurer que ce n'est pas du HTML
                                if first_chunk and not is_resume:
                                    head_chk = chunk[:100].lower()
                                    if b"<html" in head_chk or b"<!doctype" in head_chk:
                                        raise ValueError("Contenu reçu est du HTML et non un flux vidéo")
                                    first_chunk = False

                                if task.cancelled:
                                    transition(task, DownloadStatus.CANCELLED)
                                    task.reset_speed()
                                    task.downloadedBytes = downloaded
                                    ctx.broadcast_update(task)
                                    library_service.save_task(task)
                                    logger.info("Cancelled %s — .part file kept (%s)",
                                                task.fileName, format_bytes(downloaded))
                                    return
                                if task.paused:
                                    transition(task, DownloadStatus.PAUSED)
                                    task.reset_speed()
                                    task.downloadedBytes = downloaded
                                    ctx.broadcast_update(task)
                                    library_service.save_task(task)
                                    logger.info("Paused %s — progress saved (%s)",
                                                task.fileName, format_bytes(downloaded))
                                    return

                                f.write(chunk)
                                downloaded += len(chunk)

                                # Throttling
                                await ctx._apply_throttle(task, len(chunk))

                                now = time.time()
                                task.update_progress(downloaded, now)
                                if total_bytes > 0:
                                    task.progress = min(100.0, (downloaded / total_bytes) * 100.0)

                                if now - last_time >= 0.5:
                                    last_time = now
                                    f.flush()
                                    ctx.broadcast_update(task)
                    except ResumeMismatch:
                        logger.warning("Different media bytes after reconnect for %s; restarting safely", task.fileName)
                        existing_len = request_start = 0
                        is_resume = False
                        req_headers.pop("Range", None)
                        req_headers.pop("If-Range", None)
                        continue

                    if overlap_position < len(overlap) or (response_length is not None and received != response_length):
                        raise ConnectionError("Incomplete media response during resume")

                    if total_bytes > 0 and downloaded < total_bytes:
                        raise ConnectionError(f"Incomplete download: {downloaded}/{total_bytes} bytes")
                    if downloaded <= 0:
                        raise ConnectionError("0 bytes received")

                    break

        # Téléchargement complet : renommer .part → fichier final
        if part_path.exists():
            publish_file(part_path, output_path)
            logger.info(".part file renamed to final file: %s (%s)", output_path.name, format_bytes(downloaded))
        metadata_path.unlink(missing_ok=True)

        # Sous-titres
        if task.downloadSubtitles:
            await ctx._download_subtitles(task)

        await ctx._finalize_task(task)


    async def _download_mytv_chunks(self, task: DownloadTask, chunks: List[str]):
        ctx = self.manager
        task.phase = "video"
        ctx.broadcast_update(task)
        logger.info("myTV: %d chunk(s) to download for %s", len(chunks), task.fileName)
        base_path = re.sub(r"\.(mp4|mkv)$", "", task.savePath)
        chunk_files = []
        total_all_chunks = 0

        # Estimer la taille totale
        for curl in chunks:
            sz = await ctx.get_remote_file_size(curl)
            if sz > 0:
                total_all_chunks += sz

        if total_all_chunks > 0:
            task.totalBytes = total_all_chunks
            ctx.broadcast_update(task)

        downloaded_total = 0
        headers = {"User-Agent": proxy_service.get_user_agent(), "Referer": "https://vidzy.live/"}
        proxy = proxy_service.get_random_proxy()

        async with ctx._create_async_client(headers=headers, proxy=proxy, timeout=settings.READ_TIMEOUT) as client:
            for idx, curl in enumerate(chunks):
                if task.cancelled:
                    transition(task, DownloadStatus.CANCELLED)
                    ctx.broadcast_update(task)
                    return
                if task.paused:
                    transition(task, DownloadStatus.PAUSED)
                    ctx.broadcast_update(task)
                    return

                part_file = Path(f"{base_path}_part{idx + 1}.tmp")
                chunk_files.append(part_file)

                async with client.stream("GET", curl) as resp:
                    if resp.status_code not in [200, 206]:
                        raise ConnectionError(f"HTTP {resp.status_code} pour morceau {idx + 1}")

                    last_time = time.time()
                    last_bytes = downloaded_total
                    chunk_downloaded = 0

                    with open(part_file, "wb") as f:
                        async for chunk in resp.aiter_bytes(chunk_size=16384):
                            if task.cancelled:
                                transition(task, DownloadStatus.CANCELLED)
                                task.reset_speed()
                                ctx.broadcast_update(task)
                                return
                            if task.paused:
                                transition(task, DownloadStatus.PAUSED)
                                task.reset_speed()
                                ctx.broadcast_update(task)
                                return

                            f.write(chunk)
                            chunk_downloaded += len(chunk)
                            cur_glob = downloaded_total + chunk_downloaded

                            await ctx._apply_throttle(task, len(chunk))

                            now = time.time()
                            task.update_progress(cur_glob, now)
                            if total_all_chunks > 0:
                                task.progress = (cur_glob / total_all_chunks) * 100.0

                            if now - last_time >= 0.5:
                                last_time = now
                                ctx.broadcast_update(task)

                    expected_length = resp.headers.get('content-length')
                    if expected_length is not None and chunk_downloaded != int(expected_length):
                        raise ConnectionError('Incomplete media chunk')
                    downloaded_total += chunk_downloaded

        if task.downloadSubtitles:
            await ctx._download_subtitles(task)
        ctx.scheduler.release_network(task.id)
        if not await ctx.media_pipeline.assemble_chunks(task, chunk_files):
            return

        await ctx._finalize_task(task)


    async def _download_hls_stream(self, task: DownloadTask, m3u8_url: str):
        ctx = self.manager
        logger.info("HLS download for %s from %s", task.fileName, m3u8_url)
        if task.totalBytes <= 0:
            try:
                est_sz = await ctx.estimate_hls_size(m3u8_url)
                if est_sz > 0:
                    task.totalBytes = est_sz
                    ctx.broadcast_update(task)
            except VerificationRequired:
                raise
            except Exception:
                pass

        # Téléchargement natif par segments avec micro-retries in-situ et reprise sans perte
        await ctx._download_hls_segments_native(task, m3u8_url)


    async def _download_hls_segments_native(self, task: DownloadTask, m3u8_url: str):
        ctx = self.manager
        task.phase = "video"
        ctx.broadcast_update(task)
        logger.info("Segmented HLS download (with resume) for %s", task.fileName)
        output_path = Path(task.savePath)
        output_path.parent.mkdir(parents=True, exist_ok=True)
        segments_dir = output_path.parent / f".{output_path.stem}_segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        headers = ctx.get_headers_for_url(m3u8_url, getattr(task, "selectedServer", None))
        proxy = proxy_service.get_random_proxy()

        timeout = httpx.Timeout(connect=20.0, read=45.0, write=30.0, pool=30.0)
        async with ctx._create_async_client(headers=headers, proxy=proxy, timeout=timeout) as client:
            resp = await client.get(m3u8_url)
            if resp.status_code != 200:
                raise ConnectionError(f"HTTP {resp.status_code} on m3u8 playlist")

            playlist_text = resp.text
            sub_url = m3u8_url
            # Si le m3u8 ne contient pas directement de tags #EXTINF, c'est une master playlist
            if "#EXTINF" not in playlist_text:
                for line in playlist_text.splitlines():
                    line = line.strip()
                    if line and not line.startswith("#"):
                        sub_url = urljoin(m3u8_url, line)
                        break

                if sub_url != m3u8_url:
                    sub_resp = await client.get(sub_url)
                    if sub_resp.status_code != 200:
                        raise ConnectionError(f"HTTP {sub_resp.status_code} on HLS sub-playlist")
                    playlist_text = sub_resp.text

            segments = []
            encryption = []
            current_key = None
            sequence = 0
            for line in playlist_text.splitlines():
                line = line.strip()
                if line.startswith("#EXT-X-MEDIA-SEQUENCE:"):
                    sequence = int(line.split(":", 1)[1])
                elif line.startswith("#EXT-X-KEY:"):
                    attrs = dict(re.findall(r'(\w+)=("[^"\n]*"|[^,\n]*)', line.split(":", 1)[1]))
                    method = attrs.get("METHOD", "NONE")
                    if method == "NONE":
                        current_key = None
                    elif method == "AES-128" and attrs.get("URI"):
                        key_url = urljoin(sub_url, attrs["URI"].strip('"'))
                        iv = bytes.fromhex(attrs["IV"].removeprefix("0x").zfill(32)) if attrs.get("IV") else None
                        if iv is not None and len(iv) != 16:
                            raise ValueError("IV AES-128 HLS invalide")
                        current_key = (key_url, iv)
                    else:
                        raise ValueError("Méthode de chiffrement HLS non prise en charge")
                elif line.startswith(("#EXT-X-BYTERANGE:", "#EXT-X-MAP:")):
                    raise ValueError("HLS byte ranges and initialization maps require a dedicated assembler")
                elif line and not line.startswith("#"):
                    segments.append(urljoin(sub_url, line))
                    encryption.append((current_key[0], current_key[1] or sequence.to_bytes(16, "big")) if current_key else None)
                    sequence += 1
            keys = {}

            if not segments:
                raise ValueError("No segments found in HLS playlist")

            prepare_hls_cache(segments_dir, sub_url, playlist_text)

            total_segments = len(segments)

            # Analyser les segments déjà complétés sur le disque pour reprise instantanée sans perte
            existing_bytes = 0
            completed_indices = set()
            for idx in range(total_segments):
                sf = segments_dir / f"seg_{idx:05d}.ts"
                if valid_cached_segment(sf):
                    existing_bytes += sf.stat().st_size
                    completed_indices.add(idx)

            downloaded = existing_bytes
            if existing_bytes > 0:
                logger.info("HLS resume for %s: %d/%d segments already present (%s)",
                            task.fileName, len(completed_indices), total_segments, format_bytes(existing_bytes))
                task.downloadedBytes = downloaded
                if total_segments > 0:
                    task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                ctx.broadcast_update(task)

            task.reset_speed()
            if task.downloadedBytes > 0:
                task.speed_tracker.add_sample(task.downloadedBytes)
            last_time = time.time()

            for idx, seg_url in enumerate(segments):
                if task.cancelled:
                    shutil.rmtree(segments_dir, ignore_errors=True)
                    transition(task, DownloadStatus.CANCELLED)
                    task.reset_speed()
                    ctx.broadcast_update(task)
                    return
                if task.paused:
                    transition(task, DownloadStatus.PAUSED)
                    task.reset_speed()
                    ctx.broadcast_update(task)
                    return

                seg_file = segments_dir / f"seg_{idx:05d}.ts"
                if idx in completed_indices and seg_file.exists() and seg_file.stat().st_size > 0:
                    continue

                seg_tmp = segments_dir / f"seg_{idx:05d}.tmp"
                max_seg_retries = 5
                seg_success = False

                for attempt in range(1, max_seg_retries + 1):
                    if task.cancelled or task.paused:
                        break
                    seg_bytes_this_attempt = 0
                    try:
                        if hasattr(client, "stream"):
                            async with client.stream("GET", seg_url) as seg_resp:
                                if seg_resp.status_code != 200:
                                    if seg_resp.status_code in (403, 404, 410):
                                        raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx} (expired or not found link)")
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx}")

                                with open(seg_tmp, "wb") as f_seg:
                                    async for chunk_data in seg_resp.aiter_bytes(chunk_size=16384):
                                        if task.cancelled or task.paused:
                                            break
                                        f_seg.write(chunk_data)
                                        chunk_len = len(chunk_data)
                                        seg_bytes_this_attempt += chunk_len
                                        downloaded += chunk_len
                                        await ctx._apply_throttle(task, chunk_len)

                                        now = time.time()
                                        task.update_progress(downloaded, now)
                                        if now - last_time >= 0.5:
                                            last_time = now
                                            task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                                            ctx.broadcast_update(task)
                                declared_length = seg_resp.headers.get("Content-Length")
                                if not (task.cancelled or task.paused) and declared_length is not None and (
                                        not declared_length.isdigit() or int(declared_length) != seg_bytes_this_attempt):
                                    raise ConnectionError(f"Incomplete HLS segment {idx}")
                        else:
                            seg_resp = await client.get(seg_url)
                            if seg_resp.status_code != 200:
                                if seg_resp.status_code in (403, 404, 410):
                                    raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx} (expired or not found link)")
                                raise ConnectionError(f"HTTP {seg_resp.status_code} on segment {idx}")
                            chunk_data = seg_resp.content
                            with open(seg_tmp, "wb") as f_seg:
                                f_seg.write(chunk_data)
                            chunk_len = len(chunk_data)
                            seg_bytes_this_attempt += chunk_len
                            downloaded += chunk_len
                            await ctx._apply_throttle(task, chunk_len)
                            now = time.time()
                            task.update_progress(downloaded, now)

                        if task.cancelled:
                            if seg_tmp.exists():
                                seg_tmp.unlink(missing_ok=True)
                            shutil.rmtree(segments_dir, ignore_errors=True)
                            transition(task, DownloadStatus.CANCELLED)
                            task.reset_speed()
                            ctx.broadcast_update(task)
                            return
                        if task.paused:
                            if seg_tmp.exists():
                                seg_tmp.unlink(missing_ok=True)
                            transition(task, DownloadStatus.PAUSED)
                            task.reset_speed()
                            ctx.broadcast_update(task)
                            return

                        if seg_tmp.exists() and seg_tmp.stat().st_size > 0:
                            if encryption[idx]:
                                key_url, iv = encryption[idx]
                                if key_url not in keys:
                                    key_response = await client.get(key_url)
                                    key_response.raise_for_status()
                                    if len(key_response.content) != 16:
                                        raise ValueError("Clé AES-128 HLS invalide")
                                    keys[key_url] = key_response.content
                                plaintext = media_tools.decrypt_aes_cbc(
                                    seg_tmp.read_bytes(), keys[key_url], iv, unpad=True)
                                seg_tmp.write_bytes(plaintext)
                            commit_segment(seg_tmp, seg_file)
                            completed_indices.add(idx)
                            seg_success = True
                            break
                        else:
                            raise ConnectionError(f"Segment {idx} downloaded empty (0 bytes)")

                    except (VerificationRequired, RateLimited):
                        raise
                    except Exception as seg_err:
                        if seg_bytes_this_attempt > 0:
                            downloaded -= seg_bytes_this_attempt
                            task.downloadedBytes = downloaded
                        if seg_tmp.exists():
                            seg_tmp.unlink(missing_ok=True)

                        err_str = str(seg_err).lower()
                        if "expiré" in err_str or "expired" in err_str or "403" in err_str or "410" in err_str:
                            raise seg_err

                        if attempt >= max_seg_retries:
                            logger.warning("Permanent failure for segment %d/%d after %d retries for %s: %s",
                                           idx + 1, total_segments, max_seg_retries, task.fileName, seg_err)
                            raise seg_err

                        backoff = min(1.0 * attempt, 4.0)
                        logger.warning("Micro-interruption on segment %d/%d for %s (%s), retry %d/%d in %.1fs...",
                                       idx + 1, total_segments, task.fileName, seg_err, attempt + 1, max_seg_retries, backoff)
                        await asyncio.sleep(backoff)

                if not seg_success and not (task.cancelled or task.paused):
                    raise ConnectionError(f"Cannot download segment {idx}")

                now = time.time()
                task.update_progress(downloaded, now)
                task.progress = min(99.0, (len(completed_indices) / total_segments) * 100.0)
                if now - last_time >= 0.5:
                    last_time = now
                    ctx.broadcast_update(task)

        if task.downloadSubtitles:
            await ctx._download_subtitles(task)
        ctx.scheduler.release_network(task.id)
        if not await ctx.media_pipeline.assemble_hls(task, output_path, segments_dir, total_segments):
            return

        await ctx._finalize_task(task)


    async def _apply_throttle(self, task: DownloadTask, bytes_read: int):
        ctx = self.manager
        speed_limit = task.maxSpeedLimit if task.maxSpeedLimit > 0 else ctx.global_speed_limit
        if speed_limit <= 0:
            return

        now_ms = time.time() * 1000
        if task.throttleStartTimeMs == 0:
            task.throttleStartTimeMs = now_ms
            task.throttleBytesWritten = 0

        task.throttleBytesWritten += bytes_read
        elapsed_ms = max(1.0, now_ms - task.throttleStartTimeMs)

        expected_time_ms = (task.throttleBytesWritten * 1000.0) / speed_limit
        sleep_time_ms = expected_time_ms - elapsed_ms

        if sleep_time_ms > 0:
            await asyncio.sleep(min(sleep_time_ms / 1000.0, 1.0))

        if elapsed_ms > 2000 or task.throttleBytesWritten > 1024 * 1024:
            task.throttleStartTimeMs = time.time() * 1000
            task.throttleBytesWritten = 0
