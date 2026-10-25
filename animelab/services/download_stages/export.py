"""ExportCoordinator: extracted stage with a compatibility coordinator context."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animelab.services.download_manager import DownloadManagerService

import asyncio
import json
import logging
from animelab import platform_events
from datetime import datetime, timezone


from animelab.config import settings
from animelab.models.download_task import DownloadTask, ExportStatus
from animelab.services.library_service import library_service

logger = logging.getLogger("animelab.download.export")

from animelab.services.download_stages.budget import StageBudget

class ExportCoordinator:
    def __init__(self, manager: DownloadManagerService):
        self.manager = manager
        self.locks = {}
        self.jobs = {}
        self.budget = StageBudget(settings.MAX_EXPORT_WORKERS)

    async def export_task(self, task: DownloadTask, *, manual=False):
        """Persist an independent, retryable native export. Never fetch media."""
        ctx = self.manager
        if platform_events.completed_handler is None:
            raise ValueError("Android export is unavailable")
        native_job = ctx._native_exports.get(task.id)
        if native_job is not None and not native_job.done():
            raise ValueError("An export is already in progress for this download")
        lock = ctx._export_locks.setdefault(task.id, asyncio.Lock())
        if lock.locked():
            raise ValueError("An export is already in progress for this download")
        async with lock:
            previous_phase = task.phase
            try:
                if manual:
                    task.paused = task.cancelled = False
                if task.paused or task.cancelled:
                    raise ValueError("Export was paused or cancelled")
                ctx.tasks[task.id] = task
                if task.id not in ctx.task_order:
                    ctx.task_order.append(task.id)
                task.exportStatus = ExportStatus.EXPORTING
                task.exportError = None
                task.exportUrisJson = "[]"
                task.exportedAt = None
                task.exportAttempts += 1
                task.phase = "exporting"
                library_service.save_task(task)
                ctx.broadcast_update(task)
                storage = await asyncio.to_thread(platform_events.storage_status)
                task.exportDestination = storage.get("destination") if storage else None
                if storage is not None and not storage.get("authorized"):
                    raise PermissionError("Storage access unavailable; authorize a folder in Settings > Storage")
                result = await self.budget.run(task, self.jobs, platform_events.completed, task)
                if task.paused or task.cancelled:
                    raise ValueError("Export was paused or cancelled")
                uris = result.get("uris") if isinstance(result, dict) else None
                if not isinstance(uris, list) or not uris or not all(isinstance(uri, str) and uri for uri in uris):
                    raise ValueError("The storage provider did not confirm the exported files")
                task.exportStatus = ExportStatus.EXPORTED
                task.exportUrisJson = json.dumps(uris)
                task.exportDestination = result.get("destination") or task.exportDestination
                task.exportedAt = datetime.now(timezone.utc)
                return result
            except (Exception, asyncio.CancelledError) as exc:
                if isinstance(exc, asyncio.CancelledError):
                    task.paused = True  # Stop the still-running native copy at its next chunk.
                task.exportStatus = ExportStatus.PENDING if task.paused or task.cancelled or isinstance(exc, asyncio.CancelledError) else ExportStatus.EXPORT_FAILED
                task.exportError = str(exc) or "Export interrupted; retry from the private library copy."
                raise
            finally:
                if task.error and task.error.startswith("Android export failed;"):
                    task.error = None
                task.phase = previous_phase
                try:
                    library_service.save_task(task)
                    ctx.broadcast_update(task)
                finally:
                    ctx._export_locks.pop(task.id, None)
