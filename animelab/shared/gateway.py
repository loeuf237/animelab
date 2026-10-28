"""Authenticated same-origin gateway. User identity never comes from a request path."""
import asyncio
from collections import OrderedDict, deque
from contextlib import asynccontextmanager, suppress
from dataclasses import dataclass
from pathlib import Path
import ipaddress
import math
import re
import time
from urllib.parse import urlsplit

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse, Response, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.middleware.trustedhost import TrustedHostMiddleware
from uvicorn.middleware.proxy_headers import ProxyHeadersMiddleware
import httpx

from animelab.shared.accounts import Accounts, PasswordBusy, digest
from animelab.shared.workers import Workers
from animelab.desktop.state import InstanceLock
from animelab import __version__

COOKIE = 'animelab_session'
SAFE = {'GET', 'HEAD', 'OPTIONS'}
ASSETS = Path(__file__).with_name('web')
HOP = {'connection', 'keep-alive', 'proxy-authenticate', 'proxy-authorization',
       'te', 'trailer', 'transfer-encoding', 'upgrade', 'set-cookie', 'content-length'}

# The built Vue UI uses local scripts and HLS blob workers, Google fonts and
# external covers/media. No remote or inline scripts may execute in the UI.
SPA_CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline' https://fonts.googleapis.com; "
           "font-src 'self' https://fonts.gstatic.com; img-src 'self' https: data: blob:; "
           "media-src 'self' https: blob:; connect-src 'self' https:; worker-src 'self' blob:; "
           "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")


@dataclass
class SharedConfig:
    root: Path
    public_url: str
    max_workers: int = 4
    session_hours: int = 12
    idle_minutes: int = 30
    trusted_proxies: tuple[str, ...] = ()

    def __post_init__(self):
        url = urlsplit(self.public_url)
        if (url.scheme not in ('http', 'https') or not url.hostname or url.username or url.password
                or url.path not in ('', '/') or url.query or url.fragment):
            raise ValueError('Public URL must be an http(s) origin without a path or credentials')
        if url.scheme == 'http' and url.hostname not in ('localhost', '127.0.0.1', '::1'):
            raise ValueError('Shared access over a network requires an HTTPS public URL')
        if not 1 <= self.max_workers <= 32:
            raise ValueError('Active engines must be between 1 and 32')
        if (type(self.session_hours) is not int or not 1 <= self.session_hours <= 168
                or type(self.idle_minutes) is not int or not 1 <= self.idle_minutes <= 1440
                or self.idle_minutes > self.session_hours * 60):
            raise ValueError('Invalid session lifetime or idle timeout')
        self.public_url = self.public_url.rstrip('/')
        self.root = Path(self.root).resolve()
        # Never accept '*' or names resolving to a different machine later.
        for peer in self.trusted_proxies:
            ipaddress.ip_network(peer, strict=False)

    @property
    def secure(self):
        return self.public_url.startswith('https://')


class Input(BaseModel):
    model_config = ConfigDict(extra='forbid', strict=True)


class Login(Input):
    username: str = Field(max_length=40)
    password: str = Field(max_length=256)


class NewUser(Login):
    admin: bool = False
    permissions: list[str] = Field(default_factory=lambda: ['download'])


class UpdateUser(Input):
    password: str | None = Field(default=None, max_length=256)
    enabled: bool | None = None
    admin: bool | None = None
    permissions: list[str] | None = None


class Password(Input):
    old_password: str = Field(max_length=256)
    password: str = Field(max_length=256)


class NewCode(Input):
    user_id: str | None = Field(default=None, pattern=r'^[0-9a-f]{32}$')
    permissions: list[str] = Field(default_factory=lambda: ['download'])


class Redeem(Input):
    code: str = Field(max_length=128)
    password: str = Field(max_length=256)
    username: str | None = Field(default=None, max_length=40)


class Attempts:
    """Only failures consume a bounded, expiring (identity, peer) budget."""
    def __init__(self):
        self.peers = OrderedDict()

    def _prune(self):
        now = time.monotonic()
        for key in list(self.peers):
            attempts = self.peers[key]
            while attempts and attempts[0] <= now - 900:
                attempts.popleft()
            if not attempts:
                del self.peers[key]
        return now

    def check(self, peer, identity):
        now = self._prune()
        failures = self.peers.get((identity.lower(), peer), ())
        if len(failures) >= 10:
            raise HTTPException(429, 'Too many authentication failures; try later',
                headers={'Retry-After': str(max(1, math.ceil(failures[0] + 900 - now)))})

    def failed(self, peer, identity):
        now = self._prune()
        key = (identity.lower(), peer)
        if key not in self.peers:
            if len(self.peers) >= 10000:
                self.peers.popitem(last=False)
            self.peers[key] = deque(maxlen=10)
        self.peers[key].append(now)
        self.peers.move_to_end(key)

    def succeeded(self, peer, identity):
        self.peers.pop((identity.lower(), peer), None)


class BodyLimit:
    """Bound bodies before FastAPI parses JSON, including chunked requests."""
    def __init__(self, app, limit=2 * 1024 * 1024):
        self.app, self.limit = app, limit

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        subtitle_upload = (scope.get('method') == 'POST' and
                           re.fullmatch(r'/api/download/[^/]{1,128}/subtitles/import', scope.get('path', '')))
        limit = 10 * 1024 * 1024 if subtitle_upload else self.limit
        size = 0
        messages = []
        while True:
            message = await receive()
            if message['type'] == 'http.disconnect':
                return
            size += len(message.get('body', b''))
            if size > limit:
                return await JSONResponse({'error': f'Request body exceeds {limit // (1024 * 1024)} MiB'}, status_code=413)(scope, receive, send)
            messages.append(message)
            if not message.get('more_body', False):
                break

        async def replay():
            if messages:
                return messages.pop(0)
            return await receive()
        return await self.app(scope, replay, send)


def has_permission(user, permission):
    return bool(user['admin'] or permission in user['permissions'])


def check_action(user, path, method):
    if method in SAFE:
        return
    # Download control is private, but the ability to create/resume automatic
    # transfers is still an explicit grant. Favorites can enable auto-download.
    if path.startswith(('/api/download', '/api/watchdog', '/api/favorites/auto-download')) and not has_permission(user, 'download'):
        raise HTTPException(403, 'Download permission required')
    if path.startswith('/api/extensions') and not has_permission(user, 'extensions'):
        raise HTTPException(403, 'Extension management permission required')
    if path.startswith(('/api/proxy', '/api/network/proxy-pool')) and not user['admin']:
        raise HTTPException(403, 'Administrator required for server proxy connections')


def create_app(config: SharedConfig, *, accounts=None, workers=None, transport=None):
    store = accounts or Accounts(config.root)
    store.lifetime, store.idle = config.session_hours * 3600, config.idle_minutes * 60
    pool = workers or Workers(config.root, max_workers=config.max_workers)
    attempts = Attempts()
    password_work = asyncio.Lock()

    @asynccontextmanager
    async def hashing():
        # Fail fast rather than queue threads/128 MiB computations. No global
        # minute quota can lock unrelated users out after the work has finished.
        if password_work.locked():
            raise HTTPException(503, 'Password verification is busy; try shortly', headers={'Retry-After': '1'})
        async with password_work:
            yield

    @asynccontextmanager
    async def lifespan(app):
        if not any(user['admin'] and user['enabled'] for user in store.users()):
            raise RuntimeError('Create an administrator first: python -m animelab.shared create-admin')
        lock = InstanceLock(config.root, 'gateway.lock')
        if not lock.acquire():
            raise RuntimeError('A gateway already owns this shared-server directory')
        try:
            async with httpx.AsyncClient(timeout=httpx.Timeout(60, read=None), trust_env=False,
                    transport=transport, limits=httpx.Limits(max_connections=128, max_keepalive_connections=16)) as client:
                app.state.client = client
                try:
                    yield
                finally:
                    await pool.close()
        finally:
            lock.release()

    app = FastAPI(title='AnimeLab Shared Server', lifespan=lifespan, docs_url=None,
                  redoc_url=None, openapi_url=None)
    app.state.accounts, app.state.workers = store, pool

    @app.exception_handler(ValueError)
    async def invalid(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=400)

    @app.exception_handler(PasswordBusy)
    async def busy(request, exc):
        return JSONResponse({'error': str(exc)}, status_code=503, headers={'Retry-After': '1'})

    @app.middleware('http')
    async def boundaries(request, call_next):
        if request.method not in SAFE:
            # Compare the complete configured origin, including scheme and port.
            if request.headers.get('origin') != config.public_url:
                return JSONResponse({'error': 'Same-origin request required'}, status_code=403)
            if request.headers.get('sec-fetch-site') == 'cross-site':
                return JSONResponse({'error': 'Cross-site request blocked'}, status_code=403)
            if request.headers.get('content-type', '').split(';')[0].strip() != 'application/json':
                return JSONResponse({'error': 'JSON request required'}, status_code=415)
        response = await call_next(request)
        response.headers['Cache-Control'] = 'no-store'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Vary'] = 'Cookie'
        response.headers['X-AnimeLab-Shared'] = '1'
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'DENY'
        response.headers['Referrer-Policy'] = 'no-referrer'
        if request.url.path.startswith('/auth/'):
            response.headers['Content-Security-Policy'] = "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
        else:
            response.headers['Content-Security-Policy'] = SPA_CSP
        return response

    async def current(request):
        user = await asyncio.to_thread(store.session, request.cookies.get(COOKIE, ''))
        if not user:
            raise HTTPException(401, 'Authentication required', headers={'X-AnimeLab-Shared': '1'})
        return user

    async def admin(request):
        user = await current(request)
        if not user['admin']:
            raise HTTPException(403, 'Administrator required')
        return user

    def peer(request):
        return request.client.host if request.client else 'unknown'

    def session_response(token):
        response = JSONResponse({'success': True})
        response.set_cookie(COOKIE, token, httponly=True, secure=config.secure,
                            samesite='strict', max_age=store.lifetime, path='/')
        # Personal-mode language/preferences must not survive an account switch.
        response.delete_cookie('animan_lang')
        return response

    @app.get('/healthz')
    async def health():
        return {'status': 'ok', 'mode': 'shared', 'version': __version__}

    @app.get('/auth/login')
    @app.get('/auth/account')
    async def account_page():
        return FileResponse(ASSETS / 'account.html')

    @app.get('/auth/client.js')
    async def client_script():
        return FileResponse(ASSETS / 'client.js', media_type='text/javascript')

    @app.get('/auth/style.css')
    async def style():
        return FileResponse(ASSETS / 'style.css', media_type='text/css')

    @app.get('/api/auth/me')
    async def me(request: Request):
        return {'shared': True, 'user': await current(request)}

    @app.post('/api/auth/login')
    async def login(body: Login, request: Request):
        address = peer(request)
        attempts.check(address, body.username)
        async with hashing():
            token = await asyncio.to_thread(store.login, body.username, body.password)
        if not token:
            attempts.failed(address, body.username)
            raise HTTPException(401, 'Invalid username or password')
        attempts.succeeded(address, body.username)
        # Rotate the current session; never reuse a client-selected identifier.
        await asyncio.to_thread(store.revoke, request.cookies.get(COOKIE, ''))
        return session_response(token)

    @app.post('/api/auth/logout')
    async def logout(request: Request):
        await asyncio.to_thread(store.revoke, request.cookies.get(COOKIE, ''))
        response = JSONResponse({'success': True})
        response.delete_cookie(COOKIE, secure=config.secure, httponly=True, samesite='strict')
        response.delete_cookie('animan_lang')
        response.headers['Clear-Site-Data'] = '"cache", "storage"'
        return response

    @app.post('/api/auth/password')
    async def password(body: Password, request: Request):
        user = await current(request)
        address, identity = peer(request), user['username']
        attempts.check(address, identity)
        try:
            async with hashing():
                await asyncio.to_thread(store.change_password, request.cookies.get(COOKIE, ''), body.old_password, body.password)
        except ValueError:
            attempts.failed(address, identity)
            raise
        attempts.succeeded(address, identity)
        return {'success': True, 'login_required': True}

    @app.post('/api/auth/redeem')
    async def redeem(body: Redeem, request: Request):
        # Recovery has no username. Scope its failures to a digest of the code,
        # never a shared anonymous bucket and never a plaintext invitation token.
        identity = '@redeem:' + (body.username.lower() if body.username else digest(body.code))
        address = peer(request)
        attempts.check(address, identity)
        try:
            async with hashing():
                token = await asyncio.to_thread(store.redeem, body.code, body.password, body.username, issue_session=True)
        except ValueError:
            attempts.failed(address, identity)
            raise
        attempts.succeeded(address, identity)
        return session_response(token)

    @app.get('/api/auth/users')
    async def users(request: Request):
        await admin(request)
        return {'users': await asyncio.to_thread(store.users), 'engines': list(pool.running)}

    @app.post('/api/auth/users')
    async def create_user(body: NewUser, request: Request):
        await admin(request)
        async with hashing():
            identity = await asyncio.to_thread(store.create, **body.model_dump())
        return {'id': identity}

    @app.patch('/api/auth/users/{user_id}')
    async def update_user(user_id: str, body: UpdateUser, request: Request):
        await admin(request)
        # Permission revocation stops scheduled/watchdog jobs as well as requests.
        async def change():
            await pool.change(user_id, lambda: asyncio.to_thread(store.update, user_id, **body.model_dump(exclude_none=True)))
        if body.password is not None:
            async with hashing():
                await change()
        else:
            await change()
        return {'success': True}

    @app.post('/api/auth/users/{user_id}/stop')
    async def stop_user(user_id: str, request: Request):
        await admin(request)
        await pool.stop(user_id)
        return {'success': True}

    @app.post('/api/auth/codes')
    async def code(body: NewCode, request: Request):
        await admin(request)
        value = await asyncio.to_thread(store.code, **body.model_dump())
        return {'code': value, 'expires_in': 86400 if body.user_id else 7 * 86400}

    @app.get('/api/auth/codes')
    async def codes(request: Request):
        await admin(request)
        return {'codes': await asyncio.to_thread(store.codes)}

    @app.delete('/api/auth/codes/{code_id}')
    async def revoke_code(code_id: str, request: Request):
        await admin(request)
        await asyncio.to_thread(store.revoke_code, code_id)
        return {'success': True}

    # Network-only replacement for the personal PWA cache. A dedicated server
    # origin is required; no API response may be replayed to the next account.
    @app.get('/sw.js')
    async def service_worker():
        return Response("self.addEventListener('install',()=>self.skipWaiting());"
            "self.addEventListener('activate',e=>e.waitUntil(caches.keys().then(ks=>Promise.all(ks.map(k=>caches.delete(k)))).then(()=>self.registration.unregister())));",
            media_type='text/javascript', headers={'Service-Worker-Allowed': '/'})

    @app.api_route('/{path:path}', methods=['GET', 'HEAD', 'OPTIONS', 'POST', 'PUT', 'PATCH', 'DELETE'])
    async def engine(path: str, request: Request):
        # Unknown auth routes must not fall through to a private engine.
        if path.startswith(('api/auth/', 'auth/')):
            raise HTTPException(404, 'Not found')
        user = await asyncio.to_thread(store.session, request.cookies.get(COOKIE, ''))
        if not user:
            if request.method == 'GET' and 'text/html' in request.headers.get('accept', ''):
                return RedirectResponse('/auth/login', status_code=303)
            raise HTTPException(401, 'Authentication required')
        check_action(user, '/' + path, request.method)
        if path == 'api/favorites' and request.method == 'POST' and not has_permission(user, 'download'):
            try:
                body = await request.json()
            except ValueError as exc:
                raise HTTPException(400, 'Invalid JSON') from exc
            if not isinstance(body, dict) or body.get('autoDownload'):
                raise HTTPException(403, 'Download permission required for automatic downloads')
        try:
            worker = await pool.get(user['id'], allow_download=has_permission(user, 'download'),
                authorize=lambda: asyncio.to_thread(store.session, request.cookies.get(COOKIE, ''), touch=False))
        except PermissionError as exc:
            raise HTTPException(401, 'Session was revoked') from exc
        except RuntimeError as exc:
            raise HTTPException(503, str(exc)) from exc
        if not await asyncio.to_thread(store.session, request.cookies.get(COOKIE, ''), touch=False):
            raise HTTPException(401, 'Session was revoked')
        # Forward only protocol headers needed by the app, never identity headers,
        # browser credentials, operator cookies or proxy forwarding headers.
        keep = {'accept', 'accept-language', 'content-type', 'range', 'if-range', 'if-none-match', 'if-modified-since'}
        headers = {key: value for key, value in request.headers.items() if key in keep}
        headers['x-animelab-worker'] = worker.token
        headers['accept-encoding'] = 'identity'
        lang = request.cookies.get('animan_lang')
        if lang in ('en', 'fr'):
            headers['cookie'] = 'animan_lang=' + lang
        raw = request.scope['raw_path']
        if request.scope['query_string']:
            raw += b'?' + request.scope['query_string']
        url = httpx.URL(f'http://127.0.0.1:{worker.port}').copy_with(raw_path=raw)
        outgoing = httpx.Request(request.method, url, headers=headers, content=await request.body())
        try:
            upstream = await app.state.client.send(outgoing, stream=True)
        except httpx.HTTPError as exc:
            raise HTTPException(502, 'Private engine connection failed') from exc

        async def stream():
            pending = None
            iterator = upstream.aiter_raw()
            checked_at = time.monotonic()
            is_media = path.startswith('api/media/stream')
            try:
                while True:
                    # Check even idle SSE connections; do not allow an expired
                    # or revoked session to remain subscribed indefinitely.
                    if pending is None:
                        pending = asyncio.create_task(anext(iterator))
                    done, _ = await asyncio.wait([pending], timeout=2)
                    if time.monotonic() - checked_at >= 2:
                        if not await asyncio.to_thread(store.session, request.cookies.get(COOKIE, ''), touch=is_media):
                            break
                        checked_at = time.monotonic()
                    if not done:
                        continue
                    try:
                        chunk = pending.result()
                    except StopAsyncIteration:
                        break
                    pending = None
                    yield chunk
            finally:
                if pending is not None:
                    pending.cancel()
                    with suppress(asyncio.CancelledError, StopAsyncIteration, httpx.HTTPError):
                        await pending
                await upstream.aclose()

        response_headers = {key: value for key, value in upstream.headers.items() if key not in HOP}
        # Keep byte lengths and Content-Range for seeking and HEAD requests.
        if 'content-length' in upstream.headers:
            response_headers['content-length'] = upstream.headers['content-length']
        location = response_headers.get('location', '')
        if location.startswith(f'http://127.0.0.1:{worker.port}'):
            response_headers['location'] = location[len(f'http://127.0.0.1:{worker.port}'):]
        response = StreamingResponse(stream(), status_code=upstream.status_code, headers=response_headers)
        for cookie in upstream.headers.get_list('set-cookie'):
            if cookie.startswith('animan_lang='):
                response.headers.append('set-cookie', cookie + ('; Secure' if config.secure else ''))
        return response

    app.add_middleware(BodyLimit)
    app.add_middleware(TrustedHostMiddleware,
        allowed_hosts=[urlsplit(config.public_url).hostname, '127.0.0.1', 'localhost'], www_redirect=False)
    if config.trusted_proxies:
        app.add_middleware(ProxyHeadersMiddleware, trusted_hosts=list(config.trusted_proxies))
    return app
