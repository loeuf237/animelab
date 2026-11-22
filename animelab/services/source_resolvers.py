"""Source resolution registry, extracted without replacing the queue/retry owner."""
import asyncio
import json
import logging
from pathlib import Path
import re
import shutil
from urllib.parse import urlparse

from animelab.services.source_http import VerificationRequired
from animelab.api_errors import APIProblem
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
        if not matched_container and not task.source and u_host:
            for cs in extension_service.get_enabled_container_sources():
                source_host = (urlparse(cs.base_url).hostname or "").lower()
                if source_host and (u_host == source_host or u_host.endswith("." + source_host)):
                    matched_container = cs
                    break
    except (VerificationRequired, APIProblem):
        raise
    except Exception:
        pass

    if not matched_container:
        try:
            from animelab.services.seanime_service import seanime_service
            if task.source and task.source not in ("french-manga", "voir-anime", "animepahe"):
                matched_container = seanime_service.get_source_by_id(task.source)
            elif not task.source:
                for s_src in seanime_service.get_enabled_sources():
                    if s_src.has_reference(task.fileUrl):
                        matched_container = s_src
                        break
                    source_host = (urlparse(s_src.base_url).hostname or "").lower()
                    if source_host and u_host and (u_host == source_host or u_host.endswith("." + source_host)):
                        matched_container = s_src
                        break
        except Exception:
            pass

    if not matched_container and ((task.source or '').startswith('aniyomi:') or (task.source or '').startswith('seanime:')):
        raise APIProblem('source_not_found', status=404, category='not_found')

    native = getattr(matched_container, 'runtime', '') in ('android-apk', 'seanime')
    target_url = task.fileUrl if native else direct_url
    video_sources = []
    # Recipes can attach all alternate players to a known embed in its fragment.
    # Let the selected recipe expand that reference before choosing an extractor.
    if matched_container and (native or not is_known_embed or urlparse(target_url).fragment):
        if getattr(matched_container, 'runtime', '') == 'seanime':
            video_sources = await matched_container.get_episode_sources(
                target_url,
                preferred_server=task.selectedServer,
            )
        else:
            video_sources = await matched_container.get_episode_sources(target_url)
    from animelab.services.extension_media import prioritize_candidates
    candidates = prioritize_candidates(video_sources, task.selectedServer, task.selectedQuality)
    if not candidates and not native:
        candidates = [{'url': target_url}]
    resolved = None
    failures = []
    for candidate in candidates:
        try:
            if native:
                result = await matched_container.resolve_candidate(candidate)
            else:
                result = await ctx.resolve_imported_video_stream(candidate.get('url') or target_url,
                    referer=task.fileUrl, preferred_quality=task.selectedQuality)
            if result and result.get('videoUrl'):
                resolved = merge_stream_metadata(result, candidate, task.fileUrl)
                break
        except VerificationRequired:
            raise
        except Exception as failure:
            failures.append(failure)
    if not resolved or not resolved.get('videoUrl'):
        if native:
            if failures:
                raise failures[0]
            kind = 'Seanime' if getattr(matched_container, 'runtime', '') == 'seanime' else 'APK'
            raise ValueError(f'Cette extension {kind} n’a renvoyé aucun flux vidéo pour cet épisode.')
        clean_t = target_url.split('#')[0].strip()
        if re.search(r'\.(mp4|m3u8|webm|mkv)(\?.*)?$', clean_t, re.IGNORECASE):
            resolved = {'videoUrl': clean_t, 'serverType': 'direct', 'selectedQuality': task.selectedQuality or 'HD'}
        else:
            raise ValueError(f"Impossible de résoudre le flux vidéo de la source importée pour {task.fileName}")

    task.requestHeaders = dict(resolved.get("headers") or {})
    task.mediaJson = json.dumps({**json.loads(task.mediaJson), **{key: resolved.get(key, default) for key, default in (("audioTracks", []), ("requirements", []))}})
    direct_url = resolved["videoUrl"]
    server_type = resolved.get("serverType", "imported")
    task.selectedServer = server_type
    task.selectedQuality = resolved.get("selectedQuality") or task.selectedQuality
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
        # Extension episode fragments can carry the source's identity/memo key.
        # Strip only at the HTTP boundary, never before the APK/recipe callback.
        url = (task.fileUrl or '').strip()
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
