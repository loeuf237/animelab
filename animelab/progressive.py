"""Progressive two-stage engine initialization and on-demand ASGI router mounting."""
from __future__ import annotations

import asyncio
from contextlib import suppress
import importlib
import logging
import re
import threading
import time
from typing import Any, Callable
import weakref

logger = logging.getLogger("animelab.progressive")

_SUBTITLE_PATH_RE = re.compile(r"^/api/download/[^/]+/subtitles(?:/|$)")
_SOURCE_FEED_RE = re.compile(r"^/api/sources/[^/]+/feed/?$")

STAGE0_EXACT_PATHS = frozenset({
    "/",
    "/favicon.ico",
    "/manifest.json",
    "/sw.js",
    "/offline.html",
    "/api/app",
    "/api/i18n",
    "/api/diagnostics",
    "/api/engine/readiness",
    "/downloads",
    "/settings",
    "/library",
    "/favorites",
    "/history",
    "/extensions",
    "/sources",
    "/search",
    "/anime",
    "/voiranime",
})

STAGE0_PREFIXES = (
    "/spa",
    "/app",
    "/assets/",
    "/static/",
    "/img/",
    "/api/app/",
    "/api/i18n/",
    "/api/diagnostics/",
)

OPENAPI_PATHS = frozenset({
    "/openapi.json",
    "/docs",
    "/docs/oauth2-redirect",
    "/redoc",
})

ROUTE_GROUP_SPECS: dict[str, tuple[str, str]] = {
    "library": ("animelab.routers.library", "router"),
    "anime": ("animelab.routers.anime", "router"),
    "downloads": ("animelab.routers.download", "router"),
    "media": ("animelab.routers.media", "router"),
    "playback": ("animelab.routers.playback", "router"),
    "network": ("animelab.routers.network", "router"),
    "sources": ("animelab.routers.sources", "router"),
    "extensions": ("animelab.routers.extensions", "router"),
    "subtitles": ("animelab.routers.subtitles", "router"),
}

STAGE1_GROUPS: tuple[str, ...] = (
    "library",
    "anime",
    "downloads",
    "media",
    "playback",
    "network",
)

STAGE2_GROUPS: tuple[str, ...] = (
    "sources",
    "extensions",
    "subtitles",
)

ALL_ROUTE_GROUPS: tuple[str, ...] = STAGE1_GROUPS + STAGE2_GROUPS


def resolve_groups_for_path(path: str) -> tuple[str, ...]:
    """Return ordered router group names needed to serve *path*."""
    clean = path or "/"
    if clean in STAGE0_EXACT_PATHS:
        return ()
    for prefix in STAGE0_PREFIXES:
        if prefix.endswith("/"):
            if clean.startswith(prefix):
                return ()
        elif clean == prefix or clean.startswith(prefix + "/"):
            return ()

    if clean in OPENAPI_PATHS:
        return ALL_ROUTE_GROUPS

    if (
        clean == "/api/download/subtitle-provider"
        or clean == "/api/download/subtitle-sync-capabilities"
        or _SUBTITLE_PATH_RE.match(clean)
    ):
        return ("subtitles",)

    if (
        clean == "/api/releases"
        or clean.startswith("/api/releases/")
        or clean == "/api/search"
        or clean.startswith("/api/search/")
        or clean == "/api/anime"
        or clean.startswith("/api/anime/")
        or clean == "/api/home"
        or clean.startswith("/api/home/")
        or _SOURCE_FEED_RE.match(clean)
    ):
        return ("anime",)

    if (
        clean == "/api/favorites"
        or clean.startswith("/api/favorites/")
        or clean == "/api/progress"
        or clean.startswith("/api/progress/")
        or clean == "/api/history"
        or clean.startswith("/api/history/")
        or clean == "/api/voiranime"
        or clean.startswith("/api/voiranime/")
        or clean == "/api/system"
        or clean.startswith("/api/system/")
        or clean == "/api/watchdog"
        or clean.startswith("/api/watchdog/")
    ):
        return ("library",)

    if (
        clean == "/api/download"
        or clean.startswith("/api/download/")
        or clean == "/api/proxy"
        or clean.startswith("/api/proxy/")
        or clean == "/api/episode"
        or clean.startswith("/api/episode/")
    ):
        return ("downloads",)

    if clean == "/api/media" or clean.startswith("/api/media/"):
        return ("media",)

    if clean == "/api/playback" or clean.startswith("/api/playback/"):
        return ("playback",)

    if clean == "/api/network" or clean.startswith("/api/network/"):
        return ("network",)

    if clean == "/api/sources" or clean.startswith("/api/sources/"):
        return ("sources",)

    if clean == "/api/extensions" or clean.startswith("/api/extensions/"):
        return ("extensions",)

    if clean.startswith("/api/"):
        return ALL_ROUTE_GROUPS

    return ()


class ProgressiveAppLoader:
    """Coordinates staged service hydration and on-demand FastAPI router inclusion."""

    def __init__(self, app: Any, *, progressive: bool = True) -> None:
        self.app = app
        self.progressive = progressive
        self.started_at: float = time.perf_counter()
        self.stage0_ready_at: float | None = None
        self.stage1_ready_at: float | None = None
        self.full_ready_at: float | None = None
        self.loaded_groups: set[str] = set()
        self.group_timings_ms: dict[str, float] = {}
        self.core_initialized: bool = False
        self.fully_loaded: bool = False
        self._mount_lock = threading.RLock()
        self._loop_locks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, dict[str, asyncio.Lock]
        ] = weakref.WeakKeyDictionary()
        self._hooks: dict[str, list[Callable[[], Any]]] = {}
        self._background_tasks: weakref.WeakKeyDictionary[
            asyncio.AbstractEventLoop, list[asyncio.Task[Any]]
        ] = weakref.WeakKeyDictionary()
        self._warmup_task: asyncio.Task[Any] | None = None
        self._installed_linux_webview: bool = False

    def _task_bucket(self) -> list[asyncio.Task[Any]]:
        loop = asyncio.get_running_loop()
        bucket = self._background_tasks.get(loop)
        if bucket is None:
            bucket = []
            self._background_tasks[loop] = bucket
        return bucket

    def register_hook(self, event: str, callback: Callable[[], Any]) -> None:
        if callback not in self._hooks.setdefault(event, []):
            self._hooks[event].append(callback)

    def _fire_hooks(self, event: str) -> None:
        for callback in list(self._hooks.get(event, ())):
            callback()

    def _get_lock(self, key: str) -> asyncio.Lock:
        loop = asyncio.get_running_loop()
        per_loop = self._loop_locks.get(loop)
        if per_loop is None:
            per_loop = {}
            self._loop_locks[loop] = per_loop
        lock = per_loop.get(key)
        if lock is None:
            lock = asyncio.Lock()
            per_loop[key] = lock
        return lock

    def mark_stage0_ready(self) -> None:
        if self.stage0_ready_at is None:
            self.stage0_ready_at = time.perf_counter()

    def mount_all_eager(self) -> None:
        """Mount every Stage 1 + Stage 2 router synchronously (non-progressive mode)."""
        with self._mount_lock:
            for group in ALL_ROUTE_GROUPS:
                if group not in self.loaded_groups:
                    t0 = time.perf_counter()
                    module_name, attr_name = ROUTE_GROUP_SPECS[group]
                    router = getattr(importlib.import_module(module_name), attr_name)
                    self.app.include_router(router)
                    self.loaded_groups.add(group)
                    self.group_timings_ms[group] = round((time.perf_counter() - t0) * 1000.0, 2)
            self.app.openapi_schema = None
            self.fully_loaded = True
            self.stage0_ready_at = self.stage0_ready_at or time.perf_counter()
            self.stage1_ready_at = self.stage1_ready_at or time.perf_counter()
            self.full_ready_at = self.full_ready_at or time.perf_counter()

    def initialize_core_services_eager(self) -> None:
        """Run full lifespan core startup synchronously inside async lifespan."""
        from animelab.config import IS_ANDROID
        from animelab.database import init_db
        from animelab.environment import getenv
        from animelab.services import app_preferences
        from animelab.services.animepahe_service import animepahe_service
        from animelab.services.browser_verification import browser_verification
        from animelab.services.download_manager import download_manager
        from animelab.services.proxy_pool import proxy_pool
        from animelab.services.scraping_service import scraping_service
        from animelab.services.source_http import source_http
        from animelab.services.voiranime_service import voiranime_service
        from animelab.services.watchdog_service import watchdog_service

        self._fire_hooks("core_services")
        source_http.start()
        browser_verification.verified_callback = download_manager.resume_verified_domain
        if not IS_ANDROID:
            from animelab.desktop.window import install_linux_webview_opener
            self._installed_linux_webview = install_linux_webview_opener(browser_verification)
        init_db()
        app_preferences.restore_download_directory()
        download_manager.init_from_db()
        loop = asyncio.get_running_loop()
        source_http.rotation_callback = lambda domain: loop.call_soon_threadsafe(
            download_manager.resume_verified_domain, domain
        )
        watchdog_service.start()
        bucket = self._task_bucket()
        bucket.extend([
            asyncio.create_task(browser_verification.watch()),
            asyncio.create_task(proxy_pool.watch()),
        ])
        if getenv("ANIMAN_STARTUP_REFRESH", "true").lower() not in ("false", "0", "no"):
            bucket.append(asyncio.create_task(proxy_pool.refresh()))
            for service in (scraping_service, voiranime_service, animepahe_service):
                service._refresh_task = asyncio.create_task(service._safe_refresh_cache())
                bucket.append(service._refresh_task)
        self.core_initialized = True

    async def ensure_core_services(self) -> None:
        """Lazily initialize database, transport, download queue and background watchers."""
        if self.core_initialized:
            return
        async with self._get_lock("__core__"):
            if self.core_initialized:
                return
            t0 = time.perf_counter()
            self._fire_hooks("core_services")

            def _blocking_core_setup() -> None:
                from animelab.database import init_db
                from animelab.services import app_preferences
                from animelab.services.source_http import source_http

                importlib.import_module("animelab.services.download_manager")
                importlib.import_module("animelab.services.browser_verification")
                importlib.import_module("animelab.services.watchdog_service")
                importlib.import_module("animelab.services.proxy_pool")
                init_db()
                app_preferences.restore_download_directory()
                source_http.start()

            await asyncio.to_thread(_blocking_core_setup)

            from animelab.config import IS_ANDROID
            from animelab.services.browser_verification import browser_verification
            from animelab.services.download_manager import download_manager
            from animelab.services.proxy_pool import proxy_pool
            from animelab.services.source_http import source_http
            from animelab.services.watchdog_service import watchdog_service

            browser_verification.verified_callback = download_manager.resume_verified_domain
            if not IS_ANDROID:
                from animelab.desktop.window import install_linux_webview_opener
                self._installed_linux_webview = install_linux_webview_opener(browser_verification)
            download_manager.init_from_db()
            loop = asyncio.get_running_loop()
            source_http.rotation_callback = lambda domain: loop.call_soon_threadsafe(
                download_manager.resume_verified_domain, domain
            )
            watchdog_service.start()
            self._task_bucket().extend([
                asyncio.create_task(browser_verification.watch()),
                asyncio.create_task(proxy_pool.watch()),
            ])
            self.core_initialized = True
            self.group_timings_ms["core_services"] = round((time.perf_counter() - t0) * 1000.0, 2)

    async def ensure_group(self, group: str) -> None:
        """Import and mount a single router group on demand."""
        if group in self.loaded_groups:
            return
        await self.ensure_core_services()
        if group in self.loaded_groups:
            return
        async with self._get_lock(group):
            if group in self.loaded_groups:
                return
            t0 = time.perf_counter()
            self._fire_hooks(group)
            module_name, attr_name = ROUTE_GROUP_SPECS[group]
            module = await asyncio.to_thread(importlib.import_module, module_name)
            router = getattr(module, attr_name)
            with self._mount_lock:
                if group not in self.loaded_groups:
                    self.app.include_router(router)
                    self.app.openapi_schema = None
                    self.loaded_groups.add(group)
                    self.group_timings_ms[group] = round((time.perf_counter() - t0) * 1000.0, 2)
                    if all(item in self.loaded_groups for item in STAGE1_GROUPS) and self.stage1_ready_at is None:
                        self.stage1_ready_at = time.perf_counter()
                    if len(self.loaded_groups) == len(ALL_ROUTE_GROUPS):
                        self.fully_loaded = True
                        if self.full_ready_at is None:
                            self.full_ready_at = time.perf_counter()
                            self._fire_hooks("full_ready")

    async def ensure_for_path(self, path: str) -> None:
        if self.fully_loaded:
            return
        groups = resolve_groups_for_path(path)
        for group in groups:
            await self.ensure_group(group)

    async def warmup_background(self) -> None:
        """Hydrate Stage 1 then Stage 2 in small yields without blocking Stage 0."""
        try:
            await asyncio.sleep(0)
            await self.ensure_core_services()
            for group in STAGE1_GROUPS:
                await self.ensure_group(group)
                await asyncio.sleep(0.01)
            if self.stage1_ready_at is None:
                self.stage1_ready_at = time.perf_counter()

            await asyncio.sleep(0.25)
            for group in STAGE2_GROUPS:
                await self.ensure_group(group)
                await asyncio.sleep(0.01)

            from animelab.environment import getenv
            if getenv("ANIMAN_STARTUP_REFRESH", "true").lower() not in ("false", "0", "no"):
                from animelab.services.animepahe_service import animepahe_service
                from animelab.services.french_stream_service import french_stream_service
                from animelab.services.proxy_pool import proxy_pool
                from animelab.services.scraping_service import scraping_service
                from animelab.services.voiranime_service import voiranime_service

                bucket = self._task_bucket()
                bucket.append(asyncio.create_task(proxy_pool.refresh()))
                for service in (scraping_service, voiranime_service, animepahe_service, french_stream_service):
                    service._refresh_task = asyncio.create_task(service._safe_refresh_cache())
                    bucket.append(service._refresh_task)

            self.fully_loaded = True
            if self.full_ready_at is None:
                self.full_ready_at = time.perf_counter()
                self._fire_hooks("full_ready")
            logger.info(
                "Progressive warmup complete (groups=%s)",
                sorted(self.loaded_groups),
            )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            logger.warning("Progressive background warmup stopped early: %s", exc, exc_info=True)

    def start_warmup(self) -> asyncio.Task[Any]:
        if self._warmup_task is None or self._warmup_task.done():
            self._warmup_task = asyncio.create_task(self.warmup_background(), name="progressive-warmup")
        return self._warmup_task

    async def shutdown(self) -> None:
        """Stop only subsystems that were actually initialized during this session."""
        loop = asyncio.get_running_loop()
        if self._warmup_task is not None and self._warmup_task.get_loop() is loop:
            if not self._warmup_task.done():
                self._warmup_task.cancel()
            with suppress(asyncio.CancelledError):
                await self._warmup_task
            self._warmup_task = None

        tasks = [task for task in self._background_tasks.pop(loop, []) if task.get_loop() is loop]
        for task in tasks:
            if not task.done():
                task.cancel()
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        if not self.core_initialized:
            return

        from animelab.services.browser_verification import browser_verification
        from animelab.services.download_manager import download_manager
        from animelab.services.proxy_pool import proxy_pool
        from animelab.services.source_http import source_http
        from animelab.services.watchdog_service import watchdog_service

        try:
            source_http.rotation_callback = None
            browser_verification.verified_callback = None
            if self._installed_linux_webview:
                browser_verification.webview_opener = None
            watchdog_service.stop()
            await download_manager.shutdown()
            await browser_verification.close()
            await proxy_pool.close()
            await asyncio.to_thread(source_http.close)
        finally:
            self.core_initialized = False

    def readiness_snapshot(self) -> dict[str, Any]:
        loaded = sorted(self.loaded_groups)
        pending = [group for group in ALL_ROUTE_GROUPS if group not in self.loaded_groups]
        stage = "full" if self.fully_loaded else "stage1" if all(g in self.loaded_groups for g in STAGE1_GROUPS) else "stage0"
        timings = dict(self.group_timings_ms)
        if self.stage0_ready_at is not None:
            timings["stage0_ms"] = round((self.stage0_ready_at - self.started_at) * 1000.0, 2)
        if self.stage1_ready_at is not None:
            timings["stage1_ms"] = round((self.stage1_ready_at - self.started_at) * 1000.0, 2)
        if self.full_ready_at is not None:
            timings["full_ms"] = round((self.full_ready_at - self.started_at) * 1000.0, 2)
        return {
            "progressive": self.progressive,
            "stage": stage,
            "ready": self.stage0_ready_at is not None or not self.progressive,
            "coreInitialized": self.core_initialized,
            "fullyReady": self.fully_loaded,
            "loadedGroups": loaded,
            "pendingGroups": pending,
            "timingsMs": timings,
        }


class ProgressiveRouteMiddleware:
    """ASGI guard that loads required router groups on demand before routing."""

    def __init__(self, app: Any, *, loader: ProgressiveAppLoader) -> None:
        self.app = app
        self.loader = loader

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if not self.loader.fully_loaded and scope.get("type") in ("http", "websocket"):
            await self.loader.ensure_for_path(scope.get("path", "/"))
        await self.app(scope, receive, send)
