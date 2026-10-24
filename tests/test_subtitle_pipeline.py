import json
import asyncio
import shutil
import struct
import subprocess
from pathlib import Path
from unittest.mock import AsyncMock

import httpx
import pytest

from animan.models.download_task import DownloadTask, DownloadStatus
from animan.services.download_manager import download_manager as manager, SubtitleError
from animan.services.library_service import library_service
from animan.services.scraping_service import scraping_service
from animan.services.subtitle_service import normalize_subtitles
from animan.services.verification_service import verification_service

SRT = b"1\n00:00:00,000 --> 00:00:01,000\nBonjour\n\n"


@pytest.fixture
def isolated(monkeypatch):
    monkeypatch.setattr(library_service, "save_task", lambda task: None)
    monkeypatch.setattr(library_service, "mark_as_downloaded", lambda *args: None)
    monkeypatch.setattr(manager, "broadcast_update", lambda task: None)
    monkeypatch.setattr(manager, "plex_organization", False)


@pytest.fixture
def video(tmp_path, isolated):
    if not shutil.which("ffmpeg") or not shutil.which("ffprobe"):
        pytest.skip("FFmpeg and ffprobe required")
    path = tmp_path / "episode.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                    "color=c=black:s=160x90:r=10", "-f", "lavfi", "-i", "sine=frequency=440",
                    "-t", "2", "-c:v", "mpeg4", "-c:a", "aac", str(path)],
                   check=True, capture_output=True, timeout=30)
    return path


def task(path, tracks):
    return DownloadTask(animeName="Test", fileName=path.name, savePath=str(path),
                        downloadPageUrl="https://player.example/embed/123",
                        downloadSubtitles=True, subtitlesJson=tracks)


def mock_http(monkeypatch, handler):
    monkeypatch.setattr(manager, "_create_async_client", lambda **kwargs:
                        httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False,
                                          follow_redirects=True, headers=kwargs.get("headers")))


def streams(path):
    result = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(path)],
                            check=True, capture_output=True, text=True, timeout=30)
    return json.loads(result.stdout)["streams"]


def test_extraction_keeps_track_boundaries_and_relative_urls():
    source = '''tracks: [{file: "/fr.vtt", kind: "captions", srclang: "fr"},
                         {"file": "//cdn.example/en.vtt", label: "English [CC]", srclang: "en"}]'''
    tracks = scraping_service._extract_all_subtitles(source, "", "https://player.example/embed/123")
    assert len(tracks) == 2
    assert tracks[0]["url"] == "https://player.example/fr.vtt"
    assert tracks[0]["label"] == "Sous-titres"
    assert tracks[0]["lang"] == "fr"
    assert tracks[1]["url"] == "https://cdn.example/en.vtt"
    assert tracks[1]["label"] == "English [CC]"


def test_html_track_resolves_relative_url():
    tracks = scraping_service._extract_all_subtitles("", '<track src="../fr.vtt" srclang="fr">',
                                                    "https://player.example/embed/123")
    assert tracks[0]["url"] == "https://player.example/fr.vtt"


@pytest.mark.asyncio
async def test_download_list_src_duplicate_labels_and_language(video, monkeypatch):
    tracks = [{"src": "/fr.srt", "label": "Sous-titres", "srclang": "fr"},
              {"url": "https://cdn.example/en.srt", "label": "Sous-titres", "lang": "en"}]
    episode = task(video, tracks)
    assert isinstance(episode.subtitlesJson, str)
    seen = []
    def handler(request):
        seen.append(request)
        return httpx.Response(200, content=SRT if request.url.path == "/fr.srt" else SRT.replace(b"Bonjour", b"Hello"))
    mock_http(monkeypatch, handler)
    await manager._download_subtitles(episode)
    paths = json.loads(episode.savePathSubtitle)
    assert len(set(paths)) == 2
    assert b"Bonjour" in Path(paths[0]).read_bytes()
    assert b"Hello" in Path(paths[1]).read_bytes()
    assert seen[0].headers["referer"] == episode.downloadPageUrl
    manager._mux_subtitles_with_ffmpeg(episode)
    subtitles = [s for s in streams(episode.savePath) if s["codec_type"] == "subtitle"]
    assert len(subtitles) == 2
    assert [s["tags"]["language"] for s in subtitles] == ["fra", "eng"]


@pytest.mark.asyncio
@pytest.mark.parametrize("content", [b"<html>Forbidden</html>", b"", b"not a subtitle"])
async def test_download_rejects_invalid_content(tmp_path, isolated, monkeypatch, content):
    episode = task(tmp_path / "episode.mp4", [{"url": "https://cdn.example/fr.srt"}])
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=content))
    with pytest.raises(SubtitleError):
        await manager._download_subtitles(episode)
    assert episode.savePathSubtitle is None


@pytest.mark.asyncio
@pytest.mark.parametrize("redirect", [False, True])
async def test_download_blocks_private_urls_and_redirects(tmp_path, isolated, monkeypatch, redirect):
    url = "https://cdn.example/fr.srt" if redirect else "http://127.0.0.1/fr.srt"
    episode = task(tmp_path / "episode.mp4", [{"url": url}])
    seen = []
    def handler(request):
        seen.append(str(request.url))
        return httpx.Response(302, headers={"location": "http://127.0.0.1/fr.srt"})
    mock_http(monkeypatch, handler)
    with pytest.raises(SubtitleError):
        await manager._download_subtitles(episode)
    assert seen == ([url] if redirect else [])


@pytest.mark.asyncio
@pytest.mark.parametrize("container", ["mp4", "mkv"])
async def test_mux_validates_output_and_updates_size(video, monkeypatch, container):
    if container == "mkv":
        converted = video.with_suffix(".mkv")
        subprocess.run(["ffmpeg", "-v", "error", "-i", str(video), "-c", "copy", str(converted)],
                       check=True, capture_output=True)
        video = converted
    else:
        with video.open("ab") as output:
            output.write(struct.pack(">I4s", 65544, b"free") + b"\0" * 65536)
    episode = task(video, [{"url": "https://cdn.example/fr.srt", "lang": "fr"}])
    episode.totalBytes = video.stat().st_size
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=SRT))
    events = []
    monkeypatch.setattr(manager, "broadcast_update", lambda item: events.append(item.to_dict()))
    await manager._download_subtitles(episode)
    await manager._finalize_task(episode)
    assert [event["phase"] for event in events[:3]] == ["subtitles", "muxing", "verifying"]
    assert events[1]["status"] == "MUXING"
    assert events[-1]["status"] == "COMPLETED"
    assert episode.status == DownloadStatus.COMPLETED
    assert episode.totalBytes == episode.downloadedBytes == Path(episode.savePath).stat().st_size
    assert verification_service.verify_file(episode.savePath, expected_size=episode.totalBytes).valid
    assert any(s["codec_type"] == "subtitle" for s in streams(episode.savePath))


@pytest.mark.asyncio
async def test_mux_failure_preserves_files_and_reports_failure(video):
    sidecar = video.with_suffix(".srt")
    sidecar.write_text("<html>Bad subtitle</html>")
    episode = task(video, [])
    episode.savePathSubtitle = json.dumps([str(sidecar)])
    original = video.read_bytes()
    await manager._finalize_task(episode)
    assert episode.status == DownloadStatus.FAILED
    assert "fusion" in episode.error
    assert video.read_bytes() == original and sidecar.exists()
    assert not list(video.parent.glob(".animan-mux-*"))


@pytest.mark.parametrize("hardlinks", [True, False, "permission_denied", "android"])
def test_existing_mkv_is_preserved_and_new_export_gets_unique_name(video, monkeypatch, hardlinks):
    if hardlinks is not True:
        import errno
        import os
        def unsupported(*args):
            if hardlinks == "android":
                raise AssertionError("Android must reserve and rename instead of creating hard links")
            raise OSError(errno.EACCES if hardlinks == "permission_denied" else errno.EOPNOTSUPP, "Hard links unavailable")
        monkeypatch.setattr(os, "link", unsupported)
        if hardlinks == "android":
            from animan import media_tools
            monkeypatch.setattr(media_tools, "is_native", lambda: True)
            # Exercise the real mux/probe pipeline, isolating the storage policy
            # from the Android-only JNI implementation.
            monkeypatch.setattr(media_tools, "run", subprocess.run)
    target = video.with_suffix(".mkv")
    target.write_bytes(b"existing video")
    sidecar = video.with_suffix(".srt")
    sidecar.write_bytes(SRT)
    episode = task(video, [])
    episode.savePathSubtitle = json.dumps([str(sidecar)])
    manager._mux_subtitles_with_ffmpeg(episode)
    assert target.read_bytes() == b"existing video"
    assert Path(episode.savePath) != target
    assert any(stream["codec_type"] == "subtitle" for stream in streams(episode.savePath))
    assert not video.exists() and not sidecar.exists()


def test_normalize_rejects_invalid_structure():
    with pytest.raises(ValueError):
        normalize_subtitles({"url": "https://cdn.example/fr.srt"})


@pytest.mark.asyncio
async def test_imported_download_propagates_subtitle_list(tmp_path, isolated, monkeypatch):
    from animan.services.extension_service import extension_service
    from animan.services.extractors import extractor_registry
    episode = task(tmp_path / "episode.mp4", [])
    episode.source = "custom"
    episode.fileUrl = "https://player.example/embed/123"
    monkeypatch.setattr(extension_service, "get_container_source_by_id", lambda source: None)
    monkeypatch.setattr(extension_service, "get_enabled_container_sources", lambda: [])
    monkeypatch.setattr(extractor_registry, "is_known_embed", lambda url: True)
    monkeypatch.setattr(manager, "resolve_imported_video_stream", AsyncMock(return_value={
        "videoUrl": "https://cdn.example/episode.mp4", "serverType": "custom",
        "subtitles": [{"src": "/fr.srt", "srclang": "fr"}],
    }))
    downloader = AsyncMock()
    monkeypatch.setattr(manager, "_download_single_file", downloader)
    monkeypatch.setattr(manager, "process_queue", AsyncMock())
    await manager._execute_download(episode)
    assert downloader.await_count == 1
    track = json.loads(episode.subtitlesJson)[0]
    assert track["url"] == "https://player.example/fr.srt"
    assert track["lang"] == "fr"


def test_resume_does_not_hide_pending_subtitle_failure(tmp_path, isolated, monkeypatch):
    from animan.services.verification_service import VerificationResult
    video = tmp_path / "episode.mp4"
    video.write_bytes(b"x" * (1024 * 1024 + 1))
    episode = task(video, [{"url": "https://cdn.example/fr.srt"}])
    episode.status = DownloadStatus.FAILED
    episode.totalBytes = video.stat().st_size
    monkeypatch.setattr(manager, "tasks", {episode.id: episode})
    monkeypatch.setattr(manager, "_trigger_process_queue", lambda: None)
    monkeypatch.setattr(verification_service, "verify_file", lambda *args, **kwargs:
                        VerificationResult(valid=True, status="VALID"))
    assert manager.resume_download(episode.id)
    assert episode.status == DownloadStatus.PENDING


@pytest.mark.asyncio
async def test_successful_mux_is_not_repeated_on_resume(video, monkeypatch):
    episode = task(video, [{"url": "https://cdn.example/fr.srt", "lang": "fr"}])
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=SRT))
    await manager._download_subtitles(episode)
    manager._mux_subtitles_with_ffmpeg(episode)
    assert not manager._has_pending_subtitles(episode)
    def unexpected_request(**kwargs):
        pytest.fail("Already muxed subtitles must not be downloaded again")
    monkeypatch.setattr(manager, "_create_async_client", unexpected_request)
    await manager._download_subtitles(episode)
    assert len([s for s in streams(episode.savePath) if s["codec_type"] == "subtitle"]) == 1


@pytest.mark.asyncio
async def test_subtitle_timeout_retries_with_nonempty_error(tmp_path, isolated, monkeypatch):
    episode = task(tmp_path / "episode.mp4", [{"url": "https://cdn.example/fr.srt"}])
    requests = []
    def handler(request):
        requests.append(request)
        raise httpx.ReadTimeout("", request=request)
    mock_http(monkeypatch, handler)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    with pytest.raises(SubtitleError, match="Délai réseau dépassé après 3 tentatives"):
        await manager._download_subtitles(episode)
    assert len(requests) == 3


@pytest.mark.asyncio
async def test_partial_subtitles_are_cached_across_retries(tmp_path, isolated, monkeypatch):
    episode = task(tmp_path / "episode.mp4", [
        {"url": "https://cdn.example/fr.srt", "lang": "fr"},
        {"url": "https://cdn.example/en.srt", "lang": "en"}])
    first = True
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(503 if first and request.url.path == "/en.srt" else 200, content=SRT)
    mock_http(monkeypatch, handler)
    monkeypatch.setattr(asyncio, "sleep", AsyncMock())
    with pytest.raises(SubtitleError, match="HTTP 503"):
        await manager._download_subtitles(episode)
    assert len(json.loads(episode.savePathSubtitle)) == 1
    first = False
    seen.clear()
    await manager._download_subtitles(episode)
    assert seen == ["/en.srt"]
    assert len(json.loads(episode.savePathSubtitle)) == 2
    assert not list(tmp_path.glob(".animan-sub-*"))


@pytest.mark.asyncio
async def test_retry_finalizes_local_video_without_resolving_player(video, monkeypatch):
    episode = task(video, [{"url": "https://cdn.example/fr.srt", "lang": "fr"}])
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=SRT))
    await manager._download_subtitles(episode)
    monkeypatch.setattr(manager, "process_queue", AsyncMock())
    # The local fast path must work even with no remote video URL.
    await manager._execute_download(episode)
    assert episode.status == DownloadStatus.COMPLETED


@pytest.mark.asyncio
async def test_legacy_missing_mp4_recovers_verified_mkv(video, monkeypatch):
    episode = task(video, [{"url": "https://cdn.example/fr.srt", "lang": "fr"}])
    mock_http(monkeypatch, lambda request: httpx.Response(200, content=SRT))
    await manager._download_subtitles(episode)
    stale = task(video, json.loads(episode.subtitlesJson))
    manager._mux_subtitles_with_ffmpeg(episode)
    assert not video.exists()
    assert manager._recover_muxed_file(stale)
    assert stale.savePath == episode.savePath
    assert not manager._has_pending_subtitles(stale)
    incompatible = task(video, [{"url": "https://cdn.example/de.srt", "lang": "de", "label": "Allemand"}])
    assert not manager._recover_muxed_file(incompatible)


@pytest.mark.asyncio
async def test_expired_subtitle_url_is_refreshed_once_without_losing_metadata(video, monkeypatch):
    episode = task(video, [{"url": "https://cdn.example/expired.srt", "lang": "fr"}])
    episode.source = "custom"
    episode.fileUrl = "https://player.example/embed/123"
    seen = []
    def handler(request):
        seen.append(request.url.path)
        return httpx.Response(403 if request.url.path == "/expired.srt" else 200, content=SRT)
    mock_http(monkeypatch, handler)
    from animan.services.extension_service import extension_service
    from animan.services.extractors import extractor_registry
    monkeypatch.setattr(extension_service, "get_container_source_by_id", lambda source: None)
    monkeypatch.setattr(extension_service, "get_enabled_container_sources", lambda: [])
    monkeypatch.setattr(extractor_registry, "is_known_embed", lambda url: True)
    resolver = AsyncMock(return_value={"videoUrl": "https://cdn.example/episode.mp4", "serverType": "custom",
        "subtitles": [{"url": "https://cdn.example/fresh.srt", "lang": "fr"}]})
    monkeypatch.setattr(manager, "resolve_imported_video_stream", resolver)
    monkeypatch.setattr(manager, "process_queue", AsyncMock())
    await manager._execute_download(episode)
    assert episode.status == DownloadStatus.COMPLETED
    assert resolver.await_count == 1
    assert seen == ["/expired.srt", "/fresh.srt"]


def test_empty_reextraction_keeps_pending_subtitles(tmp_path):
    episode = task(tmp_path / "episode.mp4", [{"url": "https://cdn.example/fr.srt"}])
    manager._update_resolved_subtitles(episode, [], "https://cdn.example")
    assert len(json.loads(episode.subtitlesJson)) == 1
    assert manager._has_pending_subtitles(episode)
