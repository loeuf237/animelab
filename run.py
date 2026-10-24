import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

import os
from animan.diagnostics import install_logging
install_logging()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse, FileResponse
from fastapi.staticfiles import StaticFiles
import uvicorn

from animan.services.source_http import source_http, VerificationRequired
from animan.services.browser_verification import browser_verification
from animan.routers.network import router as network_router
from animan.config import settings
from animan import __version__
from animan.database import init_db
from animan.services.download_manager import download_manager
from animan.services.scraping_service import scraping_service
from animan.services.voiranime_service import voiranime_service
from animan.services.animepahe_service import animepahe_service
from animan.services.watchdog_service import watchdog_service
from animan.services.i18n_service import current_request_lang, detect_client_language
from animan.routers import (
    anime_router,
    download_router,
    library_router,
    media_router,
    extensions_router,
    sources_router,
    i18n_router,
)

logger = logging.getLogger("animan")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Starting AnimeLab Python v%s...", __version__)
    source_http.start()
    # 1. Initialize SQLite database
    init_db()
    # 2. Restore unfinished download tasks
    download_manager.init_from_db()
    loop = asyncio.get_running_loop()
    source_http.rotation_callback = lambda domain: loop.call_soon_threadsafe(download_manager.resume_verified_domain, domain)
    # 3. Start Watchdog service
    watchdog_service.start()
    # 4. Pre-load release feeds (background with concurrency lock)
    bg_tasks = [
        asyncio.create_task(browser_verification.watch()),
    ]
    from animan.services.proxy_pool import proxy_pool
    bg_tasks.append(asyncio.create_task(proxy_pool.watch()))
    if os.getenv("ANIMAN_STARTUP_REFRESH", "true").lower() not in ("false", "0", "no"):
        bg_tasks.append(asyncio.create_task(proxy_pool.refresh()))
        for service in (scraping_service, voiranime_service, animepahe_service):
            service._refresh_task = asyncio.create_task(service._safe_refresh_cache())
            bg_tasks.append(service._refresh_task)

    import socket
    lan_ip = "127.0.0.1"
    try:
        with socket.socket(socket.AF_INET, socket.SOCK_DGRAM) as s:
            s.connect(("8.8.8.8", 80))
            lan_ip = s.getsockname()[0]
    except Exception:
        pass
    logger.info("Application ready at http://localhost:%d and http://%s:%d (LAN / Mobile)", settings.PORT, lan_ip, settings.PORT)
    yield

    logger.info("Stopping AnimeLab...")
    source_http.rotation_callback = None
    watchdog_service.stop()
    await download_manager.shutdown()
    for t in bg_tasks:
        if not t.done():
            t.cancel()
    await asyncio.gather(*bg_tasks, return_exceptions=True)
    await browser_verification.close()
    await proxy_pool.close()
    await asyncio.to_thread(source_http.close)

app = FastAPI(
    title="AnimeLab",
    description="Anime Downloader - High performance anime streaming & downloads",
    version=__version__,
    lifespan=lifespan
)

# Configuration CORS pour autoriser les clients frontend découplés (SPA Vite, mobile, LAN)
_cors_origins_env = os.getenv("ANIMAN_CORS_ORIGINS", "")
_allowed_origins = [
    "http://localhost:5173",
    "http://127.0.0.1:5173",
    "http://localhost:8080",
    "http://127.0.0.1:8080",
    "http://localhost:3000",
    "http://127.0.0.1:3000",
]
if _cors_origins_env:
    for _o in _cors_origins_env.split(","):
        _clean_o = _o.strip()
        if _clean_o and _clean_o not in _allowed_origins:
            _allowed_origins.append(_clean_o)

app.add_middleware(
    CORSMiddleware,
    allow_origins=_allowed_origins if "*" not in _allowed_origins else ["*"],
    allow_origin_regex=r"https?://(localhost|127\.0\.0\.1)(:\d+)?",
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Range", "Content-Length", "Accept-Ranges"],
)

@app.middleware("http")
async def i18n_middleware(request: Request, call_next):
    lang = request.query_params.get("lang")
    if not lang or lang not in ("fr", "en"):
        lang = request.cookies.get("animan_lang")
    if not lang or lang not in ("fr", "en"):
        lang = detect_client_language(request.headers.get("accept-language"))
    
    token = current_request_lang.set(lang)
    request.state.lang = lang
    try:
        response = await call_next(request)
    finally:
        current_request_lang.reset(token)

    path = request.url.path
    is_static_or_media = (
        path.startswith(("/static", "/assets", "/css", "/js", "/img", "/api/media"))
        or path in ("/favicon.ico", "/manifest.json", "/sw.js", "/offline.html")
    )
    if "lang" in request.query_params and request.query_params["lang"] in ("fr", "en"):
        response.set_cookie(key="animan_lang", value=lang, max_age=31536000, httponly=False, samesite="lax")
    elif not is_static_or_media and not request.cookies.get("animan_lang"):
        response.set_cookie(key="animan_lang", value=lang, max_age=31536000, httponly=False, samesite="lax")
    return response

@app.middleware("http")
async def security_headers_and_csrf_middleware(request: Request, call_next):
    if request.method in ("POST", "PUT", "DELETE", "PATCH"):
        origin = request.headers.get("origin")
        referer = request.headers.get("referer")
        source_url = origin or referer
        is_cors_allowed = False

        if origin:
            try:
                from urllib.parse import urlparse
                parsed_origin = urlparse(origin)
                o_host = (parsed_origin.hostname or "").lower()
                if o_host in ("localhost", "127.0.0.1", "0.0.0.0", "testserver"):
                    is_cors_allowed = True
                elif origin in _allowed_origins:
                    is_cors_allowed = True
            except Exception:
                pass

        sec_fetch_site = request.headers.get("sec-fetch-site", "").lower()
        if sec_fetch_site == "cross-site" and not is_cors_allowed:
            logger.warning("CSRF blocked: cross-site sec-fetch-site for %s %s", request.method, request.url.path)
            return JSONResponse(status_code=403, content={"error": "Cross-site request blocked"})

        if source_url and not is_cors_allowed:
            try:
                from urllib.parse import urlparse
                parsed_source = urlparse(source_url)
                source_host = (parsed_source.hostname or "").lower()
                request_host = (request.url.hostname or "").lower()
                allowed_hosts = {"localhost", "127.0.0.1", "0.0.0.0", "testserver", settings.HOST.lower(), request_host}
                if source_host and source_host not in allowed_hosts:
                    logger.warning("CSRF blocked: Origin '%s' rejected for %s %s", source_url, request.method, request.url.path)
                    return JSONResponse(status_code=403, content={"error": "Forbidden origin (CSRF blocked)"})
            except Exception:
                return JSONResponse(status_code=403, content={"error": "Invalid origin"})

    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "SAMEORIGIN"
    return response

# Montage des fichiers statiques
static_dir = settings.STATIC_DIR
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")
app.mount("/css", StaticFiles(directory=str(static_dir / "css")), name="css")
app.mount("/js", StaticFiles(directory=str(static_dir / "js")), name="js")
app.mount("/img", StaticFiles(directory=str(static_dir / "img")), name="img")

@app.get("/favicon.ico", include_in_schema=False)
async def get_favicon():
    return FileResponse(static_dir / "favicon.ico", media_type="image/x-icon")

# Points d'accès PWA (Progressive Web App)
@app.get("/manifest.json", include_in_schema=False)
async def get_manifest():
    return FileResponse(
        static_dir / "manifest.json",
        media_type="application/manifest+json",
        headers={"Cache-Control": "no-cache"},
    )

@app.get("/sw.js", include_in_schema=False)
async def get_service_worker():
    return FileResponse(
        static_dir / "sw.js",
        media_type="application/javascript",
        headers={
            "Service-Worker-Allowed": "/",
            "Cache-Control": "no-cache, no-store, must-revalidate",
        },
    )

@app.get("/offline.html", include_in_schema=False)
async def get_offline_page():
    return FileResponse(
        static_dir / "offline.html",
        media_type="text/html",
        headers={"Cache-Control": "public, max-age=86400"},
    )

# Enregistrement des routeurs
from animan.routers.playback import router as playback_router
app.include_router(playback_router)
from animan.routers.diagnostics import router as diagnostics_router
app.include_router(diagnostics_router)
from animan.api_errors import ErrorContractMiddleware, install_error_handlers
install_error_handlers(app)
from animan.api_contracts import install_contract_schema
install_contract_schema(app)
app.add_middleware(ErrorContractMiddleware)
# Validate Host before CSRF checks, CORS preflights and route handling.
app.add_middleware(TrustedHostMiddleware, allowed_hosts=settings.ALLOWED_HOSTS, www_redirect=False)

app.include_router(network_router)
app.include_router(anime_router)
app.include_router(download_router)
app.include_router(library_router)
app.include_router(media_router)
app.include_router(extensions_router)
app.include_router(sources_router)
app.include_router(i18n_router)

# Support SPA Vue 3 découplée (Mode hybride / production unifiée)
frontend_dist = Path(__file__).parent / "frontend" / "dist"
if (frontend_dist / "assets").exists():
    app.mount("/assets", StaticFiles(directory=str(frontend_dist / "assets")), name="spa_assets")

@app.get("/spa", include_in_schema=False)
@app.get("/spa/{full_path:path}", include_in_schema=False)
@app.get("/app", include_in_schema=False)
@app.get("/app/{full_path:path}", include_in_schema=False)
async def serve_spa_page():
    index_file = frontend_dist / "index.html"
    if index_file.exists():
        return FileResponse(index_file)
    return JSONResponse(
        status_code=404,
        content={"error": "Build SPA non trouvé. Exécutez 'npm run build' dans frontend/."}
    )

_embedded_server = None

def start_embedded_server(host: str = "0.0.0.0", port: int = 8080, data_dir: str = None):
    """Point d'entrée pour les environnements embarqués (Android / Chaquopy, etc.)."""
    global _embedded_server
    import os
    from pathlib import Path
    if data_dir:
        os.environ["ANIMAN_DATA_DIR"] = str(data_dir)
        try:
            Path(data_dir, "db").mkdir(parents=True, exist_ok=True)
            Path(data_dir, "cache").mkdir(parents=True, exist_ok=True)
        except Exception:
            pass
    import uvicorn
    logger.info("Démarrage du serveur embarqué AnimeLab sur %s:%d...", host, port)
    config = uvicorn.Config(
        app,
        host=host,
        port=port,
        log_level="info",
        loop="asyncio",
        timeout_keep_alive=30,
        timeout_graceful_shutdown=10,
    )
    _embedded_server = uvicorn.Server(config)
    _embedded_server.run()

def stop_embedded_server():
    """Arrête proprement le serveur embarqué Uvicorn."""
    global _embedded_server
    if _embedded_server is not None:
        _embedded_server.should_exit = True

if __name__ == "__main__":
    import os
    reload_enabled = os.getenv("ANIMAN_RELOAD", "true").lower() in ("1", "true", "yes")
    bind_host = os.getenv("ANIMAN_HOST", settings.HOST)
    uvicorn.run(
        "run:app" if reload_enabled else app,
        host=bind_host,
        port=settings.PORT,
        log_level="info",
        reload=reload_enabled,
        reload_dirs=["animan", "."] if reload_enabled else None,
        timeout_keep_alive=30,
        timeout_graceful_shutdown=10,
    )
