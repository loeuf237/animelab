"""Versioned, additive API errors. Legacy error/detail fields remain readable."""
import json
from typing import Literal
import httpx
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from starlette.exceptions import HTTPException

Category = Literal['protection', 'network', 'rate_limit', 'media', 'permission', 'export', 'validation', 'conflict', 'not_found', 'internal']
Action = Literal['verify', 'retry', 'wait', 'storage_settings', 'retry_export', 'open_site', 'none']


class Problem(BaseModel):
    code: str
    category: Category
    messageKey: str
    action: Action = 'none'
    retryAfter: float | None = None
    domain: str | None = None
    url: str | None = None


MESSAGES = {
    'protection': 'Le site demande une vérification.',
    'network': 'La connexion au site a échoué. Réessayez.',
    'rate_limit': 'Le site limite les requêtes. Patientez avant de réessayer.',
    'media': 'Le média ne peut pas être traité. Réessayez le téléchargement.',
    'permission': 'Autorisez le stockage dans les paramètres.',
    'export': 'La publication a échoué. Réessayez depuis la copie locale.',
    'validation': 'Certains paramètres sont invalides.',
    'conflict': 'Une opération est déjà en cours ou entre en conflit.',
    'not_found': 'La ressource demandée est introuvable.',
    'internal': 'Une erreur interne est survenue.',
}
ACTIONS = {'protection': 'verify', 'network': 'retry', 'rate_limit': 'wait', 'media': 'retry',
           'permission': 'storage_settings', 'export': 'retry_export'}


class APIProblem(RuntimeError):
    def __init__(self, code: str, *, status=400, category: Category = 'validation', action: Action | None = None):
        self.status = status
        self.problem = Problem(code=code, category=category, messageKey={
            'source_operation_unsupported': 'Cette source ne propose pas cette fonctionnalité.',
            'extension_untrusted': 'Approuvez la version et le signataire de cet APK avant son exécution.',
            'extension_abi_incompatible': 'Les classes ou bibliothèques de cet APK sont incompatibles avec le moteur actuel.',
            'extension_runtime_unavailable': 'Le moteur APK est indisponible. Réessayez son chargement.',
            'extension_runtime_timeout': 'L’extension a dépassé le délai autorisé. Son worker a été arrêté.',
            'extension_runtime_busy': 'Le moteur APK est occupé. Attendez la fin des appels en cours.',
            'extension_runtime_error': 'Le code de l’extension a échoué pendant cette opération.',
            'cancelled': 'L’opération de l’extension a été annulée.',
            'verification_route_changed': 'La route réseau a changé. Fermez cette fenêtre et recommencez la vérification.',
            'verification_cancelled': 'Cette vérification est fermée. Ouvrez une nouvelle fenêtre.',
            'verification_mode_unavailable': 'Ce mode de vérification est indisponible pour cette plateforme ou ce proxy.',
        }.get(code, MESSAGES[category]),
                               action=action or ACTIONS.get(category, 'none'))
        super().__init__(self.problem.messageKey)


def problem_for(status, payload, path='', *, category=None):
    code = payload.get('code')
    if not category:
        category = ('protection' if code == 'verification_required' else
                    'permission' if code == 'storage_permission_required' else
                    'export' if code == 'export_failed' else
                    'rate_limit' if status == 429 else 'permission' if status == 403 else
                    'not_found' if status == 404 else 'validation' if status in (400, 422, 413) else
                    'conflict' if status == 409 else 'network' if status in (502, 503, 504) else 'internal')
    return Problem(code=code or category + '_error', category=category, messageKey=MESSAGES[category],
                   action=ACTIONS.get(category, 'none'), domain=payload.get('domain'), url=payload.get('url'),
                   retryAfter=payload.get('retryAfter'))


def install_error_handlers(app):
    from animelab.services.source_http import VerificationRequired, RateLimited, SourceNetworkError

    @app.exception_handler(APIProblem)
    async def application_problem(request, exc):
        return JSONResponse(status_code=exc.status, content={'error': str(exc), 'code': exc.problem.code,
                                                             'problem': exc.problem.model_dump()})

    @app.exception_handler(HTTPException)
    async def http_error(request, exc):
        return JSONResponse(status_code=exc.status_code, content={'detail': exc.detail, **({'error': exc.detail} if isinstance(exc.detail, str) else {})}, headers=exc.headers)

    @app.exception_handler(RequestValidationError)
    async def invalid_request(request, exc):
        # Keep FastAPI's locations/types without echoing passwords, URLs or input.
        details = [{k: error[k] for k in ('type', 'loc', 'msg') if k in error} for error in exc.errors()]
        return JSONResponse(status_code=422, content={'detail': details})

    @app.exception_handler(VerificationRequired)
    async def challenge(request, exc):
        return JSONResponse(status_code=409, content=exc.to_dict())

    @app.exception_handler(RateLimited)
    async def rate_limit(request, exc):
        return JSONResponse(status_code=429, content={'error': MESSAGES['rate_limit'], 'code': 'rate_limited',
                            'retryAfter': exc.retry_after}, headers={'Retry-After': str(max(1, int(exc.retry_after)))})

    @app.exception_handler(httpx.RequestError)
    async def network_error(request, exc):
        code = 'network_' + exc.kind if isinstance(exc, SourceNetworkError) else 'network_error'
        return JSONResponse(status_code=502, content={'error': MESSAGES['network'], 'code': code})

    @app.exception_handler(httpx.HTTPStatusError)
    async def upstream_error(request, exc):
        status = 429 if exc.response.status_code == 429 else 502
        return JSONResponse(status_code=status, content={'error': MESSAGES['network'], 'code': 'upstream_error'})

    @app.exception_handler(PermissionError)
    async def permission_error(request, exc):
        return JSONResponse(status_code=403, content={'error': MESSAGES['permission'], 'code': 'storage_permission_required'})

    @app.exception_handler(Exception)
    async def unexpected_error(request, exc):
        import logging
        logging.getLogger('animelab.api').error('Unhandled API failure at %s', request.url.path, exc_info=exc)
        problem = problem_for(500, {})
        return JSONResponse(status_code=500, content={'error': MESSAGES['internal'], 'problem': problem.model_dump()},
                            headers={'X-Animan-API-Version': '1'})


class ErrorContractMiddleware:
    """Normalize JSON failures only; never buffer videos, SSE or successful feeds."""
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http' or not scope.get('path', '').startswith('/api/'):
            return await self.app(scope, receive, send)
        start, chunks, pending = None, [], False
        async def wrapped(message):
            nonlocal start, pending
            if message['type'] == 'http.response.start':
                start = message.copy()
                start['headers'] = list(message.get('headers', [])) + [(b'x-animan-api-version', b'1')]
                content_type = dict(start['headers']).get(b'content-type', b'')
                pending = start['status'] >= 400 and b'application/json' in content_type
                if not pending:
                    await send(start)
            elif message['type'] == 'http.response.body' and pending:
                chunks.append(message.get('body', b''))
                if message.get('more_body'):
                    return
                body = b''.join(chunks)
                try:
                    payload = json.loads(body)
                    if isinstance(payload, dict):
                        payload.setdefault('problem', problem_for(start['status'], payload, scope['path']).model_dump())
                        body = json.dumps(payload, ensure_ascii=False).encode()
                except (ValueError, TypeError):
                    pass
                start['headers'] = [(k, v) for k, v in start['headers'] if k.lower() != b'content-length'] + [(b'content-length', str(len(body)).encode())]
                await send(start)
                await send({'type': 'http.response.body', 'body': body})
            else:
                await send(message)
        await self.app(scope, receive, wrapped)
