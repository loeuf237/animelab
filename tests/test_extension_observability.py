"""A13: reproducible contracts, health causes and bounded immutable revisions."""
import asyncio
import json
from pathlib import Path
from unittest.mock import AsyncMock
import httpx
import pytest
from animelab.database import sqlite_connection
from animelab.services.extension_service import ExtensionService
from animelab.services.extension_observability import extension_observability as health,save_recipe_revision,classify,SelectorMismatch,InvalidSelector
from animelab.services.aniyomi_container import AniyomiContainerSource,_safe_select
from animelab.services.aniyomi_dex_parser import SourceRecipe,RecipeVersionError
from animelab.services.source_registry import SourceRegistry
from animelab.services.source_http import VerificationRequired,SourceNetworkError,RateLimited
from bs4 import BeautifulSoup
from animelab.api_errors import APIProblem

FIXTURES=Path(__file__).parent/'fixtures'/'extensions'


@pytest.fixture
def extension(tmp_path):
    path=tmp_path/'extensions.sqlite'
    service=ExtensionService(str(path))
    recipe=SourceRecipe(**json.loads((FIXTURES/'manifest.json').read_text())['htmlRecipe'])
    with service._get_conn() as conn:
        conn.execute("INSERT INTO extension_repos(id,url,name,is_active) VALUES(1,'https://fixtures.example/index.json','Fixture',1)")
        conn.execute('INSERT INTO imported_extensions(id,repo_id,pkg,name,lang,is_enabled,base_url,recipe_json) VALUES (1,1,?,?,?,1,?,?)',
                     (recipe.pkg,recipe.name,'en',recipe.base_url,json.dumps(recipe.to_dict())))
    service._load_enabled_sources()
    return service,recipe,path


@pytest.mark.asyncio
@pytest.mark.parametrize('case',json.loads((FIXTURES/'manifest.json').read_text())['cases'])
async def test_versioned_html_reference_corpus(case):
    recipe=SourceRecipe.from_dict(json.loads((FIXTURES/'manifest.json').read_text())['htmlRecipe'])
    source=AniyomiContainerSource(recipe)
    source._fetch_html=AsyncMock(return_value=(FIXTURES/case['file']).read_text())
    if case.get('expectedError'):
        with pytest.raises(SelectorMismatch): await source.get_latest_releases()
    else:
        assert len(await source.get_latest_releases())==case['expectedCount']


@pytest.mark.asyncio
async def test_json_reference_corpus():
    manifest=json.loads((FIXTURES/'manifest.json').read_text())
    for case in manifest['jsonCases']:
        source=AniyomiContainerSource(SourceRecipe(pkg='animeextension.de.aniworld',base_url='https://aniworld.example'))
        source._fetch_html=AsyncMock(return_value=(FIXTURES/case['file']).read_text())
        results=await source.search_anime('river')
        assert len(results)==case['expectedCount'] and results[0].title==case['expectedTitle']


@pytest.mark.parametrize('error,status',[
    (VerificationRequired('https://fixtures.example'),'protection'),
    (SourceNetworkError('private','dns','https://fixtures.example'),'network_error'),
    (TimeoutError(),'network_error'),(InvalidSelector('bad selector'),'selector_error'),
    (SelectorMismatch('missing'),'selector_error'),(ValueError('invalid json'),'parse_error'),
    (RecipeVersionError('future'),'unsupported'),
    (APIProblem('source_operation_unsupported'),'unsupported'),
])
def test_protection_network_and_recipe_failures_are_distinct(error,status):
    assert classify(error)[0]==status


@pytest.mark.asyncio
async def test_normal_requests_persist_health_without_hiding_errors(extension):
    service,recipe,path=extension
    source=service.get_container_source_by_id(recipe.pkg)
    provider=SourceRegistry(natives={},extensions=service).describe(recipe.pkg,source)
    source._fetch_html=AsyncMock(return_value=(FIXTURES/'catalogue.html').read_text())
    assert len(await provider.get_latest_releases())==2
    good=service.get_visible_extensions()[0]['health'][0]
    assert good['status']=='healthy' and good['result_count']==2 and good['recipe_revision']>=1
    source._fetch_html.side_effect=VerificationRequired(recipe.base_url)
    with pytest.raises(VerificationRequired): await provider.get_latest_releases()
    bad=service.get_visible_extensions()[0]['health'][0]
    assert bad['status']=='protection' and bad['failure_streak']==1 and bad['success_at']==good['success_at']
    source._fetch_html.side_effect=None;source._fetch_html.return_value=(FIXTURES/'changed.html').read_text()
    with pytest.raises(SelectorMismatch): await provider.get_latest_releases()
    assert service.get_visible_extensions()[0]['health'][0]['status']=='selector_error'
    source._fetch_html.side_effect=asyncio.CancelledError()
    with pytest.raises(asyncio.CancelledError): await provider.get_latest_releases()
    assert service.get_visible_extensions()[0]['health'][0]['status']=='selector_error'


@pytest.mark.asyncio
async def test_recipe_history_deduplicates_and_restore_creates_new_revision(extension,monkeypatch):
    service,recipe,path=extension
    monkeypatch.setattr('animelab.services.extension_service.is_safe_url',lambda url:True)
    history=service.recipe_history(1)['revisions'];assert len(history)>=1
    original=history[0]
    service._load_enabled_sources()
    assert service.recipe_history(1)['revisions']==history
    await service.configure_extension(1,{'latest_selector':'section.new-card'})
    assert service.recipe_history(1)['revisions'][0]['revision']>original['revision']
    await service.restore_recipe(1,original['revision'])
    restored=service.recipe_history(1)['revisions']
    assert len(restored)==len(history)+2 and restored[0]['fingerprint']==original['fingerprint']
    assert next(r for r in restored if r['revision']==original['revision'])==original
    assert service.get_container_source_by_id(recipe.pkg).recipe.latest_selector==recipe.latest_selector
    assert 'recipe_json' not in restored[0]


def test_revision_retention_and_future_schema_visibility(extension):
    service,recipe,path=extension
    with service._get_conn() as conn:
        for n in range(25): save_recipe_revision(conn,1,{**recipe.to_dict(),'latest_selector':f'.card-{n}'},'test')
    assert len(service.recipe_history(1)['revisions'])==20
    with service._get_conn() as conn:
        conn.execute('UPDATE imported_extensions SET recipe_json=? WHERE id=1',(json.dumps({'schema_version':999}),))
    service._load_enabled_sources()
    assert not service.get_enabled_container_sources()
    assert service.get_visible_extensions()[0]['health'][0]['code']=='recipe_schema_unsupported'


def test_invalid_selector_is_not_silently_treated_as_empty():
    with pytest.raises(InvalidSelector): _safe_select(BeautifulSoup('<main/>','html.parser'),'main[')
    assert _safe_select(BeautifulSoup('<main/>','html.parser'),'main[, main')


@pytest.mark.asyncio
async def test_batch_preflight_refuses_broken_recipe_before_queueing(extension,monkeypatch):
    from fastapi import FastAPI
    from animelab.routers.download import router
    from animelab.services.download_manager import download_manager
    service,recipe,path=extension
    monkeypatch.setattr('animelab.services.extension_service.extension_service',service)
    queued=[]
    monkeypatch.setattr(download_manager,'start_batch_download',lambda *a,**kw:queued.append(a))
    app=FastAPI();app.include_router(router)
    source=service.get_container_source_by_id(recipe.pkg)
    source.recipe.latest_selector='main['
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        body={'animeName':'Series','source':recipe.pkg,'episodes':[{'number':1,'url':'https://fixtures.example/1'},{'number':2,'url':'https://fixtures.example/2'}]}
        invalid=await client.post('/api/download/batch',json=body)
        assert invalid.status_code==409 and invalid.json()['code']=='source_recipe_invalid'
        source.recipe.latest_selector='article'
        observed=await client.post('/api/download/batch',json=body)
        assert observed.status_code==409 and not queued
    assert service.get_visible_extensions()[0]['health'][0]['status']=='selector_error'


@pytest.mark.asyncio
async def test_old_request_cannot_validate_a_new_recipe(extension,monkeypatch):
    service,recipe,path=extension
    monkeypatch.setattr('animelab.services.extension_service.is_safe_url',lambda url:True)
    old=service.get_container_source_by_id(recipe.pkg)
    result=asyncio.get_running_loop().create_future()
    async def fetch(*a,**kw): return await result
    old._fetch_html=fetch
    provider=SourceRegistry(natives={},extensions=service).describe(recipe.pkg,old)
    request=asyncio.create_task(provider.get_latest_releases())
    await asyncio.sleep(0)
    await service.configure_extension(1,{'latest_selector':'section.new-card'})
    result.set_result((FIXTURES/'catalogue.html').read_text())
    assert len(await request)==2
    assert not service.get_visible_extensions()[0]['health'],'the old request must not validate the changed recipe'
    current=service.get_container_source_by_id(recipe.pkg)
    current._fetch_html=AsyncMock(return_value=(FIXTURES/'changed.html').read_text())
    await SourceRegistry(natives={},extensions=service).describe(recipe.pkg,current).get_latest_releases()
    observed=service.get_visible_extensions()[0]
    assert observed['health'][0]['recipe_revision']==observed['recipe_revision']
