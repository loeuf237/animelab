"""Catalogue filters and stable pagination use complete upstream data, offline."""
from unittest.mock import AsyncMock
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
import pytest

from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.aniyomi_dex_parser import SourceRecipe, AniyomiDexParser
from animelab.services.source_catalogue import SourceCatalogueService, CatalogueError
from animelab.services.source_registry import SourceRegistry


def catalogue(name):
    recipe = SourceRecipe(pkg=f'eu.kanade.tachiyomi.animeextension.fr.{name}',
                          name=name, base_url=f'https://{name}.example')
    AniyomiDexParser._fill_heuristics(recipe)
    source = AniyomiContainerSource(recipe)
    service = SourceCatalogueService()
    service.provider = lambda sid: SourceRegistry(natives={}).describe(sid, source)
    return service, source, source.data_runtime


def fr_rows(count):
    # Normalized wire fields; matches the upstream FrAnimeDto.kt format/status fields.
    return [{'id':i, 'title':f'Anime {i:03}', 'note':i, 'genres':['Action'],
             'format':'TV', 'status':'EN COURS',
             'seasons':[{'episodes':[{'languages':{'vo':{'players':['sibnet']}}}]}]}
            for i in range(count)]


@pytest.mark.asyncio
async def test_popular_catalogue_retains_every_entry_and_order_across_pages(monkeypatch):
    cat, source, adapter = catalogue('franime')
    monkeypatch.setattr(adapter, 'catalogue', AsyncMock(return_value=fr_rows(125)))
    pages, cursor = [], None
    for _ in range(4):
        page = await cat.browse(source.pkg, 'popular', cursor=cursor)
        pages.append(page)
        cursor = page['nextCursor']
        if not cursor:
            break
    assert [len(p['results']) for p in pages] == [48, 48, 29]
    assert [r.id for p in pages for r in p['results']] == [f'{i}-1-vo' for i in reversed(range(125))]
    assert all(r.genres == ['Action'] for p in pages for r in p['results'])


@pytest.mark.asyncio
async def test_popular_sort_survives_genre_query_and_explicit_order(monkeypatch):
    cat, source, adapter = catalogue('franime')
    rows = fr_rows(100)
    for row in rows[1::2]:
        row['genres'] = ['Romance']
    monkeypatch.setattr(adapter, 'catalogue', AsyncMock(return_value=rows))
    filters = await cat.filters(source.pkg)
    action = next(t['id'] for t in filters['tags'] if t['value'] == 'Action')
    page = await cat.browse(source.pkg, 'popular', 'Anime', [action])
    last = await cat.browse(source.pkg, 'popular', 'Anime', [action], cursor=page['nextCursor'])
    assert [r.id for r in page['results'] + last['results']] == [f'{i}-1-vo' for i in reversed(range(0, 100, 2))]
    # An explicit sort takes precedence over the current view's default.
    latest = await cat.browse(source.pkg, 'latest', order='note')
    assert latest['results'][0].id == '99-1-vo'


@pytest.mark.asyncio
@pytest.mark.parametrize('mode,order,metric', [('feed:views','source','views'), ('feed:likes','source','likes'),
                                             ('catalogue','views','views'), ('latest','likes','likes')])
async def test_hanime_respects_metric_with_filters_and_pagination(monkeypatch, mode, order, metric):
    cat, source, adapter = catalogue('hanime')
    rows = [{'id':i, 'slug':f'anime-{i}', 'name':f'Anime {i}', 'likes':65-i, 'views':i,
             'created_at_unix':i, 'tags':['Action']} for i in range(1, 66)]
    monkeypatch.setattr(source.data_runtime, 'catalogue', AsyncMock(return_value=rows))
    filters = await cat.filters(source.pkg)
    action = next(t['id'] for t in filters['tags'] if t['value'] == 'Action')
    first = await cat.browse(source.pkg, mode, 'Anime', [action], order)
    second = await cat.browse(source.pkg, mode, 'Anime', [action], order, first['nextCursor'])
    expected = sorted(rows, key=lambda row: row[metric], reverse=True)
    assert [r.id for r in first['results'] + second['results']] == [str(row['id']) for row in expected]


@pytest.mark.asyncio
async def test_imported_voiranime_filters_keep_query_defaults(monkeypatch):
    cat, source, _ = catalogue('voiranime')
    fetch = AsyncMock(side_effect=lambda service, url, *args: ('<div></div>', url))
    monkeypatch.setattr(cat, 'html', fetch)
    filters = await cat.filters(source.pkg)
    genres = [t['id'] for t in filters['tags'][:2]]
    await cat.browse(source.pkg, 'search', 'Naruto & Boruto', genres, 'rating')
    url = fetch.call_args.args[1]
    params = parse_qs(urlparse(url).query, keep_blank_values=True)
    assert params == {'s':['Naruto & Boruto'], 'post_type':['wp-manga'], 'genre[]':['action','adventure'],
                      'op':['AND'], 'm_orderby':['rating']}
    assert '{' not in url


@pytest.mark.asyncio
async def test_filtered_custom_feed_keeps_its_default_type(monkeypatch):
    cat, source, _ = catalogue('animesama')
    fetch = AsyncMock(side_effect=lambda service, url, *args: ('<div></div>', url))
    monkeypatch.setattr(cat, 'html', fetch)
    filters = await cat.filters(source.pkg)
    action = next(t['id'] for t in filters['tags'] if t['group'] == 'Genres' and t['value'] == 'Action')
    await cat.browse(source.pkg, 'feed:films', tags=[action])
    params = parse_qs(urlparse(fetch.call_args.args[1]).query)
    assert params['type[]'] == ['Film'] and params['genre[]'] == ['Action']


@pytest.mark.asyncio
async def test_franime_filters_use_format_status_language_and_genres_together(monkeypatch):
    cat, source, adapter = catalogue('franime')
    rows = fr_rows(3)
    rows[1].update(format='MOVIE', status='TERMINÉ')
    rows[2].update(format='OVA', status='TERMINÉ')
    rows[1]['seasons'][0]['episodes'][0]['languages']['vf'] = {'players':['sendvid']}
    monkeypatch.setattr(adapter, 'catalogue', AsyncMock(return_value=rows))
    filters = await cat.filters(source.pkg)
    def tag(group, value):
        return next(t['id'] for t in filters['tags'] if t['group'] == group and t['value'] == value)
    page = await cat.browse(source.pkg, 'catalogue', tags=[tag('Format','FILM'), tag('Statut','TERMINÉ'),
                                                         tag('Langue','VF'), tag('Genres','Action')])
    assert [r.id for r in page['results']] == ['1-1-vf']
    page = await cat.browse(source.pkg, 'catalogue', tags=[tag('Format','TV'), tag('Statut','TERMINÉ')])
    assert not page['results']


@pytest.mark.asyncio
async def test_franime_previous_seasons_are_completed(monkeypatch):
    cat, source, adapter = catalogue('franime')
    rows = fr_rows(1)
    rows[0]['seasons'] = rows[0]['seasons'] * 2
    monkeypatch.setattr(adapter, 'catalogue', AsyncMock(return_value=rows))
    filters = await cat.filters(source.pkg)
    completed = next(t['id'] for t in filters['tags'] if t['group'] == 'Statut' and t['value'] == 'TERMINÉ')
    result = await cat.browse(source.pkg, 'catalogue', tags=[completed])
    assert [r.id for r in result['results']] == ['0-1-vo']


@pytest.mark.asyncio
async def test_single_groups_are_exposed_and_conflicting_values_rejected(monkeypatch):
    cat, source, adapter = catalogue('franime')
    monkeypatch.setattr(adapter, 'catalogue', AsyncMock(return_value=fr_rows(2)))
    filters = await cat.filters(source.pkg)
    assert next(g for g in filters['groups'] if g['name'] == 'Langue')['single']
    languages = [t['id'] for t in filters['tags'] if t['group'] == 'Langue']
    with pytest.raises(CatalogueError, match='une seule option'):
        await cat.browse(source.pkg, 'catalogue', tags=languages)
    from run import app
    monkeypatch.setattr('animelab.routers.sources.source_catalogue', cat)
    client = TestClient(app)
    response = client.get(f'/api/sources/{source.pkg}/filters')
    assert response.status_code == 200
    assert next(g for g in response.json()['groups'] if g['name'] == 'Langue') == {
        'name':'Langue', 'param':'lang', 'single':True}
    assert client.get(f'/api/sources/{source.pkg}/catalogue', params=[('mode','catalogue'),
        *[('tags', value) for value in languages]]).status_code == 400
