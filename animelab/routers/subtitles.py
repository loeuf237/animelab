"""Download permission applies to this whole task-local subtitle API."""
import asyncio
from typing import Literal
from fastapi import APIRouter, Request, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from animelab.services.download_manager import download_manager
from animelab.services.download_subtitles import DownloadSubtitles
from animelab.services.subtitle_provider import ProviderError, SubtitleQuery, MAX_FILE
from animelab.services.subtitle_sync import TimingCorrection, capabilities as sync_capabilities

router = APIRouter(prefix='/api/download')


def service():
    if not hasattr(download_manager, '_subtitle_library'):
        download_manager._subtitle_library = DownloadSubtitles(download_manager)
    return download_manager._subtitle_library


def error(exc):
    headers = {'Retry-After': str(exc.retry_after)} if exc.retry_after else {}
    category = 'rate_limit' if exc.status == 429 else 'network' if exc.status >= 500 else 'validation'
    # 401 on the shared gateway denotes an expired AnimeLab login, not an
    # expired third-party token. Keep these sessions independent.
    status = 424 if exc.status == 401 else exc.status
    return JSONResponse(status_code=status, content={'error': str(exc), 'code': exc.code,
        'problem': dict(code=exc.code, category=category, messageKey=str(exc),
                        action='wait' if exc.status == 429 else 'none', retryAfter=exc.retry_after)}, headers=headers)


class Credentials(BaseModel):
    model_config = ConfigDict(extra='forbid')
    apiKey: SecretStr | None = Field(default=None, max_length=4096)
    username: str = Field(default='', max_length=256)
    password: SecretStr = Field(default='', max_length=1024)
    remember: bool = False


class Attach(BaseModel):
    model_config = ConfigDict(extra='forbid')
    importId: str = Field(pattern=r'^[0-9a-f]{32}$')
    entryId: str = Field(pattern=r'^[0-9a-f]{32}$')
    language: str = Field(default='und', pattern=r'^[a-z]{2,3}(?:-[a-z]{2})?$')
    label: str = Field(default='', max_length=255)
    confirmedEpisode: bool = False


class ProviderPreview(BaseModel):
    model_config = ConfigDict(extra='forbid')
    resultId: str = Field(pattern=r'^[0-9a-f]{32}$')


@router.get('/subtitle-provider')
async def get_provider(provider: Literal['opensubtitles', 'subdl'] = 'opensubtitles'):
    return service().get_provider(provider).status()


@router.put('/subtitle-provider')
async def configure_provider(body: Credentials, provider: Literal['opensubtitles', 'subdl'] = 'opensubtitles'):
    try:
        result = await service().get_provider(provider).configure(
            body.apiKey.get_secret_value() if body.apiKey else None, body.username,
            body.password.get_secret_value() if isinstance(body.password, SecretStr) else '', body.remember)
        service().results.clear()
        return result
    except ProviderError as exc:
        return error(exc)


@router.delete('/subtitle-provider')
async def forget_provider(provider: Literal['opensubtitles', 'subdl'] = 'opensubtitles'):
    try:
        result = await service().get_provider(provider).forget()
        service().results.clear()
        return result
    except ProviderError as exc:
        return error(exc)


@router.get('/{task_id}/subtitles/context')
async def context(task_id: str):
    try:
        return await service().video_context(task_id)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/import')
async def upload_subtitles(task_id: str, request: Request,
                           filename: str = Query(max_length=255),
                           encoding: Literal['auto', 'utf-8', 'windows-1252', 'iso-8859-1'] = 'auto'):
    try:
        service().task(task_id)
        content = bytearray()
        async for chunk in request.stream():
            content.extend(chunk)
            if len(content) > MAX_FILE:
                raise ProviderError('Import limité à 10 Mo compressés', 'subtitle_size', 413)
        return await service().upload(task_id, bytes(content), filename, encoding)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/attach')
async def attach_subtitle(task_id: str, body: Attach):
    try:
        return await service().attach(task_id, body.importId, body.entryId, body.language, body.label, body.confirmedEpisode)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/search')
async def search_subtitles(task_id: str, body: SubtitleQuery):
    try:
        return await service().search(task_id, body)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/provider-preview')
async def preview_provider(task_id: str, body: ProviderPreview):
    try:
        return await service().provider_preview(task_id, body.resultId)
    except ProviderError as exc:
        return error(exc)


@router.get('/subtitle-sync-capabilities')
async def get_sync_capabilities():
    return await asyncio.to_thread(sync_capabilities)


@router.get('/{task_id}/subtitles/imports/{import_id}')
async def get_import(task_id: str, import_id: str):
    try:
        return await service().blocking(service().package, service().task(task_id), import_id)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/transform')
async def transform_subtitle(task_id: str, body: TimingCorrection):
    try:
        return await service().transform(task_id, body)
    except ProviderError as exc:
        return error(exc)


@router.post('/{task_id}/subtitles/cancel-sync')
async def cancel_sync(task_id: str):
    return {'cancelled': service().cancel_sync(task_id)}


@router.post('/{task_id}/subtitles/tracks/{track_id}/restore')
async def restore_subtitle_track(task_id: str, track_id: str):
    try:
        return await service().restore_track(task_id, track_id)
    except ProviderError as exc:
        return error(exc)
