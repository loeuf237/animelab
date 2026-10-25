import time
import asyncio
from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from animelab.services.browser_verification import BrowserVerificationService
from animelab.services.source_http import SourceHTTPService, VerificationRequired
from animelab.services.proxy_service import proxy_service


@pytest.fixture
def verification(tmp_path, monkeypatch):
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: None)
    transport = SourceHTTPService(storage=tmp_path)
    service = BrowserVerificationService(transport)
    state = transport.state('https://source.example/episode')
    state.blocked_url = 'https://source.example/episode'
    service.jobs['job'] = {'id':'job','domain':'source.example','url':state.blocked_url,
                           'created':time.monotonic(),'mode':'browser','process':None,'window':None}
    service._cdp = AsyncMock(return_value={'cookies':[
        {'domain':'source.example','name':'cf_clearance','value':'private','expires':time.time()+120},
        {'domain':'other.example','name':'account','value':'unrelated'},
    ]})
    yield service, transport, state
    transport.close()


@pytest.mark.asyncio
async def test_completion_imports_only_domain_cookies_and_checks_response(verification, monkeypatch):
    service, transport, state = verification
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return httpx.Response(200,request=httpx.Request(method,url))
    monkeypatch.setattr(transport,'request',request)
    result=await service.complete('job')
    assert result=={'success':True,'domain':'source.example'}
    assert state.blocked_url is None
    assert [cookie.name for cookie in state.cookies]==['cf_clearance']
    assert calls[0][2]['verify_challenge'] and calls[0][2]['bypass_cache']
    assert 'job' not in service.jobs


@pytest.mark.asyncio
async def test_failed_verification_keeps_downloads_blocked(verification,monkeypatch):
    service, transport, state = verification
    def request(*args,**kwargs): raise VerificationRequired('https://source.example/episode')
    monkeypatch.setattr(transport,'request',request)
    with pytest.raises(VerificationRequired): await service.complete('job')
    assert state.blocked_url and 'job' in service.jobs


@pytest.mark.asyncio
@pytest.mark.parametrize('status', [403, 500])
async def test_ordinary_refusal_keeps_verification_pending(verification, monkeypatch, status):
    service, transport, state = verification
    monkeypatch.setattr(transport, 'request', lambda method, url, **kwargs:
                        httpx.Response(status, request=httpx.Request(method, url)))
    with pytest.raises(ValueError, match=f'HTTP {status}'):
        await service.complete('job')
    assert state.blocked_url and 'job' in service.jobs


@pytest.mark.asyncio
async def test_expired_verification_is_cleaned_up(verification):
    service, transport, state = verification
    service.jobs['job']['created']-=601
    await service.expire()
    assert not service.jobs
    assert state.blocked_url


@pytest.mark.asyncio
async def test_verification_cannot_open_an_arbitrary_domain(verification):
    service, transport, state = verification
    with pytest.raises(ValueError,match='Aucune vérification'):
        await service.start('not-challenged.example')


@pytest.mark.asyncio
async def test_closed_browser_can_be_reopened(verification, monkeypatch):
    import importlib
    module = importlib.import_module('animelab.services.browser_verification')
    service, transport, state = verification
    old = MagicMock()
    old.poll.return_value = 0
    service.jobs['job']['process'] = old
    new = MagicMock()
    new.poll.return_value = None
    new.wait.return_value = 0
    monkeypatch.setattr(service, 'installed_browsers', lambda: [{'name': 'installed', 'path': '/fake/browser'}])
    monkeypatch.setattr(module, 'is_safe_url', lambda url: True)
    monkeypatch.setattr(importlib.import_module('animelab.services.verification_platform').subprocess, 'Popen', lambda *args, **kwargs: new)
    monkeypatch.setenv('DISPLAY', ':test')
    job = await service.start('SOURCE.EXAMPLE')
    assert job['domain'] == 'source.example' and job['id'] != 'job'
    assert 'job' not in service.jobs and service.jobs[job['id']]['process'] is new
    await service.close()


def test_download_resume_requires_validated_domain(verification, monkeypatch):
    from animelab.services.download_manager import DownloadManagerService, library_service
    from animelab.models.download_task import DownloadTask, DownloadStatus
    import importlib
    module=importlib.import_module('animelab.services.download_manager')
    service, transport, state = verification
    manager=DownloadManagerService()
    task=DownloadTask(status=DownloadStatus.VERIFICATION_REQUIRED,verificationUrl=state.blocked_url)
    manager.tasks[task.id]=task
    monkeypatch.setattr(module,'source_http',transport)
    monkeypatch.setattr(library_service,'save_task',lambda task:None)
    monkeypatch.setattr(manager,'_trigger_process_queue',lambda:None)
    assert manager.resume_download(task.id) is False
    assert task.status==DownloadStatus.VERIFICATION_REQUIRED
    state.blocked_url=None
    assert manager.resume_verified_domain('other.example')==0
    assert manager.resume_verified_domain('source.example')==1
    assert task.status==DownloadStatus.PENDING and task.verificationUrl is None

@pytest.mark.asyncio
async def test_installed_chrome_cookie_exchange_with_local_server(tmp_path, monkeypatch):
    """Exercise CDP and cookie transfer with a local simulated challenge only."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import subprocess
    import threading
    browser = next(iter(BrowserVerificationService().installed_browsers()), None)
    if not browser:
        pytest.skip('No installed Chrome-family browser')
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            verified=self.path=='/verify' or 'access=local-test' in self.headers.get('Cookie','')
            self.send_response(200 if verified else 403)
            if self.path=='/verify': self.send_header('Set-Cookie','access=local-test; Max-Age=120; Path=/')
            if not verified: self.send_header('cf-mitigated','challenge')
            self.send_header('Content-Type','text/html')
            self.end_headers()
            self.wfile.write(b'<html>local fixture</html>')
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    threading.Thread(target=server.serve_forever,daemon=True).start()
    base=f'http://127.0.0.1:{server.server_port}'
    monkeypatch.setattr('animelab.services.source_http.is_safe_url',lambda url:url.startswith(base+'/'))
    monkeypatch.setattr(proxy_service,'get_random_proxy',lambda:None)
    transport=SourceHTTPService(storage=tmp_path/'cookies',min_interval=0)
    service=BrowserVerificationService(transport)
    profile=tmp_path/'profile'
    profile.mkdir()
    browser_log=tmp_path/'browser-startup.log'
    with browser_log.open('wb') as stderr:
        process=subprocess.Popen([browser['path'],'--headless=new',f'--user-data-dir={profile}',
            '--remote-debugging-port=0','--remote-debugging-address=127.0.0.1','--no-first-run',
            '--no-default-browser-check','--disable-background-networking',base+'/verify'],
            stdout=subprocess.DEVNULL,stderr=stderr)
    service.jobs['real']={'id':'real','domain':'127.0.0.1','url':base+'/episode','created':time.monotonic(),
        'mode':'browser','process':process,'window':None,'port_file':profile/'DevToolsActivePort'}
    try:
        with pytest.raises(VerificationRequired): await transport.async_client().get(base+'/episode')
        # A cold browser on a shared runner may take longer than a normal CDP
        # command's readiness budget. Wait for startup explicitly, retaining
        # diagnostics instead of skipping or weakening the browser sandbox.
        deadline=time.monotonic()+30
        port_file=profile/'DevToolsActivePort'
        while time.monotonic()<deadline:
            if process.poll() is not None:
                pytest.fail('Browser exited during startup: '+browser_log.read_text(errors='replace')[-3000:])
            if port_file.exists() and len(port_file.read_text().splitlines())>=2:
                break
            await asyncio.sleep(0.1)
        else:
            pytest.fail('Browser startup timed out: '+browser_log.read_text(errors='replace')[-3000:])
        # The local fixture page sets a cookie; no production challenge is automated.
        for _ in range(30):
            cookies=(await service._cdp(service.jobs['real'],'Storage.getCookies')).get('cookies',[])
            if any(c['name']=='access' for c in cookies): break
            await asyncio.sleep(0.1)
        assert any(c['name']=='access' for c in cookies)
        result=await service.complete('real')
        assert result['success'] and transport.state(base).blocked_url is None
        assert (await transport.async_client().get(base+'/episode')).status_code==200
    finally:
        await service.close()
        transport.close()
        server.shutdown()
        server.server_close()
