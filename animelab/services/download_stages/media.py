"""MediaPipeline: extracted stage with a compatibility coordinator context."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animelab.services.download_manager import DownloadManagerService

from animelab.services.download_stages.state import transition
from animelab.services.source_http import VerificationRequired, RateLimited
import asyncio
import errno
import json
import logging
import os
import shutil
import subprocess
from animelab import media_tools, platform_events
import tempfile
import xml.sax.saxutils as saxutils
from datetime import datetime, timezone
from collections import Counter
from pathlib import Path

import httpx

from animelab.config import settings
from animelab.models.download_task import DownloadTask, DownloadStatus, ExportStatus
from animelab.services.library_service import library_service
from animelab.services.verification_service import verification_service
from animelab.services.subtitle_service import normalize_subtitles, subtitle_extension, subtitle_language
from animelab.services.download_errors import SubtitleError
from animelab.services.download_resume import valid_cached_segment, publish_file
from animelab.security import is_safe_path, is_safe_url

logger = logging.getLogger("animelab.download.media")

from animelab.services.download_stages.budget import StageBudget

class MediaPipeline:
    def __init__(self, manager: DownloadManagerService):
        self.manager = manager
        self.locks = {}
        self.jobs = {}
        self.budget = StageBudget(settings.MAX_MEDIA_WORKERS)

    async def _finalize_task(self, task: DownloadTask, verification=None):
        ctx = self.manager
        native = ctx._media_jobs.get(task.id)
        if native is not None and not native.done():
            raise ValueError("Media finalization is still in progress")
        lock = ctx._finalization_locks.setdefault(task.id, asyncio.Lock())
        if lock.locked():
            raise ValueError("Media finalization is already in progress")
        try:
            async with lock:
                await ctx._finalize_task_locked(task, verification)
        except asyncio.CancelledError:
            task.paused = True
            if task.status != DownloadStatus.COMPLETED:
                transition(task, DownloadStatus.PAUSED)
            library_service.save_task(task)
            ctx.broadcast_update(task)
            raise
        finally:
            ctx._finalization_locks.pop(task.id, None)


    async def _prepare(self, task: DownloadTask, verification=None):
        ctx = self.manager
        if task.cancelled or task.paused:
            task.status = DownloadStatus.CANCELLED if task.cancelled else DownloadStatus.PAUSED
            library_service.save_task(task)
            ctx.broadcast_update(task)
            return
        task.progress = 100.0
        task.speed = 0

        # Muxing FFmpeg si sous-titres présents
        if task.savePathSubtitle and ctx.is_ffmpeg_available():
            verification = None  # A newly muxed output needs its own integrity check.
            transition(task, DownloadStatus.MUXING)
            task.phase = "muxing"
            ctx.broadcast_update(task)
            library_service.save_task(task)
            try:
                await self.budget.run(task, self.jobs, ctx._mux_subtitles_with_ffmpeg, task)
            except Exception as exc:
                transition(task, DownloadStatus.FAILED)
                task.error = f"Échec de fusion des sous-titres : {exc}"
                ctx.broadcast_update(task)
                library_service.save_task(task)
                return

        if task.cancelled or task.paused:
            task.status = DownloadStatus.CANCELLED if task.cancelled else DownloadStatus.PAUSED
            library_service.save_task(task)
            ctx.broadcast_update(task)
            return

        task.phase = "verifying"
        ctx.broadcast_update(task)

        # Vérification d'intégrité automatique du fichier téléchargé
        verif = verification or await self.budget.run(
            task, self.jobs, verification_service.verify_file,
            file_path_str=task.savePath,
            anime_name=task.animeName,
            file_name=task.fileName,
            expected_size=task.totalBytes
        )

        if verif.relocatedPath and verif.relocatedPath != task.savePath:
            task.savePath = verif.relocatedPath

        task.verificationStatus = verif.status
        task.verifiedAt = datetime.now(timezone.utc)
        task.videoDuration = verif.duration
        task.verificationError = verif.error

        return verif


    async def _finalize_task_locked(self, task: DownloadTask, verification=None):
        ctx = self.manager
        ctx.scheduler.release_network(task.id)
        verif = await self._prepare(task, verification)
        if verif is None:
            return
        if task.paused or task.cancelled:
            transition(task, DownloadStatus.CANCELLED if task.cancelled else DownloadStatus.PAUSED)
            library_service.save_task(task)
            ctx.broadcast_update(task)
            return
        if verif.valid:
            task.error = None
            # A verified private file is complete even if publication is paused,
            # denied or interrupted. EXPORTING keeps Android's service alive.
            transition(task, DownloadStatus.COMPLETED)
            task.progress = 100.0
            task.completedAt = datetime.now(timezone.utc)
            library_service.save_task(task)
            if platform_events.completed_handler is not None and task.exportStatus != ExportStatus.EXPORTED:
                try:
                    await ctx.export_task(task)
                except Exception as exc:
                    logger.exception("Completed media could not be exported by the native platform")
            transition(task, DownloadStatus.COMPLETED)
            task.phase = None
            task.progress = 100.0
            task.completedAt = datetime.now(timezone.utc)
            part_path = Path(task.savePath + ".part")
            if part_path.exists():
                part_path.unlink(missing_ok=True)
            ctx.broadcast_update(task)
            library_service.save_task(task)

            logger.info("Download completed and verified: %s (%s, duration: %s)", task.fileName, task.formattedTotalSize, verif.formattedDuration)

            if ctx.plex_organization:
                await asyncio.to_thread(ctx._generate_nfo_files, task)
        else:
            transition(task, DownloadStatus.FAILED)
            task.error = f"Integrity verification failed: {verif.error}"
            ctx.broadcast_update(task)
            library_service.save_task(task)
            logger.error("Download failed after verification for %s: %s", task.fileName, verif.error)


    def _update_resolved_subtitles(self, task: DownloadTask, value, base_url: str):
        ctx = self.manager
        tracks = normalize_subtitles(value, base_url)
        # A failed/empty re-extraction must not erase known pending subtitles.
        if not tracks:
            return
        previous = {track["url"]: track for track in normalize_subtitles(task.subtitlesJson)}
        for track in tracks:
            cached = previous.get(track["url"], {})
            for key in ("path", "muxed"):
                if key in cached:
                    track[key] = cached[key]
        task.subtitlesJson = json.dumps(tracks)


    def _recover_muxed_file(self, task: DownloadTask) -> bool:
        """Recover a legacy task whose MP4 was removed after a successful MKV export.

        Only the exact sibling destination is considered, and every requested track
        must be present with its title and language. Never adopt an arbitrary MKV.
        """
        ctx = self.manager
        if not task.savePath or Path(task.savePath).exists():
            return False
        candidate = Path(task.savePath).with_suffix(".mkv")
        if not candidate.is_file() or not media_tools.which("ffprobe"):
            return False
        try:
            tracks = normalize_subtitles(task.subtitlesJson)
            if task.downloadSubtitles and not tracks:
                return False
            result = verification_service.verify_file(str(candidate), expected_size=task.totalBytes or None)
            if not result.valid:
                return False
            probe = media_tools.run([media_tools.which("ffprobe"), "-v", "error", "-show_streams",
                                    "-of", "json", str(candidate)], capture_output=True,
                                   text=True, check=True, timeout=30)
            present = Counter((stream.get("tags", {}).get("title", ""),
                               stream.get("tags", {}).get("language", "und"))
                              for stream in json.loads(probe.stdout).get("streams", [])
                              if stream.get("codec_type") == "subtitle")
            expected = Counter((track["label"], subtitle_language(track.get("lang"))) for track in tracks)
            if task.downloadSubtitles and any(present[key] < count for key, count in expected.items()):
                return False
            for track in tracks:
                track["muxed"] = True
            task.subtitlesJson = json.dumps(tracks)
            task.savePathSubtitle = None
            task.savePath = str(candidate)
            task.fileName = candidate.name
            task.totalBytes = task.downloadedBytes = candidate.stat().st_size
            library_service.save_task(task)
            return True
        except (OSError, ValueError, subprocess.SubprocessError):
            logger.warning("Unable to recover existing mux for %s", task.fileName, exc_info=True)
            return False


    def _has_pending_subtitles(self, task: DownloadTask) -> bool:
        ctx = self.manager
        if not task.downloadSubtitles:
            return False
        if task.savePathSubtitle:
            return True
        try:
            tracks = normalize_subtitles(task.subtitlesJson)
        except (ValueError, TypeError):
            return True
        return not tracks or any(not track.get("muxed") for track in tracks)


    async def _download_subtitles(self, task: DownloadTask):
        ctx = self.manager
        base_url = task.downloadPageUrl or task.fileUrl or task.directDownloadUrl or ""
        try:
            subs = normalize_subtitles(task.subtitlesJson, base_url)
        except (ValueError, TypeError) as exc:
            raise SubtitleError(f"Métadonnées de sous-titres invalides : {exc}") from exc
        if not subs and task.subtitleUrl:
            subs = normalize_subtitles([{"url": task.subtitleUrl}], base_url)
        pending = [(index, sub) for index, sub in enumerate(subs) if not sub.get("muxed")]
        if not pending:
            return

        task.phase = "subtitles"
        task.reset_speed()
        ctx.broadcast_update(task)
        downloaded_paths = []
        errors = []
        refresh_required = False
        parent = Path(task.savePath).parent

        async def validate_request(request):
            if not is_safe_url(str(request.url)):
                raise ValueError("URL de sous-titres non autorisée")

        headers = ctx.get_headers_for_url(base_url, task.selectedServer)
        if base_url:
            headers["Referer"] = base_url
        try:
            async with ctx._create_async_client(headers=headers, timeout=30.0) as client:
                client.event_hooks.setdefault("request", []).append(validate_request)
                for index, sub in pending:
                    if task.cancelled or task.paused:
                        return
                    url, label = sub["url"], sub["label"]
                    try:
                        # A completed sidecar survives retries, including an expired CDN URL.
                        cached = Path(sub["path"]) if sub.get("path") else None
                        if cached and is_safe_path(cached, [parent]) and cached.is_file():
                            if 0 < cached.stat().st_size <= 10 * 1024 * 1024:
                                try:
                                    subtitle_extension(cached.read_bytes())
                                    downloaded_paths.append(str(cached))
                                    continue
                                except ValueError:
                                    pass
                        if not is_safe_url(url):
                            raise ValueError("URL de sous-titres non autorisée")
                        request_headers = dict(sub.get("headers") or {})
                        if sub.get("referer"):
                            request_headers["Referer"] = sub["referer"]
                        for attempt in range(3):
                            if task.cancelled or task.paused:
                                return
                            try:
                                resp = await client.get(url, headers=request_headers)
                                resp.raise_for_status()
                                break
                            except (httpx.TimeoutException, httpx.TransportError, httpx.HTTPStatusError) as exc:
                                transient = (not hasattr(exc, "kind") and
                                    (not isinstance(exc, httpx.HTTPStatusError) or exc.response.status_code in (408, 500, 502, 503, 504)))
                                if (isinstance(exc, httpx.HTTPStatusError) and hasattr(client, "service")
                                        and exc.response.status_code in (502, 503, 504)):
                                    transient = False  # The common transport already retried these.
                                if not transient or attempt == 2:
                                    raise
                                await asyncio.sleep(2 ** attempt)
                        if not resp.content or len(resp.content) > 10 * 1024 * 1024:
                            raise ValueError("Sous-titres vides ou trop volumineux")
                        ext = subtitle_extension(resp.content)
                        clean_label = ctx.sanitize_file_name(str(label)) or "Sous-titres"
                        sub_name = f"{Path(task.savePath).stem}.sub{index + 1}.{clean_label}{ext}"
                        sub_path = parent / sub_name
                        if not is_safe_path(sub_path, [parent]):
                            raise ValueError("Chemin de sous-titres non autorisé")
                        parent.mkdir(parents=True, exist_ok=True)
                        staging = None
                        try:
                            with tempfile.NamedTemporaryFile(dir=parent, prefix=".animan-sub-", delete=False) as temp:
                                staging = Path(temp.name)
                                temp.write(resp.content)
                            staging.replace(sub_path)
                        finally:
                            if staging:
                                staging.unlink(missing_ok=True)
                        sub["path"] = str(sub_path)
                        downloaded_paths.append(str(sub_path))
                        logger.info("Subtitles downloaded: %s", sub_name)
                    except (VerificationRequired, RateLimited):
                        raise
                    except Exception as exc:
                        if isinstance(exc, httpx.TimeoutException):
                            reason = "Délai réseau dépassé après 3 tentatives"
                        elif isinstance(exc, httpx.HTTPStatusError):
                            reason = f"HTTP {exc.response.status_code}"
                            refresh_required = refresh_required or exc.response.status_code in (401, 403, 404, 410)
                        else:
                            reason = str(exc).strip() or type(exc).__name__
                        errors.append(f"{label}: {reason}")
                        logger.warning("Error downloading subtitles %s: %s", label, reason)
        finally:
            # Persist partial success even when a later track requires verification.
            task.subtitlesJson = json.dumps(subs)
            task.savePathSubtitle = json.dumps(downloaded_paths) if downloaded_paths else None
            library_service.save_task(task)
        if errors:
            raise SubtitleError("Échec du téléchargement des sous-titres : " + "; ".join(errors), refresh_required)


    def is_ffmpeg_available(self) -> bool:
        ctx = self.manager
        return media_tools.which("ffmpeg") is not None


    def _mux_subtitles_with_ffmpeg(self, task: DownloadTask):
        ctx = self.manager
        if not ctx.is_ffmpeg_available():
            raise RuntimeError("FFmpeg indisponible")
        video_path = Path(task.savePath)
        if not video_path.is_file():
            raise ValueError("Vidéo introuvable")

        try:
            sub_paths = json.loads(task.savePathSubtitle or "[]")
        except (ValueError, TypeError):
            sub_paths = [task.savePathSubtitle]
        if not isinstance(sub_paths, list):
            sub_paths = [sub_paths]
        existing_subs = [Path(sp) for sp in sub_paths if sp and
                         is_safe_path(Path(sp), [video_path.parent]) and Path(sp).is_file()]
        if not existing_subs or len(existing_subs) != len(sub_paths):
            raise ValueError("Fichier de sous-titres introuvable")
        metadata = {s.get("path"): s for s in normalize_subtitles(task.subtitlesJson)}

        original = verification_service.verify_file(str(video_path), expected_size=task.totalBytes)
        if not original.valid:
            raise ValueError(f"Vidéo source invalide : {original.error}")
        probe_path = media_tools.which("ffprobe")
        if not probe_path:
            raise RuntimeError("FFprobe requis pour valider les pistes fusionnées")

        def probe(path):
            result = media_tools.run([probe_path, "-v", "error", "-show_streams", "-of", "json", str(path)],
                                    capture_output=True, text=True, check=True, timeout=30)
            return json.loads(result.stdout).get("streams", [])

        embedded = [s for s in probe(video_path) if s.get("codec_type") == "subtitle"]
        output_path = video_path.with_suffix(".mkv")
        with tempfile.NamedTemporaryFile(dir=video_path.parent, prefix=".animan-mux-", suffix=".mkv", delete=False) as temp:
            staging = Path(temp.name)
        try:
            cmd = ["ffmpeg", "-v", "error", "-y", "-i", str(video_path)]
            for sf in existing_subs:
                cmd.extend(["-i", str(sf)])
            cmd.extend(["-map", "0:v", "-map", "0:a?", "-map", "0:s?",
                        "-c:v", "copy", "-c:a", "copy", "-c:s", "copy"])
            for index, stream in enumerate(embedded):
                if stream.get("codec_name") == "mov_text":
                    cmd.extend([f"-c:s:{index}", "srt"])
            for index, sf in enumerate(existing_subs):
                cmd.extend(["-map", f"{index + 1}:s:0"])
                stream_index = len(embedded) + index
                if sf.suffix.lower() == ".vtt":
                    cmd.extend([f"-c:s:{stream_index}", "srt"])
                track = metadata.get(str(sf), {})
                title = track.get("label") or sf.stem
                lang = subtitle_language(track.get("lang") or track.get("srclang"))
                cmd.extend([f"-metadata:s:s:{stream_index}", f"language={lang}",
                            f"-metadata:s:s:{stream_index}", f"title={title}"])
            cmd.append(str(staging))
            result = media_tools.run(cmd, capture_output=True, text=True, timeout=300)
            if result.returncode:
                raise RuntimeError(result.stderr.strip()[-1000:] or "FFmpeg a échoué")
            verification = verification_service.verify_file(str(staging))
            if not verification.valid:
                raise ValueError(f"Vidéo fusionnée invalide : {verification.error}")
            subtitles = [s for s in probe(staging) if s.get("codec_type") == "subtitle"]
            if len(subtitles) != len(embedded) + len(existing_subs):
                raise ValueError("Pistes de sous-titres manquantes après fusion")
            if task.cancelled or task.paused:
                return
            output_path = ctx._publish_mux_file(staging, video_path, output_path, task.id)
            task.fileName = output_path.name
            task.savePath = str(output_path)
            task.totalBytes = task.downloadedBytes = output_path.stat().st_size
            task.savePathSubtitle = None
            tracks = normalize_subtitles(task.subtitlesJson)
            for track in tracks:
                if track.get("path") in sub_paths:
                    track["muxed"] = True
            task.subtitlesJson = json.dumps(tracks)
            library_service.save_task(task)
            for obsolete in ([video_path] if video_path != output_path else []) + existing_subs:
                try:
                    obsolete.unlink(missing_ok=True)
                except OSError:
                    logger.warning("Export completed; unable to remove %s", obsolete.name, exc_info=True)
            logger.info("FFmpeg muxing succeeded: %s", output_path.name)
        finally:
            staging.unlink(missing_ok=True)


    def _publish_mux_file(self, staging: Path, video_path: Path, output_path: Path, task_id: str) -> Path:
        ctx = self.manager
        if output_path == video_path:
            staging.replace(output_path)
            return output_path
        # Preserve unrelated episodes, including a destination created during mux.
        for collision in range(1000):
            candidate = output_path if collision == 0 else output_path.with_name(
                f"{output_path.stem}.subtitled-{ctx.sanitize_file_name(task_id)[:12]}-{collision}.mkv")
            try:
                if not media_tools.is_native():
                    try:
                        os.link(staging, candidate)
                        return candidate
                    except OSError as exc:
                        if exc.errno not in (errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP):
                            raise
                # Android/FAT may reject hard links despite allowing ordinary
                # writes. Reserve exclusively and replace only our placeholder.
                fd = os.open(candidate, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
                os.close(fd)
                try:
                    staging.replace(candidate)
                except BaseException:
                    candidate.unlink(missing_ok=True)
                    raise
                return candidate
            except FileExistsError:
                continue
        raise FileExistsError("Impossible de réserver un nom de fichier pour la fusion")


    def _generate_nfo_files(self, task: DownloadTask):
        ctx = self.manager
        try:
            video_file = Path(task.savePath)
            season_dir = video_file.parent
            anime_dir = season_dir.parent

            tvshow_nfo = anime_dir / "tvshow.nfo"
            if not tvshow_nfo.exists():
                synopsis = ""
                studio = ""
                genres = []

                # Favoris ou recherche pour métadonnées
                fav = next((f for f in library_service.get_all_favorites() if f.title.lower() == task.animeName.lower()), None)
                if fav:
                    pass

                content = (
                    '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
                    '<tvshow>\n'
                    f'    <title>{saxutils.escape(task.animeName)}</title>\n'
                    f'    <plot>{saxutils.escape(synopsis)}</plot>\n'
                    f'    <studio>{saxutils.escape(studio)}</studio>\n'
                )
                for g in genres:
                    content += f'    <genre>{saxutils.escape(g)}</genre>\n'
                content += '</tvshow>\n'

                with open(tvshow_nfo, "w", encoding="utf-8") as f:
                    f.write(content)

            ep_nfo = season_dir / f"{video_file.stem}.nfo"
            ep_content = (
                '<?xml version="1.0" encoding="UTF-8" standalone="yes" ?>\n'
                '<episodedetails>\n'
                f'    <title>{saxutils.escape(f"Épisode {task.episodeNumber}")}</title>\n'
                f'    <episode>{task.episodeNumber}</episode>\n'
                '    <season>1</season>\n'
                f'    <plot>{saxutils.escape(f"{task.animeName} - Épisode {task.episodeNumber}")}</plot>\n'
                '</episodedetails>\n'
            )
            with open(ep_nfo, "w", encoding="utf-8") as f:
                f.write(ep_content)
        except Exception as e:
            logger.error("Error generating NFO: %s", e)


    async def assemble_hls(self, task, output_path, segments_dir, total_segments):
        task.phase = 'assembling'
        self.manager.broadcast_update(task)
        return await self.budget.run(task, self.jobs, self._assemble_hls,
                                     task, output_path, segments_dir, total_segments)

    def _assemble_hls(self, task, output_path, segments_dir, total_segments):
        ctx = self.manager
        # FFmpeg's concat demuxer resolves segment names relative to its list.
        # JNI has no per-command working directory: never change process cwd.
        output_path = Path(output_path).resolve()
        segments_dir = Path(segments_dir).resolve()
        task.phase = "assembling"
        task.reset_speed()

        # Assemblage final sans perte des segments HLS
        logger.info("Assembling %d HLS segments to %s", total_segments, task.fileName)
        temp_output = output_path.with_suffix(".tmp.mp4")
        if temp_output.exists():
            temp_output.unlink(missing_ok=True)

        concat_file = segments_dir / "concat_list.txt"
        with open(concat_file, "w", encoding="utf-8") as f_concat:
            for idx in range(total_segments):
                sf = segments_dir / f"seg_{idx:05d}.ts"
                f_concat.write(f"file '{sf.name}'\n")

        merged = False
        if ctx.is_ffmpeg_available() and task.fileName.endswith(".mp4"):
            remux_cmd = [
                "ffmpeg", "-v", "error", "-y",
                "-f", "concat",
                "-safe", "0",
                "-i", str(concat_file),
                "-c", "copy",
                "-bsf:a", "aac_adtstoasc",
                str(temp_output)
            ]
            result = media_tools.run(remux_cmd, capture_output=True, timeout=300)
            r_rc = result.returncode
            if r_rc and media_tools.is_native():
                raise RuntimeError("Android HLS remux failed: " + result.stderr[-1000:])
            if r_rc == 0 and temp_output.exists() and temp_output.stat().st_size > 0:
                merged = True

        if not merged:
            # Fallback concaténation binaire directe
            with open(temp_output, "wb") as outfile:
                for idx in range(total_segments):
                    sf = segments_dir / f"seg_{idx:05d}.ts"
                    if not valid_cached_segment(sf):
                        raise ConnectionError(f"HLS segment {idx} is missing or corrupted during assembly")
                    with open(sf, "rb") as infile:
                        shutil.copyfileobj(infile, outfile, length=65536)
                outfile.flush()
                os.fsync(outfile.fileno())
        if task.cancelled or task.paused:
            temp_output.unlink(missing_ok=True)
            return
        # Publish only after the full assembly succeeded. On failure the cache
        # remains available and an existing final file is left untouched.
        if output_path.exists():
            raise FileExistsError("A final media file appeared during HLS assembly")
        publish_file(temp_output, output_path)

        # Nettoyage sécurisé du dossier temporaire de segments une fois l'assemblage validé
        shutil.rmtree(segments_dir, ignore_errors=True)

        final_size = output_path.stat().st_size
        task.downloadedBytes = final_size
        task.totalBytes = final_size
        task.progress = 100.0
        task.reset_speed()

        return True

    async def assemble_chunks(self, task, parts):
        task.phase = 'assembling'
        self.manager.broadcast_update(task)
        return await self.budget.run(task, self.jobs, self._assemble_chunks, task, parts)

    def _assemble_chunks(self, task, parts):
        destination = Path(task.savePath)
        staging = destination.with_name(destination.name + '.assembling')
        try:
            with staging.open('wb') as output:
                for part in parts:
                    if task.paused or task.cancelled:
                        return False
                    with part.open('rb') as source:
                        shutil.copyfileobj(source, output, length=65536)
                output.flush()
                os.fsync(output.fileno())
            if task.paused or task.cancelled:
                return False
            publish_file(staging, destination)
            for part in parts:
                part.unlink(missing_ok=True)
            task.downloadedBytes = task.totalBytes = destination.stat().st_size
            return True
        finally:
            staging.unlink(missing_ok=True)
