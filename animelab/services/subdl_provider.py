"""SubDL REST v2, deliberately separate from its legacy query-key API.

Only explicit search, account status and subtitle downloads are used. No AI,
translation or paid endpoint is invoked. Provider URLs never come from clients.
"""
import asyncio
import json
import re
import time
from urllib.parse import quote, urljoin, urlsplit

import httpx

from animelab import __version__
from animelab.security import is_safe_url
from animelab.services.subtitle_provider import ProviderError, MAX_FILE


class SubDLProvider:
    def __init__(self, vault=None, client_factory=None):
        self.vault = vault
        self.client_factory = client_factory or (lambda: httpx.AsyncClient(timeout=30, follow_redirects=False, trust_env=False))
        self.key = ''
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
                    self.key, self.remember = saved['apiKey'], True
            except ProviderError as exc:
                self.last_error = exc.code

    def status(self):
        return dict(configured=bool(self.key), authenticated=bool(self.key) and self.last_error != 'provider_auth', username='', remember=self.remember,
            secureStorageAvailable=bool(self.vault and self.vault.available()), quota=self.quota, error=self.last_error,
            retryAfter=max(0, int(self.cooldown-time.monotonic())+1) if self.cooldown else 0, apiVersion='v2')

    @staticmethod
    def destination(url, *, cdn=False):
        try:
            parsed = urlsplit(url)
            valid = (parsed.scheme == 'https' and parsed.port in (None, 443) and not parsed.username
                     and not parsed.password and not parsed.fragment and not parsed.query
                     and ((parsed.hostname == 'dl.subdl.com' and parsed.path.startswith('/subtitle/')) if cdn else
                          parsed.hostname == 'api.subdl.com' and parsed.path.startswith('/api/v2/')))
        except ValueError:
            valid = False
        if not valid or not is_safe_url(url):
            raise ProviderError('Destination SubDL non autorisée', 'provider_destination', 502)
        return url

    def update_quota(self, response, data=None):
        for field, header in [('requestLimit', 'x-ratelimit-limit'), ('requestRemaining', 'x-ratelimit-remaining'), ('reset', 'x-ratelimit-reset')]:
            value = response.headers.get(header)
            if value is not None:
                try:
                    self.quota[field] = int(value)
                except ValueError:
                    pass
        if isinstance(data, dict):
            usage = data.get('usage') or {}
            if isinstance(usage, dict):
                for category in ('search', 'downloads'):
                    row = usage.get(category)
                    if isinstance(row, dict):
                        self.quota[category] = {key: row[key] for key in ('used', 'limit', 'remaining', 'period')
                                                if isinstance(row.get(key), (int, str))}

    async def exchange(self, endpoint, *, params=None, download=False):
        if not self.key:
            raise ProviderError('Configurez une clé API SubDL avant la recherche', 'provider_configuration')
        if time.monotonic() < self.cooldown:
            raise ProviderError('SubDL demande de patienter avant de réessayer', 'provider_rate_limit', 429,
                                max(1, int(self.cooldown-time.monotonic())+1))
        await asyncio.sleep(max(0, self.next_request-time.monotonic()))
        self.next_request = time.monotonic()+self.request_interval
        url = 'https://api.subdl.com/api/v2/' + endpoint
        try:
            async with self.client_factory() as client:
                cdn = False
                for _ in range(5):
                    self.destination(url, cdn=cdn)
                    headers = {'User-Agent': f'AnimeLab v{__version__}', 'Accept-Encoding': 'identity',
                               'Accept': '*/*' if download else 'application/json'}
                    if not cdn:
                        headers['Authorization'] = 'Bearer '+self.key
                    async with client.stream('GET', url, headers=headers, params=params) as response:
                        self.update_quota(response)
                        if response.status_code in (301, 302, 303, 307, 308):
                            target = urljoin(url, response.headers.get('location', ''))
                            target_cdn = urlsplit(target).hostname == 'dl.subdl.com'
                            if (target_cdn and not download) or (cdn and not target_cdn):
                                raise ProviderError('Redirection SubDL non autorisée', 'provider_destination', 502)
                            self.destination(target, cdn=target_cdn)
                            url, params, cdn = target, None, target_cdn
                            continue
                        if response.status_code == 429:
                            try:
                                delay = max(1, min(86400, int(response.headers.get('Retry-After', '60'))))
                            except ValueError:
                                delay = 60
                            self.cooldown = time.monotonic()+delay
                            raise ProviderError('Quota ou limite de requêtes SubDL atteinte', 'provider_rate_limit', 429, delay)
                        if response.status_code == 401:
                            raise ProviderError('Clé API SubDL refusée ; reconnectez le fournisseur', 'provider_auth', 401)
                        if response.status_code in (402, 403):
                            raise ProviderError('Accès SubDL refusé ou quota épuisé', 'provider_quota_or_access', 403)
                        if response.status_code in (404, 410) and download:
                            raise ProviderError('Sous-titre SubDL indisponible ; relancez la recherche', 'provider_link_expired', 410)
                        if response.status_code >= 400:
                            raise ProviderError('SubDL est momentanément indisponible', 'provider_unavailable', 502)
                        if response.headers.get('content-encoding', 'identity').lower() != 'identity':
                            raise ProviderError('Compression HTTP SubDL inattendue', 'provider_response', 502)
                        body = bytearray()
                        async for chunk in response.aiter_bytes(65536):
                            body.extend(chunk)
                            if len(body) > (MAX_FILE if download else 2*1024*1024):
                                raise ProviderError('Réponse SubDL trop volumineuse', 'provider_response', 502)
                        if download:
                            # Request the documented archive form; entry selection
                            # and traversal/size checks remain in the import layer.
                            return bytes(body)
                        try:
                            data = json.loads(body)
                            if not isinstance(data, dict) or data.get('error') or data.get('status') is False:
                                raise ValueError()
                        except (ValueError, UnicodeError) as exc:
                            raise ProviderError('Réponse SubDL v2 invalide ou incompatible', 'provider_response', 502) from exc
                        self.update_quota(response, data)
                        return data
                raise ProviderError('Trop de redirections SubDL', 'provider_destination', 502)
        except httpx.RequestError as exc:
            raise ProviderError('Connexion à SubDL interrompue ; la vidéo est conservée', 'provider_network', 502) from exc

    async def configure(self, api_key=None, username='', password='', remember=False):
        async with self.lock:
            key = api_key or self.key
            if not key or len(key) > 4096 or any(c.isspace() for c in key) or username or password:
                raise ProviderError('SubDL utilise une clé API, sans nom d’utilisateur ni mot de passe', 'provider_configuration')
            if remember and not (self.vault and self.vault.available()):
                raise ProviderError('La sauvegarde requiert une clé de chiffrement externe', 'provider_storage')
            self.key, self.remember = key, False
            if self.vault:
                self.vault.clear()
            try:
                await self.exchange('me')
                if remember:
                    self.vault.save(dict(apiKey=key))
                    self.remember = True
                self.last_error = None
                return self.status()
            except ProviderError as exc:
                self.last_error = exc.code
                raise

    async def forget(self):
        async with self.lock:
            if self.vault:
                self.vault.clear()
            self.key, self.remember, self.quota, self.last_error = '', False, {}, None
            return self.status()

    async def search(self, query):
        if query.idType == 'episode' and (query.imdbId or query.tmdbId):
            raise ProviderError('Pour SubDL, utilisez l’identifiant de la série et sa numérotation', 'provider_query')
        if query.page != 1:
            raise ProviderError('La pagination SubDL v2 n’est pas documentée ; affinez la recherche', 'provider_query')
        params = dict(languages=','.join(sorted(set(query.languages.split(',')))))
        if query.imdbId:
            params['imdb_id'] = 'tt'+str(int(query.imdbId.removeprefix('tt')))
        elif query.tmdbId:
            params['tmdb_id'] = str(query.tmdbId)
        else:
            params['film_name'] = query.query
        params['type'] = 'movie' if query.idType == 'movie' else 'tv'
        if query.season is not None:
            params['season'] = str(query.season)
        number = query.absoluteEpisode if query.absoluteEpisode is not None else query.episode
        if number is not None:
            params['episode'] = str(number)
        async with self.lock:
            try:
                value = await self.exchange('subtitles/search', params=dict(sorted(params.items())))
                self.last_error = None
                return normalize_subdl(value, query)
            except ProviderError as exc:
                self.last_error = exc.code
                raise

    async def download(self, file_id):
        if not isinstance(file_id, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', file_id):
            raise ProviderError('Identifiant SubDL v2 invalide', 'provider_response')
        async with self.lock:
            return await self.exchange('subtitles/'+quote(file_id, safe='')+'/download', params={'format': 'zip'}, download=True), file_id+'.zip'


def normalize_subdl(value, query):
    rows = value.get('subtitles')
    features = value.get('results') or []
    if not isinstance(rows, list) or not isinstance(features, list):
        raise ProviderError('Schéma de recherche SubDL v2 non reconnu', 'provider_response', 502)
    data = []
    for row in rows[:100]:
        if not isinstance(row, dict):
            raise ProviderError('Sous-titre SubDL v2 invalide', 'provider_response', 502)
        nid = row.get('n_id') or row.get('nId')
        if not isinstance(nid, str) or not re.fullmatch(r'[a-zA-Z0-9_-]{1,100}', nid):
            raise ProviderError('Identifiant nId absent du résultat SubDL v2', 'provider_response', 502)
        language = str(row.get('language') or row.get('lang') or 'und').lower()
        language = {'french': 'fr', 'english': 'en', 'japanese': 'ja'}.get(language, language)
        feature = next((item for item in features if isinstance(item, dict) and
                        row.get('sd_id') is not None and str(item.get('sd_id')) == str(row['sd_id'])), {})
        normalized = dict(title=feature.get('name'), season_number=row.get('season'), episode_number=row.get('episode'))
        # Never copy the requested identifiers into missing provider metadata.
        prefix = 'parent_' if query.idType == 'series' else ''
        for key in ('imdb_id', 'tmdb_id'):
            raw = feature.get(key)
            if raw is not None:
                normalized[prefix+key] = str(raw).removeprefix('tt').lstrip('0') or '0'
        data.append(dict(id=nid, attributes=dict(language=language,
            release=row.get('release_name') or row.get('name') or '', fps=row.get('fps'),
            duration=row.get('duration'), hearing_impaired=bool(row.get('hi')),
            foreign_parts_only=bool(row.get('forced')), feature_details=normalized,
            md5=row.get('md5'), files=[dict(file_id=nid, file_name=str(row.get('name') or nid)+'.zip')])))
    return dict(data=data, page=1, total_pages=1)
