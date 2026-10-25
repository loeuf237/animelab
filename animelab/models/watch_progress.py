from sqlalchemy import Column, Integer, String, Boolean, DateTime, UniqueConstraint
from animelab.database import Base

class WatchProgress(Base):
    __tablename__ = "watch_progress"

    id = Column(Integer, primary_key=True, autoincrement=True)
    animeUrl = Column(String, nullable=False, index=True)
    animeName = Column(String, nullable=False)
    episodeNumber = Column(Integer, nullable=False)
    version = Column(String, default="")
    downloaded = Column(Boolean, default=False)
    watched = Column(Boolean, default=False)
    downloadedAt = Column(DateTime, nullable=True)
    watchedAt = Column(DateTime, nullable=True)

    __table_args__ = (
        UniqueConstraint("animeUrl", "episodeNumber", "version", name="uq_progress_anime_ep_version"),
    )

    def to_dict(self):
        return {
            "id": self.id,
            "animeUrl": self.animeUrl,
            "animeName": self.animeName,
            "episodeNumber": self.episodeNumber,
            "version": self.version,
            "downloaded": self.downloaded,
            "watched": self.watched,
            "downloadedAt": self.downloadedAt.isoformat() if self.downloadedAt else None,
            "watchedAt": self.watchedAt.isoformat() if self.watchedAt else None,
        }
