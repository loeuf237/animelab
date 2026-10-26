from animelab.services.animepahe_service import animepahe_service
from animelab.services.scraping_service import scraping_service
from animelab.services.voiranime_service import voiranime_service
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

import httpx
import pytest
from fastapi.testclient import TestClient

from run import app
from animelab.models.anime import AnimeResult
from animelab.routers import anime as anime_router
from animelab.services.source_catalogue import SourceCatalogueService, CatalogueError
from animelab.services.source_http import VerificationRequired
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.aniyomi_dex_parser import SourceRecipe
from animelab.services.extension_service import extension_service


@pytest.fixture
def providers(monkeypatch):
    for service in (scraping_service, voiranime_service, animepahe_service):
        monkeypatch.setattr(service, 'search_anime', AsyncMock(return_value=[]))
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [])
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda sid: None)
    return TestClient(app)


def test_global_search_keeps_results_and_exposes_challenges(providers, monkeypatch):
    challenge = VerificationRequired('https://voir-anime.to/?s=naruto')
    voiranime_service.search_anime.side_effect = challenge
    scraping_service.search_anime.return_value = [AnimeResult(id='1', title='Naruto', url='https://fm.example/1')]
    response = providers.get('/api/search', params={'q': 'naruto', 'source': 'all', 'include_challenges': 'true'})
    assert response.status_code == 200
    data = response.json()
    assert data['results'][0]['source'] == 'french-manga'
    assert data['challenges'] == [{**challenge.to_dict(), 'source': 'voir-anime'}]
    assert not data['errors']
    # Legacy callers must receive a real error rather than an empty result set.
    assert providers.get('/api/search?q=naruto&source=all').status_code == 409


def test_targeted_search_challenge_and_cookie_validation_retry(providers, monkeypatch, tmp_path):
    from curl_cffi.requests import Cookies
    from animelab.services.source_http import SourceHTTPService
    from animelab.services.browser_verification import BrowserVerificationService
    from animelab.routers import network
    import time
    url = 'https://source.example/search?q=naruto'
    class Session:
        def __init__(self, **kwargs): self.cookies = Cookies()
        def request(self, method, target, **kwargs):
            success = self.cookies.get('clearance') == 'verified'
            return httpx.Response(200 if success else 403, text='Naruto' if success else 'challenge',
                headers={'cache-control':'no-store', **({} if success else {'cf-mitigated':'challenge'})}, request=httpx.Request(method, target))
        def close(self): pass
    monkeypatch.setattr('animelab.services.source_http.is_safe_url', lambda target: target == url)
    transport = SourceHTTPService(storage=tmp_path, min_interval=0, session_factory=Session)
    browser = BrowserVerificationService(transport)
    browser._cdp = AsyncMock(return_value={'cookies':[{'name':'clearance','value':'verified','domain':'source.example'}]})
    browser.jobs['job'] = {'id':'job','domain':'source.example','url':url,'created':time.monotonic(), 'mode':'browser','window':None,'process':None}
    monkeypatch.setattr(network, 'browser_verification', browser)
    monkeypatch.setattr(network.download_manager, 'resume_verified_domain', lambda domain: 0)
    async def search(q):
        response = await transport.async_client().get(url)
        return [AnimeResult(id='1', title=response.text, url='https://source.example/anime/1')]
    monkeypatch.setattr(voiranime_service, 'search_anime', search)
    try:
        initial = providers.get('/api/search?q=naruto&source=voir-anime&include_challenges=true').json()
        assert initial['challenges'][0]['domain'] == 'source.example' and not initial['results']
        verified = providers.post('/api/network/verification/job/complete')
        assert verified.status_code == 200 and verified.json()['domain'] == 'source.example'
        retried = providers.get('/api/search?q=naruto&source=voir-anime&include_challenges=true').json()
        assert not retried['challenges'] and retried['results'][0]['title'] == 'Naruto'
    finally: transport.close()


def test_unknown_source_does_not_search_another_catalogue(providers):
    assert providers.get('/api/search?q=naruto&source=missing').status_code == 404
    scraping_service.search_anime.assert_not_called()


@pytest.fixture
def catalogue(monkeypatch):
    service = SourceCatalogueService()
    monkeypatch.setattr(extension_service, 'get_visible_extensions', lambda: [])
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [])
    return service


def test_source_list_includes_compiled_extensions_only(catalogue, monkeypatch):
    enabled = AniyomiContainerSource(SourceRecipe(pkg='installed', name='Installed', base_url='https://installed.example', popular_request_path='/popular', popular_selector='article'))
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [enabled])
    monkeypatch.setattr(extension_service, 'get_visible_extensions', lambda: [
        {'pkg':'available','name':'Available','lang':'fr','recipe_json':None},
        {'pkg':'disabled','name':'Disabled','lang':'fr','recipe_json':'{}'},
    ])
    sources = catalogue.sources()
    assert len(sources) == 5
    assert not any(s['id'] == 'available' for s in sources)
    assert next(s for s in sources if s['id'] == 'disabled')['isEnabled'] is False
    assert 'popular' in [v['id'] for v in next(s for s in sources if s['id'] == 'installed')['views']]
    assert 'popular' not in [view['id'] for source in sources if source['id']=='french-manga' for view in source['views']]


@pytest.mark.asyncio
async def test_empty_search_does_not_request_the_site(catalogue, monkeypatch):
    fetch = AsyncMock()
    search = AsyncMock()
    monkeypatch.setattr(catalogue, 'html', fetch)
    monkeypatch.setattr(scraping_service, 'search_anime', search)
    page = await catalogue.browse('french-manga', 'search')
    assert not page['results'] and page['nextCursor'] is None
    fetch.assert_not_called()
    search.assert_not_called()


@pytest.mark.asyncio
async def test_voiranime_combines_remote_genres_query_and_sort(catalogue, monkeypatch):
    html = '<a href="/anime-genre/action/">Action</a><a href="/anime-genre/comedy/">Comedy</a><a href="https://private.example/genre/hack">External</a>'
    requests = []
    async def fetch(service, url, *args): requests.append(url); return html, url
    monkeypatch.setattr(catalogue, 'html', fetch)
    filters = await catalogue.filters('voir-anime')
    assert len(filters['tags']) == 2
    tags = [t['id'] for t in filters['tags']]
    await catalogue.browse('voir-anime', 'popular', 'Naruto & Boruto', tags, 'views')
    params = parse_qs(urlparse(requests[-1]).query)
    assert params['s'] == ['Naruto & Boruto']
    assert params['genre[]'] == ['action', 'comedy'] and params['op'] == ['AND']
    assert params['m_orderby'] == ['views']


@pytest.mark.asyncio
async def test_recipe_popular_pagination_is_bound_to_criteria(catalogue, monkeypatch):
    source = AniyomiContainerSource(SourceRecipe(pkg='recipe', name='Recipe', base_url='https://source.example',
        popular_request_path='/popular/{page}', popular_selector='article', popular_next_selector='a.next'))
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda sid: source)
    calls = []
    async def fetch(service, url, *args):
        calls.append(url)
        if url.endswith('/2'): return '<article><a href="/anime/second"><img alt="Second" src="/2.jpg"></a></article>', url
        return '<article><a href="/anime/first"><img alt="First" src="/1.jpg"></a></article><a class="next" href="/popular/2">Next</a>', url
    monkeypatch.setattr(catalogue, 'html', fetch)
    first = await catalogue.browse('recipe', 'popular')
    assert first['results'][0].source == 'recipe' and first['results'][0].imageUrl == 'https://source.example/1.jpg'
    second = await catalogue.browse('recipe', 'popular', cursor=first['nextCursor'])
    assert second['results'][0].title == 'Second' and not second['nextCursor']
    with pytest.raises(CatalogueError, match='expiré'):
        await catalogue.browse('recipe', 'latest', cursor=first['nextCursor'])
    assert calls == ['https://source.example/popular/1', 'https://source.example/popular/2']


@pytest.mark.asyncio
async def test_filters_reject_unknown_ids_and_foreign_pagination(catalogue, monkeypatch):
    fetch = AsyncMock(return_value=('<a href="/xfsearch/tagz/magic/">Magie</a>', 'https://w16.french-manga.net/'))
    monkeypatch.setattr(catalogue, 'html', fetch)
    with pytest.raises(CatalogueError, match='Filtre inconnu'):
        await catalogue.browse('french-manga', tags=['http://127.0.0.1/private'])
    assert fetch.await_count == 1
    assert not catalogue.next_cursor('<a rel="next" href="http://127.0.0.1/private">Next</a>', 'https://source.example/', ('source',))
    assert not catalogue.next_cursor('<a rel="next" href="#">Next</a>', 'https://source.example/', ('source',))


@pytest.mark.asyncio
async def test_franime_api_tags_search_and_pagination(catalogue, monkeypatch):
    source = AniyomiContainerSource(SourceRecipe(pkg='animeextension.fr.franime', name='FRAnime', base_url='https://franime.fr'))
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda sid: source)
    rows = [AnimeResult(id=str(i),title=f'Anime {i:03}',url=f'https://franime.fr/anime/{i}',genres=['Action']) for i in range(70)]
    monkeypatch.setattr(catalogue, 'api_catalogue', AsyncMock(return_value=rows))
    filters = await catalogue.filters(source.pkg)
    first = await catalogue.browse(source.pkg, 'catalogue', 'Anime', [filters['tags'][0]['id']], 'title')
    assert len(first['results']) == 48 and first['queryScope'] == 'catalogue'
    second = await catalogue.browse(source.pkg, 'catalogue', 'Anime', [filters['tags'][0]['id']], 'title', first['nextCursor'])
    assert len(second['results']) == 22 and not second['nextCursor']


@pytest.mark.asyncio
async def test_animesama_multi_group_tags_and_custom_feeds(catalogue, monkeypatch):
    from animelab.services.aniyomi_dex_parser import AniyomiDexParser
    recipe = SourceRecipe(pkg='eu.kanade.tachiyomi.animeextension.fr.animesama', name='Anime-Sama')
    AniyomiDexParser._fill_heuristics(recipe)
    source = AniyomiContainerSource(recipe)
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda sid: source)
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [source])

    sources = catalogue.sources()
    animesama_desc = next(s for s in sources if s['id'] == recipe.pkg)
    view_ids = [v['id'] for v in animesama_desc['views']]
    assert 'popular' in view_ids
    assert 'feed:pepites' in view_ids
    assert 'feed:classiques' in view_ids

    filters = await catalogue.filters(recipe.pkg)
    assert any(t['group'] == 'Genres' and t['value'] == 'Action' for t in filters['tags'])
    assert any(t['group'] == 'Type' and t['value'] == 'Anime' for t in filters['tags'])
    assert any(t['group'] == 'Langue' and t['value'] == 'VOSTFR' for t in filters['tags'])

    requests = []
    sample_html = '''
    <div id="containerPepites">
      <div class="shrink-0 m-3 rounded border-2"><a href="/catalogue/frieren"><img src="/frieren.jpg"><h2 class="card-title">Frieren</h2></a></div>
    </div>
    <div id="list_catalog">
      <div class="catalog-card"><a href="/catalogue/solo-leveling"><img src="/sl.jpg"><h2 class="card-title">Solo Leveling</h2></a></div>
    </div>
    '''
    async def fetch(svc, url, *args):
        requests.append(url)
        return sample_html, url

    monkeypatch.setattr(catalogue, 'html', fetch)
    async def series_html(url, **kwargs):
        title = 'Frieren' if '/frieren/' in url else 'Solo Leveling'
        return f'<h1>{title}</h1><script>panneauAnime("Saison 1", "saison1/vostfr");</script>'
    monkeypatch.setattr(source, '_fetch_html', series_html)

    # Test custom feed "feed:pepites"
    pepites_page = await catalogue.browse(recipe.pkg, 'feed:pepites')
    assert len(pepites_page['results']) == 1
    assert pepites_page['results'][0].title == 'Frieren — Saison 1'

    # Test multi-parameter filter groups (genre[] + type[] + langue[])
    action_tag = next(t['id'] for t in filters['tags'] if t['group'] == 'Genres' and t['value'] == 'Action')
    type_tag = next(t['id'] for t in filters['tags'] if t['group'] == 'Type' and t['value'] == 'Anime')
    lang_tag = next(t['id'] for t in filters['tags'] if t['group'] == 'Langue' and t['value'] == 'VOSTFR')
    filtered_page = await catalogue.browse(recipe.pkg, 'catalogue', '', [action_tag, type_tag, lang_tag])
    assert any(r.title == 'Solo Leveling — Saison 1' for r in filtered_page['results'])
    parsed = parse_qs(urlparse(requests[-1]).query)
    assert parsed['genre[]'] == ['Action']
    assert parsed['type[]'] == ['Anime']
    assert parsed['langue[]'] == ['VOSTFR']
