"""JNI admission failures and native path semantics; host encoding is not device proof."""
import json
from pathlib import Path
import shutil
import subprocess

import pytest

from animelab import media_tools
from animelab.services.android_hardsub import subtitle_filter
from animelab.services.output_profiles import available_profiles, require_available


@pytest.mark.parametrize('payload', [
    {}, {'available': True}, {'available': True, 'renderVerified': False},
    {'available': True, 'renderVerified': True, 'fontPath': '/missing-font.ttf'},
])
def test_native_hardsub_requires_render_and_readable_font(monkeypatch, payload):
    class Bridge:
        @staticmethod
        def probeHardsub(directory):
            return json.dumps(payload)
    monkeypatch.setattr(media_tools, '_native_media', Bridge())
    assert not media_tools.native_hardsub_status()['available']
    with pytest.raises(ValueError, match='Android reste à valider'):
        require_available({'mode': 'MP4_HARD'})
    assert not next(p for p in available_profiles() if p['mode'] == 'MP4_HARD')['available']


def test_native_missing_probe_fails_closed(monkeypatch):
    monkeypatch.setattr(media_tools, '_native_media', object())
    assert not media_tools.native_hardsub_status()['available']


def test_native_verified_probe_still_requires_actual_codecs(tmp_path, monkeypatch):
    font = tmp_path/'font.ttf'; font.write_bytes(b'font placeholder')
    class Bridge:
        @staticmethod
        def probeHardsub(directory):
            return json.dumps(dict(available=True, renderVerified=True, fontPath=str(font)))
    monkeypatch.setattr(media_tools, '_native_media', Bridge())
    monkeypatch.setattr(media_tools, 'capabilities', lambda: dict(ffprobe=True, filters=[], encoders=[]))
    with pytest.raises(ValueError, match='libass'):
        require_available({'mode': 'MP4_HARD'})
    assert not next(p for p in available_profiles() if p['mode'] == 'MP4_HARD')['available']


def test_absolute_filter_handles_unicode_apostrophe_and_graph_syntax(tmp_path):
    if not shutil.which('ffmpeg'):
        pytest.skip('FFmpeg required')
    directory = tmp_path/"l'été animé : [a,b]; test"; directory.mkdir()
    fonts = directory/'fonts'; fonts.mkdir()
    subtitle = directory/'burn.srt'
    subtitle.write_text('1\n00:00:00,000 --> 00:00:01,000\nP14\n')
    result = subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=s=160x90:r=10',
        '-t', '1', '-vf', subtitle_filter(subtitle, fonts), '-f', 'null', '-'],
        capture_output=True, text=True, timeout=15)
    assert result.returncode == 0, result.stderr


def test_android_media_budget_is_one_worker(monkeypatch):
    from animelab.services.download_stages.media import MediaPipeline
    monkeypatch.setattr(media_tools, '_native_media', object())
    assert MediaPipeline(object()).budget.limit == 1


def test_android_p15_keeps_native_backends_and_refuses_unsupported_dash(monkeypatch):
    from animelab.services.media_contracts import ResolvedMedia, UnsupportedMedia
    from animelab.services.transfer_backends import TransferPlanner
    monkeypatch.setattr(media_tools, '_native_media', object())
    planner = TransferPlanner(object())
    assert planner.select(ResolvedMedia('https://fixture.example/video.mp4')).name == 'http-range'
    assert planner.select(ResolvedMedia('https://fixture.example/video.m3u8', protocol='hls')).name == 'hls-native'
    with pytest.raises(UnsupportedMedia):
        planner.select(ResolvedMedia('https://fixture.example/video.mpd', protocol='dash'))


def test_instrumentation_requires_real_render_cancel_and_export_evidence(tmp_path):
    from scripts.android_instrumentation import validate_hardsub_report
    with pytest.raises(RuntimeError, match='Missing'):
        validate_hardsub_report('OK (1 test)', tmp_path, 35)
    data = dict(hardsub=dict(available=True, renderVerified=True, pixelDifference=20000, api=35, pageSize=4096),
                managed_cancellation=True, managed_progress=True, storage_export=True)
    validate_hardsub_report('ANIMAN_NATIVE_MEDIA_PROBE='+json.dumps(data), tmp_path, 35)
    assert json.loads((tmp_path/'hardsub-proof.json').read_text()) == data
    data['hardsub']['renderVerified'] = False
    with pytest.raises(RuntimeError, match='Incomplete'):
        validate_hardsub_report('ANIMAN_NATIVE_MEDIA_PROBE='+json.dumps(data), tmp_path, 35)


@pytest.mark.parametrize('alignment,expected_ok', [(4096, False), (16384, True)])
def test_probe_audit_rejects_four_kilobyte_load_segments(tmp_path, alignment, expected_ok):
    import struct
    from zipfile import ZipFile
    from scripts.android_hardsub_audit import audit
    elf = bytearray(120); elf[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', elf, 18, 183)
    struct.pack_into('<Q', elf, 32, 64)
    struct.pack_into('<HH', elf, 54, 56, 1)
    struct.pack_into('<IIQQQQQQ', elf, 64, 1, 5, 0, 0, 0, 120, 120, alignment)
    apk = tmp_path/'probe.apk'
    with ZipFile(apk, 'w') as archive:
        archive.writestr('lib/arm64-v8a/libavfilter.so', elf)
    if expected_ok:
        assert audit(apk, 'arm64-v8a')['elf16kbAligned']
    else:
        with pytest.raises(ValueError, match='16 KB'):
            audit(apk, 'arm64-v8a')
