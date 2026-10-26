"""The Python namespace moves; installed identities and user data stay compatible."""
import ast
import importlib.util
import json
import os
from pathlib import Path
import subprocess
import sys

from importlib.resources import files

ROOT = Path(__file__).resolve().parents[1]


def test_animelab_owns_the_runtime_resources():
    import animelab
    from animelab.config import settings

    assert Path(animelab.__file__).resolve().parent == ROOT / 'animelab'
    assert importlib.util.find_spec('animan') is None
    assert settings.BASE_DIR == ROOT / 'animelab'
    for resource in ('static/img/icon-192.png', 'static/manifest.json', 'desktop/panel.html'):
        assert files('animelab').joinpath(resource).is_file()


def test_engine_and_tools_have_no_absolute_imports_of_the_old_package():
    sources = [ROOT / name for name in ('run.py', 'desktop.py', 'android_runtime.py', 'animelab.spec')]
    for directory in ('animelab', 'scripts', 'tests'):
        sources.extend(path for path in (ROOT / directory).rglob('*.py')
                       if 'ressources' not in path.parts)
    for path in sources:
        for node in ast.walk(ast.parse(path.read_text(encoding='utf-8'))):
            if isinstance(node, ast.Import):
                names = [alias.name for alias in node.names]
            elif isinstance(node, ast.ImportFrom) and node.level == 0:
                names = [node.module or '']
            else:
                continue
            assert all(name.split('.')[0] != 'animan' for name in names), (path, node.lineno)


def test_frozen_runtime_resolves_assets_in_the_renamed_package(tmp_path):
    env = {**os.environ, 'HOME': str(tmp_path), 'USERPROFILE': str(tmp_path)}
    result = subprocess.run([sys.executable, '-c', '''
import json, sys
sys.frozen = True
sys._MEIPASS = sys.argv[1]
from animelab.config import settings
print(json.dumps(str(settings.BASE_DIR)))
''', str(tmp_path)], cwd=ROOT, env=env, text=True, capture_output=True, check=True, timeout=15)
    assert Path(json.loads(result.stdout)) == tmp_path / 'animelab'


def test_previous_data_directory_and_android_installation_identity_are_preserved(tmp_path):
    env = {key: value for key, value in os.environ.items() if not key.startswith('ANIMAN_')}
    env.update(HOME=str(tmp_path), USERPROFILE=str(tmp_path))
    result = subprocess.run([sys.executable, '-c', '''
import json
from animelab.config import settings
from animelab.desktop.state import state_directory
print(json.dumps({'database': str(settings.DATABASE_PATH), 'desktop': str(state_directory())}))
'''], cwd=ROOT, env=env, text=True, capture_output=True, check=True, timeout=15)
    paths = json.loads(result.stdout)
    assert Path(paths['database']) == tmp_path / '.animan/db/animan.sqlite3'
    assert Path(paths['desktop']) == tmp_path / '.animan/desktop'
    gradle = (ROOT / 'android/app/build.gradle.kts').read_text()
    assert 'applicationId = "com.animan.app"' in gradle
    assert 'extractPackages("animelab")' in gradle and 'include("animelab/**")' in gradle
