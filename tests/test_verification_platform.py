from http.cookies import SimpleCookie
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI

from animelab.api_errors import APIProblem
from animelab.services.browser_verification import BrowserVerificationService
from animelab.services.source_http import SourceHTTPService


@pytest.fixture
def service(tmp_path, monkeypatch):
    transport = SourceHTTPService(storage=tmp_path)
    monkeypatch.setenv('DISPLAY', ':test')
    browser = BrowserVerificationService(transport)
    monkeypatch.setattr(browser, 'installed_browsers', lambda: [{'name': 'chromium', 'path': '/fake/chromium'}])
    browser.webview_opener = lambda url: type('Window', (), {
        'get_cookies': lambda self: [SimpleCookie('cf_clearance=test')], 'destroy': lambda self: None})()
    state = transport.state('https://source.example/anime')
    state.proxy = None
    state.blocked_url = 'https://source.example/anime'
    yield browser, state
    transport.close()


@pytest.mark.parametrize('platform,local,proxy,browser_ok,webview_ok', [
    ('desktop', True, None, True, True),
    ('desktop', True, 'http://proxy.example:8080', True, False),
    ('desktop', True, 'http://user:secret@proxy.example:8080', False, False),
    ('desktop', False, None, False, False),
    ('android', True, None, False, True),
    ('android', True, 'http://proxy.example:8080', False, False),
    ('android', False, None, False, False),
])
def test_platform_route_matrix(service, platform, local, proxy, browser_ok, webview_ok):
    browser, state = service
    browser.platform, state.proxy = platform, proxy
    modes = {mode['id']: mode for mode in browser.modes(state, client_local=local)}
    assert modes['browser']['available'] is browser_ok
    assert modes['webview']['available'] is webview_ok
    assert modes['manual']['available'] and not modes['manual']['capturesCookies']
    for name in ('browser', 'webview'):
        assert modes[name]['available'] or modes[name]['reason']


@pytest.mark.asyncio
async def test_unsupported_mode_does_not_open_window(service, monkeypatch):
    browser, state = service
    state.proxy = 'http://proxy.example:8080'
    opener = AsyncMock()
    monkeypatch.setattr(browser.mechanisms['webview'], 'open', opener)
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url', lambda url: True)
    with pytest.raises(APIProblem):
        await browser.start('source.example', mode='webview')
    opener.assert_not_called()


@pytest.mark.asyncio
async def test_route_change_never_imports_cookies_or_clears_challenge(service, monkeypatch):
    browser, state = service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url', lambda url: True)
    job = await browser.start('source.example', mode='webview')
    state.generation += 1  # An automatic rotation/reconfiguration happened.
    importer = AsyncMock()
    monkeypatch.setattr(browser.transport, 'import_cookies', importer)
    with pytest.raises(APIProblem) as caught:
        await browser.complete(job['id'])
    assert caught.value.problem.code == 'verification_route_changed'
    assert state.blocked_url
    importer.assert_not_called()
    await browser.close()


@pytest.mark.asyncio
async def test_webview_captures_without_a_probe_and_duplicate_complete_is_idempotent(service, monkeypatch):
    browser, state = service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url', lambda url: True)
    def unexpected_request(*args,**kwargs):
        pytest.fail('WebView completion must not send an emulated HTTP probe')
    monkeypatch.setattr(browser.transport, 'request', unexpected_request)
    job = await browser.start('source.example', mode='webview')
    result=await browser.complete(job['id'])
    assert result['success'] and result['sessionImported'] and result['accessVerified'] is False
    assert state.blocked_url is None
    assert [cookie.name for cookie in state.cookies] == ['cf_clearance']
    assert (await browser.complete(job['id']))['success']
    assert browser.status(job['id'])['status'] == 'completed'


@pytest.mark.asyncio
async def test_webview_watcher_never_probes_or_resumes_while_the_window_is_open(service,monkeypatch):
    import asyncio
    browser,state=service
    window=type('Window',(),{
        'closed':False,'get_cookies':lambda self:[SimpleCookie('cf_clearance=fresh')],
        'is_closed':lambda self:self.closed,'destroy':lambda self:setattr(self,'closed',True)})()
    browser.webview_opener=lambda url:window
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url',lambda url:True)
    def unexpected_request(*args,**kwargs):
        pytest.fail('The watcher issued an upstream probe')
    monkeypatch.setattr(browser.transport,'request',unexpected_request)
    resumed=[]
    def resume(domain):
        assert window.closed and state.verification_owner is None
        resumed.append(domain)
        return 1
    browser.verified_callback=resume
    job=await browser.start('source.example',mode='webview')
    watcher=asyncio.create_task(browser.watch())
    try:
        await asyncio.sleep(1.15)
        assert browser.status(job['id'])['status']=='pending'
        assert state.blocked_url and state.verification_owner==job['id'] and not resumed
        assert [cookie.value for cookie in state.cookies]==['fresh']
        # Return/back in the actual app closes the window before a pending source resumes.
        window.closed=True
        for _ in range(25):
            if browser.status(job['id'])['status']=='completed':
                break
            await asyncio.sleep(.1)
        assert browser.status(job['id'])['accessVerified'] is False and resumed==['source.example']
    finally:
        watcher.cancel()
        with pytest.raises(asyncio.CancelledError):
            await watcher
        await browser.close()


@pytest.mark.asyncio
async def test_webview_drains_active_handles_before_navigation_and_cancel_releases_gate(service,monkeypatch):
    import asyncio
    browser,state=service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url',lambda url:True)
    opened=[]
    old=browser.webview_opener
    browser.webview_opener=lambda url:opened.append(url) or old(url)
    with state.condition:
        state.leased=1
    opening=asyncio.create_task(browser.start('source.example',mode='webview'))
    try:
        for _ in range(25):
            if state.verification_owner:
                break
            await asyncio.sleep(.01)
        assert state.verification_owner and not opened
        with state.condition:
            state.leased=0
            state.condition.notify_all()
        job=await opening
        assert opened
        await browser.cancel(job['id'])
        assert state.verification_owner is None and state.blocked_url
    finally:
        with state.condition:
            state.leased=0
            state.condition.notify_all()
        await browser.close()


@pytest.mark.asyncio
@pytest.mark.parametrize('bounded',[False,True])
async def test_webview_gate_blocks_even_explicit_challenge_probes_before_network_io(service,monkeypatch,bounded):
    browser,state=service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url',lambda url:True)
    monkeypatch.setattr('animelab.services.source_http.is_safe_url',lambda url:True)
    job=await browser.start('source.example',mode='webview')
    def no_session(**kwargs):
        pytest.fail('An emulated HTTP session was created while the WebView was open')
    monkeypatch.setattr(browser.transport,'session_factory',no_session)
    from animelab.services.source_http import VerificationRequired
    try:
        with pytest.raises(VerificationRequired):
            if bounded:
                async with browser.transport.async_client().stream('GET',state.blocked_url,verify_challenge=True):
                    pass
            else:
                await browser.transport.async_client().get(state.blocked_url,verify_challenge=True)
        # A stale job cannot release the current owner's gate.
        browser.transport.release_webview(state.blocked_url,'other-job')
        assert state.verification_owner==job['id']
        assert browser.transport.rotate_proxy(state.domain,automatic=True) is False
        with pytest.raises(ValueError,match='WebView'):
            browser.transport.rotate_proxy(state.domain)
    finally:
        await browser.cancel(job['id'])


def test_webview_drain_timeout_does_not_leave_a_session_locked(service):
    browser,state=service
    state.leased=1
    try:
        with pytest.raises(ValueError,match='requêtes en cours'):
            browser.transport.pause_for_webview(state.blocked_url,'job',timeout=.001)
        assert state.verification_owner is None
    finally:
        state.leased=0


@pytest.mark.asyncio
async def test_failed_native_close_keeps_the_gate_and_job_until_close_is_confirmed(service,monkeypatch):
    browser,state=service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url',lambda url:True)
    job=await browser.start('source.example',mode='webview')
    close=AsyncMock(side_effect=RuntimeError('Native window is still active'))
    monkeypatch.setattr(browser.mechanisms['webview'],'close',close)
    with pytest.raises(RuntimeError):
        await browser.cancel(job['id'])
    assert job['id'] in browser.jobs and state.verification_owner==job['id']
    assert state.blocked_url
    close.side_effect=None
    await browser.cancel(job['id'])
    assert job['id'] not in browser.jobs and state.verification_owner is None


@pytest.mark.asyncio
async def test_partial_open_with_failed_close_remains_owned_until_cleanup_succeeds(service,monkeypatch):
    browser,state=service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url',lambda url:True)
    mechanism=browser.mechanisms['webview']
    monkeypatch.setattr(mechanism,'open',AsyncMock(side_effect=ValueError('Partial native open')))
    close=AsyncMock(side_effect=RuntimeError('Native shutdown not confirmed'))
    monkeypatch.setattr(mechanism,'close',close)
    with pytest.raises(RuntimeError):
        await browser.start('source.example',mode='webview')
    job=next(iter(browser.jobs.values()))
    assert job['openingFailed'] and state.verification_owner==job['id']
    close.side_effect=None
    await browser.cancel(job['id'])
    assert not browser.jobs and state.verification_owner is None


def test_cancelled_drain_cannot_later_claim_an_orphaned_gate(service):
    import threading
    browser,state=service
    cancelled=threading.Event()
    cancelled.set()
    with pytest.raises(ValueError,match='annulée'):
        browser.transport.pause_for_webview(state.blocked_url,'old-job',cancelled=cancelled)
    assert state.verification_owner is None


@pytest.mark.asyncio
async def test_remote_client_options_do_not_offer_server_windows(service, monkeypatch):
    from animelab.routers.network import router
    browser, _ = service
    monkeypatch.setattr('animelab.routers.network.browser_verification', browser)
    app = FastAPI(); app.include_router(router)
    transport = httpx.ASGITransport(app, client=('192.0.2.1', 54321))
    async with httpx.AsyncClient(transport=transport, base_url='http://server') as client:
        options = (await client.get('/api/network/sessions')).json()
        assert not options['clientLocal'] and not options['browsers']
        assert all(not mode['available'] for mode in options['modes'] if mode['id'] != 'manual')
        assert (await client.post('/api/network/verification', json={'domain': 'source.example', 'mode': 'webview'})).status_code == 403
