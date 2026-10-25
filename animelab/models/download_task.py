import collections
import json
import time
import uuid
from datetime import datetime, timezone
from enum import Enum
from typing import Optional, Deque, Tuple
from urllib.parse import urlparse
from sqlalchemy import Column, Integer, BigInteger, Float, String, Boolean, DateTime
from animelab.database import Base

def ensure_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Normalise une date en UTC aware.

    Une date naïve fournie par un client est interprétée comme heure locale ;
    SQLite ne conservant pas le fuseau, les dates relues depuis la base sont
    rattachées à UTC explicitement dans ``DownloadTaskEntity.to_task``.
    """
    if dt is None:
        return None
    return dt.astimezone(timezone.utc)


def _db_utc(dt: Optional[datetime]) -> Optional[datetime]:
    """Rattache UTC à une date naïve relue depuis SQLite (stockée en UTC)."""
    if dt is not None and dt.tzinfo is None:
        return dt.replace(tzinfo=timezone.utc)
    return dt


class SpeedTracker:
    """
    Gestionnaire de lissage du débit réseau via fenêtre glissante (Rolling Window).
    Élimine les à-coups, les faux 0 B/s et les disparitions d'ETA lors des téléchargements
    par segments (HLS / ffmpeg / streaming direct).
    """
    def __init__(self, window_seconds: float = 15.0):
        self.window_seconds = window_seconds
        self.samples: Deque[Tuple[float, int]] = collections.deque()  # (timestamp, downloaded_bytes)
        self.last_speed: int = 0

    def reset(self):
        self.samples.clear()
        self.last_speed = 0

    def add_sample(self, current_bytes: int, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self.samples.append((now, current_bytes))
        self._prune(now)
        return self._calc_speed(now)

    def _prune(self, now: float):
        cutoff = now - self.window_seconds
        while len(self.samples) > 2 and self.samples[1][0] < cutoff:
            self.samples.popleft()

    def get_speed(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self._prune(now)
        return self._calc_speed(now)

    def _calc_speed(self, now: float) -> int:
        if len(self.samples) < 2:
            return self.last_speed

        t_first, b_first = self.samples[0]
        t_last, b_last = self.samples[-1]
        dt = t_last - t_first

        # Si aucun nouvel octet n'est reçu depuis plus de window_seconds, décroître à 0
        if now - t_last > self.window_seconds:
            self.last_speed = 0
            return 0

        if dt < 0.2:
            return self.last_speed

        db = b_last - b_first
        if db <= 0:
            if now - t_first >= 2.0:
                self.last_speed = 0
                return 0
            return self.last_speed

        calculated = int(db / dt)
        self.last_speed = calculated
        return calculated

class DownloadStatus(str, Enum):
    PENDING = "PENDING"
    SCHEDULED = "SCHEDULED"
    DOWNLOADING = "DOWNLOADING"
    RETRYING = "RETRYING"
    PAUSED = "PAUSED"
    VERIFICATION_REQUIRED = "VERIFICATION_REQUIRED"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    CANCELLED = "CANCELLED"
    MUXING = "MUXING"


class ExportStatus(str, Enum):
    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    EXPORTING = "EXPORTING"
    EXPORTED = "EXPORTED"
    EXPORT_FAILED = "EXPORT_FAILED"

def format_bytes(b: int) -> str:
    if b <= 0:
        return "0 B"
    units = ["B", "KB", "MB", "GB", "TB"]
    unit_index = 0
    size = float(b)
    while size >= 1024.0 and unit_index < len(units) - 1:
        size /= 1024.0
        unit_index += 1
    return f"{size:.1f} {units[unit_index]}"

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

class DownloadTaskEntity(Base):
    __tablename__ = "download_tasks"

    id = Column(String(36), primary_key=True, default=lambda: str(uuid.uuid4()))
    animeName = Column(String, nullable=False)
    episodeNumber = Column(Integer, default=0)
    version = Column(String, default="")
    animeUrl = Column(String, default="")
    fileName = Column(String, nullable=False)
    fileUrl = Column(String, nullable=True)
    savePath = Column(String, nullable=True)
    savePathSubtitle = Column(String, nullable=True)
    downloadPageUrl = Column(String, nullable=True)
    directDownloadUrl = Column(String, nullable=True)
    subtitleUrl = Column(String, nullable=True)
    subtitlesJson = Column(String, default="[]")
    error = Column(String, nullable=True)
    verificationUrl = Column(String, nullable=True)
    status = Column(String, default=DownloadStatus.PENDING.value, nullable=False)
    progress = Column(Float, default=0.0)
    downloadedBytes = Column(BigInteger, default=0)
    totalBytes = Column(BigInteger, default=0)
    maxSpeedLimit = Column(BigInteger, default=0)
    retryCount = Column(Integer, default=0)
    downloadSubtitles = Column(Boolean, default=False)
    scheduledStartTime = Column(DateTime, nullable=True)
    createdAt = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    completedAt = Column(DateTime, nullable=True)
    source = Column(String, default="french-manga")
    verificationStatus = Column(String, default="UNVERIFIED", nullable=False)
    videoDuration = Column(Float, nullable=True)
    verifiedAt = Column(DateTime, nullable=True)
    verificationError = Column(String, nullable=True)
    selectedServer = Column(String, nullable=True)
    selectedQuality = Column(String, nullable=True)
    exportStatus = Column(String, default=ExportStatus.NOT_REQUESTED.value, nullable=False)
    exportUrisJson = Column(String, default="[]", nullable=False)
    exportDestination = Column(String, nullable=True)
    exportError = Column(String, nullable=True)
    exportAttempts = Column(Integer, default=0, nullable=False)
    exportedAt = Column(DateTime, nullable=True)

    def to_task(self) -> "DownloadTask":
        return DownloadTask(
            id=self.id,
            animeName=self.animeName,
            episodeNumber=self.episodeNumber,
            version=self.version,
            animeUrl=self.animeUrl,
            fileName=self.fileName,
            fileUrl=self.fileUrl or "",
            savePath=self.savePath,
            savePathSubtitle=self.savePathSubtitle,
            downloadPageUrl=self.downloadPageUrl,
            directDownloadUrl=self.directDownloadUrl,
            subtitleUrl=self.subtitleUrl,
            subtitlesJson=self.subtitlesJson or "[]",
            error=self.error,
            verificationUrl=self.verificationUrl,
            status=DownloadStatus(self.status),
            progress=self.progress,
            downloadedBytes=self.downloadedBytes,
            totalBytes=self.totalBytes,
            maxSpeedLimit=self.maxSpeedLimit,
            retryCount=self.retryCount,
            downloadSubtitles=self.downloadSubtitles,
            scheduledStartTime=_db_utc(self.scheduledStartTime),
            createdAt=self.createdAt,
            completedAt=self.completedAt,
            source=self.source,
            verificationStatus=self.verificationStatus or "UNVERIFIED",
            videoDuration=self.videoDuration,
            verifiedAt=self.verifiedAt,
            verificationError=self.verificationError,
            selectedServer=self.selectedServer,
            selectedQuality=self.selectedQuality,
            exportStatus=self.exportStatus or ExportStatus.NOT_REQUESTED.value,
            exportUrisJson=self.exportUrisJson or "[]",
            exportDestination=self.exportDestination,
            exportError=self.exportError,
            exportAttempts=self.exportAttempts or 0,
            exportedAt=_db_utc(self.exportedAt),
        )

class DownloadTask:
    def __init__(
        self,
        id: Optional[str] = None,
        animeName: str = "",
        episodeNumber: int = 0,
        fileName: str = "",
        fileUrl: str = "",
        savePath: Optional[str] = None,
        savePathSubtitle: Optional[str] = None,
        downloadPageUrl: Optional[str] = None,
        directDownloadUrl: Optional[str] = None,
        subtitleUrl: Optional[str] = None,
        subtitlesJson: str = "[]",
        error: Optional[str] = None,
        verificationUrl: Optional[str] = None,
        status: DownloadStatus = DownloadStatus.PENDING,
        progress: float = 0.0,
        downloadedBytes: int = 0,
        totalBytes: int = 0,
        maxSpeedLimit: int = 0,
        retryCount: int = 0,
        downloadSubtitles: bool = False,
        scheduledStartTime: Optional[datetime] = None,
        createdAt: Optional[datetime] = None,
        completedAt: Optional[datetime] = None,
        source: str = "french-manga",
        verificationStatus: str = "UNVERIFIED",
        videoDuration: Optional[float] = None,
        verifiedAt: Optional[datetime] = None,
        verificationError: Optional[str] = None,
        selectedServer: Optional[str] = None,
        selectedQuality: Optional[str] = None,
        version: str = "",
        animeUrl: str = "",
        exportStatus: str = ExportStatus.NOT_REQUESTED.value,
        exportUrisJson: str = "[]",
        exportDestination: Optional[str] = None,
        exportError: Optional[str] = None,
        exportAttempts: int = 0,
        exportedAt: Optional[datetime] = None,
    ):
        self.id = id or str(uuid.uuid4())
        self.animeName = animeName
        self.episodeNumber = episodeNumber
        self.version = version or ""
        self.animeUrl = animeUrl or ""
        self.fileName = fileName
        self.fileUrl = fileUrl
        self.savePath = savePath
        self.savePathSubtitle = savePathSubtitle
        self.downloadPageUrl = downloadPageUrl
        self.directDownloadUrl = directDownloadUrl
        self.subtitleUrl = subtitleUrl
        self.subtitlesJson = subtitlesJson if isinstance(subtitlesJson, str) else json.dumps(subtitlesJson or [])
        self.error = error
        self.verificationUrl = verificationUrl
        self.status = status
        self.progress = progress
        self.downloadedBytes = downloadedBytes
        self.totalBytes = totalBytes
        self.speed: int = 0  # bytes/sec
        self.maxSpeedLimit = maxSpeedLimit
        self.retryCount = retryCount
        self.downloadSubtitles = downloadSubtitles
        self.scheduledStartTime = ensure_utc(scheduledStartTime)
        self.createdAt = createdAt or datetime.now(timezone.utc)
        self.completedAt = completedAt
        self.source = source
        self.verificationStatus = verificationStatus
        self.videoDuration = videoDuration
        self.verifiedAt = verifiedAt
        self.verificationError = verificationError
        self.selectedServer = selectedServer
        self.selectedQuality = selectedQuality
        self.exportStatus = ExportStatus(exportStatus)
        self.exportUrisJson = exportUrisJson or "[]"
        self.exportDestination = exportDestination
        self.exportError = exportError
        self.exportAttempts = exportAttempts
        self.exportedAt = exportedAt

        self.phase: Optional[str] = None

        # Runtime control flags
        self.cancelled: bool = False
        self.paused: bool = False
        self.supportsResume: bool = False
        self.throttleBytesWritten: int = 0
        self.throttleStartTimeMs: float = 0.0
        self.speed_tracker: SpeedTracker = SpeedTracker(window_seconds=15.0)
        self.last_broadcast_time: float = 0.0

    def update_progress(self, downloaded_bytes: int, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self.downloadedBytes = downloaded_bytes
        if self.totalBytes > 0:
            self.progress = min(99.0, (downloaded_bytes / self.totalBytes) * 100.0)
        self.speed = self.speed_tracker.add_sample(downloaded_bytes, now)
        return self.speed

    def refresh_speed(self, now: Optional[float] = None) -> int:
        if now is None:
            now = time.time()
        self.speed = self.speed_tracker.get_speed(now)
        return self.speed

    def reset_speed(self):
        self.speed = 0
        self.speed_tracker.reset()

    @property
    def formattedTotalSize(self) -> str:
        if self.totalBytes <= 0:
            return "Taille inconnue"
        return format_bytes(self.totalBytes)

    @property
    def formattedDownloadedSize(self) -> str:
        return format_bytes(self.downloadedBytes)

    @property
    def formattedSpeed(self) -> str:
        if self.speed <= 0:
            return "0 B/s"
        return f"{format_bytes(self.speed)}/s"

    @property
    def formattedDuration(self) -> str:
        return format_duration(self.videoDuration)

    def to_dict(self) -> dict:
        try:
            export_uris = json.loads(self.exportUrisJson)
            if not isinstance(export_uris, list):
                export_uris = []
        except (TypeError, ValueError):
            export_uris = []
        return {
            "id": self.id,
            "animeName": self.animeName,
            "episodeNumber": self.episodeNumber,
            "version": self.version,
            "animeUrl": self.animeUrl,
            "fileName": self.fileName,
            "status": self.status.value,
            "phase": self.phase,
            "source": self.source,
            "progress": round(self.progress, 1),
            "downloadedBytes": self.downloadedBytes,
            "totalBytes": self.totalBytes,
            "downloadedSize": self.formattedDownloadedSize,
            "totalSize": self.formattedTotalSize,
            "speed": self.formattedSpeed,
            "speedBytes": self.speed,
            "error": self.error,
            "verificationUrl": self.verificationUrl,
            "verificationDomain": urlparse(self.verificationUrl or "").hostname,
            "savePath": self.savePath,
            "scheduledStartTime": self.scheduledStartTime.isoformat() if self.scheduledStartTime else None,
            "downloadPageUrl": self.downloadPageUrl,
            "directDownloadUrl": self.directDownloadUrl,
            "downloadSubtitles": self.downloadSubtitles,
            "maxSpeedLimit": self.maxSpeedLimit,
            "verificationStatus": self.verificationStatus,
            "videoDuration": self.videoDuration,
            "formattedDuration": self.formattedDuration,
            "verifiedAt": self.verifiedAt.isoformat() if self.verifiedAt else None,
            "verificationError": self.verificationError,
            "selectedServer": self.selectedServer,
            "selectedQuality": self.selectedQuality,
            "exportStatus": self.exportStatus.value,
            "exportUris": export_uris,
            "exportDestination": self.exportDestination,
            "exportError": self.exportError,
            "exportAttempts": self.exportAttempts,
            "exportedAt": self.exportedAt.isoformat() if self.exportedAt else None,
        }

    def to_entity(self) -> DownloadTaskEntity:
        return DownloadTaskEntity(
            id=self.id,
            animeName=self.animeName,
            episodeNumber=self.episodeNumber,
            version=self.version,
            animeUrl=self.animeUrl,
            fileName=self.fileName,
            fileUrl=self.fileUrl,
            savePath=self.savePath,
            savePathSubtitle=self.savePathSubtitle,
            downloadPageUrl=self.downloadPageUrl,
            directDownloadUrl=self.directDownloadUrl,
            subtitleUrl=self.subtitleUrl,
            subtitlesJson=self.subtitlesJson,
            error=self.error,
            verificationUrl=self.verificationUrl,
            status=self.status.value,
            progress=self.progress,
            downloadedBytes=self.downloadedBytes,
            totalBytes=self.totalBytes,
            maxSpeedLimit=self.maxSpeedLimit,
            retryCount=self.retryCount,
            downloadSubtitles=self.downloadSubtitles,
            scheduledStartTime=self.scheduledStartTime,
            createdAt=self.createdAt,
            completedAt=self.completedAt,
            source=self.source,
            verificationStatus=self.verificationStatus,
            videoDuration=self.videoDuration,
            verifiedAt=self.verifiedAt,
            verificationError=self.verificationError,
            selectedServer=self.selectedServer,
            selectedQuality=self.selectedQuality,
            exportStatus=self.exportStatus.value,
            exportUrisJson=self.exportUrisJson,
            exportDestination=self.exportDestination,
            exportError=self.exportError,
            exportAttempts=self.exportAttempts,
            exportedAt=self.exportedAt,
        )
