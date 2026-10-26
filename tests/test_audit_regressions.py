from animelab.services.extension_service import extension_service
from animelab.services.scraping_service import scraping_service
"""Regressions for progress, episode identity, byte ranges and proxy redirects."""
import importlib
import socket
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest
from fastapi import HTTPException
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from animelab.database import Base
from animelab.models.anime import AnimeDetail, Episode
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.routers import anime, download, library, media
from animelab.services.library_service import library_service

library_module = importlib.import_module("animelab.services.library_service")


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    engine = create_engine(f"sqlite:///{tmp_path / 'regressions.db'}")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(library_module, "SessionLocal", sessionmaker(bind=engine))
    yield
    engine.dispose()


def request(body=None, method="GET"):
    return SimpleNamespace(json=AsyncMock(return_value=body or {}), method=method)


@pytest.mark.asyncio
async def test_unwatch_persists_and_clears_timestamp(isolated_db):
    body = {"animeUrl": "https://example.com/anime", "episodeNumber": 1, "version": "VF"}
    await library.mark_watched(request(body))  # Legacy callers still mark as watched.
    await library.mark_watched(request({**body, "watched": False}))
    progress = library_service.get_progress_for_anime(body["animeUrl"])[0]
    assert progress.watched is False
    assert progress.watchedAt is None
    assert library_service.get_watched_episodes_set(body["animeUrl"]) == set()


@pytest.mark.asyncio
async def test_unwatch_rejects_string_boolean(isolated_db):
    result = await library.mark_watched(request({"animeUrl": "x", "watched": "false"}))
    assert result.status_code == 400


@pytest.mark.asyncio
@pytest.mark.parametrize("version", ["", "VF", "VOSTFR"])
async def test_detail_restores_progress_flags(isolated_db, version):
    url = "https://example.com/anime"
    library_service.mark_as_downloaded(url, "Test", 1, version)
    library_service.mark_as_watched(url, "Test", 1, version)
    detail = AnimeDetail(title="Test", url=url, version=version,
                         episodes=[Episode(number=1, title="One", version=version)])
    with patch.object(anime, "is_safe_url", return_value=True), \
         patch.object(scraping_service, "get_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(anime.tmdb_service, "enrich_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None):
        result = await anime.fetch_enriched_anime_detail(url)
    assert result["anime"]["episodes"][0]["isDownloaded"] is True
    assert result["anime"]["episodes"][0]["isWatched"] is True
    assert result["downloadedCount"] == result["watchedCount"] == 1


def test_local_episode_requires_matching_url(isolated_db, tmp_path):
    video = tmp_path / "vf.mp4"
    video.write_bytes(b"VF video")
    task = DownloadTask(animeName="Same Title", episodeNumber=1, fileName=video.name,
                        savePath=str(video), downloadPageUrl="https://example.com/vf/1",
                        status=DownloadStatus.COMPLETED)
    library_service.save_task(task)
    assert library_service.find_downloaded_episode(
        "Same Title", 1, version="VOSTFR", episode_url="https://example.com/vostfr/1") is None
    assert library_service.find_downloaded_episode("Same Title", 1, version="VOSTFR") is None
    assert library_service.find_downloaded_episode(
        "Different display title", 1, version="VF", episode_url=task.downloadPageUrl).id == task.id
    video.unlink()
    assert library_service.find_downloaded_episode(
        "Same Title", 1, episode_url=task.downloadPageUrl) is None


@pytest.mark.asyncio
async def test_specific_unwatch_overrides_legacy_progress(isolated_db):
    url = "https://example.com/anime"
    library_service.mark_as_watched(url, "Test", 1, "")
    library_service.mark_as_watched(url, "Test", 1, "VOSTFR", watched=False)
    detail = AnimeDetail(title="Test", url=url, episodes=[
        Episode(number=1, title="One VF", version="VF"),
        Episode(number=1, title="One VOSTFR", version="VOSTFR"),
    ])
    with patch.object(anime, "is_safe_url", return_value=True), \
         patch.object(scraping_service, "get_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(anime.tmdb_service, "enrich_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None):
        result = await anime.fetch_enriched_anime_detail(url)
    assert result["anime"]["episodes"][0]["isWatched"] is True
    assert result["anime"]["episodes"][1]["isWatched"] is False


@pytest.mark.asyncio
async def test_batch_preferences_and_episode_overrides():
    body = {"animeName": "Test", "preferredQuality": "1080p", "preferredServer": "Sibnet",
            "episodes": [{"number": 1, "url": "https://example.com/1"},
                         {"number": 2, "url": "https://example.com/2",
                          "selectedQuality": "720p", "selectedServer": "VOE"}]}
    with patch.object(download.download_manager, "start_batch_download", return_value=[]) as start:
        await download.start_batch_download(request(body))
    first, second = start.call_args.args[1]
    assert (first["selectedQuality"], first["selectedServer"]) == ("1080p", "Sibnet")
    assert (second["selectedQuality"], second["selectedServer"]) == ("720p", "VOE")


@pytest.mark.asyncio
@pytest.mark.parametrize("header, status, expected", [
    ("bytes=-5", 206, b"56789"), ("bytes=-100", 206, b"0123456789"),
    ("bytes=0-99999", 206, b"0123456789"), ("bytes=5-", 206, b"56789"),
    ("bytes=2-4", 206, b"234"), ("bytes=-0", 416, None),
    ("bytes=10-", 416, None), ("bytes=5-3", 416, None),
    ("bytes=-", 416, None), ("bytes=abc", 416, None),
])
async def test_local_video_ranges(tmp_path, header, status, expected):
    video = tmp_path / "video.mp4"
    video.write_bytes(b"0123456789")
    task = DownloadTask(animeName="Test", fileName=video.name, savePath=str(video))
    with patch.object(media.download_manager, "get_task", return_value=task):
        result = await media.stream_video(task.id, request(), range=header)
    assert result.status_code == status
    if expected is not None:
        assert b"".join([chunk async for chunk in result.body_iterator]) == expected
        assert int(result.headers["content-length"]) == len(expected)
    else:
        assert result.headers["content-range"] == "bytes */10"


@pytest.mark.asyncio
@pytest.mark.parametrize("method", ["GET", "HEAD"])
@pytest.mark.parametrize('shared', [False, True])
@pytest.mark.parametrize("destination, blocked", [
    ("http://127.0.0.1/private", True), ("http://169.254.169.254/metadata", True),
    ("http://10.0.0.1/private", True), ("https://cdn.example/video.mp4", False),
])
async def test_proxy_validates_redirects(method, destination, blocked, shared, monkeypatch):
    if shared:
        monkeypatch.setenv('ANIMELAB_SHARED_WORKER', '1')
        monkeypatch.setenv('ANIMELAB_SHARED_DOWNLOAD', '0')
        monkeypatch.setenv('ANIMELAB_MEDIA_DOMAINS', 'public.example,cdn.example')
    visited = []
    clients = []
    real_client = httpx.AsyncClient

    def upstream(req):
        visited.append(str(req.url))
        if req.url.host == "public.example":
            return httpx.Response(302, headers={"location": destination})
        return httpx.Response(200, content=b"video")

    def factory(**kwargs):
        # The source facade enforces this sync policy itself. HTTPX uses the
        # request hook below for the same per-redirect destination validation.
        kwargs.pop('url_validator', None)
        client = real_client(**kwargs, transport=httpx.MockTransport(upstream), trust_env=False)
        clients.append(client)
        return client

    public_dns = [(socket.AF_INET, socket.SOCK_STREAM, 6, "", ("93.184.216.34", 0))]
    with patch("socket.getaddrinfo", return_value=public_dns), \
         patch.object(media.source_http, "async_client", side_effect=factory), \
         patch.object(media.proxy_service, "get_active_proxy", return_value=None):
        if blocked:
            with pytest.raises(HTTPException) as error:
                await media.stream_proxy(request(method=method), url="https://public.example/video",
                                         server=None, referer=None, range=None)
            assert error.value.status_code == 400
            assert visited == ["https://public.example/video"]
        else:
            result = await media.stream_proxy(request(method=method), url="https://public.example/video",
                                              server=None, referer=None, range=None)
            assert result.status_code == 200
            if method == "GET":
                assert b"".join([chunk async for chunk in result.body_iterator]) == b"video"
            assert visited[-1] == destination
    assert all(client.is_closed for client in clients)
