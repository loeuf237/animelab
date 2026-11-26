"""Lightweight release version inspection without heavy HTTP/archive dependencies."""
import json
from pathlib import Path
import re
import sys

from animelab import __version__
from animelab.environment import getenv

VERSION = re.compile(r'^(?:android-)?v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)[.-]?(\d+))?(?:\+[\w.-]+)?$')


def version_key(value):
    match = VERSION.fullmatch(str(value))
    if not match:
        raise ValueError('Unsupported release version')
    major, minor, patch, phase, serial = match.groups()
    return (int(major), int(minor), int(patch), {'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[phase], int(serial or 0))


def current_version():
    explicit = getenv('ANIMELAB_RELEASE_VERSION')
    if explicit:
        return explicit
    if getattr(sys, 'frozen', False) and hasattr(sys, '_MEIPASS'):
        try:
            data = json.loads((Path(sys._MEIPASS) / 'release-metadata' / 'build-info.json').read_text())
            tag = data['release_tag']
            version_key(tag)
            return tag.removeprefix('v')
        except (OSError, ValueError, KeyError, TypeError):
            pass
    return __version__
