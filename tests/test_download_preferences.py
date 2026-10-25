"""Preferences must survive process/container replacement without losing data."""
import sqlite3

import pytest

from animelab.config import settings
from animelab.database import init_db, create_database_engine
from animelab.migrations import migrate, MIGRATIONS
from animelab.services import download_preferences
from animelab.services.download_manager import DownloadManagerService
from animelab.services.proxy_service import proxy_service
from animelab.services.voiranime_service import voiranime_service


@pytest.fixture
def database(tmp_path, monkeypatch):
    path = tmp_path / 'preferences.sqlite3'
    init_db(path)
    monkeypatch.setattr(settings, 'DATABASE_PATH', str(path))
    monkeypatch.setattr(proxy_service, 'selected_user_agent', 'Random (Rotator)')
    monkeypatch.setattr(voiranime_service, 'default_server', 'auto')
    monkeypatch.setattr(DownloadManagerService, '_trigger_process_queue', lambda self: None)
    return path


def test_download_options_survive_a_new_manager(database):
    manager = DownloadManagerService()
    manager.update_settings(2, 4096, True, 'Chrome', 'sibnet')
    proxy_service.set_selected_user_agent('Random (Rotator)')
    restored = DownloadManagerService()
    restored._load_preferences()
    assert restored.max_concurrent_downloads == 2
    assert restored.global_speed_limit == 4096
    assert restored.plex_organization is True
    assert restored.voiranime_default_server == voiranime_service.default_server == 'sibnet'
    assert proxy_service.get_selected_user_agent() == 'Chrome'


def test_separate_speed_control_retains_other_options_and_persists_unlimited(database):
    manager = DownloadManagerService()
    manager.update_settings(2, 4096, True, 'Chrome', 'sibnet')
    manager.set_global_speed_limit(0)
    restored = DownloadManagerService()
    restored._load_preferences()
    assert restored.global_speed_limit == 0
    assert restored.max_concurrent_downloads == 2
    assert restored.plex_organization is True
    assert restored.voiranime_default_server == 'sibnet'


@pytest.mark.parametrize('change', ['all', 'speed'])
def test_failed_write_does_not_change_live_settings(database, monkeypatch, change):
    manager = DownloadManagerService()
    before = manager._preferences()
    def fail(values):
        raise OSError('storage unavailable')
    monkeypatch.setattr(download_preferences, 'save', fail)
    with pytest.raises(OSError, match='storage unavailable'):
        if change == 'all':
            manager.update_settings(2, 4096, True, 'Chrome', 'sibnet')
        else:
            manager.set_global_speed_limit(4096)
    assert manager._preferences() == before


def test_no_saved_preferences_retains_environment_defaults(database, monkeypatch):
    monkeypatch.setattr(settings, 'MAX_CONCURRENT_DOWNLOADS', 7)
    manager = DownloadManagerService()
    manager._load_preferences()
    assert manager.max_concurrent_downloads == 7


def test_upgrade_adds_preferences_without_changing_existing_library(tmp_path):
    path = tmp_path / 'version6.sqlite3'
    engine = create_database_engine('sqlite:///' + str(path))
    try:
        migrate(engine, MIGRATIONS[:-1])
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO favorites(url,title) VALUES ('https://example.invalid/kept','Keep me')")
        migrate(engine)
        migrate(engine)
        with sqlite3.connect(path) as conn:
            assert conn.execute('SELECT title FROM favorites').fetchone()[0] == 'Keep me'
            assert conn.execute('SELECT count(*) FROM download_preferences').fetchone()[0] == 0
    finally:
        engine.dispose()
