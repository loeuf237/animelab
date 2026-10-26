"""Default branding changes must not replace explicit destinations or legacy data."""
import runpy
import sys
from pathlib import Path

import pytest

from animelab.desktop.launcher_model import LauncherModel

CONFIG = Path(__file__).resolve().parents[1] / 'animelab/config.py'


@pytest.mark.parametrize('android', [False, True])
@pytest.mark.parametrize('custom', [False, True])
def test_defaults_keep_private_android_work_and_explicit_paths(tmp_path, monkeypatch, android, custom):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delitem(sys.modules, 'chaquopy', raising=False)
    monkeypatch.delattr(sys, 'getandroidapilevel', raising=False)
    monkeypatch.delenv('ANDROID_ROOT', raising=False)
    monkeypatch.delenv('ANIMAN_DOWNLOAD_DIR', raising=False)
    monkeypatch.setenv('ANIMAN_DATA_DIR', str(tmp_path / 'private'))
    monkeypatch.setenv('ANIMAN_CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('ANIMAN_DB_PATH', str(tmp_path / 'db/animan.sqlite3'))
    if android:
        monkeypatch.setenv('ANDROID_ROOT', '/system')
    selected = tmp_path / 'my chosen folder'
    if custom:
        monkeypatch.setenv('ANIMAN_DOWNLOAD_DIR', str(selected))
    legacy = tmp_path / 'Downloads/Animan/episode.mp4'
    legacy.parent.mkdir(parents=True)
    legacy.write_bytes(b'existing video')
    namespace = runpy.run_path(str(CONFIG))
    expected = selected if custom else tmp_path / ('private/downloads' if android else 'Downloads/AnimeLab')
    assert namespace['settings'].DOWNLOAD_DIR == str(expected)
    assert expected.is_dir()
    assert legacy.read_bytes() == b'existing video'
    assert not (expected / 'episode.mp4').exists()
    assert Path(namespace['settings'].DATABASE_PATH).name == 'animan.sqlite3'


def test_launcher_matches_engine_default_and_preserves_user_choices(tmp_path, monkeypatch):
    monkeypatch.setattr(Path, 'home', lambda: tmp_path)
    monkeypatch.delenv('ANIMAN_DOWNLOAD_DIR', raising=False)
    model = LauncherModel(tmp_path / 'desktop')
    monkeypatch.setattr(model, 'config', lambda: {'launcher': {}})
    assert model.paths()['downloads'] == tmp_path / 'Downloads/AnimeLab'
    selected = tmp_path / 'Downloads/Animan'
    monkeypatch.setenv('ANIMAN_DOWNLOAD_DIR', str(selected))
    assert model.paths()['downloads'] == selected
    monkeypatch.setattr(model, 'config', lambda: {'launcher': {'downloadDir': str(tmp_path / 'my media')}})
    assert model.paths()['downloads'] == tmp_path / 'my media'
