"""End-to-end boundaries for P1-P5; all requests and media are local fixtures."""
import asyncio
import importlib
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from sqlalchemy import select
from sqlalchemy.orm import sessionmaker

from animelab import media_tools
from animelab.database import create_database_engine
from animelab.migrations import MIGRATIONS, migrate
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.models.media_state import tracks, attempts
from animelab.services.download_manager import DownloadManagerService
from animelab.services.extractors.ytdlp_fallback import YtDlpFallbackExtractor
from animelab.services.library_service import library_service
from animelab.services.media_contracts import ResolvedMedia, UnsupportedMedia
from animelab.services.media_execution import MediaInterrupted, run_process
from animelab.services.output_profiles import snapshot, require_available


@pytest.fixture
def private_library(tmp_path, monkeypatch):
    engine = create_database_engine('sqlite:///' + str(tmp_path / 'private.sqlite3'))
    migrate(engine)
    monkeypatch.setattr(importlib.import_module('animelab.services.library_service'), 'SessionLocal', sessionmaker(bind=engine))
    yield engine
    engine.dispose()


@pytest.mark.asyncio
async def test_direct_source_metadata_reaches_task_and_private_database(tmp_path, private_library, monkeypatch):
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path / 'downloads')
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    monkeypatch.setattr(manager, 'get_remote_file_size', AsyncMock(return_value=100))
    from animelab.services.extension_service import extension_service
    source = SimpleNamespace(base_url='https://source.example', get_episode_sources=AsyncMock(return_value=[{
        'url': 'https://cdn.example/episode.mp4', 'headers': {'Referer': 'https://source.example', 'Cookie': 'private'},
        'subtitleTracks': [{'url': '/fr.vtt', 'lang': 'fr', 'headers': {'Authorization': 'secret'}}],
        'audioTracks': [{'url': '/audio.m4a', 'lang': 'ja', 'role': 'alternate'}],
    }]))
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda source_id: source)
    info = await manager.get_or_resolve_episode_info('https://source.example/episode/1', source='custom')
    assert info is not None
    task = manager.start_download('Test', 1, 'https://source.example/episode/1', 'episode.mp4', source='custom', download_subtitles=True)
    assert json.loads(task.subtitlesJson)[0]['url'] == 'https://source.example/fr.vtt'
    assert json.loads(task.mediaJson)['audioTracks'][0]['lang'] == 'ja'
    assert task.requestHeaders['Cookie'] == 'private'
    reloaded = library_service.get_task_entity(task.id).to_task()
    assert reloaded.requestHeaders == {}
    assert 'secret' not in reloaded.subtitlesJson
    assert 'private' not in reloaded.mediaJson
    public = reloaded.to_dict()
    assert len(public['mediaTracks']) == 2
    assert all('headers' not in track for track in public['mediaTracks'])
    with private_library.connect() as connection:
        assert len(connection.execute(select(tracks).where(tracks.c.task_id == task.id)).all()) == 2


@pytest.mark.asyncio
async def test_ytdlp_preserves_manual_automatic_and_required_audio(monkeypatch):
    import yt_dlp
    info = {'extractor': 'fixture', 'requested_formats': [
        {'url': 'https://cdn.example/video.mp4', 'vcodec': 'h264', 'acodec': 'none', 'http_headers': {'Origin': 'https://source.example'}},
        {'url': 'https://cdn.example/audio.m4a', 'vcodec': 'none', 'acodec': 'aac', 'language': 'ja'}],
        'subtitles': {'fr': [{'url': 'https://cdn.example/fr.ass', 'ext': 'ass'}]},
        'automatic_captions': {'en': [{'url': 'https://cdn.example/en.vtt', 'ext': 'vtt'}]}}
    monkeypatch.setattr(yt_dlp.YoutubeDL, 'extract_info', lambda *args, **kwargs: info)
    result = await YtDlpFallbackExtractor().extract('https://source.example/embed')
    resolved = result.to_download_info()
    assert result.video_url.endswith('video.mp4')
    assert resolved['requirements'] == ['separate_audio']
    assert resolved['audioTracks'][0]['required']
    assert resolved['subtitles'][0]['automatic'] is False
    assert resolved['subtitles'][1]['automatic'] is True
    manager = DownloadManagerService()
    with pytest.raises(UnsupportedMedia):
        manager.transfer_worker.planner.select(ResolvedMedia.from_info(resolved))


def test_legacy_profile_snapshot_survives_restart_and_preferences(private_library, tmp_path, monkeypatch):
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path)
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    value = {'version': 1, 'mode': 'MKV_SOFT', 'keepOriginals': True}
    task = manager.start_download('Test', 1, 'https://cdn.example/1.mp4', 'episode.mp4', output_profile=value)
    value['mode'] = 'ORIGINAL'
    restored = library_service.get_task_entity(task.id).to_task()
    assert restored.to_dict()['outputProfile']['mode'] == 'MKV_SOFT'
    assert restored.downloadSubtitles is True
    assert json.loads(DownloadTask(downloadSubtitles=True).outputProfileJson)['mode'] == 'MKV_SOFT'
    assert json.loads(DownloadTask().outputProfileJson)['mode'] == 'ORIGINAL'


@pytest.mark.parametrize('value', [dict(mode='ORIGINAL', selections=[{'trackId': 'fr'}]), dict(mode='SIDECAR', burnTrackId='fr'), dict(mode='MKV_SOFT', selections=[{'trackId': 'fr'}, {'trackId': 'fr'}])])
def test_unavailable_profiles_cannot_be_silently_queued(value):
    with pytest.raises(ValueError):
        require_available(snapshot(value))


def test_upgrade_backup_and_finished_download_are_preserved(tmp_path):
    path = tmp_path / 'old.sqlite3'
    engine = create_database_engine('sqlite:///' + str(path))
    migrate(engine, MIGRATIONS[:9])
    with engine.begin() as connection:
        from animelab.models.download_task import DownloadTaskEntity
        connection.execute(DownloadTaskEntity.__table__.insert().values(id='old', animeName='Test', fileName='video.mp4', status='COMPLETED', subtitlesJson='[]', downloadSubtitles=True))
    migrate(engine)
    migrate(engine)
    with engine.connect() as connection:
        row = connection.exec_driver_sql("SELECT status,subtitlesJson,downloadSubtitles,outputProfileJson FROM download_tasks WHERE id='old'").one()
        assert row == ('COMPLETED', '[]', 1, '')
    assert list(tmp_path.glob('old.sqlite3.before-media-v10*.sqlite3'))
    engine.dispose()


@pytest.mark.asyncio
async def test_backend_persists_attempt_and_uses_existing_http_resume(private_library, monkeypatch, tmp_path):
    manager = DownloadManagerService()
    task = DownloadTask(savePath=str(tmp_path / 'video.mp4'))
    async def transfer(*args):
        task.downloadedBytes = 42
        task.paused = True
        task.status = DownloadStatus.PAUSED
    worker = AsyncMock(side_effect=transfer)
    monkeypatch.setattr(manager, '_download_single_file', worker)
    result = await manager.transfer_worker.planner.transfer(task, ResolvedMedia('https://cdn.example/video.mp4'))
    assert not result.complete and result.checkpoint['bytes'] == 42
    worker.assert_awaited_once()
    with private_library.connect() as connection:
        attempt = connection.execute(select(attempts)).mappings().one()
        assert attempt['backend'] == 'http-range' and attempt['status'] == 'interrupted'
    task.mediaJson = json.dumps({'transferAttempt': dict(id='old', backend='other', status='interrupted')})
    with pytest.raises(UnsupportedMedia, match='autre moteur'):
        await manager.transfer_worker.planner.transfer(task, ResolvedMedia('https://cdn.example/video.mp4'))


def test_process_progress_is_separate_from_network_and_paths_are_not_shell(tmp_path):
    script = tmp_path / 'épisode with spaces.py'
    script.write_text("print('out_time_us=1500000', flush=True)\nprint('progress=end', flush=True)\n")
    events = []
    result = run_process([sys.executable, str(script)], timeout=5, cancel=lambda: False, emit=events.append)
    assert result.returncode == 0
    assert events[-1].media_seconds == 1.5 and events[-1].bytes_received == 0


def test_process_timeout_and_cancellation_preserve_inputs(tmp_path):
    master = tmp_path / 'master.mp4'
    master.write_bytes(b'original')
    for interrupt in (False, True):
        stop = threading.Event()
        if interrupt:
            stop.set()
        with pytest.raises(MediaInterrupted if interrupt else subprocess.TimeoutExpired):
            run_process([sys.executable, '-c', 'import time; time.sleep(30)'],
                        timeout=.15, cancel=stop.is_set, emit=lambda event: None)
    assert master.read_bytes() == b'original'


@pytest.mark.skipif(sys.platform != 'linux', reason='Linux process group assertion')
def test_cancellation_terminates_child_process_group(tmp_path):
    import os
    import time
    pidfile = tmp_path / 'child.pid'
    code = "import subprocess,sys,time; p=subprocess.Popen([sys.executable,'-c','import time; time.sleep(30)']); open(sys.argv[1],'w').write(str(p.pid)); time.sleep(30)"
    def cancel():
        return pidfile.exists()
    with pytest.raises(MediaInterrupted):
        run_process([sys.executable, '-c', code, str(pidfile)], timeout=5, cancel=cancel, emit=lambda event: None)
    pid = int(pidfile.read_text())
    for _ in range(100):
        status = Path(f'/proc/{pid}/stat')
        if not status.exists() or status.read_text().split()[2] == 'Z':
            break
        time.sleep(.01)
    else:
        pytest.fail('Child still running after cancellation')


def test_native_progress_and_cancel_contract(monkeypatch):
    class Bridge:
        def __init__(self):
            self.stopped = threading.Event()
            self.released = False
        def executeManaged(self, *args):
            assert self.stopped.wait(2)
            return json.dumps({'returncode': 255, 'stdout': '', 'stderr': ''})
        def pollManaged(self, job):
            return json.dumps({'seconds': .5})
        def cancelManaged(self, job):
            self.stopped.set()
        def releaseManaged(self, job):
            self.released = True
    bridge = Bridge()
    monkeypatch.setattr(media_tools, '_native_media', bridge)
    events = []
    with pytest.raises(MediaInterrupted):
        media_tools.run(['ffmpeg', '-version'], cancel=lambda: bool(events), on_event=events.append, timeout=2)
    assert bridge.released and events[0].media_seconds == .5


def test_ffmpeg_capabilities_are_probed():
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg required')
    cap = media_tools.capabilities()
    assert cap['ffmpeg'] and cap['ffprobe']
    assert 'scale' in cap['filters'] and cap['encoders']


def test_reference_media_inventory_is_reproducible_offline(tmp_path):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/FFprobe required')
    from scripts.media_pipeline_fixtures import generate
    media = generate(tmp_path)
    data = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-of', 'json', str(media['mkv'])],
                                    check=True, capture_output=True, text=True, timeout=15).stdout)
    streams = data['streams']
    assert [s['tags']['language'] for s in streams if s['codec_type'] == 'audio'] == ['jpn', 'eng']
    assert len([s for s in streams if s['codec_type'] == 'subtitle']) == 1
    with pytest.raises(FileExistsError):
        generate(tmp_path)  # Reference files must not overwrite a previous run.


def test_public_api_rejects_unsupported_output_before_creating_task(monkeypatch):
    from fastapi.testclient import TestClient
    from run import app
    from animelab.services.download_manager import download_manager
    created = []
    monkeypatch.setattr(media_tools, 'is_native', lambda: True)
    monkeypatch.setattr(download_manager, 'start_download', lambda **kwargs: created.append(kwargs))
    client = TestClient(app)
    response = client.post('/api/download', json={'url': 'https://cdn.example/video.mp4',
        'outputProfile': {'mode': 'MP4_HARD'}})
    assert response.status_code == 422 and created == []
    profiles = client.get('/api/download/output-profiles').json()
    assert next(p for p in profiles if p['mode'] == 'MP4_HARD')['available'] is False


def test_two_accounts_do_not_share_media_inventory(tmp_path, monkeypatch):
    module = importlib.import_module('animelab.services.library_service')
    for name, language in [('alice', 'fr'), ('bob', 'ja')]:
        engine = create_database_engine('sqlite:///' + str(tmp_path / (name + '.sqlite3')))
        migrate(engine)
        monkeypatch.setattr(module, 'SessionLocal', sessionmaker(bind=engine))
        task = DownloadTask(id='same-id', subtitlesJson=[{'url': f'https://cdn.example/{language}.srt', 'lang': language}])
        library_service.save_task(task)
        with engine.connect() as connection:
            rows = connection.execute(select(tracks.c.metadata_json)).scalars().all()
            assert len(rows) == 1 and json.loads(rows[0])['lang'] == language
        engine.dispose()


def test_supervision_bounds_output_and_reports_nonzero_without_argv_secret():
    with pytest.raises(RuntimeError, match='diagnostics'):
        run_process([sys.executable, '-c', 'import sys; sys.stdout.write("x" * 3000000)'],
                    timeout=5, cancel=lambda: False, emit=lambda event: None)
    with pytest.raises(subprocess.CalledProcessError) as error:
        run_process([sys.executable, '-c', 'raise SystemExit(3)', 'private-argument'],
                    timeout=5, cancel=lambda: False, emit=lambda event: None, check=True)
    assert 'private-argument' not in str(error.value)
