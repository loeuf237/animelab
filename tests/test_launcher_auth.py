"""Authentication is an operational desktop setting, never a cosmetic panel."""
from contextlib import closing
import json
from pathlib import Path
import sqlite3
import time

import httpx
import pytest

from animelab.desktop.launcher_model import LauncherModel
from animelab.desktop.options import normalize_config, engine_environment
from animelab.desktop.state import load_config
from animelab.desktop.supervisor import choose_port
from animelab.shared.accounts import Accounts

PASSWORD = 'Desktop integration password 42!'


@pytest.fixture
def model(tmp_path, monkeypatch):
    monkeypatch.setenv('HOME', str(tmp_path))
    monkeypatch.setenv('USERPROFILE', str(tmp_path))
    monkeypatch.setenv('ANIMAN_DB_PATH', str(tmp_path / 'personal.sqlite3'))
    monkeypatch.setenv('ANIMAN_CACHE_DIR', str(tmp_path / 'personal-cache'))
    monkeypatch.setenv('ANIMAN_STARTUP_REFRESH', 'false')
    monkeypatch.delenv('ANIMELAB_SHARED_DIR', raising=False)
    directory = tmp_path / '.animan' / 'desktop'
    directory.mkdir(parents=True)
    return LauncherModel(directory)


@pytest.mark.parametrize('values', [
    {'authMode': 'jwt'}, {'authSessionHours': 0}, {'authSessionHours': True},
    {'authIdleMinutes': 0}, {'authSessionHours': 1, 'authIdleMinutes': 61},
    {'authMaxEngines': 0}, {'authPassword': PASSWORD},
])
def test_auth_preferences_validate_ranges_and_never_accept_passwords(values):
    with pytest.raises(ValueError):
        normalize_config({'port': 8080, 'browser': True, 'launcher': values})


def test_viewing_authentication_does_not_create_an_account_database(model):
    state = model.authentication_status()
    assert not state['configured']
    assert not Path(state['root']).exists()
    assert not model.paths()['database'].exists()


def test_bootstrap_is_one_time_and_credentials_stay_out_of_launcher_config(model):
    assert model.create_administrator('operator', PASSWORD)['configured']
    config = normalize_config({'port': 8080, 'browser': True, 'launcher': {'authMode': 'accounts'}})
    model.save(config)
    data = (model.directory / 'config.json').read_text()
    assert PASSWORD not in data and 'operator' not in data
    with closing(sqlite3.connect(Path(model.authentication_status()['root']) / 'accounts.sqlite3')) as db:
        encoded = db.execute('SELECT password FROM users').fetchone()[0]
    assert PASSWORD not in encoded
    with pytest.raises(ValueError, match='already configured'):
        model.create_administrator('replacement', 'A different password 42!')
    assert Accounts(model.authentication_status()['root']).authenticate('operator', PASSWORD)
    assert not model.paths()['database'].exists()


def test_launcher_requires_bootstrap_before_starting_account_mode(model):
    config = normalize_config({'port': 8080, 'browser': True, 'launcher': {'authMode': 'accounts'}})
    with pytest.raises(ValueError, match='first administrator'):
        model.launch(config)
    assert model.child is None


def test_real_desktop_gateway_starts_authenticates_and_stops_account_engines(model):
    model.create_administrator('operator', PASSWORD)
    config = normalize_config({'port': choose_port(0), 'browser': True, 'launcher': {
        'openUi': False, 'authMode': 'accounts', 'authSessionHours': 2, 'authIdleMinutes': 10,
        'authMaxEngines': 2,
    }})
    try:
        state = model.launch(config)
        assert state['ready'] and state['authMode'] == 'accounts'
        base = f"http://127.0.0.1:{state['port']}"
        # The first authenticated request starts a fresh engine; Windows imports
        # can take longer than HTTPX's default five-second read deadline.
        with httpx.Client(base_url=base, trust_env=False, timeout=60) as client:
            assert client.get('/api/favorites').status_code == 401
            assert client.get('/healthz').json()['mode'] == 'shared'
            login = client.post('/api/auth/login', json={'username': 'operator', 'password': PASSWORD},
                                headers={'Origin': base})
            assert login.status_code == 200
            assert client.get('/api/auth/me').json()['user']['admin'] is True
            assert client.get('/api/favorites').json() == []
            if (Path(__file__).resolve().parents[1] / 'frontend/dist/index.html').is_file():
                assert client.get('/app/').status_code == 200
        path = Path(model.authentication_status()['root']) / 'accounts.sqlite3'
        with closing(sqlite3.connect(path)) as db:
            created, expires = db.execute('SELECT created, expires FROM sessions LIMIT 1').fetchone()
        assert expires - created == 7200
        report = model.diagnose()
        assert next(check for check in report['checks'] if check['name'] == 'backend')['ok']
        with pytest.raises(ValueError, match='signed-in web account'):
            model.engine_api('/api/proxy/settings')
        assert not model.paths()['database'].exists()
    finally:
        model.stop()
        if model.child is not None:
            model.child.wait(timeout=20)
    assert not model.status()['running']
    assert not list((Path(model.authentication_status()['root']) / 'users').glob('*/ready.json'))


def test_old_account_schema_keeps_sessions_and_never_resurrects_expired_tokens(tmp_path):
    store = Accounts(tmp_path)
    identity = store.bootstrap('operator', PASSWORD)
    token = store.new_session(identity)
    with store.connect() as db:
        db.execute('ALTER TABLE sessions DROP COLUMN expires')
    reopened = Accounts(tmp_path)
    assert reopened.session(token)
    with reopened.connect() as db:
        db.execute('UPDATE sessions SET expires=?', (time.time() - 1,))
    reopened.lifetime = 7 * 86400
    assert reopened.session(token) is None


def test_real_auth_controls_are_masked_and_nonpersisted(model, monkeypatch):
    pytest.importorskip('PySide6.QtWidgets')
    from PySide6.QtGui import QPalette, QFont
    from PySide6.QtWidgets import QLineEdit
    from PySide6.QtTest import QTest
    from animelab.desktop.launcher_widgets import application
    from animelab.desktop.launcher import NativeLauncher
    app = application()
    ui = NativeLauncher(model.directory)
    ui.show()
    try:
        ui.select_tab('authentication')
        ui.fields[('authentication', 'auth_mode')].setCurrentIndex(1)
        app.processEvents()
        field = ui.fields[('authentication', 'password')]
        assert field.echoMode() == QLineEdit.EchoMode.Password and field.isEnabled()
        ui.auth_username.set('operator')
        ui.auth_password.set(PASSWORD)
        ui.create_administrator()
        deadline = time.monotonic() + 10
        while ui.busy and time.monotonic() < deadline:
            app.processEvents()
            QTest.qWait(20)
        assert ui.auth_configured and not field.isEnabled() and field.text() == ''
        assert ui.collect_config()['launcher']['authMode'] == 'accounts'
        assert PASSWORD not in json.dumps(ui.collect_config())
        assert ui.palette().color(QPalette.ColorRole.WindowText).name() == '#000000'
        assert ui.font().hintingPreference() == QFont.HintingPreference.PreferFullHinting
    finally:
        ui.closed = True
        ui.hide()
        ui.deleteLater()
        app.processEvents()
