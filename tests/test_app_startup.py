import asyncio
import json
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock
import httpx
import pytest
from fastapi import FastAPI
from animelab.config import settings
from animelab.database import create_database_engine
from animelab.migrations import migrate
from animelab.services import app_preferences
from animelab.services.app_updates import AppUpdates, normalize_feed, version_key, current_version, MAX_FEED_BYTES


@pytest.fixture
def installation(tmp_path, monkeypatch):
    path = tmp_path / 'library.sqlite3'
    engine = create_database_engine('sqlite:///' + str(path))
    migrate(engine)
    migrate(engine)
    engine.dispose()
    monkeypatch.setattr(settings, 'DATABASE_PATH', str(path))
    monkeypatch.setattr(settings, 'DOWNLOAD_DIR', str(tmp_path / 'downloads'))
    from animelab.services.download_manager import download_manager
    monkeypatch.setattr(download_manager, 'download_dir', settings.DOWNLOAD_DIR)
    monkeypatch.setattr(download_manager, 'tasks', {})
    monkeypatch.delenv('ANIMELAB_SHARED_WORKER', raising=False)
    return path


def release(version='v0.1.7-beta.2', **changes):
    return {'tag_name': version, 'html_url': 'https://github.com/loeuf237/animelab/releases/tag/' + version,
            'body': '# New release\n- Changes', 'assets': [
                {'name': 'AnimeLab-Android-arm64.apk', 'browser_download_url': 'https://github.com/loeuf237/animelab/releases/download/' + version + '/AnimeLab.apk', 'size': 120}], **changes}


def mock_feed(monkeypatch, response):
    original = httpx.AsyncClient
    requests = []
    def handler(request):
        requests.append(request)
        if isinstance(response, Exception):
            raise response
        return response
    monkeypatch.setattr('animelab.services.app_updates.httpx.AsyncClient',
                        lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs))
    return requests


def test_release_order_and_stable_channel_ignore_beta_even_when_not_prerelease():
    assert version_key('v0.1.7-beta.9') < version_key('0.1.7-beta.10') < version_key('0.1.7-rc.1') < version_key('0.1.7')
    assert version_key('0.1.10') > version_key('0.1.9')
    rows = [release(), release('v0.1.6'), release('v9.0.0', draft=True)]
    assert normalize_feed(rows, 'stable')['version'] == 'v0.1.6'
    assert normalize_feed(rows, 'beta')['version'] == 'v0.1.7-beta.2'


def test_custom_feed_and_untrusted_links():
    data = {'releases': [{'version': '1.2.0', 'notes': '<script>untrusted</script>',
        'url': 'https://downloads.example/releases/1.2.0', 'assets': [
            {'name': 'Linux-x64.tar.gz', 'url': 'https://downloads.example/Linux-x64.tar.gz'},
            {'name': 'evil.apk', 'url': 'javascript:alert(1)'},
            {'name': 'private.apk', 'url': 'https://user:password@example.com/a.apk'}]}]}
    result = normalize_feed(data, 'stable')
    assert len(result['assets']) == 1
    assert result['notes'] == '<script>untrusted</script>'  # UI renders it as text.
    assert normalize_feed([release(assets=None)], 'beta')['assets'] == []
    assert normalize_feed([release(html_url='javascript:alert(1)')], 'beta') is None


@pytest.mark.asyncio
async def test_update_check_compares_beta_versions_and_coalesces_requests(monkeypatch):
    monkeypatch.setenv('ANIMELAB_RELEASE_VERSION', '0.1.7-beta.1')
    calls = mock_feed(monkeypatch, httpx.Response(200, json=[release()]))
    service = AppUpdates()
    results = await asyncio.gather(*(service.check('beta') for _ in range(5)))
    assert all(result['status'] == 'available' for result in results)
    assert len(calls) == 1
    assert 'authorization' not in calls[0].headers
    await service.check('stable')
    assert len(calls) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize('response', [httpx.Response(403, text='private upstream details'),
    httpx.Response(302, headers={'Location': 'http://127.0.0.1/internal'}),
    httpx.Response(200, content=b' ' * (MAX_FEED_BYTES + 1)), httpx.Response(200, json={'wrong': 'schema'}),
    httpx.ConnectTimeout('no connection')])
async def test_feed_failures_are_bounded_nonblocking_and_cached(monkeypatch, response):
    calls = mock_feed(monkeypatch, response)
    service = AppUpdates()
    result = await service.check()
    assert result['status'] == 'offline' and result['release'] is None
    assert 'private' not in json.dumps(result)
    await service.check()
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_local_update_feed_is_rejected_before_any_request(monkeypatch):
    monkeypatch.setenv('ANIMELAB_UPDATE_FEED_URL', 'https://127.0.0.1/private')
    calls = mock_feed(monkeypatch, httpx.Response(200, json=[]))
    assert (await AppUpdates().check())['status'] == 'offline'
    assert not calls


@pytest.mark.asyncio
async def test_manual_refresh_is_throttled_and_offline_mode_makes_no_network_calls(monkeypatch):
    import time
    calls = mock_feed(monkeypatch, httpx.Response(200, json=[release()]))
    service = AppUpdates()
    await service.check()
    await service.check(refresh=True)
    assert len(calls) == 1
    key = next(iter(service.cache))
    expiry, result, _ = service.cache[key]
    service.cache[key] = (expiry, result, time.monotonic() - 61)
    await service.check(refresh=True)
    assert len(calls) == 2
    monkeypatch.setenv('ANIMELAB_UPDATE_CHECK_DISABLED', 'true')
    assert (await AppUpdates().check())['status'] == 'offline'
    assert len(calls) == 2


def test_packaged_version_uses_beta_tag_not_plain_base_version(monkeypatch, tmp_path):
    monkeypatch.delenv('ANIMELAB_RELEASE_VERSION', raising=False)
    monkeypatch.setattr(sys, 'frozen', True, raising=False)
    monkeypatch.setattr(sys, '_MEIPASS', str(tmp_path), raising=False)
    directory = tmp_path / 'release-metadata'; directory.mkdir()
    (directory / 'build-info.json').write_text(json.dumps({'release_tag': 'v0.1.6-beta.3'}))
    assert current_version() == '0.1.6-beta.3'


def app():
    from animelab.routers.startup import router
    result = FastAPI(); result.include_router(router)
    return result


@pytest.mark.asyncio
async def test_setup_preferences_persist_and_reject_arbitrary_configuration(installation):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app()), base_url='http://test',) as client:
        original = (await client.get('/api/app/startup')).json()
        assert original['preferences']['onboardingCompleted'] is False
        response = await client.patch('/api/app/preferences', json={'onboardingCompleted': True, 'theme': 'system', 'palette': 'ember'})
        assert response.status_code == 200
        assert app_preferences.load()['onboardingCompleted'] is True
        assert app_preferences.load()['checkUpdates'] is True
        for valid_palette in ('classic', 'amoled'):
            palette_resp = await client.patch('/api/app/preferences', json={'palette': valid_palette})
            assert palette_resp.status_code == 200
            assert app_preferences.load()['palette'] == valid_palette
        for changes in ({'palette': 'unknown'}, {'updateFeed': 'http://127.0.0.1'}, {'downloadDirectory': '/private'}):
            assert (await client.patch('/api/app/preferences', json=changes)).status_code == 422
        assert 'downloadDirectory' not in response.json()


@pytest.mark.asyncio
async def test_selected_directory_persists_without_moving_existing_files(installation, tmp_path, monkeypatch):
    existing = tmp_path / 'existing.mp4'; existing.write_bytes(b'personal video')
    new = tmp_path / 'new-folder'
    from animelab.services.download_manager import download_manager
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=('127.0.0.1', 123)), base_url='http://localhost') as client:
        response = await client.post('/api/app/directory', json={'path': str(new)})
        assert response.status_code == 200
        assert download_manager.download_dir == str(new)
        monkeypatch.setattr(settings, 'DOWNLOAD_DIR', 'old')
        app_preferences.restore_download_directory()
        assert settings.DOWNLOAD_DIR == str(new)
        assert not list(new.iterdir())
        assert existing.read_bytes() == b'personal video'


@pytest.mark.asyncio
async def test_remote_and_shared_clients_cannot_change_host_directory(installation, tmp_path, monkeypatch):
    for peer, shared in [('192.0.2.10', False), ('127.0.0.1', True)]:
        if shared: monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=(peer, 1)), base_url='http://test') as client:
            response = await client.post('/api/app/directory', json={'path': str(tmp_path / 'denied')})
            assert response.status_code == 403
    assert not (tmp_path / 'denied').exists()


def test_folder_picker_rejects_foreign_pages_and_handles_cancel(monkeypatch):
    from animelab.desktop.window import DirectoryPicker
    picker = DirectoryPicker('http://127.0.0.1:8080/spa/')
    chooser = SimpleNamespace(FOLDER_DIALOG=10)
    monkeypatch.setitem(sys.modules, 'webview', chooser)
    picker._window = SimpleNamespace(get_current_url=lambda: 'https://example.com/', create_file_dialog=lambda *_: ['/private'])
    with pytest.raises(PermissionError): picker.choose_download_directory()
    picker._window.get_current_url = lambda: 'http://127.0.0.1:8080/spa/settings'
    picker._window.create_file_dialog = lambda *_: None
    assert picker.choose_download_directory() is None


def test_desktop_bridge_native_actions_require_local_origin():
    from animelab.desktop.window import DesktopBridge
    bridge = DesktopBridge('http://127.0.0.1:8080/spa/')
    titles = []
    bridge._window = SimpleNamespace(
        get_current_url=lambda: 'https://untrusted.example/phishing',
        set_title=titles.append,
    )
    for fn in (
        bridge.platform_info,
        lambda: bridge.set_title('Malicious'),
        lambda: bridge.set_theme('light'),
    ):
        with pytest.raises(PermissionError):
            fn()
    bridge._window.get_current_url = lambda: 'http://127.0.0.1:8080/spa/home'
    info = bridge.platform_info()
    assert info['runtime'] == 'desktop'
    assert info['os'] in ('windows', 'macos', 'linux')
    assert bridge.set_title('AnimeLab   —   Bibliothèque\n\n') == 'AnimeLab — Bibliothèque'
    assert titles == ['AnimeLab — Bibliothèque']
    assert bridge.set_theme('dark') is True
    assert bridge.set_theme('light') is True


def test_new_launcher_directory_overrides_a_previous_setup_choice(installation, tmp_path, monkeypatch):
    app_preferences.save({'downloadDirectory': str(tmp_path / 'wizard'), 'downloadDirectoryOrigin': '/old-launcher-choice'})
    monkeypatch.setenv('ANIMELAB_DOWNLOAD_DIR', '/old-launcher-choice')
    app_preferences.restore_download_directory()
    assert settings.DOWNLOAD_DIR == str(tmp_path / 'wizard')
    monkeypatch.setenv('ANIMELAB_DOWNLOAD_DIR', str(tmp_path / 'new-launcher-choice'))
    monkeypatch.setattr(settings, 'DOWNLOAD_DIR', str(tmp_path / 'new-launcher-choice'))
    app_preferences.restore_download_directory()
    assert settings.DOWNLOAD_DIR == str(tmp_path / 'new-launcher-choice')


@pytest.mark.asyncio
async def test_remote_preferences_do_not_disclose_host_paths(installation):
    app_preferences.save({'downloadDirectory': '/home/private-owner/secret-folder', 'downloadDirectoryOrigin': '/private'})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=('192.0.2.10', 1)), base_url='http://test') as client:
        response = await client.get('/api/app/startup')
        assert response.status_code == 200
        assert 'private-owner' not in response.text
        assert 'downloadDirectoryOrigin' not in response.text


@pytest.mark.asyncio
async def test_active_media_processing_prevents_directory_changes(installation, tmp_path, monkeypatch):
    from animelab.services.download_manager import download_manager
    monkeypatch.setattr(download_manager, 'tasks', {'episode': SimpleNamespace(status=SimpleNamespace(value='MUXING'))})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=('127.0.0.1', 1)), base_url='http://test') as client:
        assert (await client.post('/api/app/directory', json={'path': str(tmp_path / 'new')})).status_code == 409
    assert not (tmp_path / 'new').exists()


@pytest.mark.asyncio
async def test_android_prefixed_release_tags_and_compact_github_feed_size(monkeypatch):
    assert version_key('android-v0.1.6-beta.5') == version_key('v0.1.6-beta.5')
    assert version_key('android-v0.1.7-beta.1') > version_key('v0.1.6-beta.5')
    monkeypatch.setenv('ANIMELAB_RELEASE_VERSION', '0.1.6-beta.5')
    calls = mock_feed(monkeypatch, httpx.Response(200, json=[release('android-v0.1.7-beta.1')]))
    result = await AppUpdates().check('beta')
    assert result['status'] == 'available'
    assert result['release']['version'] == 'android-v0.1.7-beta.1'
    assert 'per_page=10' in str(calls[0].url)


@pytest.mark.asyncio
async def test_in_app_release_download_checksum_verification_and_install(installation, tmp_path, monkeypatch):
    import hashlib
    import io
    import tarfile
    from animelab import platform_events
    from animelab.services.app_updates import app_updates

    monkeypatch.setattr(settings, 'CACHE_DIR', str(tmp_path / 'cache'))
    monkeypatch.setenv('ANIMELAB_RELEASE_VERSION', '0.1.7-beta.1')
    monkeypatch.setattr('animelab.services.app_updates.is_safe_url_async', AsyncMock(return_value=True))

    tar_buf = io.BytesIO()
    with tarfile.open(fileobj=tar_buf, mode='w:gz') as tf:
        info = tarfile.TarInfo('AnimeLab/AnimeLab')
        payload = b'#!/bin/sh\necho AnimeLab\n'
        info.size = len(payload)
        info.mode = 0o755
        tf.addfile(info, io.BytesIO(payload))
    tar_bytes = tar_buf.getvalue()
    tar_sha = hashlib.sha256(tar_bytes).hexdigest()
    apk_bytes = b'PK\x03\x04fake-signed-animelab-apk'
    apk_sha = hashlib.sha256(apk_bytes).hexdigest()
    sums_text = f'{tar_sha}  AnimeLab-v0.2.0-Linux-x64.tar.gz\n{apk_sha}  AnimeLab-v0.2.0-Android-arm64.apk\n'

    feed_payload = [
        {
            'tag_name': 'v0.2.0',
            'html_url': 'https://github.com/loeuf237/animelab/releases/tag/v0.2.0',
            'body': '# AnimeLab v0.2.0\n- In-app update installer',
            'assets': [
                {
                    'name': 'AnimeLab-v0.2.0-Linux-x64.tar.gz',
                    'browser_download_url': 'https://github.com/loeuf237/animelab/releases/download/v0.2.0/AnimeLab-v0.2.0-Linux-x64.tar.gz',
                    'size': len(tar_bytes),
                },
                {
                    'name': 'AnimeLab-v0.2.0-Android-arm64.apk',
                    'browser_download_url': 'https://github.com/loeuf237/animelab/releases/download/v0.2.0/AnimeLab-v0.2.0-Android-arm64.apk',
                    'size': len(apk_bytes),
                },
                {
                    'name': 'SHA256SUMS.txt',
                    'browser_download_url': 'https://github.com/loeuf237/animelab/releases/download/v0.2.0/SHA256SUMS.txt',
                    'size': len(sums_text),
                },
            ],
        }
    ]

    original_client = httpx.AsyncClient

    def handler(request: httpx.Request):
        url_str = str(request.url)
        if 'api.github.com' in url_str:
            return httpx.Response(200, json=feed_payload)
        if url_str.endswith('AnimeLab-v0.2.0-Linux-x64.tar.gz'):
            return httpx.Response(200, content=tar_bytes, headers={'Content-Length': str(len(tar_bytes))})
        if url_str.endswith('AnimeLab-v0.2.0-Android-arm64.apk'):
            return httpx.Response(200, content=apk_bytes, headers={'Content-Length': str(len(apk_bytes))})
        if url_str.endswith('SHA256SUMS.txt'):
            return httpx.Response(200, text=sums_text)
        return httpx.Response(404)

    monkeypatch.setattr(
        'animelab.services.app_updates.httpx.AsyncClient',
        lambda **kwargs: original_client(**({'transport': httpx.MockTransport(handler)} | kwargs)),
    )
    app_updates.cache.clear()
    app_updates._install_task = None

    # 1. Remote client cannot trigger installation
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=('192.0.2.10', 1)), base_url='http://test') as remote:
        denied = await remote.post('/api/app/updates/install', json={})
        assert denied.status_code == 403

    # 2. Local client installs desktop archive and verifies extracted executable
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app(), client=('127.0.0.1', 1)), base_url='http://localhost') as local:
        bad_url = await local.post('/api/app/updates/install', json={'url': 'https://evil.example/payload.tar.gz'})
        assert bad_url.status_code == 400

        res = await local.post(
            '/api/app/updates/install',
            json={'url': 'https://github.com/loeuf237/animelab/releases/download/v0.2.0/AnimeLab-v0.2.0-Linux-x64.tar.gz'},
        )
        assert res.status_code == 200
        status = res.json()
        assert status['state'] == 'ready'
        assert status['percent'] == 100
        assert status['restartRequired'] is True
        assert status['executablePath'].endswith('AnimeLab')

        # 3. Android APK install invokes native PackageInstaller hook
        installed_apks = []
        monkeypatch.setattr(
            platform_events,
            'app_update_install_handler',
            lambda path: (installed_apks.append(path), {'state': 'waiting_user'})[1],
        )
        apk_res = await local.post(
            '/api/app/updates/install',
            json={'url': 'https://github.com/loeuf237/animelab/releases/download/v0.2.0/AnimeLab-v0.2.0-Android-arm64.apk'},
        )
        assert apk_res.status_code == 200
        apk_status = apk_res.json()
        assert apk_status['state'] == 'waiting_user'
        assert len(installed_apks) == 1
        assert installed_apks[0].endswith('AnimeLab-v0.2.0-Android-arm64.apk')
