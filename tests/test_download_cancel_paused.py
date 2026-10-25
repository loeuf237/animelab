import pytest
from fastapi.testclient import TestClient
from run import app
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager
from animelab.services.library_service import library_service

@pytest.fixture
def client():
    return TestClient(app)

def test_cancel_paused_task(client):
    """Vérifie qu'un téléchargement à l'état PAUSED peut être annulé via DELETE /api/download/{id}."""
    task = DownloadTask(
        id="test-paused-cancel-task",
        animeName="Paused Anime",
        episodeNumber=1,
        fileName="paused.mp4",
        status=DownloadStatus.PAUSED,
    )
    download_manager.tasks[task.id] = task
    library_service.save_task(task)

    try:
        # Appel DELETE pour annuler
        res = client.delete(f"/api/download/{task.id}")
        assert res.status_code == 200, res.text
        data = res.json()
        assert data.get("success") is True

        # Vérifier que la tâche est bien marquée CANCELLED
        updated = download_manager.tasks.get(task.id)
        assert updated is not None
        assert updated.status == DownloadStatus.CANCELLED
    finally:
        download_manager.remove_task(task.id)

def test_remove_task_purges_db_and_memory(client):
    """Vérifie que /api/download/{id}/remove supprime la tâche de la mémoire et de SQLite."""
    task = DownloadTask(
        id="test-purge-remove-task",
        animeName="Purge Anime",
        episodeNumber=1,
        fileName="purge.mp4",
        status=DownloadStatus.FAILED,
    )
    download_manager.tasks[task.id] = task
    library_service.save_task(task)

    # Vérifier présence en DB
    entity = library_service.get_task_entity(task.id)
    assert entity is not None

    # Supprimer
    res = client.delete(f"/api/download/{task.id}/remove")
    assert res.status_code == 200, res.text

    # Vérifier absence en mémoire et en DB
    assert task.id not in download_manager.tasks
    assert library_service.get_task_entity(task.id) is None

def test_cancel_endpoint_fallback_to_remove(client):
    """Vérifie que DELETE /api/download/{id} supprime une tâche déjà annulée ou introuvable en mémoire mais présente en DB."""
    task = DownloadTask(
        id="test-cancelled-remove-fallback",
        animeName="Cancelled Anime",
        episodeNumber=1,
        fileName="cancelled.mp4",
        status=DownloadStatus.CANCELLED,
    )
    # Présente uniquement en DB
    library_service.save_task(task)
    download_manager.tasks.pop(task.id, None)

    res = client.delete(f"/api/download/{task.id}")
    assert res.status_code == 200, res.text
    assert library_service.get_task_entity(task.id) is None
