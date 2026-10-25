"""A04: same identities and real capabilities across source entry points."""
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from animelab.api_errors import APIProblem
from animelab.models.anime import AnimeResult,AnimeDetail,Episode
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.aniyomi_dex_parser import SourceRecipe
from animelab.services.source_registry import SourceProvider,SourceRegistry
from animelab.services.source_catalogue import SourceCatalogueService
from animelab.routers import anime as router


def provider(sid):
    base=f'https://{sid}.example'
    return SimpleNamespace(base_url=base,name=sid,lang='en',
        search_anime=AsyncMock(return_value=[AnimeResult(id='1',title='Series',url=base+'/series',source='cached')]),
        get_latest_releases=AsyncMock(return_value=[AnimeResult(id='1',title='Series',url=base+'/series')]),
        get_anime_detail=AsyncMock(return_value=AnimeDetail(title='Series',url=base+'/series',episodes=[Episode(number=1,title='One')])) )


@pytest.mark.asyncio
@pytest.mark.parametrize('sid',['french-manga','voir-anime','animepahe','installed.extension'])
async def test_all_source_entry_points_share_the_registry_without_mutating_provider_cache(sid,monkeypatch):
    natives={key:provider(key) for key in ('french-manga','voir-anime','animepahe')}
    extension=provider('installed.extension');extension.pkg='installed.extension'
    extensions=SimpleNamespace(get_enabled_container_sources=lambda:[extension],
        get_container_source_by_id=lambda key:extension if key==extension.pkg else None)
    registry=SourceRegistry(natives,extensions)
    monkeypatch.setattr(router,'source_registry',registry)
    monkeypatch.setattr('animelab.services.source_catalogue.source_registry',registry)
    monkeypatch.setattr(router.library_service,'get_all_favorites',lambda:[])
    monkeypatch.setattr(router.library_service,'get_history',lambda:[])
    registered=registry.get(sid)
    assert isinstance(registered.service,SourceProvider)
    search=await router.search_api('series',sid,True)
    feed=await router.api_source_feed(sid)
    detail=await SourceCatalogueService().provider(sid).get_anime_detail(registered.base_url+'/series')
    home=await router.api_home_feed()
    assert search['results'][0].source==sid
    assert feed['source']==sid and feed['releases'][0].source==sid
    assert detail.source==sid and home['latestReleases'][sid][0]['source']==sid
    assert registered.service.search_anime.return_value[0].source=='cached'


@pytest.mark.asyncio
async def test_unknown_or_disabled_source_never_falls_back_and_capabilities_do_not_invent_popularity():
    generic=AniyomiContainerSource(SourceRecipe(pkg='generic',name='Generic',base_url='https://generic.example',
        search_selector='article',episode_list_selector='.episode',latest_selector='article',supports_latest=False))
    active={'generic':generic}
    extensions=SimpleNamespace(get_enabled_container_sources=lambda:list(active.values()),get_container_source_by_id=active.get)
    registry=SourceRegistry({'french-manga':provider('french-manga')},extensions)
    registered=registry.get('generic')
    assert registered.capabilities.search and registered.capabilities.detail
    assert not registered.capabilities.latest and not registered.capabilities.popular and not registered.capabilities.catalogue
    generic.get_latest_releases=AsyncMock()
    with pytest.raises(APIProblem): await registered.get_latest_releases()
    generic.get_latest_releases.assert_not_called()
    active.clear()
    for sid in ('generic','missing'):
        with pytest.raises(APIProblem) as failure: registry.get(sid)
        assert failure.value.status==404
    assert registry.detect('https://french-manga.example.evil.invalid/series','missing')=='missing'
