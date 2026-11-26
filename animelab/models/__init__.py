"""Lazy model exports (PEP 562) so Pydantic API imports do not eagerly load SQLAlchemy."""
from importlib import import_module

_EXPORTS = {
    "AnimeResult": ("animelab.models.anime", "AnimeResult"),
    "AnimeDetail": ("animelab.models.anime", "AnimeDetail"),
    "Episode": ("animelab.models.anime", "Episode"),
    "AnimeDetailSnapshot": ("animelab.models.anime_detail_cache", "AnimeDetailSnapshot"),
    "FavoriteAnime": ("animelab.models.favorite", "FavoriteAnime"),
    "AutoDownloadEpisode": ("animelab.models.auto_download", "AutoDownloadEpisode"),
    "WatchProgress": ("animelab.models.watch_progress", "WatchProgress"),
    "PlaybackProgress": ("animelab.models.playback", "PlaybackProgress"),
    "DownloadTask": ("animelab.models.download_task", "DownloadTask"),
    "DownloadTaskEntity": ("animelab.models.download_task", "DownloadTaskEntity"),
    "DownloadStatus": ("animelab.models.download_task", "DownloadStatus"),
    "ExportStatus": ("animelab.models.download_task", "ExportStatus"),
}

__all__ = [
    "AnimeResult",
    "AnimeDetail",
    "AnimeDetailSnapshot",
    "Episode",
    "FavoriteAnime",
    "AutoDownloadEpisode",
    "WatchProgress",
    "DownloadTask",
    "DownloadTaskEntity",
    "DownloadStatus",
    "ExportStatus",
]


def register_all() -> None:
    """Import every ORM model module so Base.metadata knows all tables before migrations."""
    for module_name in (
        "animelab.models.playback",
        "animelab.models.anime_detail_cache",
        "animelab.models.favorite",
        "animelab.models.watch_progress",
        "animelab.models.auto_download",
        "animelab.models.download_task",
        "animelab.models.media_state",
    ):
        import_module(module_name)


def __getattr__(name: str):
    if name in _EXPORTS:
        module_name, attr_name = _EXPORTS[name]
        value = getattr(import_module(module_name), attr_name)
        globals()[name] = value
        return value
    try:
        value = import_module(f"{__name__}.{name}")
        globals()[name] = value
        return value
    except ModuleNotFoundError as exc:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}") from exc


def __dir__():
    return sorted([*globals(), *__all__])
