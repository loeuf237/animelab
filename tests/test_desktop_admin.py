"""Regression checks for native resources and the independent desktop control plane."""
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import threading
import time
from urllib.error import HTTPError
from urllib.request import ProxyHandler, Request, build_opener

import pytest

from animelab.desktop.control import remote_call
from animelab.desktop.state import InstanceLock, load_config, read_json, write_json
from animelab.desktop.supervisor import Supervisor, choose_port
from animelab.desktop import window

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture
def supervisor(tmp_path):
    owner = Supervisor(tmp_path, {'port': 8080, 'browser': False}, headless=True)
    owner.control.start()
    try:
        yield owner
    finally:
        owner.stop_engine()
        owner.control.close()


def record(owner):
    return {'port': owner.control.server.server_port, 'token': owner.control.token,
            'instanceId': owner.control.token[:16]}


def request(owner, path, *, token=None, host=None, origin=None, data=None):
    headers = {'Host': host or owner.control.authority, 'Content-Type': 'application/json'}
    if token is not None: headers['Authorization'] = 'Bearer ' + token
    if origin is not None: headers['Origin'] = origin
    req = Request(owner.control.origin + path, headers=headers,
                  data=json.dumps(data).encode() if data is not None else None)
    return build_opener(ProxyHandler({})).open(req, timeout=10)


def test_control_requires_capability_and_blocks_rebinding_and_csrf(supervisor):
    owner = supervisor
    for headers, status in [({}, 401), ({'token': 'wrong'}, 401),
                            ({'token': owner.control.token, 'host': 'attacker.example'}, 403),
                            ({'token': owner.control.token, 'origin': 'https://attacker.example'}, 403),
                            ({'token': owner.control.token, 'origin': 'null'}, 403)]:
        with pytest.raises(HTTPError) as error:
            request(owner, '/api/action', data={'action': 'stop'}, **headers)
        assert error.value.code == status
    assert owner.commands.empty()
    assert remote_call(record(owner))['application'] == 'AnimeLab'
    wrong = {**record(owner), 'instanceId': 'another-instance'}
    with pytest.raises(ValueError, match='identity'):
        remote_call(wrong)
    with request(owner, '/') as response:
        assert owner.control.token.encode() not in response.read()
        assert response.headers['X-Frame-Options'] == 'DENY'
        assert "frame-ancestors 'none'" in response.headers['Content-Security-Policy']


@pytest.mark.parametrize('port', [0, -1, 65536, '8080', True, 8080.5, None])
def test_invalid_ports_do_not_change_saved_config(supervisor, port):
    with pytest.raises(HTTPError) as error:
        request(supervisor, '/api/config', token=supervisor.control.token, data={'port': port, 'browser': False})
    assert error.value.code == 400
    assert not (supervisor.directory / 'config.json').exists()


def test_settings_are_persistent_private_and_actions_are_serialized(supervisor):
    remote_call(record(supervisor), '/api/config', {'port': 9010, 'browser': True})
    assert load_config(supervisor.directory) == {'port': 9010, 'browser': True}
    if os.name != 'nt':
        assert (supervisor.directory / 'config.json').stat().st_mode & 0o777 == 0o600
    remote_call(record(supervisor), '/api/action', {'action': 'restart'})
    remote_call(record(supervisor), '/api/action', {'action': 'restart'})
    assert supervisor.commands.qsize() == 1
    assert supervisor.commands.get_nowait() == 'restart'
    remote_call(record(supervisor), '/api/action', {'action': 'stop'})
    assert supervisor.commands.get_nowait() == 'stop'


def test_busy_port_is_not_reused_or_interfered_with():
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        occupied = listener.getsockname()[1]
        assert choose_port(occupied) != occupied
        assert listener.getsockname()[1] == occupied


def test_instance_lock_is_held_across_processes_and_released_on_crash(tmp_path):
    lock = InstanceLock(tmp_path)
    assert lock.acquire()
    script = '''
from pathlib import Path
from animelab.desktop.state import InstanceLock
import sys
lock = InstanceLock(Path(sys.argv[1]))
print(lock.acquire())
'''
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=10)
    assert result.stdout.strip() == 'False'
    lock.release()
    result = subprocess.run([sys.executable, '-c', script, str(tmp_path)], cwd=ROOT,
                            capture_output=True, text=True, check=True, timeout=10)
    assert result.stdout.strip() == 'True'
    assert lock.acquire()  # Child exited without release(), the OS released it.
    lock.release()


def test_windows_uses_real_ico_and_rejects_png_disguised_as_ico(monkeypatch, tmp_path):
    monkeypatch.setattr(sys, 'platform', 'win32')
    assert Path(window.window_icon()).suffix == '.ico'
    root = tmp_path / 'bundle'
    (root / 'desktop-assets').mkdir(parents=True)
    icon = root / 'desktop-assets/animelab.ico'
    icon.write_bytes((ROOT / 'docs/branding/animelab.ico').read_bytes())
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(root), raising=False)
    assert Path(window.window_icon()) == icon
    icon.write_bytes((ROOT / 'animelab/static/img/icon-512.png').read_bytes())
    with pytest.raises(ValueError, match='ICO'):
        window.window_icon()


def test_native_process_crash_keeps_administration_and_falls_back_to_browser(tmp_path, monkeypatch):
    # A real child exits abruptly, just like an uncaught .NET GUI-thread exception.
    worker = tmp_path / 'fake_engine.py'
    worker.write_text('''
import pathlib, sys, time, os
path = pathlib.Path(sys.argv[sys.argv.index('--worker') + 1])
if '--headless' not in sys.argv:
    os._exit(27)
(path / 'ready').touch()
while not (path / 'stop').exists(): time.sleep(.03)
''')
    from animelab.desktop import supervisor as module
    monkeypatch.setattr(module, 'launcher_command', lambda: [sys.executable, str(worker)])
    opened = []
    monkeypatch.setattr(module.webbrowser, 'open', opened.append)
    owner = Supervisor(tmp_path, {'port': 8080, 'browser': False})
    errors = []
    def run():
        try: owner.run()
        except Exception as error: errors.append(error)
    thread = threading.Thread(target=run)
    thread.start()
    try:
        deadline = time.monotonic() + 10
        while time.monotonic() < deadline:
            if owner.mode == 'browser' and owner.ready: break
            time.sleep(.05)
        result = remote_call(record(owner))
        assert result['ready'] and result['running'] and result['mode'] == 'browser'
        assert result['nativeError']
        assert thread.is_alive()
        remote_call(record(owner), '/api/action', {'action': 'stop'})
    finally:
        owner.command('stop')
        thread.join(timeout=10)
    assert not thread.is_alive() and not errors
    assert not (tmp_path / 'runtime.json').exists()


def test_diagnostic_report_is_allowlisted_and_does_not_contact_sources(supervisor, monkeypatch):
    monkeypatch.setenv('ANIMAN_PROXIES', 'http://user:very-private-password@example.test')
    report = remote_call(record(supervisor), '/api/diagnostics')
    text = json.dumps(report)
    assert 'very-private-password' not in text and supervisor.control.token not in text
    assert set(report) == {'schemaVersion', 'version', 'platform', 'port', 'configuredPort', 'mode', 'checks', 'ok'}
    assert {row['name'] for row in report['checks']} == {
        'frontend', 'desktop_storage', 'download_storage', 'database', 'ffmpeg', 'ffprobe', 'backend'}
    assert not report['ok']  # No engine is running in this fixture.


def test_running_record_cannot_redirect_commands_to_remote_host():
    with pytest.raises(ValueError):
        remote_call({'port': '8080@attacker.test', 'token': 'a' * 40})


def test_real_headless_launcher_reuses_instance_restarts_and_stops(tmp_path):
    # This is the real Python/FastAPI subprocess, with no access to the user's library.
    env = {key: value for key, value in os.environ.items() if not key.startswith('ANIMAN_')}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), ANIMAN_STARTUP_REFRESH='false',
               ANIMAN_DB_PATH=str(tmp_path / 'library.sqlite3'), ANIMAN_CACHE_DIR=str(tmp_path / 'cache'),
               ANIMAN_DOWNLOAD_DIR=str(tmp_path / 'downloads'), ANIMAN_ALLOWED_HOSTS='127.0.0.1,localhost')
    base = [sys.executable, str(ROOT / 'desktop.py')]
    runtime = tmp_path / '.animan/desktop/runtime.json'
    process = None
    def wait_status(predicate):
        deadline = time.monotonic() + 45
        while time.monotonic() < deadline:
            try:
                info = remote_call(read_json(runtime))
                if predicate(info): return info
            except (OSError, ValueError): pass
            if process.poll() is not None:
                pytest.fail('Launcher stopped before it was ready: ' + (tmp_path / 'launcher.log').read_text())
            time.sleep(.1)
        pytest.fail('Desktop status did not reach expected state')
    with socket.socket() as listener, (tmp_path / 'launcher.log').open('w') as logfile:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        occupied = listener.getsockname()[1]
        process = subprocess.Popen(base + ['--headless', '--port', str(occupied)],
                                   cwd=ROOT, env=env, stdout=logfile, stderr=logfile)
        try:
            first = wait_status(lambda info: info['ready'])
            assert first['portFallback'] and first['port'] != occupied
            subprocess.run(base + ['--headless'], cwd=ROOT, env=env, check=True, timeout=15,
                           stdout=logfile, stderr=logfile)
            assert remote_call(read_json(runtime))['instanceId'] == first['instanceId']
            new_port = choose_port(0)
            active = read_json(runtime)
            remote_call(active, '/api/config', {'port': new_port, 'browser': True})
            remote_call(active, '/api/action', {'action': 'restart'})
            updated = wait_status(lambda info: info['ready'] and info['port'] == new_port)
            assert updated['instanceId'] == first['instanceId'] and not updated['portFallback']
            report = remote_call(active, '/api/diagnostics')
            assert all(row['ok'] for row in report['checks'] if row['name'] in ('database', 'backend', 'download_storage'))
            subprocess.run(base + ['--stop'], cwd=ROOT, env=env, check=True, timeout=45,
                           stdout=logfile, stderr=logfile)
            assert process.wait(timeout=10) == 0
            assert not runtime.exists()
            assert load_config(runtime.parent) == {'port': new_port, 'browser': True}
            # The foreign listening socket is still untouched.
            assert listener.getsockname()[1] == occupied
        finally:
            if process.poll() is None:
                try: remote_call(read_json(runtime), '/api/action', {'action': 'stop'})
                except (OSError, ValueError): pass
                try: process.wait(timeout=40)
                except subprocess.TimeoutExpired:
                    process.kill()
                    process.wait(timeout=5)


def test_engine_does_not_survive_a_killed_supervisor(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith('ANIMAN_')}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path), ANIMAN_STARTUP_REFRESH='false',
               ANIMAN_DB_PATH=str(tmp_path / 'library.sqlite3'), ANIMAN_CACHE_DIR=str(tmp_path / 'cache'),
               ANIMAN_DOWNLOAD_DIR=str(tmp_path / 'downloads'))
    directory = tmp_path / '.animan/desktop'
    process = subprocess.Popen([sys.executable, str(ROOT / 'desktop.py'), '--headless', '--port', str(choose_port(0))],
                               cwd=ROOT, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    engine_lock = None
    try:
        deadline = time.monotonic() + 45
        status = None
        while time.monotonic() < deadline:
            try:
                status = remote_call(read_json(directory / 'runtime.json'))
                if status['ready']: break
            except (OSError, ValueError): pass
            time.sleep(.1)
        assert status and status['ready']
        engine_lock = InstanceLock(directory, 'engine.lock')
        assert not engine_lock.acquire()
        process.kill()  # The known Popen supervisor; bypass all of its finally blocks.
        process.wait(timeout=10)
        deadline = time.monotonic() + 45
        released = False
        while time.monotonic() < deadline:
            if engine_lock.acquire():
                released = True
                engine_lock.release()
                break
            time.sleep(.1)
        assert released, 'Orphaned engine still holds its library lock'
        with socket.socket() as client:
            client.settimeout(1)
            assert client.connect_ex(('127.0.0.1', status['port'])) != 0
    finally:
        if engine_lock:
            engine_lock.release()
        for workspace in directory.glob('engine-*'):
            if workspace.is_dir():
                (workspace / 'stop').touch()
        if process.poll() is None:
            process.kill()
            process.wait(timeout=5)
