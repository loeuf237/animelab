import json
from unittest.mock import AsyncMock

import httpx
import pytest
from fastapi import FastAPI
from pydantic import ValidationError

from animelab.api_contracts import ContractRoute, DownloadTaskResponse, install_contract_schema
from animelab.api_errors import ErrorContractMiddleware, install_error_handlers, APIProblem
from animelab.services.source_http import VerificationRequired, SourceNetworkError, RateLimited


def api_app():
    app = FastAPI()
    app.router.route_class = ContractRoute
    install_error_handlers(app)
    app.add_middleware(ErrorContractMiddleware)
    install_contract_schema(app)
    return app


@pytest.mark.asyncio
@pytest.mark.parametrize('error,status,category,action', [
    (VerificationRequired('https://source.example/blocked'), 409, 'protection', 'verify'),
    (SourceNetworkError('private URL', 'dns', 'https://source.example'), 502, 'network', 'retry'),
    (PermissionError('private path'), 403, 'permission', 'storage_settings'),
    (APIProblem('mux_failed', status=422, category='media'), 422, 'media', 'retry'),
    (APIProblem('export_failed', status=409, category='export'), 409, 'export', 'retry_export'),
])
async def test_errors_are_structured_and_keep_legacy_message(error, status, category, action):
    app = api_app()
    @app.get('/api/fail')
    async def fail(): raise error
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.get('/api/fail')
    assert response.status_code == status
    assert response.headers['x-animan-api-version'] == '1'
    result = response.json()
    assert result['error']
    assert result['problem']['category'] == category
    assert result['problem']['action'] == action
    assert 'private' not in response.text


@pytest.mark.asyncio
async def test_rate_limit_keeps_retry_after_and_binary_response_streams():
    app = api_app()
    @app.get('/api/fail')
    async def fail():
        raise RateLimited(httpx.Response(429, request=httpx.Request('GET', 'https://source.example')), 7)
    from fastapi.responses import StreamingResponse
    @app.get('/api/binary')
    async def binary():
        async def chunks():
            yield b'first'
            yield b'last'
        return StreamingResponse(chunks(), media_type='video/mp4', status_code=206)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.get('/api/fail')
        assert response.status_code == 429
        assert response.headers['retry-after'] == '7'
        assert response.json()['problem']['retryAfter'] == 7
        assert (await client.get('/api/binary')).content == b'firstlast'


@pytest.mark.asyncio
async def test_invalid_download_is_rejected_before_queueing_and_does_not_echo_secrets(monkeypatch):
    from animelab.routers.download import router
    from animelab.services.download_manager import download_manager
    start = AsyncMock()
    monkeypatch.setattr(download_manager, 'start_download', start)
    app = api_app(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.post('/api/download', json={'url': 'https://example.com', 'episodeNumber': 'secret-value'})
    assert response.status_code == 422
    assert response.json()['problem']['category'] == 'validation'
    assert 'secret-value' not in response.text
    start.assert_not_called()
    schema = app.openapi()
    body = schema['paths']['/api/download']['post']['requestBody']
    definition = body['content']['application/json']['schema']
    if '$ref' in definition: definition = schema['components']['schemas'][definition['$ref'].rsplit('/', 1)[-1]]
    assert definition['properties']['episodeNumber']['type'] == 'integer'


def test_schema_download_response_detects_contract_drift():
    from animelab.models.download_task import DownloadTask
    wire = DownloadTask().to_dict()
    assert DownloadTaskResponse.model_validate(wire).exportUris == []
    with pytest.raises(ValidationError):
        DownloadTaskResponse.model_validate({**wire, 'exportStatus': 'invented'})


@pytest.mark.asyncio
async def test_legacy_json_error_retains_fields():
    from fastapi.responses import JSONResponse
    app = api_app()
    @app.get('/api/legacy')
    async def legacy():
        return JSONResponse(status_code=409, content={'success': False, 'code': 'export_failed', 'error': 'Export failed', 'task': {'id': 'id'}})
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        result = (await client.get('/api/legacy')).json()
    assert result['task'] == {'id': 'id'}
    assert result['code'] == 'export_failed'
    assert result['problem']['action'] == 'retry_export'


@pytest.mark.asyncio
async def test_legacy_metadata_failure_keeps_http_status_and_adds_media_advice():
    app = api_app()
    @app.get('/api/episode/size')
    async def get_episode_size():
        return {'success': False, 'size': -1, 'formattedSize': 'Taille inconnue'}
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.get('/api/episode/size')
    assert response.status_code == 200
    assert response.json()['size'] == -1
    assert response.json()['problem']['category'] == 'media'
    assert response.json()['problem']['action'] == 'retry'


@pytest.mark.asyncio
async def test_active_media_worker_cannot_be_cancelled_or_deleted(monkeypatch):
    from animelab.routers.download import router
    from animelab.services.download_manager import download_manager
    monkeypatch.setattr(download_manager, '_export_in_progress', lambda task_id: True)
    app = api_app(); app.include_router(router)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url='http://test') as client:
        response = await client.delete('/api/download/active-media-task')
    assert response.status_code == 409
    assert response.json()['problem']['category'] == 'conflict'
