"""OpenSubtitles REST v1: fixed destinations, account-local state, no source cookies.

The application registers as an API consumer. A human explicitly requests each
preview/download; generating a URL spends provider quota. No scrape fallback.
"""
import asyncio
import json
import time
from typing import Literal, Protocol
from urllib.parse import urljoin, urlsplit

import httpx
from pydantic import BaseModel, ConfigDict, Field, model_validator

from animelab import __version__
from animelab.security import is_safe_url

API_HOSTS = {'api.opensubtitles.com', 'vip-api.opensubtitles.com'}
FILE_HOSTS = {'www.opensubtitles.com', 'dl.opensubtitles.com'}
MAX_FILE = 10 * 1024 * 1024


class ProviderError(ValueError):
    def __init__(self, message, code='provider_error', status=400, retry_after=None):
        super().__init__(message)
        self.code, self.status, self.retry_after = code, status, retry_after


class SubtitleQuery(BaseModel):
    model_config = ConfigDict(extra='forbid', allow_inf_nan=False)
    query: str = Field(default='', max_length=200)
    languages: str = Field(default='fr', pattern=r'^[a-z]{2,3}(?:-[a-z]{2})?(?:,[a-z]{2,3}(?:-[a-z]{2})?){0,4}$')
    imdbId: str = Field(default='', pattern=r'^(?:tt)?\d{1,12}$|^$')
    tmdbId: int | None = Field(default=None, gt=0, le=10**12)
    idType: Literal['series', 'episode', 'movie'] = 'series'
    season: int | None = Field(default=None, ge=0, le=1000)
    episode: int | None = Field(default=None, ge=0, le=100000)
    absoluteEpisode: int | None = Field(default=None, ge=1, le=100000)
    page: int = Field(default=1, ge=1, le=100)
    providers: list[Literal['opensubtitles', 'subdl']] = Field(default_factory=lambda: ['opensubtitles'], min_length=1, max_length=2)
    expectedRelease: str = Field(default='', max_length=255)
    expectedFps: float | None = Field(default=None, ge=1, le=240)
    expectedDuration: float | None = Field(default=None, gt=0, le=864000)

    @model_validator(mode='after')
    def valid_identity(self):
        self.query = self.query.strip()
        if len(self.providers) != len(set(self.providers)):
            raise ValueError('Un fournisseur ne peut être choisi plusieurs fois')
        if not (self.query or self.imdbId or self.tmdbId):
            raise ValueError('Indiquez un titre ou un identifiant IMDb/TMDB')
        if self.absoluteEpisode is not None and (self.season is not None or self.episode is not None):
            raise ValueError('Choisissez la numérotation saison/épisode ou absolue')
        if self.idType != 'series' and any(value is not None for value in (self.season, self.episode, self.absoluteEpisode)):
            raise ValueError('Un identifiant de film ou d’épisode se recherche sans numérotation supplémentaire')
        return self

    def parameters(self):
        values = dict(languages=','.join(sorted(set(self.languages.split(',')))), page=str(self.page),
                      ai_translated='exclude', machine_translated='exclude')
        prefix = 'parent_' if self.idType == 'series' else ''
        if self.imdbId:
            values[prefix + 'imdb_id'] = str(int(self.imdbId.removeprefix('tt')))
        if self.tmdbId:
            values[prefix + 'tmdb_id'] = str(self.tmdbId)
        if not self.imdbId and not self.tmdbId:
            values['query'] = self.query.lower()
        if self.season is not None:
            values['season_number'] = str(self.season)
        number = self.absoluteEpisode if self.absoluteEpisode is not None else self.episode
        if number is not None:
            values['episode_number'] = str(number)
        if self.idType in ('movie', 'episode'):
            values['type'] = self.idType
        return dict(sorted(values.items()))


def match_criteria(query, feature):
    """Expose evidence and uncertainty rather than an invented confidence score."""
    checks, warnings = [], []
    params = query.parameters()
    for key in ('imdb_id', 'tmdb_id', 'parent_imdb_id', 'parent_tmdb_id', 'season_number', 'episode_number'):
        if key not in params:
            continue
        actual = feature.get(key)
        state = 'unknown' if actual is None else 'match' if str(actual) == params[key] else 'mismatch'
        checks.append(dict(field=key, expected=params[key], actual=actual, state=state))
    if not checks:
        warnings.append('Recherche par titre uniquement : vérifiez la série et l’épisode')
    if query.absoluteEpisode is not None:
        warnings.append('Numérotation absolue : le fournisseur peut utiliser des saisons différentes')
    if any(check['state'] == 'mismatch' for check in checks):
        warnings.append('Les identifiants ou la numérotation ne correspondent pas à la recherche')
    if any(check['state'] == 'unknown' for check in checks):
        warnings.append('Certaines métadonnées de correspondance sont absentes')
    return checks, warnings


class SubtitleProvider(Protocol):
    async def search(self, query: SubtitleQuery) -> dict: ...
    async def download(self, file_id: int | str) -> tuple[bytes, str]: ...


class OpenSubtitlesProvider:
    def __init__(self, vault=None, client_factory=None):
        self.vault = vault
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False))
        self.credentials = {}
        self.base = 'api.opensubtitles.com'
        self.token = None
        self.auth_failed = False
        self.remember = False
        self.quota = {}
        self.last_error = None
        self.cooldown = 0
        self.next_request = 0
        self.request_interval = 1
        self.lock = asyncio.Lock()
        if vault:
            try:
                saved = vault.load()
                if saved:
                    self.credentials = saved
                    self.remember = True
            except ProviderError as exc:
                self.last_error = exc.code

    def status(self):
        return dict(configured=bool(self.credentials.get('apiKey')), authenticated=bool(self.token),
                    username=self.credentials.get('username', ''), remember=self.remember,
                    secureStorageAvailable=bool(self.vault and self.vault.available()),
                    quota=self.quota, error=self.last_error,
                    retryAfter=max(0, int(self.cooldown - time.monotonic()) + 1) if self.cooldown else 0)

    @staticmethod
    def destination(url, *, file=False):
        try:
            parsed = urlsplit(url)
            port = parsed.port
        except ValueError as exc:
            raise ProviderError('Destination OpenSubtitles non autorisée', 'provider_destination', 502) from exc
        hosts = FILE_HOSTS if file else API_HOSTS
        path_ok = parsed.path.startswith('/download/') if file else parsed.path.startswith('/api/v1/')
        if (parsed.scheme != 'https' or parsed.hostname not in hosts or port not in (None, 443)
                or parsed.username or parsed.password or parsed.fragment or not path_ok or not is_safe_url(url)):
            raise ProviderError('Destination OpenSubtitles non autorisée', 'provider_destination', 502)
        return url

    async def exchange(self, method, url, *, data=None, params=None, file=False):
        # Callers hold the provider lock. Every redirect is checked before a
        # request. Never forward API keys/bearer tokens to file/CDN endpoints.
        if time.monotonic() < self.cooldown:
            raise ProviderError('OpenSubtitles demande de patienter avant de réessayer', 'provider_rate_limit', 429,
                                max(1, int(self.cooldown - time.monotonic()) + 1))
        await asyncio.sleep(max(0, self.next_request - time.monotonic()))
        self.next_request = time.monotonic() + self.request_interval
        headers = {'User-Agent': f'AnimeLab v{__version__}', 'Accept': '*/*' if file else 'application/json',
                   'Accept-Encoding': 'identity'}
        if not file:
            headers['Api-Key'] = self.credentials['apiKey']
            if self.token:
                headers['Authorization'] = 'Bearer ' + self.token
        try:
            async with self.client_factory() as client:
                for _ in range(5):
                    self.destination(url, file=file)
                    async with client.stream(method, url, headers=headers, json=data, params=params) as response:
                        if response.status_code in (301, 302, 303, 307, 308):
                            if method != 'GET':
                                raise ProviderError('Redirection inattendue de l’API OpenSubtitles', 'provider_destination', 502)
                            url = urljoin(url, response.headers.get('location', ''))
                            params = None
                            continue
                        if response.status_code == 429:
                            try:
                                delay = max(1, min(86400, int(response.headers.get('Retry-After', '60'))))
                            except ValueError:
                                delay = 60
                            self.cooldown = time.monotonic() + delay
                            raise ProviderError('Limite de requêtes OpenSubtitles atteinte', 'provider_rate_limit', 429, delay)
                        if response.status_code == 401:
                            self.token = None
                            raise ProviderError('Session OpenSubtitles expirée ou identifiants incorrects', 'provider_auth', 401)
                        if response.status_code in (403, 406):
                            raise ProviderError('Accès refusé ou quota OpenSubtitles épuisé ; vérifiez votre compte', 'provider_quota_or_access', 403)
                        if file and response.status_code in (404, 410):
                            raise ProviderError('Le lien du sous-titre a expiré', 'provider_link_expired', 410)
                        if response.status_code >= 400:
                            raise ProviderError('OpenSubtitles est momentanément indisponible', 'provider_unavailable', 502)
                        if response.headers.get('Content-Encoding', 'identity').lower() != 'identity':
                            raise ProviderError('Compression HTTP OpenSubtitles inattendue', 'provider_response', 502)
                        body = bytearray()
                        limit = MAX_FILE if file else 2 * 1024 * 1024
                        async for chunk in response.aiter_bytes(chunk_size=65536):
                            body.extend(chunk)
                            if len(body) > limit:
                                raise ProviderError('Réponse OpenSubtitles trop volumineuse', 'provider_response', 502)
                        if file:
                            return bytes(body)
                        try:
                            value = json.loads(body)
                            if not isinstance(value, dict):
                                raise ValueError()
                            return value
                        except (ValueError, UnicodeError) as exc:
                            raise ProviderError('Réponse OpenSubtitles invalide', 'provider_response', 502) from exc
                raise ProviderError('Trop de redirections OpenSubtitles', 'provider_destination', 502)
        except httpx.RequestError as exc:
            raise ProviderError('Connexion à OpenSubtitles interrompue ; la vidéo est conservée', 'provider_network', 502) from exc

    async def login(self):
        if self.auth_failed:
            raise ProviderError('Reconnectez OpenSubtitles avec des identifiants valides', 'provider_auth', 401)
        username, password = self.credentials.get('username'), self.credentials.get('password')
        if not username or not password:
            return
        try:
            data = await self.exchange('POST', 'https://api.opensubtitles.com/api/v1/login', data=dict(username=username, password=password))
        except ProviderError as exc:
            if exc.code == 'provider_auth':
                self.auth_failed = True  # No repeated automatic bad logins.
            raise
        host, token = data.get('base_url'), data.get('token')
        if host not in API_HOSTS or not isinstance(token, str) or not token or len(token) > 8192 or any(c.isspace() for c in token):
            raise ProviderError('Session OpenSubtitles invalide', 'provider_response', 502)
        self.base, self.token = host, token
        user = data.get('user') or {}
        self.quota = {key: user[key] for key in ('allowed_downloads',) if isinstance(user.get(key), (int, float))}

    async def configure(self, api_key=None, username='', password='', remember=False):
        async with self.lock:
            key = api_key or self.credentials.get('apiKey')
            if not key:
                raise ProviderError('Une clé API OpenSubtitles est nécessaire', 'provider_configuration')
            if len(key) > 4096 or any(c.isspace() for c in key):
                raise ProviderError('Clé API OpenSubtitles invalide', 'provider_configuration')
            if remember and not (self.vault and self.vault.available()):
                raise ProviderError('La sauvegarde requiert une clé de chiffrement externe configurée par l’opérateur', 'provider_storage')
            if bool(username) != bool(password):
                raise ProviderError('Renseignez le nom d’utilisateur et le mot de passe ensemble', 'provider_configuration')
            self.credentials = dict(apiKey=key, username=username, password=password)
            self.token, self.base, self.auth_failed = None, 'api.opensubtitles.com', False
            self.remember = False
            if self.vault:
                self.vault.clear()
            try:
                if username:
                    await self.login()
                else:
                    await self.exchange('GET', f'https://{self.base}/api/v1/infos/languages')
                if remember:
                    self.vault.save(self.credentials)
                    self.remember = True
                self.last_error = None
                return self.status()
            except ProviderError as exc:
                self.last_error = exc.code
                raise

    async def forget(self):
        async with self.lock:
            # Remove local secrets even when the provider is offline.
            if self.vault:
                self.vault.clear()
            self.credentials, self.token, self.quota = {}, None, {}
            self.base, self.auth_failed, self.remember, self.last_error = 'api.opensubtitles.com', False, False, None
            return self.status()

    async def api(self, method, endpoint, **kwargs):
        if not self.credentials.get('apiKey'):
            raise ProviderError('Configurez OpenSubtitles avant de rechercher des sous-titres', 'provider_configuration')
        if not self.token:
            await self.login()
        try:
            return await self.exchange(method, f'https://{self.base}/api/v1/{endpoint}', **kwargs)
        except ProviderError as exc:
            if exc.code != 'provider_auth' or endpoint == 'login' or self.auth_failed or not self.credentials.get('username'):
                self.last_error = exc.code
                raise
            await self.login()  # One refresh after an expired token, never a loop.
            return await self.exchange(method, f'https://{self.base}/api/v1/{endpoint}', **kwargs)

    async def search(self, query):
        async with self.lock:
            result = await self.api('GET', 'subtitles', params=query.parameters())
            self.last_error = None
            return result

    async def download(self, file_id):
        async with self.lock:
            result = await self.api('POST', 'download', data={'file_id': file_id})
            self.quota = {key: result[key] for key in ('remaining', 'requests', 'reset_time_utc') if isinstance(result.get(key), (int, float, str))}
            link = result.get('link')
            if not isinstance(link, str):
                raise ProviderError('Lien OpenSubtitles manquant', 'provider_response', 502)
            try:
                content = await self.exchange('GET', link, file=True)
            except ProviderError as exc:
                # Exactly one new signed link, only after an explicit 404/410.
                # A new POST /download may consume one more quota unit.
                if exc.code != 'provider_link_expired':
                    raise
                raise ProviderError('Lien expiré : redemandez l’aperçu pour le renouveler (quota possible)', 'provider_link_expired', 410) from exc
            return content, str(result.get('file_name') or 'subtitle.srt')[:255]
