from animelab.routers.anime import router as anime_router
from animelab.routers.download import router as download_router
from animelab.routers.library import router as library_router
from animelab.routers.media import router as media_router
from animelab.routers.extensions import router as extensions_router
from animelab.routers.sources import router as sources_router
from animelab.routers.i18n import router as i18n_router

__all__ = [
    "anime_router",
    "download_router",
    "library_router",
    "media_router",
    "extensions_router",
    "sources_router",
    "i18n_router",
]
