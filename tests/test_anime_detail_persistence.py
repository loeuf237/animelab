"""Tests for persistent offline library anime detail snapshots and cover image offline cache."""
import hashlib
import importlib
from unittest.mock import AsyncMock, patch

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

from animelab import config as app_config, security
from animelab.api_errors import install_error_handlers
from animelab.database import Base, create_database_engine
from animelab.migrations import MIGRATIONS, migrate
from animelab.models.anime import AnimeDetail, Episode
from animelab.models.anime_detail_cache import AnimeDetailSnapshot
from animelab.routers import anime, library, media
from animelab.services.download_manager import download_manager
from animelab.services.extension_service import extension_service
from animelab.services.library_service import library_service
from animelab.services.local_media import local_media
from animelab.services.tmdb_service import tmdb_service
from animelab.services.voiranime_service import voiranime_service

database_module = importlib.import_module("animelab.database")
library_module = importlib.import_module("animelab.services.library_service")


@pytest.fixture
def isolated_env(tmp_path, monkeypatch):
    dl_dir = tmp_path / "downloads"
    dl_dir.mkdir(parents=True, exist_ok=True)
    img_dir = tmp_path / "image_cache"
    img_dir.mkdir(parents=True, exist_ok=True)
    db_file = tmp_path / "detail_cache.db"
    engine = create_engine(f"sqlite:///{db_file}", connect_args={"check_same_thread": False})
    Base.metadata.create_all(engine)
    factory = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)
    monkeypatch.setattr(database_module, "SessionLocal", factory)
    monkeypatch.setattr(library_module, "SessionLocal", factory)
    monkeypatch.setattr(app_config.settings, "DOWNLOAD_DIR", str(dl_dir))
    monkeypatch.setattr(app_config.settings, "VOIR_ANIME_URL", "https://voiranime.cx")
    monkeypatch.setattr(media, "IMAGE_DISK_CACHE_DIR", img_dir)
    monkeypatch.setattr(media, "IMAGE_CACHE", media.OrderedDict())
    monkeypatch.setattr(media, "IMAGE_CACHE_CURRENT_BYTES", 0)
    monkeypatch.setattr(download_manager, "tasks", {})
    with local_media._lock:
        local_media._entries.clear()

    app = FastAPI()
    install_error_handlers(app)
    app.include_router(anime.router)
    app.include_router(library.router)
    app.include_router(media.router)
    with TestClient(app) as client:
        yield client, dl_dir, img_dir, factory

    with local_media._lock:
        local_media._entries.clear()
    engine.dispose()


def test_migration_16_creates_anime_detail_snapshots_idempotently(tmp_path):
    db_path = tmp_path / "v15_upgrade.sqlite3"
    engine = create_database_engine(f"sqlite:///{db_path}")
    try:
        migrate(engine, MIGRATIONS[:15])
        with engine.begin() as conn:
            conn.exec_driver_sql(
                "INSERT INTO favorites(url, title, source) VALUES "
                "('https://voiranime.cx/anime/frieren/', 'Frieren', 'voir-anime')"
            )
        migrate(engine)
        migrate(engine)
        with engine.connect() as conn:
            applied = conn.exec_driver_sql(
                "SELECT version FROM schema_migrations ORDER BY version"
            ).scalars().all()
            assert applied == [m.version for m in MIGRATIONS]
            cols = {
                row[1] for row in conn.exec_driver_sql("PRAGMA table_info(anime_detail_snapshots)")
            }
            assert {"animeUrl", "source", "sourceName", "title", "detailJson", "pinned", "updatedAt"} <= cols
            fav_title = conn.exec_driver_sql("SELECT title FROM favorites").scalar_one()
            assert fav_title == "Frieren"
    finally:
        engine.dispose()


def test_library_anime_detail_persists_and_loads_offline_with_live_local_state(
    isolated_env, monkeypatch
):
    client, dl_dir, _, _ = isolated_env
    anime_url = "https://voiranime.cx/anime/frieren/"
    library_service.add_favorite(anime_url, "Frieren", source="voir-anime")

    online_detail = AnimeDetail(
        title="Frieren",
        url=anime_url,
        imageUrl="https://voiranime.cx/frieren.jpg",
        synopsis="Après la défaite du roi démon...",
        genres=["Aventure", "Fantaisie"],
        version="VF",
        episodes=[
            Episode(
                number=1,
                title="Épisode 1",
                version="VF",
                playerUrl="https://voiranime.cx/anime/frieren/ep-1/",
                downloadPageUrl="https://voiranime.cx/anime/frieren/ep-1/",
            )
        ],
    )

    monkeypatch.setattr(security, "_resolve_dns", lambda host: ["93.184.216.34"])
    with patch.object(tmdb_service, "enrich_anime_detail", AsyncMock(return_value=online_detail)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None), \
         patch.object(voiranime_service, "get_anime_detail", AsyncMock(return_value=online_detail)) as m_get:
        resp_online = client.get("/api/anime/detail", params={"url": anime_url, "source": "voir-anime"})

    assert resp_online.status_code == 200
    body_online = resp_online.json()
    assert body_online["fromCache"] is False
    assert body_online["isFavorite"] is True
    assert len(body_online["anime"]["episodes"]) == 1
    assert m_get.await_count == 1

    # Add local downloaded file and mark watched after caching snapshot.
    ep_dir = dl_dir / "Frieren"
    ep_dir.mkdir()
    local_file = ep_dir / "Frieren - Episode 1 [VF].mp4"
    local_file.write_bytes(b"LOCAL_MP4_DATA")
    library_service.mark_as_watched(anime_url, "Frieren", 1, "VF", watched=True)

    # Go completely offline: DNS empty and upstream scraper fails.
    monkeypatch.setattr(security, "_resolve_dns", lambda host: [])
    with patch.object(voiranime_service, "get_anime_detail", AsyncMock(side_effect=RuntimeError("offline"))):
        resp_offline = client.get("/api/anime/detail", params={"url": anime_url, "source": "voir-anime"})
        resp_mirror = client.get(
            "/api/anime/detail",
            params={"url": "https://voir-anime.to/anime/frieren/", "source": "voir-anime"},
        )

    assert resp_offline.status_code == 200
    body_offline = resp_offline.json()
    assert body_offline["fromCache"] is True
    assert body_offline["cachedAt"] is not None
    assert body_offline["anime"]["title"] == "Frieren"
    assert "roi démon" in body_offline["anime"]["synopsis"]
    ep1 = body_offline["anime"]["episodes"][0]
    assert ep1["isWatched"] is True
    assert ep1["isDownloaded"] is True
    assert isinstance(ep1["downloadTaskId"], str) and ep1["downloadTaskId"].startswith("local-")

    assert resp_mirror.status_code == 200
    assert resp_mirror.json()["fromCache"] is True


def test_non_library_pin_on_favorite_undo_and_unpinned_pruning(isolated_env, monkeypatch):
    client, _, _, factory = isolated_env
    monkeypatch.setattr(security, "_resolve_dns", lambda host: ["93.184.216.34"])

    target_url = "https://voiranime.cx/anime/dandadan/"
    detail = AnimeDetail(
        title="Dandadan",
        url=target_url,
        version="VOSTFR",
        episodes=[Episode(number=1, title="Épisode 1", version="VOSTFR")],
    )

    with patch.object(tmdb_service, "enrich_anime_detail", AsyncMock(return_value=detail)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None), \
         patch.object(voiranime_service, "get_anime_detail", AsyncMock(return_value=detail)):
        resp = client.get("/api/anime/detail", params={"url": target_url, "source": "voir-anime"})
    assert resp.status_code == 200
    assert resp.json()["isFavorite"] is False

    # Adding to library pins the existing snapshot; removing unpins; re-adding re-pins.
    add_res = client.post(
        "/api/favorites",
        json={"url": target_url, "title": "Dandadan", "source": "voir-anime"},
    )
    assert add_res.status_code == 200

    # Insert many unpinned snapshots (> limit) and verify Dandadan (pinned) survives pruning.
    for i in range(library_service.MAX_UNPINNED_DETAIL_SNAPSHOTS + 6):
        library_service.save_anime_detail_snapshot(
            f"https://voiranime.cx/anime/extra-{i}/",
            "voir-anime",
            "VoirAnime",
            {"title": f"Extra {i}", "url": f"https://voiranime.cx/anime/extra-{i}/", "episodes": []},
            pinned=False,
        )

    with factory() as db:
        pinned_rows = db.query(AnimeDetailSnapshot).filter(AnimeDetailSnapshot.pinned.is_(True)).all()
        unpinned_count = (
            db.query(AnimeDetailSnapshot).filter(AnimeDetailSnapshot.pinned.is_(False)).count()
        )
    assert [r.animeUrl for r in pinned_rows] == [target_url]
    assert unpinned_count == library_service.MAX_UNPINNED_DETAIL_SNAPSHOTS

    # Works completely offline after unpinned eviction!
    monkeypatch.setattr(security, "_resolve_dns", lambda host: [])
    with patch.object(voiranime_service, "get_anime_detail", AsyncMock(side_effect=RuntimeError("offline"))):
        offline_resp = client.get("/api/anime/detail", params={"url": target_url, "source": "voir-anime"})
    assert offline_resp.status_code == 200
    assert offline_resp.json()["fromCache"] is True

    # Removing and re-adding preserves pinned offline snapshot.
    assert client.request("DELETE", "/api/favorites", json={"url": target_url}).status_code == 200
    assert (
        client.post(
            "/api/favorites",
            json={"url": target_url, "title": "Dandadan", "source": "voir-anime"},
        ).status_code
        == 200
    )
    snap = library_service.get_anime_detail_snapshot(target_url)
    assert snap is not None and snap.pinned is True


def test_manual_refresh_updates_snapshot_online_and_preserves_snapshot_offline(
    isolated_env, monkeypatch
):
    client, _, _, _ = isolated_env
    anime_url = "https://voiranime.cx/anime/solo-leveling/"
    library_service.add_favorite(anime_url, "Solo Leveling", source="voir-anime")

    v1 = AnimeDetail(
        title="Solo Leveling",
        url=anime_url,
        version="VF",
        episodes=[Episode(number=1, title="Épisode 1", version="VF")],
    )
    v2 = AnimeDetail(
        title="Solo Leveling",
        url=anime_url,
        version="VF",
        episodes=[
            Episode(number=1, title="Épisode 1", version="VF"),
            Episode(number=2, title="Épisode 2", version="VF"),
        ],
    )

    monkeypatch.setattr(security, "_resolve_dns", lambda host: ["93.184.216.34"])
    with patch.object(tmdb_service, "enrich_anime_detail", AsyncMock(side_effect=lambda d: d)), \
         patch.object(extension_service, "get_container_source_by_id", return_value=None), \
         patch.object(voiranime_service, "get_anime_detail", AsyncMock(side_effect=[v1, v2])):
        first = client.get("/api/anime/detail", params={"url": anime_url, "source": "voir-anime"})
        assert len(first.json()["anime"]["episodes"]) == 1

        refreshed = client.get(
            "/api/anime/detail",
            params={"url": anime_url, "source": "voir-anime", "refresh": "true"},
        )
        assert refreshed.status_code == 200
        ref_body = refreshed.json()
        assert ref_body["fromCache"] is False
        assert len(ref_body["anime"]["episodes"]) == 2

    # Offline refresh returns 503 while leaving the 2-episode snapshot intact.
    monkeypatch.setattr(security, "_resolve_dns", lambda host: [])
    failed_refresh = client.get(
        "/api/anime/detail",
        params={"url": anime_url, "source": "voir-anime", "refresh": "true"},
    )
    assert failed_refresh.status_code == 503

    cached_after = client.get("/api/anime/detail", params={"url": anime_url, "source": "voir-anime"})
    assert cached_after.status_code == 200
    assert cached_after.json()["fromCache"] is True
    assert len(cached_after.json()["anime"]["episodes"]) == 2


def test_image_proxy_serves_disk_cache_offline_while_rejecting_unapproved_shared_urls(
    isolated_env, monkeypatch
):
    client, _, img_dir, _ = isolated_env
    tmdb_cover = "https://image.tmdb.org/t/p/w500/frieren.jpg"
    cover_hash = hashlib.sha256(tmdb_cover.encode()).hexdigest()
    (img_dir / f"{cover_hash}.bin").write_bytes(b"PNG_COVER_BYTES")
    (img_dir / f"{cover_hash}.meta").write_text("image/png", encoding="utf-8")

    unapproved_cover = "https://outside.example/secret.jpg"
    unapproved_hash = hashlib.sha256(unapproved_cover.encode()).hexdigest()
    (img_dir / f"{unapproved_hash}.bin").write_bytes(b"UNAPPROVED")
    (img_dir / f"{unapproved_hash}.meta").write_text("image/jpeg", encoding="utf-8")

    # Completely offline DNS -> cached approved cover still serves cleanly.
    monkeypatch.setattr(security, "_resolve_dns", lambda host: [])
    resp = client.get("/api/media/image-proxy", params={"url": tmdb_cover})
    assert resp.status_code == 200
    assert resp.content == b"PNG_COVER_BYTES"

    # In shared worker mode, unapproved domains remain blocked before reading cache.
    monkeypatch.setenv("ANIMELAB_SHARED_WORKER", "1")
    blocked = client.get("/api/media/image-proxy", params={"url": unapproved_cover})
    assert blocked.status_code == 400
