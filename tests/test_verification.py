import os
import tempfile
import subprocess
import pytest
from fastapi.testclient import TestClient

from animelab.services.verification_service import verification_service, format_duration
from animelab.services.download_manager import download_manager
from animelab.models.download_task import DownloadTask, DownloadStatus
from run import app

client = TestClient(app)

@pytest.fixture
def sample_valid_mp4():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name

    # Create a real 1-second silent MP4 test video with ffmpeg
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "lavfi", "-i", "color=c=black:s=320x240:d=1",
        "-f", "lavfi", "-i", "anullsrc=r=44100:cl=mono",
        "-t", "1",
        "-c:v", "libx264", "-c:a", "aac",
        tmp_path
    ], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=True)

    yield tmp_path

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

@pytest.fixture
def sample_corrupted_file():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        f.write(b"NOT_A_REAL_VIDEO_HEADER_GARBAGE_CONTENT_HERE")
        tmp_path = f.name

    yield tmp_path

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

@pytest.fixture
def sample_empty_file():
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as f:
        tmp_path = f.name

    yield tmp_path

    if os.path.exists(tmp_path):
        os.remove(tmp_path)

def test_format_duration():
    assert format_duration(None) == ""
    assert format_duration(0) == ""
    assert format_duration(45) == "45s"
    assert format_duration(125) == "2m 05s"
    assert format_duration(3665) == "1h 01m 05s"

def test_verify_valid_file(sample_valid_mp4):
    res = verification_service.verify_file(sample_valid_mp4)
    assert res.valid is True
    assert res.status == "VALID"
    assert res.fileSize > 0
    assert res.hasVideo is True
    assert res.duration is not None
    assert res.duration > 0.5

def test_verify_missing_file():
    res = verification_service.verify_file("/non/existent/path/video.mp4")
    assert res.valid is False
    assert res.status == "MISSING"
    assert "introuvable" in res.error.lower()

def test_verify_empty_file(sample_empty_file):
    res = verification_service.verify_file(sample_empty_file)
    assert res.valid is False
    assert res.status == "EMPTY"
    assert res.fileSize == 0
    assert "0 octet" in res.error

def test_verify_corrupted_file(sample_corrupted_file):
    res = verification_service.verify_file(sample_corrupted_file)
    assert res.valid is False
    assert res.status == "CORRUPTED"
    assert "corrompu" in res.error.lower()

def test_verify_task_via_download_manager(sample_valid_mp4):
    task = DownloadTask(
        animeName="Test Anime",
        episodeNumber=1,
        fileName="test-ep1.mp4",
        savePath=sample_valid_mp4,
        status=DownloadStatus.COMPLETED,
    )
    download_manager.tasks[task.id] = task

    res = download_manager.verify_task(task.id)
    assert res is not None
    assert res.valid is True
    assert task.verificationStatus == "VALID"
    assert task.videoDuration is not None

def test_api_verify_endpoints(sample_valid_mp4):
    task = DownloadTask(
        animeName="API Test Anime",
        episodeNumber=2,
        fileName="api-ep2.mp4",
        savePath=sample_valid_mp4,
        status=DownloadStatus.COMPLETED,
    )
    download_manager.tasks[task.id] = task

    # Single task verify
    resp = client.post(f"/api/download/{task.id}/verify")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["valid"] is True
    assert data["status"] == "VALID"

    # Verify all
    from unittest.mock import patch
    with patch("animelab.services.download_manager.library_service.get_history", return_value=[]):
        resp_all = client.post("/api/download/verify-all")
        assert resp_all.status_code == 200
        all_data = resp_all.json()
        assert all_data["success"] is True
        assert all_data["total"] >= 1
        assert all_data["valid"] >= 1

def test_api_redownload_task(sample_corrupted_file):
    task = DownloadTask(
        animeName="Redownload Test Anime",
        episodeNumber=3,
        fileName="redownload-ep3.mp4",
        savePath=sample_corrupted_file,
        status=DownloadStatus.FAILED,
        verificationStatus="CORRUPTED",
    )
    download_manager.tasks[task.id] = task

    resp = client.post(f"/api/download/{task.id}/redownload")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["task"]["status"] == DownloadStatus.PENDING.value
    assert data["task"]["verificationStatus"] == "UNVERIFIED"
    assert not os.path.exists(sample_corrupted_file)


@pytest.mark.parametrize("diagnostic,code,valid", [
    ("[null @ 0x123] Application provided invalid, non monotonically increasing dts to muxer in stream 0: 30 >= 30\n" * 30, 0, True),
    ("[h264 @ 0x123] Invalid NAL unit size\n", 0, False),
    ("", 1, False),
])
def test_decode_diagnostics_are_classified(sample_valid_mp4, monkeypatch, diagnostic, code, valid):
    import json
    monkeypatch.setattr(verification_service, "_ffprobe_path", "/usr/bin/ffprobe")
    monkeypatch.setattr("animelab.services.verification_service.shutil.which", lambda name: "/usr/bin/" + name)
    calls = []
    def run(cmd, **kwargs):
        calls.append(cmd)
        if "-show_entries" in cmd:
            return subprocess.CompletedProcess(cmd, 0, json.dumps({"format": {"duration": "1200"},
                "streams": [{"codec_type": "video"}, {"codec_type": "audio"}]}), "")
        return subprocess.CompletedProcess(cmd, code, "", diagnostic)
    monkeypatch.setattr("animelab.services.verification_service.subprocess.run", run)
    result = verification_service.verify_file(sample_valid_mp4)
    assert result.valid == valid
    assert "-sn" in calls[1] and "-fps_mode" in calls[1]


def test_probe_exception_does_not_validate_magic_header(sample_valid_mp4, monkeypatch):
    monkeypatch.setattr(verification_service, "_ffprobe_path", "/usr/bin/ffprobe")
    def run(*args, **kwargs):
        raise subprocess.TimeoutExpired("ffprobe", 30)
    monkeypatch.setattr("animelab.services.verification_service.subprocess.run", run)
    result = verification_service.verify_file(sample_valid_mp4)
    assert not result.valid and result.status == "ERROR"
