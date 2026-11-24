"""Tests for external video player configuration, safe Desktop launch, and Android intent/tickets."""
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import urllib.parse
import xml.etree.ElementTree as ET

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from animelab import config as app_config, platform_events
from animelab.android_security import AndroidSessionMiddleware
from animelab.api_errors import install_error_handlers
from animelab.routers import media
from animelab.security import is_safe_path
from animelab.services import external_player as ep_mod
from animelab.services.download_manager import download_manager
from animelab.services.extension_media import extension_media


def _make_fake_player(directory: Path, name: str = 'mpv') -> Path:
    path = directory / name
    path.write_text('#!/bin/sh\nexit 0\n', encoding='utf-8')
    path.chmod(0o755)
    return path


def _test_app() -> FastAPI:
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(media.router)
    return app


def test_executable_validation_rejects_unsafe_inputs_and_accepts_executable(tmp_path):
    exe = _make_fake_player(tmp_path, 'custom-mpv')
    assert ep_mod.validate_player_executable(str(exe)) == str(exe.resolve())

    non_exec = tmp_path / 'plain.txt'
    non_exec.write_text('not executable', encoding='utf-8')
    non_exec.chmod(0o644)
    if sys.platform != 'win32':
        with pytest.raises(ValueError):
            ep_mod.validate_player_executable(str(non_exec))

    batch = tmp_path / 'evil.bat'
    batch.write_text('echo pwn\n', encoding='utf-8')
    batch.chmod(0o755)
    if sys.platform == 'win32':
        with pytest.raises(ValueError):
            ep_mod.validate_player_executable(str(batch))

    for bad in ('', '   ', '-flag', 'mpv;id', 'mpv\nid', 'mpv\x00x', str(tmp_path / 'missing')):
        with pytest.raises(ValueError):
            ep_mod.validate_player_executable(bad)


def test_build_player_command_isolates_flags_and_handles_mpv_vlc_and_generic(tmp_path):
    mpv_exe = _make_fake_player(tmp_path, 'mpv')
    argv = ep_mod.build_player_command(
        str(mpv_exe),
        '/tmp/video.mp4',
        title='Solo\nLeveling\x07  — Ep 1',
        subtitles=['/tmp/sub.ass', '-injected-flag'],
    )
    assert argv[0] == str(mpv_exe.resolve())
    assert '--force-media-title=Solo Leveling — Ep 1' in argv
    assert '--sub-file=/tmp/sub.ass' in argv
    assert not any('-injected-flag' in item for item in argv)
    assert argv[-2:] == ['--', '/tmp/video.mp4']

    vlc_exe = _make_fake_player(tmp_path, 'vlc')
    vlc_argv = ep_mod.build_player_command(
        str(vlc_exe),
        'http://127.0.0.1:8080/api/media/stream/t1',
        title='Title',
        subtitles=['/tmp/one.srt', '/tmp/two.srt'],
    )
    assert '--meta-title=Title' in vlc_argv
    assert vlc_argv.count('--sub-file=/tmp/one.srt') == 1
    assert vlc_argv[-2:] == ['--', 'http://127.0.0.1:8080/api/media/stream/t1']

    generic_exe = _make_fake_player(tmp_path, 'celluloid')
    assert ep_mod.build_player_command(str(generic_exe), '/tmp/v.mp4') == [
        str(generic_exe.resolve()),
        '/tmp/v.mp4',
    ]

    with pytest.raises(ValueError):
        ep_mod.build_player_command(str(mpv_exe), '--eval=bad')


@pytest.mark.asyncio
async def test_desktop_settings_and_launch_local_and_proxied_streams(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, 'IS_ANDROID', False)
    monkeypatch.delenv('ANIMELAB_SHARED_WORKER', raising=False)
    monkeypatch.setattr(app_config.settings, 'DOWNLOAD_DIR', str(tmp_path / 'downloads'))
    monkeypatch.setattr(app_config.settings, 'CACHE_DIR', tmp_path / 'cache')
    monkeypatch.setattr('tempfile.gettempdir', lambda: str(tmp_path / 'isolated-temp'))
    monkeypatch.setattr(ep_mod, 'external_player', ep_mod.ExternalPlayerSettings(tmp_path / 'cache' / 'external-player.json'))
    monkeypatch.setattr(media, 'external_player', ep_mod.external_player)
    monkeypatch.setattr(ep_mod, 'detect_installed_players', lambda *, is_android=False: [])

    app = _test_app()
    fake_exe = _make_fake_player(tmp_path, 'mpv')

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('192.0.2.10', 1)), base_url='http://remote') as remote:
        snap = (await remote.get('/api/media/external-player/settings')).json()
        assert snap['available'] is False and snap['resolvedPath'] is None
        assert (await remote.post('/api/media/external-player/settings', json={'preset': 'none'})).status_code == 403
        assert (await remote.post('/api/media/external-player/launch', json={'taskId': 't1'})).status_code == 403

    dl_dir = tmp_path / 'downloads'
    dl_dir.mkdir(parents=True, exist_ok=True)
    ep_file = dl_dir / 'Show Ep 1.mp4'
    sub_file = dl_dir / 'Show Ep 1.ass'
    ep_file.write_bytes(b'video')
    sub_file.write_text('[Script Info]\n', encoding='utf-8')
    outside = tmp_path / 'secret.mp4'
    outside.write_bytes(b'secret')

    task_ok = SimpleNamespace(
        id='task-ok',
        animeName='Show',
        episodeNumber=1,
        fileName='Show Ep 1.mp4',
        savePath=str(ep_file),
        savePathSubtitle=json.dumps([str(sub_file)]),
        exportUrisJson='[]',
    )
    task_evil = SimpleNamespace(
        id='task-evil',
        animeName='Evil',
        episodeNumber=1,
        fileName='secret.mp4',
        savePath=str(outside),
        savePathSubtitle=None,
        exportUrisJson='[]',
    )
    monkeypatch.setattr(media.download_manager, 'get_task', lambda tid: task_ok if tid == 'task-ok' else task_evil if tid == 'task-evil' else None)
    assert is_safe_path(ep_file)
    assert not is_safe_path(outside)

    spawned: list[list[str]] = []
    monkeypatch.setattr(media, 'spawn_desktop_player', lambda argv: spawned.append(argv))

    async with httpx.AsyncClient(transport=httpx.ASGITransport(app, client=('127.0.0.1', 1)), base_url='http://127.0.0.1:8080') as client:
        # Unconfigured fails cleanly with 409 so client falls back to built-in player.
        unconfigured = await client.post('/api/media/external-player/launch', json={'taskId': 'task-ok'})
        assert unconfigured.status_code == 409

        # Configure custom mpv binary.
        saved = await client.post(
            '/api/media/external-player/settings',
            json={'preset': 'custom', 'customPath': str(fake_exe), 'preferExternal': True},
        )
        assert saved.status_code == 200
        assert saved.json()['configured'] is True
        assert saved.json()['preferExternal'] is True

        # Reject path traversal outside allowed download/temp directories.
        denied = await client.post('/api/media/external-player/launch', json={'taskId': 'task-evil'})
        assert denied.status_code == 403

        # Launch via local /api/media/stream/<id> path resolves to disk file + sidecar subtitles.
        local_launch = await client.post(
            '/api/media/external-player/launch',
            json={'streamUrl': '/api/media/stream/task-ok', 'title': 'Show - Épisode 1'},
        )
        assert local_launch.status_code == 200
        assert local_launch.json()['mode'] == 'desktop_process'
        assert local_launch.json()['targetKind'] == 'file'
        assert spawned[-1][0] == str(fake_exe.resolve())
        assert f'--sub-file={sub_file.resolve()}' in spawned[-1]
        assert spawned[-1][-2:] == ['--', str(ep_file.resolve())]

        # Launch proxied local stream URL prepends loopback origin.
        stream_launch = await client.post(
            '/api/media/external-player/launch',
            json={
                'streamUrl': '/api/media/stream-proxy?url=https%3A%2F%2Fcdn.example%2Fep.mp4&server=vidzy',
                'title': 'Show - Épisode 2',
                'subtitles': [{'src': '/api/media/subtitle-proxy?url=https%3A%2F%2Fcdn.example%2Fsub.vtt'}],
            },
        )
        assert stream_launch.status_code == 200
        assert stream_launch.json()['targetKind'] == 'stream'
        assert spawned[-1][-1] == 'http://127.0.0.1:8080/api/media/stream-proxy?url=https%3A%2F%2Fcdn.example%2Fep.mp4&server=vidzy'
        assert '--sub-file=http://127.0.0.1:8080/api/media/subtitle-proxy?url=https%3A%2F%2Fcdn.example%2Fsub.vtt' in spawned[-1]

        # Reject dangerous file:// URL.
        bad_url = await client.post('/api/media/external-player/launch', json={'streamUrl': 'file:///etc/passwd'})
        assert bad_url.status_code == 400


@pytest.mark.asyncio
async def test_android_intent_uses_exported_uri_fileprovider_and_scoped_tickets(monkeypatch, tmp_path):
    monkeypatch.setattr(app_config, 'IS_ANDROID', True)
    monkeypatch.delenv('ANIMELAB_SHARED_WORKER', raising=False)
    monkeypatch.setattr(app_config.settings, 'DOWNLOAD_DIR', str(tmp_path / 'downloads'))
    monkeypatch.setattr(ep_mod, 'external_player', ep_mod.ExternalPlayerSettings(tmp_path / 'external-player.json'))
    monkeypatch.setattr(ep_mod, 'external_media_tickets', ep_mod.ExternalMediaTickets())
    monkeypatch.setattr(media, 'external_media_tickets', ep_mod.external_media_tickets)
    monkeypatch.setattr(platform_events, 'exported_copy_exists_handler', lambda uri: uri.endswith('valid'))
    monkeypatch.setattr('animelab.services.extension_media.validate_media_url', lambda url: None)

    dl_dir = tmp_path / 'downloads'
    dl_dir.mkdir(parents=True, exist_ok=True)
    priv_file = dl_dir / 'Ep3.mkv'
    priv_file.write_bytes(b'mkv')

    exported_task = SimpleNamespace(
        id='android-exp',
        animeName='AndroidShow',
        episodeNumber=1,
        fileName='Ep1.mp4',
        savePath=str(priv_file),
        savePathSubtitle=None,
        exportUrisJson=json.dumps(['content://downloads/valid', 'content://downloads/sub.srt']),
    )
    private_only_task = SimpleNamespace(
        id='android-priv',
        animeName='AndroidShow',
        episodeNumber=3,
        fileName='Ep3.mkv',
        savePath=str(priv_file),
        savePathSubtitle=None,
        exportUrisJson=json.dumps(['content://downloads/missing']),
    )
    monkeypatch.setattr(
        media.download_manager,
        'get_task',
        lambda tid: exported_task if tid == 'android-exp' else private_only_task if tid == 'android-priv' else None,
    )

    res_token_url = extension_media.issue('https://cdn.example/master.m3u8', {'Referer': 'https://cdn.example'})
    app = _test_app()
    token = 's' * 64
    secured = AndroidSessionMiddleware(app, token)

    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(secured, client=('127.0.0.1', 1)),
        base_url='http://127.0.0.1:9001',
    ) as client:
        # Unauthenticated settings check still requires Android session.
        assert (await client.get('/api/media/external-player/settings')).status_code == 401

        headers = {'X-Animan-Session': token}
        # Invalid preset rejected on Android.
        assert (await client.post('/api/media/external-player/settings', headers=headers, json={'preset': 'vlc'})).status_code == 400
        saved = await client.post('/api/media/external-player/settings', headers=headers, json={'preset': 'system', 'preferExternal': True})
        assert saved.status_code == 200 and saved.json()['preferExternal'] is True

        # Exported copy prefers MediaStore content:// URI.
        exp_launch = await client.post('/api/media/external-player/launch', headers=headers, json={'taskId': 'android-exp'})
        assert exp_launch.status_code == 200
        exp_intent = exp_launch.json()['androidIntent']
        assert exp_intent['kind'] == 'uri'
        assert exp_intent['target'] == 'content://downloads/valid'
        assert exp_intent['subtitleUri'] == 'content://downloads/sub.srt'

        # Deleted MediaStore copy falls back to FileProvider target inside app files/downloads.
        priv_launch = await client.post('/api/media/external-player/launch', headers=headers, json={'taskId': 'android-priv'})
        assert priv_launch.status_code == 200
        priv_intent = priv_launch.json()['androidIntent']
        assert priv_intent['kind'] == 'file'
        assert priv_intent['mimeType'] == 'video/x-matroska'

        # Proxied extension HLS stream mints scoped read-only media_ticket without leaking X-Animan-Session.
        hls_launch = await client.post(
            '/api/media/external-player/launch',
            headers=headers,
            json={'streamUrl': res_token_url, 'isHls': True, 'title': 'Android HLS'},
        )
        assert hls_launch.status_code == 200
        hls_intent = hls_launch.json()['androidIntent']
        assert hls_intent['kind'] == 'url'
        assert hls_intent['mimeType'] == 'application/vnd.apple.mpegurl'
        parsed_intent_url = urllib.parse.urlsplit(hls_intent['target'])
        ticket = urllib.parse.parse_qs(parsed_intent_url.query)['media_ticket'][0]
        assert token not in hls_intent['target']

        # Playlist rewriting propagates media_ticket cleanly.
        rewritten = extension_media.playlist(
            '#EXTM3U\n#EXTINF:6,\nsegment-1.ts\n',
            extension_media.get(res_token_url.rsplit('/', 1)[-1]),
            'https://cdn.example/master.m3u8',
            query_suffix=f'?media_ticket={ticket}',
        )
        assert f'?media_ticket={ticket}' in rewritten

        # Scoped ticket CANNOT access non-scoped routes or POST or other task files.
        assert (await client.get(f'/api/media/external-player/settings?media_ticket={ticket}')).status_code == 401
        assert (await client.get(f'/api/media/stream/android-priv?media_ticket={ticket}')).status_code == 401
        assert (await client.post(f'{parsed_intent_url.path}?media_ticket={ticket}')).status_code == 401

        # Scoped stream-proxy ticket only authorizes GET/HEAD on the exact stream-proxy URL.
        proxy_launch = await client.post(
            '/api/media/external-player/launch',
            headers=headers,
            json={'streamUrl': '/api/media/stream-proxy?url=https%3A%2F%2Fcdn.example%2Fa.mp4'},
        )
        proxy_url = urllib.parse.urlsplit(proxy_launch.json()['androidIntent']['target'])
        proxy_ticket = urllib.parse.parse_qs(proxy_url.query)['media_ticket'][0]
        assert ep_mod.external_media_tickets.verify(
            proxy_ticket, '/api/media/stream-proxy', 'url=https%3A%2F%2Fcdn.example%2Fa.mp4'
        )
        assert not ep_mod.external_media_tickets.verify(
            proxy_ticket, '/api/media/stream-proxy', 'url=https%3A%2F%2Fevil.example%2Fb.mp4'
        )
        assert not ep_mod.external_media_tickets.verify(proxy_ticket, '/api/media/stream/android-priv', '')


def test_desktop_bridge_external_player_dialog_requires_local_origin(monkeypatch):
    from animelab.desktop.window import DesktopBridge

    bridge = DesktopBridge('http://127.0.0.1:8080/spa/')
    chooser = SimpleNamespace(OPEN_DIALOG=1)
    monkeypatch.setitem(sys.modules, 'webview', chooser)
    bridge._window = SimpleNamespace(
        get_current_url=lambda: 'https://evil.example/',
        create_file_dialog=lambda *_: ['/usr/bin/mpv'],
    )
    with pytest.raises(PermissionError):
        bridge.choose_external_player()

    bridge._window.get_current_url = lambda: 'http://127.0.0.1:8080/spa/settings'
    assert bridge.choose_external_player() == '/usr/bin/mpv'
    bridge._window.create_file_dialog = lambda *_: None
    assert bridge.choose_external_player() is None


def test_android_manifest_declares_non_exported_fileprovider():
    root = Path(__file__).resolve().parents[1]
    manifest = ET.parse(root / 'android' / 'app' / 'src' / 'main' / 'AndroidManifest.xml').getroot()
    ns = {'android': 'http://schemas.android.com/apk/res/android'}
    providers = manifest.findall('./application/provider')
    fp = [
        p
        for p in providers
        if p.attrib.get(f"{{{ns['android']}}}name") == 'androidx.core.content.FileProvider'
    ]
    assert len(fp) == 1
    assert fp[0].attrib.get(f"{{{ns['android']}}}authorities") == '${applicationId}.fileprovider'
    assert fp[0].attrib.get(f"{{{ns['android']}}}exported") == 'false'
    assert fp[0].attrib.get(f"{{{ns['android']}}}grantUriPermissions") == 'true'

    paths_xml = ET.parse(root / 'android' / 'app' / 'src' / 'main' / 'res' / 'xml' / 'file_paths.xml').getroot()
    entries = paths_xml.findall('./files-path')
    assert [(e.attrib.get('name'), e.attrib.get('path')) for e in entries] == [('downloads', 'downloads/')]
