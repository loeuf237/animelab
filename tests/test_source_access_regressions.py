from animelab.services.extension_service import extension_service
"""Source failures must remain distinguishable from a successful empty catalogue."""
import asyncio
from unittest.mock import AsyncMock
from types import SimpleNamespace

import httpx
import pytest
from bs4 import BeautifulSoup

from animelab.models.anime import AnimeResult
from animelab.routers import anime as router
from animelab.services.source_http import VerificationRequired
from animelab.services.voiranime_service import voiranime_service
from animelab.services.animepahe_service import animepahe_service
from animelab.services.scraping_service import scraping_service
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.aniyomi_dex_parser import SourceRecipe


@pytest.mark.asyncio
@pytest.mark.parametrize('original', [voiranime_service, animepahe_service, scraping_service])
async def test_empty_cache_refresh_runs_once_and_returns_first_results(original):
    service = object.__new__(type(original))
    service.latest_cache, service.last_cache_time, service.is_refreshing = [], 0, False
    service.base_url = "https://cache-source.example"
    async def refresh():
        await asyncio.sleep(0)
        service.latest_cache = [AnimeResult(id='one', title='One', url='https://source.example/one')]
    service.refresh_cache = AsyncMock(side_effect=refresh)
    results = await asyncio.gather(*(service.get_latest_releases() for _ in range(3)))
    assert all(result[0].title == 'One' for result in results)
    service.refresh_cache.assert_awaited_once()
    assert not service.is_refreshing


@pytest.mark.asyncio
async def test_home_feed_reports_protections_and_loads_more_than_four_extensions(monkeypatch):
    for service in (scraping_service, voiranime_service, animepahe_service):
        monkeypatch.setattr(service, 'get_latest_releases', AsyncMock(return_value=[]))
    challenge = VerificationRequired('https://animepahe.pw/api?m=airing')
    animepahe_service.get_latest_releases.side_effect = challenge
    extensions = [SimpleNamespace(pkg=f'ext{i}', name=f'Extension {i}', base_url=f'https://ext{i}.example',
        get_latest_releases=AsyncMock(return_value=[AnimeResult(id=str(i),title=f'Anime {i}',url=f'https://ext{i}.example/anime')])) for i in range(6)]
    extensions[1].get_latest_releases.side_effect = VerificationRequired('https://ext1.example/latest')
    extensions[2].get_latest_releases.side_effect = TimeoutError()
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: extensions)
    monkeypatch.setattr(router.library_service, 'get_all_favorites', lambda: [])
    monkeypatch.setattr(router.library_service, 'get_history', lambda: [])
    feed = await router.api_home_feed()
    assert feed['latestReleases']['ext5'][0]['title'] == 'Anime 5'
    assert {item['source'] for item in feed['challenges']} == {'animepahe', 'ext1'}
    assert feed['challenges'][0]['url'] == challenge.url
    assert feed['errors'][0]['source'] == 'ext2'
    assert all(ext.get_latest_releases.await_count == 1 for ext in extensions)


@pytest.mark.asyncio
async def test_animepahe_search_does_not_swallow_request_failure(monkeypatch):
    monkeypatch.setattr(animepahe_service, '_fetch_api', AsyncMock(side_effect=ValueError('Invalid API response')))
    with pytest.raises(ValueError, match='Invalid API'):
        await animepahe_service.search_anime('One Piece')


@pytest.mark.asyncio
async def test_extension_request_failure_is_not_an_empty_catalogue(monkeypatch):
    from animelab.services import aniyomi_container
    source = AniyomiContainerSource(SourceRecipe(pkg='test', base_url='https://source.example'))
    client = SimpleNamespace(request=AsyncMock(side_effect=httpx.ConnectError('offline')))
    class Context:
        async def __aenter__(self): return client
        async def __aexit__(self, *args): pass
    monkeypatch.setattr(aniyomi_container.source_http, 'async_client', lambda **kwargs: Context())
    with pytest.raises(httpx.ConnectError):
        await source.get_latest_releases()


def test_voiranime_current_madara_cards_prefer_title_and_lazy_image():
    html = '''<div class="page-listing-item"><div class="row">
      <div class="page-item-detail video"><div class="item-thumb"><a href="/anime/one/" title="One"><img src="placeholder.svg" data-src="/one.jpg"></a></div>
        <div class="item-summary"><div class="post-title font-title"><h3 class="h5"><a href="/anime/one/">One</a></h3></div><div class="list-chapter"><div class="chapter-item"><span class="chapter"><a class="btn-link" href="/anime/one/one-01-vostfr/">01</a></span></div></div></div></div>
      <div class="page-item-detail video"><div class="post-title"><h3 class="h5"><a href="/anime/two-vf/">Two (VF)</a></h3></div></div>
    </div></div>'''
    results = voiranime_service.parse_cards(html)
    assert [item.title for item in results] == ['One', 'Two (VF)']
    assert results[0].imageUrl.endswith('/one.jpg')
    assert results[0].episodeInfo == 'Ep 01'
    assert results[1].version == 'VF'


@pytest.mark.asyncio
async def test_voiranime_chapter_dropdown_and_current_player_scripts():
    soup = BeautifulSoup('''<select class="single-chapter-select"><option data-redirect="/anime/one/one-02-vostfr/">02</option><option data-redirect="/anime/one/one-01-vostfr/">01</option></select>''', 'html.parser')
    episodes = await voiranime_service.fetch_episodes('https://voir-anime.to/anime/one/', soup)
    assert [ep.number for ep in episodes] == [1, 2]
    assert all(ep.playerUrl.startswith('https://voir-anime.to/anime/one/') for ep in episodes)
    html = '''<script>const thisChapterSources = {"LECTEUR myTV":"<iframe data-src=\\"https://voembed.net/embed-1.html\\"></iframe>"} ;</script>'''
    assert voiranime_service._parse_episode_sources(html)['myTV'] == 'https://voembed.net/embed-1.html'


def test_manual_retry_keeps_blocked_state_until_transport_accepts(monkeypatch):
    import threading
    from fastapi.testclient import TestClient
    from run import app
    from animelab.services import source_http as transport_module
    url = 'https://source.example/search?q=one'
    state = SimpleNamespace(condition=threading.RLock(), blocked_url=url, generation=0, last_error='challenge')
    get = AsyncMock(side_effect=VerificationRequired(url))
    transport = SimpleNamespace(state=lambda target: state, async_client=lambda: SimpleNamespace(get=get))
    monkeypatch.setattr(transport_module, 'source_http', transport)
    client = TestClient(app)
    first = client.post('/api/network/recheck', json={'domain': 'source.example'})
    assert first.status_code == 409 and first.json()['url'] == url
    assert state.blocked_url == url
    get.side_effect = None
    get.return_value = httpx.Response(200, json={'data': []}, request=httpx.Request('GET', url))
    assert client.post('/api/network/recheck', json={'domain': 'source.example'}).status_code == 200
    assert state.blocked_url is None and state.last_error is None and state.generation == 1
    # Further retries do not invent another URL or make an unnecessary request.
    assert client.post('/api/network/recheck', json={'domain': 'source.example'}).status_code == 200
    assert get.await_count == 2


@pytest.mark.asyncio
async def test_imported_voiranime_old_recipe_reads_current_cards(monkeypatch):
    source = AniyomiContainerSource(SourceRecipe(pkg='imported.voiranime', base_url='https://voir-anime.to',
        search_selector='div.c-tabs-item__content, article', popular_selector='div.c-tabs-item__content, article'))
    monkeypatch.setattr(source, '_fetch_html', AsyncMock(return_value='<div class="page-item-detail video"><div class="post-title"><h3 class="h5"><a href="/anime/one/">One</a></h3></div><img src="/one.jpg"></div>'))
    results = await source.get_latest_releases()
    assert results[0].title == 'One' and results[0].source == source.pkg
    custom = AniyomiContainerSource(SourceRecipe(pkg='custom.voiranime', base_url=source.base_url, latest_selector='.custom-card'))
    assert custom.recipe.latest_selector == '.custom-card'


@pytest.mark.asyncio
@pytest.mark.parametrize('original', [voiranime_service, animepahe_service, scraping_service])
async def test_known_protection_is_reported_even_with_a_fresh_cache(original, monkeypatch):
    import time
    from animelab.services.source_http import source_http
    service = object.__new__(type(original))
    service.base_url = 'https://source.example'
    service.latest_cache = [AnimeResult(id='old',title='Cached anime',url='https://source.example/old')]
    service.last_cache_time = time.time()
    monkeypatch.setattr(source_http, 'state', lambda url: SimpleNamespace(blocked_url='https://source.example/blocked'))
    with pytest.raises(VerificationRequired) as error:
        await service.get_latest_releases()
    assert error.value.url == 'https://source.example/blocked'
