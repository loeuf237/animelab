"""DownloadScheduler: extracted stage with a compatibility coordinator context."""
from __future__ import annotations
from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from animelab.services.download_manager import DownloadManagerService

from animelab.services.download_stages.state import transition
import asyncio
from animelab.services.background import spawn
import logging
from datetime import datetime, timezone
from typing import List


from animelab.models.download_task import DownloadStatus, ensure_utc
from animelab.services.library_service import library_service

logger = logging.getLogger("animelab.download.scheduler")


class DownloadScheduler:
    def __init__(self, manager: DownloadManagerService):
        self.manager = manager
        self.lock = asyncio.Lock()
        self.workers = {}
        self.network_tasks = set()
        self.closing = False

    def move_task_to_top(self, task_id: str):
        ctx = self.manager
        if task_id in ctx.task_order:
            ctx.task_order.remove(task_id)
            ctx.task_order.insert(0, task_id)
            ctx._trigger_process_queue()
            task = ctx.tasks.get(task_id)
            if task:
                ctx.broadcast_update(task)


    def move_series_to_top(self, anime_name: str):
        ctx = self.manager
        if not anime_name:
            return
        series_ids = [tid for tid in ctx.task_order if ctx.tasks.get(tid) and ctx.tasks[tid].animeName.lower() == anime_name.lower()]
        if series_ids:
            for tid in series_ids:
                ctx.task_order.remove(tid)
            for tid in reversed(series_ids):
                ctx.task_order.insert(0, tid)
            ctx._trigger_process_queue()
            for tid in series_ids:
                t = ctx.tasks.get(tid)
                if t:
                    ctx.broadcast_update(t)


    def reorder_tasks(self, ordered_ids: List[str]):
        ctx = self.manager
        new_order = [tid for tid in ordered_ids if tid in ctx.tasks]
        for tid in ctx.task_order:
            if tid not in new_order:
                new_order.append(tid)
        ctx.task_order = new_order
        ctx._trigger_process_queue()


    def release_network(self, task_id):
        self.network_tasks.discard(task_id)
        self.manager._trigger_process_queue()

    async def process_queue(self):
        ctx = self.manager
        if self.closing:
            return
        async with self.lock:
            active = self.network_tasks | {task.id for task in ctx.tasks.values()
                if task.status in (DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING)
                and task.phase not in ('verifying', 'muxing', 'exporting')}
            slots = max(0, ctx.max_concurrent_downloads - len(active))
            for task_id in list(ctx.task_order):
                if slots <= 0:
                    break
                task = ctx.tasks.get(task_id)
                if task is None or task.status != DownloadStatus.PENDING or task_id in self.workers:
                    continue
                if ctx._has_destination_conflict(task):
                    ctx._pause_destination_conflict(task)
                    continue
                from animelab.services.download_stages.state import transition
                transition(task, DownloadStatus.DOWNLOADING)
                task.phase = 'resolving'
                library_service.save_task(task)
                ctx.broadcast_update(task)
                self.network_tasks.add(task_id)
                slots -= 1
                job = spawn(ctx._execute_download(task), name=f'download-{task.id}')
                self.workers[task_id] = job
                def finished(result, identity=task_id):
                    if self.workers.get(identity) is result:
                        self.workers.pop(identity, None)
                    self.release_network(identity)
                job.add_done_callback(finished)

    async def close(self):
        self.closing = True
        jobs = list(self.workers.values())
        for job in jobs:
            job.cancel()
        await asyncio.gather(*jobs, return_exceptions=True)
        # Native jobs retain their permits until actual completion. Their tasks
        # have been marked paused so they cannot publish after cancellation.
        remaining = list(self.manager._media_jobs.values()) + list(self.manager._native_exports.values())
        await asyncio.gather(*remaining, return_exceptions=True)


    async def check_scheduled_tasks(self):
        ctx = self.manager
        now = datetime.now(timezone.utc)
        for t in ctx.tasks.values():
            if t.status == DownloadStatus.SCHEDULED and t.scheduledStartTime:
                if ensure_utc(t.scheduledStartTime) <= now:
                    transition(t, DownloadStatus.PENDING)
                    library_service.save_task(t)
                    ctx.broadcast_update(t)
        await ctx.process_queue()
