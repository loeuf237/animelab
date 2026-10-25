"""Resume identity is stable across quality, host and local/remote playback."""
from datetime import datetime, timezone
from sqlalchemy import Column, Integer, String, Float, DateTime, UniqueConstraint
from animelab.database import Base


class PlaybackProgress(Base):
    __tablename__ = 'playback_progress'
    id = Column(Integer, primary_key=True)
    source = Column(String, nullable=False)
    animeUrl = Column(String, nullable=False)
    episodeNumber = Column(Integer, nullable=False)
    version = Column(String, nullable=False, default='')
    positionSeconds = Column(Float, nullable=False, default=0)
    durationSeconds = Column(Float, nullable=False, default=0)
    selectionJson = Column(String, nullable=False, default='{}')
    sessionId = Column(String(32), nullable=False)
    lastSequence = Column(Integer, nullable=False, default=0)
    updatedAt = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
    __table_args__ = (UniqueConstraint('source','animeUrl','episodeNumber','version',name='uq_playback_identity'),)
