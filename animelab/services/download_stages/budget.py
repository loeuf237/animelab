"""Bound native work until its real completion, even if its awaiter is cancelled."""
import asyncio
import time
from animelab.diagnostics import telemetry,domain
from collections.abc import Callable


class StageBudget:
    def __init__(self, limit: int):
        self.limit = max(1, limit)
        self.semaphore = asyncio.Semaphore(self.limit)
        self.active = 0

    async def run(self, task, jobs: dict, function: Callable, *args, **kwargs):
        waiting=time.monotonic()
        await self.semaphore.acquire()
        started=time.monotonic()
        context={"taskId":task.id,"source":task.source or "unknown","phase":task.phase or "native","domain":domain(task.fileUrl)}
        telemetry.event("stage_started",**context,waitMs=(started-waiting)*1000)
        if task.paused or task.cancelled:
            self.semaphore.release()
            raise ValueError('Operation was paused or cancelled')
        self.active += 1
        job = asyncio.create_task(asyncio.to_thread(function, *args, **kwargs))
        jobs[task.id] = job
        def finished(result):
            if jobs.get(task.id) is result:
                jobs.pop(task.id, None)
            telemetry.event("stage_finished",**context,durationMs=(time.monotonic()-started)*1000,
                            status="interrupted" if task.paused or task.cancelled else "failed" if result.cancelled() or result.exception() else "completed")
            self.active -= 1
            self.semaphore.release()
            if not result.cancelled():
                result.exception()
        job.add_done_callback(finished)
        return await asyncio.shield(job)
