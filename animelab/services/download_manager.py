from animelab.services.download_stages.state import transition
from animelab.services.download_errors import SubtitleError
from animelab.services.download_stages.transfer import TransferWorker
from animelab.services.download_stages.media import MediaPipeline
from animelab.services.download_stages.export import ExportCoordinator
from animelab.services.download_stages.scheduler import DownloadScheduler
from animelab.services.source_http import source_http, VerificationRequired, RateLimited, PROFILE
import asyncio
import errno
from animelab.services.background import spawn
import json
import logging
import math
import os
import re
import shutil
import socket
import subprocess
from animelab import media_tools, platform_events
import tempfile
import time
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path
from typing import Dict, List, Optional, Any, Tuple
from urllib.parse import urljoin, urlparse

import httpx

from animelab.config import settings
from animelab.models.download_task import DownloadTask, DownloadStatus, ExportStatus, format_bytes, ensure_utc
from animelab.services.library_service import library_service
from animelab.services import download_preferences
from animelab.services.proxy_service import proxy_service
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.verification_service import verification_service, VerificationResult
from animelab.services.extractors import extractor_registry
from animelab.services.subtitle_service import normalize_subtitles, subtitle_extension, subtitle_language
from animelab.services.media_contracts import merge_stream_metadata
from animelab.services.output_profiles import snapshot, require_available
from animelab.services.download_resume import (RESUME_OVERLAP, ResumeMismatch, read_metadata,
    valid_cached_segment, commit_segment, publish_file, media_resource,
                                            write_metadata, representation, response_range, prepare_hls_cache)
from animelab.security import is_safe_path, is_safe_url

logger = logging.getLogger("animelab.download_manager")

class ResolvedVideoInfo:
    def __init__(self):
        self.direct_url: str = ""
        self.subtitle_url: str = ""
        self.subtitles_json: str = "[]"
        self.media_json: str = "{}"
        self.headers: dict = {}
        self.size: int = -1
        self.formatted_size: str = "Taille inconnue"
        self.server_type: str = "unknown"
        self.video_chunks_json: str = "[]"
        self.video_qualities_json: str = "{}"
        self.available_servers: List[str] = []
        self.selected_server: str = ""
        self.selected_quality: str = ""
        self.qualities_sizes_json: str = "{}"

class DownloadManagerService:
    def __init__(self):
        self.download_dir: str = settings.DOWNLOAD_DIR
        self.max_concurrent_downloads: int = settings.MAX_CONCURRENT_DOWNLOADS
        self.global_speed_limit: int = 0
        self.plex_organization: bool = False
        self.voiranime_default_server: str = settings.VOIRANIME_DEFAULT_SERVER

        self.tasks: Dict[str, DownloadTask] = {}
        self.task_order: List[str] = []
        self.transfer_worker = TransferWorker(self)
        self.media_pipeline = MediaPipeline(self)
        self.export_coordinator = ExportCoordinator(self)
        self.scheduler = DownloadScheduler(self)
        # Compatibility aliases for integrations; each stage owns its state.
        self._finalization_locks = self.media_pipeline.locks
        self._media_jobs = self.media_pipeline.jobs
        self._export_locks = self.export_coordinator.locks
        self._native_exports = self.export_coordinator.jobs
        self.sse_subscribers: List[asyncio.Queue] = []
        self.resolved_info_cache: Dict[str, ResolvedVideoInfo] = {}

        self._active_workers: int = 0
        self._lock = self.scheduler.lock
        self._info_semaphore = asyncio.Semaphore(4)

    def _create_async_client(
        self,
        headers: Optional[Dict[str, str]] = None,
        proxy: Optional[str] = None,
        timeout: Any = 10.0,
        follow_redirects: bool = True,
    ) -> httpx.AsyncClient:
        return source_http.async_client(headers=headers, timeout=timeout, follow_redirects=follow_redirects)

    def _trigger_process_queue(self):
        if self.scheduler.closing:
            return
        try:
            loop = asyncio.get_running_loop()
            spawn(self.process_queue(), name="process-queue")
        except RuntimeError:
            pass

    async def is_client_online(self) -> bool:
        """
        Vérifie si la machine locale dispose d'un accès actif au réseau Internet.
        Permet de distinguer formellement une coupure locale (perte Wi-Fi / 4G / câble débranché)
        d'une indisponibilité spécifique du serveur d'hébergement distant.
        """
        loop = asyncio.get_running_loop()

        def _socket_probe() -> bool:
            for host, port in [("1.1.1.1", 53), ("8.8.8.8", 53), ("9.9.9.9", 53)]:
                try:
                    s = socket.create_connection((host, port), timeout=2.0)
                    s.close()
                    return True
                except Exception:
                    continue
            return False

        try:
            if await loop.run_in_executor(None, _socket_probe):
                return True
        except Exception:
            pass

        # Fallback HTTP au cas où les ports DNS UDP/TCP 53 soient bloqués
        try:
            async with httpx.AsyncClient(timeout=3.0, trust_env=False) as client:
                r = await client.head("http://connectivitycheck.gstatic.com/generate_204")
                if r.status_code in (200, 204):
                    return True
        except Exception:
            pass

        return False

    def init_from_db(self):
        self.scheduler.closing = False
        self._load_preferences()
        try:
            library_service.recover_interrupted_exports()
            unfinished = library_service.get_unfinished_tasks()
            restored = [entity.to_task() for entity in unfinished]
            for task in restored:
                if task.status == DownloadStatus.VERIFICATION_REQUIRED and task.verificationUrl:
                    source_http.state(task.verificationUrl).blocked_url = task.verificationUrl
            destinations = {}
            for task in restored:
                if task.savePath:
                    destinations.setdefault(task.savePath, set()).add(task.downloadPageUrl or task.fileUrl)
            conflicts = {path for path, urls in destinations.items() if len(urls) > 1}
            for task in restored:
                if task.status == DownloadStatus.COMPLETED:
                    # A pending export does not invalidate verified media or
                    # require another full video scan during startup.
                    self.tasks[task.id] = task
                    self.task_order.append(task.id)
                    continue
                if task.savePath in conflicts:
                    self._pause_destination_conflict(task)
                    self.tasks[task.id] = task
                    self.task_order.append(task.id)
                    continue
                # Vérifier si le fichier final est en réalité déjà complet et valide sur disque
                if task.savePath:
                    out_path = Path(task.savePath)
                    part_path = Path(task.savePath + ".part")
                    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                        verif = verification_service.verify_file(str(out_path), task.animeName, task.fileName)
                        if verif.valid and not self._has_pending_subtitles(task):
                            transition(task, DownloadStatus.COMPLETED)
                            task.progress = 100.0
                            task.downloadedBytes = out_path.stat().st_size
                            task.totalBytes = max(task.totalBytes, out_path.stat().st_size)
                            task.verificationStatus = verif.status
                            task.videoDuration = verif.duration
                            task.error = None
                            if platform_events.completed_handler is not None and task.exportStatus == ExportStatus.NOT_REQUESTED:
                                task.exportStatus = ExportStatus.PENDING
                            library_service.save_task(task)
                            library_service.mark_as_downloaded(task.animeUrl or task.downloadPageUrl or "", task.animeName, task.episodeNumber, task.version)
                            self.tasks[task.id] = task
                            self.task_order.append(task.id)
                            continue
                    elif part_path.exists() and part_path.stat().st_size > 0:
                        task.downloadedBytes = part_path.stat().st_size
                        if task.totalBytes > 0:
                            task.progress = min(99.9, (task.downloadedBytes / task.totalBytes) * 100.0)

                if task.status in [DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING, DownloadStatus.MUXING]:
                    transition(task, DownloadStatus.PAUSED)
                    task.speed = 0
                    library_service.save_task(task)
                self.tasks[task.id] = task
                self.task_order.append(task.id)
            # Completed downloads must remain available in the local player
            # after restarting, including media with no Android export work.
            for entity in library_service.get_completed_tasks():
                if entity.id not in self.tasks:
                    self.tasks[entity.id] = entity.to_task()
                    self.task_order.append(entity.id)
            logger.info("Loaded %d task(s) from database at startup", len(self.tasks))
        except Exception as e:
            logger.error("Error loading unfinished tasks: %s", e)

    # -------------------------------------------------------------------------
    # Paramètres et Configuration
    # -------------------------------------------------------------------------

    async def shutdown(self):
        await self.scheduler.close()

    def _preferences(self):
        return dict(max_concurrent=self.max_concurrent_downloads, global_limit=self.global_speed_limit,
                    plex_org=self.plex_organization, user_agent=proxy_service.get_selected_user_agent(),
                    default_server=self.voiranime_default_server)

    def _load_preferences(self):
        saved = download_preferences.load()
        if saved is not None:
            self.max_concurrent_downloads = saved['max_concurrent']
            self.global_speed_limit = saved['global_limit']
            self.plex_organization = bool(saved['plex_org'])
            self.voiranime_default_server = saved['default_server']
            voiranime_service.default_server = self.voiranime_default_server
            proxy_service.set_selected_user_agent(saved['user_agent'])

    def get_settings(self) -> Dict[str, Any]:
        return {
            "maxConcurrentDownloads": self.max_concurrent_downloads,
            "mediaWorkers": self.media_pipeline.budget.limit,
            "exportWorkers": self.export_coordinator.budget.limit,
            "globalSpeedLimit": self.global_speed_limit,
            "plexOrganization": self.plex_organization,
            "selectedUserAgent": proxy_service.get_selected_user_agent(),
            "networkProfile": PROFILE,
            "voiranimeDefaultServer": self.voiranime_default_server,
            "ffmpegAvailable": self.is_ffmpeg_available(),
            "proxy": proxy_service.get_proxy_settings(),
        }

    def update_settings(
        self,
        max_concurrent: int,
        global_limit: int,
        plex_org: bool,
        user_agent: Optional[str] = None,
        voiranime_default_server: Optional[str] = None,
    ):
        # Commit first: a failed write must not appear as a successful setting
        # change, and a single transaction preserves all preferences together.
        values = self._preferences()
        values.update(max_concurrent=max(1, max_concurrent), global_limit=max(0, global_limit), plex_org=plex_org)
        if user_agent:
            values['user_agent'] = user_agent.strip() or 'Random (Rotator)'
        if voiranime_default_server:
            values['default_server'] = voiranime_default_server
        download_preferences.save(values)
        self.max_concurrent_downloads = values['max_concurrent']
        self.set_global_speed_limit(values['global_limit'], persist=False)
        self.plex_organization = plex_org
        if user_agent:
            proxy_service.set_selected_user_agent(user_agent)
        if voiranime_default_server:
            self.voiranime_default_server = voiranime_default_server
            voiranime_service.default_server = voiranime_default_server
        self._trigger_process_queue()

    def set_global_speed_limit(self, limit_bytes_per_sec: int, *, persist=True):
        limit_bytes_per_sec = max(0, limit_bytes_per_sec)
        if persist:
            values = self._preferences()
            values['global_limit'] = limit_bytes_per_sec
            download_preferences.save(values)
        self.global_speed_limit = limit_bytes_per_sec
        for t in self.tasks.values():
            if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING]:
                t.maxSpeedLimit = self.global_speed_limit

    def set_task_speed_limit(self, task_id: str, limit: int) -> bool:
        task = self.tasks.get(task_id)
        if task:
            task.maxSpeedLimit = max(0, limit)
            self.broadcast_update(task)
            return True
        return False

    # -------------------------------------------------------------------------
    # Vérification Doublon & Taille distante
    # -------------------------------------------------------------------------

    def _pause_destination_conflict(self, task):
        task.paused = True
        transition(task, DownloadStatus.PAUSED)
        task.speed = 0
        task.error = "Plusieurs liens partagent ce fichier. Relancez la version souhaitée depuis la fiche animé."
        library_service.save_task(task)
        self.broadcast_update(task)

    def _has_destination_conflict(self, task):
        return bool(task.savePath and any(
            other.id != task.id and other.savePath == task.savePath
            and other.status != DownloadStatus.CANCELLED
            and (other.downloadPageUrl or other.fileUrl) != (task.downloadPageUrl or task.fileUrl)
            for other in self.tasks.values()))

    def _active_episode_task(self, url: str, source: str, version: str):
        active = {DownloadStatus.PENDING, DownloadStatus.DOWNLOADING, DownloadStatus.SCHEDULED,
                  DownloadStatus.PAUSED, DownloadStatus.RETRYING, DownloadStatus.MUXING,
                  DownloadStatus.VERIFICATION_REQUIRED}
        return next((task for task in self.tasks.values()
                     if task.status in active and task.downloadPageUrl == url
                     and task.source == source and task.version == version), None)

    def _version_suffix(self, version: str) -> str:
        clean = self.sanitize_file_name(version) if version else ""
        return f" [{clean}]" if clean else ""

    def _versioned_filename(self, name: str, version: str) -> str:
        suffix = self._version_suffix(version)
        path = Path(name)
        if suffix and not path.stem.endswith(suffix):
            return f"{path.stem}{suffix}{path.suffix or '.mp4'}"
        return name

    def check_existing_file(self, anime_name: str, file_name: str, episode_number: int, version: str = "") -> Optional[Path]:
        if not anime_name or not file_name:
            return None

        file_name = self._versioned_filename(file_name, version)
        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_name = f"{clean_anime} - S01E{episode_number:02d}{self._version_suffix(version)}{ext}"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
            final_name = self.sanitize_file_name(file_name)

        exact_file = anime_dir / final_name
        if exact_file.exists():
            return exact_file

        base_name = re.sub(r"\.(mp4|mkv|avi)$", "", final_name)
        for ext in [".mp4", ".mkv", ".avi"]:
            alt = anime_dir / f"{base_name}{ext}"
            if alt.exists():
                return alt

        return None

    def get_headers_for_url(self, url: str, server_type: Optional[str] = None) -> Dict[str, str]:
        return extractor_registry.get_headers_for_url(url, server_type)

    async def get_remote_file_size(
        self,
        url: str,
        headers: Optional[Dict[str, str]] = None,
        server_type: Optional[str] = None,
    ) -> int:
        if not url:
            return -1
        if ".m3u8" in url.lower():
            return await self.estimate_hls_size(url, headers=headers, server_type=server_type)

        try:
            req_headers = headers or self.get_headers_for_url(url, server_type)
            async with self._create_async_client(
                headers=req_headers,
                timeout=8.0,
                follow_redirects=True,
            ) as client:
                try:
                    resp = await client.head(url)
                    if resp.status_code == 200:
                        cl = resp.headers.get("Content-Length")
                        if cl and cl.isdigit() and int(cl) > 1024:
                            return int(cl)
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                # Essai Range: bytes=0-0 pour les serveurs rejetant HEAD (ex: Sibnet)
                try:
                    range_resp = await client.get(url, headers={"Range": "bytes=0-0"})
                    cr = range_resp.headers.get("Content-Range")
                    if cr and "/" in cr:
                        total_str = cr.split("/")[-1].strip()
                        if total_str.isdigit():
                            return int(total_str)
                    cl2 = range_resp.headers.get("Content-Length")
                    if cl2 and cl2.isdigit() and int(cl2) > 0 and range_resp.status_code == 200:
                        return int(cl2)
                except VerificationRequired:
                    raise
                except Exception:
                    pass
        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Error in get_remote_file_size for %s: %s", url, e)
        return -1

    async def estimate_hls_size(
        self,
        m3u8_url: str,
        headers: Optional[Dict[str, str]] = None,
        bandwidth: Optional[int] = None,
        server_type: Optional[str] = None,
    ) -> int:
        if not m3u8_url:
            return -1
        req_headers = headers or self.get_headers_for_url(m3u8_url, server_type or "myTV")

        try:
            async with self._create_async_client(
                headers=req_headers,
                timeout=8.0,
                follow_redirects=True,
            ) as client:
                resp = await client.get(m3u8_url)
                if resp.status_code != 200:
                    return -1

                text = resp.text
                target_variant_url = m3u8_url
                est_bandwidth = bandwidth or 0

                # Cas 1: Master playlist (#EXT-X-STREAM-INF)
                if "#EXT-X-STREAM-INF:" in text:
                    lines = text.strip().splitlines()
                    best_bw = 0
                    chosen_rel = ""
                    for i, line in enumerate(lines):
                        line_s = line.strip()
                        if line_s.startswith("#EXT-X-STREAM-INF:"):
                            bw_m = re.search(r"BANDWIDTH=(\d+)", line_s)
                            bw = int(bw_m.group(1)) if bw_m else 0
                            if i + 1 < len(lines):
                                cand_url = lines[i + 1].strip()
                                if not cand_url.startswith("#") and bw >= best_bw:
                                    best_bw = bw
                                    chosen_rel = cand_url
                    if chosen_rel:
                        target_variant_url = urljoin(m3u8_url, chosen_rel)
                        if best_bw > 0:
                            est_bandwidth = best_bw
                        v_resp = await client.get(target_variant_url)
                        if v_resp.status_code == 200:
                            text = v_resp.text

                # Cas 2: Analyse de la variante
                durations = [float(d) for d in re.findall(r"#EXTINF:([\d.]+)", text)]
                total_duration = sum(durations)
                segs = [l.strip() for l in text.splitlines() if l.strip() and not l.strip().startswith("#")]

                if not segs:
                    return -1

                if total_duration <= 0:
                    td_m = re.search(r"#EXT-X-TARGETDURATION:(\d+)", text)
                    target_dur = float(td_m.group(1)) if td_m else 10.0
                    total_duration = len(segs) * target_dur

                if est_bandwidth > 0 and total_duration > 0:
                    return int((est_bandwidth * total_duration) / 8)

                # Fallback: échantillonnage parallèle HEAD de 2 à 3 segments
                sample_indices = list(set([0, len(segs) // 2, max(0, len(segs) - 2)]))

                async def sample_seg(idx: int) -> int:
                    seg_u = segs[idx]
                    if not seg_u.startswith("http"):
                        seg_u = urljoin(target_variant_url, seg_u)
                    try:
                        hr = await client.head(seg_u, timeout=5.0)
                        cl = hr.headers.get("Content-Length")
                        if cl and cl.isdigit() and int(cl) > 0:
                            return int(cl)
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass
                    return -1

                sampled_results = await asyncio.gather(*(sample_seg(i) for i in sample_indices), return_exceptions=True)
                valid_samples = [s for s in sampled_results if isinstance(s, int) and s > 0]
                if valid_samples:
                    avg_seg_size = sum(valid_samples) / len(valid_samples)
                    return int(avg_seg_size * len(segs))

                if total_duration > 0:
                    return int((1_800_000 * total_duration) / 8)

        except VerificationRequired:
            raise
        except Exception as e:
            logger.debug("Error in estimate_hls_size for %s: %s", m3u8_url, e)

        return -1

    async def resolve_imported_video_stream(
        self,
        url: str,
        referer: Optional[str] = None,
        preferred_quality: Optional[str] = None,
        source_info: Optional[Dict[str, Any]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Résout l'URL directe (m3u8 ou mp4) pour les sources importées et hébergeurs vidéo
        en déléguant au hub modulaire d'extracteurs vidéo.
        """
        if not url:
            return None

        clean_url = url.split("#")[0].strip()

        # 1. Si l'URL est déjà un flux vidéo direct (mp4, m3u8, webm, mkv)
        if re.search(r"\.(mp4|m3u8|webm|mkv)(\?.*)?$", clean_url, re.IGNORECASE):
            is_hls = ".m3u8" in clean_url.lower()
            headers = self.get_headers_for_url(clean_url, "imported")
            if referer:
                headers["Referer"] = referer
            headers.update((source_info or {}).get('headers') or {})
            sz = (
                await self.estimate_hls_size(clean_url, headers=headers)
                if is_hls
                else await self.get_remote_file_size(clean_url, headers=headers, server_type="imported")
            )
            return merge_stream_metadata({
                "videoUrl": clean_url,
                "serverType": "direct",
                "selectedQuality": preferred_quality or "HD",
                "videoQualities": json.dumps({"HD": clean_url}),
                "size": sz,
                "headers": headers,
            }, source_info, referer or clean_url)

        # 2. Délégation aux extracteurs dédiés
        res = await extractor_registry.extract(clean_url, referer=referer, preferred_quality=preferred_quality)
        if res and res.video_url:
            info = res.to_download_info()
            if info.get("size", -1) <= 0:
                is_hls = ".m3u8" in info["videoUrl"].lower()
                headers = info.get("headers") or self.get_headers_for_url(info["videoUrl"], info["serverType"])
                sz = (
                    await self.estimate_hls_size(info["videoUrl"], headers=headers, server_type=info["serverType"])
                    if is_hls
                    else await self.get_remote_file_size(info["videoUrl"], headers=headers, server_type=info["serverType"])
                )
                info["size"] = sz
            return merge_stream_metadata(info, source_info, referer or clean_url)

        return None

    async def get_or_resolve_episode_info(
        self,
        download_page_url: str,
        preferred_server: Optional[str] = None,
        preferred_quality: Optional[str] = None,
        source: Optional[str] = None,
    ) -> Optional[ResolvedVideoInfo]:
        if not download_page_url:
            return None
        eff_server_key = preferred_server or self.voiranime_default_server
        cache_key = f"{download_page_url}::{source or ''}::{eff_server_key}::{preferred_quality or ''}"
        if cache_key in self.resolved_info_cache:
            return self.resolved_info_cache[cache_key]

        async with self._info_semaphore:
            if cache_key in self.resolved_info_cache:
                return self.resolved_info_cache[cache_key]

            try:
                info = ResolvedVideoInfo()
                parsed_u = urlparse(download_page_url)
                u_host = (parsed_u.hostname or "").lower()
                clean_page_url = download_page_url.split("#")[0].strip()
                is_known_embed = extractor_registry.is_known_embed(clean_page_url)
                is_imported = bool(source and source not in ("french-manga", "voir-anime", "animepahe")) or is_known_embed

                matched_container = None
                try:
                    from animelab.services.extension_service import extension_service
                    if source and source not in ("french-manga", "voir-anime", "animepahe"):
                        matched_container = extension_service.get_container_source_by_id(source)
                    if not matched_container and u_host:
                        for cs in extension_service.get_enabled_container_sources():
                            if cs.base_url and u_host in cs.base_url.lower():
                                matched_container = cs
                                break
                except VerificationRequired:
                    raise
                except Exception:
                    pass

                if matched_container:
                    is_imported = True

                is_voir_anime = not is_imported and (source == "voir-anime" or "voir-anime" in download_page_url)
                is_animepahe = not is_imported and (source == "animepahe" or any(k in download_page_url for k in ["animepahe", "kwik.", "pahe."]))

                if is_imported:
                    target_url = download_page_url
                    avail_servers = []
                    qualities = {}
                    video_sources = []
                    if matched_container and not is_known_embed:
                        try:
                            video_sources = await matched_container.get_episode_sources(download_page_url)
                        except VerificationRequired:
                            raise
                        except Exception as e:
                            logger.debug("[download_manager] Error getting episode sources: %s", e)
                            video_sources = []

                        if video_sources:
                            for vs in video_sources:
                                s_name = vs.get("server") or vs.get("name")
                                if s_name and s_name not in avail_servers:
                                    avail_servers.append(s_name)
                                qualities[s_name or "Serveur"] = vs.get("url", "")

                        target = None
                        if preferred_server and preferred_server != "auto":
                            for s in video_sources:
                                s_srv = s.get("server") or s.get("name") or ""
                                if preferred_server.lower() in s_srv.lower():
                                    target = s
                                    break
                        if not target and preferred_quality and preferred_quality != "auto":
                            for s in video_sources:
                                q_name = s.get("quality") or s.get("server") or ""
                                if preferred_quality.lower() in q_name.lower():
                                    target = s
                                    break
                        if not target and video_sources:
                            target = video_sources[0]
                        if target and target.get("url"):
                            target_url = target.get("url", "")

                    # Résolution du flux direct via resolve_imported_video_stream avec repli
                    resolved = None
                    candidate_urls = []
                    if target and target.get("url"):
                        candidate_urls.append(target.get("url"))
                    if video_sources:
                        for s in video_sources:
                            u_ = s.get("url")
                            if u_ and u_ not in candidate_urls:
                                candidate_urls.append(u_)

                    for cand_u in (candidate_urls or [target_url]):
                        try:
                            cand_res = await self.resolve_imported_video_stream(
                                cand_u, preferred_quality=preferred_quality
                            )
                            if cand_res and cand_res.get("videoUrl"):
                                candidate = target if target and target.get('url') == cand_u else next((row for row in video_sources if row.get("url") == cand_u), {})
                                resolved = merge_stream_metadata(cand_res, candidate, download_page_url)
                                break
                        except VerificationRequired:
                            raise
                        except Exception:
                            pass

                    if resolved and resolved.get("videoUrl"):
                        dl_info = resolved
                    else:
                        raise ValueError("Aucun flux vidéo résolu pour cette extension.")
                    info.server_type = dl_info.get("serverType", "imported")
                    info.available_servers = avail_servers if avail_servers else [info.server_type]
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    info.selected_server = info.server_type
                    info.selected_quality = dl_info.get("selectedQuality", "HD")
                    if dl_info.get("size"):
                        info.size = dl_info["size"]
                elif is_voir_anime:
                    eff_server = preferred_server or self.voiranime_default_server
                    dl_info = await asyncio.to_thread(
                        voiranime_service.extract_download_info,
                        download_page_url,
                        preferred_server=eff_server,
                        preferred_quality=preferred_quality,
                    )
                    info.server_type = dl_info.get("serverType", "unknown")
                    info.video_chunks_json = dl_info.get("videoChunks", "[]")
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    raw_avail = dl_info.get("availableServers", "[]")
                    if isinstance(raw_avail, str):
                        try:
                            info.available_servers = json.loads(raw_avail)
                        except VerificationRequired:
                            raise
                        except Exception:
                            info.available_servers = []
                    elif isinstance(raw_avail, list):
                        info.available_servers = raw_avail
                    info.selected_server = dl_info.get("serverType", "")
                    info.selected_quality = dl_info.get("selectedQuality", "")
                    info.qualities_sizes_json = dl_info.get("qualitiesSizes", "{}")

                    # Si extract_download_info a déjà extrait une taille positive
                    if dl_info.get("size") and int(dl_info.get("size", -1)) > 0:
                        info.size = int(dl_info["size"])
                elif is_animepahe:
                    from animelab.services.animepahe_service import animepahe_service
                    info.server_type = "kwik"
                    info.available_servers = ["kwik"]

                    if ("kwik." in download_page_url or "pahe." in download_page_url) and ("/e/" in download_page_url or "/d/" in download_page_url):
                        direct_url = await animepahe_service.extract_kwik_stream(download_page_url)
                        dl_info = {
                            "videoUrl": direct_url or "",
                            "serverType": "kwik",
                            "selectedQuality": preferred_quality or "HD",
                            "videoQualities": json.dumps({preferred_quality or "HD": download_page_url}),
                        }
                    elif preferred_server and ("kwik." in preferred_server or "pahe." in preferred_server):
                        direct_url = await animepahe_service.extract_kwik_stream(preferred_server)
                        dl_info = {
                            "videoUrl": direct_url or "",
                            "serverType": "kwik",
                            "selectedQuality": preferred_quality or "HD",
                        }
                    else:
                        sources = await animepahe_service.get_episode_sources(download_page_url)
                        qualities = {}
                        qualities_sizes = {}
                        target = None
                        for s in sources:
                            q_name = s.get("name") or f"{s.get('quality', 'HD')} ({s.get('audio', 'sub')})"
                            raw_q = (s.get("quality") or "").lower()
                            qualities[q_name] = s.get("url", "")

                            # Estimation de la taille selon la résolution sans appeler Kwik pour éviter le code 429
                            if "360" in raw_q or "360" in q_name:
                                est_bytes = 95 * 1024 * 1024
                            elif "1080" in raw_q or "1080" in q_name:
                                est_bytes = 420 * 1024 * 1024
                            else:
                                est_bytes = 220 * 1024 * 1024
                            qualities_sizes[q_name] = format_bytes(est_bytes)

                            if preferred_quality and (preferred_quality.lower() in q_name.lower() or preferred_quality.lower() in raw_q):
                                if not target:
                                    target = s
                        if not target and sources:
                            target = sources[0]

                        sel_q = preferred_quality or "HD"
                        target_url = ""
                        target_size = 220 * 1024 * 1024
                        if target:
                            sel_q = target.get("name") or target.get("quality", "HD")
                            target_url = target.get("url", "")
                            raw_tq = (target.get("quality") or "").lower()
                            if "360" in raw_tq or "360" in sel_q:
                                target_size = 95 * 1024 * 1024
                            elif "1080" in raw_tq or "1080" in sel_q:
                                target_size = 420 * 1024 * 1024
                            else:
                                target_size = 220 * 1024 * 1024

                        dl_info = {
                            "videoUrl": target_url,
                            "serverType": "kwik",
                            "selectedQuality": sel_q,
                            "videoQualities": json.dumps(qualities),
                            "qualitiesSizes": json.dumps(qualities_sizes),
                            "size": target_size,
                        }
                    info.video_qualities_json = dl_info.get("videoQualities", "{}")
                    info.qualities_sizes_json = dl_info.get("qualitiesSizes", "{}")
                    info.selected_server = "kwik"
                    info.selected_quality = dl_info.get("selectedQuality", "")
                    if dl_info.get("size"):
                        info.size = dl_info["size"]
                else:
                    dl_info = await asyncio.to_thread(scraping_service.extract_download_info, download_page_url)
                    info.server_type = "vidzy"

                info.media_json = json.dumps({key: dl_info.get(key, default) for key, default in (("audioTracks", []), ("requirements", []))})
                info.headers = dl_info.get("headers") or {}
                info.direct_url = dl_info.get("videoUrl", "")
                info.subtitle_url = dl_info.get("subtitleUrl", "")
                info.subtitles_json = json.dumps(normalize_subtitles(dl_info.get("subtitles", []), download_page_url))

                # Si la taille n'est pas encore déterminée
                if info.size <= 0 and info.direct_url:
                    if ".m3u8" in info.direct_url.lower() or info.server_type == "myTV":
                        info.size = await self.estimate_hls_size(info.direct_url, server_type=info.server_type)
                    else:
                        info.size = await self.get_remote_file_size(info.direct_url, server_type=info.server_type)

                info.formatted_size = format_bytes(info.size) if info.size > 0 else "Taille inconnue"

                # Si qualities_sizes_json est vide mais qu'on a la taille, générer pour la qualité sélectionnée
                if (not info.qualities_sizes_json or info.qualities_sizes_json == "{}") and info.size > 0:
                    info.qualities_sizes_json = json.dumps({info.selected_quality or "HD": info.formatted_size})

                # Mettre en cache seulement les résultats avec taille valide
                if info.size > 0:
                    self.resolved_info_cache[cache_key] = info

                return info
            except VerificationRequired:
                raise
            except Exception as e:
                logger.error("Error in get_or_resolve_episode_info: %s", e)
                return None

    # -------------------------------------------------------------------------
    # Démarrage des téléchargements
    # -------------------------------------------------------------------------

    def start_download(
        self,
        anime_name: str,
        episode_number: int,
        download_page_url: str,
        file_name: str,
        subtitle_url: Optional[str] = None,
        scheduled_start_time: Optional[datetime] = None,
        speed_limit: int = 0,
        download_subtitles: bool = False,
        selected_server: Optional[str] = None,
        selected_quality: Optional[str] = None,
        source: str = "french-manga",
        version: str = "",
        anime_url: str = "",
        output_profile: Optional[dict] = None,
    ) -> DownloadTask:
        profile_json = snapshot(output_profile, legacy_subtitles=download_subtitles)
        profile = require_available(profile_json)
        download_subtitles = profile.mode != "ORIGINAL"
        existing_task = self._active_episode_task(download_page_url, source, version)
        if existing_task:
            return existing_task
        file_name = self._versioned_filename(file_name, version)
        cache_key = f"{download_page_url}::{source}::{selected_server or self.voiranime_default_server}::{selected_quality or ''}"
        cached = self.resolved_info_cache.get(cache_key)
        if not cached and not (selected_server or selected_quality):
            cached = self.resolved_info_cache.get(download_page_url)
        initial_total_bytes = cached.size if cached and cached.size > 0 else 0
        resolved_subs = cached.subtitles_json if cached else "[]"

        scheduled_start_time = ensure_utc(scheduled_start_time)
        now = datetime.now(timezone.utc)
        is_scheduled = scheduled_start_time is not None and scheduled_start_time > now
        status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

        file_name = self._versioned_filename(file_name, version)
        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
            ext = Path(file_name).suffix or ".mp4"
            final_file_name = f"{clean_anime} - S01E{episode_number:02d}{self._version_suffix(version)}{ext}"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
            final_file_name = self.sanitize_file_name(file_name)

        if not is_safe_path(anime_dir, [self.download_dir]):
            anime_dir = Path(self.download_dir) / "Downloads"

        anime_dir.mkdir(parents=True, exist_ok=True)
        save_path = str(anime_dir / final_file_name)

        task = DownloadTask(
            animeName=anime_name,
            episodeNumber=episode_number,
            fileName=final_file_name,
            fileUrl=download_page_url,
            savePath=save_path,
            downloadPageUrl=download_page_url,
            subtitleUrl=subtitle_url,
            subtitlesJson=resolved_subs,
            mediaJson=cached.media_json if cached else "{}",
            outputProfileJson=profile_json,
            downloadSubtitles=download_subtitles,
            status=status,
            scheduledStartTime=scheduled_start_time,
            maxSpeedLimit=speed_limit if speed_limit > 0 else self.global_speed_limit,
            totalBytes=initial_total_bytes,
            selectedServer=selected_server,
            selectedQuality=selected_quality,
            source=source,
            version=version,
            animeUrl=anime_url,
            exportStatus=ExportStatus.PENDING if platform_events.completed_handler is not None else ExportStatus.NOT_REQUESTED,
        )

        task.requestHeaders = dict(cached.headers) if cached else {}
        library_service.save_task(task)
        self.tasks[task.id] = task
        self.task_order.append(task.id)

        if task.status == DownloadStatus.PENDING:
            self._trigger_process_queue()

        self.broadcast_update(task)
        return task

    def start_batch_download(self, anime_name: str, episodes: List[Dict[str, Any]], source: str = "french-manga") -> List[DownloadTask]:
        # Validate the whole batch before allocating paths or queue entries.
        profiles = [snapshot(ep.get("outputProfile"), legacy_subtitles=str(ep.get("downloadSubtitles", "false")).lower() == "true") for ep in episodes]
        for profile in profiles:
            require_available(profile)
        started = []
        new_tasks = []

        clean_anime = self.sanitize_file_name(anime_name)
        if self.plex_organization:
            anime_dir = Path(self.download_dir) / clean_anime / "Season 01"
        else:
            anime_dir = Path(self.download_dir) / clean_anime
        anime_dir.mkdir(parents=True, exist_ok=True)

        for ep, profile_json in zip(episodes, profiles):
            ep_num = int(ep.get("number", 0))
            url = ep.get("url", "")
            if not url:
                continue
            ep_source = ep.get("source") or source
            version = ep.get("version") or ""
            if self._active_episode_task(url, ep_source, version):
                continue
            name = self._versioned_filename(ep.get("fileName", f"{anime_name} - Episode {ep_num}.mp4"), version)
            sub_url = ep.get("subtitleUrl")
            dl_subs = require_available(profile_json).mode != "ORIGINAL"
            sel_server = ep.get("selectedServer")
            sel_quality = ep.get("selectedQuality")

            # Check duplicate
            existing = self.check_existing_file(anime_name, name, ep_num, version)
            if existing and existing.exists() and existing.stat().st_size > 1024 * 1024:
                verif = verification_service.verify_file(str(existing), anime_name, name)
                if verif.valid:
                    logger.info("Batch: %s Ep%d already exists and is valid (%s), skipping",
                                anime_name, ep_num, format_bytes(existing.stat().st_size))
                    library_service.mark_as_downloaded(ep.get("animeUrl") or url, anime_name, ep_num, version)
                    continue

            if existing:
                cache_key = f"{url}::{ep_source}::{sel_server or self.voiranime_default_server}::{sel_quality or ''}"
                cached = self.resolved_info_cache.get(cache_key)
                if not cached and not (sel_server or sel_quality):
                    cached = self.resolved_info_cache.get(url)
                if cached and cached.size > 0 and existing.stat().st_size == cached.size:
                    logger.info("Batch: %s Ep%d already exists with the same size, skipping", anime_name, ep_num)
                    continue

            sched_time = None
            if ep.get("scheduledTime"):
                try:
                    sched_time = datetime.fromisoformat(ep["scheduledTime"])
                except Exception:
                    pass

            speed_limit = 0
            if ep.get("speedLimit"):
                try:
                    speed_limit = int(ep["speedLimit"])
                except Exception:
                    pass

            cache_key = f"{url}::{ep_source}::{sel_server or self.voiranime_default_server}::{sel_quality or ''}"
            cached = self.resolved_info_cache.get(cache_key)
            if not cached and not (sel_server or sel_quality):
                cached = self.resolved_info_cache.get(url)
            initial_total_bytes = cached.size if cached and cached.size > 0 else 0
            resolved_subs = cached.subtitles_json if cached else "[]"

            sched_time = ensure_utc(sched_time)
            now = datetime.now(timezone.utc)
            is_scheduled = sched_time is not None and sched_time > now
            status = DownloadStatus.SCHEDULED if is_scheduled else DownloadStatus.PENDING

            if self.plex_organization:
                ext = Path(name).suffix or ".mp4"
                final_file_name = f"{clean_anime} - S01E{ep_num:02d}{self._version_suffix(version)}{ext}"
            else:
                final_file_name = self.sanitize_file_name(name)

            save_path = str(anime_dir / final_file_name)

            task = DownloadTask(
                animeName=anime_name,
                episodeNumber=ep_num,
                fileName=final_file_name,
                fileUrl=url,
                savePath=save_path,
                downloadPageUrl=url,
                subtitleUrl=sub_url,
                subtitlesJson=resolved_subs,
                mediaJson=cached.media_json if cached else "{}",
                outputProfileJson=profile_json,
                downloadSubtitles=dl_subs,
                status=status,
                scheduledStartTime=sched_time,
                maxSpeedLimit=speed_limit if speed_limit > 0 else self.global_speed_limit,
                totalBytes=initial_total_bytes,
                selectedServer=sel_server,
                selectedQuality=sel_quality,
                source=ep_source,
                version=version,
                animeUrl=ep.get("animeUrl") or "",
                exportStatus=ExportStatus.PENDING if platform_events.completed_handler is not None else ExportStatus.NOT_REQUESTED,
            )

            task.requestHeaders = dict(cached.headers) if cached else {}
            self.tasks[task.id] = task
            self.task_order.append(task.id)
            new_tasks.append(task)
            started.append(task)

        if new_tasks:
            library_service.save_tasks_batch(new_tasks)
            for task in new_tasks:
                self.broadcast_update(task)
            self._trigger_process_queue()

        return started

    # -------------------------------------------------------------------------
    # Contrôle de la file et des tâches
    # -------------------------------------------------------------------------

    def get_all_tasks(self) -> List[DownloadTask]:
        ordered = []
        for tid in self.task_order:
            t = self.tasks.get(tid)
            if t:
                ordered.append(t)
        return ordered

    def get_task(self, task_id: str) -> Optional[DownloadTask]:
        if task_id in self.tasks:
            return self.tasks[task_id]
        entity = library_service.get_task_entity(task_id)
        return entity.to_task() if entity else None

    async def output_inventory(self, task_id: str):
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        if self._export_in_progress(task_id) or task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.MUXING, DownloadStatus.RETRYING, DownloadStatus.PENDING):
            raise ValueError('Attendez la fin ou mettez le téléchargement en pause avant de choisir les pistes')
        async with self.media_pipeline.inventory_budget:
            tracks, data = await asyncio.to_thread(self.media_pipeline.output_processor.inventory, task)
            from animelab.services.output_profiles import available_profiles
            profiles = await asyncio.to_thread(available_profiles)
        return dict(tracks=[track.public() for track in tracks], outputProfile=json.loads(task.outputProfileJson),
                    profiles=profiles, duration=data.get('format', {}).get('duration'),
                    warnings=self.media_pipeline.output_processor.state(task).get('warnings', []))

    async def reprocess_output(self, task_id: str, value):
        import copy
        if task_id in getattr(self, '_subtitle_mutations', set()):
            raise ValueError('Attendez la fin de l’import de sous-titres')
        task = self.get_task(task_id)
        if task is None:
            raise KeyError(task_id)
        profile_json = snapshot(value)
        profile = require_available(profile_json)
        if profile.mode == 'ORIGINAL':
            raise ValueError('Choisissez un format de traitement ; le master original reste conservé')
        await self.output_inventory(task_id)
        async with self.media_pipeline.inventory_budget:
            inventory, _ = await asyncio.to_thread(self.media_pipeline.output_processor.inventory, task)
        proposed = copy.copy(task)
        proposed.outputProfileJson = profile_json
        self.media_pipeline.output_processor.select(proposed, inventory)
        if task_id in getattr(self, '_subtitle_mutations', set()):
            raise ValueError('Attendez la fin de l’import de sous-titres')
        task = self.tasks.get(task_id) or task
        if self._export_in_progress(task_id) or task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.MUXING, DownloadStatus.RETRYING, DownloadStatus.PENDING):
            raise ValueError('Un traitement est déjà en cours pour cette tâche')
        state = self.media_pipeline.output_processor.state(task)
        master = state.get('master') or task.savePath
        if not master or not is_safe_path(master, [self.download_dir]) or not Path(master).is_file():
            raise ValueError('Master local introuvable')
        task.outputProfileJson = profile_json
        task.savePath = master
        task.fileName = Path(state.get('source') or master).name
        task.totalBytes = task.downloadedBytes = Path(master).stat().st_size
        task.downloadSubtitles = True
        task.paused = task.cancelled = False
        task.error = None
        task.progress = 100
        task.exportStatus = ExportStatus.PENDING if platform_events.completed_handler else ExportStatus.NOT_REQUESTED
        task.exportUrisJson = '[]'
        task.exportError = None
        task.exportedAt = None
        task.completedAt = None
        task.verificationStatus = 'UNVERIFIED'
        task.verifiedAt = None
        transition(task, DownloadStatus.PENDING)
        library_service.save_task(task)
        self.tasks[task.id] = task
        if task.id not in self.task_order:
            self.task_order.append(task.id)
        self.broadcast_update(task)
        self._trigger_process_queue()
        return task

    def pause_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        if t and t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.RETRYING, DownloadStatus.SCHEDULED, DownloadStatus.MUXING]:
            t.paused = True
            transition(t, DownloadStatus.PAUSED)
            t.speed = 0
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        return False

    def resume_verified_domain(self, domain: str) -> int:
        if os.getenv('ANIMELAB_SHARED_WORKER') == '1' and os.getenv('ANIMELAB_SHARED_DOWNLOAD') != '1':
            return 0
        ids = [task.id for task in self.tasks.values()
               if task.status == DownloadStatus.VERIFICATION_REQUIRED
               and urlparse(task.verificationUrl or "").hostname == domain]
        return sum(self.resume_download(task_id) for task_id in ids)

    def resume_download(self, task_id: str) -> bool:
        if task_id in getattr(self, '_subtitle_mutations', set()):
            return False
        if self._export_in_progress(task_id):
            return False
        t = self.tasks.get(task_id)
        if not t:
            entity = library_service.get_task_entity(task_id)
            if entity:
                t = entity.to_task()
                self.tasks[t.id] = t
                if t.id not in self.task_order:
                    self.task_order.append(t.id)

        if t and t.status == DownloadStatus.VERIFICATION_REQUIRED:
            if not t.verificationUrl or source_http.state(t.verificationUrl).blocked_url:
                return False
            t.verificationUrl = None
            transition(t, DownloadStatus.PAUSED)
        if t and self._has_destination_conflict(t):
            self._pause_destination_conflict(t)
            return False
        if t and t.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED, DownloadStatus.CANCELLED, DownloadStatus.COMPLETED]:
            t.paused = False
            t.cancelled = False
            t.error = None
            t.retryCount = 0
            t.directDownloadUrl = None  # Forcer la re-résolution pour obtenir un token CDN frais

            # Détecter le fichier partiel existant (.part ou savePath) pour reprise
            if t.savePath:
                part_path = Path(t.savePath + ".part")
                out_path = Path(t.savePath)
                if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                    verif = verification_service.verify_file(str(out_path), t.animeName, t.fileName)
                    if verif.valid and not self._has_pending_subtitles(t):
                        transition(t, DownloadStatus.COMPLETED)
                        t.progress = 100.0
                        t.downloadedBytes = out_path.stat().st_size
                        t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                        t.verificationStatus = verif.status
                        t.videoDuration = verif.duration
                        self.broadcast_update(t)
                        library_service.save_task(t)
                        library_service.mark_as_downloaded(t.animeUrl or t.downloadPageUrl or "", t.animeName, t.episodeNumber, t.version)
                        return True

                if part_path.exists() and part_path.stat().st_size > 0:
                    if t.totalBytes > 0 and part_path.stat().st_size > t.totalBytes:
                        logger.warning(".part file (%d bytes) larger than totalBytes (%d) for %s, deleting",
                                       part_path.stat().st_size, t.totalBytes, t.fileName)
                        part_path.unlink(missing_ok=True)
                        t.downloadedBytes = 0
                    else:
                        t.downloadedBytes = part_path.stat().st_size
                elif out_path.exists() and out_path.stat().st_size > 0:
                    try:
                        with open(out_path, "rb") as f_chk:
                            head = f_chk.read(100).lower()
                            if b"<html" not in head and b"<!doctype" not in head:
                                t.downloadedBytes = out_path.stat().st_size
                    except Exception:
                        pass

                if t.totalBytes > 0 and t.downloadedBytes > 0:
                    t.progress = min(99.9, (t.downloadedBytes / t.totalBytes) * 100.0)
                elif t.downloadedBytes == 0:
                    t.progress = 0.0
                logger.info("Resume detected for %s: %s already downloaded",
                            t.fileName, format_bytes(t.downloadedBytes))

            transition(t, DownloadStatus.PENDING)
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        return False

    def cancel_download(self, task_id: str) -> bool:
        t = self.tasks.get(task_id)
        cancellable_statuses = [
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PENDING,
            DownloadStatus.RETRYING,
            DownloadStatus.SCHEDULED,
            DownloadStatus.PAUSED,
            DownloadStatus.VERIFICATION_REQUIRED,
            DownloadStatus.MUXING,
        ]
        if t and t.status in cancellable_statuses:
            t.cancelled = True
            t.paused = False
            transition(t, DownloadStatus.CANCELLED)
            t.speed = 0
            proc = getattr(t, "activeProcess", None)
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
            self.broadcast_update(t)
            library_service.save_task(t)
            self._trigger_process_queue()
            return True
        elif not t:
            entity = library_service.get_task_entity(task_id)
            if entity and entity.status in [s.value for s in cancellable_statuses]:
                task = entity.to_task()
                task.cancelled = True
                task.paused = False
                transition(task, DownloadStatus.CANCELLED)
                task.speed = 0
                library_service.save_task(task)
                return True
        return False

    def cancel_all_downloads(self) -> int:
        count = 0
        active_statuses = [
            DownloadStatus.DOWNLOADING,
            DownloadStatus.PENDING,
            DownloadStatus.RETRYING,
            DownloadStatus.SCHEDULED,
            DownloadStatus.PAUSED,
            DownloadStatus.VERIFICATION_REQUIRED,
            DownloadStatus.MUXING
        ]
        cancelled_tasks = []
        for t in self.tasks.values():
            if t.status in active_statuses:
                t.cancelled = True
                t.paused = False
                transition(t, DownloadStatus.CANCELLED)
                t.speed = 0
                proc = getattr(t, "activeProcess", None)
                if proc:
                    try:
                        proc.terminate()
                    except Exception:
                        pass
                self.broadcast_update(t)
                cancelled_tasks.append(t)
                count += 1
        if cancelled_tasks:
            library_service.save_tasks_batch(cancelled_tasks)
            self._trigger_process_queue()
        logger.info("Global cancellation: %d download(s) cancelled", count)
        return count

    def _export_in_progress(self, task_id: str) -> bool:
        task = self.tasks.get(task_id)
        lock = self._finalization_locks.get(task_id)
        if lock is not None and lock.locked():
            return True
        media = self._media_jobs.get(task_id)
        if media is not None and not media.done():
            return True
        native = self._native_exports.get(task_id)
        return bool((task and task.exportStatus == ExportStatus.EXPORTING)
                    or (native is not None and not native.done()))

    def remove_task(self, task_id: str) -> bool:
        if task_id in getattr(self, '_subtitle_mutations', set()):
            raise ValueError('Attendez la fin de l’import de sous-titres')
        if self._export_in_progress(task_id):
            raise ValueError("Wait for the current export before removing this download")
        t = self.tasks.pop(task_id, None) or self.get_task(task_id)
        if task_id in self.task_order:
            self.task_order.remove(task_id)
        if t:
            t._removed = True
            t.cancelled = True
            proc = getattr(t, "activeProcess", None)
            if proc:
                try:
                    proc.terminate()
                except Exception:
                    pass
            if t.savePath:
                out_p = Path(t.savePath)
                Path(t.savePath + ".part").unlink(missing_ok=True)
                Path(t.savePath + ".part.resume.json").unlink(missing_ok=True)
                out_p.with_suffix(".tmp.mp4").unlink(missing_ok=True)
                seg_d = out_p.parent / f".{out_p.stem}_segments"
                if seg_d.exists():
                    shutil.rmtree(seg_d, ignore_errors=True)
        deleted_from_db = library_service.delete_task_entity(task_id)
        if t:
            worker = self.scheduler.workers.get(task_id)
            def cleanup_media(_=None):
                media_job = self.media_pipeline.jobs.get(task_id)
                if media_job and not media_job.done():
                    media_job.add_done_callback(cleanup_media)
                    return
                try:
                    self.media_pipeline.output_processor.cleanup(t)
                except OSError:
                    logger.warning('Unable to clean private media workspace for %s', task_id)
            if worker and not worker.done():
                worker.add_done_callback(cleanup_media)
            else:
                cleanup_media()
        self._trigger_process_queue()
        return (t is not None) or deleted_from_db

    def pause_all_downloads(self):
        for exporting in list(self.tasks.values()):
            if exporting.exportStatus == ExportStatus.EXPORTING:
                exporting.paused = True
                self.broadcast_update(exporting)
        for t in self.tasks.values():
            if t.status in [DownloadStatus.DOWNLOADING, DownloadStatus.PENDING, DownloadStatus.RETRYING, DownloadStatus.SCHEDULED, DownloadStatus.MUXING]:
                t.paused = True
                transition(t, DownloadStatus.PAUSED)
                t.speed = 0
                self.broadcast_update(t)
                library_service.save_task(t)
        self._trigger_process_queue()

    def resume_all_downloads(self):
        try:
            for entity in library_service.get_unfinished_tasks():
                if entity.id not in self.tasks:
                    task = entity.to_task()
                    self.tasks[task.id] = task
                    if task.id not in self.task_order:
                        self.task_order.append(task.id)
        except Exception as e:
            logger.warning("Error reloading DB tasks for resume: %s", e)

        for t in list(self.tasks.values()):
            if self._has_destination_conflict(t):
                self._pause_destination_conflict(t)
                continue
            if t.status in [DownloadStatus.PAUSED, DownloadStatus.FAILED]:
                t.paused = False
                t.cancelled = False
                t.retryCount = 0
                t.error = None
                t.directDownloadUrl = None

                if t.savePath:
                    out_path = Path(t.savePath)
                    part_path = Path(t.savePath + ".part")
                    if out_path.exists() and out_path.stat().st_size > 1024 * 1024:
                        verif = verification_service.verify_file(str(out_path), t.animeName, t.fileName)
                        if verif.valid and not self._has_pending_subtitles(t):
                            transition(t, DownloadStatus.COMPLETED)
                            t.progress = 100.0
                            t.downloadedBytes = out_path.stat().st_size
                            t.totalBytes = max(t.totalBytes, out_path.stat().st_size)
                            t.verificationStatus = verif.status
                            t.videoDuration = verif.duration
                            self.broadcast_update(t)
                            library_service.save_task(t)
                            library_service.mark_as_downloaded(t.animeUrl or t.downloadPageUrl or "", t.animeName, t.episodeNumber, t.version)
                            continue
                    elif part_path.exists() and part_path.stat().st_size > 0:
                        if t.totalBytes > 0 and part_path.stat().st_size > t.totalBytes:
                            part_path.unlink(missing_ok=True)
                            t.downloadedBytes = 0
                        else:
                            t.downloadedBytes = part_path.stat().st_size
                        if t.totalBytes > 0 and t.downloadedBytes > 0:
                            t.progress = min(99.9, (t.downloadedBytes / t.totalBytes) * 100.0)

                transition(t, DownloadStatus.PENDING)
                self.broadcast_update(t)
                library_service.save_task(t)
        self._trigger_process_queue()

    def clear_inactive_tasks(self):
        inactive = [DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]
        for tid in list(self.tasks.keys()):
            task = self.tasks[tid]
            protected = self._export_in_progress(tid) or (task.status == DownloadStatus.COMPLETED
                and task.exportStatus in (ExportStatus.PENDING, ExportStatus.EXPORT_FAILED))
            if task.status in inactive and not protected:
                self.remove_task(tid)

    def clear_history_tasks(self, status: Optional[str] = None, anime_name: Optional[str] = None):
        target_statuses = None
        if status:
            target_statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
        for tid in list(self.tasks.keys()):
            t = self.tasks.get(tid)
            if not t:
                continue
            if self._export_in_progress(tid) or (t.status == DownloadStatus.COMPLETED
                    and t.exportStatus in (ExportStatus.PENDING, ExportStatus.EXPORT_FAILED)):
                continue
            if anime_name and t.animeName.lower() != anime_name.lower():
                continue
            if target_statuses:
                if t.status.value.upper() in target_statuses or t.status.name.upper() in target_statuses:
                    self.remove_task(tid)
            else:
                if t.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED]:
                    self.remove_task(tid)

    def move_task_to_top(self, task_id: str):
        return self.scheduler.move_task_to_top(task_id)

    def move_series_to_top(self, anime_name: str):
        return self.scheduler.move_series_to_top(anime_name)

    def reorder_tasks(self, ordered_ids: List[str]):
        return self.scheduler.reorder_tasks(ordered_ids)

    # -------------------------------------------------------------------------
    # Vérification d'intégrité & Re-téléchargement
    # -------------------------------------------------------------------------

    def _apply_verification(self, task: DownloadTask, verif: VerificationResult) -> None:
        if verif.relocatedPath and verif.relocatedPath != task.savePath:
            task.savePath = verif.relocatedPath

        task.verificationStatus = verif.status
        task.verifiedAt = datetime.now(timezone.utc)
        task.videoDuration = verif.duration
        task.verificationError = verif.error

        library_service.save_task(task)
        if task.id in self.tasks:
            self.tasks[task.id] = task
            self.broadcast_update(task)

    def verify_task(self, task_id: str) -> Optional[VerificationResult]:
        task = self.get_task(task_id)
        if not task:
            return None

        verif = verification_service.verify_file(
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes
        )
        self._apply_verification(task, verif)
        return verif

    async def verify_task_async(self, task_id: str) -> Optional[VerificationResult]:
        """Variante non bloquante : ffprobe/ffmpeg tournent dans un thread."""
        task = self.get_task(task_id)
        if not task:
            return None

        verif = await asyncio.to_thread(
            verification_service.verify_file,
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes,
        )
        # Mutations d'état et broadcast SSE (asyncio.Queue) : uniquement dans la boucle
        self._apply_verification(task, verif)
        return verif

    def _collect_completed_tasks(self) -> Dict[str, DownloadTask]:
        completed_tasks: Dict[str, DownloadTask] = {}

        # 1. Tâches en mémoire
        for t in self.tasks.values():
            if t.status in [DownloadStatus.COMPLETED, DownloadStatus.FAILED]:
                completed_tasks[t.id] = t

        # 2. Tâches dans l'historique
        for entity in library_service.get_history():
            if entity.id not in completed_tasks and entity.status in [DownloadStatus.COMPLETED.value, DownloadStatus.FAILED.value]:
                completed_tasks[entity.id] = entity.to_task()
        return completed_tasks

    @staticmethod
    def _summarize_verifications(pairs: List[Tuple[DownloadTask, VerificationResult]]) -> Dict[str, Any]:
        valid_count = missing_count = empty_count = incomplete_count = corrupted_count = 0
        results_list = []

        for task, verif in pairs:
            if verif.valid:
                valid_count += 1
            elif verif.status == "MISSING":
                missing_count += 1
            elif verif.status == "EMPTY":
                empty_count += 1
            elif verif.status == "INCOMPLETE":
                incomplete_count += 1
            else:
                corrupted_count += 1

            results_list.append({
                "taskId": task.id,
                "animeName": task.animeName,
                "episodeNumber": task.episodeNumber,
                "fileName": task.fileName,
                "status": verif.status,
                "valid": verif.valid,
                "duration": verif.duration,
                "formattedDuration": verif.formattedDuration,
                "formattedSize": verif.formattedSize,
                "expectedSize": verif.expectedSize,
                "sizeRatio": verif.sizeRatio,
                "error": verif.error,
            })

        return {
            "total": len(pairs),
            "valid": valid_count,
            "missing": missing_count,
            "empty": empty_count,
            "incomplete": incomplete_count,
            "corrupted": corrupted_count,
            "results": results_list,
        }

    def verify_all_completed(self) -> Dict[str, Any]:
        """Vérifie l'intégrité de l'ensemble des téléchargements terminés."""
        pairs: List[Tuple[DownloadTask, VerificationResult]] = []
        for task in self._collect_completed_tasks().values():
            verif = verification_service.verify_file(
                file_path_str=task.savePath,
                anime_name=task.animeName,
                file_name=task.fileName,
                expected_size=task.totalBytes
            )
            self._apply_verification(task, verif)
            pairs.append((task, verif))
        return self._summarize_verifications(pairs)

    async def verify_all_completed_async(self) -> Dict[str, Any]:
        """Variante non bloquante de verify_all_completed (ffprobe/ffmpeg dans des threads)."""
        tasks = await asyncio.to_thread(self._collect_completed_tasks)
        pairs: List[Tuple[DownloadTask, VerificationResult]] = []
        for task in tasks.values():
            verif = await asyncio.to_thread(
                verification_service.verify_file,
                file_path_str=task.savePath,
                anime_name=task.animeName,
                file_name=task.fileName,
                expected_size=task.totalBytes,
            )
            self._apply_verification(task, verif)
            pairs.append((task, verif))
        return self._summarize_verifications(pairs)

    def redownload_task(self, task_id: str, force: bool = False) -> Optional[DownloadTask]:
        """Relance un téléchargement en reprenant si possible ou en nettoyant si corrompu."""
        if task_id in getattr(self, '_subtitle_mutations', set()):
            raise ValueError('Attendez la fin de l’import de sous-titres')
        task = self.get_task(task_id)
        if not task:
            return None
        if self._export_in_progress(task_id):
            raise ValueError("Wait for the current export before downloading the file again")

        # Vérifier si un fichier partiel sain existe sur le disque
        has_healthy_part = False
        if not force and task.savePath:
            part_p = Path(task.savePath + ".part")
            out_p = Path(task.savePath)

            # Si le statut de vérification est explicitement corrompu, ne pas reprendre
            if task.verificationStatus in ["CORRUPTED", "INVALID"]:
                logger.warning("File marked as %s for %s, mandatory purge for fresh start",
                               task.verificationStatus, task.fileName)
                has_healthy_part = False
            else:
                target = part_p if part_p.exists() else (out_p if out_p.exists() else None)
                if target and target.stat().st_size > 1024:
                    if task.totalBytes > 0 and target.stat().st_size > task.totalBytes:
                        logger.warning("Partial file %s (%s) larger than totalBytes (%s), purge required",
                                       target.name, format_bytes(target.stat().st_size), format_bytes(task.totalBytes))
                        has_healthy_part = False
                    else:
                        try:
                            with open(target, "rb") as f_chk:
                                head = f_chk.read(100).lower()
                                if b"<html" not in head and b"<!doctype" not in head:
                                    has_healthy_part = True
                        except Exception:
                            pass

        # Si un fichier partiel sain existe et qu'on ne force pas le reset complet : reprise !
        if has_healthy_part:
            logger.info("Healthy partial file detected for %s, switching to resume_download", task.fileName)
            self.resume_download(task_id)
            return self.get_task(task_id)

        # Sinon, purger tout fichier corrompu ou vide sur le disque
        output_state = self.media_pipeline.output_processor.state(task)
        if output_state:
            # Fresh video transfer must never recover a receipt/master belonging
            # to the previous representation. Keep already published outputs.
            self.media_pipeline.output_processor.cleanup(task, keep_imports=True)
            task.savePath = output_state.get('source') or task.savePath
            task.fileName = Path(task.savePath).name if task.savePath else task.fileName
            media = json.loads(task.mediaJson)
            media.pop('outputState', None)
            task.mediaJson = json.dumps(media)
            task.savePathSubtitle = None
        if task.savePath:
            try:
                p = Path(task.savePath)
                if p.exists() and p.is_file():
                    p.unlink()
                part_p = Path(task.savePath + ".part")
                if part_p.exists() and part_p.is_file():
                    part_p.unlink()
                Path(task.savePath + ".part.resume.json").unlink(missing_ok=True)
            except Exception as e:
                logger.warning("Unable to delete corrupted file %s: %s", task.savePath, e)

        # Réinitialiser la tâche pour un nouveau téléchargement complet
        task.progress = 0.0
        task.downloadedBytes = 0
        task.totalBytes = 0
        task.speed = 0
        task.error = None
        task.cancelled = False
        task.paused = False
        task.directDownloadUrl = None  # Forcer la re-résolution de l'URL
        transition(task, DownloadStatus.PENDING)
        task.verificationStatus = "UNVERIFIED"
        task.verificationError = None
        task.completedAt = None
        task.exportStatus = ExportStatus.PENDING if platform_events.completed_handler is not None else ExportStatus.NOT_REQUESTED
        task.exportError = task.exportDestination = task.exportedAt = None
        task.exportUrisJson = "[]"

        self.tasks[task.id] = task
        if task.id not in self.task_order:
            self.task_order.append(task.id)

        library_service.save_task(task)
        self.broadcast_update(task)
        self._trigger_process_queue()
        logger.info("Task restarted for full redownload: %s", task.fileName)
        return task

    # -------------------------------------------------------------------------
    # Traitement de la file d'attente (process_queue)
    # -------------------------------------------------------------------------

    async def process_queue(self):
        return await self.scheduler.process_queue()

    # -------------------------------------------------------------------------
    # Exécution du téléchargement
    # -------------------------------------------------------------------------

    async def _execute_download(self, task: DownloadTask):
        return await self.transfer_worker._execute_download(task)

    async def _download_single_file(self, task: DownloadTask, direct_url: str):
        return await self.transfer_worker._download_single_file(task, direct_url)

    async def _download_mytv_chunks(self, task: DownloadTask, chunks: List[str]):
        return await self.transfer_worker._download_mytv_chunks(task, chunks)

    async def _download_hls_stream(self, task: DownloadTask, m3u8_url: str):
        return await self.transfer_worker._download_hls_stream(task, m3u8_url)

    async def _download_hls_segments_native(self, task: DownloadTask, m3u8_url: str):
        return await self.transfer_worker._download_hls_segments_native(task, m3u8_url)

    async def _apply_throttle(self, task: DownloadTask, bytes_read: int):
        return await self.transfer_worker._apply_throttle(task, bytes_read)

    async def export_task(self, task: DownloadTask, *, manual=False):
        return await self.export_coordinator.export_task(task, manual=manual)

    async def _finalize_task(self, task: DownloadTask, verification=None):
        return await self.media_pipeline._finalize_task(task, verification)

    async def _finalize_task_locked(self, task: DownloadTask, verification=None):
        return await self.media_pipeline._finalize_task_locked(task, verification)

    # -------------------------------------------------------------------------
    # Sous-titres & FFmpeg
    # -------------------------------------------------------------------------

    def _update_resolved_subtitles(self, task: DownloadTask, value, base_url: str):
        return self.media_pipeline._update_resolved_subtitles(task, value, base_url)

    def _recover_muxed_file(self, task: DownloadTask) -> bool:
        return self.media_pipeline._recover_muxed_file(task)

    def _has_pending_subtitles(self, task: DownloadTask) -> bool:
        return self.media_pipeline._has_pending_subtitles(task)

    async def _download_subtitles(self, task: DownloadTask):
        return await self.media_pipeline._download_subtitles(task)

    def is_ffmpeg_available(self) -> bool:
        return self.media_pipeline.is_ffmpeg_available()

    def _mux_subtitles_with_ffmpeg(self, task: DownloadTask):
        return self.media_pipeline._mux_subtitles_with_ffmpeg(task)

    def _publish_mux_file(self, staging: Path, video_path: Path, output_path: Path, task_id: str) -> Path:
        return self.media_pipeline._publish_mux_file(staging, video_path, output_path, task_id)

    # -------------------------------------------------------------------------
    # Plex / Jellyfin NFO
    # -------------------------------------------------------------------------

    def _generate_nfo_files(self, task: DownloadTask):
        return self.media_pipeline._generate_nfo_files(task)

    # -------------------------------------------------------------------------
    # SSE Broadcast
    # -------------------------------------------------------------------------

    def subscribe_sse(self) -> asyncio.Queue:
        q = asyncio.Queue()
        self.sse_subscribers.append(q)
        # Send initial snapshot
        for t in self.get_all_tasks():
            q.put_nowait(t.to_dict())
        return q

    def unsubscribe_sse(self, q: asyncio.Queue):
        if q in self.sse_subscribers:
            self.sse_subscribers.remove(q)

    def broadcast_update(self, task: DownloadTask):
        from animelab.diagnostics import telemetry
        telemetry.task_phase(task)
        try:
            platform_events.progress(task)
        except Exception:
            logger.exception("Native download notification update failed")
        data = task.to_dict()
        for q in list(self.sse_subscribers):
            try:
                q.put_nowait(data)
            except Exception:
                if q in self.sse_subscribers:
                    self.sse_subscribers.remove(q)

    # -------------------------------------------------------------------------
    # Ticker / Scheduled Downloads
    # -------------------------------------------------------------------------

    async def check_scheduled_tasks(self):
        return await self.scheduler.check_scheduled_tasks()

    # -------------------------------------------------------------------------
    # Helpers
    # -------------------------------------------------------------------------

    def sanitize_file_name(self, name: str) -> str:
        if not name:
            return "download"
        clean = name.replace("\0", "")
        clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean)
        clean = re.sub(r"\.{2,}", "_", clean)
        clean = re.sub(r"\s+", " ", clean).strip(" .")
        return clean or "download"

    def _needs_scraping_resolution(self, url: str) -> bool:
        if not url:
            return False
        if re.search(r"\.(mp4|mkv|avi|webm|m3u8)(\?.*)?$", url):
            return False
        if extractor_registry.is_known_embed(url):
            return False
        if "vidzy.live" in url or "luluvdo.com" in url or "french-manga.net" in url:
            return True
        if "vidzy.cc" in url and any(x in url for x in ["/e/", "/d/", "embed-"]):
            return True
        return not bool(re.search(r"\.(mp4|mkv|avi|webm|ts|m4v|m3u8)(\?.*)?$", url))

download_manager = DownloadManagerService()
