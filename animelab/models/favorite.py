from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Boolean, DateTime
from animelab.database import Base

class FavoriteAnime(Base):
    __tablename__ = "favorites"

    id = Column(Integer, primary_key=True, autoincrement=True)
    url = Column(String, unique=True, nullable=False, index=True)
    title = Column(String, nullable=False)
    imageUrl = Column(String, default="")
    source = Column(String, default="french-manga")
    lastKnownEpisode = Column(Integer, default=0)
    autoDownload = Column(Boolean, default=False)
    autoDownloadVersion = Column(String, default="")
    autoDownloadSubtitles = Column(Boolean, default=False)
    autoDownloadServer = Column(String, nullable=True)
    autoDownloadQuality = Column(String, nullable=True)
    autoDownloadInitialized = Column(Boolean, default=False)
    autoDownloadError = Column(String, nullable=True)
    addedAt = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    lastCheckedAt = Column(DateTime, nullable=True)

    def to_dict(self):
        return {
            "id": self.id,
            "url": self.url,
            "title": self.title,
            "imageUrl": self.imageUrl,
            "source": self.source,
            "lastKnownEpisode": self.lastKnownEpisode,
            "autoDownload": self.autoDownload,
            "autoDownloadVersion": self.autoDownloadVersion or "",
            "autoDownloadSubtitles": bool(self.autoDownloadSubtitles),
            "autoDownloadServer": self.autoDownloadServer,
            "autoDownloadQuality": self.autoDownloadQuality,
            "autoDownloadError": self.autoDownloadError,
            "addedAt": self.addedAt.isoformat() if self.addedAt else None,
            "lastCheckedAt": self.lastCheckedAt.isoformat() if self.lastCheckedAt else None,
        }
