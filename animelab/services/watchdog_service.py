import asyncio
import logging
from animelab.config import settings
from animelab.services.library_service import library_service
from animelab.services.source_catalogue import source_catalogue
from animelab.models.auto_download import episode_version
from animelab import platform_events
from animelab.services.download_manager import download_manager

logger = logging.getLogger("animelab.watchdog")

class WatchdogService:
    def __init__(self):
        self.interval: int = settings.WATCHDOG_INTERVAL_SECONDS
        self._running: bool = False
        self._task: asyncio.Task = None
        self._check_lock = asyncio.Lock()

    def start(self):
        if not self._running:
            self._running = True
            self._task = asyncio.create_task(self._run_loop())
            logger.info("Watchdog démarré (intervalle: %ds)", self.interval)

    def stop(self):
        self._running = False
        if self._task:
            self._task.cancel()

    async def _run_loop(self):
        last_watchdog_time = 0.0
        while self._running:
            try:
                now = asyncio.get_event_loop().time()
                # 1. Vérification des tâches planifiées toutes les 5 secondes
                await download_manager.check_scheduled_tasks()

                # 2. Vérification des nouveaux épisodes toutes les `interval` secondes
                if now - last_watchdog_time >= self.interval:
                    last_watchdog_time = now
                    await self.check_new_episodes()

            except asyncio.CancelledError:
                break
            except Exception as e:
                logger.error("Erreur dans la boucle watchdog: %s", e)

            await asyncio.sleep(5)

    async def check_new_episodes(self) -> int:
        if self._check_lock.locked():
            return 0
        async with self._check_lock:
            return await self._check_favorites()

    async def _check_favorites(self) -> int:
        favorites = [f for f in library_service.get_all_favorites() if f.autoDownload]
        if not favorites:
            return 0

        total_new = 0
        logger.info("[Watchdog] Vérification de %d animé(s) en auto-download...", len(favorites))
        for fav in favorites:
            try:
                count = await self._check_anime(fav)
                total_new += count
            except Exception as e:
                logger.error("[Watchdog] Erreur pour '%s': %s", fav.title, e)
                library_service.set_auto_download_error(fav.url, str(e))
        return total_new

    async def _check_anime(self, fav) -> int:
        logger.info("[Watchdog] Vérification de '%s'...", fav.title)
        provider = source_catalogue.provider(fav.source)
        detail = await provider.get_anime_detail(fav.url)

        if not detail or not detail.episodes:
            logger.warning("[Watchdog] Aucun épisode trouvé pour '%s'", fav.title)
            return 0

        # A preference may have changed while fetching the remote catalogue.
        fav = library_service.get_favorite(fav.url)
        if not fav or not fav.autoDownload:
            return 0
        episodes = {}
        for ep in detail.episodes:
            version = episode_version(ep.version or detail.version)
            url = ep.downloadPageUrl or ep.playerUrl or ep.directDownloadUrl
            if url:
                episodes.setdefault((ep.number, version), (ep, version, url))
        versions = {version for _, version in episodes}
        preferred = episode_version(fav.autoDownloadVersion)
        if not preferred:
            declared = episode_version(detail.version)
            if declared in versions:
                preferred = declared
            elif len(versions) == 1:
                preferred = next(iter(versions))
            elif len(versions) > 1:
                raise ValueError("Choisissez une version pour le suivi automatique dans la bibliothèque.")
        selected = versions if preferred == "*" else {preferred}
        storage = await asyncio.to_thread(platform_events.storage_status)
        if storage is not None and not storage.get("authorized"):
            raise PermissionError("Storage access unavailable; authorize a folder in Settings > Storage")
        pending = library_service.discover_auto_episodes(fav, list(episodes.values()), selected)
        count = 0
        errors = []
        for entry in pending:
            try:
                previous = library_service.find_episode_task(fav.source, fav.url, entry.episodeNumber, entry.version)
                if previous:
                    library_service.attach_auto_download_task(entry.id, previous.to_task())
                    continue
                ep = episodes.get((entry.episodeNumber, entry.version))
                if ep is None:
                    continue  # A temporarily absent player stays discoverable for a future check.
                task = download_manager.start_download(
                    anime_name=fav.title, episode_number=entry.episodeNumber,
                    download_page_url=entry.episodeUrl,
                    file_name=f"{fav.title} - Episode {entry.episodeNumber}.mp4",
                    subtitle_url=ep[0].subtitleUrl,
                    download_subtitles=bool(fav.autoDownloadSubtitles),
                    selected_server=fav.autoDownloadServer, selected_quality=fav.autoDownloadQuality,
                    source=fav.source, version=entry.version, anime_url=fav.url,
                )
                library_service.attach_auto_download_task(entry.id, task)
                count += 1
            except Exception as exc:
                # Keep DISCOVERED if queue creation fails; the numeric cursor is
                # informational only and cannot discard this episode anymore.
                errors.append(str(exc))
                logger.exception("Unable to schedule episode %s (%s)", entry.episodeNumber, entry.version)
        if errors:
            library_service.set_auto_download_error(fav.url, errors[0])
        return count

watchdog_service = WatchdogService()
