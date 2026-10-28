"""Reproduce study findings without opening the user's database or source sessions."""
import argparse
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT))
from scripts.check import test_environment

BASELINE = [
    'tests/test_aniyomi_container.py',
    'tests/test_recipe_runtime.py',
    'tests/test_imported_extensions_regression.py',
    'tests/test_extension_observability.py',
    'tests/test_extension_update_regressions.py',
    'tests/test_extension_search_integration.py',
    'tests/test_frenchanime_recipe.py',
    'tests/test_episode_versions_extensions.py',
]


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--baseline', action='store_true', help='Also run the existing extension tests')
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix='animelab-extension-study-') as temporary:
        env = test_environment(Path(temporary))
        env['PYTHONPATH'] = str(ROOT)
        commands = [[str(Path(__file__).with_name('audit_current_cases.py'))]]
        if args.baseline:
            commands.append(BASELINE)
        for files in commands:
            result = subprocess.run([sys.executable, '-m', 'pytest', *files, '-q'], cwd=ROOT, env=env)
            if result.returncode:
                return result.returncode
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
