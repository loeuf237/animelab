"""Persistent offline snapshot of library anime detail metadata and episodes."""
from datetime import datetime, timezone

from sqlalchemy import Boolean, Column, DateTime, Integer, String, Text

from animelab.database import Base


class AnimeDetailSnapshot(Base):
    """Cached AnimeDetail JSON snapshot keyed by canonical anime URL."""

    __tablename__ = "anime_detail_snapshots"

    id = Column(Integer, primary_key=True, autoincrement=True)
    animeUrl = Column(String, unique=True, nullable=False, index=True)
    source = Column(String, nullable=False, default="")
    sourceName = Column(String, nullable=False, default="")
    title = Column(String, nullable=False, default="")
    detailJson = Column(Text, nullable=False)
    pinned = Column(Boolean, nullable=False, default=False, index=True)
    updatedAt = Column(DateTime, nullable=False, default=lambda: datetime.now(timezone.utc))
