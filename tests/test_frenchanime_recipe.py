"""French Anime must never execute the similarly named Hanime API recipe."""
import json
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

from animan.services.aniyomi_container import AniyomiContainerSource, _safe_select
from animan.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animan.services.extension_service import ExtensionService
from animan.services.recipe_plans import source_key
from animan.services.source_catalogue import SourceCatalogueService
from animan.services.source_registry import SourceRegistry

PKG = 'eu.kanade.tachiyomi.animeextension.fr.frenchanime'
BASE = 'https://french-anime.com'


@pytest.mark.parametrize('pkg,host,expected', [
    (PKG, BASE, 'frenchanime'),
    ('eu.kanade.tachiyomi.animeextension.fr.franime', 'https://franime.fr', 'franime'),
    ('eu.kanade.tachiyomi.animeextension.all.hanime', 'https://hanime.tv', 'hanime'),
    ('unknown.frenchanimeclone', 'https://hanime.tv', 'frenchanimeclone'),
    ('', 'https://hanime.tv.attacker.example', ''),
    ('', 'https://www.french-anime.com', 'frenchanime'),
])
def test_source_identity_uses_complete_identifier(pkg, host, expected):
    assert source_key(pkg, host) == expected


def test_imported_french_anime_recipe_never_becomes_hanime(extension_apk):
    recipe = AniyomiDexParser.parse_apk(extension_apk(BASE), pkg_name=PKG, default_base_url=BASE, strict=True)
    assert recipe.base_url == BASE
    assert recipe.multisrc_theme == 'datalifeengine'
    assert 'api:hanime' not in json.dumps(recipe.to_dict())
    assert recipe.popular_request_path == '/animes-vostfr/page/1/'
    assert recipe.episode_list_selector == 'div.eps'


@pytest.mark.asyncio
async def test_french_anime_browse_filters_episodes_and_all_players_use_own_site():
    recipe = SourceRecipe(pkg=PKG, base_url=BASE)
    AniyomiDexParser._fill_heuristics(recipe)
    source = AniyomiContainerSource(SourceRecipe.from_dict(json.loads(json.dumps(recipe.to_dict()))))
    async def fetch(url, **kwargs):
        assert url.startswith(BASE)
        if '/show.html' in url:
            return '<h1>Example VF</h1><div class="eps">2!https://sendvid.com/two 1!https://video.sibnet.ru/shell.php?videoid=1,https://sendvid.com/one</div>'
        return '''<a href="/genre/action/">Action</a><a href="https://another.example/genre/adult/">External advertisement</a>
        <div id="dle-content"><div class="mov"><a href="/show.html"><img src="/poster.jpg" alt="Example">Example</a></div></div>'''
    source._fetch_html = AsyncMock(side_effect=fetch)
    catalogue = SourceCatalogueService()
    catalogue.provider = lambda sid: SourceRegistry(natives={}).describe(sid, source)
    async def html(service, url, method='GET', data=None):
        return await fetch(url, method=method, data=data), url
    catalogue.html = html
    filters = await catalogue.filters(PKG)
    assert [t['label'] for t in filters['tags']] == ['Action']
    result = await catalogue.browse(PKG, 'popular')
    assert len(result['results']) == 1 and result['results'][0].url == BASE + '/show.html'
    detail = await source.get_anime_detail(result['results'][0].url)
    assert [e.number for e in detail.episodes] == [1, 2]
    assert all(e.version == 'VF' for e in detail.episodes)
    streams = await source.get_episode_sources(detail.episodes[0].playerUrl)
    assert {s['url'] for s in streams} == {'https://video.sibnet.ru/shell.php?videoid=1', 'https://sendvid.com/one'}


def test_polluted_stored_recipe_is_repaired_and_original_revision_preserved(tmp_path):
    service = ExtensionService(str(tmp_path / 'library.sqlite'))
    polluted = SourceRecipe(pkg=PKG, name='French Anime', base_url='https://hanime.tv',
        popular_selector='api:hanime', search_selector='api:hanime', latest_selector='api:hanime',
        filter_tags={'Wrong catalogue': 'wrong-catalogue'})
    custom = SourceRecipe(pkg='custom.source', name='Custom', base_url='https://custom.example', search_selector='.my-cards')
    with service._get_conn() as conn:
        repo = conn.execute("INSERT INTO extension_repos(url,name,is_active) VALUES ('https://repo.example','Test',1)").lastrowid
        for recipe in (polluted, custom):
            conn.execute('INSERT INTO imported_extensions(repo_id,pkg,name,lang,version,base_url,recipe_json,is_enabled) VALUES (?,?,?,\'fr\',\'1\',?,?,1)',
                (repo, recipe.pkg, recipe.name, recipe.base_url, json.dumps(recipe.to_dict())))
    service._load_enabled_sources()
    assert service._active_container_sources[PKG].base_url == BASE
    assert service._active_container_sources['custom.source'].recipe.search_selector == '.my-cards'
    with service._get_conn() as conn:
        row = conn.execute('SELECT * FROM imported_extensions WHERE pkg=?', (PKG,)).fetchone()
        assert row['base_url'] == BASE
        assert 'api:hanime' not in row['recipe_json']
        assert 'wrong-catalogue' not in row['recipe_json']
        previous = conn.execute("SELECT recipe_json FROM extension_recipe_versions WHERE ext_id=? AND reason='before_identity_repair'", (row['id'],)).fetchone()
        assert json.loads(previous[0])['popular_selector'] == 'api:hanime'
    # Loading twice should keep the repaired state, without adding repair revisions.
    service._load_enabled_sources()
    assert service._active_container_sources[PKG].recipe.popular_selector == 'div#dle-content > div.mov'


def test_unknown_api_operation_is_reported_as_unsupported():
    from bs4 import BeautifulSoup
    with pytest.raises(NotImplementedError):
        _safe_select(BeautifulSoup('<html/>', 'html.parser'), 'api:unknown')


def test_no_runtime_dependency_on_removed_adapter_directory():
    root = Path(__file__).resolve().parents[1] / 'animan/services'
    assert not (root / 'container_adapters').exists()
    for path in root.rglob('*.py'):
        assert 'from animan.services.container_adapters' not in path.read_text()
