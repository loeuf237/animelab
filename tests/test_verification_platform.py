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
async def test_webview_captures_then_rechecks_and_duplicate_complete_is_idempotent(service, monkeypatch):
    browser, state = service
    monkeypatch.setattr('animelab.services.browser_verification.is_safe_url', lambda url: True)
    monkeypatch.setattr(browser.transport, 'request', lambda method, url, **kwargs: httpx.Response(200, request=httpx.Request(method, url)))
    job = await browser.start('source.example', mode='webview')
    assert (await browser.complete(job['id']))['success']
    assert state.blocked_url is None
    assert [cookie.name for cookie in state.cookies] == ['cf_clearance']
    assert (await browser.complete(job['id']))['success']
    assert browser.status(job['id'])['status'] == 'completed'


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
