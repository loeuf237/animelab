"""Bounded, cached update metadata. Never download or execute a release binary."""
import asyncio
import json
import ipaddress
import re
import time
import sys
from pathlib import Path
from urllib.parse import urlsplit
import httpx
from animelab import __version__
from animelab.diagnostics import telemetry
from animelab.environment import getenv
from animelab.security import is_safe_url_async

GITHUB_FEED = 'https://api.github.com/repos/loeuf237/animelab/releases?per_page=10'
MAX_FEED_BYTES = 512 * 1024
VERSION = re.compile(r'^(?:android-)?v?(\d+)\.(\d+)\.(\d+)(?:-(alpha|beta|rc)[.-]?(\d+))?(?:\+[\w.-]+)?$')


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


def version_key(value):
    match = VERSION.fullmatch(str(value))
    if not match:
        raise ValueError('Unsupported release version')
    major, minor, patch, phase, serial = match.groups()
    return (int(major), int(minor), int(patch), {'alpha': 0, 'beta': 1, 'rc': 2, None: 3}[phase], int(serial or 0))


def public_https(value):
    if not isinstance(value, str) or len(value) > 4096:
        return False
    try:
        url = urlsplit(value)
        host = (url.hostname or '').lower().rstrip('.')
        if not host or host == 'localhost' or host.endswith(('.localhost', '.local')):
            return False
        try:
            if not ipaddress.ip_address(host).is_global:
                return False
        except ValueError:
            pass
        return url.scheme == 'https' and not url.username and not url.password and not url.fragment
    except ValueError:
        return False


def normalize_feed(payload, channel):
    """A future HTTPS host uses {releases:[{version,notes,url,assets:[...]}]}."""
    rows = payload.get('releases') if isinstance(payload, dict) else payload
    if not isinstance(rows, list):
        raise ValueError('Invalid update feed')
    releases = []
    for row in rows[:100]:
        if not isinstance(row, dict) or row.get('draft'):
            continue
        version = row.get('tag_name', row.get('version', ''))
        try:
            key = version_key(version)
        except ValueError:
            continue
        if channel == 'stable' and (row.get('prerelease') or key[3] != 3):
            continue
        url = row.get('html_url', row.get('url', ''))
        if not public_https(url):
            continue
        assets = []
        raw_assets = row.get('assets')
        for asset in (raw_assets if isinstance(raw_assets, list) else [])[:100]:
            if not isinstance(asset, dict):
                continue
            link = asset.get('browser_download_url', asset.get('url', ''))
            name = str(asset.get('name', ''))[:250]
            if public_https(link) and name.lower().endswith(('.apk', '.zip', '.tar.gz', '.exe', '.dmg', '.appimage')):
                assets.append({'name': name, 'label': str(asset.get('label') or name)[:250], 'url': link,
                               'size': asset.get('size') if type(asset.get('size')) is int and asset['size'] >= 0 else None})
        releases.append((key, {'version': str(version), 'notes': str(row.get('body', row.get('notes', '')))[:16000],
                               'url': url, 'assets': assets}))
    return max(releases, key=lambda item: item[0])[1] if releases else None


class AppUpdates:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()

    async def check(self, channel='beta', refresh=False):
        current = current_version()
        if getenv('ANIMELAB_UPDATE_CHECK_DISABLED', '').lower() in ('1', 'true', 'yes'):
            return {'status': 'offline', 'currentVersion': current, 'channel': channel, 'release': None}
        feed = getenv('ANIMELAB_UPDATE_FEED_URL', GITHUB_FEED)
        key = (feed, channel, current)
        async with self.lock:
            previous = self.cache.get(key)
            if previous and time.monotonic() < previous[0] and (not refresh or time.monotonic() - previous[2] < 60):
                return previous[1]
            result = {'status': 'offline', 'currentVersion': current, 'channel': channel, 'release': None}
            try:
                if not public_https(feed) or not await is_safe_url_async(feed):
                    raise ValueError('Update feed must be public HTTPS')
                async with httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0), follow_redirects=False) as client:
                    async with client.stream('GET', feed, headers={'Accept': 'application/json', 'User-Agent': 'AnimeLab-update-check'}) as response:
                        response.raise_for_status()
                        data = bytearray()
                        async for chunk in response.aiter_bytes():
                            data.extend(chunk)
                            if len(data) > MAX_FEED_BYTES:
                                raise ValueError('Update feed too large')
                release = normalize_feed(json.loads(data), channel)
                if release:
                    result['release'] = release
                    result['status'] = 'available' if version_key(release['version']) > version_key(current) else 'current'
                else:
                    result['status'] = 'empty'
            except (httpx.HTTPError, ValueError, TypeError, KeyError) as exc:
                # Offline startup is usable; never expose URLs with credentials,
                # upstream response bodies or untrusted HTML in the interface.
                telemetry.event('update_check_failed', code=type(exc).__name__)
            checked_at = time.monotonic()
            self.cache[key] = (checked_at + (3600 if result['status'] != 'offline' else 60), result, checked_at)
            return result


app_updates = AppUpdates()
