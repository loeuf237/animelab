import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace

import httpx
import pytest
from fastapi import FastAPI
from fastapi.responses import JSONResponse

from animelab.android_security import AndroidSessionMiddleware
from animelab.api_contracts import install_contract_schema
from animelab.progressive import ProgressiveAppLoader, ProgressiveRouteMiddleware, resolve_groups_for_path
from animelab.routers.diagnostics import router as diagnostics_router
from animelab.routers.i18n import router as i18n_router
from animelab.routers.startup import router as startup_router
from animelab.routers.web import router as web_router


def test_progressive_subprocess_avoids_heavy_imports(tmp_path):
    env = {
        **os.environ,
        "ANIMELAB_PROGRESSIVE_BOOT": "1",
        "ANIMAN_DATA_DIR": str(tmp_path / "data"),
        "ANIMAN_CACHE_DIR": str(tmp_path / "cache"),
        "ANIMAN_DB_PATH": str(tmp_path / "db" / "animan.sqlite3"),
        "ANIMAN_DOWNLOAD_DIR": str(tmp_path / "downloads"),
    }
    script = """
import json, sys
import run
heavy = [
    name for name in (
        "sqlalchemy",
        "yt_dlp",
        "animelab.services.extension_service",
        "animelab.services.seanime_service",
        "animelab.services.download_manager",
        "animelab.routers.extensions",
        "animelab.routers.download",
        "animelab.routers.media",
        "animelab.routers.library",
        "animelab.routers.anime",
        "animelab.routers.sources",
        "animelab.routers.subtitles",
    )
    if name in sys.modules
]
print(json.dumps({
    "progressive": run.PROGRESSIVE_BOOT,
    "modules": len(sys.modules),
    "heavy": heavy,
    "readiness": run.progressive_loader.readiness_snapshot(),
}))
"""
    proc = subprocess.run(
        [sys.executable, "-c", script],
        cwd=str(Path(__file__).resolve().parents[1]),
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=30,
    )
    payload = json.loads(proc.stdout.strip().splitlines()[-1])
    assert payload["progressive"] is True
    assert payload["heavy"] == []
    assert payload["readiness"]["loadedGroups"] == []
    assert payload["readiness"]["stage"] == "stage0"


def test_resolve_groups_for_path_ordering():
    assert resolve_groups_for_path("/spa/") == ()
    assert resolve_groups_for_path("/api/app/startup") == ()
    assert resolve_groups_for_path("/api/i18n") == ()
    assert resolve_groups_for_path("/api/diagnostics/report") == ()
    assert resolve_groups_for_path("/api/engine/readiness") == ()
    assert resolve_groups_for_path("/api/download/subtitle-provider") == ("subtitles",)
    assert resolve_groups_for_path("/api/download/abc123/subtitles/search") == ("subtitles",)
    assert resolve_groups_for_path("/api/download/status") == ("downloads",)
    assert resolve_groups_for_path("/api/sources/voir-anime/feed") == ("anime",)
    assert resolve_groups_for_path("/api/sources") == ("sources",)
    assert resolve_groups_for_path("/api/extensions/repositories") == ("extensions",)
    assert resolve_groups_for_path("/api/favorites") == ("library",)
    assert resolve_groups_for_path("/api/media/external-player/settings") == ("media",)
    assert resolve_groups_for_path("/api/playback/session") == ("playback",)
    assert resolve_groups_for_path("/api/network/sessions") == ("network",)


def _build_staged_test_app(token: str | None = None):
    staged_app = FastAPI()
    install_contract_schema(staged_app)
    loader = ProgressiveAppLoader(staged_app, progressive=True)
    staged_app.add_middleware(ProgressiveRouteMiddleware, loader=loader)
    if token:
        staged_app.add_middleware(AndroidSessionMiddleware, token=token)
    staged_app.include_router(web_router)
    staged_app.include_router(diagnostics_router)
    staged_app.include_router(startup_router)
    staged_app.include_router(i18n_router)

    @staged_app.get("/api/engine/readiness")
    async def readiness():
        loader.mark_stage0_ready()
        return loader.readiness_snapshot()

    loader.mark_stage0_ready()
    return staged_app, loader


@pytest.mark.asyncio
async def test_stage0_fresh_db_and_auth_boundary_without_loading_heavy_groups(tmp_path, monkeypatch):
    from animelab.config import settings
    from animelab.database import create_database_engine

    db_path = tmp_path / "fresh" / "animan.sqlite3"
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    import animelab.database as db_mod
    fresh_engine = create_database_engine("sqlite:///" + str(db_path))
    monkeypatch.setattr(db_mod, "engine", fresh_engine)

    token = "a" * 64
    staged_app, loader = _build_staged_test_app(token=token)
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(staged_app, client=("127.0.0.1", 123)), base_url="http://127.0.0.1") as client:
            # Stage 0 startup auto-initializes schema if needed without loading Stage 1/2 routers.
            startup = await client.get("/api/app/startup", headers={"X-Animan-Session": token})
            assert startup.status_code == 200
            assert loader.loaded_groups == set()

            readiness = await client.get("/api/engine/readiness", headers={"X-Animan-Session": token})
            assert readiness.status_code == 200
            assert readiness.json()["stage"] == "stage0"

            i18n_resp = await client.get("/api/i18n", headers={"X-Animan-Session": token})
            assert i18n_resp.status_code == 200
            assert loader.loaded_groups == set()

            # Unauthenticated calls must stop at AndroidSessionMiddleware (401) without loading groups.
            unauth = await client.get("/api/extensions/repositories")
            assert unauth.status_code == 401
            assert loader.loaded_groups == set()
    finally:
        await loader.shutdown()
        fresh_engine.dispose()


@pytest.mark.asyncio
async def test_on_demand_route_group_loading_across_all_stages(tmp_path, monkeypatch):
    from animelab.config import settings
    from animelab.database import create_database_engine
    from animelab.migrations import migrate
    import animelab.database as db_mod

    db_path = tmp_path / "staged.sqlite3"
    engine = create_database_engine("sqlite:///" + str(db_path))
    migrate(engine)
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_path))
    monkeypatch.setattr(settings, "DOWNLOAD_DIR", str(tmp_path / "downloads"))
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path / "cache")
    monkeypatch.setattr(db_mod, "engine", engine)

    staged_app, loader = _build_staged_test_app()
    # Avoid real network refreshes during async route checks.
    monkeypatch.setenv("ANIMAN_STARTUP_REFRESH", "false")
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(staged_app, client=("127.0.0.1", 123)), base_url="http://127.0.0.1") as client:
            assert (await client.get("/api/favorites")).status_code == 200
            assert "library" in loader.loaded_groups

            assert (await client.get("/api/download/status")).status_code == 200
            assert "downloads" in loader.loaded_groups

            assert (await client.get("/api/download/subtitle-provider")).status_code == 200
            assert "subtitles" in loader.loaded_groups

            assert (await client.get("/api/media/external-player/settings")).status_code == 200
            assert "media" in loader.loaded_groups

            assert (await client.get("/api/network/sessions")).status_code == 200
            assert "network" in loader.loaded_groups

            assert (await client.get("/api/extensions/repositories")).status_code == 200
            assert "extensions" in loader.loaded_groups

            assert (await client.get("/api/sources")).status_code == 200
            assert "sources" in loader.loaded_groups

            assert (await client.get("/api/anime/detail", params={"url": "invalid"})).status_code in (400, 404, 422)
            assert "anime" in loader.loaded_groups

            assert (await client.post("/api/playback/checkpoint", json={})).status_code in (400, 422)
            assert "playback" in loader.loaded_groups
            assert loader.fully_loaded is True

            schema = await client.get("/openapi.json")
            assert schema.status_code == 200
            assert "/api/favorites" in schema.json()["paths"]
    finally:
        await loader.shutdown()
        engine.dispose()


def test_android_runtime_extension_http_works_before_full_warmup(monkeypatch):
    import android_runtime

    monkeypatch.setattr(android_runtime, "_configured_bridges", set())
    fake_verification = SimpleNamespace(userAgent=lambda: "Mozilla/5.0 (Linux; Android 14) AnimeLabTest")
    monkeypatch.setitem(sys.modules, "java", SimpleNamespace(jclass=lambda name: fake_verification))

    payload = json.loads(android_runtime.extension_http('{"action": "user_agent"}'))
    assert "AnimeLabTest" in payload["userAgent"]


def test_android_spa_packaging_and_interceptor_rules():
    root = Path(__file__).resolve().parents[1]
    gradle_text = (root / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    assert "syncSpaAssets" in gradle_text
    assert 'generated/spa-assets/spa' in gradle_text
    assert 'eachFile { path =' not in gradle_text

    interceptor_text = (
        root / "android" / "app" / "src" / "main" / "java" / "com" / "animan" / "app" / "SpaAssetInterceptor.kt"
    ).read_text(encoding="utf-8")
    for marker in ('"/spa"', '"/assets/"', '"/api/"', '"application/javascript"', '"text/css"', '"text/html"'):
        assert marker in interceptor_text


def test_pyinstaller_spec_collects_lazily_imported_animelab_submodules():
    root = Path(__file__).resolve().parents[1]
    spec_text = (root / "animelab.spec").read_text(encoding="utf-8")
    for pkg in ("animelab.models", "animelab.routers", "animelab.services"):
        assert f"collect_submodules('{pkg}')" in spec_text
    for mod in ("animelab.database", "animelab.migrations", "animelab.progressive", "animelab.sqlite_conn"):
        assert f"'{mod}'" in spec_text
