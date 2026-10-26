from animelab.api_contracts import ContractRoute
"""Local browser verification and safe transport diagnostics."""
from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel, Field

from animelab.services.browser_verification import browser_verification
from animelab.services.download_manager import download_manager

router = APIRouter(route_class=ContractRoute, prefix="/api/network")


@router.get("/proxy-pool")
async def public_proxies(request: Request):
    from animelab.services.proxy_pool import proxy_pool
    return proxy_pool.snapshot()


@router.post("/proxy-pool/settings")
async def proxy_pool_settings(request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    try:
        saved = proxy_pool.set_options(await request.json())
        if saved["automatic"] and not saved["healthy"] and saved["total"]:
            await proxy_pool.check()
        return proxy_pool.snapshot()
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/proxy-pool/refresh")
async def refresh_proxies(request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    await proxy_pool.refresh()
    return proxy_pool.snapshot()


@router.post("/proxy-pool/check")
async def check_proxies(request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    await proxy_pool.check()
    return proxy_pool.snapshot()


@router.post("/proxy-pool/import")
async def import_proxies(request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    # Read incrementally rather than loading an unbounded upload into memory.
    raw = bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw) > 1024 * 1024:
            raise HTTPException(413, "Le fichier JSON dépasse 1 Mo")
    try:
        import json
        return proxy_pool.import_json(json.loads(raw))
    except (ValueError, TypeError, AttributeError) as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/proxy-pool/import")
async def clear_imported_proxies(request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    return proxy_pool.clear_imported()


class StartVerification(BaseModel):
    domain: str = Field(pattern=r"^[A-Za-z0-9.-]+$", max_length=253)
    browser: str | None = None
    mode: str = "browser"


@router.post("/proxy-pool/rotate")
async def rotate_proxy(body: StartVerification, request: Request):
    local_only(request)
    from animelab.services.proxy_pool import proxy_pool
    from animelab.services.source_http import source_http
    domain = body.domain.lower()
    # A domain must have been contacted by the application, not supplied as a new URL.
    with source_http._lock:
        known = domain in source_http._domains
    if not known:
        raise HTTPException(400, "Aucune session connue pour cette source")
    if not proxy_pool.snapshot()["healthy"]:
        if not proxy_pool.entries:
            await proxy_pool.refresh()
        else:
            await proxy_pool.check()
    try:
        async with browser_verification._lock:
            if any(job["domain"] == domain for job in browser_verification.jobs.values()):
                raise HTTPException(409, "Fermez la fenêtre de vérification avant de changer de proxy")
            source_http.rotate_proxy(domain)
        resumed = download_manager.resume_verified_domain(domain)
        return {"success": True, "domain": domain, "resumed": resumed}
    except ValueError as exc:
        raise HTTPException(409, str(exc)) from exc


def is_local(request):
    import os
    if os.getenv("ANIMELAB_SHARED_WORKER") == "1":
        return False
    return bool(request.client and request.client.host in ("127.0.0.1", "::1", "testclient"))


def local_only(request):
    if not is_local(request):
        raise HTTPException(403, "La vérification dans le navigateur doit être ouverte depuis cette machine")


@router.get("/sessions")
async def sessions(request: Request):
    await browser_verification.expire()
    return browser_verification.options(client_local=is_local(request))


@router.post("/verification")
async def start(body: StartVerification, request: Request):
    local_only(request)
    try:
        return await browser_verification.start(body.domain, body.browser, body.mode)
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/verification/{job_id}/complete")
async def complete(job_id: str, request: Request):
    local_only(request)
    try:
        result = await browser_verification.complete(job_id)
        result["resumed"] = download_manager.resume_verified_domain(result["domain"])
        return result
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.delete("/verification/{job_id}")
async def cancel(job_id: str, request: Request):
    local_only(request)
    await browser_verification.cancel(job_id)
    return {"success": True}


@router.post("/recheck")
async def recheck(body: StartVerification, request: Request):
    """Probe only a known blocked URL; a manual visit does not imply clearance."""
    from animelab.services.source_http import source_http
    local_only(request)
    state = source_http.state("https://" + body.domain)
    with state.condition:
        url = state.blocked_url
        generation = state.generation
    if url:
        import httpx
        try:
            response = await source_http.async_client().get(url, bypass_cache=True, verify_challenge=True)
            response.raise_for_status()
        except httpx.HTTPStatusError as exc:
            raise HTTPException(502, f"La source refuse encore l’accès (HTTP {exc.response.status_code})") from exc
        except httpx.RequestError as exc:
            raise HTTPException(502, "La source est injoignable ; réessayez plus tard") from exc
        with state.condition:
            if state.generation == generation and state.blocked_url == url:
                state.blocked_url = None
                state.last_error = None
                state.generation += 1
    return {"success": True, "domain": body.domain, "resumed": download_manager.resume_verified_domain(body.domain)}
