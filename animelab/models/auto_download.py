"""Persistent discovery ledger; a catalogue cursor is not a completion marker."""
from datetime import datetime, timezone

from sqlalchemy import Column, DateTime, Integer, String, UniqueConstraint

from animelab.database import Base


def episode_version(value):
    return " ".join(str(value or "").split()).upper()


class AutoDownloadEpisode(Base):
    __tablename__ = "auto_download_episodes"
    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    animeUrl = Column(String, nullable=False)
    episodeNumber = Column(Integer, nullable=False)
    version = Column(String, nullable=False, default="")
    episodeUrl = Column(String, nullable=False, default="")
    state = Column(String, nullable=False, default="DISCOVERED")
    taskId = Column(String(36), nullable=True, index=True)
    discoveredAt = Column(DateTime, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint("source", "animeUrl", "episodeNumber", "version",
                                      name="uq_auto_download_episode"),)
