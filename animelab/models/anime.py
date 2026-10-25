from typing import List, Optional
from pydantic import BaseModel, Field

if not hasattr(BaseModel, "model_dump"):
    setattr(BaseModel, "model_dump", lambda self, **kwargs: getattr(self, "dict")(**kwargs))
if not hasattr(BaseModel, "model_dump_json"):
    setattr(BaseModel, "model_dump_json", lambda self, **kwargs: getattr(self, "json")(**kwargs))
if not hasattr(BaseModel, "model_validate"):
    setattr(BaseModel, "model_validate", classmethod(lambda cls, obj, **kwargs: getattr(cls, "parse_obj")(obj)))

class Episode(BaseModel):
    number: int
    title: str
    playerUrl: str = ""
    downloadPageUrl: str = ""
    directDownloadUrl: Optional[str] = None
    subtitleUrl: Optional[str] = None
    version: str = "VOSTFR"
    synopsis: Optional[str] = None
    thumbnailUrl: Optional[str] = None

class AnimeResult(BaseModel):
    id: str
    title: str
    imageUrl: str = ""
    url: str
    version: str = ""
    type: str = "Anime"
    episodeInfo: str = ""
    source: str = ""
    genres: List[str] = Field(default_factory=list)

class AnimeDetail(BaseModel):
    title: str
    originalTitle: Optional[str] = None
    synopsis: Optional[str] = None
    imageUrl: str = ""
    bannerUrl: Optional[str] = None
    version: str = ""
    studio: Optional[str] = None
    url: str
    genres: List[str] = Field(default_factory=list)
    directors: List[str] = Field(default_factory=list)
    actors: List[str] = Field(default_factory=list)
    episodes: List[Episode] = Field(default_factory=list)
    source: str = ""
    tmdbId: Optional[int] = None
    releaseDate: Optional[str] = None
