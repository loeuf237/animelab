"""Small data interpreter for serializable JSON and HTML recipe operations.

There is no package/domain dispatch here and no execution of downloaded code.
All HTTP requests use the container's checked, session-aware transport.
"""
import asyncio
import hashlib
import json
import re
import time
from urllib.parse import parse_qs, quote, quote_plus, urlencode, urljoin, urlparse

from bs4 import BeautifulSoup

from animelab.models.anime import AnimeDetail, AnimeResult, Episode
from animelab.services.source_http import source_http


def field(data, path, default=None):
    for part in path.split('.') if path else []:
        if not isinstance(data, dict) or part not in data:
            return default
        data = data[part]
    return data


def normalize(data, aliases):
    if isinstance(data, list):
        return [normalize(v, aliases) for v in data]
    if not isinstance(data, dict):
        return data
    result = {k: normalize(v, aliases) for k, v in data.items()}
    for target, paths in aliases.items():
        for path in paths:
            value = field(result, path)
            if value is not None:
                result[target] = value
                break
    return result


class RecipeRuntime:
    def __init__(self, container):
        self.source = container
        self.plan = container.recipe.runtime
        self._cached = None
        self._lock = asyncio.Lock()

    def url(self, template, **values):
        base = self.source.base_url
        host = urlparse(base)
        raw = template.replace('{base}', base).replace('{api_base}', f'{host.scheme}://api.{host.hostname.removeprefix("www.")}')
        for key, value in values.items():
            raw = raw.replace('{' + key + '}', quote(str(value), safe=''))
        if re.search(r'\{\w+\}', raw):
            raise ValueError('Unresolved recipe URL parameter')
        return urljoin(base + '/', raw)

    async def catalogue(self):
        config = self.plan['catalogue']
        async with self._lock:
            if self._cached and time.monotonic() < self._cached[0]:
                return self._cached[1]
            data = json.loads(await self.source._fetch_html(self.url(config['url']), timeout=40))
            rows = data if isinstance(data, list) and config.get('allow_root_list', not config.get('root')) else field(data, config.get('root', ''))
            if not isinstance(rows, list):
                raise ValueError('Unexpected catalogue payload; expected a JSON list')
            rows = [normalize(r, config.get('aliases', {})) for r in rows if isinstance(r, dict)]
            self._cached = (time.monotonic() + config.get('ttl', 300), rows)
            return rows

    def slug(self, row):
        config = self.plan['catalogue']
        return row.get('slug') or re.sub(r'[^A-Za-z0-9 ]', '', row.get(config.get('slug_field', 'title')) or row.get('title') or '').replace(' ', '-').lower()

    def entries(self, rows):
        config = self.plan['catalogue']
        entries = []
        for row in rows:
            row = normalize(row, config.get('aliases', {}))
            title = row.get('title') or self.slug(row)
            if not title:
                continue
            versions = [(None, None, config.get('version', ''), None)]
            if config['kind'] == 'series':
                versions = [(n, lang, version, season)
                    for n, season in enumerate(row.get('seasons') or [], 1)
                    for lang, version in config['languages'].items()
                    if any(ep.get('languages', {}).get(lang, {}).get('players') for ep in season.get('episodes', []))]
            for season, language, version, _ in versions:
                href = self.url(config['entry_url'], slug=self.slug(row), season=season, language=language)
                ident = row.get('id') if row.get('id') is not None else self.slug(row)
                entries.append(AnimeResult(id=f'{ident}-{season}-{language}' if season else str(ident),
                    title=f'{title} S{season} ({version})' if season else title,
                    url=href, imageUrl=row.get('poster') or '', version=version,
                    genres=[str(g) for g in row.get('genres') or []], source=self.source.pkg))
        return entries

    async def search(self, query):
        if 'catalogue' in self.plan:
            rows = await self.catalogue()
            config = self.plan['catalogue']
            return self.entries([r for r in rows if query.casefold() in json.dumps([field(r, f) for f in config.get('search_fields', ['title', 'slug'])], ensure_ascii=False).casefold()])[:50]
        config = self.plan['search']
        target = self.source.recipe.search_request_path.replace('{query}', quote_plus(query))
        data = json.loads(await self.source._fetch_html(self.url(target)))
        if not isinstance(data, list):
            raise ValueError('Unexpected search payload; expected a JSON list')
        results = []
        for row in data:
            if not isinstance(row, dict) or not row.get(config['title']) or not row.get(config['link']):
                continue
            link = row[config['link']]
            if not link.startswith(('/', 'http')):
                link = config.get('relative_prefix', '') + link
            href = urljoin(self.source.base_url, link)
            image = row.get(config.get('image')) or ''
            if config.get('image_replace'):
                image = image.replace(*config['image_replace'])
            results.append(AnimeResult(id=hashlib.sha256(href.encode()).hexdigest()[:16],
                title=BeautifulSoup(row[config['title']], 'html.parser').get_text(), url=href,
                imageUrl=urljoin(self.source.base_url, image), version=config.get('version', ''), source=self.source.pkg))
        return results

    async def find(self, url):
        slug = urlparse(url).path.rstrip('/').split('/')[-1]
        return next((r for r in await self.catalogue() if self.slug(r) == slug), None)

    def selection(self, url):
        params = parse_qs(urlparse(url).query)
        season = int(params.get('s', ['1'])[0]) - 1
        episode = int(params.get('ep', ['1'])[0]) - 1
        if min(season, episode) < 0:
            raise ValueError('Invalid season or episode')
        return season, episode, params.get('lang', ['vo'])[0]

    async def detail(self, url):
        row = await self.find(url)
        if not row:
            return None
        config = self.plan['catalogue']
        version = config.get('version', '')
        title = row['title']
        episodes = []
        if config['kind'] == 'series':
            try:
                season, _, language = self.selection(url)
                version = config['languages'][language]
                data = row['seasons'][season]['episodes']
            except (KeyError, ValueError, IndexError):
                return None
            title += f' S{season+1}'
            for n, ep in enumerate(data, 1):
                if ep.get('languages', {}).get(language, {}).get('players'):
                    href = url.split('?', 1)[0] + '?' + urlencode({'lang': language, 's': season+1, 'ep': n})
                    episodes.append(Episode(number=n, title=ep.get('title') or f'Épisode {n}', version=version,
                        downloadPageUrl=href, playerUrl=href))
        else:
            episodes = [Episode(number=1, title=title, downloadPageUrl=url, playerUrl=url, version=version)]
        return AnimeDetail(title=title, url=url, imageUrl=row.get('poster') or '', source=self.source.pkg,
            synopsis=BeautifulSoup(row.get('description') or '', 'html.parser').get_text(),
            genres=row.get('genres') or [], version=version, episodes=episodes)

    def stream(self, url, name='Player', quality='HD'):
        return {'url': url, 'server': name, 'name': name, 'quality': quality,
                'format': 'hls' if '.m3u8' in url else 'mp4' if '.mp4' in url else 'embed'}

    async def players(self, url):
        config = self.plan.get('players', {})
        response = config.get('response')
        if response == 'url':
            row = await self.find(url)
            if not row:
                return []
            try:
                season, episode, language = self.selection(url)
                names = row['seasons'][season]['episodes'][episode]['languages'][language]['players']
            except (ValueError, KeyError, IndexError):
                return []
            sources = []
            for index, name in enumerate(names):
                target = self.url(config['url'], id=row['id'], season_index=season,
                    episode_index=episode, language=language, player_index=index)
                raw = await self.source._fetch_html(target)
                try:
                    link = json.loads(raw)
                except ValueError:
                    link = raw.strip()
                if isinstance(link, str) and link.startswith(('https://', 'http://')):
                    sources.append(self.stream(link, name))
            return sources
        if response == 'streams':
            data = json.loads(await self.source._fetch_html(self.url(config['url'], slug=urlparse(url).path.rstrip('/').split('/')[-1])))
            return [self.stream(s['url'], server.get('name', 'Player'), str(s.get(config['quality'], 'HD')) + ('p' if str(s.get(config['quality'], '')).isdigit() else ''))
                for server in field(data, config['servers'], []) for s in field(server, config['streams'], []) if s.get('url')]
        if response in ('redirects', 'json_html'):
            raw = await self.source._fetch_html(url)
            html = field(json.loads(raw), config['root']) if response == 'json_html' else raw
            soup = BeautifulSoup(html, 'html.parser')
            sources = []
            for item in soup.select(config['selector']):
                if response == 'json_html':
                    episode_id = parse_qs(urlparse(url).query).get('episodeId', [''])[0]
                    target = self.url(config['url'], server_id=item['data-id'], episode_id=episode_id)
                    link = field(json.loads(await self.source._fetch_html(target)), config['link_field'])
                    if link:
                        sources.append(self.stream(urljoin(url, link), item.get_text(strip=True)))
                else:
                    link = item.select_one(config['link'])
                    if not link:
                        continue
                    async with source_http.async_client(headers=self.source._get_headers(), timeout=12, follow_redirects=True) as client:
                        result = await client.get(urljoin(url, link['href']))
                        result.raise_for_status()
                    name = item.select_one(config['name'])
                    name = name.get_text(strip=True) if name else 'Player'
                    language = config['languages'].get(item.get(config['language_attr']), '')
                    stream = self.stream(str(result.url), name)
                    stream['name'] = f'{name} ({language})'
                    sources.append(stream)
            return sources
        return None

    async def episodes(self, url, soup, version):
        config = self.plan.get('episodes', {})
        kind = config.get('kind')
        if not kind:
            return None
        if kind == 'text_pairs':
            node = soup.select_one(config['selector'])
            result = []
            for entry in node.get_text().split() if node else []:
                number, sep, urls = entry.partition(config['separator'])
                try:
                    n = int(float(number))
                except ValueError:
                    continue
                links = [urljoin(url, link) for link in urls.split(',') if link.startswith(('http://', 'https://', '/'))]
                if not sep or not links:
                    continue
                # A local fragment preserves all players without using an invented URL scheme.
                href = links[0] + '#players=' + quote_plus(json.dumps(links)) if len(links) > 1 else links[0]
                result.append(Episode(number=n, title=f'Épisode {number}', playerUrl=href, downloadPageUrl=href, version=version))
            return sorted(result, key=lambda e: e.number)
        if kind == 'js_arrays':
            arrays = self.arrays(str(soup), config)
            directory = url if url.endswith('/') else url + '/'
            if not arrays:
                paths = re.findall(config['pages_pattern'], str(soup))
                for path in paths:
                    if path.strip('/') in ('', 'url'):
                        continue
                    sub = urljoin(directory, path.strip('/') + '/')
                    html = await self.source._fetch_html(sub)
                    arrays = self.arrays(html, config)
                    if not arrays:
                        arrays = self.arrays(await self.source._fetch_html(urljoin(sub, config['script_path'])), config)
                    if arrays:
                        break
                if not arrays:
                    arrays = self.arrays(await self.source._fetch_html(urljoin(directory, config['script_path'])), config)
            result = []
            for n in range(max((len(a) for a in arrays.values()), default=0)):
                links = [urljoin(url, a[n]) for a in arrays.values() if n < len(a) and a[n]]
                if links:
                    href = links[0] + '#players=' + quote_plus(json.dumps(links)) if len(links) > 1 else links[0]
                    result.append(Episode(number=n+1, title=f'Épisode {n+1:02d}', playerUrl=href, downloadPageUrl=href, version=version))
            return result
        if kind == 'json_html':
            canonical = soup.select_one('link[rel="canonical"]')
            page_id = urlparse(canonical.get('href') if canonical else url).path.rstrip('/').rsplit('-', 1)[-1]
            raw = await self.source._fetch_html(self.url(config['url'], page_id=page_id))
            pages = [(url, BeautifulSoup(field(json.loads(raw), config['root']), 'html.parser'))]
        elif kind == 'pages':
            links = list(dict.fromkeys(urljoin(url, a['href']) for a in soup.select(config['pages'])))
            pages = [(link, soup if link == url else BeautifulSoup(await self.source._fetch_html(link), 'html.parser')) for link in links or [url]]
        else:
            raise NotImplementedError('Unsupported episode recipe operation: ' + str(kind))
        results, seen = [], set()
        for page_url, page in pages:
            for item in page.select(config['selector']):
                link = item.select_one(config['link']) if config.get('link') else item
                if not link or not link.get('href'):
                    continue
                href = urljoin(page_url, link['href'])
                if kind == 'json_html':
                    episode_id = parse_qs(urlparse(href).query).get('ep', [''])[0]
                    href = self.url(config['entry_url'], episode_id=episode_id)
                if href in seen:
                    continue
                seen.add(href)
                node = item.select_one(config['number']) if config.get('number') else item
                raw_number = node.get(config.get('number_attr', ''), len(results)+1) if node else len(results)+1
                try:
                    number = int(float(raw_number))
                except (ValueError, TypeError):
                    number = len(results)+1
                results.append(Episode(number=number, title=link.get('title') or link.get_text(' ', strip=True) or f'Épisode {number}',
                    playerUrl=href, downloadPageUrl=href, version=config.get('version', version)))
        return sorted(results, key=lambda e: e.number)

    @staticmethod
    def arrays(text, config):
        # Parse only literal URL arrays, never evaluate downloaded JavaScript.
        result = {}
        for name, body in re.findall(config['array_pattern'], text or '', re.S):
            tokens = re.findall(r'''(["'])(.*?)\1|(\bnull\b)''', body, re.S)
            result[name] = [value.replace(r'\/', '/') if value.replace(r'\/', '/').startswith(('http://', 'https://')) else '' for _, value, _ in tokens]
        return result
