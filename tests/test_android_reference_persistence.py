"""Native URLs and callback data must survive a Python/Android process restart."""
import copy
from unittest.mock import AsyncMock

import pytest

from animelab.services import android_extensions as native
from animelab.services.extension_service import ExtensionService
from animelab.services.extension_references import NativeReferences
from animelab.api_errors import APIProblem


@pytest.fixture
def restarted(tmp_path,monkeypatch):
    package={'pkg':'fixture.references','name':'References','version':'17.1','versionCode':'1','signer':'a'*64,
             'trusted':True,'compatible':True,'state':'loaded','sources':[
                 {'id':'1152921504606846977','name':'References','lang':'fr','baseUrl':'https://fixture.example','supportsLatest':True}]}
    monkeypatch.setattr(native,'_bridge',object())
    monkeypatch.setattr(native,'discover',lambda:copy.deepcopy([package]))
    path=str(tmp_path/'references.sqlite')
    def open_source():
        service=ExtensionService(path)
        service.sync_android_extensions()
        return service,service.get_enabled_container_sources()[0]
    return path,open_source


@pytest.mark.asyncio
@pytest.mark.parametrize('raw_url',['/anime/one#season','https://api.fixture.example/item?id=one'])
async def test_library_reference_keeps_the_original_url_and_callback_data_after_restart(restarted,raw_url):
    _,open_source=restarted
    _,first=open_source()
    card=first._result({'url':raw_url,'title':'One','memo':{'cursor':'native-state'}})
    _,fresh=open_source()
    fresh.call=AsyncMock(return_value={'anime':{'url':raw_url,'title':'One'},'episodes':[]})
    await fresh.get_anime_detail(card.url)
    request=fresh.call.call_args.args[1]
    assert request['url']==raw_url and request['memo']=={'cursor':'native-state'}


@pytest.mark.asyncio
async def test_episode_callback_data_survives_without_loading_its_anime_again(restarted):
    _,open_source=restarted
    _,first=open_source()
    first.call=AsyncMock(return_value={'anime':{'url':'/anime/one','title':'One'},'episodes':[
        {'url':'/episode/1?track=fr','name':'Episode 1','memo':{'ticket':'native-episode'}}]})
    detail=await first.get_anime_detail('https://fixture.example/anime/one')
    _,fresh=open_source()
    fresh.call=AsyncMock(return_value=[])
    await fresh.get_episode_sources(detail.episodes[0].playerUrl)
    request=fresh.call.call_args.args[1]
    assert request['url']=='/episode/1?track=fr' and request['memo']=={'ticket':'native-episode'}


@pytest.mark.asyncio
async def test_private_callback_data_is_not_exposed_in_detail_or_public_catalogue(restarted):
    _,open_source=restarted
    _,source=open_source()
    anime={'url':'/one','title':'One','memo':{'ticket':'private-anime'}}
    source.call=AsyncMock(return_value={'results':[anime],'hasNextPage':False})
    public=await source.public_call('search',{'query':'One'})
    assert 'memo' not in public['results'][0]
    source.call.return_value={'anime':anime,'episodes':[
        {'url':'/episode','name':'1','memo':{'ticket':'private-episode'},'internalData':'private-internal'}]}
    detail=await source.get_anime_detail('https://fixture.example/one')
    assert source.call.call_args.args[1]['memo']=={'ticket':'private-anime'}
    assert 'private-' not in detail.model_dump_json()
    _,fresh=open_source()
    fresh.call=AsyncMock(return_value=[])
    await fresh.get_episode_sources(detail.episodes[0].playerUrl)
    assert fresh.call.call_args.args[1]['memo']=={'ticket':'private-episode'}


@pytest.mark.asyncio
async def test_related_and_seasons_preserve_private_native_references(restarted):
    _,open_source=restarted
    _,source=open_source()
    source._result({'url':'/root','title':'Root','memo':{'ticket':'root'}})
    source.call=AsyncMock(return_value={'anime':{'url':'/root','title':'Root'},
                                      'seasons':[{'url':'/season','title':'Season','memo':{'ticket':'season'}}]})
    result=await source.public_call('seasons',{'anime':{'url':'https://fixture.example/root'}})
    assert source.call.call_args.args[1]['anime']['memo']=={'ticket':'root'}
    assert 'memo' not in result['seasons'][0]
    _,fresh=open_source()
    fresh.call=AsyncMock(return_value=[{'name':'Sequel','animes':[
        {'url':'/related','title':'Related','memo':{'ticket':'related'}}]}])
    result=await fresh.public_call('related',{'url':'https://fixture.example/season'})
    assert fresh.call.call_args.args[1]['anime']['memo']=={'ticket':'season'}
    assert 'memo' not in result[0]['animes'][0]
    assert fresh._references.get('anime','https://fixture.example/related')['memo']=={'ticket':'related'}


def test_empty_relative_native_url_round_trips_but_empty_public_key_is_rejected(restarted):
    path,open_source=restarted
    open_source()
    store=NativeReferences(path,'aniyomi:empty')
    store.remember('anime','https://fixture.example/',{'url':'','title':'Root'})
    assert store.get('anime','https://fixture.example/')['url']==''
    with pytest.raises(APIProblem):
        store.remember('anime','',{'url':'/bad'})


def test_native_reference_namespaces_do_not_mix_sources_or_anime_and_episode(restarted):
    path,open_source=restarted
    open_source()
    one=NativeReferences(path,'aniyomi:one')
    two=NativeReferences(path,'aniyomi:two')
    url='https://fixture.example/shared'
    one.remember('anime',url,{'url':'/one','memo':{'context':'one-anime'}})
    one.remember('episode',url,{'url':'/one-episode','memo':{'context':'one-episode'}})
    two.remember('anime',url,{'url':'/two','memo':{'context':'two-anime'}})
    assert one.get('anime',url)['memo']['context']=='one-anime'
    assert one.get('episode',url)['memo']['context']=='one-episode'
    assert two.get('anime',url)['memo']['context']=='two-anime'


@pytest.mark.parametrize('limits',[{'max_rows':1},{'max_bytes':150}])
def test_reference_quota_failure_rolls_back_the_entire_batch_without_eviction(restarted,limits):
    path,open_source=restarted
    open_source()
    store=NativeReferences(path,'aniyomi:quota',**limits)
    first='https://fixture.example/first'
    second='https://fixture.example/second'
    original={'url':'/first','memo':{'value':'original'}}
    store.remember('anime',first,original)
    with pytest.raises(APIProblem) as failure:
        store.remember_many([('anime',first,{'url':'/first','memo':{'value':'changed'}}),
                             ('anime',second,{'url':'/second','memo':{'value':'x'*200}})])
    assert failure.value.problem.code=='extension_reference_budget'
    assert store.get('anime',first)==original and store.get('anime',second) is None
    # Failed updates must not consume the remaining budget permanently.
    store.remember('anime',first,{'url':'/first'})
    assert store.get('anime',first)=={'url':'/first'}


@pytest.mark.asyncio
async def test_external_uninstall_and_reinstall_preserve_private_reference_and_library_rows(restarted,monkeypatch):
    _,open_source=restarted
    service,source=open_source()
    card=source._result({'url':'/retained','title':'Retained','memo':{'ticket':'kept'}})
    with service._get_conn() as conn:
        conn.execute('INSERT INTO favorites(url,title,source) VALUES (?,?,?)',(card.url,card.title,source.source_id))
    discover=native.discover
    monkeypatch.setattr(native,'discover',lambda:[])
    service.sync_android_extensions()
    assert service.get_enabled_container_sources()==[]
    monkeypatch.setattr(native,'discover',discover)
    _,fresh=open_source()
    fresh.call=AsyncMock(return_value={'anime':{'url':'/retained','title':'Retained'},'episodes':[]})
    await fresh.get_anime_detail(card.url)
    assert fresh.call.call_args.args[1]['memo']=={'ticket':'kept'}
    with service._get_conn() as conn:
        assert conn.execute('SELECT title,source FROM favorites WHERE url=?',(card.url,)).fetchone()[:]==('Retained',source.source_id)


def test_metadata_backup_excludes_private_callback_data(restarted):
    from animelab.services.extension_backup import snapshot
    import json
    _,open_source=restarted
    service,source=open_source()
    source._result({'url':'/private-callback','title':'One','memo':{'ticket':'must-not-export-native-state'}})
    assert 'must-not-export-native-state' not in json.dumps(snapshot(service))


def test_utf16_budget_keeps_valid_non_ascii_data_and_rejects_oversized_native_requests(restarted):
    path,open_source=restarted
    open_source()
    store=NativeReferences(path,'aniyomi:unicode')
    valid={'url':'/日本語','memo':{'text':'語'*80_000}}
    store.remember('anime','https://fixture.example/unicode',valid)
    assert store.get('anime','https://fixture.example/unicode')==valid
    with pytest.raises(APIProblem) as failure:
        store.remember('anime','https://fixture.example/too-large',{'url':'/large','memo':{'text':'x'*250_000}})
    assert failure.value.status==413 and store.get('anime','https://fixture.example/too-large') is None


def test_reinstallation_does_not_reactivate_an_explicitly_disabled_extension(restarted,monkeypatch):
    _,open_source=restarted
    service,_=open_source()
    with service._get_conn() as conn:
        conn.execute('UPDATE imported_extensions SET is_enabled=0')
    discover=native.discover
    monkeypatch.setattr(native,'discover',lambda:[])
    service.sync_android_extensions()
    monkeypatch.setattr(native,'discover',discover)
    service.sync_android_extensions()
    assert service.get_enabled_container_sources()==[]
    assert service.get_visible_extensions()[0]['is_enabled'] is False
