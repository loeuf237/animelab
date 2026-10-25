import asyncio
import importlib
from types import SimpleNamespace

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from animelab import platform_events
from animelab.database import Base
from animelab.models.anime import AnimeDetail, Episode
from animelab.models.auto_download import AutoDownloadEpisode
from animelab.models.download_task import DownloadStatus
from animelab.services.download_manager import DownloadManagerService
from animelab.services.library_service import library_service
from animelab.services.source_catalogue import source_catalogue
from animelab.services.watchdog_service import WatchdogService

library_module = importlib.import_module("animelab.services.library_service")
watchdog_module = importlib.import_module("animelab.services.watchdog_service")


@pytest.fixture
def tracking(monkeypatch, tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'tracking.sqlite'}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(library_module, "SessionLocal", sessions)
    manager = DownloadManagerService()
    manager.download_dir = str(tmp_path / "downloads")
    monkeypatch.setattr(manager, "_trigger_process_queue", lambda: None)
    monkeypatch.setattr(manager, "broadcast_update", lambda task: None)
    monkeypatch.setattr(watchdog_module, "download_manager", manager)
    monkeypatch.setattr(platform_events, "storage_status_handler", None)
    monkeypatch.setattr(platform_events, "completed_handler", None)
    yield manager, sessions
    engine.dispose()


def favorite(source="animepahe", version="VF", **options):
    fav = library_service.add_favorite("https://example.com/series", "Series", source=source)
    return library_service.update_auto_download(fav.url, True, autoDownloadVersion=version, **options)


def catalogue(monkeypatch, episodes):
    detail = AnimeDetail(title="Series", url="https://example.com/series", episodes=episodes)
    calls = []
    async def get_detail(url):
        calls.append(url)
        return detail
    def provider(source):
        calls.append(source)
        return SimpleNamespace(get_anime_detail=get_detail)
    monkeypatch.setattr(source_catalogue, "provider", provider)
    return detail, calls


def episode(number, version):
    return Episode(number=number, title=f"Episode {number}", version=version,
                   downloadPageUrl=f"https://example.com/episode/{number}/{version}",
                   subtitleUrl="https://example.com/subtitle.vtt")


@pytest.mark.asyncio
@pytest.mark.parametrize("source", ["french-manga", "voir-anime", "animepahe", "imported.extension"])
async def test_every_source_and_exact_variant_use_the_catalogue_registry(tracking, monkeypatch, source):
    manager, sessions = tracking
    fav = favorite(source, "vf", autoDownloadSubtitles=True, autoDownloadQuality="720p", autoDownloadServer="Sibnet")
    _, calls = catalogue(monkeypatch, [episode(7, "VF"), episode(7, "VOSTFR"), episode(7, "VF")])
    assert await WatchdogService().check_new_episodes() == 1
    task, = manager.tasks.values()
    assert calls[0] == source
    assert (task.source, task.animeUrl, task.episodeNumber, task.version) == (source, fav.url, 7, "VF")
    assert task.downloadSubtitles and task.selectedServer == "Sibnet" and task.selectedQuality == "720p"
    assert "[VF]" in task.fileName
    # New watchdog instance / persisted discovery cannot queue this episode twice.
    assert await WatchdogService().check_new_episodes() == 0
    persisted = library_service.get_task_entity(task.id).to_task()
    assert persisted.selectedServer == "Sibnet" and persisted.selectedQuality == "720p"


@pytest.mark.asyncio
async def test_a_later_variant_of_the_same_number_is_not_lost(tracking, monkeypatch):
    manager, sessions = tracking
    favorite(version="*")
    detail, _ = catalogue(monkeypatch, [episode(12, "VOSTFR")])
    assert await WatchdogService().check_new_episodes() == 1
    detail.episodes.append(episode(12, "VF"))
    assert await WatchdogService().check_new_episodes() == 1
    assert {task.version for task in manager.tasks.values()} == {"VF", "VOSTFR"}
    assert await WatchdogService().check_new_episodes() == 0


@pytest.mark.asyncio
async def test_changing_tracking_version_does_not_backfill_previously_ignored_episodes(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite(version="VF")
    detail, _ = catalogue(monkeypatch, [episode(1, "VF"), episode(1, "VOSTFR")])
    assert await WatchdogService().check_new_episodes() == 1
    library_service.update_auto_download(fav.url, True, autoDownloadVersion="VOSTFR")
    assert await WatchdogService().check_new_episodes() == 0
    detail.episodes.append(episode(2, "VOSTFR"))
    assert await WatchdogService().check_new_episodes() == 1
    assert {(task.episodeNumber, task.version) for task in manager.tasks.values()} == {(1, "VF"), (2, "VOSTFR")}


@pytest.mark.asyncio
async def test_disabling_tracking_while_a_source_loads_prevents_queue_creation(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite()
    async def detail(url):
        library_service.update_auto_download(url, False)
        return AnimeDetail(title="Series", url=url, episodes=[episode(3, "VF")])
    monkeypatch.setattr(source_catalogue, "provider", lambda source: SimpleNamespace(get_anime_detail=detail))
    assert await WatchdogService().check_new_episodes() == 0
    assert not manager.tasks
    assert library_service.get_favorite(fav.url).lastKnownEpisode == 0


@pytest.mark.asyncio
async def test_ambiguous_tracking_requires_a_choice_instead_of_downloading_both(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite(version="")
    catalogue(monkeypatch, [episode(1, "VF"), episode(1, "VOSTFR")])
    assert await WatchdogService().check_new_episodes() == 0
    assert not manager.tasks
    assert "version" in library_service.get_favorite(fav.url).autoDownloadError
    library_service.update_auto_download(fav.url, True, autoDownloadVersion="VOSTFR")
    assert await WatchdogService().check_new_episodes() == 1
    assert {task.version for task in manager.tasks.values()} == {"VOSTFR"}


@pytest.mark.asyncio
async def test_queue_failure_keeps_discovery_and_transfer_failure_keeps_one_task(tracking, monkeypatch):
    manager, sessions = tracking
    fav = favorite()
    catalogue(monkeypatch, [episode(5, "VF")])
    original = manager.start_download
    def fail(**kwargs):
        raise OSError("Queue storage temporarily unavailable")
    monkeypatch.setattr(manager, "start_download", fail)
    assert await WatchdogService().check_new_episodes() == 0
    with sessions() as db:
        assert db.query(AutoDownloadEpisode).one().state == "DISCOVERED"
    assert library_service.get_favorite(fav.url).lastKnownEpisode == 5
    monkeypatch.setattr(manager, "start_download", original)
    assert await WatchdogService().check_new_episodes() == 1
    task, = manager.tasks.values()
    task.status = DownloadStatus.FAILED
    library_service.save_task(task)
    assert await WatchdogService().check_new_episodes() == 0
    with sessions() as db:
        record = db.query(AutoDownloadEpisode).one()
        assert record.state == "FAILED" and record.taskId == task.id
    # The failed task is visible and retryable rather than silently discarded or duplicated.
    assert library_service.get_task_entity(task.id).status == "FAILED"
    task.status = DownloadStatus.PENDING
    library_service.save_task(task)
    with sessions() as db:
        assert db.query(AutoDownloadEpisode).one().state == "PLANNED"
    assert await WatchdogService().check_new_episodes() == 0


@pytest.mark.asyncio
async def test_legacy_cursor_is_only_an_initial_baseline(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite(version="*")
    library_service.update_last_known_episode(fav.url, 10)
    detail, _ = catalogue(monkeypatch, [episode(9, "VF"), episode(10, "VF"), episode(11, "VF")])
    assert await WatchdogService().check_new_episodes() == 1
    assert {t.episodeNumber for t in manager.tasks.values()} == {11}
    detail.episodes.append(episode(10, "VOSTFR"))
    assert await WatchdogService().check_new_episodes() == 1
    assert {(t.episodeNumber, t.version) for t in manager.tasks.values()} == {(11, "VF"), (10, "VOSTFR")}


@pytest.mark.asyncio
async def test_existing_manual_task_and_simultaneous_checks_do_not_duplicate(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite()
    catalogue(monkeypatch, [episode(1, "VF")])
    task = manager.start_download(anime_name="Series", episode_number=1,
        download_page_url=episode(1, "VF").downloadPageUrl, file_name="Episode.mp4",
        source=fav.source, anime_url=fav.url, version="VF")
    watchdog = WatchdogService()
    assert sum(await asyncio.gather(watchdog.check_new_episodes(), watchdog.check_new_episodes())) == 0
    assert list(manager.tasks) == [task.id]


@pytest.mark.asyncio
async def test_unknown_or_disabled_source_never_falls_back_to_french_manga(tracking, monkeypatch):
    manager, _ = tracking
    fav = favorite("disabled.extension")
    def missing(source):
        raise ValueError("Source disabled")
    monkeypatch.setattr(source_catalogue, "provider", missing)
    assert await WatchdogService().check_new_episodes() == 0
    assert not manager.tasks
    assert library_service.get_favorite(fav.url).autoDownloadError == "Source disabled"
