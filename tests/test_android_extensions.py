"""Python/native boundary contracts; actual APK execution is tested on Android."""
import copy
import json
from unittest.mock import AsyncMock

import pytest

from animelab.services import android_extensions as native
from animelab.services.extension_service import ExtensionService
from animelab.services.source_http import VerificationRequired


def package(pkg='fixture.one', source='1152921504606846977'):
    return {'pkg':pkg,'name':'Fixture','version':'17.1','versionCode':'1','signer':'a'*64,
            'trusted':True,'state':'loaded','compatible':True,
            'sources':[{'id':source,'name':'Français','lang':'fr','baseUrl':'https://fixture.example','supportsLatest':True}]}


@pytest.fixture
def host(tmp_path,monkeypatch):
    monkeypatch.setattr(native,'_bridge',None)
    service=ExtensionService(str(tmp_path/'extensions.sqlite'))
    monkeypatch.setattr(native,'_bridge',object())
    packages=[]
    monkeypatch.setattr(native,'discover',lambda:copy.deepcopy(packages))
    return service,packages


def test_native_discovery_retains_ids_and_source_instance_metadata(host):
    service,packages=host
    first=package()
    first['sources'].append({**first['sources'][0],'id':'1152921504606846978','lang':'en'})
    packages.append(first)
    service.sync_android_extensions()
    sources=service.get_enabled_container_sources()
    assert len(sources)==2
    assert {s.source_id for s in sources}=={'aniyomi:1152921504606846977','aniyomi:1152921504606846978'}
    assert service.get_container_source_by_id('fixture.one') is None
    from animelab.services.source_registry import SourceRegistry
    assert {entry.id for entry in SourceRegistry(natives={},extensions=service).all()}=={source.source_id for source in sources}
    from animelab.services.source_settings_service import SourceSettingsService
    settings=SourceSettingsService(service.db_path).get_all_sources_with_settings()
    assert {s['id'] for s in settings if s['type']=='imported'}=={source.source_id for source in sources}
    source=sources[0]
    service.set_source_alias('fixture.one',source.source_id)
    assert service.get_container_source_by_id('fixture.one') is source
    assert SourceRegistry(natives={},extensions=service).get('fixture.one').id==source.source_id
    source._episodes['https://fixture.example/episode']={'memo':{'cursor':'native'}}
    service.sync_android_extensions()
    assert service.get_container_source_by_id(source.source_id) is source
    assert source._episodes['https://fixture.example/episode']['memo']['cursor']=='native'
    service.set_source_state(source.source_id,{'enabled':False})
    assert len(service.get_enabled_container_sources())==1


def test_external_uninstall_retains_stub_without_claiming_installation(host):
    service,packages=host
    packages.append(package())
    service.sync_android_extensions()
    assert service.get_visible_extensions()[0]['is_installed']
    packages.clear()
    service.sync_android_extensions()
    assert not service.get_enabled_container_sources()
    with service._get_conn() as conn:
        row=conn.execute('SELECT installed_code,is_enabled,catalog_state FROM imported_extensions').fetchone()
        assert tuple(row)==(None,0,'missing')
    assert service.retained_source_descriptors()[0]['source_key']=='aniyomi:1152921504606846977'


def test_no_recipe_is_counted_as_installed_apk(host):
    service,_=host
    with service._get_conn() as conn:
        conn.execute("INSERT INTO extension_repos(url,name) VALUES ('https://repo.example','Repo')")
        conn.execute("INSERT INTO imported_extensions(repo_id,pkg,name,lang,version,installed_version,is_enabled,recipe_json) VALUES (1,'fixture.one','Fixture','fr','1','1',1,'{}')")
    row=service.get_visible_extensions()[0]
    assert row['is_installed'] is False and row['is_enabled'] is False and row['installed_version'] is None


def test_collision_does_not_replace_another_package_or_publish_partial_map(host):
    service,packages=host
    packages.append(package())
    service.sync_android_extensions()
    original=service.get_enabled_container_sources()[0]
    packages.append(package(pkg='fixture.two'))
    with pytest.raises(ValueError,match='Collision'):
        service.sync_android_extensions()
    assert service.get_enabled_container_sources()==[original]
    with service._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM extension_sources').fetchone()[0]==1


@pytest.mark.asyncio
async def test_installer_pending_does_not_mean_installed(host,monkeypatch,tmp_path):
    service,_=host
    with service._get_conn() as conn:
        conn.execute("INSERT INTO extension_repos(url,name) VALUES ('https://repo.example','Repo')")
        conn.execute("INSERT INTO imported_extensions(repo_id,pkg,name,lang,apk_url) VALUES (1,'fixture.one','Fixture','fr','https://repo.example/a.apk')")
    expected={'success':True,'pending':True,'is_installed':False,'operation':{'state':'waiting_user'}}
    installer=AsyncMock(return_value=expected)
    monkeypatch.setattr(service,'install_android_extension',installer)
    assert await service.toggle_extension(1,True)==expected
    assert service.get_visible_extensions()[0]['is_installed'] is False


@pytest.mark.asyncio
async def test_native_call_cancellation_reaches_worker(monkeypatch):
    import asyncio
    import threading
    entered=threading.Event()
    release=threading.Event()
    class Bridge:
        def invoke(self,raw):
            self.operation=json.loads(raw)['operationId']; entered.set(); release.wait(2)
            return '{"ok":true,"result":{}}'
        def cancel(self,operation):
            assert operation==self.operation
            release.set()
    bridge=Bridge()
    monkeypatch.setattr(native,'_bridge',bridge)
    task=asyncio.create_task(native.invoke('fixture.one','search','123'))
    await asyncio.to_thread(entered.wait,2)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert release.is_set()


def test_native_network_verification_is_not_hidden():
    with pytest.raises(VerificationRequired) as error:
        native.unpack('{"ok":false,"code":"verification_required","url":"https://fixture.example/check"}')
    assert error.value.domain=='fixture.example'


def test_native_default_user_agent_matches_the_verification_session():
    import android_runtime
    from animelab.services.source_http import USER_AGENT
    assert json.loads(android_runtime.extension_http('{"action":"user_agent"}'))=={'userAgent':USER_AGENT}


@pytest.mark.asyncio
async def test_catalogue_and_episode_memos_survive_callbacks(monkeypatch):
    source=native.AndroidAPKSource(package(),package()['sources'][0])
    source._result({'url':'/anime','title':'Fixture','memo':{'ticket':'x'}})
    call=AsyncMock(return_value={'anime':{'url':'/anime','title':'Fixture'},'episodes':[
        {'url':'/ep','name':'1.5','episode_number':1.5,'memo':{'ticket':'y'}}]})
    monkeypatch.setattr(source,'call',call)
    detail=await source.get_anime_detail('https://fixture.example/anime')
    assert call.call_args.args[1]['memo']=={'ticket':'x'}
    assert detail.episodes[0].nativeMetadata['episode_number']==1.5
    call.return_value=[{'hosterName':'Fixture','videoList':[]}]
    await source.get_episode_sources('https://fixture.example/ep')
    assert call.call_args.args[1]['memo']=={'ticket':'y'}


@pytest.mark.asyncio
async def test_bulk_update_reports_partial_failure(host,monkeypatch):
    service,_=host
    monkeypatch.setattr(service,'get_visible_extensions',lambda:[{'id':1,'has_update':True},{'id':2,'has_update':True}])
    update=AsyncMock(side_effect=[ValueError('secret URL must not appear in result'),{'success':True,'pending':True}])
    monkeypatch.setattr(service,'update_extension',update)
    result=await service.update_all_extensions()
    assert result['pending_ids']==[2] and result['failed']==[{'id':1,'code':'extension_update_failed'}]
    assert result['success'] is False
