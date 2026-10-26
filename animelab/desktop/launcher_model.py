"""Native launcher's operations. No GUI imports, no engine imports before launch."""
import json
from contextlib import closing
import os
from animelab.environment import getenv
from pathlib import Path
import shutil
import socket
import sqlite3
import subprocess
import time
from urllib.request import ProxyHandler, Request, build_opener
import webbrowser

from .control import remote_call, running_record
from .options import normalize_config, preferences, PAGES, shared_directory
from .state import load_config, write_json
from .supervisor import launcher_command, Supervisor


class LauncherModel:
    def __init__(self, directory):
        self.directory = directory
        self.child = None

    def config(self):
        data = load_config(self.directory)
        if not (self.directory / 'config.json').exists():
            data['browser'] = True
        if 'launcher' not in data:
            path = Path(getenv('ANIMAN_DB_PATH', str(self.directory.parent / 'db/animan.sqlite3')))
            if path.is_file():
                try:
                    with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                        row = db.execute('SELECT max_concurrent, global_limit, plex_org FROM download_preferences WHERE id=1').fetchone()
                    if row:
                        data['launcher'] = {'maxConcurrentDownloads': row[0], 'globalSpeedLimit': row[1],
                                            'plexOrganization': bool(row[2])}
                except sqlite3.Error:
                    pass  # Older schemas remain viewable; diagnostics can report corruption.
        return normalize_config(data)

    def status(self):
        try:
            return remote_call(running_record(self.directory), timeout=2)
        except (OSError, ValueError):
            return {'running': False, 'ready': False, 'busy': False, 'url': None}

    def save(self, data):
        config = normalize_config(data)
        if self.status().get('instanceId'):
            remote_call(running_record(self.directory), '/api/launcher-config', config)
        else:
            write_json(self.directory / 'config.json', config)
        return config

    def wait_ready(self):
        deadline = time.monotonic() + 65
        while time.monotonic() < deadline:
            state = self.status()
            if state.get('ready') and not state.get('busy'):
                return state
            if state.get('error') and not state.get('running'):
                raise RuntimeError('Engine failed to start. Open the diagnostic tab or engine.log.')
            if self.child is not None and self.child.poll() is not None:
                raise RuntimeError('The desktop server exited. Open the diagnostic tab or desktop.log.')
            time.sleep(.2)
        raise RuntimeError('Engine startup timed out. Open the diagnostic tab.')

    def launch(self, config, native=False):
        values = normalize_config(config)
        if values['launcher']['authMode'] == 'accounts' and not self.authentication_status()['configured']:
            raise ValueError('Create the first administrator in the Authentication tab before starting')
        if native:
            values['browser'] = False
            values['launcher']['openUi'] = True
        self.save(values)
        state = self.status()
        wants_native = not values['browser'] and preferences(values)['openUi']
        if state.get('running') and wants_native and state.get('mode') != 'native':
            self.stop()
            state = self.status()
        if state.get('instanceId'):
            if not state.get('running'):
                return self.restart(values)
            if state.get('pendingRestart'):
                return self.restart(values)
            if state.get('ready') and preferences(values)['openUi'] and values['browser']:
                self.open_page(preferences(values)['startPage'])
            return state
        flags = {'creationflags': subprocess.CREATE_NO_WINDOW} if os.name == 'nt' else {'start_new_session': True}
        self.child = subprocess.Popen(launcher_command() + ['--launch'], stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, **flags)
        return self.wait_ready()

    def restart(self, config):
        self.save(config)
        # Replace the supervisor as well: an instance originally started with
        # --headless must honor a later native/browser choice in this launcher.
        self.stop()
        return self.launch(config)

    def stop(self):
        if not self.status().get('instanceId'):
            return
        record = running_record(self.directory)
        remote_call(record, '/api/action', {'action': 'stop'})
        deadline = time.monotonic() + 80
        while time.monotonic() < deadline:
            try:
                remote_call(record, timeout=2)
            except (OSError, ValueError):
                return
            time.sleep(.2)
        raise RuntimeError('The server has not stopped yet. Check the logs.')

    def open_page(self, page='home', query=''):
        state = self.status()
        if not state.get('ready'):
            raise RuntimeError('Start the server first.')
        if page not in PAGES or query not in ('', '?tab=proxy', '?tab=storage'):
            raise ValueError('Unsupported application page')
        webbrowser.open(f"http://127.0.0.1:{state['port']}/spa/{PAGES[page]}{query}")

    def authentication_status(self):
        root = shared_directory(self.directory)
        path = root / 'accounts.sqlite3'
        configured = False
        if path.is_file():
            with closing(sqlite3.connect(path.as_uri() + '?mode=ro', uri=True, timeout=1)) as db:
                configured = db.execute('SELECT id FROM users WHERE admin=1 AND enabled=1 LIMIT 1').fetchone() is not None
        return {'configured': configured, 'root': str(root)}

    def create_administrator(self, username, password):
        from animelab.diagnostics import remember_secret
        remember_secret(password)
        from animelab.shared.accounts import Accounts
        store = Accounts(shared_directory(self.directory))
        store.bootstrap(username, password)
        return self.authentication_status()

    def open_accounts(self):
        state = self.status()
        if not state.get('ready') or state.get('authMode', 'none') != 'accounts':
            raise RuntimeError('Start AnimeLab with account authentication first')
        webbrowser.open(f"http://127.0.0.1:{state['port']}/auth/account")

    def engine_api(self, path, data=None):
        if path not in ('/api/proxy/settings', '/api/proxy/test'):
            raise ValueError('Unsupported engine operation')
        state = self.status()
        if state.get('authMode') == 'accounts' or preferences(self.config())['authMode'] == 'accounts':
            raise ValueError('Configure private source/proxy settings in the signed-in web account')
        if path == '/api/proxy/settings' and not state.get('ready'):
            if state.get('instanceId'):
                raise RuntimeError('Wait for the engine to finish starting or stopping.')
            from .launcher_proxy import load_proxy, save_proxy
            db_path = self.paths()['database']
            return load_proxy(db_path) if data is None else save_proxy(db_path, data)
        if not state.get('ready'):
            raise RuntimeError('Start the server first.')
        base = f"http://127.0.0.1:{state['port']}"
        req = Request(base + path, data=None if data is None else json.dumps(data).encode(),
                      headers={'Content-Type': 'application/json', 'Origin': base})
        with build_opener(ProxyHandler({})).open(req, timeout=20) as response:
            return json.load(response)

    def diagnose(self):
        if self.status().get('running'):
            return remote_call(running_record(self.directory), '/api/diagnostics')
        owner = Supervisor(self.directory, self.config(), headless=True)
        try:
            return owner.diagnose()
        finally:
            owner.control.close()

    def test_port(self, port):
        from .state import valid_port
        valid_port(port)
        state = self.status()
        if state.get('ready') and state.get('port') == port:
            return 'active'
        with socket.socket() as connection:
            connection.bind(('127.0.0.1', valid_port(port)))
        return 'free'

    def paths(self):
        config = self.config()
        # Paths match the engine's desktop defaults; no settings module is imported
        # here, so editing preferences cannot initialize the user's database.
        return {
            'data': self.directory.parent,
            'database': Path(getenv('ANIMAN_DB_PATH', str(self.directory.parent / 'db/animan.sqlite3'))),
            'cache': Path(getenv('ANIMAN_CACHE_DIR', str(self.directory.parent / 'cache'))),
            'downloads': Path(preferences(config)['downloadDir'] or getenv('ANIMAN_DOWNLOAD_DIR',
                str(Path.home() / 'Downloads/AnimeLab'))).expanduser(),
            'logs': self.directory,
        }

    def open_folder(self, kind):
        folder = self.paths()[kind]
        if kind == 'database':
            folder = folder.parent
        folder.mkdir(parents=True, exist_ok=True)
        if os.name == 'nt':
            os.startfile(str(folder))
        else:
            subprocess.Popen(['open' if __import__('sys').platform == 'darwin' else 'xdg-open', str(folder)],
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def backup(self, destination):
        source = self.paths()['database'].resolve()
        target = Path(destination).resolve()
        if not source.is_file():
            raise ValueError('No library database exists yet.')
        if target == source or target.exists():
            raise ValueError('Choose a new backup filename; existing files are not overwritten.')
        # SQLite's backup API includes committed WAL data while the server is active.
        # Copy to a sibling temporary file and publish only after quick_check passes.
        import tempfile
        fd, name = tempfile.mkstemp(dir=target.parent, prefix='.animelab-backup-')
        os.close(fd)
        temporary = Path(name)
        created = False
        try:
            # A Connection context manages transactions; it does not close the
            # file. Explicitly close both handles before publishing or unlinking
            # the snapshot, which Windows forbids while SQLite still owns it.
            with closing(sqlite3.connect(source.as_uri() + '?mode=ro', uri=True, timeout=5)) as original:
                with closing(sqlite3.connect(temporary)) as output:
                    deadline = time.monotonic() + 30
                    def progress(*_):
                        if time.monotonic() > deadline:
                            raise TimeoutError('The library is busy. Retry the backup later.')
                    original.backup(output, pages=128, sleep=.05, progress=progress)
                    if output.execute('PRAGMA quick_check').fetchone()[0] != 'ok':
                        raise RuntimeError('Backup verification failed')
            # Exclusive creation prevents races from replacing an existing destination.
            with target.open('xb') as handle, temporary.open('rb') as data:
                created = True
                if os.name != 'nt': os.fchmod(handle.fileno(), 0o600)
                shutil.copyfileobj(data, handle)
        except Exception:
            if created: target.unlink(missing_ok=True)
            raise
        finally:
            temporary.unlink(missing_ok=True)
        return str(target)
