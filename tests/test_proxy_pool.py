import asyncio
import json
import time

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from animelab.services.proxy_service import ProxyService
from animelab.services.proxy_pool import ProxyPool, PROVIDERS, HEALTH_TTL, normalize_proxy, parse_list
from animelab.services.source_http import VerificationRequired, RateLimited
from test_source_http import transport, response


@pytest.fixture
def pool(tmp_path, monkeypatch):
    pool = ProxyPool(ProxyService(str(tmp_path / 'network.sqlite')))
    monkeypatch.setattr('animelab.services.proxy_pool.proxy_pool', pool)
    return pool


def entry(url='http://8.8.8.8:8080', provider='import', status='ok'):
    return {'url': url, 'provider': provider, 'country': '', 'status': status,
            'checkedAt': time.time(), 'latencyMs': 100}


@pytest.mark.parametrize('url', ['http://127.0.0.1:8080', 'http://10.0.0.1:8080',
    'http://169.254.169.254:80', 'http://[::1]:80', 'http://[::ffff:192.168.1.1]:80',
    'http://224.0.0.1:80', 'http://192.0.2.1:80', 'http://proxy.internal:8080',
    'file://8.8.8.8:80', 'http://8.8.8.8:65536', 'http://8.8.8.8:0',
    'http://8.8.8.8:80/path', 'http://8.8.8.8:80?x=1', 'http://user:pass@8.8.8.8:80'])
def test_public_list_rejects_unsafe_or_malformed_addresses(url):
    with pytest.raises(ValueError): normalize_proxy(url)


def test_formats_connect_semantics_duplicates_and_atomic_import(pool):
    rows, rejected = parse_list({'data': [{'ip': '8.8.8.8', 'port': 8080, 'protocol': 'https'},
        'http://8.8.8.8:8080', {'ip': '1.1.1.1', 'port': '1080', 'protocols': ['socks5']}, 'bad']})
    assert rejected == 1
    assert [r['url'] for r in rows] == ['http://8.8.8.8:8080', 'socks5://1.1.1.1:1080']
    pool.import_json(['http://bob:secret@8.8.8.8:8080'])
    assert 'secret' not in json.dumps(pool.snapshot())
    before = pool.snapshot()
    with pytest.raises(ValueError): pool.import_json(['http://1.1.1.1:8080', '127.0.0.1:80'])
    assert pool.snapshot() == before
    loaded = ProxyPool(pool.config)
    assert loaded.entries == pool.entries
    assert loaded.snapshot()['importedCount'] == 1
    assert loaded.clear_imported()['total'] == 0


def test_import_limits(pool):
    with pytest.raises(ValueError): pool.import_json(['8.8.8.8:8080'] * 1001)
    with pytest.raises(ValueError): pool.import_json({'wrong': []})
    with pytest.raises(ValueError): pool.set_options({'automatic': 'false'})


def test_only_fresh_healthy_proxies_and_bounded_domain_rotation(pool):
    pool.entries = {e['url']: e for e in [entry(), entry('http://1.1.1.1:8080'), entry('socks5://9.9.9.9:1080')]}
    assert pool.choose('one.example', None, automatic=True) is None
    pool.set_options({'automatic': True})
    first = pool.choose('one.example', None, automatic=True)
    second = pool.choose('one.example', first, automatic=True)
    assert first != second
    assert pool.choose('one.example', second, automatic=True) is None
    assert pool.choose('other.example', None, automatic=True) is not None
    for e in pool.entries.values(): e['checkedAt'] -= HEALTH_TTL + 1
    assert pool.snapshot()['healthy'] == 0
    assert pool.choose('fresh.example', None) is None


def test_rotation_skips_other_ports_on_the_same_proxy_and_same_exit_ip(pool):
    one = {**entry(), 'exitIp':'4.4.4.4'}
    same_host = entry('http://8.8.8.8:8081')
    same_exit = {**entry('http://1.1.1.1:8080'), 'exitIp':'4.4.4.4'}
    different = {**entry('http://9.9.9.9:8080'), 'exitIp':'3.3.3.3'}
    pool.entries = {e['url']:e for e in (one, same_host, same_exit, different)}
    assert pool.choose('source.example', one['url']) == different['url']


@pytest.mark.asyncio
async def test_refresh_coalesces_keeps_imports_failed_provider_and_health(pool, monkeypatch):
    pool.entries = {'http://8.8.8.8:8080': entry(provider='proxyscrape'),
                    'http://1.1.1.1:8080': entry('http://1.1.1.1:8080')}
    calls = []
    async def fetch(provider):
        calls.append(provider['id'])
        await asyncio.sleep(.01)
        if provider['id'] == 'proxyscrape': raise httpx.ConnectError('offline')
        if provider['id'] == 'proxifly': return parse_list(['http://9.9.9.9:8080'])
        return [], 10
    async def check(limit): return pool.snapshot()
    monkeypatch.setattr(pool, '_fetch_provider', fetch)
    monkeypatch.setattr(pool, 'check', check)
    await asyncio.gather(pool.refresh(), pool.refresh())
    assert len(calls) == len(PROVIDERS)
    assert not pool.refreshing
    assert len(pool.entries) == 3
    assert pool.entries['http://8.8.8.8:8080']['status'] == 'ok'
    assert pool.provider_status['proxyscrape']['status'] == 'error'
    assert pool.provider_status['geonode']['status'] == 'error'
    assert ProxyPool(pool.config).last_refresh == pool.last_refresh


@pytest.mark.asyncio
async def test_checks_are_bounded_and_overlapping_checks_do_not_repeat(pool, monkeypatch):
    for n in range(1, 31):
        e = entry(f'http://8.8.8.{n}:8080', status='untested')
        e['checkedAt'] = 0
        pool.entries[e['url']] = e
    calls = []
    def probe(url):
        calls.append(url)
        time.sleep(.01)
        return {'status': 'ok', 'checkedAt': time.time(), 'latencyMs': 20}
    monkeypatch.setattr(pool, 'probe', probe)
    await asyncio.gather(pool.check(12), pool.check(12))
    assert len(calls) == 12
    assert pool.snapshot()['healthy'] == 12


def test_pool_can_refresh_and_close_on_successive_application_loops(pool, monkeypatch):
    async def fetch(provider): return [], 0
    monkeypatch.setattr(pool, '_fetch_provider', fetch)
    for _ in range(2):
        asyncio.run(pool.refresh())
        asyncio.run(pool.close())
        assert pool._refresh_task is None
        assert not pool.refreshing


@pytest.mark.asyncio
async def test_close_cancels_and_awaits_owned_refresh(pool, monkeypatch):
    started = asyncio.Event()
    async def fetch(provider):
        started.set()
        await asyncio.Event().wait()
    monkeypatch.setattr(pool, '_fetch_provider', fetch)
    caller = asyncio.create_task(pool.refresh())
    await started.wait()
    await pool.close()
    with pytest.raises(asyncio.CancelledError): await caller
    assert pool._refresh_task is None and not pool.refreshing


@pytest.mark.asyncio
async def test_health_renewal_prioritizes_expired_successes_over_unknown_addresses(pool, monkeypatch):
    known = entry('http://8.8.8.8:8080')
    known['checkedAt'] -= HEALTH_TTL + 1
    untested = entry('http://1.1.1.1:8080', status='untested')
    untested['checkedAt'] = 0
    pool.entries = {e['url']:e for e in (untested, known)}
    checked = []
    def probe(url):
        checked.append(url)
        return {'status':'ok','checkedAt':time.time(),'latencyMs':10,'exitIp':'4.4.4.4'}
    monkeypatch.setattr(pool, 'probe', probe)
    await pool.check(1)
    assert checked == [known['url']]
    assert pool.snapshot()['healthyExits'] == 1


@pytest.mark.asyncio
async def test_health_watch_checks_only_when_opted_in_and_obeys_five_minute_budget(pool, monkeypatch):
    ticks, checks = 0, 0
    # A fresh runner can have less than five minutes of machine uptime. Zero
    # means no probe yet, not a probe performed at boot.
    monkeypatch.setattr('animelab.services.proxy_pool.time.monotonic', lambda: 100.0)
    async def tick(_):
        nonlocal ticks
        ticks += 1
        if ticks == 2: pool.options['automatic'] = True
        if ticks == 4: raise asyncio.CancelledError
    async def check():
        nonlocal checks
        checks += 1
        pool.last_check = time.monotonic()
    monkeypatch.setattr('animelab.services.proxy_pool.asyncio.sleep', tick)
    monkeypatch.setattr(pool, 'check', check)
    with pytest.raises(asyncio.CancelledError): await pool.watch()
    assert ticks == 4 and checks == 1


def test_rotation_clears_old_cookies_clients_and_refuses_active_transfer(pool, transport):
    service = transport(lambda s, m, u, k: response(u))
    service.client().get('https://source.example/')
    state = service.state('https://source.example/')
    state.cookies.set_cookie(service.cookie(state.domain, 'cf_clearance', 'old'))
    state.blocked_url = 'https://source.example/search'
    pool.entries = {'http://8.8.8.8:8080': entry()}
    with service.lease(state):
        with pytest.raises(ValueError, match='en cours'): service.rotate_proxy(state.domain)
        assert not service.rotate_proxy(state.domain, automatic=True)
    old = service.instances[0]
    assert service.rotate_proxy(state.domain)
    assert old.closed
    assert state.proxy == 'http://8.8.8.8:8080'
    assert not list(state.cookies) and not state.blocked_url
    service.client().get('https://source.example/')
    assert service.instances[-1].options['proxy'] == state.proxy


def test_auto_challenge_retry_is_once_and_does_not_retry_post_or_rate_limit(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry(), 'http://1.1.1.1:8080': entry('http://1.1.1.1:8080')}
    calls = []
    def handler(session, method, url, kwargs):
        calls.append(session.options['proxy'])
        return response(url, 403, headers={'cf-mitigated': 'challenge'})
    service = transport(handler)
    with pytest.raises(VerificationRequired): service.client().get('https://source.example/')
    assert calls == [None, 'http://8.8.8.8:8080']
    with pytest.raises(VerificationRequired): service.client().post('https://post.example/')
    assert calls[-1] is None
    service2 = transport(lambda s, m, u, k: response(u, 429, headers={'retry-after': '60'}))
    with pytest.raises(RateLimited): service2.client().get('https://rate.example/')
    assert service2.state('https://rate.example/').proxy is None


def test_successful_auto_retry_and_manual_config_deferred_until_stream_finishes(pool, transport, monkeypatch):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    def handler(s, m, u, k):
        return response(u, 200 if s.options['proxy'] else 403, headers={'cache-control': 'no-store'})
    service = transport(handler)
    assert service.client().get('https://source.example/').status_code == 200
    state = service.state('https://source.example/')
    from animelab.services.proxy_service import proxy_service
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: 'http://manual:8080')
    with service.lease(state):
        service.apply_proxy_settings()
        assert state.proxy == 'http://8.8.8.8:8080'
        assert state.pending_reset
    assert state.proxy == 'http://manual:8080'
    assert not state.pending_reset


def test_previously_blocked_request_rotates_only_once_and_cannot_use_cached_results(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {e['url']: e for e in [entry(), entry('http://1.1.1.1:8080')]}
    calls = []
    def handler(s, m, u, k):
        calls.append(s.options['proxy'])
        return response(u, 200 if len(calls) == 1 else 403, headers={} if len(calls) == 1 else {'cf-mitigated': 'challenge'})
    service = transport(handler)
    url = 'https://source.example/search'
    service.client().get(url)
    service.state(url).blocked_url = url
    with pytest.raises(VerificationRequired): service.client().get(url)
    assert calls == [None, 'http://8.8.8.8:8080']


def test_retry_preserves_original_search_parameters_after_redirect(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    searches = []
    def handler(s, m, u, k):
        if 'origin.example' in u:
            searches.append(k.get('params'))
            return response(u, 302, headers={'location': 'https://mirror.example/api?q=one'})
        return response(u, 200 if s.options['proxy'] else 403, headers={'cache-control':'no-store'} if s.options['proxy'] else {'cf-mitigated':'challenge'})
    service = transport(handler)
    assert service.client().get('https://origin.example/api', params={'q':'one'}).status_code == 200
    assert searches == [{'q':'one'}, {'q':'one'}]


def test_read_only_post_search_can_rotate_with_body_preserved(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    bodies = []
    def handler(s, m, u, k):
        assert 'retry_safe' not in k
        bodies.append(k['data'])
        return response(u, 200 if s.options['proxy'] else 403, headers={'cf-mitigated':'challenge'} if not s.options['proxy'] else {})
    service = transport(handler)
    assert service.client().post('https://source.example/search', data={'query':'one'}, retry_safe=True).status_code == 200
    assert bodies == [{'query':'one'}, {'query':'one'}]


@pytest.mark.asyncio
async def test_media_rotation_happens_before_bytes_and_closes_old_stream(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    class Raw:
        def __init__(self, proxy, url):
            self.status_code, self.url = (200 if proxy else 403), url
            self.headers = httpx.Headers({'content-type': 'video/mp4'} if proxy else {'cf-mitigated': 'challenge'})
            self.closed = False
        def close(self): self.closed = True
        def iter_content(self, chunk_size=None): yield b'video-bytes'
    raw = []
    def handler(s, m, u, k):
        r = Raw(s.options['proxy'], u); raw.append(r); return r
    service = transport(handler)
    async with service.async_client().stream('GET', 'https://cdn.example/video.mp4') as r:
        assert b''.join([chunk async for chunk in r.aiter_bytes()]) == b'video-bytes'
        assert raw[0].closed
        assert service.state('https://cdn.example').leased == 1
    assert all(r.closed for r in raw)
    assert service.state('https://cdn.example').leased == 0


@pytest.mark.asyncio
async def test_automatic_rotation_notifies_the_download_scheduler_on_its_event_loop(pool, transport):
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    service = transport(lambda s, m, u, k: response(u, 200 if s.options['proxy'] else 403))
    loop = asyncio.get_running_loop()
    observed = loop.create_future()
    service.rotation_callback = lambda domain: loop.call_soon_threadsafe(observed.set_result, domain)
    assert (await service.async_client().get('https://cdn.example/video.mp4')).status_code == 200
    assert await asyncio.wait_for(observed, 1) == 'cdn.example'
    assert service.state('https://cdn.example').blocked_url is None


def test_pool_api_restricts_mutations_and_masks_import(pool, monkeypatch):
    from animelab.routers.network import router
    app = FastAPI(); app.include_router(router)
    with TestClient(app, client=('203.0.113.10', 123)) as remote:
        assert remote.get('/api/network/proxy-pool').status_code == 200
        assert remote.post('/api/network/proxy-pool/settings', json={'automatic': True}).status_code == 403
        assert remote.post('/api/network/proxy-pool/import', json=[]).status_code == 403
    with TestClient(app, client=('127.0.0.1', 123)) as local:
        result = local.post('/api/network/proxy-pool/import', json=['http://user:secret@8.8.8.8:8080'])
        assert result.status_code == 200 and 'secret' not in result.text
        assert local.post('/api/network/proxy-pool/import', json=['127.0.0.1:80']).status_code == 400
        assert local.post('/api/network/proxy-pool/import', content='x' * (1024*1024+1)).status_code == 413
        assert local.post('/api/network/proxy-pool/rotate', json={'domain': 'unknown.example'}).status_code == 400


def test_rotation_endpoint_known_domain_resumes_and_rejects_open_browser(pool, transport, monkeypatch):
    from animelab.routers import network
    service = transport(lambda s, m, u, k: response(u))
    service.state('https://source.example/')
    monkeypatch.setattr('animelab.services.source_http.source_http', service)
    monkeypatch.setattr(network.download_manager, 'resume_verified_domain', lambda domain: 2)
    pool.entries = {'http://8.8.8.8:8080': entry()}
    app = FastAPI(); app.include_router(network.router)
    with TestClient(app, client=('127.0.0.1', 123)) as local:
        monkeypatch.setattr(network.browser_verification, 'jobs', {'one': {'domain': 'source.example'}})
        assert local.post('/api/network/proxy-pool/rotate', json={'domain': 'source.example'}).status_code == 409
        network.browser_verification.jobs.clear()
        result = local.post('/api/network/proxy-pool/rotate', json={'domain': 'source.example'})
        assert result.status_code == 200 and result.json()['resumed'] == 2
        assert service.state('https://source.example/').proxy == 'http://8.8.8.8:8080'


def test_restart_does_not_restore_cookies_from_a_different_proxy(pool, transport):
    service = transport(lambda s, m, u, k: response(u))
    state = service.state('https://source.example/')
    state.cookies.set_cookie(service.cookie(state.domain, 'cf_clearance', 'ip-bound', expires=int(time.time())+3600))
    pool.entries = {'http://8.8.8.8:8080': entry()}
    service.rotate_proxy(state.domain)
    state.cookies.set_cookie(service.cookie(state.domain, 'cf_clearance', 'proxy-bound', expires=int(time.time())+3600))
    service._save(state)
    restarted = transport(lambda s, m, u, k: response(u))
    assert not list(restarted.state('https://source.example/').cookies)


def test_public_proxy_keeps_tls_verification_even_if_manual_option_disabled(pool, transport, monkeypatch):
    from animelab.config import settings
    monkeypatch.setattr(settings, 'SSL_VERIFY', False)
    service = transport(lambda s, m, u, k: response(u))
    state = service.state('https://source.example/')
    pool.entries = {'http://8.8.8.8:8080': entry()}
    service.rotate_proxy(state.domain)
    service.client().get('https://source.example/')
    assert service.instances[0].options['verify'] is True


@pytest.mark.asyncio
@pytest.mark.parametrize('service_class', ['ScrapingService', 'VoirAnimeScrapingService', 'AnimepaheService'])
async def test_cached_native_feed_uses_automatic_rotation_when_already_blocked(pool, transport, monkeypatch, service_class):
    import importlib
    name = {'ScrapingService': 'scraping_service', 'VoirAnimeScrapingService': 'voiranime_service', 'AnimepaheService': 'animepahe_service'}[service_class]
    module = importlib.import_module('animelab.services.' + name)
    cls = getattr(module, service_class)
    native = cls.__new__(cls)
    native.base_url = 'https://source.example/'
    native.latest_cache, native.last_cache_time = ['old'], time.time()
    service = transport(lambda s, m, u, k: response(u))
    service.state(native.base_url).blocked_url = native.base_url
    monkeypatch.setattr(module, 'source_http', service)
    pool.set_options({'automatic': True})
    pool.entries = {'http://8.8.8.8:8080': entry()}
    from unittest.mock import AsyncMock
    async def refresh(): native.latest_cache = ['fresh']
    native._safe_refresh_cache = AsyncMock(side_effect=refresh)
    assert await native.get_latest_releases() == ['fresh']
    assert service.state(native.base_url).proxy == 'http://8.8.8.8:8080'
    native._safe_refresh_cache.assert_awaited_once()
