import asyncio
import io
import json
from pathlib import Path
import stat
import threading
import zipfile

import httpx
import pytest

import test_output_profiles_p6_p7 as reference
from animelab.database import init_db, sqlite_connection
from animelab.models.download_task import DownloadStatus, DownloadTask
from animelab.services.download_subtitles import DownloadSubtitles
from animelab.services.output_profiles import snapshot
from animelab.services.subtitle_imports import unpack, parse_text
from animelab.services.subtitle_provider import OpenSubtitlesProvider, ProviderError, SubtitleQuery, match_criteria
from animelab.services.subtitle_vault import SubtitleVault

media_case = reference.output_case


@pytest.fixture
def output_case(media_case):
    media_case[1].status = DownloadStatus.COMPLETED
    return media_case

SRT = '1\n00:00:00,200 --> 00:00:01,400\nÉquipage à bâbord !\n'.encode()
KEY = 'private-application-key'
PASS = 'private-password'


def make_provider(handler, vault=None):
    provider = OpenSubtitlesProvider(vault, lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler), follow_redirects=False))
    provider.request_interval = 0
    provider.credentials = dict(apiKey=KEY, username='', password='')
    return provider


def api_result(episode=2):
    return {'data': [{'id': '42', 'attributes': {
        'language': 'fr', 'release': 'One Piece WEB 1080p', 'fps': 23.976,
        'feature_details': {'title': 'Episode', 'parent_title': 'One Piece', 'parent_imdb_id': 100,
                            'season_number': 1, 'episode_number': episode},
        'files': [{'file_id': 123, 'file_name': f'One.Piece.S01E{episode:02}.srt'}]}}], 'page': 1, 'total_pages': 1}


def zip_bytes(rows):
    stream = io.BytesIO()
    with zipfile.ZipFile(stream, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, content in rows:
            archive.writestr(name, content)
    return stream.getvalue()


@pytest.mark.asyncio
async def test_provider_login_vip_cdn_headers_and_quota():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('/login'):
            assert json.loads(request.content)['password'] == PASS
            return httpx.Response(200, json={'token': 'private-bearer', 'base_url': 'vip-api.opensubtitles.com', 'user': {'allowed_downloads': 100}})
        if request.url.path.endswith('/subtitles'):
            assert request.url.host == 'vip-api.opensubtitles.com'
            assert request.headers['Api-Key'] == KEY and request.headers['Authorization'] == 'Bearer private-bearer'
            assert request.headers['User-Agent'].startswith('AnimeLab v')
            return httpx.Response(200, json=api_result())
        if request.url.path == '/api/v1/download':
            return httpx.Response(200, json={'link': 'https://www.opensubtitles.com/download/signed/file', 'file_name': 'episode.srt', 'remaining': 7})
        assert request.url.host == 'www.opensubtitles.com'
        assert 'api-key' not in request.headers and 'authorization' not in request.headers and 'cookie' not in request.headers
        return httpx.Response(200, content=SRT)
    provider = make_provider(handler)
    await provider.configure(KEY, 'tester', PASS)
    await provider.search(SubtitleQuery(query='one piece', imdbId='tt000100', season=1, episode=2))
    assert await provider.download(123) == (SRT, 'episode.srt')
    assert provider.status()['quota']['remaining'] == 7
    assert not any(secret in json.dumps(provider.status()) for secret in (KEY, PASS, 'private-bearer'))
    assert len(requests) == 4


@pytest.mark.asyncio
async def test_invalid_login_not_repeated_automatically():
    requests = []
    def reject(request):
        requests.append(request)
        return httpx.Response(401)
    provider = make_provider(reject)
    with pytest.raises(ProviderError, match='Session'):
        await provider.configure(KEY, 'bad', PASS)
    with pytest.raises(ProviderError, match='Reconnectez'):
        await provider.search(SubtitleQuery(query='one piece'))
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_expired_token_refreshed_once():
    requests = []
    def handler(request):
        requests.append(request)
        if request.url.path.endswith('login'):
            return httpx.Response(200, json={'token': 'fresh', 'base_url': 'api.opensubtitles.com'})
        return httpx.Response(401) if request.headers.get('authorization') == 'Bearer expired' else httpx.Response(200, json=api_result())
    provider = make_provider(handler)
    provider.credentials.update(username='tester', password=PASS)
    provider.token = 'expired'
    await provider.search(SubtitleQuery(query='one piece'))
    assert len(requests) == 3 and provider.token == 'fresh'


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(403, 'provider_quota_or_access'), (406, 'provider_quota_or_access'),
                                        (429, 'provider_rate_limit'), (503, 'provider_unavailable')])
async def test_provider_failures_are_actionable_and_do_not_loop(status, code):
    requests = []
    def fail(request):
        requests.append(request)
        return httpx.Response(status, headers={'Retry-After': '120'})
    provider = make_provider(fail)
    with pytest.raises(ProviderError) as failure:
        await provider.search(SubtitleQuery(query='test'))
    assert failure.value.code == code and KEY not in str(failure.value)
    if status == 429:
        assert failure.value.retry_after == 120
        with pytest.raises(ProviderError):
            await provider.search(SubtitleQuery(query='test'))
        assert len(requests) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('url', ['http://dl.opensubtitles.com/download/test', 'https://attacker.example/download/test',
                                  'https://www.opensubtitles.com@127.0.0.1/download/test', 'https://dl.opensubtitles.com:444/download/test'])
async def test_provider_rejects_foreign_or_private_destinations(url):
    requests = []
    def handler(request):
        requests.append(request)
        return httpx.Response(200, json={'link': url})
    provider = make_provider(handler)
    with pytest.raises(ProviderError, match='Destination'):
        await provider.download(123)
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_file_redirect_checked_and_expired_link_requires_explicit_retry():
    downloads = []
    expired = True
    def handler(request):
        if request.url.path == '/api/v1/download':
            downloads.append(request)
            return httpx.Response(200, json={'link': 'https://dl.opensubtitles.com/download/signed', 'file_name': 'test.srt', 'remaining': 5-len(downloads)})
        return httpx.Response(410) if expired else httpx.Response(200, content=SRT)
    provider = make_provider(handler)
    with pytest.raises(ProviderError) as error:
        await provider.download(1)
    assert error.value.code == 'provider_link_expired' and len(downloads) == 1
    expired = False
    assert (await provider.download(1))[0] == SRT and len(downloads) == 2
    def redirect(request):
        if request.url.path == '/api/v1/download':
            return handler(request)
        return httpx.Response(302, headers={'Location': 'https://127.0.0.1/download/private'})
    provider.client_factory = lambda: httpx.AsyncClient(transport=httpx.MockTransport(redirect))
    with pytest.raises(ProviderError, match='Destination'):
        await provider.download(1)


def test_query_identifiers_numbering_and_evidence():
    query = SubtitleQuery(query='wrong title ignored', imdbId='tt000100', tmdbId=123, season=1, episode=2)
    params = query.parameters()
    assert params['parent_imdb_id'] == '100' and params['parent_tmdb_id'] == '123' and 'query' not in params
    checks, warnings = match_criteria(query, {'parent_imdb_id': 100, 'season_number': 1, 'episode_number': 3})
    assert any(check['state'] == 'mismatch' for check in checks) and warnings
    absolute = SubtitleQuery(query='one piece', absoluteEpisode=1010)
    assert absolute.parameters()['episode_number'] == '1010'
    assert match_criteria(absolute, {})[1]
    with pytest.raises(ValueError):
        SubtitleQuery(query='x', absoluteEpisode=2, season=1)
    with pytest.raises(ValueError):
        SubtitleQuery(imdbId='tt100', idType='episode', episode=2)


@pytest.mark.parametrize('name', ['../outside.srt', '/outside.srt', 'C:\\outside.srt', 'folder/../../outside.srt'])
def test_archive_paths_never_escape(name):
    with pytest.raises(ProviderError):
        unpack(zip_bytes([(name, SRT)]), 'test.zip')


def test_archive_symlinks_size_member_count_encoding_and_preview():
    link = zipfile.ZipInfo('linked.srt')
    link.create_system = 3
    link.external_attr = (stat.S_IFLNK | 0o777) << 16
    with pytest.raises(ProviderError):
        unpack(zip_bytes([(link, b'outside')]), 'test.zip')
    with pytest.raises(ProviderError):
        unpack(zip_bytes([(str(index)+'.srt', SRT) for index in range(101)]), 'test.zip')
    with pytest.raises(ProviderError):
        unpack(zip_bytes([('bomb.srt', b'0' * (11 * 1024 * 1024))]), 'test.zip')
    cp = SRT.decode().encode('cp1252')
    with pytest.raises(ProviderError):
        parse_text(cp, 'episode.srt')
    assert 'Équipage' in parse_text(cp, 'episode.srt', 'windows-1252')['preview']
    assert parse_text(SRT.decode().encode('utf-16'), 'episode.srt')['content'] == SRT
    with pytest.raises(ProviderError):
        parse_text(b'<html>challenge</html>', 'episode.srt')


def test_vault_external_key_encryption_and_account_scope(tmp_path):
    from cryptography.fernet import Fernet
    data = tmp_path / 'account'
    data.mkdir()
    db = data / 'db.sqlite3'
    init_db(db)
    key = tmp_path / 'external.key'
    key.write_bytes(Fernet.generate_key())
    key.chmod(0o600)
    vault = SubtitleVault(db, data / 'downloads', data / 'cache', str(key))
    assert vault.available()
    credentials = dict(apiKey=KEY, username='tester', password=PASS)
    vault.save(credentials)
    with sqlite_connection(db) as conn:
        encrypted = conn.execute('SELECT payload FROM subtitle_provider_secret').fetchone()[0]
    assert KEY not in encrypted and PASS not in encrypted
    assert vault.load() == credentials
    assert not SubtitleVault(db, data / 'downloads', data / 'cache', str(db)).available()
    other = data / 'other.sqlite3'
    init_db(other)
    with sqlite_connection(other) as conn:
        conn.execute('INSERT INTO subtitle_provider_secret VALUES(?,?)', ('opensubtitles', encrypted))
    with pytest.raises(ProviderError):
        SubtitleVault(other, data / 'downloads', data / 'cache', str(key)).load()
    key.write_bytes(Fernet.generate_key())
    with pytest.raises(ProviderError):
        vault.load()
    vault.clear()
    assert vault.load() is None


@pytest.mark.asyncio
async def test_archive_selection_confirmation_persistence_and_actual_mkv(output_case):
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    service = DownloadSubtitles(manager, make_provider(lambda req: httpx.Response(200, json={})))
    imported = await service.upload(task.id, zip_bytes([('One.Piece.S01E01.srt', SRT), ('One.Piece.S01E02.srt', SRT.replace(b'bord', b'bord encore'))]), 'season.zip')
    assert len(imported['entries']) == 2 and 'path' not in json.dumps(imported)
    second = imported['entries'][1]
    assert second['numbering']['episode'] == 2
    with pytest.raises(ProviderError, match='Confirmez'):
        await service.attach(task.id, imported['importId'], second['id'], 'fr', 'Import français', False)
    added = await service.attach(task.id, imported['importId'], second['id'], 'fr', 'Import français', True)
    assert (await service.attach(task.id, imported['importId'], second['id'], 'fr', 'Duplicate', True))['duplicate']
    # A new service instance can read the task's persisted metadata and files.
    other = DownloadSubtitles(manager, service.provider)
    assert other.package(task, imported['importId'])['entries'][1]['preview']
    await manager.reprocess_output(task.id, {'mode': 'MKV_SOFT', 'selections': [
        {'trackId': 'embedded:audio:1', 'default': True}, {'trackId': added['trackId'], 'default': True, 'offsetSeconds': .25}]})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    streams = reference.probe(task.savePath)['streams']
    subs = [stream for stream in streams if stream['codec_type'] == 'subtitle']
    assert len(subs) == 1 and subs[0]['tags']['title'] == 'Import français' and subs[0]['tags']['language'] == 'fra'
    assert not requests


@pytest.mark.asyncio
async def test_new_import_invalidates_old_receipt_and_hardsub_uses_local_text(output_case):
    manager, task, files, requests = output_case
    task.status = DownloadStatus.PENDING
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    old = task.savePath
    manager.tasks[task.id] = task
    service = DownloadSubtitles(manager, make_provider(lambda req: httpx.Response(200, json={})))
    imported = await service.upload(task.id, SRT, 'new.srt')
    track = await service.attach(task.id, imported['importId'], imported['entries'][0]['id'], 'fr', 'New text', True)
    assert not manager.media_pipeline.output_processor.recover(task)
    await manager.reprocess_output(task.id, {'mode': 'MP4_HARD', 'burnTrackId': track['trackId'], 'selections': [
        {'trackId': 'embedded:audio:1'}, {'trackId': track['trackId']}]})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert Path(old).is_file() and len(requests) == 1
    assert [stream['codec_type'] for stream in reference.probe(task.savePath)['streams']] == ['video', 'audio']


@pytest.mark.asyncio
async def test_provider_search_preview_cache_episode_mismatch_and_isolation(output_case):
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    calls = []
    def handler(request):
        calls.append(request)
        if request.url.path.endswith('/subtitles'):
            return httpx.Response(200, json=api_result(episode=3))
        if request.url.path.endswith('/download'):
            return httpx.Response(200, json={'link': 'https://dl.opensubtitles.com/download/abc', 'file_name': 'One.Piece.S01E03.srt', 'remaining': 3})
        return httpx.Response(200, content=SRT)
    service = DownloadSubtitles(manager, make_provider(handler))
    task.episodeNumber = 2
    results = await service.search(task.id, SubtitleQuery(imdbId='tt100', season=1, episode=2))
    result = results['results'][0]
    assert result['warnings'] and 'fileId' not in result and 'url' not in result
    package = await service.provider_preview(task.id, result['id'])
    assert package['entries'][0]['numbering']['episode'] == 3
    assert (await service.provider_preview(task.id, result['id']))['importId'] == package['importId']
    assert len(calls) == 3
    another = DownloadTask(savePath=task.savePath, status=DownloadStatus.COMPLETED)
    manager.tasks[another.id] = another
    with pytest.raises(ProviderError):
        await service.provider_preview(another.id, result['id'])
    with pytest.raises(ProviderError):
        await service.attach(another.id, package['importId'], package['entries'][0]['id'], 'fr', 'Cross task', True)
    service.results[result['id']]['expires'] = 0
    with pytest.raises(ProviderError, match='expiré'):
        await service.provider_preview(task.id, result['id'])
    assert task.status != DownloadStatus.FAILED


@pytest.mark.asyncio
async def test_import_mutation_blocks_resume_and_forced_transfer_keeps_local_assets(output_case):
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    service = DownloadSubtitles(manager, make_provider(lambda req: httpx.Response(200, json={})))
    async with service.editing(task.id):
        assert not manager.resume_download(task.id)
        with pytest.raises(ValueError):
            manager.remove_task(task.id)
        with pytest.raises(ValueError):
            await manager.reprocess_output(task.id, {'mode': 'MKV_SOFT'})
    imported = await service.upload(task.id, SRT, 'test.srt')
    added = await service.attach(task.id, imported['importId'], imported['entries'][0]['id'], 'fr', '', True)
    path = Path(json.loads(task.mediaJson)['localSubtitleTracks'][0]['path'])
    manager.redownload_task(task.id, force=True)
    assert path.exists() and added['trackId'] in task.mediaJson


def test_subtitle_routes_bound_uploads_validate_and_hide_provider_secrets(output_case, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from animelab.api_errors import install_error_handlers, ErrorContractMiddleware
    from animelab.routers import subtitles as routes
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    provider = make_provider(lambda request: httpx.Response(401))
    service = DownloadSubtitles(manager, provider)
    monkeypatch.setattr(routes, 'service', lambda: service)
    app = FastAPI()
    app.include_router(routes.router)
    install_error_handlers(app)
    app.add_middleware(ErrorContractMiddleware)
    with TestClient(app) as client:
        root = f'/api/download/{task.id}/subtitles'
        upload = client.post(root+'/import?filename=test.srt', content=SRT)
        assert upload.status_code == 200
        data = upload.json()
        entry = data['entries'][0]
        assert 'path' not in entry
        response = client.post(root+'/attach', json=dict(importId=data['importId'], entryId=entry['id'],
                                                       language='fr', confirmedEpisode=True))
        assert response.status_code == 200
        assert client.post(root+'/import?filename=../bad.srt', content=SRT).status_code == 400
        assert client.post(root+'/import?filename=test.srt', content=b'0' * (10 * 1024 * 1024 + 1)).status_code == 413
        auth = client.put('/api/download/subtitle-provider', json={'apiKey': KEY, 'username': 'bad', 'password': PASS})
        assert auth.status_code == 424 and auth.json()['problem']['code'] == 'provider_auth'
        assert KEY not in auth.text and PASS not in auth.text
        invalid = client.put('/api/download/subtitle-provider', json={'apiKey': KEY, 'password': {'secret': PASS}})
        assert invalid.status_code == 422 and PASS not in invalid.text and KEY not in invalid.text
        assert client.post(root+'/provider-preview', json={'resultId': '123', 'url': 'https://attacker.example'}).status_code == 422
        missing = client.get('/api/download/missing/subtitles/context')
        assert missing.status_code == 404


def test_shared_body_limit_only_allows_larger_subtitle_uploads():
    from fastapi import FastAPI, Request
    from fastapi.testclient import TestClient
    from animelab.shared.gateway import BodyLimit, check_action
    app = FastAPI()
    @app.post('/{path:path}')
    async def receive(request: Request):
        return {'size': len(await request.body())}
    with TestClient(BodyLimit(app)) as client:
        data = b'0' * (2 * 1024 * 1024 + 1)
        assert client.post('/api/download/task/subtitles/import', content=data).status_code == 200
        assert client.post('/api/download/task/output', content=data).status_code == 413
        assert client.post('/api/download/task/subtitles/import', content=b'0' * (10 * 1024 * 1024 + 1)).status_code == 413
    with pytest.raises(Exception) as refusal:
        check_action({'admin': False, 'permissions': []}, '/api/download/task/subtitles/import', 'POST')
    assert refusal.value.status_code == 403


@pytest.mark.asyncio
async def test_no_key_file_means_memory_only_and_remember_is_refused(tmp_path):
    data = tmp_path / 'account'
    data.mkdir()
    database = data / 'library.sqlite3'
    init_db(database)
    vault = SubtitleVault(database, data / 'downloads', data / 'cache', key_file='')
    calls = []
    def handler(request):
        calls.append(request)
        return httpx.Response(200, json={'data': []})
    provider = make_provider(handler, vault)
    with pytest.raises(ProviderError, match='clé de chiffrement externe'):
        await provider.configure(KEY, remember=True)
    assert calls == []
    await provider.configure(KEY)
    with sqlite_connection(database) as db:
        assert db.execute('SELECT COUNT(*) FROM subtitle_provider_secret').fetchone()[0] == 0
    assert OpenSubtitlesProvider(vault).status()['configured'] is False


@pytest.mark.asyncio
async def test_disk_import_cancel_keeps_mutation_lock_until_worker_finished(output_case, monkeypatch):
    from animelab.services import download_subtitles as module
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    service = DownloadSubtitles(manager, make_provider(lambda req: httpx.Response(200, json={})))
    started, release = threading.Event(), threading.Event()
    original = module.unpack
    def blocking_unpack(*args):
        started.set()
        assert release.wait(5)
        return original(*args)
    monkeypatch.setattr(module, 'unpack', blocking_unpack)
    job = asyncio.create_task(service.upload(task.id, SRT, 'episode.srt'))
    assert await asyncio.to_thread(started.wait, 3)
    job.cancel()
    await asyncio.sleep(.02)
    assert task.id in manager._subtitle_mutations and not manager.resume_download(task.id)
    release.set()
    with pytest.raises(asyncio.CancelledError):
        await job
    assert task.id not in manager._subtitle_mutations


def test_gzip_import_preserves_text_and_rejects_corrupt_archive():
    import gzip
    assert unpack(gzip.compress(SRT), 'test.srt.gz')[0]['content'] == SRT
    with pytest.raises(ProviderError):
        unpack(b'not zip', 'test.zip')
    with pytest.raises(ProviderError):
        unpack(b'not gzip', 'test.srt.gz')


@pytest.mark.asyncio
async def test_tampered_import_cannot_be_attached(output_case):
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    service = DownloadSubtitles(manager, make_provider(lambda req: httpx.Response(200, json={})))
    imported = await service.upload(task.id, SRT, 'test.srt')
    info = json.loads(task.mediaJson)
    Path(info['subtitleImports'][imported['importId']]['entries'][0]['path']).write_bytes(b'modified')
    with pytest.raises(ProviderError, match='modifié'):
        await service.attach(task.id, imported['importId'], imported['entries'][0]['id'], 'fr', '', True)
    assert not json.loads(task.mediaJson).get('localSubtitleTracks')


def test_html_challenge_with_timestamps_is_not_a_subtitle():
    with pytest.raises(ProviderError):
        parse_text(b'<html><body>1\n00:00:00,000 --> 00:00:01,000\nCheck browser</body></html>', 'challenge.srt')


@pytest.mark.asyncio
async def test_provider_filename_without_extension_infers_valid_text(output_case):
    manager, task, files, requests = output_case
    manager.tasks[task.id] = task
    def handler(request):
        if request.url.path.endswith('/subtitles'):
            return httpx.Response(200, json=api_result())
        if request.url.path.endswith('/download'):
            return httpx.Response(200, json={'link': 'https://dl.opensubtitles.com/download/signed', 'file_name': 'One.Piece.S01E02'})
        return httpx.Response(200, content=SRT)
    service = DownloadSubtitles(manager, make_provider(handler))
    result = await service.search(task.id, SubtitleQuery(query='one piece'))
    imported = await service.provider_preview(task.id, result['results'][0]['id'])
    assert imported['entries'][0]['name'].endswith('.srt')
