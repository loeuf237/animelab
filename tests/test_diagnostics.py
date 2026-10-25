"""A10: no arbitrary payload in exports, bounded memory and redacted log records."""
import json
import logging
from types import SimpleNamespace
import httpx
import pytest
from animelab.diagnostics import Telemetry,install_logging,remember_secret,redact_text
from animelab.models.download_task import DownloadStatus


def test_structured_events_are_bounded_and_fields_are_allowlisted():
    recorder=Telemetry(capacity=3)
    for i in range(6):
        recorder.event('source_request',taskId='task-1',source='source',domain='example.org',durationMs=i,
                       cookie='private-cookie',url='https://user:password@example.org/private?token=token',error='private-error')
    rows=recorder.snapshot()
    assert len(rows)==3 and rows[-1]['durationMs']==5
    assert set(rows[-1])=={'time','event','taskId','source','domain','durationMs'}
    assert 'private' not in json.dumps(rows)


def test_phase_durations_only_on_transition(monkeypatch):
    recorder=Telemetry()
    task=SimpleNamespace(id='task',source='source',phase='transfer',status=DownloadStatus.DOWNLOADING,
                         verificationUrl=None,directDownloadUrl='https://host.example/video?key=secret',fileUrl='')
    import animelab.diagnostics as module
    ticks=iter([10,12,15]);monkeypatch.setattr(module.time,'monotonic',lambda:next(ticks))
    recorder.task_phase(task);recorder.task_phase(task)
    task.phase='mux';recorder.task_phase(task)
    assert [r['event'] for r in recorder.snapshot()]==['phase_started','phase_finished','phase_started']
    assert recorder.snapshot()[1]['durationMs']==5000


def test_logs_mask_headers_proxy_credentials_loopback_and_tracebacks():
    remember_secret('loopback-12345');remember_secret('proxy-password-12345')
    for text in ['Cookie: cf_clearance=private','Authorization: Bearer private','password=private']:
        assert 'private' not in redact_text(text)
    logger=logging.getLogger('test-diagnostics');previous=logging.getLogRecordFactory()
    install_logging()
    try:
        record=logger.makeRecord(logger.name,logging.INFO,'test',1,'GET %s %s %s',
            ('https://user:proxy-password-12345@source.example/path?token=private','loopback-12345','proxy-password-12345'),None)
        message=record.getMessage()
        assert 'loopback-12345' not in message and 'proxy-password-12345' not in message and 'private' not in message
        assert 'source.example' in message
        access=logging.getLogger('uvicorn.access').makeRecord('uvicorn.access',logging.INFO,'test',1,'%s - "%s %s HTTP/%s" %d',('local','GET','/api/image?url=private','1.1',200),None)
        assert len(access.args)==5 and 'private' not in access.getMessage()
        try: raise ValueError('Cookie: private')
        except ValueError:
            import sys
            exception=logger.makeRecord(logger.name,logging.ERROR,'test',1,'failed',(),sys.exc_info())
        assert 'private' not in (exception.exc_text or '')
    finally: logging.setLogRecordFactory(previous)


@pytest.mark.asyncio
async def test_export_is_local_only_and_excludes_raw_download_data(monkeypatch):
    import importlib
    from fastapi import FastAPI
    from animelab.routers.diagnostics import router
    module=importlib.import_module('animelab.services.download_manager')
    monkeypatch.setattr(module.download_manager,'tasks',{'secret':SimpleNamespace(status=DownloadStatus.COMPLETED,error='Cookie: private',fileUrl='https://private.example')})
    app=FastAPI();app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('127.0.0.1',123)),base_url='http://local') as client:
        response=await client.get('/api/diagnostics/export')
        assert response.status_code==200 and response.headers['cache-control']=='no-store'
        assert response.json()['taskCounts']=={'COMPLETED':1}
        assert 'private' not in response.text and 'fileUrl' not in response.text and 'settings' not in response.text
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app,client=('192.0.2.1',123)),base_url='http://remote') as client:
        assert (await client.get('/api/diagnostics/export')).status_code==403
