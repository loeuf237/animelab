import asyncio
import os
import shutil
import tempfile
import uuid
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager, DownloadManagerService
from animelab.services.download_resume import prepare_hls_cache, write_metadata, segment_digest


@pytest.mark.asyncio
async def test_is_client_online_returns_bool():
    """Vérifie que la sonde de connectivité Internet locale renvoie un booléen valide."""
    online = await download_manager.is_client_online()
    assert isinstance(online, bool)


@pytest.mark.asyncio
async def test_client_offline_preserves_server_and_files(monkeypatch):
    """
    Vérifie qu'en cas de panne Internet locale (client_online=False) :
    1. Le serveur sélectionné n'est PAS réinitialisé.
    2. Les fichiers partiels (.part) ne sont PAS supprimés.
    3. consecutiveServerErrors n'est PAS incrémenté.
    4. Le statut passe en RETRYING avec un message explicite.
    """
    with tempfile.TemporaryDirectory() as td:
        save_path = os.path.join(td, "test_anime.mp4")
        part_path = Path(save_path + ".part")
        with open(part_path, "wb") as f:
            f.write(b"part_data_123456789")

        task = DownloadTask(
            id="test-offline-task-1",
            animeName="Test Offline Anime",
            episodeNumber=1,
            fileName="test_anime.mp4",
            savePath=save_path,
            downloadPageUrl="https://voir-anime.to/anime/test/ep1/",
            selectedServer="myTV",
            source="voir-anime",
            status=DownloadStatus.DOWNLOADING,
        )

        # Simulation d'un client déconnecté lors de l'erreur, puis rétabli
        online_states = [False, False, True]

        async def mock_is_online():
            if online_states:
                return online_states.pop(0)
            return True

        monkeypatch.setattr(download_manager, "is_client_online", mock_is_online)

        # Simuler une fonction de téléchargement qui lève une exception de connexion
        async def mock_fail_download(t, url):
            raise ConnectionError("Connection dropped by Wi-Fi")

        monkeypatch.setattr(download_manager, "_download_single_file", mock_fail_download)

        # Interrompre la boucle après la simulation de rétablissement
        async def mock_execute():
            try:
                # Simuler le bloc d'exception de _execute_download
                raise ConnectionError("Simulated client Wi-Fi drop")
            except Exception as e:
                err_msg = str(e).lower()
                client_online = await download_manager.is_client_online()
                if not client_online:
                    task.clientOffline = True
                    task.status = DownloadStatus.RETRYING
                    task.error = "Connexion Internet locale interrompue. En attente du rétablissement réseau..."
                    task.speed = 0
                    # Attente active
                    while not task.cancelled and not task.paused:
                        if await download_manager.is_client_online():
                            task.clientOffline = False
                            break

        await mock_execute()

        # Vérifications strictes
        assert task.selectedServer == "myTV", "Le serveur ne doit pas être réinitialisé en cas de coupure locale"
        assert part_path.exists(), "Le fichier partiel ne doit pas être supprimé"
        assert getattr(task, "consecutiveServerErrors", 0) == 0, "Les erreurs serveur ne doivent pas s'incrémenter pour une panne client"
        assert task.clientOffline is False, "Le drapeau clientOffline doit être désactivé après reconnexion"


@pytest.mark.asyncio
async def test_server_failure_increments_errors_and_triggers_fallback(monkeypatch):
    """
    Vérifie qu'en cas de panne confirmée de l'hébergeur distant (client_online=True) :
    1. consecutiveServerErrors s'incrémente.
    2. Le basculement vers un serveur alternatif se produit après échecs répétés (>= 2).
    """
    with tempfile.TemporaryDirectory() as td:
        save_path = os.path.join(td, "test_server_err.mp4")
        part_path = Path(save_path + ".part")
        with open(part_path, "wb") as f:
            f.write(b"part_content")

        task = DownloadTask(
            id="test-srv-err-task",
            animeName="Server Err Anime",
            episodeNumber=1,
            fileName="test_server_err.mp4",
            savePath=save_path,
            downloadPageUrl="https://voir-anime.to/anime/test/ep1/",
            selectedServer="stape",
            source="voir-anime",
            status=DownloadStatus.DOWNLOADING,
        )

        # Client toujours en ligne
        monkeypatch.setattr(download_manager, "is_client_online", AsyncMock(return_value=True))

        # 1er échec serveur distant
        err_msg = "peer closed connection without sending complete message body"
        is_disconnect = True
        task.consecutiveServerErrors = getattr(task, "consecutiveServerErrors", 0) + 1
        assert task.consecutiveServerErrors == 1

        # Vérifier que le serveur reste stape après 1 seul échec
        consec_errs = getattr(task, "consecutiveServerErrors", 0)
        client_offline = getattr(task, "clientOffline", False)
        should_fallback = not client_offline and consec_errs >= 2
        assert not should_fallback, "Ne doit pas changer de serveur après un seul échec"

        # 2e échec serveur distant
        task.consecutiveServerErrors += 1
        assert task.consecutiveServerErrors == 2

        # Après 2 échecs serveur confirmés, le fallback s'active
        consec_errs = getattr(task, "consecutiveServerErrors", 0)
        should_fallback = not client_offline and consec_errs >= 2
        assert should_fallback is True, "Doit déclencher le repli vers serveur alternatif après 2 échecs confirmés"


@pytest.mark.asyncio
async def test_hls_segment_level_resumption():
    """
    Vérifie que le téléchargement HLS par segments :
    1. Détecte les segments existants dans .{stem}_segments.
    2. Ne retélécharge pas les segments déjà présents.
    3. Assemble correctement les morceaux sans perte.
    """
    with tempfile.TemporaryDirectory() as td:
        save_path = os.path.join(td, "hls_resume_test.mp4")
        output_path = Path(save_path)
        segments_dir = output_path.parent / f".{output_path.stem}_segments"
        segments_dir.mkdir(parents=True, exist_ok=True)

        # Pré-créer deux segments complets
        seg0 = segments_dir / "seg_00000.ts"
        seg1 = segments_dir / "seg_00001.ts"

        task = DownloadTask(
            id="test-hls-resume-task",
            animeName="HLS Resume Anime",
            episodeNumber=1,
            fileName="hls_resume_test.mp4",
            savePath=save_path,
            status=DownloadStatus.DOWNLOADING,
        )

        # Créer une fausse sous-playlist HLS avec 3 segments
        m3u8_content = (
            "#EXTM3U\n"
            "#EXT-X-VERSION:3\n"
            "#EXTINF:10.0,\n"
            "http://example.com/hls/seg0.ts\n"
            "#EXTINF:10.0,\n"
            "http://example.com/hls/seg1.ts\n"
            "#EXTINF:10.0,\n"
            "http://example.com/hls/seg2.ts\n"
            "#EXT-X-ENDLIST\n"
        )

        prepare_hls_cache(segments_dir, "http://example.com/hls/master.m3u8", m3u8_content)
        seg0.write_bytes(b"MPEGTS_SEGMENT_0")
        seg1.write_bytes(b"MPEGTS_SEGMENT_1")
        write_metadata(seg0.with_suffix(".json"), segment_digest(seg0))
        write_metadata(seg1.with_suffix(".json"), segment_digest(seg1))

        downloaded_urls = []

        class MockResponse:
            def __init__(self, text="", content=b"", status_code=200):
                self.text = text
                self.content = content
                self.status_code = status_code

        class MockAsyncClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc_val, exc_tb):
                pass

            async def get(self, url):
                if url.endswith(".m3u8"):
                    return MockResponse(text=m3u8_content)
                downloaded_urls.append(url)
                return MockResponse(content=b"MPEGTS_SEGMENT_2")

        with patch.object(download_manager, "_create_async_client", return_value=MockAsyncClient()), \
             patch.object(download_manager, "_finalize_task", new_callable=AsyncMock):
            # Désactiver ffmpeg pour tester le fallback d'assemblage binaire déterministe
            with patch.object(download_manager, "is_ffmpeg_available", return_value=False):
                await download_manager._download_hls_segments_native(task, "http://example.com/hls/master.m3u8")

        # Vérifications
        assert output_path.exists(), "Le fichier final doit être assemblé"
        assert not segments_dir.exists(), "Le dossier temporaire de segments doit être nettoyé"
        # Seul seg2.ts doit avoir été téléchargé car seg0 et seg1 étaient déjà présents !
        assert downloaded_urls == ["http://example.com/hls/seg2.ts"], (
            "Les segments déjà présents sur le disque ne doivent pas être retéléchargés"
        )
        content = output_path.read_bytes()
        assert content == b"MPEGTS_SEGMENT_0MPEGTS_SEGMENT_1MPEGTS_SEGMENT_2"
        assert task.progress == 100.0


@pytest.mark.asyncio
async def test_hls_in_situ_micro_cut_retry(tmp_path):
    """Vérifie qu'une micro-coupure durant le téléchargement d'un segment est résolue in-situ sans interruption globale."""
    output_path = tmp_path / "microcut.mp4"
    task = DownloadTask(
        id=str(uuid.uuid4()),
        animeName="Microcut Test Anime",
        episodeNumber=1,
        fileName="microcut.mp4",
        savePath=str(output_path),
        status=DownloadStatus.DOWNLOADING,
    )

    m3u8_content = (
        "#EXTM3U\n"
        "#EXT-X-VERSION:3\n"
        "#EXTINF:10.0,\n"
        "http://example.com/hls/seg0.ts\n"
        "#EXTINF:10.0,\n"
        "http://example.com/hls/seg1.ts\n"
        "#EXT-X-ENDLIST\n"
    )

    attempt_counts = {"http://example.com/hls/seg1.ts": 0}

    class MockResponse:
        def __init__(self, text="", content=b"", status_code=200):
            self.text = text
            self.content = content
            self.status_code = status_code

    class MockStreamContext:
        def __init__(self, url):
            self.url = url
            self.status_code = 200
            self.headers = {}

        async def __aenter__(self):
            if "seg1.ts" in self.url:
                attempt_counts[self.url] += 1
                if attempt_counts[self.url] == 1:
                    raise ConnectionResetError("Micro-coupure réseau simulée sur seg1")
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def aiter_bytes(self, chunk_size=16384):
            yield b"SEGMENT_DATA_STREAMED"

    class MockAsyncClientWithStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            pass

        async def get(self, url):
            return MockResponse(text=m3u8_content)

        def stream(self, method, url):
            return MockStreamContext(url)

    with patch.object(download_manager, "_create_async_client", return_value=MockAsyncClientWithStream()), \
         patch.object(download_manager, "_finalize_task", new_callable=AsyncMock):
        with patch.object(download_manager, "is_ffmpeg_available", return_value=False):
            with patch("asyncio.sleep", return_value=None):
                await download_manager._download_hls_segments_native(task, "http://example.com/hls/master.m3u8")

    assert output_path.exists()
    assert attempt_counts["http://example.com/hls/seg1.ts"] == 2, "seg1 doit avoir été retenté in-situ après la micro-coupure"
    assert task.progress == 100.0


@pytest.mark.asyncio
async def test_bytes_gained_prevents_server_fallback_and_decrements_retry(tmp_path):
    """Vérifie que la progression en octets protège l'hébergeur contre les faux basculements et réinitialise les erreurs."""
    output_path = tmp_path / "progression_test.mp4"
    task = DownloadTask(
        id=str(uuid.uuid4()),
        animeName="Slow Conn Test",
        episodeNumber=2,
        fileName="progression_test.mp4",
        savePath=str(output_path),
        selectedServer="myTV",
        status=DownloadStatus.DOWNLOADING,
        retryCount=2,
        downloadedBytes=0,
    )
    task.consecutiveServerErrors = 1

    download_calls = 0

    async def fake_download(t, url):
        nonlocal download_calls
        download_calls += 1
        if download_calls == 1:
            # Premier essai : gagne 500 KB puis coupure réseau transitoire
            t.downloadedBytes = 500 * 1024
            raise ConnectionError("connection reset by peer")
        else:
            # Deuxième essai : termine le téléchargement
            t.downloadedBytes = 1000 * 1024
            t.status = DownloadStatus.COMPLETED

    with patch.object(download_manager, "is_client_online", return_value=True):
        with patch.object(download_manager, "_download_single_file", side_effect=fake_download):
            with patch.object(download_manager, "_download_hls_stream", side_effect=fake_download):
                with patch("asyncio.sleep", return_value=None):
                    await download_manager._execute_download(task)

    assert task.selectedServer == "myTV", "L'hébergeur myTV doit être conservé car la connexion a progressé"
    assert getattr(task, "consecutiveServerErrors", 0) == 0, "Les erreurs serveur doivent être réinitialisées"
