"""Bounded, supervised engine processes with an independent HOME per account."""
import asyncio
import hashlib
from dataclasses import dataclass
import json
import os
from animelab.environment import with_aliases
from pathlib import Path
import re
import secrets
import subprocess
import sys
import time

import httpx


@dataclass
class Worker:
    process: subprocess.Popen
    token: str
    port: int


class Workers:
    def __init__(self, root, *, max_workers=4, startup_timeout=60):
        self.root = Path(root).resolve()
        self.max_workers = max_workers
        self.startup_timeout = startup_timeout
        self.running = {}
        self.lock = asyncio.Lock()
        self.closed = False

    def home(self, user_id):
        if not re.fullmatch(r'[0-9a-f]{32}', user_id):
            raise ValueError('Invalid account identity')
        return self.root / 'users' / user_id

    def environment(self, home, token):
        # Do not inherit the operator's source cookies, proxy, API credentials or HOME.
        env = {key: os.environ[key] for key in (
            'PATH', 'SYSTEMROOT', 'WINDIR', 'COMSPEC', 'LANG', 'LC_ALL',
            'SSL_CERT_FILE', 'SSL_CERT_DIR', 'LD_LIBRARY_PATH',
            'ANIMELAB_CHROMIUM_PATH', 'ANIMELAB_CHROMIUM_HEADLESS',
            'ANIMELAB_MEDIA_DOMAINS',
        ) if key in os.environ}
        for folder in (home, home / 'tmp', home / '.animan' / 'db', home / 'downloads'):
            folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        home.chmod(0o700)
        env.update({
            'HOME': str(home), 'USERPROFILE': str(home),
            'TMPDIR': str(home / 'tmp'), 'TMP': str(home / 'tmp'), 'TEMP': str(home / 'tmp'),
            'XDG_CACHE_HOME': str(home / '.cache'), 'XDG_CONFIG_HOME': str(home / '.config'),
            'ANIMAN_DB_PATH': str(home / '.animan' / 'db' / 'animan.sqlite3'),
            'ANIMAN_CACHE_DIR': str(home / '.animan' / 'cache'),
            'ANIMAN_DOWNLOAD_DIR': str(home / 'downloads'),
            'ANIMAN_HOST': '127.0.0.1', 'ANIMAN_ALLOWED_HOSTS': '127.0.0.1',
            'ANIMAN_STARTUP_REFRESH': 'false', 'ANIMAN_RELOAD': 'false',
            'ANIMELAB_SHARED_WORKER_TOKEN': token, 'ANIMELAB_SHARED_WORKER': '1',
            'PYTHONDONTWRITEBYTECODE': '1', 'PYTHONUNBUFFERED': '1',
        })
        return with_aliases(env)

    async def get(self, user_id, *, allow_download=True, authorize=None):
        async with self.lock:
            if self.closed:
                raise RuntimeError('Server is shutting down')
            if authorize is not None and not await authorize():
                raise PermissionError('Session was revoked')
            worker = self.running.get(user_id)
            if worker and worker.process.poll() is None:
                return worker
            self.running.pop(user_id, None)
            # Reap stopped workers before applying the active engine limit.
            for identity, item in list(self.running.items()):
                if item.process.poll() is not None:
                    item.process.stdin.close()
                    self.running.pop(identity)
            if len(self.running) >= self.max_workers:
                raise RuntimeError('Active account limit reached; ask the administrator to stop an unused engine')
            home = self.home(user_id)
            token = secrets.token_urlsafe(32)
            env = self.environment(home, token)
            env['ANIMELAB_SHARED_DOWNLOAD'] = '1' if allow_download else '0'
            ready = home / 'ready.json'
            ready.unlink(missing_ok=True)
            log = home / 'engine.log'
            with log.open('ab') as output:
                log.chmod(0o600)
                command = ([sys.executable, '--account-worker'] if getattr(sys, 'frozen', False)
                           else [sys.executable, '-m', 'animelab.shared.worker'])
                process = subprocess.Popen(
                    command,
                    cwd=Path(__file__).resolve().parents[2], env=env,
                    stdin=subprocess.PIPE, stdout=output, stderr=subprocess.STDOUT,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0,
                )
            worker = Worker(process, token, 0)
            self.running[user_id] = worker
            try:
                deadline = time.monotonic() + self.startup_timeout
                while time.monotonic() < deadline:
                    if process.poll() is not None:
                        raise RuntimeError('Private engine failed to start; inspect its engine.log on the server')
                    try:
                        value = json.loads(ready.read_text())
                        # Windows venv redirectors may report a different child PID.
                        # Match this launch's unique capability digest, not the wrapper PID.
                        if value.get('instance') == hashlib.sha256(token.encode()).hexdigest() and 0 < value['port'] < 65536:
                            worker.port = value['port']
                            return worker
                    except (OSError, ValueError, KeyError, TypeError):
                        pass
                    await asyncio.sleep(0.1)
                raise RuntimeError('Private engine startup timed out')
            except BaseException:
                await self._stop(worker)
                self.running.pop(user_id, None)
                raise

    async def _stop(self, worker):
        # EOF is also the orphan-safety signal when the gateway crashes.
        worker.process.stdin.close()
        try:
            await asyncio.wait_for(asyncio.to_thread(worker.process.wait), timeout=45)
        except TimeoutError:
            worker.process.terminate()
            try:
                await asyncio.wait_for(asyncio.to_thread(worker.process.wait), timeout=5)
            except TimeoutError:
                worker.process.kill()
                await asyncio.to_thread(worker.process.wait)

    async def stop(self, user_id):
        async with self.lock:
            worker = self.running.pop(user_id, None)
            if worker:
                await self._stop(worker)

    async def change(self, user_id, action):
        # Serialize role changes with worker startup: a stale in-flight request
        # must not restart automatic jobs after a permission has been revoked.
        async with self.lock:
            await action()
            worker = self.running.pop(user_id, None)
            if worker:
                await self._stop(worker)

    async def close(self):
        async with self.lock:
            self.closed = True
            workers, self.running = list(self.running.values()), {}
        await asyncio.gather(*(self._stop(worker) for worker in workers))


class WorkerBoundary:
    """Capability checked before every route, static file, stream or socket."""
    def __init__(self, app, token):
        self.app, self.token = app, token.encode()
        from animelab.diagnostics import remember_secret
        remember_secret(token)

    async def __call__(self, scope, receive, send):
        if scope['type'] not in ('http', 'websocket'):
            return await self.app(scope, receive, send)
        import hmac
        from starlette.responses import JSONResponse
        supplied = dict(scope.get('headers', [])).get(b'x-animelab-worker', b'')
        if not hmac.compare_digest(supplied, self.token):
            if scope['type'] == 'websocket':
                return await send({'type': 'websocket.close', 'code': 1008})
            return await JSONResponse({'error': 'Authentication required'}, status_code=401)(scope, receive, send)
        # A remote account must never launch a browser or an OS storage picker on the host.
        path = scope['path']
        headless = os.getenv('ANIMELAB_CHROMIUM_HEADLESS', '').lower() in ('1', 'true', 'yes')
        blocked = path.startswith('/api/system/android') or (path.startswith('/api/network/verification') and not headless)
        if blocked:
            return await JSONResponse({'error': 'Host device actions are unavailable on a shared server'}, status_code=403)(scope, receive, send)
        return await self.app(scope, receive, send)
