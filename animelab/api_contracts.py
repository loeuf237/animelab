from animelab.services.playback_service import PlaybackState
"""JSON boundary contracts for the public API (wire format version 1).

Models validate legacy handlers too. Dynamic source settings and recipe keys are
JSON values, never executable objects. Binary media and SSE keep streaming.
"""
import json
from typing import Literal

from fastapi import Request
from fastapi.exceptions import RequestValidationError
from fastapi.routing import APIRoute
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter, ValidationError
from animelab.models.anime import AnimeResult, AnimeDetail, Episode
from animelab.api_errors import Problem, problem_for
from animelab.services.output_profiles import OutputProfile


class WireModel(BaseModel):
    model_config = ConfigDict(extra='allow')  # Preserve existing additive fields.


class URLRequest(WireModel):
    url: str = Field(min_length=1, max_length=4096)


class DownloadRequest(URLRequest):
    url: str = Field(default='', max_length=4096)
    animeName: str = Field(default='Unknown', max_length=500)
    animeUrl: str = Field(default='', max_length=4096)
    episodeNumber: int = Field(default=0, ge=0)
    fileName: str | None = Field(default=None, max_length=500)
    version: str = Field(default='', max_length=40)
    subtitleUrl: str | None = Field(default=None, max_length=4096)
    downloadSubtitles: bool = False
    source: str = Field(default='french-manga', max_length=255)
    selectedServer: str | None = Field(default=None, max_length=100)
    selectedQuality: str | None = Field(default=None, max_length=100)
    scheduledTime: str | None = None
    speedLimit: int | None = Field(default=None, ge=0)
    outputProfile: OutputProfile | None = None


class BatchEpisode(URLRequest):
    number: int = Field(ge=0)
    version: str = Field(default='', max_length=40)
    animeUrl: str = ''
    title: str | None = None
    fileName: str | None = None
    subtitleUrl: str | None = None
    downloadSubtitles: bool = False
    source: str | None = None
    selectedServer: str | None = None
    selectedQuality: str | None = None
    outputProfile: OutputProfile | None = None


class BatchRequest(WireModel):
    animeName: str = 'Unknown'
    source: str = 'french-manga'
    episodes: list[BatchEpisode] = Field(min_length=1, max_length=2000)
    preferredServer: str | None = None
    preferredQuality: str | None = None


class SpeedRequest(WireModel):
    limit: int = Field(default=0, ge=0)


class SeriesRequest(WireModel):
    animeName: str = Field(min_length=1, max_length=500)


class DownloadSettings(WireModel):
    maxConcurrentDownloads: int = Field(default=3, ge=1, le=32)
    globalSpeedLimit: int = Field(default=0, ge=0)
    plexOrganization: bool = False
    selectedUserAgent: str | None = None
    voiranimeDefaultServer: str | None = None


class ProxySettings(WireModel):
    enabled: bool = False
    proxy_type: str | None = None
    host: str | None = None
    port: int | None = Field(default=None, ge=1, le=65535)
    username: str | None = None
    password: str | None = None
    custom_url: str | None = None
    proxyType: str | None = None
    customUrl: str | None = None


class ProxyTest(WireModel):
    proxyUrl: str = ''
    settings: ProxySettings | None = None


class ToggleRequest(WireModel):
    enabled: bool


class WatchedRequest(WireModel):
    animeUrl: str = Field(min_length=1, max_length=4096)
    animeName: str = ''
    episodeNumber: int = Field(default=0, ge=0)
    version: str = ''
    watched: bool = True


class StorageAction(WireModel):
    action: Literal['choose_directory', 'use_downloads', 'notifications', 'app_settings', 'open_downloads']


class ExportRequest(WireModel):
    taskId: str = Field(min_length=1, max_length=36)


class LanguageRequest(WireModel):
    language: Literal['fr', 'en']


class DownloadTaskResponse(WireModel):
    id: str
    animeName: str
    episodeNumber: int
    fileName: str
    status: Literal['PENDING', 'DOWNLOADING', 'PAUSED', 'COMPLETED', 'FAILED', 'CANCELLED', 'SCHEDULED', 'RETRYING', 'MUXING', 'VERIFICATION_REQUIRED']
    progress: float
    downloadedBytes: int
    totalBytes: int
    phase: str | None = None
    error: str | None = None
    exportStatus: Literal['NOT_REQUESTED', 'PENDING', 'EXPORTING', 'EXPORTED', 'EXPORT_FAILED'] = 'NOT_REQUESTED'
    exportUris: list[str] = []
    exportError: str | None = None
    exportAttempts: int = 0


class Result(WireModel):
    success: bool
    message: str | None = None
    error: str | None = None
    problem: Problem | None = None
    taskId: str | None = None
    task: DownloadTaskResponse | None = None
    count: int | None = None
    resumed: int | None = None


class ErrorResponse(WireModel):
    problem: Problem
    code: str | None = None
    error: str | None = None
    detail: str | list[dict[str, JsonValue]] | None = None


class SearchResponse(WireModel):
    results: list[AnimeResult]
    challenges: list[dict[str, JsonValue]]
    errors: list[dict[str, JsonValue]]


class SourceFeed(WireModel):
    source: str
    releases: list[AnimeResult]
    page: int = 1



class ModeCapability(WireModel):
    id: Literal['manual', 'browser', 'webview']
    available: bool
    capturesCookies: bool
    reason: str | None


class NetworkSession(WireModel):
    domain: str
    verificationRequired: bool
    usesProxy: bool
    modes: list[ModeCapability]


class NetworkOptions(WireModel):
    browsers: list[dict[str, str]]
    webviewAvailable: bool
    platform: Literal['desktop', 'android']
    clientLocal: bool
    modes: list[ModeCapability]
    sessions: list[NetworkSession]


class VerificationJob(WireModel):
    id: str
    domain: str
    mode: Literal['browser', 'webview']


class VerificationResult(Result):
    domain: str
    resumed: int = 0


class StorageState(WireModel):
    android: bool = True
    apiLevel: int = 0
    mode: Literal['downloads', 'directory'] = 'downloads'
    destination: str = ''
    authorized: bool
    selectionPending: bool = False
    notificationsGranted: bool = False
    error: str | None = None
    exportError: str | None = None


class StorageResponse(WireModel):
    totalBytes: int | None
    usedBytes: int | None
    freeBytes: int | None
    usedPercent: float | None
    downloadDir: str
    native: StorageState | None = None
    error: str | None = None


class SubtitleTrack(WireModel):
    label: str
    src: str
    srclang: str = ''
    default: bool = False
    kind: str = 'subtitles'


class StreamResponse(WireModel):
    success: bool = True
    streamUrl: str | None = None
    videoUrl: str | None = None
    serverType: str | None = None
    availableServers: list[str] = []
    qualities: dict[str, str] = {}
    videoQualities: dict[str, str] = {}
    subtitles: list[SubtitleTrack] = []
    headers: dict[str, str] = {}
    error: str | None = None


class FavoriteResponse(WireModel):
    id: int
    url: str
    title: str
    imageUrl: str | None = None
    source: str
    autoDownload: bool
    autoDownloadVersion: str = ''
    autoDownloadSubtitles: bool = False
    autoDownloadServer: str | None = None
    autoDownloadQuality: str | None = None


class FavoriteResult(Result):
    favorite: FavoriteResponse


class ProgressResponse(WireModel):
    animeUrl: str
    animeName: str
    episodeNumber: int
    version: str
    watched: bool
    downloaded: bool


class DetailedEpisode(Episode):
    model_config = ConfigDict(extra='allow')
    isWatched: bool = False
    isDownloaded: bool = False


class DetailedAnime(AnimeDetail):
    model_config = ConfigDict(extra='allow')
    episodes: list[DetailedEpisode]


class AnimeDetailResponse(WireModel):
    success: bool
    anime: DetailedAnime
    source: str
    isFavorite: bool
    autoDownload: bool = False
    downloadedEpisodes: list[str | int]
    watchedEpisodes: list[str | int]
    totalEpisodes: int
    downloadedCount: int
    watchedCount: int


class HomeFeed(WireModel):
    success: bool
    latestReleases: dict[str, list[AnimeResult]]
    favorites: list[FavoriteResponse]
    recentHistory: list[DownloadTaskResponse]
    enabledExtensions: list['ExtensionResponse']
    challenges: list[dict[str, JsonValue]] = []
    errors: list[dict[str, JsonValue]] = []


class ExtensionRepository(WireModel):
    id: int
    name: str
    url: str
    is_active: int | bool


class ExtensionResponse(WireModel):
    id: int | str
    pkg: str
    name: str
    lang: str
    version: str | None = None
    installed_version: str | None = None
    available_version: str | None = None
    available_apk_url: str | None = None
    available_base_url: str | None = None
    has_update: int | bool = False
    is_installed: bool = False
    is_enabled: int | bool = False
    recipe_json: str | None = None
    base_url: str | None = None
    icon_url: str | None = None
    apk_url: str | None = None
    updated_at: str | None = None
    capabilities_summary: dict[str, JsonValue] | None = None


class ExtensionList(WireModel):
    active_repo: ExtensionRepository | None
    count: int
    updates_count: int = 0
    extensions: list[ExtensionResponse]


class CatalogueSource(WireModel):
    id: str
    name: str
    type: str
    lang: str
    baseUrl: str
    isEnabled: bool
    views: list[dict[str, str]]
    multiTags: bool


class CatalogueSources(WireModel):
    sources: list[CatalogueSource]


class CatalogueFilters(WireModel):
    tags: list[dict[str, str]]
    groups: list[dict[str, JsonValue]] = []
    orders: list[dict[str, str]]


class CataloguePage(WireModel):
    source: str
    results: list[AnimeResult]
    nextCursor: str | None
    queryScope: str


class PoolEntry(WireModel):
    url: str
    provider: str
    country: str
    usable: bool
    status: str | None = None
    latencyMs: float | None = None


class ProxyPool(WireModel):
    automatic: bool
    refreshing: bool
    checking: bool
    lastRefresh: float | None
    total: int
    healthy: int
    importedCount: int
    providers: list[dict[str, JsonValue]]
    entries: list[PoolEntry]


class TranslationResponse(WireModel):
    language: str
    supported: list[str]
    translations: dict[str, str]
    all: dict[str, dict[str, str]]


class SourcesSettings(WireModel):
    success: bool
    sources: list[dict[str, JsonValue]]


class SourceSettings(Result):
    sourceId: str
    settings: dict[str, JsonValue]


class FavoriteCheck(WireModel):
    isFavorite: bool


class ProxyImport(WireModel):
    imported: int
    pool: ProxyPool


HomeFeed.model_rebuild()


# Mapping by handler name also works when routers have a prefix. Request models
# only cover bodies still read manually; existing Pydantic bodies stay native.
REQUESTS = {
    'start_download': DownloadRequest, 'start_batch_download': BatchRequest,
    'set_global_speed_limit': SpeedRequest, 'set_task_speed_limit': SpeedRequest,
    'move_series_to_top': SeriesRequest, 'reorder_tasks': list[str | int],
    'save_settings': DownloadSettings, 'save_proxy_settings': ProxySettings, 'test_proxy': ProxyTest,
    'remove_favorite': URLRequest, 'mark_watched': WatchedRequest,
    'android_storage_action': StorageAction, 'android_export_download': ExportRequest,
    'set_language': LanguageRequest, 'import_repo_api': URLRequest,
    'toggle_extension_api': ToggleRequest,
    'save_source_settings': dict[str, JsonValue], 'configure_extension_api': dict[str, JsonValue],
    'proxy_pool_settings': dict[str, bool],
}
RESPONSES = {
    'open_playback': PlaybackState,
    'save_playback': Result,
    'export_diagnostics': dict[str, JsonValue],

    'get_all_status': list[DownloadTaskResponse], 'get_history': list[DownloadTaskResponse],
    'search_api': SearchResponse | list[AnimeResult], 'api_source_feed': SourceFeed,
    'api_latest_releases': SourceFeed | dict[str, list[AnimeResult]],
    'api_home_feed': HomeFeed, 'api_anime_detail': AnimeDetailResponse,
    'get_favorites': list[FavoriteResponse], 'add_favorite': FavoriteResult, 'toggle_auto_download': FavoriteResult,
    'get_progress': list[ProgressResponse], 'get_downloaded_set': list[str | int],
    'get_system_storage': StorageResponse, 'android_storage_status': StorageState | None,
    'android_storage_action': StorageState, 'android_export_download': Result,
    'get_settings': DownloadSettings, 'get_proxy_settings': ProxySettings,
    'get_subtitles_list': list[SubtitleTrack], 'resolve_stream': StreamResponse,
    'list_extensions_api': ExtensionList, 'list_catalogues': CatalogueSources,
    'catalogue_filters': CatalogueFilters, 'browse_catalogue': CataloguePage,
    'sessions': NetworkOptions, 'start': VerificationJob, 'complete': VerificationResult, 'recheck': VerificationResult,
    'get_translations': TranslationResponse, 'get_all_source_settings': SourcesSettings,
    'get_source_settings': SourceSettings, 'save_source_settings': SourceSettings,
    'check_favorite': FavoriteCheck, 'import_proxies': ProxyImport,
    'search_voiranime': list[AnimeResult], 'get_voiranime_detail': AnimeDetail | None,
    'get_voiranime_qualities': dict[str, str],
}
for name in ('public_proxies', 'proxy_pool_settings', 'refresh_proxies', 'check_proxies', 'clear_imported_proxies'):
    RESPONSES[name] = ProxyPool
for name in ('start_download', 'start_batch_download', 'set_global_speed_limit', 'cancel_download', 'pause_download',
             'resume_download', 'remove_task', 'set_task_speed_limit', 'pause_all', 'resume_all', 'cancel_all',
             'clear_inactive', 'save_settings', 'save_proxy_settings', 'test_proxy', 'get_episode_servers',
             'get_episode_size', 'move_task_to_top', 'move_series_to_top', 'reorder_tasks', 'verify_task',
             'verify_all_tasks', 'redownload_task', 'remove_favorite', 'clear_all_favorites', 'mark_watched',
             'delete_history_entry', 'clear_history', 'trigger_watchdog_check', 'import_repo_api',
             'toggle_extension_api', 'refresh_extensions_api', 'check_updates_api', 'update_extension_api',
             'update_all_extensions_api', 'recompile_extension_api', 'configure_extension_api', 'diagnose_extension_api',
             'set_language', 'cancel', 'rotate_proxy'):
    RESPONSES[name] = Result

BINARY = {'proxy_image', 'stream_video', 'stream_subtitle_default', 'stream_subtitle_at_index',
          'proxy_subtitle', 'hls_proxy_playlist', 'hls_proxy_segment', 'stream_proxy', 'stream_download_updates'}
# Custom source payloads are recursively typed JSON until A04 unifies providers.
JSON_OBJECT = dict[str, JsonValue]


class ContractRoute(APIRoute):
    def __init__(self, path, endpoint, **kwargs):
        name = endpoint.__name__
        api = path.startswith('/api/') or endpoint.__module__.endswith(('.network', '.sources'))
        self.contract_request = REQUESTS.get(name) if api else None
        if api and name not in BINARY:
            # JSONResponse handlers are validated explicitly below, too.
            kwargs['response_model'] = RESPONSES.get(name, JsonValue)
            kwargs['response_model_exclude_unset'] = True
            kwargs['responses'] = {**(kwargs.get('responses') or {}),
                400: {'model': ErrorResponse, 'description': 'Invalid request; legacy fields plus problem'},
                403: {'model': ErrorResponse, 'description': 'Permission required'},
                404: {'model': ErrorResponse, 'description': 'Resource not found'},
                409: {'model': ErrorResponse, 'description': 'Verification or conflict; legacy fields plus problem'},
                422: {'model': ErrorResponse, 'description': 'Invalid request parameters'},
                429: {'model': ErrorResponse, 'description': 'Rate limited; problem.retryAfter in seconds'},
                500: {'model': ErrorResponse, 'description': 'Internal failure'},
                502: {'model': ErrorResponse, 'description': 'Upstream network failure'}}
        super().__init__(path, endpoint, **kwargs)
        if self.contract_request:
            schema = TypeAdapter(self.contract_request).json_schema(ref_template='#/components/schemas/{model}')
            self.contract_definitions = schema.pop('$defs', {})
            self.openapi_extra = {**(self.openapi_extra or {}), 'requestBody': {'required': True,
                'content': {'application/json': {'schema': schema}}}}

    def get_route_handler(self):
        original = super().get_route_handler()
        async def handler(request: Request):
            if self.contract_request:
                try:
                    raw = await request.json()
                    data = TypeAdapter(self.contract_request).validate_python(raw)
                    # Legacy handlers still read request.json(); give them the
                    # validated wire values, preserving PATCH omission semantics.
                    request._json = (data.model_dump(exclude_unset=True, mode='json') if isinstance(data, BaseModel)
                                     else TypeAdapter(self.contract_request).dump_python(data, mode='json', exclude_unset=True))
                except (ValidationError, ValueError) as exc:
                    errors = exc.errors() if isinstance(exc, ValidationError) else [{'type': 'json_invalid', 'loc': ('body',), 'msg': 'Invalid JSON'}]
                    if self.endpoint.__name__ in ('set_language', 'android_storage_action', 'toggle_extension_api'):
                        from fastapi import HTTPException
                        raise HTTPException(400, 'Invalid request parameters') from exc
                    raise RequestValidationError(errors) from exc
            response = await original(request)
            if response.status_code < 400 and hasattr(response, 'body') and response.media_type == 'application/json':
                payload = json.loads(response.body)
                if isinstance(payload, dict) and payload.get('success') is False:
                    # Some legacy metadata/proxy endpoints return HTTP 200 on
                    # failure. Preserve that wire behavior while adding advice.
                    category = ('media' if self.endpoint.__name__ in ('get_episode_size', 'get_episode_servers', 'resolve_stream')
                                else 'network' if self.endpoint.__name__ == 'test_proxy' else 'internal')
                    payload.setdefault('problem', problem_for(500, payload, category=category).model_dump())
                    response.body = json.dumps(payload, ensure_ascii=False).encode()
                    response.headers['content-length'] = str(len(response.body))
            if response.status_code < 400 and self.endpoint.__name__ in RESPONSES and hasattr(response, 'body'):
                TypeAdapter(RESPONSES[self.endpoint.__name__]).validate_json(response.body)
            return response
        return handler


def install_contract_schema(app):
    from fastapi.openapi.utils import get_openapi
    def schema():
        if app.openapi_schema is None:
            import warnings
            # FastAPI assigns one ID to multi-method media routes. Give each
            # operation its own stable ID after generation (including HEAD).
            with warnings.catch_warnings():
                warnings.filterwarnings('ignore', message='Duplicate Operation ID .*', category=UserWarning)
                result = get_openapi(title=app.title, version=app.version, routes=app.routes)
            for path, operations in result['paths'].items():
                for method, operation in operations.items():
                    if isinstance(operation, dict) and 'operationId' in operation:
                        operation['operationId'] += '_' + method
            components = result.setdefault('components', {}).setdefault('schemas', {})
            for model in REQUESTS.values():
                definition = TypeAdapter(model).json_schema(ref_template='#/components/schemas/{model}')
                components.update(definition.pop('$defs', {}))
                if isinstance(model, type) and issubclass(model, BaseModel):
                    components[model.__name__] = definition
            app.openapi_schema = result
        return app.openapi_schema
    app.openapi = schema
