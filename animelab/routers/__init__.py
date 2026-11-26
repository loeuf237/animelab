"""Lazy router exports (PEP 562) so importing one router does not pull all others."""
from importlib import import_module

_EXPORTS = {
    "anime_router": ("animelab.routers.anime", "router"),
    "download_router": ("animelab.routers.download", "router"),
    "library_router": ("animelab.routers.library", "router"),
    "media_router": ("animelab.routers.media", "router"),
    "extensions_router": ("animelab.routers.extensions", "router"),
    "sources_router": ("animelab.routers.sources", "router"),
    "i18n_router": ("animelab.routers.i18n", "router"),
}

__all__ = list(_EXPORTS)


def __getattr__(name: str):
    if name not in _EXPORTS:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    module_name, attr_name = _EXPORTS[name]
    value = getattr(import_module(module_name), attr_name)
    globals()[name] = value
    return value


def __dir__():
    return sorted([*globals(), *__all__])
