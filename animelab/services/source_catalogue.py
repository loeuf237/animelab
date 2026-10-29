from animelab.services.source_registry import source_registry, RegisteredSource, source_identity
"""Browse each source using its actual routes, filters and extension recipe."""
import hashlib
import json
import time
import unicodedata
from urllib.parse import urljoin, urlparse, urlencode, parse_qs, parse_qsl, quote_plus

from bs4 import BeautifulSoup

from animelab.models.anime import AnimeResult
from animelab.services.source_http import source_http
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
from animelab.services.animepahe_service import animepahe_service
from animelab.services.extension_service import extension_service
from animelab.services.aniyomi_container import _safe_select, _safe_select_one, _item_title


class CatalogueError(ValueError):
    pass


class SourceCatalogueService:
    def __init__(self):
        self._filters = {}
        self._cursors = {}

    def provider(self, source_id):
        return source_registry.get(source_id)

    def descriptor(self, source_id, service):
        return (service if isinstance(service, RegisteredSource) else source_registry.describe(source_id, service)).descriptor()

    def sources(self):
        entries = [self.descriptor(sid, self.provider(sid)) for sid in ('voir-anime', 'animepahe', 'french-manga')]
        active = {source_identity(ext,ext.pkg): ext for ext in extension_service.get_enabled_container_sources()}
        entries += [self.descriptor(sid, ext) for sid, ext in active.items() if not getattr(ext,'metadata',{}).get('hidden')]
        for saved in extension_service.retained_source_descriptors():
            if saved['source_key'] not in active and not saved['hidden']:
                entries.append({'id':saved['source_key'],'name':saved['name'],'lang':saved['lang'],
                                'baseUrl':saved['base_url'],'type':'imported','isEnabled':False,'views':[],
                                'multiTags':True,'state':'unavailable'})
        # A compiled recipe represents an installed extension; repository listings
        # without a recipe remain in the Extensions store.
        for ext in extension_service.get_visible_extensions():
            if ext.get('recipe_json') and ext['pkg'] not in active and not any(src.pkg==ext['pkg'] for src in active.values()):
                entries.append({'id': ext['pkg'], 'name': ext['name'], 'type': 'imported',
                                'lang': ext['lang'], 'baseUrl': ext.get('base_url') or '',
                                'isEnabled': False, 'views': [], 'multiTags': False})
        return entries

    async def html(self, service, url, method='GET', data=None):
        async with source_http.async_client(headers={'Referer': service.base_url + '/'}, timeout=15) as client:
            response = await client.request(method, url, data=data)
            response.raise_for_status()
            return response.text, str(response.url)

    async def filters(self, source_id):
        service = self.provider(source_id).service
        if getattr(service,'runtime','') == 'android-apk':
            return {'tags':[], 'groups':[], 'orders':[{'id':'source','label':'Ordre de la source'}],
                    'nativeFilters':await service.call('filters')}
        recipe = getattr(service, 'recipe', None)
        revision = hashlib.sha256(json.dumps(recipe.to_dict(), sort_keys=True).encode()).hexdigest() if recipe else ''
        key = (source_id, service.base_url, revision)
        cached = self._filters.get(key)
        if cached and cached['expires'] > time.monotonic():
            return cached
        tags, orders = [], [{'id': 'source', 'label': 'Ordre de la source'},
                            {'id': 'title', 'label': 'Titre A → Z (page)'},
                            {'id': 'title_desc', 'label': 'Titre Z → A (page)'}]
        recipe = getattr(service, 'recipe', None)
        if recipe and recipe.runtime.get('catalogue'):
            items = await self.api_catalogue(service)
            labels = sorted({label for item in items for label in item.genres}, key=str.casefold)
            seen_values = set()
            for label in labels:
                seen_values.add(label.casefold())
                tags.append({'id': hashlib.sha256(label.encode()).hexdigest()[:16], 'label': label,
                             'group': 'Genres', 'value': label})
            if recipe and recipe.filter_tags:
                for label, val in recipe.filter_tags.items():
                    if str(val).casefold() not in seen_values and label.casefold() not in seen_values:
                        seen_values.add(str(val).casefold())
                        tags.append({'id': hashlib.sha256(f"Genres:{val}".encode()).hexdigest()[:16],
                                     'label': label, 'group': 'Genres', 'value': str(val)})
            if recipe and recipe.filter_groups:
                for grp in recipe.filter_groups:
                    g_label = grp.get('label') or grp.get('key') or 'Filtres'
                    g_param = grp.get('param') or grp.get('key') or ''
                    for opt in grp.get('options') or []:
                        val = str(opt.get('value') or '')
                        lbl = str(opt.get('label') or val)
                        if val:
                            tags.append({'id': hashlib.sha256(f"{g_label}:{val}".encode()).hexdigest()[:16],
                                         'label': lbl, 'group': g_label, 'value': val, 'param': g_param})
            orders = [{'id': 'source', 'label': 'Ordre de la source'}, {'id': 'title', 'label': 'Titre A → Z'},
                      {'id': 'title_desc', 'label': 'Titre Z → A'}]
            if recipe and recipe.filter_orders:
                existing_orders = {o['id'] for o in orders}
                for label, val in recipe.filter_orders.items():
                    if val and val not in existing_orders:
                        orders.append({'id': val, 'label': label})
                        existing_orders.add(val)
        elif recipe and (recipe.filter_tags or recipe.filter_groups or recipe.filter_orders):
            for label, val in (recipe.filter_tags or {}).items():
                val_str = str(val)
                tag_url = ''
                if recipe.tag_request_path:
                    rel = recipe.tag_request_path.replace('{tag}', quote_plus(val_str)).replace('{page}', '1')
                    tag_url = urljoin(service.base_url + '/', rel)
                ident = hashlib.sha256(f"Genres:{label}:{val_str}".encode()).hexdigest()[:16]
                tags.append({'id': ident, 'label': label, 'group': 'Genres', 'url': tag_url,
                             'value': val_str, 'param': recipe.tag_param or ''})
            for grp in (recipe.filter_groups or []):
                g_label = grp.get('label') or grp.get('key') or 'Filtres'
                g_param = grp.get('param') or grp.get('key') or ''
                for opt in grp.get('options') or []:
                    val_str = str(opt.get('value') or '')
                    lbl = str(opt.get('label') or val_str)
                    if not val_str:
                        continue
                    ident = hashlib.sha256(f"{g_label}:{lbl}:{val_str}".encode()).hexdigest()[:16]
                    tags.append({'id': ident, 'label': lbl, 'group': g_label, 'url': '',
                                 'value': val_str, 'param': g_param})
            if recipe.filter_orders:
                existing_orders = {o['id'] for o in orders}
                for label, val in recipe.filter_orders.items():
                    if val and val not in existing_orders:
                        orders.append({'id': val, 'label': label})
                        existing_orders.add(val)
        elif source_id != 'animepahe':
            target = service.base_url + ('/?s=&post_type=wp-manga' if source_id == 'voir-anime' else '/')
            html, final_url = await self.html(service, target)
            soup = BeautifulSoup(html, 'html.parser')
            seen = set()
            for link in soup.select('a[href]'):
                href = urljoin(final_url, link['href'])
                path = urlparse(href).path
                label = link.get_text(' ', strip=True)
                if (urlparse(href).hostname != urlparse(final_url).hostname or not label or
                    not any(marker in path for marker in ('/genre/', '/anime-genre/', '/manga-genre/', '/tag/', '/xfsearch/'))):
                    continue
                if href in seen:
                    continue
                seen.add(href)
                group = 'Tags' if '/tag/' in path or '/tagz/' in path else 'Genres'
                if '/version-serie/' in path: group = 'Langue'
                if '/serie-statut/' in path: group = 'Statut'
                ident = hashlib.sha256(href.encode()).hexdigest()[:16]
                tags.append({'id': ident, 'label': label, 'group': group, 'url': href,
                             'value': path.rstrip('/').split('/')[-1]})
            if source_id == 'voir-anime':
                # These values are exposed by VoirAnime's advanced search form.
                orders = [{'id': value, 'label': label} for value, label in
                          [('source', 'Ordre de la source'), ('latest', 'Date de mise à jour'), ('alphabet', 'Titre A → Z'),
                           ('rating', 'Note'), ('trending', 'Populaires'), ('views', 'Plus vues'), ('new-manga', 'Nouveautés')]]
        groups = [{'name': name, 'single': False} for name in dict.fromkeys(t['group'] for t in tags)]
        for group in (recipe.filter_groups if recipe else []) or []:
            name = group.get('label') or group.get('key') or 'Filtres'
            meta = next((g for g in groups if g['name'] == name), None)
            if meta is not None:
                meta.update(param=group.get('param') or group.get('key') or '', single=not group.get('multi', False))
        value = {'tags': tags, 'groups': groups, 'orders': orders, 'expires': time.monotonic() + 600}
        if len(self._filters) >= 64: self._filters.pop(next(iter(self._filters)))
        self._filters[key] = value
        return value

    @staticmethod
    def _number(value):
        try:
            return float(value or 0)
        except (TypeError, ValueError):
            return 0.0

    @staticmethod
    def _filter_value(value):
        return ''.join(c for c in unicodedata.normalize('NFKD', str(value or '')) if not unicodedata.combining(c)).strip().casefold()

    async def api_catalogue(self, service, *, order='source', selected=()):
        config = service.recipe.runtime['catalogue']
        if config['kind'] == 'series':
            entries = []
            rows = list(await service.data_runtime.catalogue())
            if order == 'note':
                rows.sort(key=lambda row: self._number(row.get('note')), reverse=True)
            elif order in ('latest', 'created_at_unix'):
                rows.reverse()
            format_tags = [t for t in selected if t.get('param') == 'format']
            status_tags = [t for t in selected if t.get('param') == 'status']
            formats = {'movie': 'film', 'serie': 'tv', 'serie tv': 'tv', 'series': 'tv'}
            for row in rows:
                row_format = self._filter_value(row.get('format'))
                if format_tags and not any(formats.get(self._filter_value(t['value']), self._filter_value(t['value'])) == formats.get(row_format, row_format) for t in format_tags):
                    continue
                items = service.data_runtime.entries([row])
                for item in items:
                    # Earlier seasons are completed even while the last one is ongoing.
                    season = int(parse_qs(urlparse(item.url).query).get('s', ['1'])[0])
                    status = 'TERMINÉ' if season < len(row.get('seasons') or []) else row.get('status')
                    if status_tags and not any(self._filter_value(t['value']) == self._filter_value(status) for t in status_tags):
                        continue
                    item.genres = [str(g) for g in row.get('genres') or []]
                    entries.append(item)
            return entries
        rows = await service.data_runtime.catalogue()
        metric = order if order in ('likes', 'views', 'created_at_unix', 'released_at_unix') else 'created_at_unix'
        rows = sorted(rows, key=lambda r: self._number(r.get(metric)), reverse=True)
        return service.data_runtime.entries(rows)

    def parse_generic(self, html, url, service, selector=None):
        soup = BeautifulSoup(html, 'html.parser')
        recipe = getattr(service, 'recipe', None)
        cards = _safe_select(soup, selector or (recipe.popular_selector if recipe else '') or
                             '.anime-card, .movie-poster, .page-item-detail, article, .item')
        if not cards and service is animepahe_service:
            cards = soup.select('a[href*="/anime/"]')
        results, seen = [], set()
        for card in cards:
            link = _safe_select_one(card, (recipe.item_link_selector if recipe else '') or 'a[href]') or (card if card.name == 'a' else None)
            if not link or not link.get('href'): continue
            href = urljoin(url, link['href'])
            if any(part in href for part in (recipe.runtime.get('exclude_urls', []) if recipe else [])): continue
            if href in seen or urlparse(href).scheme not in ('http', 'https'): continue
            image = _safe_select_one(card, (recipe.item_thumb_selector if recipe else '') or 'img')
            title = _item_title(card, link, (recipe.item_title_selector if recipe else '') or
                                'h2, h3, h4, .title, .movie-title', image)
            if not title: continue
            seen.add(href)
            raw_image = (image.get('data-src') or image.get('data-lazy-src') or image.get('src') or '') if image else ''
            genres = [a.get_text(' ', strip=True) for a in card.select('a[href*="genre"], .genre, .genres a')]
            results.append(AnimeResult(id=hashlib.sha256(href.encode()).hexdigest()[:16], title=title,
                          url=href, imageUrl=urljoin(url, raw_image) if raw_image else '', genres=genres, version="VF" if "/vf/" in href else "VOSTFR" if "/vostfr/" in href else ""))
        return results

    def context(self, source_id, mode, query, tags, order):
        return (source_id, mode, query, tuple(sorted(tags)), order)

    def remember_cursor(self, context, target='', offset=0):
        self._cursors = {k: v for k, v in self._cursors.items() if v['expires'] > time.monotonic()}
        if len(self._cursors) >= 256: self._cursors.pop(next(iter(self._cursors)))
        ident = hashlib.sha256(repr((context, target, offset)).encode()).hexdigest()
        self._cursors[ident] = {'url': target, 'offset': offset, 'context': context, 'expires': time.monotonic()+1800}
        return ident

    def next_cursor(self, html, url, context, selector=''):
        soup = BeautifulSoup(html, 'html.parser')
        link = _safe_select_one(soup, selector) if selector else None
        if not link:
            link = soup.select_one('a[rel="next"], a.next, .next a, .pagination a[aria-label="Next"], .wp-pagenavi a.nextpostslink')
        # DLE uses a "next" anchor inside its navigation without rel/class.
        if not link:
            link = next((a for a in soup.select('.navigation a[href], .pagination a[href], .wp-pagenavi a[href]')
                         if a.get_text(strip=True) in ('»', '›', '→', 'Suivant', 'Next')), None)
        if not link or not link.get('href'): return None
        target = urljoin(url, link['href'])
        if urlparse(target)._replace(fragment='') == urlparse(url)._replace(fragment='') or urlparse(target).hostname != urlparse(url).hostname: return None
        return self.remember_cursor(context, target)

    async def browse(self, source_id, mode='latest', query='', tags=(), order='source', cursor=None, native_filters=None):
        provider=self.provider(source_id)
        if getattr(provider.service,'runtime','') == 'android-apk':
            if mode not in ('search','popular','catalogue','latest') or (mode=='latest' and not provider.service.supports_latest):
                raise CatalogueError('Opération indisponible pour cette source APK.')
            context=(source_id,mode,query,json.dumps(native_filters,sort_keys=True),order)
            page=1
            if cursor:
                saved=self._cursors.get(cursor)
                if not saved or saved['context']!=context or saved['expires'] < time.monotonic():
                    raise CatalogueError('La page a expiré ; rechargez le catalogue')
                page=saved['offset']
            result=await provider.observe('browse',provider.service.catalogue('popular' if mode=='catalogue' else mode,
                                           page=page,query=query,filters=native_filters))
            return {'source':source_id,'results':result['results'],'queryScope':'catalogue',
                    'nextCursor':self.remember_cursor(context,offset=page+1) if result['hasNextPage'] else None}
        return await provider.observe('browse',self._browse(source_id,mode,query,tags,order,cursor))

    async def _browse(self, source_id, mode='latest', query='', tags=(), order='source', cursor=None):
        service = self.provider(source_id).service
        recipe = getattr(service, 'recipe', None)
        api_catalogue = bool(recipe and recipe.runtime.get('catalogue'))
        descriptor = self.descriptor(source_id, service)
        if mode not in [v['id'] for v in descriptor['views']]:
            raise CatalogueError('Ce catalogue n’est pas proposé par cette source')
        query = query.strip()
        if mode == 'search' and not query and not tags:
            return {'source': source_id, 'results': [], 'nextCursor': None, 'queryScope': 'catalogue'}
        context = self.context(source_id, mode, query, tags, order)
        html, url, selector, next_selector = '', '', '', ''
        selected, offset = [], 0
        if tags or order != 'source':
            filters = await self.filters(source_id)
            selected = [next((t for t in filters['tags'] if t['id'] == ident), None) for ident in tags]
            if any(t is None for t in selected): raise CatalogueError('Filtre inconnu ; actualisez les filtres de cette source')
            if len(selected) > 1 and not descriptor['multiTags']: raise CatalogueError('Cette source accepte un seul filtre à la fois')
            for group in filters.get('groups', []):
                if group.get('single') and sum(t['group'] == group['name'] for t in selected) > 1:
                    raise CatalogueError('Sélectionnez une seule option pour le groupe ' + group['name'])
            if order not in [o['id'] for o in filters['orders']]: raise CatalogueError('Tri inconnu')
        if cursor:
            saved = self._cursors.get(cursor)
            if not saved or saved['context'] != context or saved['expires'] < time.monotonic():
                raise CatalogueError('La page a expiré ; rechargez le catalogue')
            url = saved['url']
            offset = saved.get('offset', 0)

        if api_catalogue:
            effective_order = order
            if order == 'source':
                feed_id = mode.split(':', 1)[-1]
                if mode == 'featured' and recipe.custom_feeds:
                    feed_id = recipe.custom_feeds[0]['id']
                if mode == 'popular' or feed_id in ('top_rated', 'likes'):
                    effective_order = recipe.runtime['catalogue']['popular_order']
                elif feed_id == 'views':
                    effective_order = 'views'
                elif mode == 'latest':
                    effective_order = recipe.runtime['catalogue']['latest_order']
            # Sort/filter the complete catalogue before applying the cursor offset.
            items = await self.api_catalogue(service, order=effective_order, selected=selected)
            if mode == 'feed:vf':
                items = [i for i in items if i.version.upper() == 'VF']
            if query: items = [i for i in items if query.casefold() in i.title.casefold()]
            if selected:
                genre_tags = [t for t in selected if t.get('group', 'Genres') == 'Genres']
                lang_tags = [t for t in selected if t.get('group') == 'Langue']
                if genre_tags:
                    items = [i for i in items if all(any(t['value'].casefold() == g.casefold() for g in i.genres) for t in genre_tags)]
                if lang_tags:
                    items = [i for i in items if any(t['value'].upper() in (i.version.upper(), i.title.upper()) for t in lang_tags)]
            if order in ('title', 'title_desc', 'title_sortable'):
                items.sort(key=lambda i: i.title.casefold(), reverse=order == 'title_desc')
            cursor = None
            if offset + 48 < len(items):
                cursor = self.remember_cursor(context, offset=offset+48)
            items = items[offset:offset+48]
        elif source_id == 'voir-anime':
            params = [('s', query), ('post_type', 'wp-manga')]
            if order != 'source': params.append(('m_orderby', order))
            elif mode == 'popular': params.append(('m_orderby', 'trending'))
            elif mode == 'latest': params.append(('m_orderby', 'latest'))
            params += [('genre[]', t['value']) for t in selected]
            if selected: params.append(('op', 'AND'))
            url = url or service.base_url + '/?' + urlencode(params)
            html, url = await self.html(service, url)
            items = service.parse_cards(html)
        elif source_id == 'french-manga':
            if query and not selected and mode == 'search':
                items = await service.search_anime(query)
            else:
                path = '/manga-streaming-1/coups-de-cur/' if mode == 'featured' else '/manga-streaming-1/'
                url = url or (selected[0]['url'] if selected else service.base_url + path)
                html, url = await self.html(service, url)
                items = service.parse_search_results(html)
                if query: items = [i for i in items if query.casefold() in i.title.casefold()]
        elif source_id == 'animepahe':
            if mode == 'search':
                items = await service.search_anime(query)
            elif mode == 'latest':
                page = '1'
                if url: page = parse_qs(urlparse(url).query).get('page', ['1'])[0]
                data = await service._fetch_api('/api?' + urlencode({'m': 'airing', 'page': page}), timeout=12)
                if data is None: raise CatalogueError('AnimePahe refuse l’accès ou est momentanément inaccessible')
                items = [AnimeResult(id=str(row.get('anime_id', row.get('id', ''))), title=row['anime_title'],
                         url=service.base_url + '/anime/' + row['anime_session'], imageUrl=row.get('snapshot') or '',
                         version='VOST / Sub', episodeInfo=f"Épisode {row.get('episode', '')}")
                         for row in data.get('data', []) if row.get('anime_title') and row.get('anime_session')]
                next_url = data.get('next_page_url')
                if next_url:
                    # Only a page number from the source API is accepted.
                    page_number = parse_qs(urlparse(next_url).query).get('page', [''])[0]
                    if page_number.isdigit():
                        target = service.base_url + '/api?' + urlencode({'m': 'airing', 'page': page_number})
                        cursor = self.remember_cursor(context, target)
                    else: cursor = None
                else: cursor = None
            else:
                html, url = await self.html(service, url or service.base_url + '/anime')
                items = self.parse_generic(html, url, service)
        else:
            recipe = service.recipe
            custom_feed = None
            if mode.startswith('feed:') and recipe.custom_feeds:
                fid = mode.split(':', 1)[1]
                custom_feed = next((f for f in recipe.custom_feeds if f.get('id') == fid), None)
            elif mode == 'featured' and recipe.custom_feeds:
                custom_feed = recipe.custom_feeds[0]

            if mode == 'search' and recipe.runtime.get('search') and not selected and not url:
                items = await service.search_anime(query)
            else:
                if custom_feed:
                    path = custom_feed.get('path') or '/'
                else:
                    path = (recipe.search_request_path if mode == 'search' else
                            recipe.latest_request_path if mode == 'latest' else recipe.popular_request_path) or '/'
                path = path.replace('{page}', '1').replace('{query}', quote_plus(query))
                method, data = 'GET', None
                if mode == 'search' and not selected:
                    method = recipe.search_method.upper()
                    if method == 'POST':
                        data = {k: v.replace('{query}', query) for k, v in recipe.search_post_params.items()}
                        data[recipe.search_query_param or 's'] = query
                    elif '{query}' not in (recipe.search_request_path or ''):
                        path += ('&' if '?' in path else '?') + urlencode({recipe.search_query_param or 's': query})
                if not url:
                    param_tags = [t for t in selected if t.get('param')]
                    if param_tags:
                        base_filter_path = path
                        if recipe.tag_request_path and '{tag}' in recipe.tag_request_path:
                            base_filter_path = recipe.tag_request_path.replace('{page}', '1').replace('{tag}', '').replace('{query}', quote_plus(query))
                        extra_params = [(t['param'], t['value']) for t in param_tags]
                        if query and (recipe.search_query_param or 's'):
                            extra_params.insert(0, (recipe.search_query_param or 's', query))
                        if order not in ('source', 'title', 'title_desc') and recipe.order_param:
                            extra_params.append((recipe.order_param, order))
                        parsed = urlparse(base_filter_path)
                        defaults = parse_qsl(urlparse(path).query, keep_blank_values=True)
                        template_defaults = parse_qsl(parsed.query, keep_blank_values=True)
                        template_keys = {k for k, _ in template_defaults}
                        defaults = [(k, v) for k, v in defaults if k not in template_keys] + template_defaults
                        replaced = {k for k, _ in extra_params}
                        params = [(k, v) for k, v in defaults if k not in replaced] + extra_params
                        url = urljoin(service.base_url + '/', parsed._replace(query=urlencode(params)).geturl())
                    elif selected and selected[0].get('url'):
                        url = selected[0]['url']
                    else:
                        if order not in ('source', 'title', 'title_desc') and recipe.order_param:
                            path += ('&' if '?' in path else '?') + urlencode({recipe.order_param: order})
                        url = urljoin(service.base_url + '/', path)
                if selected:
                    method, data = 'GET', None
                html, url = await self.html(service, url, method, data)
                if custom_feed and custom_feed.get('selector'):
                    selector = custom_feed['selector']
                else:
                    selector = recipe.search_selector if mode == 'search' else recipe.latest_selector if mode == 'latest' else recipe.popular_selector
                next_selector = recipe.search_next_selector if mode == 'search' else recipe.latest_next_selector if mode == 'latest' else recipe.popular_next_selector
                items = await service.data_runtime.expand_listing(self.parse_generic(html, url, service, selector))
                if query and selected and not any(t.get('param') for t in selected):
                    items = [i for i in items if query.casefold() in i.title.casefold()]
        page_query = bool(query and source_id != 'voir-anime' and not api_catalogue and (selected or mode != 'search') and not any(t.get('param') for t in selected))
        if page_query:
            items = [i for i in items if query.casefold() in i.title.casefold()]
        if order in ('title', 'title_desc') and not api_catalogue:
            items = sorted(items, key=lambda i: i.title.casefold(), reverse=order == 'title_desc')
        seen, results = set(), []
        for item in items:
            item.source = source_id
            if item.url not in seen:
                seen.add(item.url)
                results.append(item)
        next_page = cursor if api_catalogue or source_id == 'animepahe' and mode == 'latest' else self.next_cursor(html, url, context, next_selector) if html else None
        return {'source': source_id, 'results': results, 'nextCursor': next_page,
                'queryScope': 'page' if page_query else 'catalogue'}


source_catalogue = SourceCatalogueService()
