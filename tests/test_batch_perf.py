import time
import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.database import init_db
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager
from animelab.services.library_service import library_service

@pytest.fixture(scope="module")
def client():
    init_db()
    with TestClient(app) as c:
        yield c

def test_save_tasks_batch():
    tasks = [
        DownloadTask(
            animeName="Batch Test Anime",
            episodeNumber=i,
            fileName=f"batch_test_ep{i}.mp4",
            fileUrl=f"https://example.com/ep{i}",
            savePath=f"/tmp/batch_test_ep{i}.mp4"
        )
        for i in range(1, 11)
    ]

    t0 = time.perf_counter()
    library_service.save_tasks_batch(tasks)
    elapsed = time.perf_counter() - t0

    # Batch save of 10 items should easily take less than 200ms
    assert elapsed < 0.2

    # Verify retrieval
    for t in tasks:
        entity = library_service.get_task_entity(t.id)
        assert entity is not None
        assert entity.animeName == "Batch Test Anime"
        assert entity.episodeNumber == t.episodeNumber

def test_start_batch_download_speed():
    episodes = [
        {
            "number": str(i),
            "url": f"https://example.com/stream/ep{i}.mp4",
            "fileName": f"Speed Test - Episode {i}.mp4"
        }
        for i in range(1, 21)
    ]

    t0 = time.perf_counter()
    started = download_manager.start_batch_download("Speed Test Anime", episodes)
    elapsed = time.perf_counter() - t0

    assert len(started) == 20
    # Batch add in memory + 1 DB transaction must be extremely fast (< 250ms)
    assert elapsed < 0.25

    # Check tasks in download_manager
    for task in started:
        assert task.id in download_manager.tasks
        assert task.status in [DownloadStatus.PENDING, DownloadStatus.DOWNLOADING]

def test_api_download_batch_endpoint(client):
    episodes = [
        {
            "number": str(i),
            "url": f"https://example.com/stream/api_batch_{i}.mp4",
            "fileName": f"API Batch Anime - Episode {i}.mp4"
        }
        for i in range(1, 6)
    ]

    resp = client.post("/api/download/batch", json={
        "animeName": "API Batch Anime",
        "episodes": episodes
    })

    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] == 5

def test_cancel_all_downloads():
    episodes = [
        {
            "number": str(i),
            "url": f"https://example.com/stream/cancel_test_{i}.mp4",
            "fileName": f"Cancel Test Anime - Episode {i}.mp4"
        }
        for i in range(1, 4)
    ]
    started = download_manager.start_batch_download("Cancel Test Anime", episodes)
    assert len(started) == 3

    cancelled_count = download_manager.cancel_all_downloads()
    assert cancelled_count >= 3

    for task in started:
        assert task.status == DownloadStatus.CANCELLED
        assert task.cancelled is True

def test_api_cancel_all_endpoint(client):
    episodes = [
        {
            "number": str(i),
            "url": f"https://example.com/stream/api_cancel_{i}.mp4",
            "fileName": f"API Cancel Anime - Episode {i}.mp4"
        }
        for i in range(1, 3)
    ]
    client.post("/api/download/batch", json={
        "animeName": "API Cancel Anime",
        "episodes": episodes
    })

    resp = client.post("/api/download/cancel-all")
    assert resp.status_code == 200
    data = resp.json()
    assert data["success"] is True
    assert data["count"] >= 2

