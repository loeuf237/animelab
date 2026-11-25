"""Bounded, cached update metadata and user-initiated in-app release installer."""
import asyncio
import hashlib
import ipaddress
import json
import logging
import os
import platform
import re
import shutil
import stat
import subprocess
import sys
import tarfile
import time
import zipfile
from pathlib import Path
from typing import Any
from urllib.parse import urljoin, urlsplit
import httpx
from animelab import __version__, platform_events
from animelab.config import IS_ANDROID, settings
from animelab.diagnostics import telemetry
from animelab.environment import getenv
from animelab.security import is_safe_url_async

logger = logging.getLogger(__name__)

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


def _archive_member_target(root_resolved: Path, relative_name: str, error_message: str) -> Path:
    cleaned = relative_name.replace('\\', '/')
    if not cleaned or '\x00' in cleaned or cleaned.startswith('/'):
        raise ValueError(error_message)
    candidate = Path(os.path.normpath(str(root_resolved / cleaned)))
    if candidate != root_resolved and root_resolved not in candidate.parents:
        raise ValueError(error_message)
    return candidate


def _ensure_no_symlink_parent(root_resolved: Path, target: Path, error_message: str) -> None:
    for parent in target.parents:
        if parent == root_resolved:
            break
        if parent.is_symlink():
            raise ValueError(error_message)


def _validate_internal_link_target(root_resolved: Path, link_path: Path, link_target: str) -> Path:
    if not link_target or '\x00' in link_target:
        raise ValueError('Unsafe symlink inside release archive')
    if link_target.startswith(('/', '\\')) or Path(link_target).is_absolute():
        raise ValueError('Unsafe symlink inside release archive')
    lexical = Path(os.path.normpath(str(link_path.parent / link_target)))
    if lexical != root_resolved and root_resolved not in lexical.parents:
        raise ValueError('Unsafe symlink inside release archive')
    real = lexical.resolve(strict=False)
    if real != root_resolved and root_resolved not in real.parents:
        raise ValueError('Unsafe symlink inside release archive')
    return lexical


def _place_symlink(target: Path, link_target: str, resolved_target: Path) -> None:
    if target.is_symlink() or target.exists():
        if target.is_dir() and not target.is_symlink():
            shutil.rmtree(target)
        else:
            target.unlink()
    if os.name == 'posix':
        os.symlink(link_target, target)
    elif resolved_target.is_file():
        shutil.copy2(resolved_target, target)
    elif resolved_target.is_dir():
        shutil.copytree(resolved_target, target)


def _extract_release_archive(archive_path: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    destination.mkdir(parents=True, exist_ok=True)
    root_resolved = destination.resolve()
    lower = archive_path.name.lower()
    if lower.endswith('.zip'):
        deferred_symlinks: list[tuple[zipfile.ZipInfo, Path]] = []
        with zipfile.ZipFile(archive_path, 'r') as zf:
            for member in zf.infolist():
                target = _archive_member_target(
                    root_resolved, member.filename, 'Unsafe path inside release ZIP archive'
                )
                if target == root_resolved:
                    if member.is_dir():
                        continue
                    raise ValueError('Unsafe path inside release ZIP archive')
                mode = member.external_attr >> 16
                if stat.S_ISLNK(mode):
                    deferred_symlinks.append((member, target))
                    continue
                if member.is_dir():
                    _ensure_no_symlink_parent(root_resolved, target, 'Unsafe path inside release ZIP archive')
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                target.parent.mkdir(parents=True, exist_ok=True)
                _ensure_no_symlink_parent(root_resolved, target, 'Unsafe path inside release ZIP archive')
                with zf.open(member, 'r') as src, target.open('wb') as dst:
                    shutil.copyfileobj(src, dst)
                unix_mode = mode & 0o777
                if unix_mode and os.name == 'posix':
                    target.chmod(unix_mode)
            for member, target in deferred_symlinks:
                link_target = zf.read(member).decode('utf-8', errors='strict').strip('\x00')
                resolved = _validate_internal_link_target(root_resolved, target, link_target)
                target.parent.mkdir(parents=True, exist_ok=True)
                _ensure_no_symlink_parent(root_resolved, target, 'Unsafe symlink inside release archive')
                _place_symlink(target, link_target, resolved)
    elif lower.endswith('.tar.gz'):
        deferred_links: list[tuple[tarfile.TarInfo, Path]] = []
        with tarfile.open(archive_path, 'r:gz') as tf:
            for member in tf.getmembers():
                if member.isdev() or member.ischr() or member.isblk() or member.isfifo():
                    continue
                target = _archive_member_target(
                    root_resolved, member.name, 'Unsafe path inside release TAR archive'
                )
                if target == root_resolved:
                    if member.isdir():
                        continue
                    raise ValueError('Unsafe path inside release TAR archive')
                if member.issym() or member.islnk():
                    deferred_links.append((member, target))
                    continue
                if member.isdir():
                    _ensure_no_symlink_parent(root_resolved, target, 'Unsafe path inside release TAR archive')
                    target.mkdir(parents=True, exist_ok=True)
                    continue
                if member.isfile():
                    target.parent.mkdir(parents=True, exist_ok=True)
                    _ensure_no_symlink_parent(root_resolved, target, 'Unsafe path inside release TAR archive')
                    extracted = tf.extractfile(member)
                    if extracted is not None:
                        with extracted, target.open('wb') as dst:
                            shutil.copyfileobj(extracted, dst)
                    if os.name == 'posix' and (member.mode & 0o111):
                        target.chmod(target.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
            for member, target in deferred_links:
                target.parent.mkdir(parents=True, exist_ok=True)
                _ensure_no_symlink_parent(root_resolved, target, 'Unsafe symlink inside release archive')
                if member.issym():
                    resolved = _validate_internal_link_target(root_resolved, target, member.linkname)
                    _place_symlink(target, member.linkname, resolved)
                elif member.islnk():
                    hard_target = _archive_member_target(
                        root_resolved, member.linkname, 'Unsafe symlink inside release archive'
                    )
                    if hard_target == root_resolved or hard_target.is_symlink() or not hard_target.exists():
                        raise ValueError('Unsafe symlink inside release archive')
                    _ensure_no_symlink_parent(root_resolved, hard_target, 'Unsafe symlink inside release archive')
                    if target.is_symlink() or target.exists():
                        target.unlink()
                    try:
                        os.link(hard_target, target)
                    except OSError:
                        shutil.copy2(hard_target, target)
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
    found: Path | None = None
    for candidate in candidates:
        if candidate.is_file():
            found = candidate
            break
    if found is None:
        for depth_candidate in folder.glob('*/AnimeLab*'):
            if depth_candidate.is_file() and depth_candidate.name in ('AnimeLab', 'AnimeLab.exe'):
                found = depth_candidate
                break
    if found is not None and os.name == 'posix' and found.suffix.lower() != '.exe':
        found.chmod(found.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
    return found


def _clean_update_launch_env(base_env: dict[str, str] | None = None) -> dict[str, str]:
    env = dict(os.environ if base_env is None else base_env)
    is_frozen = getattr(sys, 'frozen', False)
    for var in ('LD_LIBRARY_PATH', 'DYLD_LIBRARY_PATH', 'DYLD_FRAMEWORK_PATH', 'LIBPATH'):
        orig_key = f'{var}_ORIG'
        if orig_key in env:
            env[var] = env.pop(orig_key)
        elif is_frozen:
            env.pop(var, None)
    for var in (
        '_MEIPASS2',
        'TCL_LIBRARY',
        'TK_LIBRARY',
        'QT_PLUGIN_PATH',
        'QML2_IMPORT_PATH',
        'ANIMELAB_RELEASE_VERSION',
        'ANIMAN_DESKTOP_PREFERENCES',
        'ANIMAN_PORT',
        'ANIMAN_HOST',
        'ANIMAN_RELOAD',
        'ANIMAN_ALLOWED_HOSTS',
        'ANIMELAB_DESKTOP_AUTH',
    ):
        env.pop(var, None)
    if is_frozen and hasattr(sys, '_MEIPASS'):
        meipass_bin = os.path.normcase(os.path.normpath(str(Path(sys._MEIPASS) / 'bin')))
        raw_path = env.get('PATH', '')
        if raw_path:
            parts = [
                entry
                for entry in raw_path.split(os.pathsep)
                if entry and os.path.normcase(os.path.normpath(entry)) != meipass_bin
            ]
            env['PATH'] = os.pathsep.join(parts)
    return env


def _desktop_launch_command(exe_path: Path, platform_name: str | None = None) -> list[str]:
    target_platform = platform_name or sys.platform
    if target_platform == 'darwin':
        if (
            exe_path.parent.name == 'MacOS'
            and len(exe_path.parents) >= 3
            and exe_path.parents[2].suffix == '.app'
            and shutil.which('open')
        ):
            return ['open', '-n', str(exe_path.parents[2]), '--args', '--launch', '--replace-instance']
        if exe_path.suffix.lower() == '.dmg' and shutil.which('open'):
            return ['open', str(exe_path)]
    if exe_path.name in ('AnimeLab', 'AnimeLab.exe'):
        return [str(exe_path), '--launch', '--replace-instance']
    return [str(exe_path)]


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open('rb') as handle:
        while chunk := handle.read(65536):
            digest.update(chunk)
    return digest.hexdigest()


class AppUpdates:
    def __init__(self):
        self.cache = {}
        self.lock = asyncio.Lock()
        self._install_task: asyncio.Task | None = None
        self._install_state: dict[str, Any] = {
            'state': 'idle',
            'version': None,
            'assetName': None,
            'downloadedBytes': 0,
            'totalBytes': 0,
            'percent': 0,
            'filePath': None,
            'installDir': None,
            'executablePath': None,
            'operationId': None,
            'restartRequired': False,
            'message': None,
            'error': None,
        }

    def _apply_android_operation(self, op: dict) -> None:
        if op.get('id'):
            self._install_state['operationId'] = str(op['id'])
        op_state = op.get('state') or 'installing'
        if op_state == 'permission_required':
            self._install_state['state'] = 'permission_required'
            self._install_state['error'] = None
            self._install_state['message'] = (
                'Autorisez l’installation d’applications dans les paramètres Android puis réessayez.'
            )
        elif op_state in ('waiting_user', 'installing', 'preparing'):
            self._install_state['state'] = 'waiting_user'
            self._install_state['error'] = None
            self._install_state['message'] = (
                'Confirmez l’installation de la mise à jour dans la boîte de dialogue Android.'
            )
        elif op_state == 'installed':
            self._install_state['state'] = 'completed'
            self._install_state['error'] = None
            self._install_state['message'] = 'Mise à jour installée avec succès.'
        elif op_state == 'cancelled':
            self._install_state['state'] = 'cancelled'
            self._install_state['error'] = str(op.get('error')) if op.get('error') else None
            self._install_state['message'] = (
                'Installation annulée. Vous pouvez rouvrir l’installeur Android.'
            )
        else:
            self._install_state['state'] = 'failed'
            self._install_state['error'] = str(op.get('error') or 'package_installer_failed')
            self._install_state['message'] = 'L’installation Android a échoué.'

    def install_status(self):
        op_id = self._install_state.get('operationId')
        if (
            op_id
            and self._install_state.get('state') in ('installing', 'waiting_user', 'permission_required')
            and platform_events.app_update_status_handler is not None
        ):
            try:
                op = platform_events.app_update_status(str(op_id))
                if isinstance(op, dict) and op.get('state'):
                    self._apply_android_operation(op)
            except Exception:
                logger.exception('Failed to refresh native app update status')
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

    async def _fetch_expected_sha256(self, checksums_url: str, asset_name: str) -> str | None:
        raw_sums = (await self._download_redirect_checked(checksums_url, 64 * 1024)).decode(
            'utf-8', errors='replace'
        )
        for line in raw_sums.splitlines():
            parts = line.strip().split()
            if len(parts) >= 2 and parts[-1].lstrip('*') == asset_name:
                return parts[0].lower()
        return None

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
            'operationId': None,
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
        checksums_url = release.get('checksumsUrl')
        expected_sha256: str | None = None
        try:
            already_verified = False
            if checksums_url and dest_path.is_file() and dest_path.stat().st_size > 0:
                self._install_state['state'] = 'verifying'
                self._install_state['message'] = 'Vérification de l’intégrité du paquet…'
                expected_sha256 = await self._fetch_expected_sha256(checksums_url, asset['name'])
                if expected_sha256:
                    existing_sha = await asyncio.to_thread(_file_sha256, dest_path)
                    if existing_sha.lower() == expected_sha256:
                        already_verified = True
                        size = dest_path.stat().st_size
                        self._install_state['downloadedBytes'] = size
                        self._install_state['totalBytes'] = size

            if not already_verified:
                self._install_state['state'] = 'downloading'
                self._install_state['message'] = 'Téléchargement de la mise à jour…'
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
                if checksums_url:
                    self._install_state['state'] = 'verifying'
                    self._install_state['message'] = 'Vérification de l’intégrité du paquet…'
                    if expected_sha256 is None:
                        expected_sha256 = await self._fetch_expected_sha256(checksums_url, asset['name'])
                    if expected_sha256 and actual_sha256.lower() != expected_sha256:
                        raise ValueError('Checksum verification failed for downloaded update')

                part_path.replace(dest_path)

            self._install_state['filePath'] = str(dest_path)
            self._install_state['percent'] = 100
            self._install_state['state'] = 'installing'
            self._install_state['message'] = 'Installation de la mise à jour…'

            lower_name = dest_path.name.lower()
            if IS_ANDROID or (lower_name.endswith('.apk') and platform_events.app_update_install_handler is not None):
                op = await asyncio.to_thread(platform_events.install_app_update, str(dest_path))
                if not isinstance(op, dict):
                    raise RuntimeError('Android installer handler returned no status')
                self._apply_android_operation(op)
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
            logger.exception('In-app update installation failed')
            if dest_path.is_file() and not self._install_state.get('filePath'):
                self._install_state['filePath'] = str(dest_path)
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
            if (
                platform_events.app_update_confirm_handler is not None
                or platform_events.app_update_install_handler is not None
            ):
                op = await asyncio.to_thread(
                    platform_events.confirm_app_update,
                    state.get('operationId'),
                    str(file_path),
                )
                if isinstance(op, dict) and op:
                    self._apply_android_operation(op)
            return self.install_status()

        exe_raw = state.get('executablePath') or state.get('filePath')
        if not exe_raw or not Path(exe_raw).exists():
            raise ValueError('No installed update binary is ready to launch')
        exe_path = Path(exe_raw)
        if os.name == 'posix' and exe_path.suffix.lower() in ('', '.appimage', '.sh'):
            exe_path.chmod(exe_path.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP)
        command = _desktop_launch_command(exe_path)
        kwargs: dict[str, Any] = {
            'cwd': str(exe_path.parent),
            'env': _clean_update_launch_env(),
            'stdin': subprocess.DEVNULL,
            'stdout': subprocess.DEVNULL,
            'stderr': subprocess.DEVNULL,
        }
        if os.name == 'nt':
            kwargs['creationflags'] = getattr(subprocess, 'DETACHED_PROCESS', 0x00000008) | getattr(
                subprocess, 'CREATE_NEW_PROCESS_GROUP', 0x00000200
            )
        else:
            kwargs['start_new_session'] = True
        try:
            subprocess.Popen(command, **kwargs)
        except OSError as exc:
            raise ValueError(f'Unable to launch installed update: {type(exc).__name__}') from exc
        self._install_state['state'] = 'completed'
        self._install_state['restartRequired'] = False
        self._install_state['error'] = None
        self._install_state['message'] = 'Nouvelle version lancée.'
        has_supervisor = False
        try:
            from animelab.desktop.control import running_record
            from animelab.desktop.state import state_directory

            has_supervisor = bool(running_record(state_directory()))
        except Exception:
            has_supervisor = False
        if getattr(sys, 'frozen', False) and not has_supervisor:
            loop = asyncio.get_running_loop()
            loop.call_later(0.6, lambda: os._exit(0))
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
