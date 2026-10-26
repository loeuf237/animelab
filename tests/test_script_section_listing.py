"""Anime-Sama's imported recipe must expose seasons, not flattened work cards."""
import json
from unittest.mock import AsyncMock

import pytest

from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.aniyomi_dex_parser import SourceRecipe
from animelab.services.recipe_plans import section_listing_plan

PKG = 'eu.kanade.tachiyomi.animeextension.fr.animesama'
BASE = 'https://anime-sama.to'
ROOT = BASE + '/catalogue/one-piece/'
CARDS = '''<div id="list_catalog"><div data-nom="One Piece" class="as-carte">
<a href="/catalogue/one-piece/"><img alt="" src="/one-piece.webp">
<span>Anime</span><span>Scans</span><img alt="VOSTFR" src="/flag.png">
<h3 class="as-carte-titre">One Piece</h3></a></div></div>
<div id="list_pagination"><a href="/catalogue/?search=one+piece&amp;page=2">2</a></div>'''
WORK = '''<h1 id="titreOeuvre">One Piece</h1><meta property="og:image" content="/one-piece.jpg">
<p id="synopsisText">Luffy et son équipage.</p><a class="genre-pill">Aventure</a>
<script>function panneauAnime(nom, url) { return url; }</script>
<script>const quotedPattern = /['"]/g;</script>
<script>/* panneauAnime("nom", "saison999/vostfr"); */
panneauAnime("Saga 1 East Blue [Episode 1 à 61]", "saison1/vostfr");
panneauAnime("Saga 2 Alabasta [Episode 62 à 143]", "saison2/vostfr");
panneauScan("Scans", "scan/vf");
panneauAnime("Films", "film/vostfr");
panneauAnime("Kai - Saga 1 (East Blue)", "kai/vostfr");
// panneauAnime("Commented", "saison666/vostfr");
panneauAnime("Unsafe", "https://unrelated.example/saison3/vostfr");
panneauAnime("Traversal", "../another-series/saison1/vostfr");
panneauAnime("Duplicate", "saison1/vostfr");
</script>'''


@pytest.fixture
def source(monkeypatch):
    # Reproduce the exact old selectors persisted by an installed extension.
    recipe = SourceRecipe(pkg=PKG, name='Anime-Sama', base_url=BASE,
        search_request_path='/catalogue/', search_query_param='search',
        search_selector='#list_catalog > div a, #list_pagination a:last-child',
        item_title_selector='.card-title, .as-carte-titre, h2, h3, img[alt]',
        runtime={'exclude_urls': ['/scan/'], 'episodes': {'kind': 'js_arrays',
            'array_pattern': r'(?:var|let|const)\s+(eps\w*)\s*=\s*\[([^\]]*)\]',
            'pages_pattern': r'panneauAnime\([^,]+,\s*["\x27]([^"\x27]+)["\x27]\)',
            'script_path': 'episodes.js'}})
    value = AniyomiContainerSource(recipe)
    async def fetch(url, **kwargs):
        if url.startswith(BASE + '/catalogue/?'): return CARDS
        if url == ROOT: return WORK
        if url.rstrip('/') in (ROOT + 'saison2/vostfr', ROOT + 'saison2/vf'): return '<h1>Lecture</h1>'
        if url == ROOT + 'saison2/vostfr/episodes.js':
            return "var eps1 = ['https://video.sibnet.ru/shell.php?videoid=201', 'https://video.sibnet.ru/shell.php?videoid=202'];"
        if url == ROOT + 'saison2/vf/episodes.js':
            return "var eps1 = ['https://video.sibnet.ru/shell.php?videoid=301'];"
        pytest.fail('Unexpected request, including pagination or another season: ' + url)
    value._fetch_html = AsyncMock(side_effect=fetch)
    return value


@pytest.mark.asyncio
async def test_search_expands_real_seasons_and_excludes_badges_scans_pagination_and_comments(source):
    results = await source.search_anime('one piece')
    assert [item.title for item in results] == ['One Piece — Saison 1', 'One Piece — Saison 2', 'One Piece — Films', 'One Piece — Kai - Saga 1 (East Blue)']
    assert results[0].url == ROOT + 'saison1/vostfr'
    assert results[0].version == 'VOSTFR' and results[0].imageUrl == BASE + '/one-piece.jpg'
    assert results[0].episodeInfo.startswith('Saga 1 East Blue')
    assert '#list_pagination' not in source.recipe.search_selector
    # Old recipes upgrade in place and survive export/reimport.
    roundtrip = SourceRecipe.from_dict(json.loads(json.dumps(source.recipe.to_dict())))
    assert roundtrip.runtime['listing_expansion']['kind'] == 'script_sections'
    assert roundtrip.runtime['episodes']['kind'] == 'js_arrays'


@pytest.mark.asyncio
async def test_selected_season_detail_never_loads_the_first_seasons_episodes(source):
    results = await source.search_anime('one piece')
    detail = await source.get_anime_detail(results[1].url)
    assert detail.title == 'One Piece — Saison 2'
    assert detail.synopsis == 'Luffy et son équipage.' and detail.genres == ['Aventure']
    assert [ep.number for ep in detail.episodes] == [1, 2]
    assert 'videoid=201' in detail.episodes[0].playerUrl
    assert detail.version == 'VOSTFR' and all(ep.version == 'VOSTFR' for ep in detail.episodes)
    assert source._fetch_html.call_args_list.count(((ROOT,), {})) == 1
    assert not any('/saison1/' in call.args[0] for call in source._fetch_html.call_args_list)


@pytest.mark.asyncio
async def test_language_variant_stays_in_the_selected_season(source):
    detail = await source.get_anime_detail(ROOT + 'saison2/vf/')
    assert detail.title == 'One Piece — Saison 2' and detail.version == 'VF'
    assert detail.episodes[0].version == 'VF' and 'videoid=301' in detail.episodes[0].playerUrl


@pytest.mark.asyncio
async def test_direct_release_seasons_keep_their_language_without_extra_requests(source):
    from animelab.models.anime import AnimeResult
    direct = AnimeResult(id='vf', title='One Piece', url=ROOT + 'saison2/vf/', version='VF')
    results = await source.data_runtime.expand_listing([direct])
    assert results == [direct]
    source._fetch_html.assert_not_awaited()


@pytest.mark.asyncio
async def test_section_listing_runs_as_a_serializable_recipe_for_an_unrelated_publisher():
    recipe = SourceRecipe(pkg='independent.publisher', base_url='https://independent.example',
        runtime={'listing_expansion': section_listing_plan()})
    instance = AniyomiContainerSource(recipe)
    instance._fetch_html = AsyncMock(return_value=WORK)
    from animelab.models.anime import AnimeResult
    items = [AnimeResult(id='x', title='Work', url='https://independent.example/catalogue/one-piece/')]
    results = await instance.data_runtime.expand_listing(items * 2)
    assert len(results) == 4 and all(item.source == recipe.pkg for item in results)
    assert instance._fetch_html.await_count == 1
    await instance.data_runtime.expand_listing(items)
    assert instance._fetch_html.await_count == 1


@pytest.mark.asyncio
async def test_source_catalogue_and_palette_search_return_the_same_seasons(source, monkeypatch):
    from animelab.services.source_catalogue import SourceCatalogueService
    from animelab.services.extension_service import extension_service
    service = SourceCatalogueService()
    monkeypatch.setattr(extension_service, 'get_container_source_by_id', lambda sid: source)
    monkeypatch.setattr(extension_service, 'get_enabled_container_sources', lambda: [source])
    monkeypatch.setattr(service, 'html', AsyncMock(return_value=(CARDS, BASE + '/catalogue/?search=one+piece')))
    page = await service.browse(PKG, 'search', 'one piece')
    palette = await source.search_anime('one piece')
    assert [item.url for item in page['results']] == [item.url for item in palette]
    assert len(page['results']) == 4 and page['nextCursor'] is None
