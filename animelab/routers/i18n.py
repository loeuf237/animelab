from animelab.api_contracts import ContractRoute
from fastapi import APIRouter, Request, Response, Query
from fastapi.responses import JSONResponse
from animelab.services.i18n_service import i18n_service, SUPPORTED_LANGUAGES, DEFAULT_LANGUAGE, current_lang

router = APIRouter(route_class=ContractRoute, tags=["i18n"])

@router.get("/api/i18n")
async def get_translations(lang: str = Query(None)):
    """Retourne le catalogue de traductions pour le frontend."""
    if not lang or lang not in SUPPORTED_LANGUAGES:
        lang = current_lang()
    return {
        "language": lang,
        "supported": list(SUPPORTED_LANGUAGES),
        "translations": i18n_service.get_catalog(lang),
        "all": i18n_service.get_all_catalogs(),
    }

@router.post("/api/i18n/set-language")
async def set_language(request: Request, response: Response):
    """Définit la langue active de l'utilisateur via cookie."""
    try:
        data = await request.json()
    except Exception:
        data = {}
    lang = data.get("language", DEFAULT_LANGUAGE)
    if lang not in SUPPORTED_LANGUAGES:
        return JSONResponse(status_code=400, content={"success": False, "error": f"Unsupported language '{lang}'"})

    res = JSONResponse(content={"success": True, "language": lang})
    res.set_cookie(key="animan_lang", value=lang, max_age=31536000, httponly=False, samesite="lax")
    return res
