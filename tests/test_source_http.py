import asyncio
import copy
import threading
import time
from unittest.mock import AsyncMock

import httpx
import pytest
from curl_cffi.requests import Cookies

from animelab.services.proxy_service import proxy_service
from animelab.services.source_http import SourceHTTPService, VerificationRequired, RateLimited, SourceNetworkError, USER_AGENT, PROFILE


class FakeSession:
    def __init__(self, handler, **options):
        self.handler, self.options = handler, options
        self.cookies = Cookies()
        self.closed = False

    def request(self, method, url, **kwargs):
        return self.handler(self, method, url, kwargs)

    def close(self):
        self.closed = True


@pytest.fixture
def transport(tmp_path, monkeypatch):
    monkeypatch.setattr('animelab.services.source_http.is_safe_url', lambda url: url.startswith('https://'))
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: None)
    services = []
    def make(handler, **options):
        instances = []
        def factory(**kwargs):
            s = FakeSession(handler, **kwargs)
            instances.append(s)
            return s
        s = SourceHTTPService(storage=tmp_path, min_interval=0, session_factory=factory, **options)
        s.instances = instances
        services.append(s)
        return s
    yield make
    for service in services:
        service.close()


def response(url, code=200, text='ok', headers=None):
    return httpx.Response(code, text=text, headers=headers, request=httpx.Request('GET', url))


@pytest.mark.asyncio
async def test_sync_async_share_cookies_connections_profile_and_sticky_proxy(transport, monkeypatch):
    requests = []
    proxy = ['http://proxy-one:8080']
    monkeypatch.setattr(proxy_service, 'get_random_proxy', lambda: proxy[0])
    def handler(session, method, url, kwargs):
        requests.append((session.options['proxy'], kwargs['headers']['user-agent'], session.cookies.get_dict()))
        session.cookies.set('session', 'secret', domain='source.example')
        return response(url, headers={'cache-control': 'no-store'})
    service = transport(handler)
    service.client().get('https://source.example/first')
    proxy[0] = 'http://proxy-two:8080'
    await service.async_client().get('https://source.example/second')
    service.client().get('https://other.example/third')
    assert len(service.instances) == 2
    assert requests[1] == ('http://proxy-one:8080', USER_AGENT, {'session': 'secret'})
    assert requests[2][0] == 'http://proxy-two:8080'
    assert requests[2][2] == {}
    assert service.instances[0].options['impersonate'] == PROFILE
    assert all('secret' not in str(x) for x in service.diagnostics())


@pytest.mark.parametrize('delete', [False, True])
def test_stale_lease_does_not_restore_or_overwrite_a_cookie(transport, delete):
    service = transport(lambda *args: None)
    service.import_cookies('https://source.example', [
        {'domain': 'source.example', 'name': 'session', 'value': 'old'}])
    state = service.state('https://source.example')
    with service.lease(state):
        with service.lease(state) as fresh:
            if delete:
                fresh.cookies.delete('session', domain='source.example', path='/')
            else:
                fresh.cookies.set('session', 'new', domain='source.example', path='/')
    assert [c.value for c in state.cookies if c.name == 'session'] == ([] if delete else ['new'])


def test_expiry_persistence_and_deletion(transport, tmp_path):
    def handler(session, method, url, kwargs):
        if url.endswith('delete'):
            session.cookies.delete('clearance', domain='source.example', path='/')
        return response(url, headers={'cache-control': 'no-store'})
    service = transport(handler)
    service.import_cookies('https://source.example', [
        {'name': 'clearance', 'value': 'valid', 'domain': 'source.example', 'expires': time.time()+100},
        {'name': 'expired', 'value': 'old', 'domain': 'source.example', 'expires': time.time()-10},
        {'name': 'foreign', 'value': 'x', 'domain': 'unrelated.example'},
    ])
    assert len(service.state('https://source.example').cookies) == 1
    restored = SourceHTTPService(storage=tmp_path)
    assert len(restored.state('https://source.example').cookies) == 1
    restored.close()
    service.client().get('https://source.example/delete')
    assert len(service.state('https://source.example').cookies) == 0


@pytest.mark.parametrize('code,headers,text', [
    (200, {'cf-mitigated':'challenge'}, 'challenge'),
    (503, {'content-type':'text/html'}, '<html>Just a moment /cdn-cgi/challenge-platform/ cf-chl-token</html>'),
])
def test_challenge_blocks_domain_without_retries(transport, code, headers, text):
    calls = []
    service = transport(lambda s,m,u,k: calls.append(u) or response(u, code, text, headers))
    with pytest.raises(VerificationRequired):
        service.client().get('https://source.example/episode')
    with pytest.raises(VerificationRequired):
        service.client().get('https://source.example/other')
    assert len(calls) == 1
    assert service.diagnostics()[0]['verificationRequired']


def test_plain_403_is_not_a_challenge(transport):
    service = transport(lambda s,m,u,k: response(u,403,headers={'server':'cloudflare'}))
    r = service.client().get('https://source.example/episode')
    with pytest.raises(httpx.HTTPStatusError): r.raise_for_status()
    assert not service.diagnostics()[0]['verificationRequired']


def test_rate_limit_respects_retry_after_without_long_blocking_wait(transport):
    calls = []
    service = transport(lambda s,m,u,k: calls.append(u) or response(u,429,headers={'retry-after':'120'}))
    with pytest.raises(RateLimited) as error:
        service.client().get('https://source.example/api')
    assert error.value.retry_after == 120
    assert len(calls) == 1
    assert service.state('https://source.example').cooldown > time.monotonic()+100


def test_tls_errors_and_posts_are_not_retried(transport):
    calls = []
    def fail(s,m,u,k):
        calls.append(u)
        raise RuntimeError('SSL certificate verification failed')
    service = transport(fail)
    with pytest.raises(SourceNetworkError) as exc:
        service.client().get('https://source.example')
    assert exc.value.kind == 'tls'
    assert len(calls) == 1
    service = transport(lambda s,m,u,k: calls.append(u) or response(u,503))
    assert service.client().post('https://source.example').status_code == 503
    assert len(calls) == 2


@pytest.mark.asyncio
async def test_identical_requests_are_grouped_cached_and_expire(transport):
    calls=[]
    def handler(s,m,u,k):
        calls.append(u)
        time.sleep(0.02)
        return response(u,headers={'content-type':'text/html'})
    service=transport(handler,cache_ttl=0.05)
    client=service.async_client()
    result=await asyncio.gather(*(client.get('https://source.example/feed') for _ in range(8)))
    assert len(result)==8 and len(calls)==1
    assert (await client.get('https://source.example/feed')).text=='ok'
    assert len(calls)==1
    await asyncio.sleep(0.06)
    await client.get('https://source.example/feed')
    assert len(calls)==2
    for _ in range(2): await client.get('https://source.example/live.m3u8')
    assert len(calls)==4


def test_unsafe_redirect_is_stopped_before_second_request(transport, monkeypatch):
    calls=[]
    service=transport(lambda s,m,u,k: calls.append(u) or response(u,302,headers={'location':'http://127.0.0.1/private'}))
    with pytest.raises(ValueError): service.client().get('https://source.example/redirect')
    assert len(calls)==1


@pytest.mark.asyncio
async def test_challenge_media_stream_releases_connection(transport):
    class Stream:
        status_code=403
        headers=httpx.Headers({'cf-mitigated':'challenge'})
        url='https://source.example/video.mp4'
        closed=False
        def close(self): self.closed=True
    raw=Stream()
    service=transport(lambda s,m,u,k: raw)
    with pytest.raises(VerificationRequired):
        async with service.async_client().stream('GET',raw.url):
            pytest.fail('Challenge must be intercepted before writing the file')
    assert raw.closed and service.state(raw.url).leased==0


@pytest.mark.asyncio
async def test_download_challenge_is_persisted_without_retry_and_resumes_after_verification(monkeypatch,tmp_path):
    from animelab.services.download_manager import DownloadManagerService, library_service
    from animelab.models.download_task import DownloadTask, DownloadStatus
    manager=DownloadManagerService()
    task=DownloadTask(fileUrl='https://cdn.example/episode.mp4', savePath=str(tmp_path/'episode.mp4'))
    challenge=VerificationRequired('https://cdn.example/episode.mp4')
    fail=AsyncMock(side_effect=challenge)
    monkeypatch.setattr(manager,'_download_single_file',fail)
    monkeypatch.setattr(manager,'_trigger_process_queue',lambda: None)
    saved=[]
    monkeypatch.setattr(library_service,'save_task',lambda t:saved.append(t.status))
    manager.tasks[task.id]=task
    await manager._execute_download(task)
    assert task.status==DownloadStatus.VERIFICATION_REQUIRED
    assert task.verificationUrl==challenge.url
    assert fail.await_count==1
    assert saved[-1]==DownloadStatus.VERIFICATION_REQUIRED
    assert task.to_entity().to_task().verificationUrl==challenge.url

@pytest.mark.asyncio
async def test_hls_rate_limit_stops_segment_retries(monkeypatch, tmp_path):
    from animelab.services.download_manager import DownloadManagerService
    from animelab.models.download_task import DownloadTask
    blocked = RateLimited(response('https://cdn.example/segment.ts', 429), 120)
    calls = []
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self, *args): pass
        async def get(self, url, **kwargs):
            calls.append(url)
            if url.endswith('.ts'): raise blocked
            return response(url, text='#EXTM3U\n#EXTINF:10,\nsegment.ts\n#EXT-X-ENDLIST')
    manager = DownloadManagerService()
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: Client())
    task = DownloadTask(fileName='episode.mp4', savePath=str(tmp_path/'episode.mp4'))
    with pytest.raises(RateLimited):
        await manager._download_hls_segments_native(task, 'https://cdn.example/main.m3u8')
    assert calls == ['https://cdn.example/main.m3u8', 'https://cdn.example/segment.ts']


@pytest.mark.asyncio
async def test_native_hls_aes128_uses_shared_transport_and_correct_media_sequence(monkeypatch,tmp_path):
    from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
    from cryptography.hazmat.primitives.padding import PKCS7
    from animelab.services.download_manager import DownloadManagerService
    from animelab.models.download_task import DownloadTask
    key=b'0123456789abcdef'
    plaintext=b'video segment for unit test'
    padder=PKCS7(128).padder()
    padded=padder.update(plaintext)+padder.finalize()
    encryptor=Cipher(algorithms.AES(key),modes.CBC((42).to_bytes(16,'big'))).encryptor()
    ciphertext=encryptor.update(padded)+encryptor.finalize()
    visited=[]
    async def get(url,**kwargs):
        visited.append(url)
        data=key if url.endswith('key') else ciphertext
        if url.endswith('m3u8'):
            data=b'#EXTM3U\n#EXT-X-MEDIA-SEQUENCE:42\n#EXT-X-KEY:METHOD=AES-128,URI="key"\n#EXTINF:10.0,\nsegment.ts\n#EXT-X-ENDLIST'
        return httpx.Response(200,content=data,request=httpx.Request('GET',url))
    class Client:
        async def __aenter__(self): return self
        async def __aexit__(self,*args): pass
    client=Client()
    client.get=get
    manager=DownloadManagerService()
    monkeypatch.setattr(manager,'_create_async_client',lambda **kwargs:client)
    monkeypatch.setattr(manager,'is_ffmpeg_available',lambda:False)
    monkeypatch.setattr(manager,'_finalize_task',AsyncMock())
    task=DownloadTask(fileName='episode.mp4',savePath=str(tmp_path/'episode.mp4'))
    await manager._download_hls_segments_native(task,'https://cdn.example/main.m3u8')
    assert (tmp_path/'episode.mp4').read_bytes()==plaintext
    assert visited==['https://cdn.example/main.m3u8','https://cdn.example/segment.ts','https://cdn.example/key']

@pytest.mark.asyncio
async def test_stream_checks_redirects_before_opening_destination(transport):
    class Raw:
        def __init__(self,url,status,headers):
            self.url,self.status_code,self.headers=url,status,httpx.Headers(headers)
        def close(self): pass
        def iter_content(self,chunk_size=65536): yield b'video'
    visited=[]
    def handle(s,m,u,k):
        visited.append(u)
        return Raw(u,302,{'content-type':'text/html','location':'https://cdn.example/video'}) if len(visited)==1 else Raw(u,200,{'content-type':'video/mp4'})
    service=transport(handle)
    async with service.async_client().stream('GET','https://source.example/video') as response:
        assert b''.join([chunk async for chunk in response.aiter_bytes()])==b'video'
    assert visited==['https://source.example/video','https://cdn.example/video']
    assert all(state.leased==0 for state in service._domains.values())

@pytest.mark.asyncio
async def test_real_curl_transport_decompresses_once_and_streams_without_buffering(transport,monkeypatch):
    import gzip
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
    from curl_cffi.requests import Session
    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            body=gzip.compress(b'actual transport response')
            self.send_response(200)
            self.send_header('Content-Type','text/plain')
            self.send_header('Content-Encoding','gzip')
            self.send_header('Content-Length',str(len(body)))
            self.send_header('Cache-Control','no-store')
            self.end_headers()
            self.wfile.write(body)
        def log_message(self,*args): pass
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True)
    thread.start()
    url=f'http://127.0.0.1:{server.server_port}/test'
    monkeypatch.setattr('animelab.services.source_http.is_safe_url',lambda candidate:candidate==url)
    service=transport(lambda *args:None)
    service.session_factory=Session
    try:
        response=await service.async_client().get(url)
        assert response.text=='actual transport response'
        assert 'content-encoding' not in response.headers
        async with service.async_client().stream('GET',url) as upstream:
            assert b''.join([chunk async for chunk in upstream.aiter_bytes()])==b'actual transport response'
    finally:
        server.shutdown()
        server.server_close()

@pytest.mark.parametrize('code,body', [
    (403, '<title>DDoS-Guard</title><script src="/.well-known/ddos-guard/js-challenge/view.js"></script>'),
    (403, '<div id="cf-error-details">Sorry, you have been blocked</div>'),
    (200, '<title>Verify you are human</title><div class="h-captcha"></div>'),
])
def test_other_protections_and_cloudflare_blocks_include_manual_url(transport, code, body):
    url = 'https://source.example/search?q=one+piece'
    service = transport(lambda s,m,u,k: response(u, code, body, {'content-type': 'text/html'}))
    with pytest.raises(VerificationRequired) as error:
        service.client().get(url)
    assert error.value.to_dict()['url'] == url
    assert service.state(url).blocked_url == url


def test_normal_page_with_captcha_widget_is_not_blocked(transport):
    service = transport(lambda s,m,u,k: response(u,200,'<h1>Catalogue</h1><div class="g-recaptcha"></div>', {'content-type': 'text/html'}))
    assert service.client().get('https://source.example/').status_code == 200
    assert not service.diagnostics()[0]['verificationRequired']

@pytest.mark.asyncio
@pytest.mark.parametrize('streaming', [False, True])
async def test_media_policy_checks_every_redirect_even_when_source_cache_is_warm(transport, streaming):
    from fastapi import HTTPException
    from animelab.media_policy import validate_media_url
    from unittest.mock import patch
    class Raw:
        def __init__(self, url, code, headers):
            self.url, self.status_code, self.headers = url, code, httpx.Headers(headers)
        def close(self): pass
        def iter_content(self, chunk_size=65536): yield b'video'
    visited = []
    def handle(session, method, url, kwargs):
        visited.append(url)
        assert '_url_validator' not in kwargs
        if url.endswith('/start'):
            if streaming:
                return Raw(url, 302, {'location': 'https://outside.example/file', 'content-type': 'video/mp4'})
            return response(url, 302, headers={'location': 'https://outside.example/file'})
        if streaming:
            return Raw(url, 200, {'content-type': 'video/mp4'})
        return response(url)
    service = transport(handle)
    if not streaming:
        service.client().get('https://voir-anime.to/start')  # Shared cache populated without media policy.
        visited.clear()
    with patch.dict('os.environ', {'ANIMELAB_SHARED_WORKER': '1'}):
        client = service.async_client(url_validator=validate_media_url)
        with pytest.raises(HTTPException) as error:
            if streaming:
                async with client.stream('GET', 'https://voir-anime.to/start'):
                    pytest.fail('A forbidden destination must not be opened')
            else:
                await client.get('https://voir-anime.to/start')
        assert error.value.status_code == 400
    assert visited == ['https://voir-anime.to/start']
    assert all(state.leased == 0 for state in service._domains.values())
