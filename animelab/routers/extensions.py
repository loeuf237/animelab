from animelab.api_contracts import ContractRoute
import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query, Request
from fastapi.responses import JSONResponse

from animelab.services.extension_service import extension_service

logger = logging.getLogger("animelab.router.extensions")
router = APIRouter(route_class=ContractRoute)


@router.get('/api/extensions/backup')
async def backup_extensions_api(include_artifacts: bool = False):
    import asyncio
    from fastapi.responses import Response
    from animelab.services.extension_backup import export_backup
    try:
        content=await asyncio.to_thread(export_backup,extension_service,include_artifacts)
        return Response(content,media_type='application/zip',headers={'Content-Disposition':'attachment; filename="animelab-extensions.zip"','Cache-Control':'no-store'})
    except ValueError as error:
        raise HTTPException(400,str(error)) from error


@router.post('/api/extensions/backup/restore')
async def restore_extensions_api(request: Request):
    import asyncio
    from animelab.services.extension_backup import restore_backup, MAX_BACKUP
    raw=bytearray()
    async for chunk in request.stream():
        raw.extend(chunk)
        if len(raw)>MAX_BACKUP:
            raise HTTPException(413,'Sauvegarde trop volumineuse.')
    try:
        return await asyncio.to_thread(restore_backup,extension_service,raw)
    except (ValueError,KeyError,TypeError) as error:
        raise HTTPException(400,'Sauvegarde invalide : '+str(error)) from error


@router.get('/api/extensions/android')
async def android_extensions_api():
    import asyncio
    from animelab.services import android_extensions
    packages = await asyncio.to_thread(extension_service.sync_android_extensions)
    return {'available':android_extensions.available(), 'packages':packages,
            'operations':await extension_service.android_operation_states(), 'securityBoundary':'same-uid-worker',
            'privateOtherAppStorageAccessible':False}


@router.post('/api/extensions/android/{pkg}/trust')
async def trust_android_extension(pkg: str, payload: dict = Body(...)):
    import asyncio, re
    from animelab.services import android_extensions
    if payload.get('approved') is not True or not re.fullmatch(r'[0-9a-f]{64}', str(payload.get('signer',''))):
        raise HTTPException(400,'Confirmez explicitement le signataire et la version APK.')
    result = await android_extensions.invoke(pkg,'trust',signer=payload['signer'],versionCode=str(payload.get('versionCode','')))
    with extension_service._get_conn() as conn:
        conn.execute("UPDATE imported_extensions SET is_enabled=1 WHERE pkg=? AND runtime='android-apk'",(pkg,))
    await asyncio.to_thread(extension_service.sync_android_extensions)
    return result


@router.post('/api/extensions/android/operations/{operation_id}/cancel')
async def cancel_android_installation(operation_id: str):
    from animelab.services import android_extensions
    return {'operation':await android_extensions.cancel_installation(operation_id)}


@router.post('/api/extensions/android/{pkg}/revoke')
async def revoke_android_extension(pkg: str):
    import asyncio
    from animelab.services import android_extensions
    result = await android_extensions.invoke(pkg,'revoke')
    await asyncio.to_thread(extension_service.sync_android_extensions)
    return result


@router.delete('/api/extensions/android/{pkg}')
async def uninstall_android_extension(pkg: str):
    from animelab.services import android_extensions
    return {'operation':await android_extensions.uninstall(pkg),'shared':True}


@router.post('/api/extensions/android/install-apk')
async def import_android_apk(request: Request):
    import hashlib, tempfile
    from pathlib import Path
    from animelab.services import android_extensions
    from animelab.services.extension_service import APKS_DIR
    if not android_extensions.available():
        raise HTTPException(400,'Installation APK réservée à Android.')
    path = None
    try:
        with tempfile.NamedTemporaryFile(dir=APKS_DIR,delete=False) as stream:
            path=Path(stream.name)
            size=0
            async for chunk in request.stream():
                size+=len(chunk)
                if size > 64*1024*1024:
                    raise HTTPException(413,'APK trop volumineux.')
                stream.write(chunk)
        inspected = await android_extensions.inspect(path)
        with path.open('rb') as artifact:
            digest=hashlib.file_digest(artifact,'sha256').hexdigest()
        if digest != inspected['sha256']:
            raise HTTPException(400,'APK modifié pendant son inspection.')
        final=APKS_DIR/(digest+'.apk')
        path.replace(final); path=None
        return {'operation':await android_extensions.install(final,inspected['pkg'])}
    finally:
        if path:
            path.unlink(missing_ok=True)


@router.post('/api/extensions/android/sources/{source_id}/{operation}')
async def call_android_source(source_id: str, operation: str, payload: dict = Body(default={})):
    from animelab.services import android_extensions
    if operation == 'state':
        import asyncio
        try:
            return await asyncio.to_thread(extension_service.set_source_state,source_id,payload)
        except ValueError as error:
            raise HTTPException(400,str(error)) from error
    if operation not in ('filters','preferences','set_preferences','seasons','related','search','popular','latest'):
        raise HTTPException(400,'Opération de source inconnue.')
    source=extension_service.get_container_source_by_id(source_id)
    if source is None or not isinstance(source,android_extensions.AndroidAPKSource):
        raise HTTPException(404,'Source APK non chargée.')
    return {'result':await source.call(operation,payload)}


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


@router.post('/api/extensions/repositories/{repo_id}/approve-key')
async def approve_repository_key(repo_id: int, payload: dict = Body(...)):
    if payload.get('approved') is not True:
        raise HTTPException(400,'Approbation explicite requise.')
    try:
        return extension_service.approve_repository_key(repo_id,payload.get('fingerprint'))
    except ValueError as exc:
        raise HTTPException(400,str(exc)) from exc


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
