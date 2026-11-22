from animelab.api_contracts import ContractRoute
from animelab.api_errors import APIProblem, MESSAGES, problem_for
from animelab.services.source_http import RateLimited, SourceNetworkError, VerificationRequired
import json
import logging
from typing import Dict, Any
import httpx
from fastapi import APIRouter, Request, HTTPException, Query
from fastapi.responses import JSONResponse, StreamingResponse

from animelab.services.seanime_runtime import SeanimeRuntimeError
from animelab.services.source_settings_service import source_settings_service
from animelab.services.source_catalogue import source_catalogue, CatalogueError

logger = logging.getLogger("animelab.router.sources")
router = APIRouter(route_class=ContractRoute, prefix="/api/sources", tags=["sources"])


@router.get("")
async def list_catalogues():
    return {"sources": source_catalogue.sources()}


@router.get("/{source_id}/filters")
async def catalogue_filters(source_id: str):
    try:
        filters = await source_catalogue.filters(source_id)
        return {"tags": [{k: t[k] for k in ('id', 'label', 'group')} for t in filters['tags']],
                "groups": filters.get('groups', []), "orders": filters['orders'],
                **({'nativeFilters':filters['nativeFilters']} if 'nativeFilters' in filters else {})}
    except CatalogueError as exc:
        raise HTTPException(400, str(exc)) from exc
    # Transport failures retain their typed API handlers (DNS, TLS, rate
    # limiting and geographic refusal), just like direct source searches.


@router.get("/{source_id}/catalogue")
async def browse_catalogue(source_id: str, mode: str = 'latest', q: str = Query('', max_length=250),
                           tags: list[str] = Query(default=[]), order: str = 'source',
                           cursor: str | None = Query(None, max_length=64),
                           nativeFilters: str | None = Query(None,max_length=32768)):
    if len(tags) > 12:
        raise HTTPException(400, "Sélectionnez au maximum douze genres")
    try:
        import json
        native_filters=json.loads(nativeFilters) if nativeFilters is not None else None
        if native_filters is not None and not isinstance(native_filters,list):
            raise CatalogueError('Format des filtres APK invalide.')
        return await source_catalogue.browse(source_id, mode, q, tags, order, cursor,native_filters)
    except SeanimeRuntimeError as exc:
        raise HTTPException(502, str(exc)) from exc
    except CatalogueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError,RecursionError) as exc:
        raise HTTPException(400,'Filtres de source invalides.') from exc


@router.get("/{source_id}/catalogue/stream")
async def stream_catalogue(
    source_id: str,
    mode: str = 'latest',
    q: str = Query('', max_length=250),
    tags: list[str] = Query(default=[]),
    order: str = 'source',
    cursor: str | None = Query(None, max_length=64),
    nativeFilters: str | None = Query(None, max_length=32768),
):
    if len(tags) > 12:
        raise HTTPException(400, "Sélectionnez au maximum douze genres")
    try:
        native_filters = json.loads(nativeFilters) if nativeFilters is not None else None
        if native_filters is not None and not isinstance(native_filters, list):
            raise CatalogueError('Format des filtres APK invalide.')
    except CatalogueError as exc:
        raise HTTPException(400, str(exc)) from exc
    except (ValueError, RecursionError) as exc:
        raise HTTPException(400, 'Filtres de source invalides.') from exc

    async def event_stream():
        try:
            async for event in source_catalogue.browse_stream(
                source_id, mode, q, tags, order, cursor, native_filters
            ):
                yield json.dumps(event, ensure_ascii=False) + "\n"
        except VerificationRequired as exc:
            payload = {"type": "error", "status": 409, **exc.to_dict()}
            payload.setdefault("problem", problem_for(409, payload).model_dump())
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except RateLimited as exc:
            payload = {"type": "error", "status": 429, "error": MESSAGES['rate_limit'], "code": "rate_limited", "retryAfter": exc.retry_after}
            payload["problem"] = problem_for(429, payload).model_dump()
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except CatalogueError as exc:
            payload = {"type": "error", "status": 400, "error": str(exc)}
            payload["problem"] = problem_for(400, payload).model_dump()
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except APIProblem as exc:
            payload = {"type": "error", "status": exc.status, "error": str(exc), "code": exc.problem.code, "problem": exc.problem.model_dump()}
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except SeanimeRuntimeError as exc:
            payload = {"type": "error", "status": 502, "error": str(exc), "code": "upstream_error"}
            payload["problem"] = problem_for(502, payload).model_dump()
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except httpx.RequestError as exc:
            code = 'network_' + exc.kind if isinstance(exc, SourceNetworkError) else 'network_error'
            payload = {"type": "error", "status": 502, "error": MESSAGES['network'], "code": code}
            payload["problem"] = problem_for(502, payload).model_dump()
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except httpx.HTTPStatusError as exc:
            status = 429 if exc.response.status_code == 429 else 502
            payload = {"type": "error", "status": status, "error": MESSAGES['network'], "code": "upstream_error"}
            payload["problem"] = problem_for(status, payload).model_dump()
            yield json.dumps(payload, ensure_ascii=False) + "\n"
        except Exception as exc:
            logger.error("[router.sources] Streaming catalogue failed for %s: %s", source_id, exc)
            payload = {"type": "error", "status": 500, "error": MESSAGES['internal'], "problem": problem_for(500, {}).model_dump()}
            yield json.dumps(payload, ensure_ascii=False) + "\n"

    return StreamingResponse(
        event_stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.get("/settings")
async def get_all_source_settings():
    """Retourne la liste de toutes les sources (natives et extensions importées)
    avec leurs paramètres respectifs.
    """
    try:
        sources = source_settings_service.get_all_sources_with_settings()
        return {
            "success": True,
            "sources": sources,
        }
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error("[router.sources] Error fetching source settings: %s", e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.get("/settings/{source_id}")
async def get_source_settings(source_id: str):
    """Retourne les paramètres d'une source spécifique."""
    try:
        settings = source_settings_service.get_source_settings(source_id)
        return {
            "success": True,
            "sourceId": source_id,
            "settings": settings,
        }
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error("[router.sources] Error reading source %s: %s", source_id, e)
        return JSONResponse(status_code=500, content={"success": False, "error": str(e)})


@router.post("/settings/{source_id}")
async def save_source_settings(source_id: str, request: Request):
    """Enregistre ou met à jour la configuration d'une source spécifique."""
    try:
        body = await request.json()
        if not isinstance(body, dict):
            return JSONResponse(status_code=400, content={"success": False, "error": "Format JSON invalide"})

        updated = source_settings_service.save_source_settings(source_id, body)
        return {
            "success": True,
            "sourceId": source_id,
            "settings": updated,
            "message": "Paramètres de la source mis à jour avec succès",
        }
    except VerificationRequired:
        raise
    except Exception as e:
        logger.error("[router.sources] Error saving source %s: %s", source_id, e)
        return JSONResponse(status_code=400, content={"success": False, "error": str(e)})
