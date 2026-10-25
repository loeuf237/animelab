"""A03: stage admission and lifetime under cancellation and competing jobs."""
import asyncio
import threading
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import DownloadManagerService
from animelab.services.download_stages.budget import StageBudget
from animelab.services.download_stages.state import transition
from animelab.services.library_service import library_service
from animelab.services.verification_service import verification_service, VerificationResult
from animelab import platform_events


@pytest.mark.asyncio
async def test_cancelled_native_work_retains_permit_until_thread_finishes():
    budget=StageBudget(1)
    first,second=DownloadTask(),DownloadTask()
    started,finish=threading.Event(),threading.Event()
    jobs={}
    def blocked():
        started.set(); assert finish.wait(5)
        return 'first'
    job=asyncio.create_task(budget.run(first,jobs,blocked))
    next_job=None
    try:
        assert await asyncio.to_thread(started.wait,2)
        job.cancel()
        with pytest.raises(asyncio.CancelledError): await job
        second_started=threading.Event()
        next_job=asyncio.create_task(budget.run(second,jobs,lambda: second_started.set()))
        await asyncio.sleep(0)
        assert not second_started.is_set() and budget.active == 1
        finish.set()
        await asyncio.wait_for(next_job,2)
        assert second_started.is_set() and budget.active == 0
    finally:
        finish.set()
        await asyncio.gather(*list(jobs.values()),return_exceptions=True)
        if next_job: await asyncio.gather(next_job,return_exceptions=True)


@pytest.mark.asyncio
async def test_media_wait_does_not_occupy_a_network_slot_and_never_duplicates_workers(tmp_path,monkeypatch):
    manager=DownloadManagerService();manager.max_concurrent_downloads=1
    monkeypatch.setattr(library_service,'save_task',lambda task: None)
    monkeypatch.setattr(manager,'broadcast_update',lambda task: None)
    monkeypatch.setattr(platform_events,'completed_handler',None)
    tasks=[DownloadTask(savePath=str(tmp_path/f'{i}.mp4'),fileName=f'{i}.mp4') for i in range(2)]
    for task in tasks: Path(task.savePath).write_bytes(b'video')
    manager.tasks={t.id:t for t in tasks};manager.task_order=[t.id for t in tasks]
    network_started=[asyncio.Event(),asyncio.Event()]
    network_finish=[asyncio.Event(),asyncio.Event()]
    media_started,media_finish=threading.Event(),threading.Event()
    def verify(**kwargs):
        media_started.set(); assert media_finish.wait(5)
        return VerificationResult(valid=True,status='VALID')
    monkeypatch.setattr(verification_service,'verify_file',verify)
    async def execute(task):
        index=tasks.index(task)
        network_started[index].set()
        await network_finish[index].wait()
        await manager._finalize_task(task)
    monkeypatch.setattr(manager,'_execute_download',execute)
    try:
        await asyncio.gather(manager.process_queue(),manager.process_queue())
        await asyncio.wait_for(network_started[0].wait(),2)
        assert not network_started[1].is_set() and len(manager.scheduler.workers)==1
        network_finish[0].set()
        assert await asyncio.to_thread(media_started.wait,2)
        await asyncio.wait_for(network_started[1].wait(),2)
        assert manager.media_pipeline.budget.active==1
        assert len(manager.scheduler.network_tasks)==1
        network_finish[1].set()
        media_finish.set()
        await asyncio.gather(*list(manager.scheduler.workers.values()))
        assert all(t.status==DownloadStatus.COMPLETED for t in tasks)
    finally:
        media_finish.set()
        for gate in network_finish: gate.set()
        await manager.shutdown()


@pytest.mark.asyncio
async def test_export_budget_is_independent_from_media_budget(tmp_path,monkeypatch):
    manager=DownloadManagerService()
    monkeypatch.setattr(library_service,'save_task',lambda task: None)
    monkeypatch.setattr(manager,'broadcast_update',lambda task: None)
    monkeypatch.setattr(platform_events,'storage_status_handler',None)
    started,finish=threading.Event(),threading.Event()
    media=DownloadTask();export=DownloadTask(status=DownloadStatus.COMPLETED)
    def blocked(): started.set(); assert finish.wait(5)
    media_job=asyncio.create_task(manager.media_pipeline.budget.run(media,manager._media_jobs,blocked))
    try:
        assert await asyncio.to_thread(started.wait,2)
        monkeypatch.setattr(platform_events,'completed_handler',lambda task:{'uris':['content://downloads/1']})
        result=await asyncio.wait_for(manager.export_task(export),2)
        assert result['uris'] and manager.media_pipeline.budget.active==1
    finally:
        finish.set();await media_job


def test_lifecycle_refuses_completed_to_active_without_explicit_requeue():
    task=DownloadTask(status=DownloadStatus.COMPLETED)
    with pytest.raises(ValueError,match='Invalid download transition'):
        transition(task,DownloadStatus.DOWNLOADING)
    transition(task,DownloadStatus.PENDING)
    transition(task,DownloadStatus.DOWNLOADING)
    transition(task,DownloadStatus.VERIFICATION_REQUIRED)
    transition(task,DownloadStatus.PAUSED)
    assert task.status==DownloadStatus.PAUSED


@pytest.mark.asyncio
async def test_waiting_media_job_is_protected_from_removal_and_resume(monkeypatch):
    manager=DownloadManagerService()
    task=DownloadTask(status=DownloadStatus.MUXING)
    task.paused=True
    manager.tasks[task.id]=task
    lock=asyncio.Lock();await lock.acquire()
    manager._finalization_locks[task.id]=lock
    assert not manager.resume_download(task.id)
    with pytest.raises(ValueError,match='current export'):
        manager.remove_task(task.id)
    assert task.paused
    lock.release()


@pytest.mark.asyncio
async def test_shutdown_persists_pause_and_restart_keeps_the_transfer_retryable(tmp_path,monkeypatch):
    import importlib
    from animelab.database import create_database_engine
    from animelab.migrations import migrate
    from sqlalchemy.orm import sessionmaker
    engine=create_database_engine('sqlite:///'+str(tmp_path/'restart.sqlite'))
    migrate(engine)
    sessions=sessionmaker(bind=engine)
    monkeypatch.setattr(importlib.import_module('animelab.services.library_service'),'SessionLocal',sessions)
    manager=DownloadManagerService()
    monkeypatch.setattr(manager,'broadcast_update',lambda task:None)
    task=DownloadTask(savePath=str(tmp_path/'video.mp4'),fileUrl='https://cdn.example/video.mp4')
    manager.tasks[task.id]=task;manager.task_order=[task.id]
    started=asyncio.Event()
    async def interrupted(*args):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(manager,'_download_single_file',interrupted)
    try:
        await manager.process_queue()
        await asyncio.wait_for(started.wait(),2)
        await manager.shutdown()
        assert library_service.get_task_entity(task.id).status=='PAUSED'
        restored=DownloadManagerService()
        monkeypatch.setattr(restored,'broadcast_update',lambda task:None)
        restored.init_from_db()
        assert restored.get_task(task.id).status==DownloadStatus.PAUSED
        assert not manager.scheduler.workers and not manager.scheduler.network_tasks
    finally:
        await manager.shutdown()
        engine.dispose()
