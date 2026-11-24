"""Safe desktop external video player launching and scoped Android media tickets."""
from __future__ import annotations

from collections import OrderedDict
import json
import os
from pathlib import Path
import plistlib
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import threading
import time
import urllib.parse

from animelab.config import settings

PRESETS = frozenset({'none', 'mpv', 'vlc', 'custom', 'system'})
DEFAULTS: dict[str, object] = {
    'preset': 'none',
    'customPath': '',
    'preferExternal': False,
}

_WINDOWS_SCRIPT_EXTS = frozenset(
    {'.bat', '.cmd', '.ps1', '.vbs', '.vbe', '.js', '.jse', '.wsf', '.wsh'}
)
_CONTROL_CHARS_RE = re.compile(r'[\x00-\x1f\x7f]')
_SAFE_BARE_NAME_RE = re.compile(r'^[A-Za-z0-9._+-]+$')
_TICKET_RE = re.compile(r'^[A-Za-z0-9_-]{16,128}$')
_LOCAL_STREAM_RE = re.compile(r'^/api/media/stream/([^/?#]+)$')
_EXT_RESOURCE_RE = re.compile(r'^/api/media/extension-resource/[A-Za-z0-9_-]+$')
_LOCAL_SUBTITLE_RE = re.compile(r'^/api/media/subtitle/([^/?#]+)(?:/\d+)?$')


def sanitize_title(title: str | None) -> str:
    """Strip control characters and collapse whitespace for player window titles."""
    cleaned = _CONTROL_CHARS_RE.sub(' ', str(title or ''))
    return ' '.join(cleaned.split())[:200]


def valid_ticket_format(value: str | None) -> str | None:
    """Return *value* only if it matches the generated media ticket format."""
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    return stripped if _TICKET_RE.fullmatch(stripped) else None


def append_media_ticket(url: str, ticket: str) -> str:
    """Attach *media_ticket* cleanly to a local media endpoint URL."""
    parts = urllib.parse.urlsplit(url)
    query_pairs = urllib.parse.parse_qsl(parts.query, keep_blank_values=True)
    query_pairs = [(k, v) for k, v in query_pairs if k != 'media_ticket']
    query_pairs.append(('media_ticket', ticket))
    new_query = urllib.parse.urlencode(query_pairs)
    return urllib.parse.urlunsplit((parts.scheme, parts.netloc, parts.path, new_query, parts.fragment))


def extract_local_task_id(stream_url: str | None) -> str | None:
    """Extract a download task ID when *stream_url* points to `/api/media/stream/<taskId>`."""
    if not isinstance(stream_url, str):
        return None
    path = urllib.parse.urlsplit(stream_url.strip()).path
    match = _LOCAL_STREAM_RE.fullmatch(path)
    if not match:
        return None
    return urllib.parse.unquote(match.group(1))


def local_loopback_origin(base_url: str | None, fallback_port: int) -> str:
    """Resolve the active local HTTP origin for passing stream URLs to external players."""
    parsed = urllib.parse.urlsplit(str(base_url or ''))
    if parsed.scheme == 'http' and parsed.hostname in ('127.0.0.1', 'localhost', '::1'):
        host = f'[{parsed.hostname}]' if ':' in parsed.hostname else parsed.hostname
        port = parsed.port
        return f'http://{host}:{port}' if port else f'http://{host}'
    return f'http://127.0.0.1:{fallback_port}'


def _resolve_macos_bundle_executable(bundle: Path) -> Path:
    plist_path = bundle / 'Contents' / 'Info.plist'
    if plist_path.is_file():
        try:
            with plist_path.open('rb') as handle:
                info = plistlib.load(handle)
            exe_name = info.get('CFBundleExecutable')
            if isinstance(exe_name, str) and exe_name.strip():
                candidate = bundle / 'Contents' / 'MacOS' / exe_name.strip()
                if candidate.is_file():
                    return candidate
        except Exception:
            pass
    return bundle / 'Contents' / 'MacOS' / bundle.stem


def validate_player_executable(value: str) -> str:
    """Validate and resolve a desktop external player binary path safely."""
    if not isinstance(value, str) or len(value) > 4096 or _CONTROL_CHARS_RE.search(value):
        raise ValueError('Chemin d’exécutable de lecteur invalide.')
    cleaned = value.strip()
    if not cleaned or cleaned.startswith('-'):
        raise ValueError('Chemin d’exécutable de lecteur invalide.')

    expanded = Path(cleaned).expanduser()
    has_path_sep = (
        '/' in cleaned or '\\' in cleaned or expanded.is_absolute() or cleaned.startswith('~')
    )
    if has_path_sep:
        target = (
            _resolve_macos_bundle_executable(expanded)
            if expanded.is_dir() and expanded.suffix.lower() == '.app'
            else expanded
        )
        try:
            resolved = str(target.resolve())
        except OSError as exc:
            raise ValueError('Lecteur externe introuvable sur cette machine.') from exc
    else:
        if not _SAFE_BARE_NAME_RE.fullmatch(cleaned):
            raise ValueError('Nom d’exécutable de lecteur invalide.')
        resolved_which = shutil.which(cleaned)
        if not resolved_which:
            raise ValueError(f'Lecteur « {cleaned} » introuvable dans le PATH.')
        resolved = str(Path(resolved_which).resolve())

    exe_path = Path(resolved)
    if not exe_path.is_file():
        raise ValueError('Lecteur externe introuvable sur cette machine.')
    if sys.platform == 'win32' and exe_path.suffix.lower() in _WINDOWS_SCRIPT_EXTS:
        raise ValueError('Les scripts batch/PowerShell ne sont pas autorisés comme lecteur.')
    if sys.platform != 'win32' and not os.access(exe_path, os.X_OK):
        raise ValueError('Le fichier sélectionné n’est pas exécutable.')
    return resolved


def detect_installed_players(*, is_android: bool = False) -> list[dict[str, str]]:
    """Discover supported external media players installed on this device."""
    if is_android:
        return [{'id': 'system', 'label': 'Lecteur système Android', 'path': ''}]

    detected: list[dict[str, str]] = []
    candidates: tuple[tuple[str, str, tuple[str, ...]], ...] = (
        (
            'mpv',
            'mpv',
            (
                'mpv',
                '/usr/bin/mpv',
                '/usr/local/bin/mpv',
                '/opt/homebrew/bin/mpv',
                '/Applications/mpv.app',
                str(Path.home() / 'Applications' / 'mpv.app'),
                r'C:\Program Files\mpv\mpv.exe',
                r'C:\Program Files (x86)\mpv\mpv.exe',
            ),
        ),
        (
            'vlc',
            'VLC',
            (
                'vlc',
                '/usr/bin/vlc',
                '/usr/local/bin/vlc',
                '/snap/bin/vlc',
                '/Applications/VLC.app',
                str(Path.home() / 'Applications' / 'VLC.app'),
                r'C:\Program Files\VideoLAN\VLC\vlc.exe',
                r'C:\Program Files (x86)\VideoLAN\VLC\vlc.exe',
            ),
        ),
    )
    for player_id, label, probes in candidates:
        for probe in probes:
            try:
                resolved = validate_player_executable(probe)
            except ValueError:
                continue
            detected.append({'id': player_id, 'label': label, 'path': resolved})
            break
    return detected


def _player_kind(executable_path: str) -> str:
    stem = Path(executable_path).stem.lower()
    if stem == 'mpv' or stem.startswith('mpv-') or 'mpv' == stem:
        return 'mpv'
    if stem == 'vlc' or stem.startswith('vlc'):
        return 'vlc'
    return 'generic'


def _validate_launch_arg(arg: str, label: str) -> str:
    if not isinstance(arg, str) or not arg or len(arg) > 8192 or _CONTROL_CHARS_RE.search(arg):
        raise ValueError(f'{label} invalide pour le lecteur externe.')
    if arg.startswith('-'):
        raise ValueError(f'{label} invalide pour le lecteur externe.')
    return arg


def build_player_command(
    executable: str,
    target: str,
    *,
    title: str = '',
    subtitles: list[str] | None = None,
) -> list[str]:
    """Construct a safe argument vector (`shell=False`) for launching an external player."""
    exe = validate_player_executable(executable)
    clean_target = _validate_launch_arg(target.strip(), 'Cible média')
    clean_title = sanitize_title(title)
    clean_subs: list[str] = []
    for sub in subtitles or []:
        if not isinstance(sub, str):
            continue
        stripped = sub.strip()
        if not stripped or stripped.startswith('-') or _CONTROL_CHARS_RE.search(stripped):
            continue
        clean_subs.append(stripped)

    kind = _player_kind(exe)
    argv: list[str] = [exe]
    if kind == 'mpv':
        if clean_title:
            argv.append(f'--force-media-title={clean_title}')
        for sub in clean_subs:
            argv.append(f'--sub-file={sub}')
        argv.extend(['--', clean_target])
    elif kind == 'vlc':
        if clean_title:
            argv.append(f'--meta-title={clean_title}')
        if clean_subs:
            argv.append(f'--sub-file={clean_subs[0]}')
        argv.extend(['--', clean_target])
    else:
        argv.append(clean_target)
    return argv


def spawn_desktop_player(argv: list[str]) -> None:
    """Spawn a detached external player process without invoking a shell."""
    if sys.platform == 'win32':
        flags = getattr(subprocess, 'DETACHED_PROCESS', 0) | getattr(
            subprocess, 'CREATE_NEW_PROCESS_GROUP', 0
        )
        subprocess.Popen(
            argv,
            shell=False,
            stdin=subprocess.DEVNULL,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            creationflags=flags,
        )
        return
    subprocess.Popen(
        argv,
        shell=False,
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )


class ExternalMediaTickets:
    """Short-lived, route-scoped tickets allowing external Android players read-only access."""

    def __init__(self, limit: int = 256, ttl: float = 14400.0, clock=time.monotonic):
        self.limit = limit
        self.ttl = ttl
        self.clock = clock
        self._lock = threading.Lock()
        self._tickets: OrderedDict[str, tuple[str, str, float]] = OrderedDict()

    def _prune(self, now: float) -> None:
        expired = [k for k, (_, _, exp) in self._tickets.items() if exp <= now]
        for key in expired:
            self._tickets.pop(key, None)

    def issue(self, scope_kind: str, scope_value: str, ttl: float | None = None) -> str:
        """Issue a scoped ticket for one media target or playlist tree."""
        if not scope_kind or not scope_value:
            raise ValueError('Portée de ticket média invalide.')
        now = self.clock()
        expires = now + (ttl if ttl is not None else self.ttl)
        token = secrets.token_urlsafe(24)
        with self._lock:
            self._prune(now)
            while len(self._tickets) >= self.limit:
                self._tickets.popitem(last=False)
            self._tickets[token] = (scope_kind, scope_value, expires)
        return token

    def verify(self, token: str | None, path: str, query_string: str = '') -> bool:
        """Return True iff *token* is valid and authorizes read-only access to *path*/*query*."""
        cleaned = valid_ticket_format(token)
        if not cleaned:
            return False
        now = self.clock()
        with self._lock:
            entry = self._tickets.get(cleaned)
            if entry is None:
                return False
            scope_kind, scope_value, expires = entry
            if expires <= now:
                self._tickets.pop(cleaned, None)
                return False
            self._tickets.move_to_end(cleaned)

        params = urllib.parse.parse_qs(query_string, keep_blank_values=False)
        if scope_kind == 'task':
            return (
                path == f'/api/media/stream/{scope_value}'
                or path == f'/api/media/subtitle/{scope_value}'
                or path.startswith(f'/api/media/subtitle/{scope_value}/')
            )
        if scope_kind == 'stream-proxy':
            return path == '/api/media/stream-proxy' and params.get('url', [None])[0] == scope_value
        if scope_kind == 'hls-proxy':
            if path == '/api/media/hls-proxy/playlist.m3u8':
                return params.get('url', [None])[0] == scope_value
            return path == '/api/media/hls-proxy/segment.ts'
        if scope_kind == 'extension-resource':
            return bool(_EXT_RESOURCE_RE.fullmatch(path))
        if scope_kind == 'subtitle-proxy':
            return path == '/api/media/subtitle-proxy' and params.get('url', [None])[0] == scope_value
        return False


external_media_tickets = ExternalMediaTickets()


def validate_local_media_url(path_and_query: str, *, allow_subtitle: bool = False) -> tuple[str, str]:
    """Validate an app-relative `/api/media/...` path and return `(scope_kind, scope_value)`."""
    parsed = urllib.parse.urlsplit(path_and_query)
    if parsed.scheme or parsed.netloc:
        raise ValueError('Chemin média relatif attendu.')
    params = urllib.parse.parse_qs(parsed.query, keep_blank_values=False)

    if parsed.path == '/api/media/stream-proxy':
        upstream = params.get('url', [''])[0]
        if not upstream:
            raise ValueError('Paramètre url manquant pour le flux proxy.')
        return ('stream-proxy', upstream)

    if parsed.path == '/api/media/hls-proxy/playlist.m3u8':
        upstream = params.get('url', [''])[0]
        if not upstream:
            raise ValueError('Paramètre url manquant pour la playlist HLS.')
        return ('hls-proxy', upstream)

    if _EXT_RESOURCE_RE.fullmatch(parsed.path):
        token = parsed.path.rsplit('/', 1)[-1]
        from animelab.services.extension_media import extension_media

        extension_media.get(token)
        return ('extension-resource', token)

    if allow_subtitle:
        if parsed.path == '/api/media/subtitle-proxy':
            upstream = params.get('url', [''])[0]
            if not upstream:
                raise ValueError('Paramètre url manquant pour les sous-titres.')
            return ('subtitle-proxy', upstream)
        sub_match = _LOCAL_SUBTITLE_RE.fullmatch(parsed.path)
        if sub_match:
            return ('task', urllib.parse.unquote(sub_match.group(1)))

    raise ValueError('Route média locale non prise en charge pour le lecteur externe.')


class ExternalPlayerSettings:
    """Persist and validate per-device external player configuration."""

    def __init__(self, path: Path | None = None):
        self.path = path

    def _storage_path(self) -> Path:
        return self.path or (Path(settings.CACHE_DIR) / 'external-player.json')

    def _load_raw(self) -> dict[str, object]:
        target = self._storage_path()
        try:
            data = json.loads(target.read_text(encoding='utf-8'))
        except (OSError, ValueError):
            data = {}
        if not isinstance(data, dict):
            data = {}
        preset = str(data.get('preset') or 'none')
        if preset not in PRESETS:
            preset = 'none'
        custom_path = str(data.get('customPath') or '')
        prefer_external = bool(data.get('preferExternal', False))
        return {
            'preset': preset,
            'customPath': custom_path,
            'preferExternal': prefer_external,
        }

    def resolve_configured_executable(
        self,
        data: dict[str, object] | None = None,
        *,
        is_android: bool = False,
    ) -> tuple[str, str] | None:
        """Return `(display_label, executable_path)` for Desktop, or `None` when disabled."""
        if is_android:
            return ('Android', '')
        values = data if data is not None else self._load_raw()
        preset = str(values.get('preset') or 'none')
        if preset in ('none', 'system'):
            return None
        if preset == 'custom':
            exe = validate_player_executable(str(values.get('customPath') or ''))
            return (Path(exe).stem or 'Custom', exe)
        detected = detect_installed_players(is_android=False)
        match = next((item for item in detected if item['id'] == preset), None)
        if match:
            return (match['label'], match['path'])
        exe = validate_player_executable(preset)
        return (preset.upper() if preset == 'vlc' else preset, exe)

    def snapshot(self, *, client_local: bool, is_android: bool = False) -> dict[str, object]:
        """Return public external-player capabilities without leaking paths remotely."""
        if not client_local:
            return {
                'available': False,
                'platform': 'android' if is_android else 'desktop',
                'clientLocal': False,
                'preset': 'none',
                'customPath': '',
                'preferExternal': False,
                'configured': False,
                'resolvedPath': None,
                'detected': [],
            }

        raw = self._load_raw()
        detected = detect_installed_players(is_android=is_android)
        if is_android:
            prefer_ext = bool(raw['preferExternal'] or raw['preset'] == 'system')
            preset = 'system' if prefer_ext else 'none'
            return {
                'available': True,
                'platform': 'android',
                'clientLocal': True,
                'preset': preset,
                'customPath': '',
                'preferExternal': prefer_ext,
                'configured': True,
                'resolvedPath': None,
                'detected': detected,
            }

        preset = str(raw['preset'])
        if preset == 'system':
            preset = 'none'
        resolved_path: str | None = None
        if preset != 'none':
            try:
                resolved = self.resolve_configured_executable(raw, is_android=False)
                if resolved:
                    resolved_path = resolved[1]
            except ValueError:
                resolved_path = None

        return {
            'available': True,
            'platform': 'desktop',
            'clientLocal': True,
            'preset': preset,
            'customPath': str(raw['customPath']),
            'preferExternal': bool(raw['preferExternal'] and resolved_path),
            'configured': bool(resolved_path),
            'resolvedPath': resolved_path,
            'detected': detected,
        }

    def save(self, data: dict[str, object], *, is_android: bool = False) -> dict[str, object]:
        """Validate and persist external-player settings atomically."""
        if not isinstance(data, dict):
            raise ValueError('Paramètres de lecteur externe invalides.')
        preset = str(data.get('preset') or 'none')
        custom_path = str(data.get('customPath') or '').strip()
        prefer_external = bool(data.get('preferExternal', False))

        if is_android:
            if preset not in ('none', 'system'):
                raise ValueError('Sur Android, seul le sélecteur système externe est disponible.')
            normalized_preset = 'system' if (prefer_external or preset == 'system') else 'none'
            values = {
                'preset': normalized_preset,
                'customPath': '',
                'preferExternal': prefer_external,
            }
        else:
            if preset not in ('none', 'mpv', 'vlc', 'custom'):
                raise ValueError('Préréglage de lecteur externe invalide.')
            if preset == 'none':
                values = {'preset': 'none', 'customPath': custom_path, 'preferExternal': False}
            elif preset == 'custom':
                validated = validate_player_executable(custom_path)
                values = {
                    'preset': 'custom',
                    'customPath': validated,
                    'preferExternal': prefer_external,
                }
            else:
                self.resolve_configured_executable({'preset': preset, 'customPath': ''}, is_android=False)
                values = {
                    'preset': preset,
                    'customPath': custom_path,
                    'preferExternal': prefer_external,
                }

        target = self._storage_path()
        target.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        fd, temporary = tempfile.mkstemp(dir=target.parent, prefix='.external-player-')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as handle:
                json.dump(values, handle)
            os.replace(temporary, target)
        finally:
            Path(temporary).unlink(missing_ok=True)
        return self.snapshot(client_local=True, is_android=is_android)


external_player = ExternalPlayerSettings()
