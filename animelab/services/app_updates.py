"""Bounded, cached update metadata and user-initiated in-app release installer."""
import asyncio
import hashlib
import json
import ipaddress
import os
import platform
import re
import shutil
import stat
import subprocess
import tarfile
import time
import sys
import zipfile
from pathlib import Path
from urllib.parse import urljoin, urlsplit
import httpx
from animelab import __version__, platform_events
from animelab.config import IS_ANDROID, settings
from animelab.diagnostics import telemetry
from animelab.environment import getenv
from animelab.security import is_safe_url_async

GITHUB_FEED = 'https://api.github.com/repos/loeuf237/animelab/releases?per_page=10'
MAX_FEED_BYTES = 512 * 1024
MAX_ASSET_BYTES = 512 * 1024 * 1024
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
        checksums_url = None
        raw_assets = row.get('assets')
        for asset in (raw_assets if isinstance(raw_assets, list) else [])[:100]:
            if not isinstance(asset, dict):
                continue
            link = asset.get('browser_download_url', asset.get('url', ''))
            name = str(asset.get('name', ''))[:250]
            if public_https(link) and name == 'SHA256SUMS.txt':
                checksums_url = link
            elif public_https(link) and name.lower().endswith(('.apk', '.zip', '.tar.gz', '.exe', '.dmg', '.appimage')):
                assets.append({'name': name, 'label': str(asset.get('label') or name)[:250], 'url': link,
                               'size': asset.get('size') if type(asset.get('size')) is int and asset['size'] >= 0 else None})
        entry = {'version': str(version), 'notes': str(row.get('body', row.get('notes', '')))[:16000],
                 'url': url, 'assets': assets}
        if checksums_url:
            entry['checksumsUrl'] = checksums_url
        releases.append((key, entry))
    return max(releases, key=lambda item: item[0])[1] if releases else None


def select_platform_asset(assets, runtime=None, os_name=None, arch=None):
    if not assets:
        return None
    rt = runtime or ('android' if IS_ANDROID else 'desktop')
    system = (os_name or ('android' if IS_ANDROID else platform.system())).lower()
    machine = (arch or platform.machine()).lower()
    if rt == 'android' or system == 'android':
        for asset in assets:
            if asset['name'].lower().endswith('.apk'):
                return asset
    for asset in assets:
        lower = asset['name'].lower()
        if system == 'windows' and 'windows' in lower:
            return asset
        if system == 'darwin' and 'macos' in lower and (('arm64' in machine) == ('arm64' in lower)):
            return asset
        if system == 'linux' and 'linux' in lower:
            return asset
    return assets[0]


def _extract_release_archive(archive_path: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root_resolved = destination.resolve()
    lower = archive_path.name.lower()
    if lower.endswith('.zip'):
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for member in zf.infolist():
                target = (destination / member.filename).resolve()
                if target != root_resolved and root_resolved not in target.parents:
                    raise ValueError('Unsafe path inside release ZIP archive')
                if member.is_dir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                with zf.open(member, 'r') as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                unix_mode = (member.external_attr >> 16) & 0o777
                if unix_mode and os.name == 'posix':
                    target.chmod(unix_mode)
    elif lower.endswith('.tar.gz'):
        with tarfile.open(archive_path, 'r:gz') as tf:
            for member in tf.getmembers():
                if member.issym() or member.islnk() or member.isdev():
                    continue
                target = (destination / member.name).resolve()
                if target != root_resolved and root_resolved not in target.parents:
                    raise ValueError('Unsafe path inside release TAR archive')
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    extracted = tf.extractfile(member)
                    if extracted is not None:
                        with extracted, target.open('wb') as dst:
                            shutil.copyfileobj(extracted, dst)
                    if os.name == 'posix' and (member.mode & 0o111):
                        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    else:
        raise ValueError('Unsupported archive format')
    children = [p for p in destination.iterdir() if not p.name.startswith('.')]
    return children[0] if len(children) == 1 and children[0].is_dir() else destination


def _find_extracted_executable(folder: Path) -> Path | None:
    candidates = [
        folder / 'AnimeLab.exe',
        folder / 'AnimeLab',
        folder / 'AnimeLab.app' / 'Contents' / 'MacOS' / 'AnimeLab',
    ]
    for candidate in candidates:
        if candidate.is_file():
            return candidate
    for depth_candidate in folder.glob('*/AnimeLab*'):
        if depth_candidate.is_file() and depth_candidate.name in ('AnimeLab', 'AnimeLab.exe'):
            return depth_candidate
    return None


class AppUpdates:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()
        self._install_task: asyncio.Task | None = None
        self._install_state = {
            'state': 'idle',
            'version': None,
            'assetName': None,
            'downloadedBytes': 0,
            'totalBytes': 0,
            'percent': 0,
            'filePath': None,
            'installDir': None,
            'executablePath': None,
            'restartRequired': False,
            'message': None,
            'error': None,
        }

    def install_status(self):
        return dict(self._install_state)

    async def _download_redirect_checked(self, url: str, max_bytes: int, on_chunk=None) -> bytes:
        current_url = url
        for _ in range(6):
            if not public_https(current_url) or not await is_safe_url_async(current_url):
                raise ValueError('Update asset URL must be public HTTPS')
            async with httpx.AsyncClient(timeout=httpx.Timeout(60.0, connect=10.0), follow_redirects=False) as client:
                async with client.stream('GET', current_url, headers={'User-Agent': 'AnimeLab-update-installer'}) as response:
                    if response.status_code in (301, 302, 303, 307, 308):
                        location = response.headers.get('Location', '')
                        if not location:
                            raise ValueError('Redirect missing Location header')
                        current_url = urljoin(current_url, location)
                        continue
                    response.raise_for_status()
                    content_length = int(response.headers.get('Content-Length') or 0)
                    if content_length > max_bytes:
                        raise ValueError('Update payload exceeds size limit')
                    buf = bytearray()
                    async for chunk in response.aiter_bytes():
                        buf.extend(chunk)
                        if len(buf) > max_bytes:
                            raise ValueError('Update payload exceeds size limit')
                        if on_chunk is not None:
                            on_chunk(chunk, content_length)
                    return bytes(buf)
        raise ValueError('Too many redirects while downloading update')

    async def start_install(self, url: str | None = None, channel: str = 'beta') -> dict:
        if self._install_task is not None and not self._install_task.done():
            return self.install_status()
        check_result = await self.check(channel=channel)
        release = check_result.get('release')
        if not release or not release.get('assets'):
            raise ValueError('No installable release asset is available')
        assets = release['assets']
        if url:
            asset = next((item for item in assets if item['url'] == url), None)
            if asset is None:
                raise ValueError('Requested asset URL is not part of the verified release')
        else:
            asset = select_platform_asset(assets)
            if asset is None:
                raise ValueError('No compatible asset found for this platform')

        updates_dir = Path(settings.CACHE_DIR) / 'app-updates'
        updates_dir.mkdir(parents=True, exist_ok=True)
        safe_name = re.sub(r'[^A-Za-z0-9._-]', '_', asset['name'])
        dest_path = updates_dir / safe_name
        total_hint = int(asset.get('size') or 0)
        self._install_state = {
            'state': 'downloading',
            'version': release['version'],
            'assetName': asset['name'],
            'downloadedBytes': 0,
            'totalBytes': total_hint,
            'percent': 0,
            'filePath': None,
            'installDir': None,
            'executablePath': None,
            'restartRequired': False,
            'message': 'Téléchargement de la mise à jour…',
            'error': None,
        }
        self._install_task = asyncio.create_task(self._run_install(asset, release, dest_path, updates_dir))
        try:
            await asyncio.wait_for(asyncio.shield(self._install_task), timeout=0.35)
        except (asyncio.TimeoutError, Exception):
            pass
        return self.install_status()

    async def _run_install(self, asset: dict, release: dict, dest_path: Path, updates_dir: Path):
        part_path = dest_path.with_name(dest_path.name + '.part')
        digest = hashlib.sha256()
        try:
            current_url = asset['url']
            redirect_hops = 0
            while True:
                if not public_https(current_url) or not await is_safe_url_async(current_url):
                    raise ValueError('Update asset URL must be public HTTPS')
                async with httpx.AsyncClient(timeout=httpx.Timeout(120.0, connect=10.0), follow_redirects=False) as client:
                    async with client.stream('GET', current_url, headers={'User-Agent': 'AnimeLab-update-installer'}) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            redirect_hops += 1
                            if redirect_hops > 6:
                                raise ValueError('Too many redirects while downloading update')
                            location = response.headers.get('Location', '')
                            if not location:
                                raise ValueError('Redirect missing Location header')
                            current_url = urljoin(current_url, location)
                            continue
                        response.raise_for_status()
                        header_total = int(response.headers.get('Content-Length') or 0)
                        total = header_total or int(asset.get('size') or 0)
                        if total > MAX_ASSET_BYTES:
                            raise ValueError('Update asset is too large')
                        self._install_state['totalBytes'] = total
                        downloaded = 0
                        with part_path.open('wb') as out:
                            async for chunk in response.aiter_bytes():
                                downloaded += len(chunk)
                                if downloaded > MAX_ASSET_BYTES:
                                    raise ValueError('Update asset exceeded maximum size')
                                out.write(chunk)
                                digest.update(chunk)
                                self._install_state['downloadedBytes'] = downloaded
                                if total > 0:
                                    self._install_state['percent'] = min(99, int((downloaded * 100) / total))
                        break

            actual_sha256 = digest.hexdigest()
            checksums_url = release.get('checksumsUrl')
            if checksums_url:
                self._install_state['state'] = 'verifying'
                self._install_state['message'] = 'Vérification de l’intégrité du paquet…'
                raw_sums = (await self._download_redirect_checked(checksums_url, 64 * 1024)).decode('utf-8', errors='replace')
                expected_sha256 = None
                for line in raw_sums.splitlines():
                    parts = line.strip().split()
                    if len(parts) >= 2 and parts[-1].lstrip('*') == asset['name']:
                        expected_sha256 = parts[0].lower()
                        break
                if expected_sha256 and actual_sha256.lower() != expected_sha256:
                    raise ValueError('Checksum verification failed for downloaded update')

            part_path.replace(dest_path)
            self._install_state['filePath'] = str(dest_path)
            self._install_state['percent'] = 100
            self._install_state['state'] = 'installing'
            self._install_state['message'] = 'Installation de la mise à jour…'

            lower_name = dest_path.name.lower()
            if IS_ANDROID or (lower_name.endswith('.apk') and platform_events.app_update_install_handler is not None):
                op = await asyncio.to_thread(platform_events.install_app_update, str(dest_path)) or {}
                op_state = op.get('state') or 'installing'
                if op_state == 'permission_required':
                    self._install_state['state'] = 'permission_required'
                    self._install_state['message'] = (
                        'Autorisez l’installation d’applications dans les paramètres Android puis réessayez.'
                    )
                elif op_state in ('waiting_user', 'installing', 'preparing'):
                    self._install_state['state'] = 'waiting_user'
                    self._install_state['message'] = (
                        'Confirmez l’installation de la mise à jour dans la boîte de dialogue Android.'
                    )
                elif op_state == 'installed':
                    self._install_state['state'] = 'completed'
                    self._install_state['message'] = 'Mise à jour installée avec succès.'
                else:
                    self._install_state['state'] = 'failed'
                    self._install_state['error'] = str(op.get('error') or 'package_installer_failed')
                    self._install_state['message'] = 'L’installation Android a échoué.'
            elif lower_name.endswith(('.zip', '.tar.gz')):
                version_slug = re.sub(r'[^A-Za-z0-9._-]', '_', str(release['version']))
                target_root = updates_dir / f'installed-{version_slug}'
                extracted_root = await asyncio.to_thread(_extract_release_archive, dest_path, target_root)
                executable = await asyncio.to_thread(_find_extracted_executable, extracted_root)
                self._install_state['installDir'] = str(extracted_root)
                self._install_state['executablePath'] = str(executable) if executable else None
                self._install_state['restartRequired'] = bool(executable)
                self._install_state['state'] = 'ready' if executable else 'completed'
                self._install_state['message'] = (
                    'Mise à jour installée et prête. Cliquez sur Lancer la nouvelle version pour redémarrer.'
                    if executable
                    else 'Mise à jour téléchargée et extraite avec succès.'
                )
            else:
                self._install_state['state'] = 'completed'
                self._install_state['message'] = 'Mise à jour téléchargée et prête à être installée.'
        except Exception as exc:
            try:
                if part_path.exists():
                    part_path.unlink()
            except OSError:
                pass
            telemetry.event('update_install_failed', code=type(exc).__name__)
            self._install_state['state'] = 'failed'
            self._install_state['error'] = type(exc).__name__
            self._install_state['message'] = 'Le téléchargement ou l’installation de la mise à jour a échoué.'

    async def apply_installed_update(self) -> dict:
        state = self._install_state
        if IS_ANDROID or (state.get('filePath', '') or '').lower().endswith('.apk'):
            file_path = state.get('filePath')
            if not file_path or not Path(file_path).is_file():
                raise ValueError('No downloaded APK update is available')
            if platform_events.app_update_install_handler is not None:
                op = await asyncio.to_thread(platform_events.install_app_update, str(file_path)) or {}
                op_state = op.get('state') or 'waiting_user'
                self._install_state['state'] = 'completed' if op_state == 'installed' else op_state
            return self.install_status()

        exe_raw = state.get('executablePath') or state.get('filePath')
        if not exe_raw or not Path(exe_raw).exists():
            raise ValueError('No installed update binary is ready to launch')
        exe_path = Path(exe_raw)
        kwargs: dict = {'cwd': str(exe_path.parent)}
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'DETACHED_PROCESS', 0x00000008) | getattr(
                subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200
            )
        else:
            kwargs['start_new_session'] = True
        subprocess.Popen([str(exe_path)], **kwargs)
        self._install_state['state'] = 'completed'
        self._install_state['restartRequired'] = False
        self._install_state['message'] = 'Nouvelle version lancée.'
        if getattr(sys, 'frozen', False):
            loop = asyncio.get_running_loop()
            loop.call_later(0.4, lambda: os._exit(0))
        return self.install_status()

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
