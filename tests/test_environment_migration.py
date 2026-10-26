"""New names take precedence; legacy integrations and child isolation survive."""
from pathlib import Path
import runpy

import pytest

from animelab.environment import getenv, update_environment, with_aliases
from animelab.desktop.launcher_model import LauncherModel
from animelab.desktop.options import engine_environment
from animelab.shared.workers import Workers


@pytest.mark.parametrize('name', ['PORT', 'RELOAD', 'DOWNLOAD_DIR', 'DB_PATH', 'CACHE_DIR', 'LANGUAGE'])
def test_environment_aliases_prefer_modern_names_including_empty_values(name):
    old, new = 'ANIMAN_' + name, 'ANIMELAB_' + name
    assert getenv(old, 'default', environ={}) == 'default'
    assert getenv(new, environ={old: 'old'}) == 'old'
    assert getenv(old, environ={old: 'old', new: 'new'}) == 'new'
    assert getenv(old, environ={old: 'old', new: ''}) == ''
    assert with_aliases({old: 'old', new: 'new'}) == {old: 'new', new: 'new'}


def test_child_override_replaces_both_inherited_aliases(monkeypatch):
    monkeypatch.setenv('ANIMELAB_PORT', '9999')
    monkeypatch.setenv('ANIMAN_PORT', '9998')
    update_environment(ANIMAN_PORT='8081')
    assert getenv('ANIMELAB_PORT') == '8081'
    import os
    assert os.environ['ANIMAN_PORT'] == '8081'


def test_launcher_destination_beats_both_environment_aliases(tmp_path, monkeypatch):
    monkeypatch.setenv('ANIMELAB_DOWNLOAD_DIR', str(tmp_path / 'new'))
    monkeypatch.setenv('ANIMAN_DOWNLOAD_DIR', str(tmp_path / 'old'))
    model = LauncherModel(tmp_path / 'desktop')
    monkeypatch.setattr(model, 'config', lambda: {})
    assert model.paths()['downloads'] == tmp_path / 'new'
    config = {'port': 8080, 'browser': True, 'launcher': {'downloadDir': str(tmp_path / 'selected')}}
    env = engine_environment(config)
    assert env['ANIMELAB_DOWNLOAD_DIR'] == env['ANIMAN_DOWNLOAD_DIR'] == str(tmp_path / 'selected')


def test_shared_workers_cannot_inherit_operator_paths_or_source_cookies(tmp_path, monkeypatch):
    monkeypatch.setenv('ANIMELAB_DB_PATH', str(tmp_path / 'operator.sqlite'))
    monkeypatch.setenv('ANIMELAB_ANIMEPAHE_COOKIE', 'operator-secret-not-to-be-forwarded')
    home = tmp_path / 'account'
    env = Workers(tmp_path).environment(home, 'worker-test-token')
    assert env['ANIMELAB_DB_PATH'] == env['ANIMAN_DB_PATH'] == str(home / '.animan/db/animan.sqlite3')
    assert 'ANIMELAB_ANIMEPAHE_COOKIE' not in env and 'ANIMAN_ANIMEPAHE_COOKIE' not in env
    assert env['ANIMELAB_RELOAD'] == env['ANIMAN_RELOAD'] == 'false'


def test_default_reload_behavior_is_unchanged():
    assert getenv('ANIMAN_RELOAD', 'true', environ={}) == 'true'
