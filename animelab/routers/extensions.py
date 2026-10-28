from animelab.api_contracts import ContractRoute
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query
from fastapi.responses import JSONResponse

from animelab.services.extension_service import extension_service

logger = logging.getLogger("animelab.router.extensions")
router = APIRouter(route_class=ContractRoute)


@router.post("/api/extensions/import-repo")
async def import_repo_api(payload: dict = Body(...)):
    """Importe massivement un nouveau magasin d'extensions."""
    url = payload.get("url", "").strip()
    if not url:
        raise HTTPException(status_code=400, detail="Veuillez fournir une URL de magasin valide.")

    try:
        result = await extension_service.import_repository(url)
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("[router.extensions] Error importing repository: %s", e)
        raise HTTPException(status_code=500, detail=f"Internal error during import: {e}")


@router.post("/api/extensions/{ext_id}/toggle")
async def toggle_extension_api(ext_id: int, payload: dict = Body(...)):
    """Active ou désactive une extension à la demande de l'utilisateur."""
    enabled = payload.get("enabled", False)
    if not isinstance(enabled, bool):
        raise HTTPException(status_code=400, detail="enabled doit être un booléen.")
    try:
        result = await extension_service.toggle_extension(ext_id, enabled)
        return JSONResponse(content=result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("[router.extensions] Error toggling extension %d: %s", ext_id, e)
        raise HTTPException(status_code=500, detail=f"Error toggling extension: {e}")


@router.get("/api/extensions/list")
async def list_extensions_api(
    q: Optional[str] = Query(None),
    lang: Optional[str] = Query(None),
    enabled_only: bool = Query(False)
):
    """Retourne la liste JSON des extensions visibles (uniquement du dernier magasin actif)."""
    active_repo = extension_service.get_active_repository()
    extensions = extension_service.get_visible_extensions(query=q, lang=lang, enabled_only=enabled_only)
    updates_count = sum(1 for e in extensions if e.get("has_update"))
    return JSONResponse(content={
        "active_repo": active_repo,
        "repositories": extension_service.list_repositories(),
        "count": len(extensions),
        "updates_count": updates_count,
        "extensions": extensions
    })


@router.post("/api/extensions/refresh")
async def refresh_extensions_api():
    try:
        return await extension_service.refresh_repositories()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get('/api/extensions/repositories')
async def list_repositories_api():
    return {'repositories': extension_service.list_repositories()}


@router.put('/api/extensions/repositories/{repo_id}')
async def set_repository_api(repo_id: int, payload: dict = Body(...)):
    try:
        return extension_service.set_repository_enabled(repo_id, payload.get('enabled'))
    except ValueError as exc:
        raise HTTPException(400, str(exc)) from exc


@router.post("/api/extensions/check-updates")
async def check_updates_api():
    """Vérifie si de nouvelles versions sont disponibles dans le dépôt actif sans écraser les extensions installées."""
    try:
        return await extension_service.check_updates()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/extensions/update-all")
async def update_all_extensions_api():
    """Met à jour toutes les extensions disposant d'une nouvelle version."""
    try:
        return await extension_service.update_all_extensions()
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/extensions/{ext_id}/update")
async def update_extension_api(ext_id: int):
    """Met à jour une extension spécifique vers la dernière version disponible."""
    try:
        return await extension_service.update_extension(ext_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/extensions/{ext_id}/recompile")
async def recompile_extension_api(ext_id: int):
    """Recompile la recette DEX d'une extension depuis son APK."""
    try:
        return await extension_service.recompile_extension(ext_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.put("/api/extensions/{ext_id}/recipe")
async def configure_extension_api(ext_id: int, payload: dict = Body(...)):
    try:
        return await extension_service.configure_extension(ext_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.post("/api/extensions/{ext_id}/diagnose")
async def diagnose_extension_api(ext_id: int):
    try:
        return await extension_service.diagnose_extension(ext_id)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc))


@router.get('/api/extensions/{ext_id}/recipe-history')
async def extension_recipe_history(ext_id: int):
    try: return extension_service.recipe_history(ext_id)
    except ValueError as exc: raise HTTPException(404,str(exc)) from exc


from pydantic import BaseModel,Field
class RestoreRecipeRequest(BaseModel):
    revision: int = Field(ge=1)


@router.post('/api/extensions/{ext_id}/recipe-restore')
async def restore_extension_recipe(ext_id: int, body: RestoreRecipeRequest):
    try: return await extension_service.restore_recipe(ext_id,body.revision)
    except ValueError as exc: raise HTTPException(400,str(exc)) from exc
