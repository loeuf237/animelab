"""A09 boundaries: real sessions, two independent engines and local media bytes."""
import asyncio
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
from types import SimpleNamespace
import uuid

import httpx
import pytest
from fastapi.testclient import TestClient

from animelab.shared import accounts as account_module
from animelab.shared.accounts import Accounts, digest, password_hash, password_matches
from animelab.shared.gateway import COOKIE, SharedConfig, create_app, Attempts
from animelab.shared.workers import WorkerBoundary, Workers

PASSWORD = 'Test-only password 42!'
ORIGIN = 'https://testserver'


@pytest.fixture
def accounts(tmp_path, monkeypatch):
    # Most tests exercise DB/authorization, without repeating 128 MiB hashes.
    # The dedicated hashing test below runs the real production work factor.
    monkeypatch.setattr(account_module, 'SCRYPT_N', 1024)
    store = Accounts(tmp_path / 'shared')
    store.create('admin', PASSWORD, admin=True)
    return store


def test_production_password_hash_is_salted_and_not_reversible():
    assert account_module.SCRYPT_N == 2 ** 17
    first, second = password_hash(PASSWORD), password_hash(PASSWORD)
    assert first != second and PASSWORD not in first
    assert password_matches(PASSWORD, first)
    assert not password_matches('wrong password 42', first)
    with pytest.raises(ValueError):
        password_hash('short')


def test_session_expiry_revocation_and_last_administrator(accounts):
    identity = accounts.create('alice', PASSWORD)
    token = accounts.new_session(identity)
    assert accounts.session(token)['username'] == 'alice'
    with accounts.connect() as db:
        assert db.execute('SELECT token FROM sessions').fetchone()[0] == digest(token)
        db.execute('UPDATE sessions SET touched=?', (time.time() - accounts.idle - 1,))
    assert accounts.session(token) is None
    token = accounts.new_session(identity)
    accounts.update(identity, permissions=[])
    assert accounts.session(token) is None
    accounts.update(identity, enabled=False)
    assert accounts.authenticate('alice', PASSWORD) is None
    administrator = accounts.users()[0]
    with pytest.raises(ValueError, match='last administrator'):
        accounts.update(administrator['id'], admin=False)
    with pytest.raises(ValueError, match='last administrator'):
        accounts.update(administrator['id'], enabled=False)
    with pytest.raises(ValueError):
        accounts.create('../alice', PASSWORD)
    with pytest.raises(ValueError):
        accounts.create('alice', PASSWORD)


def test_invitation_recovery_codes_are_single_use_expiring_and_revocable(accounts):
    code = accounts.code(permissions=[])
    identity = accounts.redeem(code, PASSWORD, 'bob')
    assert accounts.authenticate('bob', PASSWORD)['permissions'] == []
    with pytest.raises(ValueError, match='Invalid or expired'):
        accounts.redeem(code, PASSWORD, 'charlie')
    session = accounts.new_session(identity)
    recovery = accounts.code(user_id=identity)
    replacement = accounts.code(user_id=identity)
    with pytest.raises(ValueError, match='Invalid or expired'):
        accounts.redeem(recovery, PASSWORD)
    accounts.redeem(replacement, 'A different password 42!')
    assert accounts.session(session) is None
    assert accounts.authenticate('bob', 'A different password 42!')
    expired = accounts.code()
    with accounts.connect() as db:
        db.execute('UPDATE codes SET expires=0')
    with pytest.raises(ValueError):
        accounts.redeem(expired, PASSWORD, 'charlie')
    code = accounts.code()
    listed = accounts.codes()[0]
    assert code != listed['id'] and listed['id'] == digest(code)
    accounts.revoke_code(listed['id'])
    assert accounts.codes() == []
    with pytest.raises(ValueError):
        accounts.redeem(code, PASSWORD, 'charlie')


class Bytes(httpx.AsyncByteStream):
    async def __aiter__(self):
        yield b'abcdef'


class FakeWorkers:
    def __init__(self):
        self.running = {}
        self.stopped = []
    async def get(self, identity, **kwargs):
        self.running[identity] = SimpleNamespace(port=12345, token='private-engine-secret')
        return self.running[identity]
    async def stop(self, identity):
        self.running.pop(identity, None)
        self.stopped.append(identity)
    async def change(self, identity, action):
        await action()
        await self.stop(identity)
    async def close(self):
        self.running.clear()


def login(client, username='admin'):
    client.cookies.clear()
    response = client.post('/api/auth/login', json={'username': username, 'password': PASSWORD}, headers={'Origin': ORIGIN})
    assert response.status_code == 200, response.text
    return { 'Cookie': f'{COOKIE}={client.cookies.get(COOKIE)}', 'Origin': ORIGIN }


def test_gateway_guards_proxy_headers_permissions_csrf_and_media(accounts):
    accounts.create('alice', PASSWORD, permissions=[])
    calls = []
    def upstream(request):
        calls.append(request)
        return httpx.Response(206, headers={'content-range': 'bytes 0-5/20', 'content-length': '6',
            'set-cookie': 'private=must-not-leak'}, stream=Bytes())
    pool = FakeWorkers()
    app = create_app(SharedConfig(accounts.root, ORIGIN), accounts=accounts, workers=pool,
                     transport=httpx.MockTransport(upstream))
    with TestClient(app, base_url=ORIGIN) as client:
        for path in ('/api/favorites', '/api/download/status', '/api/media/stream/id', '/static/img/logo.jpg'):
            assert client.get(path).status_code == 401
        assert client.get('/app/', headers={'Accept': 'text/html'}, follow_redirects=False).headers['location'] == '/auth/login'
        assert client.get('/auth/login').status_code == 200
        assert client.get('/healthz', headers={'Host': 'evil.example'}).status_code == 400
        assert client.post('/api/auth/login', json={}).status_code == 403
        assert client.post('/api/auth/login', json={}, headers={'Origin': 'http://testserver'}).status_code == 403
        assert client.post('/api/auth/login', content='{}', headers={'Origin': ORIGIN}).status_code == 415
        assert client.post('/api/auth/login', content='x' * (2 * 1024 * 1024 + 1), headers={'Origin': ORIGIN}).status_code == 413
        alice = login(client, 'alice')
        for path in ('/api/auth/users', '/api/auth/codes'):
            assert client.get(path, headers=alice).status_code == 403
        for path in ('/api/download', '/api/extensions/refresh', '/api/favorites/auto-download', '/api/proxy/settings'):
            assert client.post(path, json={}, headers=alice).status_code == 403
        assert client.post('/api/auth/users', json={'username': 'other', 'password': PASSWORD}, headers=alice).status_code == 403
        assert client.post('/api/favorites', json={'autoDownload': True}, headers=alice).status_code == 403
        response = client.get('/api/media/stream/id', headers={**alice, 'Range': 'bytes=0-5',
            'X-Animelab-Worker': 'spoof', 'Authorization': 'Bearer spoof', 'X-User-Id': 'someone-else'})
        assert response.status_code == 206 and response.content == b'abcdef'
        assert response.headers['content-range'] == 'bytes 0-5/20'
        assert response.headers['cache-control'] == 'no-store'
        assert response.headers.get('set-cookie') is None
        forwarded = calls[-1]
        assert forwarded.headers['x-animelab-worker'] == 'private-engine-secret'
        assert 'cookie' not in forwarded.headers and 'authorization' not in forwarded.headers
        assert 'x-user-id' not in forwarded.headers
        client.post('/api/auth/logout', json={}, headers=alice)
        assert client.get('/api/favorites', headers=alice).status_code == 401
        administrator = login(client)
        assert client.post('/api/auth/users', json={'username': 'charlie', 'password': PASSWORD}, headers=administrator).status_code == 200
        identity = next(user['id'] for user in accounts.users() if user['username'] == 'alice')
        assert client.patch('/api/auth/users/' + identity, json={'enabled': False}, headers=administrator).status_code == 200
        assert identity in pool.stopped
        assert client.get('/api/auth/unknown', headers=administrator).status_code == 404


@pytest.mark.asyncio
async def test_private_worker_requires_capability_for_http_and_websocket():
    called = []
    async def downstream(scope, receive, send):
        called.append(scope['path'])
    middleware = WorkerBoundary(downstream, 's' * 43)
    for kind in ('http', 'websocket'):
        messages = []
        async def send(message): messages.append(message)
        async def receive(): return {'type': 'http.request', 'body': b''}
        await middleware({'type': kind, 'path': '/api/media/stream/id', 'headers': []}, receive, send)
        assert messages[0].get('status', messages[0].get('code')) in (401, 1008)
    assert called == []
    messages = []
    await middleware({'type': 'http', 'path': '/api/network/verification',
                      'headers': [(b'x-animelab-worker', b's' * 43)]}, receive, send)
    assert messages[0]['status'] == 403


def test_worker_environment_never_inherits_operator_sessions_or_proxy(tmp_path, monkeypatch):
    monkeypatch.setenv('ANIMAN_ANIMEPAHE_COOKIE', 'operator-secret')
    monkeypatch.setenv('HTTP_PROXY', 'http://operator-proxy')
    monkeypatch.setenv('GITHUB_TOKEN', 'operator-secret')
    pool = Workers(tmp_path)
    first, second = pool.home(uuid.uuid4().hex), pool.home(uuid.uuid4().hex)
    env = pool.environment(first, 'worker-secret')
    assert first != second and env['HOME'] == str(first)
    assert env['ANIMAN_DOWNLOAD_DIR'].startswith(str(first))
    assert env['TMPDIR'].startswith(str(first))
    for key in ('ANIMAN_ANIMEPAHE_COOKIE', 'HTTP_PROXY', 'GITHUB_TOKEN'):
        assert key not in env
    with pytest.raises(ValueError):
        pool.home('../another-account')


def test_rate_limit_and_public_tls_policy(tmp_path):
    attempts = Attempts()
    for _ in range(10): attempts.check('one-client')
    with pytest.raises(Exception) as error:
        attempts.check('one-client')
    assert error.value.status_code == 429
    with pytest.raises(ValueError, match='HTTPS'):
        SharedConfig(tmp_path, 'http://192.168.1.5:8080')
    with pytest.raises(ValueError):
        SharedConfig(tmp_path, 'https://example.org/app/')


def test_actual_engines_isolate_libraries_settings_media_and_restart(accounts):
    alice_id = accounts.create('alice', PASSWORD)
    bob_id = accounts.create('bob', PASSWORD)
    pool = Workers(accounts.root, max_workers=2)
    app = create_app(SharedConfig(accounts.root, ORIGIN, 2), accounts=accounts, workers=pool)
    with TestClient(app, base_url=ORIGIN) as client:
        alice, bob = login(client, 'alice'), login(client, 'bob')
        response = client.post('/api/favorites', json={'url': 'https://source.example/anime', 'title': 'Private Alice'}, headers=alice)
        assert response.status_code == 200, response.text
        assert client.get('/api/favorites', headers=bob).json() == []
        assert client.get('/api/favorites', headers=alice).json()[0]['title'] == 'Private Alice'
        assert client.post('/api/download/settings', json={'maxConcurrentDownloads': 1}, headers=alice).status_code == 200
        assert client.get('/api/download/settings', headers=bob).json()['maxConcurrentDownloads'] == 3
        assert client.get('/api/download/settings', headers=alice).json()['maxConcurrentDownloads'] == 1
        assert client.post('/api/network/verification', json={'domain': 'source.example'}, headers=alice).status_code == 403
        # Direct access, even with the browser's authenticated cookie, cannot bypass the gateway.
        worker = pool.running[alice_id]
        direct = httpx.get(f'http://127.0.0.1:{worker.port}/api/favorites', headers=alice, trust_env=False)
        assert direct.status_code == 401
        task_id = str(uuid.uuid4())
        media = pool.home(alice_id) / 'downloads' / 'private.mp4'
        media.write_bytes(bytes(range(256)) * 64)
        # Seed a completed local file using the actual ORM defaults, then restart.
        from sqlalchemy.orm import Session
        from animelab.database import create_database_engine
        from animelab.models.download_task import DownloadTaskEntity
        engine = create_database_engine('sqlite:///' + str(pool.home(alice_id) / '.animan/db/animan.sqlite3'))
        with Session(engine) as db:
            db.add(DownloadTaskEntity(id=task_id, animeName='Private', fileName='private.mp4',
                savePath=str(media), status='COMPLETED', progress=100, downloadedBytes=media.stat().st_size,
                totalBytes=media.stat().st_size))
            db.commit()
        engine.dispose()
        client.portal.call(pool.stop, alice_id)
        response = client.get('/api/media/stream/' + task_id, headers={**alice, 'Range': 'bytes=10-25'})
        assert response.status_code == 206, response.text
        assert response.content == media.read_bytes()[10:26]
        assert client.head('/api/media/stream/' + task_id, headers=alice).headers['content-length'] == str(media.stat().st_size)
        assert client.get('/api/media/stream/' + task_id, headers=bob).status_code == 404
        assert client.post('/api/download/' + task_id + '/pause', json={}, headers=bob).status_code == 400
        assert client.get('/api/download/status', headers=bob).json() == []
        assert client.get('/api/favorites', headers=alice).json()[0]['title'] == 'Private Alice'
        assert pool.home(alice_id) != pool.home(bob_id)
        # Revocation stops the real engine and a new read-only login does not
        # reactivate scheduled work through startup/watchdog side effects.
        old_process = pool.running[alice_id].process
        administrator = login(client)
        assert client.patch('/api/auth/users/' + alice_id, json={'permissions': []}, headers=administrator).status_code == 200
        assert old_process.poll() is not None
        assert client.get('/api/favorites', headers=alice).status_code == 401
        alice = login(client, 'alice')
        assert client.get('/api/favorites', headers=alice).status_code == 200
        assert client.post('/api/download/resume-all', json={}, headers=alice).status_code == 403
        processes = [item.process for item in pool.running.values()]
    assert all(process.poll() == 0 for process in processes)


def test_login_cannot_race_with_password_reset(accounts, monkeypatch):
    original = accounts._verified_record
    def concurrent_reset(username, password):
        row = original(username, password)
        accounts.update(row['id'], password='Changed by administrator 42!')
        return row
    monkeypatch.setattr(accounts, '_verified_record', concurrent_reset)
    assert accounts.login('admin', PASSWORD) is None


def test_password_change_revokes_all_sessions_and_pending_recovery(accounts):
    identity = accounts.create('alice', PASSWORD)
    one, two = accounts.new_session(identity), accounts.new_session(identity)
    recovery = accounts.code(user_id=identity)
    accounts.change_password(one, PASSWORD, 'Another good password 42!')
    assert accounts.session(one) is None and accounts.session(two) is None
    with pytest.raises(ValueError):
        accounts.redeem(recovery, PASSWORD)
    with pytest.raises(ValueError):
        accounts.change_password(two, 'Another good password 42!', PASSWORD)


@pytest.mark.asyncio
async def test_revoked_request_cannot_start_a_worker(accounts):
    pool = Workers(accounts.root)
    async def deny(): return None
    with pytest.raises(PermissionError):
        await pool.get(accounts.users()[0]['id'], authorize=deny)
    assert pool.running == {}


@pytest.mark.asyncio
async def test_idle_sse_connection_closes_after_session_revocation(accounts):
    identity = accounts.users()[0]['id']
    token = accounts.new_session(identity)
    started = asyncio.Event()
    closed = []
    class IdleStream(httpx.AsyncByteStream):
        async def __aiter__(self):
            started.set()
            yield b'event: download-update\ndata: []\n\n'
            await asyncio.Event().wait()
        async def aclose(self): closed.append(True)
    def upstream(request):
        return httpx.Response(200, headers={'content-type': 'text/event-stream'}, stream=IdleStream())
    app = create_app(SharedConfig(accounts.root, ORIGIN), accounts=accounts, workers=FakeWorkers(),
                     transport=httpx.MockTransport(upstream))
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=ORIGIN) as client:
            task = asyncio.create_task(client.get('/api/download/stream', headers={'Cookie': COOKIE + '=' + token}))
            await asyncio.wait_for(started.wait(), timeout=2)
            accounts.revoke(token)
            response = await asyncio.wait_for(task, timeout=5)
            assert response.status_code == 200
            assert closed
