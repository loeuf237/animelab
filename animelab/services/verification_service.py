import json
import logging
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional
from pydantic import BaseModel

from animelab.config import settings
from animelab import media_tools
from animelab.models.download_task import format_bytes

logger = logging.getLogger("animelab.verification")

def format_duration(seconds: Optional[float]) -> str:
    if seconds is None or seconds <= 0:
        return ""
    total_sec = int(round(seconds))
    hrs = total_sec // 3600
    mins = (total_sec % 3600) // 60
    secs = total_sec % 60
    if hrs > 0:
        return f"{hrs}h {mins:02d}m {secs:02d}s"
    elif mins > 0:
        return f"{mins}m {secs:02d}s"
    else:
        return f"{secs}s"

class VerificationResult(BaseModel):
    valid: bool
    status: str  # "VALID", "MISSING", "EMPTY", "CORRUPTED", "INCOMPLETE", "ERROR"
    duration: Optional[float] = None
    formattedDuration: str = ""
    fileSize: int = 0
    formattedSize: str = "0 B"
    expectedSize: Optional[int] = None
    sizeRatio: Optional[float] = None
    hasVideo: bool = False
    hasAudio: bool = False
    formatName: str = ""
    error: Optional[str] = None
    verifiedAt: Optional[str] = None
    filePath: Optional[str] = None
    relocatedPath: Optional[str] = None

class DownloadVerificationService:
    def __init__(self):
        self._ffprobe_path = media_tools.which("ffprobe")
        if self._ffprobe_path:
            logger.info("Verification service initialized with ffprobe (%s)", self._ffprobe_path)
        else:
            logger.warning("ffprobe not detected on the system. Headers verification mode enabled.")

    @property
    def is_ffprobe_available(self) -> bool:
        return self._ffprobe_path is not None

    def verify_file(
        self,
        file_path_str: Optional[str],
        anime_name: Optional[str] = None,
        file_name: Optional[str] = None,
        expected_size: Optional[int] = None
    ) -> VerificationResult:
        now_iso = datetime.now(timezone.utc).isoformat()

        if not file_path_str:
            return VerificationResult(
                valid=False,
                status="MISSING",
                error="Chemin de fichier non spécifié",
                verifiedAt=now_iso,
            )

        path = Path(file_path_str)
        relocated_path: Optional[str] = None

        # 1. Vérification de présence du fichier
        if not path.exists() or not path.is_file():
            # Tentative d'auto-localisation dans les répertoires standards
            found = self._try_relocate_file(file_path_str, anime_name, file_name)
            if found:
                path = found
                relocated_path = str(found)
                logger.info("File successfully relocated: %s -> %s", file_path_str, relocated_path)
            else:
                return VerificationResult(
                    valid=False,
                    status="MISSING",
                    filePath=file_path_str,
                    error="Fichier introuvable sur le disque (déplacé ou supprimé)",
                    verifiedAt=now_iso,
                )

        # 2. Vérification de la taille (détection des fichiers 0 octet)
        try:
            file_size = path.stat().st_size
        except Exception as e:
            return VerificationResult(
                valid=False,
                status="ERROR",
                filePath=str(path),
                error=f"Impossible d'accéder aux métadonnées du fichier: {e}",
                verifiedAt=now_iso,
            )

        if file_size == 0:
            return VerificationResult(
                valid=False,
                status="EMPTY",
                fileSize=0,
                formattedSize="0 B",
                filePath=str(path),
                relocatedPath=relocated_path,
                error="Le fichier fait 0 octet (téléchargement vide ou avorté)",
                verifiedAt=now_iso,
            )

        # 2b. Vérification taille minimale (fichier suspect si < 1 KB)
        if file_size < 1024:
            return VerificationResult(
                valid=False,
                status="CORRUPTED",
                fileSize=file_size,
                formattedSize=format_bytes(file_size),
                filePath=str(path),
                relocatedPath=relocated_path,
                error=f"Fichier trop petit ({format_bytes(file_size)}) — probablement corrompu ou incomplet",
                verifiedAt=now_iso,
            )

        # 2c. Détection immédiate si le contenu est une page HTML d'erreur
        try:
            with open(path, "rb") as f_chk:
                header_sample = f_chk.read(512).lower()
                if b"<html" in header_sample or b"<!doctype" in header_sample or b"<head" in header_sample:
                    return VerificationResult(
                        valid=False,
                        status="CORRUPTED",
                        fileSize=file_size,
                        formattedSize=format_bytes(file_size),
                        filePath=str(path),
                        relocatedPath=relocated_path,
                        error="Le fichier est une page web HTML d'erreur et non une vidéo",
                        verifiedAt=now_iso,
                    )
        except Exception:
            pass

        # 2c. Vérification du ratio taille attendue/réelle
        size_ratio: Optional[float] = None
        if expected_size and expected_size > 0:
            size_ratio = file_size / expected_size
            if size_ratio < 0.9:
                return VerificationResult(
                    valid=False,
                    status="INCOMPLETE",
                    fileSize=file_size,
                    formattedSize=format_bytes(file_size),
                    expectedSize=expected_size,
                    sizeRatio=round(size_ratio, 3),
                    filePath=str(path),
                    relocatedPath=relocated_path,
                    error=f"Fichier incomplet : {format_bytes(file_size)} / {format_bytes(expected_size)} ({size_ratio:.0%})",
                    verifiedAt=now_iso,
                )

        # 3. Contrôle d'intégrité approfondi avec ffprobe
        if self.is_ffprobe_available:
            try:
                cmd = [
                    self._ffprobe_path,
                    "-v", "error",
                    "-protocol_whitelist", "file,pipe",
                    "-show_entries", "format=duration,size,format_name:stream=codec_type,codec_name",
                    "-of", "json",
                    str(path)
                ]
                proc = media_tools.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=30,
                    check=False
                )

                if proc.returncode != 0:
                    err_lines = [l.strip() for l in proc.stderr.splitlines() if l.strip()]
                    err_summary = err_lines[-1] if err_lines else "Video container decode error"
                    logger.warning("ffprobe validation failed for %s: %s", path.name, err_summary)
                    return VerificationResult(
                        valid=False,
                        status="CORRUPTED",
                        fileSize=file_size,
                        formattedSize=format_bytes(file_size),
                        filePath=str(path),
                        relocatedPath=relocated_path,
                        error=f"Fichier vidéo corrompu : {err_summary}",
                        verifiedAt=now_iso,
                    )

                data = json.loads(proc.stdout)
                format_info = data.get("format", {})
                streams = data.get("streams", [])

                has_video = any(s.get("codec_type") == "video" for s in streams)
                has_audio = any(s.get("codec_type") == "audio" for s in streams)

                if not has_video:
                    return VerificationResult(
                        valid=False,
                        status="CORRUPTED",
                        fileSize=file_size,
                        formattedSize=format_bytes(file_size),
                        filePath=str(path),
                        relocatedPath=relocated_path,
                        error="Aucun flux vidéo détecté dans le conteneur",
                        verifiedAt=now_iso,
                    )

                dur_str = format_info.get("duration")
                duration = float(dur_str) if dur_str else None
                format_name = format_info.get("format_name", "")

                # 3b. Contrôle rapide de décodage effectif avec ffmpeg pour détecter les paquets corrompus
                ffmpeg_path = media_tools.which("ffmpeg")
                if ffmpeg_path and duration and duration > 30:
                    check_points = [min(60.0, duration * 0.1), duration * 0.5, duration * 0.85]
                    for check_pos in check_points:
                        test_cmd = [
                            ffmpeg_path,
                            "-v", "error",
                            "-ss", str(int(check_pos)),
                            "-i", str(path),
                            "-t", "4", "-map", "0:v:0", "-map", "0:a?", "-sn", "-dn",
                            "-fps_mode", "passthrough", "-enc_time_base", "-1",
                            "-f", "null", "-"
                        ]
                        try:
                            test_proc = media_tools.run(test_cmd, capture_output=True, text=True, timeout=10)
                            # The null output may round Matroska timestamps and report DTS
                            # collisions. These output diagnostics are not decoder errors.
                            err_lines = [line.strip() for line in test_proc.stderr.splitlines()
                                         if line.strip() and not ("[null @" in line and
                                             "non monotonically increasing dts" in line)]
                            if test_proc.returncode != 0 or err_lines:
                                logger.warning("Corrupted video file during decoding at %ds for %s: %d errors detected",
                                               int(check_pos), path.name, len(err_lines))
                                return VerificationResult(
                                    valid=False,
                                    status="CORRUPTED",
                                    fileSize=file_size,
                                    formattedSize=format_bytes(file_size),
                                    filePath=str(path),
                                    relocatedPath=relocated_path,
                                    error=f"Erreur de décodage à {int(check_pos)}s : " + (err_lines[-1][-500:] if err_lines else f"FFmpeg code {test_proc.returncode}"),
                                    verifiedAt=now_iso,
                                )
                        except Exception as dec_err:
                            return VerificationResult(
                                valid=False, status="ERROR", fileSize=file_size,
                                filePath=str(path), relocatedPath=relocated_path,
                                error="Contrôle de décodage non terminé : " + (str(dec_err).strip() or type(dec_err).__name__),
                                verifiedAt=now_iso,
                            )

                return VerificationResult(
                    valid=True,
                    status="VALID",
                    duration=duration,
                    formattedDuration=format_duration(duration),
                    fileSize=file_size,
                    formattedSize=format_bytes(file_size),
                    expectedSize=expected_size if expected_size and expected_size > 0 else None,
                    sizeRatio=round(size_ratio, 3) if size_ratio is not None else None,
                    hasVideo=has_video,
                    hasAudio=has_audio,
                    formatName=format_name,
                    filePath=str(path),
                    relocatedPath=relocated_path,
                    verifiedAt=now_iso,
                )

            except subprocess.TimeoutExpired:
                logger.error("Timeout expired for ffprobe on %s", path.name)
                return VerificationResult(
                    valid=False,
                    status="ERROR",
                    fileSize=file_size,
                    formattedSize=format_bytes(file_size),
                    filePath=str(path),
                    relocatedPath=relocated_path,
                    error="Délai dépassé lors de l'analyse vidéo ffprobe",
                    verifiedAt=now_iso,
                )
            except Exception as e:
                logger.error("Exception during ffprobe check of %s: %s", path.name, e)
                return VerificationResult(
                    valid=False, status="ERROR", fileSize=file_size, filePath=str(path),
                    relocatedPath=relocated_path, verifiedAt=now_iso,
                    error="Analyse ffprobe impossible : " + (str(e).strip() or type(e).__name__),
                )

        # 4. Fallback sans ffprobe : vérification des signatures (magic numbers)
        try:
            with open(path, "rb") as f:
                header = f.read(128)
            is_mp4 = b"ftyp" in header or b"moov" in header
            is_mkv = header.startswith(b"\x1a\x45\xdf\xa3")

            if is_mp4 or is_mkv:
                return VerificationResult(
                    valid=True,
                    status="VALID",
                    fileSize=file_size,
                    formattedSize=format_bytes(file_size),
                    filePath=str(path),
                    relocatedPath=relocated_path,
                    formatName="mp4" if is_mp4 else "matroska",
                    verifiedAt=now_iso,
                )
            else:
                return VerificationResult(
                    valid=False,
                    status="CORRUPTED",
                    fileSize=file_size,
                    formattedSize=format_bytes(file_size),
                    filePath=str(path),
                    relocatedPath=relocated_path,
                    error="En-tête de conteneur non reconnu (ni MP4 ni MKV)",
                    verifiedAt=now_iso,
                )
        except Exception as e:
            return VerificationResult(
                valid=False,
                status="ERROR",
                fileSize=file_size,
                formattedSize=format_bytes(file_size),
                filePath=str(path),
                relocatedPath=relocated_path,
                error=f"Erreur lecture fichier : {e}",
                verifiedAt=now_iso,
            )

    def _try_relocate_file(
        self,
        original_path_str: str,
        anime_name: Optional[str],
        file_name: Optional[str]
    ) -> Optional[Path]:
        """Tente de retrouver un fichier déplacé dans le dossier de téléchargement."""
        orig = Path(original_path_str)
        fname = file_name or orig.name
        base_dir = Path(settings.DOWNLOAD_DIR)

        candidates = [
            orig,
            base_dir / fname,
        ]
        if anime_name:
            candidates.append(base_dir / anime_name / fname)
            candidates.append(base_dir / anime_name / "Season 01" / fname)

        for c in candidates:
            if c.exists() and c.is_file():
                return c

        return None

verification_service = DownloadVerificationService()
