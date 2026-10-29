"""Own exactly one child engine; serialize restarts and never kill by port/PID file."""
import json
from contextlib import closing
import os
import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
import queue
import signal
import shutil
import socket
import sqlite3
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser

from animelab import __version__
from animelab.diagnostics import redact_text
from .control import ControlServer
from .state import valid_port, write_json
from .options import engine_environment, normalize_config, preferences, ui_path

logger = logging.getLogger('animelab.desktop')


def launcher_command():
    if getattr(sys, 'frozen', False):
        return [sys.executable]
    return [sys.executable, str(Path(__file__).resolve().parents[2] / 'desktop.py')]


def choose_port(preferred):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        if os.name != 'nt':
            # Match asyncio's Unix listener: a stopped engine may leave accepted
            # connections in TIME_WAIT, which must not force a new application URL.
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            sock.bind(('127.0.0.1', preferred))
        except OSError:
            sock.bind(('127.0.0.1', 0))
        return sock.getsockname()[1]


class Supervisor:
    def __init__(self, directory, config, headless=False, admin=False):
        self.directory, self.config = directory, config
        self.headless, self.admin = headless, admin
        self.process = None
        self.workspace = None
        self.console_thread = None
        self.commands = queue.Queue()
        self.lock = threading.RLock()
        self.started_at = time.monotonic()
        self.port = None
        self.ready = False
        self.error = None
        self.native_error = None
        self.busy = False
        self.mode = self.interface_mode()
        self.launch_config = dict(config)
        self.port_fallback = False
        self.control = ControlServer(self)

    def interface_mode(self):
        return 'browser' if self.headless or self.admin or self.config['browser'] or not preferences(self.config)['openUi'] else 'native'

    def status(self):
        with self.lock:
            return {'application': 'AnimeLab', 'version': __version__, 'instanceId': self.control.token[:16],
                    'running': bool(self.process and self.process.poll() is None),
                    'ready': self.ready, 'busy': self.busy, 'port': self.port,
                    'url': f'http://127.0.0.1:{self.port}' + ui_path(self.config) if self.ready else None,
                    'configuredPort': self.config['port'], 'browser': self.config['browser'],
                    'portFallback': self.port_fallback,
                    'pendingRestart': self.config != self.launch_config,
                    'authMode': preferences(self.launch_config)['authMode'],
                    'mode': self.mode, 'error': self.error, 'nativeError': self.native_error,
                    'uptimeSeconds': round(time.monotonic() - self.started_at)}

    def save_config(self, data):
        if not isinstance(data, dict) or set(data) != {'port', 'browser'} or type(data['browser']) is not bool:
            raise ValueError('Expected port and browser settings')
        config = {'port': valid_port(data['port']), 'browser': data['browser']}
        with self.lock:
            config = {**self.config, **config}
            write_json(self.directory / 'config.json', config)
            self.config = config

    def save_launcher_config(self, data):
        config = normalize_config(data)
        with self.lock:
            write_json(self.directory / 'config.json', config)
            self.config = config

    def command(self, action):
        # Coalesce double clicks: a second restart must not interrupt another restart.
        with self.lock:
            if self.busy and action != 'stop':
                return
            self.busy = True
            self.commands.put(action)

    def diagnose(self):
        checks = []

        def check(name, operation):
            try:
                detail = operation()
                checks.append({'name': name, 'ok': True, 'detail': str(detail or 'OK')})
            except Exception as error:
                checks.append({'name': name, 'ok': False, 'detail': redact_text(error)})

        base = Path(sys._MEIPASS) if getattr(sys, 'frozen', False) else Path(__file__).resolve().parents[2]

        def frontend():
            root = base / 'frontend' / 'dist'
            if not (root / 'index.html').is_file() or not list((root / 'assets').glob('*.js')):
                raise RuntimeError('Compiled frontend is missing')

        def writable(path):
            path.mkdir(parents=True, exist_ok=True)
            with tempfile.TemporaryFile(dir=path) as handle:
                handle.write(b'AnimeLab desktop check')

        def database():
            # Importing config is safe; never import the engine or export its contents.
            from animelab.config import settings
            path = Path(settings.DATABASE_PATH).resolve()
            if not path.is_file():
                return 'Database not created yet'
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=2)) as db:
                if db.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                    raise RuntimeError('SQLite quick_check failed')

        def backend():
            status = self.status()
            if not status['ready']:
                raise RuntimeError('Local engine is not ready')
            shared = status['authMode'] == 'accounts'
            path = '/healthz' if shared else '/openapi.json'
            with build_opener(ProxyHandler({})).open(
                    f"http://127.0.0.1:{status['port']}{path}", timeout=3) as response:
                payload = json.load(response)
                if (payload.get('version') if shared else payload['info']['version']) != __version__:
                    raise RuntimeError('Unexpected engine version')

        from animelab.config import settings
        check('frontend', frontend)
        check('desktop_storage', lambda: writable(self.directory))
        check('download_storage', lambda: writable(Path(settings.DOWNLOAD_DIR)))
        check('database', database)
        for tool in ('ffmpeg', 'ffprobe'):
            def media(name=tool):
                path = shutil.which(name)
                if not path:
                    raise RuntimeError(f'{name} is missing')
                result = subprocess.run([path, '-version'], stdin=subprocess.DEVNULL, capture_output=True,
                                        text=True, timeout=5, check=True)
                return result.stdout.splitlines()[0]
            check(tool, media)
        check('backend', backend)
        # Deliberate allowlist: never include cookies, URLs to sources, env, task names, or logs.
        status = self.status()
        return {'schemaVersion': 1, 'version': __version__, 'platform': sys.platform,
                'port': status['port'], 'configuredPort': status['configuredPort'],
                'mode': status['mode'], 'checks': checks, 'ok': all(row['ok'] for row in checks)}

    def start_engine(self):
        with self.lock:
            self.busy, self.ready, self.error = True, False, None
            self.launch_config = dict(self.config)
            self.port = choose_port(self.config['port'])
            self.port_fallback = self.port != self.config['port']
            self.workspace = tempfile.TemporaryDirectory(prefix='engine-', dir=self.directory)
            self.workdir = Path(self.workspace.name)
            args = launcher_command() + ['--worker', str(self.workdir), '--port', str(self.port),
                                        '--control-url', self.control.url]
            if self.mode == 'browser':
                args += ['--headless']
            self.process = subprocess.Popen(args, stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                                            stderr=subprocess.STDOUT, bufsize=0,
                                            env={**os.environ, **engine_environment(self.config, self.directory)})
            self.console_thread = threading.Thread(target=self.capture_console, args=(self.process.stdout,), daemon=True)
            self.console_thread.start()
        deadline = time.monotonic() + 35
        while self.process.poll() is None and time.monotonic() < deadline:
            if (self.workdir / 'ready').is_file():
                with self.lock:
                    self.ready = True
                break
            if not self.commands.empty():
                break
            time.sleep(.1)
        with self.lock:
            self.busy = False
            if not self.ready:
                self.error = 'Engine failed to start. Run diagnostics; see engine.log in the desktop data folder.'
        logger.info('Desktop engine ready=%s on port %s', self.ready, self.port)

    def capture_console(self, stream):
        # Drain the pipe continuously, but keep even native crash output bounded.
        handler = RotatingFileHandler(self.directory / 'engine-console.log', maxBytes=1_000_000,
                                      backupCount=1, encoding='utf-8')
        try:
            while chunk := stream.read(8192):
                handler.emit(logging.LogRecord('desktop.console', logging.INFO, '', 0,
                    redact_text(chunk.decode('utf-8', errors='replace')), (), None))
        finally:
            handler.close()
            stream.close()

    def stop_engine(self):
        if self.process is not None:
            if self.process.poll() is None:
                (self.workdir / 'stop').touch()
                try:
                    self.process.wait(timeout=65 if preferences(self.launch_config)['authMode'] == 'accounts' else 30)
                except subprocess.TimeoutExpired:
                    # This Popen handle is our own child, never a user-supplied PID/port.
                    logger.error('Engine did not stop gracefully; terminating the owned child')
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                        self.process.wait(timeout=5)
            with self.lock:
                self.process = None
            if self.console_thread:
                self.console_thread.join(timeout=5)
        with self.lock:
            self.ready = False
        if self.workspace:
            self.workspace.cleanup()
            self.workspace = None

    def run(self):
        previous_term = None
        if threading.current_thread() is threading.main_thread():
            previous_term = signal.signal(signal.SIGTERM, lambda *_: self.command('stop'))
        self.control.start()
        write_json(self.directory / 'runtime.json', {'port': self.control.server.server_port,
                   'token': self.control.token, 'instanceId': self.control.token[:16]})
        try:
            try:
                self.start_engine()
            except Exception:
                logger.exception('Engine startup failed')
                self.error, self.busy = 'Engine startup failed. Run diagnostics.', False
            if not self.headless and preferences(self.config)['openUi'] and (self.admin or self.mode == 'browser' or not self.ready):
                webbrowser.open(self.control.url if self.admin or not self.ready else self.status()['url'])
            gui_deadline = time.monotonic() + 30
            while True:
                try:
                    command = self.commands.get(timeout=.2)
                except queue.Empty:
                    command = None
                if command == 'stop':
                    break
                if command == 'restart':
                    self.stop_engine()
                    self.mode = self.interface_mode()
                    try:
                        self.start_engine()
                    except Exception:
                        logger.exception('Engine restart failed')
                        self.error, self.busy = 'Engine restart failed. Run diagnostics.', False
                    gui_deadline = time.monotonic() + 30
                    if self.ready and not self.headless and self.mode == 'browser' and preferences(self.config)['openUi']:
                        webbrowser.open(self.status()['url'])
                if self.process is None:
                    continue  # The admin console remains available after a failed start.
                code = self.process.poll()
                if code is None and not self.ready and (self.workdir / 'ready').is_file():
                    with self.lock:
                        self.ready, self.error = True, None
                shown = (self.workdir / 'shown').is_file()
                if code is None and (self.mode != 'native' or shown or time.monotonic() < gui_deadline):
                    continue
                if self.mode == 'native' and (code != 0 or not shown):
                    self.native_error = 'Native window unavailable. Using the installed browser; see engine.log.'
                    logger.warning(self.native_error)
                    self.stop_engine()
                    self.mode = 'browser'
                    try:
                        self.start_engine()
                    except Exception:
                        logger.exception('Browser fallback engine failed')
                        self.error, self.busy = 'Engine startup failed. Run diagnostics.', False
                    if not self.headless:
                        webbrowser.open(self.control.url)
                elif self.mode == 'native' and code == 0:
                    break  # Normal window close means normal application shutdown.
                elif code is not None:
                    self.error = 'Engine stopped unexpectedly. Run diagnostics or restart.'
                    self.stop_engine()
        except KeyboardInterrupt:
            pass
        finally:
            self.stop_engine()
            self.control.close()
            (self.directory / 'runtime.json').unlink(missing_ok=True)
            if previous_term is not None:
                signal.signal(signal.SIGTERM, previous_term)
