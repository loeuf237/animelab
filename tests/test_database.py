import pytest
from animelab.database import init_db
from animelab.services.library_service import library_service
from animelab.models.download_task import DownloadTask, DownloadStatus

@pytest.fixture(autouse=True)
def setup_db():
    init_db()

def test_favorites_crud():
    url = "https://example.com/anime/test-anime"
    title = "Test Anime Title"

    # Add favorite
    fav = library_service.add_favorite(url, title, image_url="https://img.jpg", source="french-manga")
    assert fav.id is not None
    assert fav.url == url
    assert fav.title == title
    assert library_service.is_favorite(url) is True

    # Toggle auto-download
    updated = library_service.update_auto_download(url, True)
    assert updated.autoDownload is True

    # Update last known episode
    library_service.update_last_known_episode(url, 12)
    favs = library_service.get_all_favorites()
    found = next((f for f in favs if f.url == url), None)
    assert found is not None
    assert found.lastKnownEpisode == 12

    # Remove favorite
    library_service.remove_favorite(url)
    assert library_service.is_favorite(url) is False

def test_watch_progress():
    url = "https://example.com/anime/naruto"
    prog = library_service.mark_as_downloaded(url, "Naruto", 1, "VOSTFR")
    assert prog.downloaded is True

    watched = library_service.mark_as_watched(url, "Naruto", 1, "VOSTFR")
    assert watched.watched is True

    dl_set = library_service.get_downloaded_episodes_set(url)
    assert "1-VOSTFR" in dl_set

    w_set = library_service.get_watched_episodes_set(url)
    assert "1-VOSTFR" in w_set

def test_download_task_persistence():
    task = DownloadTask(
        animeName="One Piece",
        episodeNumber=1000,
        fileName="One Piece - Episode 1000.mp4",
        status=DownloadStatus.PENDING,
        totalBytes=500000000,
    )
    library_service.save_task(task)

    entity = library_service.get_task_entity(task.id)
    assert entity is not None
    assert entity.animeName == "One Piece"
    assert entity.episodeNumber == 1000
    assert entity.status == "PENDING"

    # Update status
    task.status = DownloadStatus.COMPLETED
    task.progress = 100.0
    library_service.save_task(task)

    updated_entity = library_service.get_task_entity(task.id)
    assert updated_entity.status == "COMPLETED"
    assert updated_entity.progress == 100.0

    # Cleanup
    library_service.delete_task_entity(task.id)
    assert library_service.get_task_entity(task.id) is None
