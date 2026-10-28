"""Source resolution registry, extracted without replacing the queue/retry owner."""
import asyncio
import json
import logging
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

from animelab.services.source_http import VerificationRequired
from animelab.services.extractors import extractor_registry
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.media_contracts import ResolvedMedia, merge_stream_metadata

logger = logging.getLogger(__name__)

async def resolve_imported(ctx, task, direct_url, skip_local):
    server_type = "vidzy"
    chunks_json = "[]"
    u_host = (urlparse(direct_url or "").hostname or "").lower()
    is_known_embed = extractor_registry.is_known_embed(direct_url or "")
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
                candidate = target if target and target.get('url') == cand_u else next((row for row in video_sources if row.get("url") == cand_u), {})
                resolved = merge_stream_metadata(cand_res, candidate, task.fileUrl)
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

    resolved = merge_stream_metadata(resolved, target if not candidate_urls else None, task.fileUrl)
    task.requestHeaders = dict(resolved.get("headers") or {})
    task.mediaJson = json.dumps({**json.loads(task.mediaJson), **{key: resolved.get(key, default) for key, default in (("audioTracks", []), ("requirements", []))}})
    direct_url = resolved["videoUrl"]
    server_type = resolved.get("serverType", "imported")
    task.selectedServer = server_type
    task.directDownloadUrl = direct_url
    ctx._update_resolved_subtitles(task, resolved.get("subtitles", []), target_url)
    task.subtitleUrl = resolved.get("subtitleUrl") or task.subtitleUrl
    if resolved.get("size") and task.totalBytes <= 0:
        task.totalBytes = resolved["size"]
    return direct_url, server_type, chunks_json


async def resolve_voir_anime(ctx, task, direct_url, skip_local):
    server_type = "vidzy"
    chunks_json = "[]"
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
    task.requestHeaders = dict(info.get("headers") or {})
    task.mediaJson = json.dumps({**json.loads(task.mediaJson), **{key: info.get(key, default) for key, default in (("audioTracks", []), ("requirements", []))}})
    ctx._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
    return direct_url, server_type, chunks_json


async def resolve_animepahe(ctx, task, direct_url, skip_local):
    server_type = "vidzy"
    chunks_json = "[]"
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
    return direct_url, server_type, chunks_json


async def resolve_scraping(ctx, task, direct_url, skip_local):
    server_type = "vidzy"
    chunks_json = "[]"
    info = await asyncio.to_thread(scraping_service.extract_download_info, direct_url)
    direct_url = info.get("videoUrl", "")
    if not direct_url:
        raise ValueError(f"Impossible d'extraire l'URL vidéo directe pour {task.fileName}")
    task.directDownloadUrl = direct_url
    if (skip_local or not task.subtitleUrl) and info.get("subtitleUrl"):
        task.subtitleUrl = info["subtitleUrl"]
    task.requestHeaders = dict(info.get("headers") or {})
    task.mediaJson = json.dumps({**json.loads(task.mediaJson), **{key: info.get(key, default) for key, default in (("audioTracks", []), ("requirements", []))}})
    if skip_local or not task.subtitlesJson or task.subtitlesJson == "[]":
        ctx._update_resolved_subtitles(task, info.get("subtitles", []), task.fileUrl)
    return direct_url, server_type, chunks_json


async def resolve_direct(ctx, task, direct_url, skip_local):
    server_type = "vidzy"
    chunks_json = "[]"
    task.directDownloadUrl = direct_url
    return direct_url, server_type, chunks_json


class SourceResolverRegistry:
    def __init__(self):
        self.handlers = dict(imported=resolve_imported, voir_anime=resolve_voir_anime,
                             animepahe=resolve_animepahe, scraping=resolve_scraping, direct=resolve_direct)

    def select(self, ctx, task, url):
        imported = ((task.source and task.source not in ('french-manga', 'voir-anime', 'animepahe'))
                    or extractor_registry.is_known_embed(url))
        if imported:
            return 'imported'
        if 'voir-anime' in url.lower() or 'voiranime' in url.lower() or task.source == 'voir-anime':
            return 'voir_anime'
        if any(k in url.lower() for k in ('animepahe', 'kwik.', 'pahe.')) or task.source == 'animepahe':
            return 'animepahe'
        return 'scraping' if ctx._needs_scraping_resolution(url) else 'direct'

    async def resolve(self, ctx, task, *, need_resolve, skip_local):
        url = (task.fileUrl or '').split('#')[0].strip()
        cached_valid = (task.directDownloadUrl and not ctx._needs_scraping_resolution(task.directDownloadUrl)
                        and not re.search(r'vidzy\.[a-z]+/d/', task.directDownloadUrl))
        if cached_valid and not need_resolve:
            direct, server, chunks = task.directDownloadUrl, task.selectedServer or 'vidzy', '[]'
        else:
            handler = self.handlers[self.select(ctx, task, url)]
            direct, server, chunks = await handler(ctx, task, url, skip_local)
        info = json.loads(task.mediaJson)
        info.update(videoUrl=direct, subtitles=json.loads(task.subtitlesJson), headers=task.requestHeaders)
        media = ResolvedMedia.from_info(info, task.fileUrl)
        if server == 'myTV' and chunks != '[]' and len(json.loads(chunks)) > 1:
            from dataclasses import replace
            media = replace(media, protocol='chunks', chunks=tuple(json.loads(chunks)))
        return media
