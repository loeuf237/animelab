"""Native launcher settings, engine integration, backup and real Qt controls."""
import json
from contextlib import closing
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time
from urllib.request import ProxyHandler, build_opener

import pytest

from animelab.desktop.launcher_model import LauncherModel
from animelab.desktop.options import DEFAULTS, engine_environment, normalize_config
from animelab.desktop.state import load_config
from animelab.desktop.supervisor import Supervisor, choose_port


@pytest.fixture
def model(tmp_path, monkeypatch):
    directory = tmp_path / 'desktop'
    directory.mkdir()
    monkeypatch.setenv('ANIMAN_DB_PATH', str(tmp_path / 'library.sqlite3'))
    return LauncherModel(directory)


@pytest.mark.parametrize('values', [
    {'connectTimeout': 0}, {'readTimeout': float('nan')}, {'mediaWorkers': True},
    {'maxConcurrentDownloads': 0}, {'globalSpeedLimit': -1}, {'downloadDir': 'relative'},
    {'language': 'es'}, {'startPage': 'http://remote.test'}, {'openUi': 'true'},
    {'ANIMAN_ALLOWED_HOSTS': '*'},
])
def test_native_preferences_reject_unsupported_or_invalid_values(values):
    with pytest.raises(ValueError):
        normalize_config({'port': 8080, 'browser': True, 'launcher': values})


def test_viewing_preferences_does_not_create_config_or_database(model):
    assert model.config()['launcher'] == DEFAULTS
    assert not (model.directory / 'config.json').exists()
    assert not (model.directory.parent / 'db/animan.sqlite3').exists()


def test_legacy_web_settings_keep_native_preferences_on_disk(model):
    config = normalize_config({'port': 8080, 'browser': True,
                               'launcher': {'openUi': False, 'readTimeout': 77}})
    supervisor = Supervisor(model.directory, config, headless=True)
    try:
        supervisor.save_launcher_config(config)
        supervisor.save_config({'port': 9091, 'browser': False})
        result = load_config(model.directory)
        assert result['port'] == 9091 and result['launcher']['readTimeout'] == 77
        assert not result['launcher']['openUi']
    finally:
        supervisor.control.close()


def test_native_environment_contains_only_supported_overrides():
    values = normalize_config({'port': 8080, 'browser': True,
                               'launcher': {'connectTimeout': 23, 'mediaWorkers': 2}})
    env = engine_environment(values)
    assert env['ANIMAN_CONNECT_TIMEOUT'] == '23'
    assert env['ANIMAN_MEDIA_WORKERS'] == '2'
    assert 'ANIMAN_ALLOWED_HOSTS' not in env and 'ANIMAN_HOST' not in env
    assert 'ANIMAN_LANGUAGE' not in env  # Automatic detection stays automatic.


def test_first_native_launch_keeps_existing_download_preferences(model):
    database = model.paths()['database']
    with closing(sqlite3.connect(database)) as db, db:
        db.execute('CREATE TABLE download_preferences (id INTEGER, max_concurrent INTEGER, global_limit INTEGER, plex_org INTEGER)')
        db.execute('INSERT INTO download_preferences VALUES (1, 7, 4096, 1)')
    values = model.config()['launcher']
    assert values['maxConcurrentDownloads'] == 7
    assert values['globalSpeedLimit'] == 4096 and values['plexOrganization']


def test_offline_proxy_edits_preserve_masked_credentials_and_stay_out_of_exports(model):
    original = model.engine_api('/api/proxy/settings')
    assert not original['enabled']
    assert not model.paths()['database'].exists()  # Reading the form is side-effect free.
    result = model.engine_api('/api/proxy/settings', {
        'enabled': False, 'host': 'proxy.example', 'port': '1080', 'proxy_type': 'socks5',
        'password': 'private-proxy-password', 'custom_url': 'http://user:another-private-secret@proxy.example:1080',
    })
    assert result['password'] == '******' and 'another-private-secret' not in result['custom_url']
    model.engine_api('/api/proxy/settings', result)
    with closing(sqlite3.connect(model.paths()['database'])) as db:
        assert db.execute('SELECT password FROM network_proxy_settings').fetchone()[0] == 'private-proxy-password'
    assert 'private-proxy-password' not in json.dumps(model.config())


def test_native_connect_timeout_reaches_shared_transport(monkeypatch):
    from animelab.config import settings
    from animelab.services.source_http import source_http
    monkeypatch.setenv('ANIMAN_DESKTOP_PREFERENCES', '{}')
    monkeypatch.setattr(settings, 'CONNECTION_TIMEOUT', 23)
    assert source_http.timeout(45) == (23, 45)


def test_sqlite_backup_includes_wal_data_and_does_not_overwrite(model, tmp_path, monkeypatch):
    source = tmp_path / 'library.sqlite3'
    monkeypatch.setenv('ANIMAN_DB_PATH', str(source))
    destination = tmp_path / 'backup.sqlite3'
    with closing(sqlite3.connect(source)) as db, db:
        db.execute('PRAGMA journal_mode=WAL')
        db.execute('CREATE TABLE watched (episode INTEGER)')
        db.execute('INSERT INTO watched VALUES (42)')
        db.commit()
        model.backup(destination)
        with closing(sqlite3.connect(destination)) as backup:
            assert backup.execute('SELECT episode FROM watched').fetchone() == (42,)
        with pytest.raises(ValueError, match='existing files'):
            model.backup(destination)
        with pytest.raises(ValueError):
            model.backup(source)


def test_failed_backup_removes_incomplete_output_after_closing_it(model, tmp_path, monkeypatch):
    source = model.paths()['database']
    with closing(sqlite3.connect(source)) as db, db:
        db.execute('CREATE TABLE library (id INTEGER)')
    import shutil
    def fail(*_): raise OSError('Simulated write failure')
    monkeypatch.setattr(shutil, 'copyfileobj', fail)
    target = tmp_path / 'backup.sqlite3'
    with pytest.raises(OSError, match='Simulated'):
        model.backup(target)
    assert not target.exists()
    assert not list(tmp_path.glob('.animelab-backup-*'))


@pytest.mark.parametrize('failure_phase', [None, 'backup', 'verification', 'copy'])
def test_backup_releases_windows_file_locks_on_success_and_failure(model, tmp_path, monkeypatch, failure_phase):
    """Keep connections alive and enforce Windows' refusal to unlink open files."""
    source = model.paths()['database']
    with closing(sqlite3.connect(source)) as db, db:
        db.execute('CREATE TABLE watched (episode INTEGER)')
        db.execute('INSERT INTO watched VALUES (42)')
    connections = []
    connect = sqlite3.connect
    unlink = Path.unlink
    copy = __import__('shutil').copyfileobj

    class TrackedConnection(sqlite3.Connection):
        closed = False

        def close(self):
            super().close()
            self.closed = True

        def backup(self, *args, **kwargs):
            if failure_phase == 'backup':
                raise OSError('Simulated backup failure')
            return super().backup(*args, **kwargs)

        def execute(self, statement, *args):
            if statement == 'PRAGMA quick_check' and failure_phase == 'verification':
                raise OSError('Simulated verification failure')
            return super().execute(statement, *args)

    def tracked_connect(filename, *args, **kwargs):
        connection = connect(filename, *args, factory=TrackedConnection, **kwargs)
        # Retaining the objects prevents GC from accidentally hiding leaked locks.
        connections.append((str(filename), connection))
        return connection

    def windows_unlink(path, *args, **kwargs):
        if any(filename == str(path) and not db.closed for filename, db in connections):
            raise PermissionError('Windows refuses to delete an open SQLite file')
        return unlink(path, *args, **kwargs)

    def publish(*args):
        assert connections and all(db.closed for _, db in connections)
        if failure_phase == 'copy':
            raise OSError('Simulated copy failure')
        return copy(*args)

    monkeypatch.setattr(sqlite3, 'connect', tracked_connect)
    monkeypatch.setattr(Path, 'unlink', windows_unlink)
    monkeypatch.setattr('shutil.copyfileobj', publish)
    target = tmp_path / 'backup.sqlite3'
    try:
        if failure_phase:
            with pytest.raises(OSError, match='Simulated ' + failure_phase):
                model.backup(target)
            assert not target.exists()
        else:
            model.backup(target)
            with closing(connect(target)) as snapshot:
                assert snapshot.execute('SELECT episode FROM watched').fetchone() == (42,)
        assert connections and all(db.closed for _, db in connections)
        assert not list(tmp_path.glob('.animelab-backup-*'))
    finally:
        for _, db in connections:
            db.close()


def test_launcher_starts_applies_profile_and_stops_real_engine(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('ANIMAN_DB_PATH', str(tmp_path / 'library.sqlite3'))
    monkeypatch.setenv('ANIMAN_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('ANIMAN_STARTUP_REFRESH', 'false')
    directory = tmp_path / '.animan/desktop'
    directory.mkdir(parents=True)
    model = LauncherModel(directory)
    config = normalize_config({'port': choose_port(0), 'browser': True, 'launcher': {
        'openUi': False, 'downloadDir': str(tmp_path / 'selected-downloads'),
        'maxConcurrentDownloads': 4, 'mediaWorkers': 2, 'globalSpeedLimit': 2048,
        'plexOrganization': True, 'startPage': 'downloads',
    }})
    try:
        state = model.launch(config)
        assert state['ready'] and state['url'].endswith('/spa/downloads')
        assert model.test_port(state['port']) == 'active'
        base = f"http://127.0.0.1:{state['port']}"
        with build_opener(ProxyHandler({})).open(base + '/api/download/settings', timeout=5) as response:
            applied = json.load(response)
        assert applied['maxConcurrentDownloads'] == 4 and applied['mediaWorkers'] == 2
        assert applied['globalSpeedLimit'] == 2048 and applied['plexOrganization']
        assert (tmp_path / 'selected-downloads').is_dir()
        model.restart({**config, 'port': choose_port(0)})
        assert model.status()['ready']
        # Proxy controls use the real engine and keep credentials out of launcher JSON.
        proxy = model.engine_api('/api/proxy/settings')
        assert 'enabled' in proxy
        model.engine_api('/api/proxy/settings', {'enabled': False})
    finally:
        model.stop()
        if model.child is not None:
            model.child.wait(timeout=15)
    assert not model.status()['running']


@pytest.fixture
def qt_app():
    pytest.importorskip('PySide6.QtWidgets')
    from animelab.desktop.launcher_widgets import application
    return application()


def test_closing_configuration_process_keeps_real_server_available(tmp_path, monkeypatch):
    pytest.importorskip('PySide6.QtWidgets')
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('ANIMAN_DB_PATH', str(tmp_path / 'library.sqlite3'))
    monkeypatch.setenv('ANIMAN_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('ANIMAN_STARTUP_REFRESH', 'false')
    monkeypatch.setenv('QT_QPA_PLATFORM', 'offscreen')
    directory = tmp_path / '.animan/desktop'
    directory.mkdir(parents=True)
    model = LauncherModel(directory)
    model.save(normalize_config({'port': choose_port(0), 'browser': True,
        'launcher': {'openUi': False, 'downloadDir': str(tmp_path / 'downloads')}}))
    script = '''
from pathlib import Path
from PySide6.QtCore import QTimer
from animelab.desktop.launcher import NativeLauncher
from animelab.desktop.launcher_widgets import application
app = application()
ui = NativeLauncher(Path.home() / '.animan/desktop')
ui.show()
ui.launch()
def close_when_ready():
    if not ui.busy and ui.model.status().get('ready'):
        ui.close()
    else:
        QTimer.singleShot(100, close_when_ready)
QTimer.singleShot(100, close_when_ready)
app.exec()
'''
    try:
        subprocess.run([sys.executable, '-c', script], cwd=Path(__file__).resolve().parents[1],
                       capture_output=True, text=True, check=True, timeout=75)
        # Probe beyond the worker's parent-watch failure threshold, after the
        # configuration process (and its QApplication) has fully exited.
        deadline = time.monotonic() + 4
        while True:
            state = model.status()
            assert state['running'] and state['ready']
            with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{state['port']}/openapi.json", timeout=5) as response:
                assert response.status == 200
            if time.monotonic() >= deadline:
                break
            time.sleep(.2)
    finally:
        model.stop()
    assert not model.status()['running']


@pytest.mark.parametrize('language', ['fr', 'en'])
def test_native_tabs_fields_and_save_without_starting_engine(model, monkeypatch, language, qt_app):
    from animelab.desktop.launcher import NativeLauncher
    from animelab.desktop.launcher_panels import TABS
    from PySide6.QtWidgets import QMessageBox
    from PySide6.QtGui import QRawFont
    from PySide6.QtTest import QTest
    monkeypatch.setattr(QMessageBox, 'critical', lambda *args, **kwargs: pytest.fail(str(args)))
    ui = NativeLauncher(model.directory)
    ui.variables['language'].set(language)
    qt_app.processEvents()
    ui.show()
    try:
        QTest.qWait(50)
        assert ui.fields[('server', 'host')].text() == '127.0.0.1'
        assert ui.fields[('backups', 'db_path')].text() == str(ui.model.paths()['database'])
        # Real outline fonts must cover the glyphs which Tk previously rendered as garbage.
        font = QRawFont.fromFont(ui.font())
        assert font.isValid() and font.fontTable('head')
        assert all(font.supportsCharacter(ord(char)) for char in 'éèÀœ’…')
        for width, height in ((590, 700), (800, 850)):
            ui.resize(width, height)
            QTest.qWait(30)
            rows = {}
            for tab in ui.tabs:
                rows.setdefault(tab.geometry().top(), []).append(tab)
                assert tab.fontMetrics().horizontalAdvance(tab.text()) <= tab.width() - 4
            assert [len(row) for row in rows.values()] == [4, 4, 3]
        for tab in TABS:
            ui.select_tab(tab)
            qt_app.processEvents()
            assert ui.pages[tab].isVisible()
            for (page, _), item in ui.fields.items():
                if page == tab:
                    assert item.isVisible()
                    from PySide6.QtCore import QPoint
                    top = item.mapTo(ui.pages[tab], QPoint(0, 0))
                    assert top.x() >= 0 and top.y() >= 0
                    assert top.y() + item.height() <= ui.pages[tab].height()
        ui.select_tab('webui')
        checkbox = ui.fields[('webui', 'open_ui')]
        previous = checkbox.isChecked()
        checkbox.click()
        assert ui.variables['openUi'].get() is not previous
        checkbox.click()
        # Cancelled folder selection must keep the user's current value.
        monkeypatch.setattr('animelab.desktop.launcher.choose_directory', lambda *args: '')
        before = ui.variables['downloadDir'].get()
        ui.choose_download_directory()
        assert ui.variables['downloadDir'].get() == before
        chosen = str(model.directory / 'Séries téléchargées')
        monkeypatch.setattr('animelab.desktop.launcher.choose_directory', lambda *args: chosen)
        ui.choose_download_directory()
        assert ui.variables['downloadDir'].get() == chosen
        ui.select_tab('server')
        ui.fields[('server', 'port')].setValue(9092)
        ui.save()
        deadline = time.monotonic() + 5
        while ui.busy and time.monotonic() < deadline:
            qt_app.processEvents()
            time.sleep(.02)
        result = load_config(model.directory)
        assert result['port'] == 9092
        assert result['launcher']['downloadDir'] == chosen
        assert ui.model.child is None
    finally:
        ui.closed = True
        ui.hide()
        ui.deleteLater()
        qt_app.processEvents()


def test_native_dialog_routing_and_unicode_paths(monkeypatch, qt_app, tmp_path):
    from PySide6.QtWidgets import QFileDialog
    from animelab.desktop import launcher_dialogs as dialogs
    selected = str(tmp_path / 'Séries étiquetées')
    def native_directory(parent, title, initial, options):
        assert options & QFileDialog.Option.ShowDirsOnly
        assert not options & QFileDialog.Option.DontUseNativeDialog
        return selected
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', native_directory)
    assert dialogs.choose_directory(None, 'Dossier', tmp_path) == selected
    monkeypatch.setattr(QFileDialog, 'getExistingDirectory', lambda *args: '')
    assert dialogs.choose_directory(None, 'Dossier', tmp_path) == ''
    monkeypatch.setattr(QFileDialog, 'getSaveFileName', lambda *args: (str(tmp_path / 'réglages'), ''))
    assert dialogs.save_file(None, 'Exporter…', 'réglages.json', 'JSON (*.json)').endswith('réglages.json')
