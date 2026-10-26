"""Operator-controlled browser executable and optional headless verification."""
import json
import os
from pathlib import Path
import shutil
import tempfile

from animelab.config import settings


def executable(value):
    if not isinstance(value, str) or len(value) > 4096 or any(c in value for c in '\x00\r\n'):
        raise ValueError('Invalid Chromium executable path')
    value = value.strip()
    if not value:
        return ''
    path = Path(value).expanduser()
    if path.is_dir() and path.suffix == '.app':
        binaries = path / 'Contents' / 'MacOS'
        path = binaries / path.stem
    resolved = str(path.resolve()) if path.is_absolute() else shutil.which(value)
    if not resolved or not Path(resolved).is_file() or not os.access(resolved, os.X_OK):
        raise ValueError('Chromium executable not found or not executable')
    return resolved


class VerificationSettings:
    def __init__(self, path=None):
        self.path = path or settings.CACHE_DIR / 'verification-browser.json'

    def snapshot(self):
        try:
            data = json.loads(self.path.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        path = os.getenv('ANIMELAB_CHROMIUM_PATH', data.get('chromiumPath', ''))
        headless = (os.environ['ANIMELAB_CHROMIUM_HEADLESS'].lower() in ('1', 'true', 'yes')
                    if 'ANIMELAB_CHROMIUM_HEADLESS' in os.environ else data.get('headless', False))
        return {'chromiumPath': path, 'headless': bool(headless),
                'managed': any(key in os.environ for key in ('ANIMELAB_CHROMIUM_PATH', 'ANIMELAB_CHROMIUM_HEADLESS'))}

    def save(self, data):
        if not isinstance(data, dict) or set(data) != {'chromiumPath', 'headless'} or type(data['headless']) is not bool:
            raise ValueError('Expected chromiumPath and a boolean headless setting')
        if self.snapshot()['managed']:
            raise ValueError('Browser settings are controlled by launcher or startup environment; change them there and restart')
        values = {'chromiumPath': executable(data['chromiumPath']), 'headless': data['headless']}
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=self.path.parent, prefix='.browser-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(values, handle)
            os.replace(temporary, self.path)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self.snapshot()


verification_settings = VerificationSettings()


def add_browser_arguments(parser):
    import argparse
    parser.add_argument('--chromium-path', type=executable, default=None,
                        help='Path to an installed Chromium/Chrome/Edge/Brave executable for source verification')
    parser.add_argument('--chromium-headless', action=argparse.BooleanOptionalAction, default=None,
                        help='Run verification Chromium without a display; interactive CAPTCHAs still require a visible browser')


def apply_browser_arguments(args):
    if args.chromium_path is not None:
        os.environ['ANIMELAB_CHROMIUM_PATH'] = args.chromium_path
    if args.chromium_headless is not None:
        os.environ['ANIMELAB_CHROMIUM_HEADLESS'] = str(args.chromium_headless).lower()
