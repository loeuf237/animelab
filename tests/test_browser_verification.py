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
    service._cdp = AsyncMock(return_value={'userAgent': 'Real browser UA', 'cookies':[
        {'domain':'source.example','name':'cf_clearance','value':'private','expires':time.time()+120},
        {'domain':'other.example','name':'account','value':'unrelated'},
    ]})
    yield service, transport, state
    transport.close()


@pytest.mark.asyncio
async def test_completion_imports_scoped_cookies_without_an_emulated_probe(verification, monkeypatch):
    service, transport, state = verification
    calls=[]
    def request(method,url,**kwargs):
        calls.append((method,url,kwargs))
        return httpx.Response(200,request=httpx.Request(method,url))
    monkeypatch.setattr(transport,'request',request)
    result=await service.complete('job')
    assert result=={'success':True,'domain':'source.example','sessionImported':True,'accessVerified':False}
    assert state.blocked_url is None
    assert [cookie.name for cookie in state.cookies]==['cf_clearance']
    assert calls == []
    assert 'job' not in service.jobs


@pytest.mark.asyncio
async def test_cookie_transfer_failure_keeps_downloads_blocked(verification):
    service, transport, state = verification
    service._cdp.side_effect = ValueError('Cookie exchange failed')
    with pytest.raises(ValueError, match='Cookie exchange failed'):
        await service.complete('job')
    assert state.blocked_url and 'job' in service.jobs


@pytest.mark.asyncio
async def test_shutdown_failure_does_not_resume_the_source(verification, monkeypatch):
    service, transport, state = verification
    monkeypatch.setattr(service.mechanisms['browser'], 'close', AsyncMock(side_effect=OSError('shutdown failed')))
    with pytest.raises(OSError, match='shutdown failed'):
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
    observed = []
    browser_ua = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            # Chrome can fetch /favicon.ico after its initial page has loaded.
            # Measure the blocked source operation, independently of those real
            # browser requests; the unit probe test covers every transport URL.
            if self.path == '/episode':
                observed.append((self.path, self.headers.get('User-Agent')))
            if self.path == '/verify': browser_ua.append(self.headers.get('User-Agent'))
            verified=self.path=='/verify' or ('access=local-test' in self.headers.get('Cookie','') and self.headers.get('User-Agent') in browser_ua)
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
        identity = await service._cdp(service.jobs['real'], 'Browser.getVersion')
        transport.adopt_browser_identity(base, identity['userAgent'])
        transport.pause_for_webview(base, 'real')
        before = len(observed)
        with pytest.raises(VerificationRequired):
            await transport.async_client().get(base+'/episode', verify_challenge=True)
        assert len(observed) == before
        result=await service.complete('real')
        assert len(observed) == before and process.poll() is not None
        assert transport.state(base).user_agent in browser_ua
        assert result['success'] and transport.state(base).blocked_url is None
        assert (await transport.async_client().get(base+'/episode')).status_code==200
    finally:
        await service.close()
        transport.close()
        server.shutdown()
        server.server_close()


@pytest.mark.asyncio
async def test_compact_chromium_app_args_and_auto_close_detection(tmp_path, monkeypatch):
    import importlib
    from animelab.services.verification_platform import ChromiumVerification

    platform_mod = importlib.import_module('animelab.services.verification_platform')
    browser_mod = importlib.import_module('animelab.services.browser_verification')
    transport = SourceHTTPService(storage=tmp_path / 'cookies', min_interval=0)
    service = BrowserVerificationService(transport)
    state = transport.state('https://source.example/episode')
    state.blocked_url = 'https://source.example/episode'

    launched_args = []
    proc = MagicMock()
    proc.poll.return_value = None
    proc.wait.return_value = 0

    def fake_popen(args, **kwargs):
        launched_args.append(list(args))
        return proc

    service._cdp = AsyncMock(side_effect=lambda job, cmd, params=None: (
        {'userAgent': 'Chrome/130'} if cmd == 'Browser.getVersion'
        else {'targetInfos': [{'targetId': 't1', 'type': 'page', 'url': 'about:blank'}]} if cmd == 'Target.getTargets'
        else {'cookies': []}
    ))
    navigated = []

    async def fake_nav(job, target_id, url):
        navigated.append((target_id, url))
        return True

    service._cdp_navigate = fake_nav
    monkeypatch.setattr(service, 'installed_browsers', lambda: [{'name': 'chrome', 'path': '/fake/chrome'}])
    monkeypatch.setattr(browser_mod, 'is_safe_url', lambda url: True)
    monkeypatch.setattr(platform_mod.subprocess, 'Popen', fake_popen)
    monkeypatch.setenv('DISPLAY', ':0')
    monkeypatch.setattr(service.configuration, 'snapshot', lambda: {'chromiumPath': '', 'headless': False})

    started = await service.start('source.example', mode='browser')
    assert '--app=about:blank' in launched_args[0]
    assert '--window-size=920,740' in launched_args[0]
    assert '--new-window' not in launched_args[0]
    assert navigated == [('t1', 'https://source.example/episode')]

    job = service.jobs[started['id']]
    job['created'] = time.monotonic() - 5.0
    job['capturedCookies'] = [{'name': 'cf_clearance', 'value': 'fresh', 'domain': '.source.example', 'path': '/'}]

    # First tick sees challenge title -> does not auto-close
    service._cdp = AsyncMock(return_value={'targetInfos': [{'targetId': 't1', 'type': 'page', 'url': 'https://source.example/episode', 'title': 'Just a moment...'}]})
    assert await ChromiumVerification.ready_to_auto_close(service, job) is False

    # Two consecutive clean non-challenge ticks with cf_clearance -> auto-closes
    service._cdp = AsyncMock(return_value={'targetInfos': [{'targetId': 't1', 'type': 'page', 'url': 'https://source.example/episode', 'title': 'Anime Catalogue'}]})
    assert await ChromiumVerification.ready_to_auto_close(service, job) is False
    assert await ChromiumVerification.ready_to_auto_close(service, job) is True

    await service.close()
    transport.close()
