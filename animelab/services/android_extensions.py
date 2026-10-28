"""Original Android APK execution boundary. No Java dependency on desktop/server."""
import asyncio
import hashlib
import json
import uuid
from urllib.parse import urljoin

from animelab.api_errors import APIProblem
from animelab.models.anime import AnimeResult, AnimeDetail, Episode

_bridge = None


def configure(bridge):
    global _bridge
    _bridge = bridge


def available():
    return _bridge is not None


def unpack(value):
    data = json.loads(str(value))
    if not data.get('ok'):
        code = data.get('code', 'extension_runtime_unavailable')
        if code == 'verification_required':
            from animelab.services.source_http import VerificationRequired
            raise VerificationRequired(data.get('url') or '')
        raise APIProblem(code, status=400 if code in ('extension_untrusted', 'source_operation_unsupported') else 502,
                         category='validation' if code == 'extension_untrusted' else 'network')
    return data['result']


def discover():
    if not available():
        return []
    return unpack(_bridge.discover())


async def invoke(pkg, operation, source_id=None, payload=None, **identity):
    if not available():
        raise ValueError('Le moteur APK Android est indisponible sur cette plateforme.')
    op = uuid.uuid4().hex
    request = {'operationId': op, 'pkg': pkg, 'operation': operation,
               'sourceId': str(source_id) if source_id is not None else '', 'payload': payload or {}, **identity}
    try:
        return unpack(await asyncio.to_thread(_bridge.invoke, json.dumps(request)))
    except asyncio.CancelledError:
        await asyncio.to_thread(_bridge.cancel, op)
        raise


async def install(path, pkg=''):
    if not available():
        raise ValueError('Installation APK réservée à Android.')
    return json.loads(str(await asyncio.to_thread(_bridge.install, str(path), pkg)))


async def uninstall(pkg):
    if not available():
        raise ValueError('Désinstallation APK réservée à Android.')
    return json.loads(str(await asyncio.to_thread(_bridge.uninstall, pkg)))


async def inspect(path):
    if not available():
        raise ValueError('Inspection APK native indisponible.')
    return json.loads(str(await asyncio.to_thread(_bridge.inspect, str(path))))


async def operations():
    return json.loads(str(await asyncio.to_thread(_bridge.operations))) if available() else []


async def cancel_installation(operation):
    if not available():
        raise ValueError('Installation APK réservée à Android.')
    return json.loads(str(await asyncio.to_thread(_bridge.cancelInstallation,operation)))


class AndroidAPKSource:
    """A real source instance enumerated by the original APK's factory."""
    runtime = 'android-apk'

    def __init__(self, package, metadata):
        self.pkg = package['pkg']
        self.native_id = str(metadata['id'])
        self.source_id = 'aniyomi:' + self.native_id
        self.name = metadata['name']
        self.lang = metadata.get('lang') or 'all'
        self.base_url = metadata.get('baseUrl') or ''
        self.supports_latest = bool(metadata.get('supportsLatest'))
        self.metadata = metadata
        self._episodes = {}
        self._animes = {}

    async def call(self, operation, payload=None):
        return await invoke(self.pkg, operation, self.native_id, payload)

    def _result(self, item):
        url = urljoin(self.base_url + '/', item['url'])
        if len(self._animes) >= 5000:
            self._animes.pop(next(iter(self._animes)))
        self._animes[url] = item
        return AnimeResult(id=hashlib.sha256((self.source_id + ':' + item['url']).encode()).hexdigest()[:24],
                           title=item['title'], imageUrl=item.get('thumbnail_url') or '', url=url,
                           source=self.source_id, genres=[s.strip() for s in (item.get('genre') or '').split(',') if s.strip()])

    async def catalogue(self, operation, page=1, query='', filters=None):
        result = await self.call(operation, {'page': page, 'query': query, **({'filters': filters} if filters is not None else {})})
        return {'results': [self._result(item) for item in result['results']], 'hasNextPage': result['hasNextPage']}

    async def search_anime(self, query):
        return (await self.catalogue('search', query=query))['results']

    async def get_latest_releases(self):
        return (await self.catalogue('latest'))['results']

    async def get_popular_anime(self, page=1):
        return (await self.catalogue('popular', page=page))['results']

    async def get_anime_detail(self, url):
        result = await self.call('detail', self._animes.get(url) or {'url': url, 'title': url})
        item = result['anime']
        episodes = []
        for index, row in enumerate(result['episodes'], 1):
            absolute = urljoin(self.base_url + '/', row['url'])
            self._episodes[absolute] = row
            number = row.get('episode_number', -1)
            # Preserve fractional upstream numbers in nativeMetadata; existing
            # queue numbering remains an integer display/order field.
            episodes.append(Episode(number=int(number) if number >= 0 and float(number).is_integer() else index,
                                    title=row['name'], playerUrl=absolute, downloadPageUrl=absolute,
                                    synopsis=row.get('summary'), thumbnailUrl=row.get('preview_url'), nativeMetadata=row))
        if len(self._episodes) > 5000:
            self._episodes = {episode.playerUrl: episode.nativeMetadata for episode in episodes}
        return AnimeDetail(title=item['title'], synopsis=item.get('description'), imageUrl=item.get('thumbnail_url') or '',
                           bannerUrl=item.get('background_url'), url=url, source=self.source_id, episodes=episodes,
                           genres=[s.strip() for s in (item.get('genre') or '').split(',') if s.strip()], nativeMetadata=item)

    async def get_episode_sources(self, play_url):
        hosts = await self.call('hosters', self._episodes.get(play_url) or {'url': play_url, 'name': play_url})
        candidates = []
        for host in hosts:
            try:
                videos = host.get('videoList')
                if videos is None:
                    videos = await self.call('videos', host)
                for video in videos:
                    candidates.append({'url': video.get('videoUrl') or host.get('hosterUrl') or play_url,
                                       'server': host.get('hosterName') or self.name,
                                       'quality': video.get('videoTitle') or 'Source', '_native_video': video})
            except asyncio.CancelledError:
                raise
            except Exception:
                if len(hosts) == 1:
                    raise
        return candidates

    async def resolve_candidate(self, candidate):
        video = await self.call('resolve_video', candidate['_native_video'])
        from animelab.security import is_safe_url
        resources = [video.get('videoUrl'), *[t.get('url') for key in ('subtitleTracks', 'audioTracks') for t in video.get(key, [])]]
        for url in resources:
            if not url or not await asyncio.to_thread(is_safe_url, url):
                raise ValueError('Ressource vidéo APK non autorisée.')
        headers = dict(video.get('headers') or [])
        from animelab.services.media_contracts import UnsupportedMedia
        if any(video.get(key) for key in ('mpvArgs','ffmpegStreamArgs','ffmpegVideoArgs')):
            raise UnsupportedMedia('Cette vidéo exige des options de lecteur APK non prises en charge.')
        from animelab.services.media_contracts import normalize_tracks
        subtitles = normalize_tracks(video.get('subtitleTracks'), video['videoUrl'], kind='subtitle')
        audio = normalize_tracks(video.get('audioTracks'), video['videoUrl'], kind='audio')
        return {'videoUrl': video['videoUrl'], 'headers': headers, 'subtitles': subtitles, 'audioTracks': audio,
                'serverType': candidate.get('server') or self.name, 'selectedQuality': video.get('videoTitle') or 'Source',
                'timestamps': video.get('timestamps') or [], 'provenance': 'android-apk',
                'unsupportedArguments': any(video.get(key) for key in ('mpvArgs', 'ffmpegStreamArgs', 'ffmpegVideoArgs'))}
