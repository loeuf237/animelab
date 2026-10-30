"""A processed episode should occupy one video unless retention was requested."""
import json
from pathlib import Path

import pytest

from animelab import platform_events
from animelab.models.download_task import DownloadStatus
from animelab.services.output_profiles import snapshot
from animelab.services.verification_service import VerificationResult, verification_service
import test_output_profiles_p6_p7 as reference

output_case = reference.output_case


def test_original_retention_is_opt_in():
    assert not json.loads(snapshot({'mode': 'MKV_SOFT'}))['keepOriginals']
    assert json.loads(snapshot({'mode': 'MKV_SOFT', 'keepOriginals': True}))['keepOriginals']


@pytest.mark.asyncio
@pytest.mark.parametrize('retain', [False, True])
@pytest.mark.parametrize('android_export', [False, True])
async def test_verified_output_retains_only_requested_video_copies(output_case, monkeypatch, retain, android_export):
    manager, task, files, requests = output_case
    source = files['mp4'].with_name('episode.mp4')
    files['mp4'].rename(source)
    task.savePath, task.fileName = str(source), source.name
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': retain})
    release = manager.media_pipeline.output_processor.release_originals
    cleanup_states = []
    def cleanup(completing):
        cleanup_states.append(completing.status)
        return release(completing)
    monkeypatch.setattr(manager.media_pipeline.output_processor, 'release_originals', cleanup)
    exported = []
    if android_export:
        def export(completed):
            paths = platform_events.completed_paths(completed)
            exported.extend(paths)
            return {'uris': ['content://test/' + str(i) for i in range(len(paths))], 'destination': 'Downloads/AnimeLab'}
        monkeypatch.setattr(platform_events, 'completed_handler', export)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert cleanup_states[0] == DownloadStatus.MUXING
    artifact = Path(task.savePath)
    assert artifact.is_file() and artifact.suffix == '.mkv'
    assert source.exists() is retain
    processor = manager.media_pipeline.output_processor
    state = processor.state(task)
    if retain:
        assert Path(state['master']).is_file()
    else:
        assert not state.get('master')
        assert not list(artifact.parent.glob('.animelab-media-*/master.*'))
        assert not state.get('resources')
        assert processor.recover(task)
    if android_export:
        assert exported == [str(artifact)]
    await manager._finalize_task(task)
    assert Path(task.savePath) == artifact and len(requests) == 1
    if android_export:
        assert exported == [str(artifact)]


@pytest.mark.asyncio
async def test_verification_failure_keeps_original_and_working_master(output_case, monkeypatch):
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': False})
    monkeypatch.setattr(verification_service, 'verify_file', lambda **kwargs:
                        VerificationResult(valid=False, status='CORRUPTED', error='Synthetic failed decode'))
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.FAILED
    assert files['mkv'].is_file()
    assert Path(manager.media_pipeline.output_processor.state(task)['master']).is_file()


@pytest.mark.asyncio
async def test_reprocess_without_retention_uses_only_local_published_tracks(output_case):
    manager, task, files, requests = output_case
    source = files['mp4'].with_name('episode.mp4')
    files['mp4'].rename(source)
    task.savePath, task.fileName = str(source), source.name
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': False})
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    first = Path(task.savePath)
    manager.tasks[task.id] = task
    await manager.reprocess_output(task.id, {'mode': 'SIDECAR', 'keepOriginals': False})
    await manager._execute_download(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert Path(task.savePath).is_file() and not first.exists()
    assert len(requests) == 1  # Reuse the embedded subtitle, without fetching it again.
    assert not manager.media_pipeline.output_processor.state(task).get('master')


@pytest.mark.asyncio
async def test_locked_original_cleanup_is_retryable_without_another_output(output_case, monkeypatch):
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': False})
    unlink = Path.unlink
    def locked(path, *args, **kwargs):
        if path == files['mkv']:
            raise PermissionError('Synthetic Windows file lock')
        return unlink(path, *args, **kwargs)
    monkeypatch.setattr(Path, 'unlink', locked)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    artifact = task.savePath
    assert files['mkv'].is_file()
    monkeypatch.setattr(Path, 'unlink', unlink)
    await manager._finalize_task(task)
    assert task.savePath == artifact and not files['mkv'].exists()
    assert len(requests) == 1
    assert not manager.media_pipeline.output_processor.state(task).get('master')


@pytest.mark.asyncio
async def test_source_replaced_by_user_is_not_removed(output_case, monkeypatch):
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': False})
    verify = verification_service.verify_file
    def replace_source(**kwargs):
        result = verify(**kwargs)
        files['mkv'].write_bytes(b'Another file now occupies the source pathname')
        return result
    monkeypatch.setattr(verification_service, 'verify_file', replace_source)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    assert files['mkv'].read_bytes() == b'Another file now occupies the source pathname'
    assert not manager.media_pipeline.output_processor.state(task).get('master')


@pytest.mark.asyncio
async def test_interrupted_retirement_recovers_from_verified_receipt(output_case, monkeypatch):
    manager, task, files, requests = output_case
    task.outputProfileJson = snapshot({'mode': 'MKV_SOFT', 'keepOriginals': False})
    processor = manager.media_pipeline.output_processor
    write = processor.write_receipt
    def fail_cleanup_receipt(task, state):
        if state.get('originalsDiscarded'):
            raise OSError('Synthetic interruption after working copies were removed')
        return write(task, state)
    monkeypatch.setattr(processor, 'write_receipt', fail_cleanup_receipt)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED, task.error
    artifact = task.savePath
    assert not files['mkv'].exists()
    monkeypatch.setattr(processor, 'write_receipt', write)
    await manager._finalize_task(task)
    assert task.status == DownloadStatus.COMPLETED and task.savePath == artifact
    assert not processor.state(task).get('master') and len(requests) == 1
