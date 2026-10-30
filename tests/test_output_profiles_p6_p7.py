import asyncio
import json
from pathlib import Path
import shutil
import subprocess
from unittest.mock import AsyncMock

import httpx
import pytest

from animelab import media_tools, platform_events
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import DownloadManagerService
from animelab.services.library_service import library_service
from animelab.services.output_profiles import snapshot
from animelab.services.output_processor import OutputError
from animelab.services.subtitle_timing import shift
from scripts.media_pipeline_fixtures import generate

VTT = b'WEBVTT\n\n00:00:00.000 --> 00:00:01.000\nHello\n'


@pytest.mark.asyncio
async def test_android_hardsub_uses_absolute_jni_paths_and_preserves_original(output_case, monkeypatch):
    manager, task, files, requests = output_case
    font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font.is_file():
        pytest.skip('Host font required for simulated JNI adapter')
    calls = []
    class HostBridge:
        @staticmethod
        def probeHardsub(directory):
            return json.dumps(dict(available=True, renderVerified=True, fontPath=str(font)))
        @staticmethod
        def execute(tool, arguments, timeout):
            args = [tool, *json.loads(arguments)]; calls.append(args)
            result = subprocess.run(args, capture_output=True, text=True, timeout=timeout/1000)
            return json.dumps(dict(returncode=result.returncode, stdout=result.stdout, stderr=result.stderr))
        @staticmethod
        def executeManaged(tool, arguments, timeout, job):
            return HostBridge.execute(tool, arguments, timeout)
        @staticmethod
        def pollManaged(job): return '{}'
        @staticmethod
        def cancelManaged(job): pass
        @staticmethod
        def releaseManaged(job): pass
    monkeypatch.setattr(media_tools, '_native_media', HostBridge())
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD', 'keepOriginals': True})
    before = Path.cwd()
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert before == Path.cwd() and files['mkv'].is_file() and not requests
    encode = next(args for args in calls if '-vf' in args)
    assert '-threads' in encode and encode[encode.index('-threads')+1] == '1'
    assert 'filename=/' in encode[encode.index('-vf')+1]
    streams = probe(task.savePath)['streams']
    assert {s['codec_name'] for s in streams} == {'h264', 'aac'}


def probe(path):
    return json.loads(subprocess.run(['ffprobe', '-v', 'error', '-show_streams', '-show_format', '-of', 'json', str(path)],
                                    check=True, capture_output=True, text=True, timeout=20).stdout)


@pytest.fixture
def output_case(tmp_path, monkeypatch):
    if not shutil.which('ffmpeg') or not shutil.which('ffprobe'):
        pytest.skip('FFmpeg/FFprobe required')
    folder = tmp_path / "l'été animé with spaces"
    folder.mkdir()
    files = generate(folder)
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path)
    monkeypatch.setattr(library_service, 'save_task', lambda task: None)
    monkeypatch.setattr(library_service, 'mark_as_downloaded', lambda *args: None)
    monkeypatch.setattr(manager, 'broadcast_update', lambda task: None)
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    monkeypatch.setattr(platform_events, 'completed_handler', None)
    requests = []
    def request(req):
        requests.append(req)
        return httpx.Response(200, content=VTT)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(request), follow_redirects=True, headers=kwargs.get('headers')))
    task = DownloadTask(savePath=str(files['mkv']), fileName=files['mkv'].name,
        fileUrl='https://source.example/episode', downloadSubtitles=True,
        subtitlesJson=[{'url': 'https://cdn.example/en.vtt', 'label': 'English', 'lang': 'en'}],
        outputProfileJson=snapshot({'mode': 'MKV_SOFT', 'keepOriginals': True}))
    return manager, task, files, requests


@pytest.mark.asyncio
async def test_mkv_two_audio_two_subtitles_exact_selection_and_dispositions(output_case):
    manager, task, files, requests = output_case
    processor = manager.media_pipeline.output_processor
    inventory, _ = processor.inventory(task)
    selections = [dict(trackId=t.id, default=(t.kind == 'audio' and t.lang == 'jpn') or (t.kind == 'subtitle' and t.lang in ('fra', 'fr')),
                       forced=t.kind == 'subtitle' and t.lang == 'en') for t in inventory]
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'selections': selections, 'keepOriginals': True})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    streams = probe(task.savePath)['streams']
    assert [s['codec_type'] for s in streams].count('audio') == 2
    subs = [s for s in streams if s['codec_type'] == 'subtitle']
    assert [s['tags']['language'] for s in subs] == ['fra', 'eng']
    assert subs[0]['codec_name'] == 'ass' and subs[0]['disposition']['default']
    assert subs[1]['disposition']['forced'] and not subs[1]['disposition']['default']
    assert files['mkv'].exists() and len(requests) == 1
    state = processor.state(task)
    assert state['completed'] and state['warnings']
    assert Path(state['master']).is_file()
    again = task.savePath
    await manager._finalize_task(task)
    assert task.savePath == again and len(requests) == 1


@pytest.mark.asyncio
async def test_sidecar_offsets_keep_ass_style_and_source(output_case):
    manager, task, files, requests = output_case
    inventory, _ = manager.media_pipeline.output_processor.inventory(task)
    sub = next(t for t in inventory if t.kind == 'subtitle' and t.remote is None)
    task.outputProfileJson = snapshot({'mode': 'SIDECAR', 'selections': [{'trackId': sub.id, 'offsetSeconds': .5}], 'keepOriginals': True})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    sidecars = json.loads(task.savePathSubtitle)
    content = Path(sidecars[0]).read_text()
    assert '[V4+ Styles]' in content
    from animelab.services.subtitle_timing import seconds
    packet = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 's', '-show_packets', '-of', 'json', str(files['mkv'])],
                                      check=True, capture_output=True, text=True).stdout)['packets'][0]
    start = content.split('Dialogue: ', 1)[1].split(',')[1]
    assert abs(seconds(start) - float(packet['pts_time']) - .5) < .011
    assert files['mkv'].exists() and requests == []
    assert len(probe(task.savePath)['streams']) == len(probe(files['mkv'])['streams'])


@pytest.mark.asyncio
async def test_hardsub_mp4_renders_pixels_and_chosen_audio(output_case):
    if 'subtitles' not in media_tools.capabilities()['filters'] or 'libx264' not in media_tools.capabilities()['encoders']:
        pytest.skip('libass/libx264 required')
    manager, task, files, requests = output_case
    processor = manager.media_pipeline.output_processor
    inventory, _ = processor.inventory(task)
    sub = next(t for t in inventory if t.kind == 'subtitle' and t.remote is None)
    audio = next(t for t in inventory if t.kind == 'audio' and t.lang == 'eng')
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD', 'keepOriginals': True, 'burnTrackId': sub.id, 'selections': [
        {'trackId': audio.id, 'default': True}, {'trackId': sub.id, 'offsetSeconds': .3}]})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    streams = probe(task.savePath)['streams']
    assert [s['codec_type'] for s in streams] == ['video', 'audio']
    assert streams[0]['codec_name'] == 'h264' and streams[1]['tags']['language'] == 'eng'
    assert files['mkv'].exists() and not requests
    def frame(path, at):
        return subprocess.run(['ffmpeg', '-v', 'error', '-ss', str(at), '-i', str(path), '-frames:v', '1',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24', '-'], check=True, capture_output=True, timeout=20).stdout
    master_frame = frame(files['mkv'], .6)
    rendered = frame(task.savePath, .6)
    assert len(master_frame) == len(rendered)
    assert sum(abs(a-b) for a,b in zip(master_frame, rendered)) > 10000
    # Before the shifted first cue the black image remains black.
    assert sum(frame(task.savePath, .1)) < sum(rendered) / 2


@pytest.mark.asyncio
async def test_missing_track_disk_failure_and_cancel_preserve_source(output_case, monkeypatch):
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'selections': [{'trackId': 'missing'}]})
    original = files['mkv'].read_bytes()
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED and 'absente' in task.error
    assert files['mkv'].read_bytes() == original
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT'})
    task.status = DownloadStatus.PENDING
    monkeypatch.setattr(shutil, 'disk_usage', lambda path: type('Usage', (), {'free': 0})())
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED and 'disque' in task.error
    assert files['mkv'].read_bytes() == original


def test_negative_offset_removes_only_expired_cues():
    result = shift(b'1\n00:00:00,000 --> 00:00:00,200\nOld\n\n2\n00:00:00,500 --> 00:00:01,000\nNew\n', -.3, '.srt')
    assert b'Old' not in result and b'00:00:00,200 --> 00:00:00,700' in result
    assert b'New' in result


@pytest.mark.asyncio
async def test_publication_failure_rolls_back_only_our_files_and_retry_is_local(output_case, monkeypatch):
    manager, task, files, requests = output_case
    processor = manager.media_pipeline.output_processor
    sub = next(t for t in processor.inventory(task)[0] if t.kind == 'subtitle' and t.remote is None)
    task.outputProfileJson = snapshot({'mode': 'SIDECAR', 'selections': [{'trackId': sub.id}]})
    publish = manager._publish_mux_file
    created = []
    def fail_second(*args):
        if created:
            raise OSError('disk provider failed')
        result = publish(*args)
        created.append(result)
        return result
    monkeypatch.setattr(manager, '_publish_mux_file', fail_second)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED
    assert files['mkv'].exists() and all(not p.exists() for p in created)
    monkeypatch.setattr(manager, '_publish_mux_file', publish)
    monkeypatch.setattr(manager, 'resolve_imported_video_stream', AsyncMock(side_effect=AssertionError('must stay local')))
    task.status = DownloadStatus.PENDING
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert not requests


@pytest.mark.asyncio
async def test_collision_and_android_export_keep_only_selected_sidecars(output_case):
    manager, task, files, requests = output_case
    processor = manager.media_pipeline.output_processor
    sub = next(t for t in processor.inventory(task)[0] if t.kind == 'subtitle' and t.remote is None)
    task.outputProfileJson = snapshot({'mode': 'SIDECAR', 'selections': [{'trackId': sub.id}]})
    collision = files['mkv'].with_name('reference.sidecar.mkv')
    collision.write_bytes(b'unrelated existing file')
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert collision.read_bytes() == b'unrelated existing file'
    assert task.savePath != str(collision) and Path(task.savePath).suffix == '.mkv'
    exported = platform_events.completed_paths(task)
    assert task.savePath in exported and len(exported) == 3  # video, ASS, provenance JSON
    assert not any('.animelab-media-' in path for path in exported)
    assert not requests


@pytest.mark.asyncio
async def test_hardsub_converts_pcm_audio_to_aac(output_case):
    manager, task, files, requests = output_case
    pcm = files['mkv'].with_name('pcm.mkv')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(files['mkv']), '-map', '0:v', '-map', '0:a:0', '-map', '0:s',
                    '-c:v', 'copy', '-c:a', 'pcm_s16le', '-c:s', 'copy', str(pcm)], check=True, capture_output=True)
    task.savePath, task.fileName = str(pcm), pcm.name
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD'})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert next(s for s in probe(task.savePath)['streams'] if s['codec_type'] == 'audio')['codec_name'] == 'aac'
    assert not requests


@pytest.mark.asyncio
async def test_cancelled_encode_retains_master_and_restarts_without_video_download(output_case, monkeypatch):
    from animelab.services.media_execution import MediaInterrupted
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD', 'keepOriginals': True})
    run = manager.media_pipeline._run_media
    def interrupt(task, args, **kwargs):
        if '-vf' in args:
            task.paused = True
            raise MediaInterrupted('paused')
        return run(task, args, **kwargs)
    monkeypatch.setattr(manager.media_pipeline, '_run_media', interrupt)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.PAUSED
    assert Path(manager.media_pipeline.output_processor.state(task)['master']).exists()
    monkeypatch.setattr(manager.media_pipeline, '_run_media', run)
    monkeypatch.setattr(manager, 'resolve_imported_video_stream', AsyncMock(side_effect=AssertionError('no network video')))
    task.paused = False
    task.status = DownloadStatus.PENDING
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert not requests and files['mkv'].exists()


@pytest.mark.asyncio
async def test_embedded_font_is_attached_to_mkv(output_case):
    font = Path('/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf')
    if not font.exists():
        pytest.skip('Reference font unavailable')
    manager, task, files, requests = output_case
    source = files['mkv'].with_name('font-source.mkv')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(files['mkv']), '-map', '0', '-c', 'copy', '-attach', str(font),
        '-metadata:s:t:0', 'filename=DejaVuSans.ttf', '-metadata:s:t:0', 'mimetype=application/x-truetype-font', str(source)],
        check=True, capture_output=True)
    task.savePath, task.fileName = str(source), source.name
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    attachments = [s for s in probe(task.savePath)['streams'] if s['codec_type'] == 'attachment']
    assert len(attachments) == 1 and attachments[0]['tags']['filename'].endswith('.ttf')
    manager.tasks[task.id] = task
    await manager.reprocess_output(task.id, {'mode': 'MP4_HARD'})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert not manager.media_pipeline.output_processor.state(task)['warnings']
    assert all(s['codec_type'] != 'attachment' for s in probe(task.savePath)['streams'])


@pytest.mark.asyncio
async def test_reprocessing_existing_task_changes_mode_without_resolving_video(output_case, monkeypatch):
    manager, task, files, requests = output_case
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    manager.tasks[task.id] = task
    monkeypatch.setattr(manager, 'resolve_imported_video_stream', AsyncMock(side_effect=AssertionError('no re-resolution')))
    response = await manager.output_inventory(task.id)
    assert response['tracks'] and all('path' not in row and 'url' not in row for row in response['tracks'])
    await manager.reprocess_output(task.id, {'mode': 'MP4_HARD', 'keepOriginals': True})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert task.savePath.endswith('.mp4') and len(requests) == 1  # original English VTT only fetched once for MKV


@pytest.mark.asyncio
async def test_hardsub_rejects_bitmap_before_publishing(output_case, monkeypatch):
    from dataclasses import replace
    manager, task, files, requests = output_case
    processor = manager.media_pipeline.output_processor
    inventory = processor.inventory
    def bitmap(*args, **kwargs):
        tracks, data = inventory(*args, **kwargs)
        return [replace(track, codec='hdmv_pgs_subtitle') if track.kind == 'subtitle' and track.remote is None else track for track in tracks], data
    monkeypatch.setattr(processor, 'inventory', bitmap)
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD'})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED and 'bitmap' in task.error
    assert files['mkv'].exists()


def test_profile_cannot_disable_strict_processing():
    assert json.loads(snapshot({'mode': 'SIDECAR', 'strict': False}))['strict'] is True


@pytest.mark.asyncio
async def test_mkv_subtitle_offset_is_preserved_in_packets(output_case, monkeypatch):
    manager, task, files, requests = output_case
    run = manager.media_pipeline._run_media
    def legacy_default_mode(task, args, **kwargs):
        # Reproduce FFmpeg 4.4's default on modern development machines too.
        if str(args[-1]).endswith('.mkv') and '-default_mode' not in args:
            args = [*args[:-1], '-default_mode', 'infer', args[-1]]
        return run(task, args, **kwargs)
    monkeypatch.setattr(manager.media_pipeline, '_run_media', legacy_default_mode)
    inventory = manager.media_pipeline.output_processor.inventory(task)[0]
    audio = next(t for t in inventory if t.kind == 'audio')
    sub = next(t for t in inventory if t.kind == 'subtitle' and t.remote is None)
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'selections': [
        {'trackId': audio.id, 'default': True}, {'trackId': sub.id, 'offsetSeconds': .6, 'forced': True}]})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    subtitle = next(s for s in probe(task.savePath)['streams'] if s['codec_type'] == 'subtitle')
    assert not subtitle['disposition']['default'] and subtitle['disposition']['forced']
    packets = json.loads(subprocess.run(['ffprobe', '-v', 'error', '-select_streams', 's', '-show_packets', '-of', 'json', task.savePath],
                                       check=True, capture_output=True, text=True).stdout)['packets']
    assert abs(float(packets[0]['pts_time']) - .6) < .04


@pytest.mark.asyncio
async def test_out_of_range_hardsub_is_not_reported_as_rendered(output_case):
    manager, task, files, requests = output_case
    inventory = manager.media_pipeline.output_processor.inventory(task)[0]
    audio = next(t for t in inventory if t.kind == 'audio')
    sub = next(t for t in inventory if t.kind == 'subtitle' and t.remote is None)
    task.outputProfileJson = snapshot({'mode': 'MP4_HARD', 'burnTrackId': sub.id, 'selections': [
        {'trackId': audio.id}, {'trackId': sub.id, 'offsetSeconds': 600}]})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED and 'hors' in task.error
    assert files['mkv'].exists()


def test_local_probe_rejects_disguised_manifest_without_network(output_case):
    manager, task, files, requests = output_case
    fake = files['mp4'].with_name('fake.audio')
    fake.write_text('#EXTM3U\n#EXTINF:2,\nhttp://127.0.0.1/private\n')
    with pytest.raises(OutputError, match='manifeste'):
        manager.media_pipeline.output_processor.probe(fake)
    assert requests == []


@pytest.mark.asyncio
async def test_resource_network_shares_scheduler_slots(output_case):
    manager, task, files, requests = output_case
    manager.max_concurrent_downloads = 1
    active = DownloadTask(status=DownloadStatus.DOWNLOADING)
    manager.tasks = {active.id: active, task.id: task}
    manager.scheduler.network_tasks.add(active.id)
    started = asyncio.Event()
    async def reserve():
        async with manager.scheduler.resource_network(task):
            started.set()
            assert len(manager.scheduler.network_tasks) == 1
    job = asyncio.create_task(reserve())
    await asyncio.sleep(.06)
    assert not started.is_set()
    active.phase = 'preparing_output'
    manager.scheduler.release_network(active.id)
    await asyncio.wait_for(job, 2)
    assert not manager.scheduler.network_tasks and not manager.scheduler.resource_waiters


def test_windows_srt_crlf_offset():
    content = b'1\r\n00:00:00,500 --> 00:00:01,000\r\nBonjour\r\n\r\n'
    shifted = shift(content, .25, '.srt')
    assert b'00:00:00,750 --> 00:00:01,250' in shifted and b'Bonjour' in shifted


@pytest.mark.asyncio
async def test_external_audio_acquisition_uses_selected_resource_headers(output_case, monkeypatch):
    manager, task, files, requests = output_case
    audio_path = files['mkv'].with_name('external.m4a')
    subprocess.run(['ffmpeg', '-v', 'error', '-i', str(files['mkv']), '-map', '0:a:1', '-c:a', 'copy', str(audio_path)],
                   check=True, capture_output=True)
    payload = audio_path.read_bytes()
    requests.clear()
    def fetch(request):
        requests.append(request)
        assert request.headers['Referer'] == 'https://source.example/episode'
        assert request.headers['X-Track'] == 'per-resource'
        return httpx.Response(200, content=payload)
    monkeypatch.setattr(manager, '_create_async_client', lambda **kwargs: httpx.AsyncClient(
        transport=httpx.MockTransport(fetch), follow_redirects=True, headers=kwargs.get('headers')))
    task.mediaJson = json.dumps({'audioTracks': [{'id': 'external-english', 'url': 'https://cdn.example/english.m4a',
        'lang': 'eng', 'label': 'English external', 'headers': {'X-Track': 'per-resource'},
        'referer': 'https://source.example/episode'}]})
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'selections': [{'trackId': 'external-english', 'default': True}]})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    streams = probe(task.savePath)['streams']
    assert [s['codec_type'] for s in streams] == ['video', 'audio']
    assert streams[1]['tags']['language'] == 'eng'
    assert len(requests) == 1


@pytest.mark.asyncio
async def test_forced_redownload_drops_previous_receipt_and_master(output_case):
    manager, task, files, requests = output_case
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    processor = manager.media_pipeline.output_processor
    master = Path(processor.state(task)['master'])
    previous = Path(task.savePath)
    manager.tasks[task.id] = task
    manager.redownload_task(task.id, force=True)
    assert task.status == DownloadStatus.PENDING
    assert not master.exists() and not processor.state(task)
    assert previous.exists()  # A new transfer does not destroy an existing good output.
    assert task.savePath == str(files['mkv']) and not files['mkv'].exists()
    assert task.totalBytes == task.downloadedBytes == 0
    assert not processor.recover(task)


@pytest.mark.asyncio
async def test_receipt_rejects_tampered_artifact_and_retries_from_master(output_case):
    manager, task, files, requests = output_case
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    processor = manager.media_pipeline.output_processor
    old_output = Path(task.savePath)
    old_output.write_bytes(b'corrupted artifact')
    assert not processor.recover(task)
    manager.tasks[task.id] = task
    await manager.reprocess_output(task.id, {'mode': 'MKV_SOFT'})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert Path(task.savePath) != old_output and len(requests) == 1


@pytest.mark.asyncio
async def test_removal_waits_for_actual_media_job_before_private_cleanup(output_case, monkeypatch):
    manager, task, files, requests = output_case
    master = manager.media_pipeline.output_processor.ensure_master(task)
    job = asyncio.get_running_loop().create_future()
    manager.media_pipeline.jobs[task.id] = job
    manager.tasks[task.id] = task
    monkeypatch.setattr(library_service, 'delete_task_entity', lambda task_id: True)
    with pytest.raises(ValueError, match='Wait'):
        manager.remove_task(task.id)
    assert master.exists()
    # Between CPU stages the network worker can still own this task. Defer
    # workspace deletion until that worker acknowledges cancellation as well.
    manager.media_pipeline.jobs.pop(task.id)
    manager.scheduler.workers[task.id] = job
    assert manager.remove_task(task.id)
    assert master.exists() and task.cancelled and task._removed
    job.set_result(None)
    await asyncio.sleep(0)
    assert not master.exists() and files['mkv'].exists()
    # A late finalization callback cannot resurrect the deleted row.
    import importlib
    module = importlib.import_module('animelab.services.library_service')
    monkeypatch.setattr(module, 'transaction', lambda *args: pytest.fail('Removed task must not be persisted'))
    type(library_service).save_task(library_service, task)
    library_service.save_tasks_batch([task])
