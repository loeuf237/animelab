"""Browser session exchange preserves concurrent changes and source boundaries."""
import asyncio
import json
import os
import time
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock

import httpx
import pytest

from animelab.services.source_http import SourceHTTPService
from animelab.services.verification_cookies import snapshot, merge
from animelab.browser_settings import VerificationSettings, executable
from animelab.services.browser_verification import BrowserVerificationService

URL = 'https://source.example/episode'


@pytest.fixture
def transport(tmp_path, monkeypatch):
    from animelab.services.proxy_service import proxy_service
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: None)
    value = SourceHTTPService(storage=tmp_path / 'sessions')
    yield value
    value.close()


def put(transport, name, value, **kwargs):
    transport.import_cookies(URL, [dict(name=name, value=value, domain='source.example', **kwargs)])


def test_three_way_sync_preserves_concurrent_engine_updates_and_cookie_deletions(transport):
    put(transport, 'session', 'old', httpOnly=True)
    put(transport, 'deleted', 'old')
    initial = snapshot(transport, URL)
    state = transport.state(URL)
    # A server response changed session while the browser was open.
    put(transport, 'session', 'new-engine')
    remote = [dict(v, value='stale-browser') for v in initial.values() if v['name'] == 'session']
    remote += [dict(name='clearance', value='browser-proof', domain='source.example', path='/', secure=True)]
    remote += [dict(name='private', value='unrelated', domain='other.example')]
    browser, engine, changed = merge(transport, URL, remote, initial, initial, (None, state.generation))
    assert changed and len(browser) == 2
    assert {v['name']: v['value'] for v in engine.values()} == {'session': 'new-engine', 'clearance': 'browser-proof'}
    assert all(v['domain'] == 'source.example' for v in engine.values())


def test_browser_changes_cannot_survive_proxy_rotation(transport):
    initial = snapshot(transport, URL)
    state = transport.state(URL)
    route = (state.proxy, state.generation)
    state.generation += 1
    from animelab.api_errors import APIProblem
    with pytest.raises(APIProblem) as caught:
        merge(transport, URL, [dict(name='access', value='secret')], initial, initial, route)
    assert caught.value.problem.code == 'verification_route_changed'
    assert not list(state.cookies)


def test_browser_scope_rejects_subdomains_and_cookie_injection(transport):
    state = transport.state(URL)
    values = [dict(name='good', value='yes', domain='.source.example'),
              dict(name='bad', value='no', domain='else.source.example'),
              dict(name='expired', value='no', expires=time.time() - 1),
              dict(name='inject', value='no\r\nCookie: bad'),
              dict(name='nan', value='no', expires=float('nan'))]
    _, engine, _ = merge(transport, URL, values, {}, {}, (None, state.generation))
    assert [v['name'] for v in engine.values()] == ['good']


@pytest.mark.asyncio
async def test_watcher_automatically_validates_resumes_and_exposes_completion(transport, tmp_path, monkeypatch):
    service = BrowserVerificationService(transport, VerificationSettings(tmp_path / 'browser.json'))
    state = transport.state(URL)
    state.blocked_url = URL
    put(transport, 'session', 'engine')
    initial = snapshot(transport, URL)
    mechanism = SimpleNamespace(cookies=AsyncMock(return_value=[*initial.values(), dict(name='cf_clearance', value='verified')]),
                                push=AsyncMock(), close=AsyncMock())
    service.mechanisms['test'] = mechanism
    service.jobs['test'] = dict(id='test', domain='source.example', url=URL, mode='test', created=time.monotonic(),
        routeProxy=None, routeGeneration=state.generation, browserCookies=initial, engineCookies=initial)
    calls = []
    service.verified_callback = lambda domain: calls.append(domain) or 2
    monkeypatch.setattr(transport, 'request', lambda method, url, **kw: httpx.Response(200, request=httpx.Request(method, url)))
    watcher = asyncio.create_task(service.watch())
    try:
        for _ in range(40):
            if service.status('test')['status'] == 'completed': break
            await asyncio.sleep(.1)
        assert service.status('test')['resumed'] == 2
        assert calls == ['source.example'] and state.blocked_url is None
        assert (await service.complete('test'))['resumed'] == 2
        assert calls == ['source.example']  # UI/manual completion race is idempotent.
    finally:
        watcher.cancel()
        with pytest.raises(asyncio.CancelledError): await watcher
        await service.close()


def test_browser_settings_validate_executables_and_environment_precedence(tmp_path, monkeypatch):
    monkeypatch.delenv('ANIMELAB_CHROMIUM_PATH', raising=False)
    monkeypatch.delenv('ANIMELAB_CHROMIUM_HEADLESS', raising=False)
    store = VerificationSettings(tmp_path / 'settings.json')
    with pytest.raises(ValueError): store.save(dict(chromiumPath='/missing/browser --args', headless=True))
    import sys
    value = store.save(dict(chromiumPath=sys.executable, headless=True))
    assert value['chromiumPath'] == str(Path(sys.executable).resolve()) and value['headless']
    assert VerificationSettings(store.path).snapshot() == value
    monkeypatch.setenv('ANIMELAB_CHROMIUM_PATH', '/operator/browser')
    assert store.snapshot()['managed'] and store.snapshot()['chromiumPath'] == '/operator/browser'
    with pytest.raises(ValueError, match='controlled'): store.save(dict(chromiumPath='', headless=False))
    for value in ('foo\nbar', None, '/tmp/browser\x00bad'):
        with pytest.raises(ValueError): executable(value)


@pytest.mark.asyncio
async def test_remote_clients_cannot_change_executable_or_read_browser_jobs(transport, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from animelab.routers.network import router
    service = BrowserVerificationService(transport, VerificationSettings(tmp_path / 'settings.json'))
    monkeypatch.setattr('animelab.routers.network.browser_verification', service)
    app = FastAPI(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('192.0.2.1', 1)), base_url='http://server') as client:
        assert (await client.get('/api/network/browser-settings')).status_code == 403
        assert (await client.post('/api/network/browser-settings', json=dict(chromiumPath='', headless=True))).status_code == 403
        assert (await client.get('/api/network/verification/test/status')).status_code == 403


@pytest.mark.asyncio
async def test_real_chromium_is_seeded_then_shares_cookies_both_ways_and_auto_resumes(tmp_path, monkeypatch):
    """A local challenge fixture exercises a real browser; no production CAPTCHA."""
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    import threading
    installed = BrowserVerificationService().installed_browsers()
    if not installed: pytest.skip('No installed Chromium-family browser')
    monkeypatch.delenv('ANIMELAB_CHROMIUM_PATH', raising=False)
    monkeypatch.delenv('ANIMELAB_CHROMIUM_HEADLESS', raising=False)
    seen = []
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            cookie = self.headers.get('Cookie', '')
            seen.append(cookie)
            verified = 'access=fixture' in cookie
            self.send_response(200 if verified else 403)
            self.send_header('Content-Type', 'text/html')
            if not verified: self.send_header('cf-mitigated', 'challenge')
            self.end_headers()
            script = '<script>document.cookie="access=fixture; Path=/; Max-Age=120"</script>' if 'session=engine-seed' in cookie else ''
            self.wfile.write(('<html>' + script + '</html>').encode())
        def log_message(self, *args): pass
    server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    base = f'http://127.0.0.1:{server.server_port}'
    import importlib
    browser_module = importlib.import_module('animelab.services.browser_verification')
    http_module = importlib.import_module('animelab.services.source_http')
    monkeypatch.setattr(browser_module, 'is_safe_url', lambda url: url.startswith(base))
    monkeypatch.setattr(http_module, 'is_safe_url', lambda url: url.startswith(base))
    from animelab.services.proxy_service import proxy_service
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: None)
    transport = SourceHTTPService(storage=tmp_path / 'sessions', min_interval=0)
    config = VerificationSettings(tmp_path / 'browser.json')
    config.save(dict(chromiumPath=installed[0]['path'], headless=True))
    service = BrowserVerificationService(transport, config)
    transport.import_cookies(base, [dict(name='session', value='engine-seed', secure=False)])
    callback = []
    service.verified_callback = lambda domain: callback.append(domain) or 1
    watcher = None
    try:
        with pytest.raises(Exception) as caught:
            await transport.async_client().get(base + '/episode')
        from animelab.services.source_http import VerificationRequired
        assert isinstance(caught.value, VerificationRequired)
        started = await service.start('127.0.0.1')
        job = service.jobs[started['id']]
        for _ in range(60):
            remote = await service.mechanisms['browser'].cookies(service, job)
            if any(c['name'] == 'access' for c in remote): break
            await asyncio.sleep(.1)
        assert any(c['name'] == 'session' and c['value'] == 'engine-seed' for c in remote)
        assert any(c['name'] == 'access' for c in remote)
        # Simulate a subsequent HTTP Set-Cookie, which does not change the proxy generation.
        state = transport.state(base)
        with state.condition:
            state.cookies.set_cookie(transport.cookie('127.0.0.1', 'refresh', 'from-http', secure=False))
        await service.synchronize(job)
        remote = await service.mechanisms['browser'].cookies(service, job)
        assert any(c['name'] == 'refresh' and c['value'] == 'from-http' for c in remote)
        assert any(c.name == 'access' and c.value == 'fixture' for c in state.cookies)
        watcher = asyncio.create_task(service.watch())
        for _ in range(100):
            if service.status(started['id'])['status'] == 'completed': break
            await asyncio.sleep(.1)
        assert service.status(started['id'])['status'] == 'completed'
        assert callback == ['127.0.0.1'] and state.blocked_url is None
        assert any('session=engine-seed' in cookies and 'access=fixture' in cookies for cookies in seen)
    finally:
        if watcher:
            watcher.cancel()
            with pytest.raises(asyncio.CancelledError): await watcher
        await service.close()
        transport.close()
        server.shutdown(); server.server_close()


def test_android_bridge_seeds_http_only_cookies_and_keeps_expiry_stable():
    from android_runtime import VerificationWindow
    headers, order = [], []
    bridge = SimpleNamespace(setCookies=lambda url, data: (headers.extend(json.loads(data)), order.append('seed')),
        open=lambda url, ua: order.append('open'), cookies=lambda url: 'session=seed; clearance=browser', close=lambda url: None)
    seed = dict(name='session', value='seed', domain='source.example', path='/', secure=True,
                httpOnly=True, expires=time.time() + 120)
    VerificationWindow.seed_cookies(URL, [seed], bridge)
    window = VerificationWindow(URL, bridge)
    assert order == ['seed', 'open'] and 'HttpOnly' in headers[0] and 'Secure' in headers[0]
    first = window.get_cookie_records()
    assert first[0] == seed
    assert window.get_cookie_records() == first
    window.set_cookies([dict(seed, value='refreshed')])
    assert 'refreshed' in headers[-1]


def test_launcher_and_cli_propagate_the_operator_browser(tmp_path, monkeypatch):
    import argparse
    import sys
    from animelab.desktop.options import normalize_config, engine_environment
    from animelab.browser_settings import add_browser_arguments, apply_browser_arguments
    monkeypatch.setenv('ANIMELAB_CHROMIUM_PATH', '')
    monkeypatch.setenv('ANIMELAB_CHROMIUM_HEADLESS', 'false')
    parser = argparse.ArgumentParser()
    add_browser_arguments(parser)
    args = parser.parse_args(['--chromium-path', sys.executable, '--chromium-headless'])
    apply_browser_arguments(args)
    assert os.environ['ANIMELAB_CHROMIUM_HEADLESS'] == 'true'
    config = normalize_config(dict(port=8080, browser=True, launcher=dict(chromiumPath=args.chromium_path, chromiumHeadless=True)))
    env = engine_environment(config)
    assert env['ANIMELAB_CHROMIUM_PATH'] == str(Path(sys.executable).resolve())
    assert env['ANIMELAB_CHROMIUM_HEADLESS'] == 'true'


@pytest.mark.asyncio
async def test_local_browser_settings_persist_and_refuse_changes_during_verification(transport, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from animelab.routers.network import router
    monkeypatch.delenv('ANIMELAB_CHROMIUM_PATH', raising=False)
    monkeypatch.delenv('ANIMELAB_CHROMIUM_HEADLESS', raising=False)
    service = BrowserVerificationService(transport, VerificationSettings(tmp_path / 'settings.json'))
    monkeypatch.setattr('animelab.routers.network.browser_verification', service)
    app = FastAPI(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('127.0.0.1', 1)), base_url='http://server') as client:
        response = await client.post('/api/network/browser-settings', json=dict(chromiumPath='', headless=True))
        assert response.status_code == 200 and response.json()['headless'] is True
        assert (await client.get('/api/network/browser-settings')).json()['headless'] is True
        service.jobs['open'] = {}
        assert (await client.post('/api/network/browser-settings', json=dict(chromiumPath='', headless=False))).status_code == 409


@pytest.mark.asyncio
async def test_headless_account_client_can_verify_but_cannot_configure_host_executables(transport, tmp_path, monkeypatch):
    from fastapi import FastAPI
    from animelab.routers.network import router
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    monkeypatch.setenv('ANIMELAB_CHROMIUM_HEADLESS', 'true')
    service = BrowserVerificationService(transport, VerificationSettings(tmp_path / 'settings.json'))
    monkeypatch.setattr(service, 'installed_browsers', lambda: [dict(name='operator-chromium', path='/operator/chromium')])
    service.completed['test'] = {'created': time.monotonic(), 'result': {'success': True, 'domain': 'source.example'}}
    monkeypatch.setattr('animelab.routers.network.browser_verification', service)
    app = FastAPI(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('127.0.0.1', 1)), base_url='http://server') as client:
        options = (await client.get('/api/network/sessions')).json()
        browser = next(mode for mode in options['modes'] if mode['id'] == 'browser')
        assert browser['available'] and browser['headless']
        assert (await client.get('/api/network/verification/test/status')).json()['status'] == 'completed'
        assert (await client.post('/api/network/browser-settings', json=dict(chromiumPath='/other', headless=True))).status_code == 403


def test_verification_does_not_resume_downloads_for_read_only_accounts(monkeypatch):
    from animelab.services.download_manager import DownloadManagerService
    monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
    monkeypatch.setenv('ANIMELAB_SHARED_DOWNLOAD', '0')
    manager = DownloadManagerService()
    from animelab.models.download_task import DownloadStatus
    manager.tasks['blocked'] = SimpleNamespace(id='blocked', status=DownloadStatus.VERIFICATION_REQUIRED, verificationUrl=URL)
    monkeypatch.setattr(manager, 'resume_download', lambda identity: pytest.fail('Read-only account resumed a download'))
    assert manager.resume_verified_domain('source.example') == 0


def test_webview_exchange_does_not_remove_cookies_outside_the_visible_url(transport):
    put(transport, 'account', 'hidden', path='/account')
    put(transport, 'access', 'visible', path='/')
    initial = snapshot(transport, URL, visible_only=True)
    assert [item['name'] for item in initial.values()] == ['access']
    state = transport.state(URL)
    merge(transport, URL, [], initial, initial, (state.proxy, state.generation), visible_only=True)
    assert [cookie.name for cookie in state.cookies] == ['account']


def test_android_preserves_seeded_cookie_paths_on_refresh_and_ambiguous_names():
    from android_runtime import VerificationWindow
    bridge = SimpleNamespace(setCookies=lambda *args: None, open=lambda *args: None,
        cookies=lambda url: 'session=renewed', close=lambda *args: None)
    cookies = [dict(name='session', value='old', domain='source.example', path='/episode', secure=True, expires=None)]
    VerificationWindow.seed_cookies(URL, cookies, bridge)
    window = VerificationWindow(URL, bridge)
    assert window.get_cookie_records()[0]['path'] == '/episode'
    duplicate = dict(cookies[0], path='/', value='separate')
    window.set_cookies([duplicate])
    assert {item['path'] for item in window.get_cookie_records()} == {'/', '/episode'}


def test_browser_sync_preserves_http_only_same_site_and_path(transport):
    state = transport.state(URL)
    merge(transport, URL, [dict(name='secure-session', value='proof', path='/episode',
        secure=True, httpOnly=True, sameSite='Strict')], {}, {}, (None, state.generation))
    item = next(iter(snapshot(transport, URL).values()))
    assert item['httpOnly'] and item['sameSite'] == 'Strict' and item['path'] == '/episode'


@pytest.mark.asyncio
async def test_completion_remains_readable_while_browser_closes(transport, tmp_path, monkeypatch):
    service = BrowserVerificationService(transport, VerificationSettings(tmp_path / 'browser.json'))
    state = transport.state(URL)
    state.blocked_url = URL
    initial = snapshot(transport, URL)
    closing, release = asyncio.Event(), asyncio.Event()
    async def slow_close(job):
        closing.set()
        await release.wait()
    service.mechanisms['test'] = SimpleNamespace(cookies=AsyncMock(return_value=[]), push=AsyncMock(), close=slow_close)
    service.jobs['test'] = dict(id='test', domain='source.example', url=URL, mode='test', created=time.monotonic(),
        routeProxy=None, routeGeneration=state.generation, browserCookies=initial, engineCookies=initial)
    monkeypatch.setattr(transport, 'request', lambda method, url, **kw: httpx.Response(200, request=httpx.Request(method, url)))
    job = asyncio.create_task(service.complete('test'))
    try:
        await asyncio.wait_for(closing.wait(), 3)
        assert service.status('test')['status'] == 'completed'
    finally:
        release.set()
        assert (await job)['success']
        await service.close()
