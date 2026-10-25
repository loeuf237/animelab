import pytest
import os
import tempfile
from pathlib import Path
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager

@pytest.mark.asyncio
async def test_html_response_rejection(tmp_path, monkeypatch):
    """Vérifie que _download_single_file rejette immédiatement un contenu HTML."""
    task = DownloadTask(
        animeName="Test Anime",
        episodeNumber=1,
        fileName="test_ep1.mp4",
        fileUrl="https://example.com/test",
        savePath=str(tmp_path / "test_ep1.mp4"),
    )
    import httpx
    monkeypatch.setattr(download_manager, '_create_async_client', lambda **kwargs:
        httpx.AsyncClient(transport=httpx.MockTransport(lambda request:
            httpx.Response(200, text='<html>web page</html>', headers={'content-type':'text/html'})), trust_env=False))
    with pytest.raises(Exception) as excinfo:
        await download_manager._download_single_file(task, "https://example.com")
    
    assert "html" in str(excinfo.value).lower()
    # S'assurer que le fichier final n'a PAS été créé avec du HTML
    assert not (tmp_path / "test_ep1.mp4").exists()

def test_redownload_preserves_healthy_part(tmp_path):
    """Vérifie que redownload_task ne détruit pas un fichier .part binaire sain."""
    target = tmp_path / "healthy.mp4"
    part = tmp_path / "healthy.mp4.part"
    
    # Créer un fichier partiel binaire de 50 Ko (non-HTML)
    with open(part, "wb") as f:
        f.write(b"\x00\x00\x00\x20ftypmp42" + b"\x00" * 50000)
    
    task = DownloadTask(
        id="test-healthy-task-1",
        animeName="Healthy Anime",
        episodeNumber=1,
        fileName="healthy.mp4",
        fileUrl="https://example.com/stream",
        savePath=str(target),
        status=DownloadStatus.FAILED,
        downloadedBytes=50032,
        totalBytes=100000,
    )
    download_manager.tasks[task.id] = task
    
    try:
        # Relancer la tâche
        res = download_manager.redownload_task(task.id, force=False)
        
        # Le fichier .part doit être conservé intact !
        assert part.exists()
        assert part.stat().st_size == 50012
        assert res.downloadedBytes == 50012
    finally:
        download_manager.remove_task(task.id)

def test_redownload_purges_corrupted_html(tmp_path):
    """Vérifie que redownload_task purge un fichier HTML corrompu."""
    target = tmp_path / "corrupted.mp4"
    with open(target, "wb") as f:
        f.write(b"<!doctype html><html><head><title>Error</title></head></html>")
    
    task = DownloadTask(
        id="test-corrupted-task-1",
        animeName="Corrupted Anime",
        episodeNumber=1,
        fileName="corrupted.mp4",
        fileUrl="https://example.com/stream",
        savePath=str(target),
        status=DownloadStatus.FAILED,
    )
    download_manager.tasks[task.id] = task
    
    try:
        res = download_manager.redownload_task(task.id, force=False)
        
        # Le fichier HTML corrompu doit être purgé
        assert not target.exists()
        assert res.downloadedBytes == 0
        assert res.progress == 0.0
    finally:
        download_manager.remove_task(task.id)

def test_speed_tracker_smoothing_and_decay():
    """Vérifie que SpeedTracker lisse les arrivées par paquets HLS et ne chute pas à 0 B/s."""
    from animelab.models.download_task import SpeedTracker

    tracker = SpeedTracker(window_seconds=3.0)
    t0 = 1000.0

    # Échantillon initial
    tracker.add_sample(0, now=t0)

    # Chunk 1 de 2 Mo à t = 1.5s
    sp1 = tracker.add_sample(2_000_000, now=t0 + 1.5)
    assert sp1 > 1_000_000  # ~1.33 Mo/s

    # Ligne de flush ffmpeg répétée à la même taille à t = 1.8s
    sp2 = tracker.add_sample(2_000_000, now=t0 + 1.8)
    assert sp2 > 1_000_000  # Ne chute PAS à 0 B/s !

    # Consultation intermédiaire à t = 2.5s pendant que ffmpeg télécharge le chunk suivant
    sp_mid = tracker.get_speed(now=t0 + 2.5)
    assert sp_mid > 700_000  # Débit maintenu

    # Chunk 2 de 2 Mo supplémentaire à t = 3.0s
    sp3 = tracker.add_sample(4_000_000, now=t0 + 3.0)
    assert sp3 > 1_000_000

    # Arrêt prolongé du réseau à t = 8.0s (au-delà de window_seconds)
    sp_stall = tracker.get_speed(now=t0 + 8.0)
    assert sp_stall == 0  # Décroissance propre à 0 B/s si coupure avérée

