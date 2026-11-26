"""Lazy service exports (PEP 562) to avoid cascading eager imports on startup."""
from importlib import import_module

_EXPORTS = {
    "unpack": ("animelab.services.unpacking", "unpack"),
    "try_unpack": ("animelab.services.unpacking", "try_unpack"),
    "proxy_service": ("animelab.services.proxy_service", "proxy_service"),
    "scraping_service": ("animelab.services.scraping_service", "scraping_service"),
    "voiranime_service": ("animelab.services.voiranime_service", "voiranime_service"),
    "library_service": ("animelab.services.library_service", "library_service"),
    "download_manager": ("animelab.services.download_manager", "download_manager"),
    "watchdog_service": ("animelab.services.watchdog_service", "watchdog_service"),
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
