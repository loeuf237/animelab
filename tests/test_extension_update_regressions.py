"""Updates keep working recipes intact until the requested APK has been validated."""
import json
from unittest.mock import AsyncMock

import httpx
import pytest

from animelab.services.aniyomi_dex_parser import SourceRecipe, AniyomiDexParser
from animelab.services.extension_service import ExtensionService


@pytest.fixture
def installed(tmp_path, monkeypatch):
    cache = tmp_path / 'apks'
    cache.mkdir()
    monkeypatch.setattr('animelab.services.extension_service.APKS_DIR', cache)
    monkeypatch.setattr('animelab.services.extension_service.is_safe_url', lambda url: True)
    service = ExtensionService(str(tmp_path / 'library.sqlite'))
    recipe = SourceRecipe(pkg='review.source', name='Review', base_url='https://source.example',
                          search_selector='.old-card', popular_selector='.old-card', popular_request_path='/popular')
    with service._get_conn() as conn:
        repo = conn.execute("INSERT INTO extension_repos(url,name,is_active) VALUES ('https://repo.example/index.json','Review',1)").lastrowid
        ext_id = conn.execute('''INSERT INTO imported_extensions
            (repo_id,pkg,name,lang,version,installed_version,available_version,apk_url,available_apk_url,
             base_url,recipe_json,is_enabled,has_update)
            VALUES (?,?,'Review','fr','1','1','2','https://repo.example/v1.apk',
                    'https://repo.example/v2.apk',?,?,1,1)''',
            (repo, recipe.pkg, recipe.base_url, json.dumps(recipe.to_dict()))).lastrowid
    service._load_enabled_sources()
    return service, ext_id, cache


def row_for(service, ext_id):
    with service._get_conn() as conn:
        return dict(conn.execute('SELECT * FROM imported_extensions WHERE id=?', (ext_id,)).fetchone())


@pytest.mark.asyncio
@pytest.mark.parametrize('failure', ['http500', 'network', 'invalid_apk', 'invalid_dex', 'broken_dex_tables', 'missing_url', 'challenge'])
async def test_failed_upgrade_keeps_version_recipe_history_and_active_source(installed, monkeypatch, failure):
    from animelab.services.source_http import VerificationRequired
    service, ext_id, cache = installed
    if failure == 'missing_url':
        with service._get_conn() as conn:
            conn.execute("UPDATE imported_extensions SET apk_url='',available_apk_url='' WHERE id=?", (ext_id,))
    before = row_for(service, ext_id)
    active = service._active_container_sources['review.source']
    with service._get_conn() as conn:
        history = conn.execute('SELECT count(*) FROM extension_recipe_versions WHERE ext_id=?', (ext_id,)).fetchone()[0]
    request = httpx.Request('GET', 'https://repo.example/v2.apk')
    if failure == 'network':
        get = AsyncMock(side_effect=httpx.ConnectError('offline'))
    elif failure == 'challenge':
        get = AsyncMock(side_effect=VerificationRequired(str(request.url)))
    else:
        content = b'not an apk'
        if failure in ('invalid_dex', 'broken_dex_tables'):
            import io, zipfile, struct
            buffer = io.BytesIO()
            with zipfile.ZipFile(buffer, 'w') as archive:
                dex = bytearray(b'dex\n035\0' + bytes(104))
                struct.pack_into('<II', dex, 0x38, 1, 0xFFFFFFFF)
                archive.writestr('classes.dex', dex if failure == 'broken_dex_tables' else b'not dex')
            content = buffer.getvalue()
        get = AsyncMock(return_value=httpx.Response(500 if failure == 'http500' else 200,
                                                  content=content, request=request))
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', get)
    with pytest.raises(VerificationRequired if failure == 'challenge' else ValueError):
        await service.update_extension(ext_id)
    after = row_for(service, ext_id)
    assert after == before
    assert service._active_container_sources['review.source'] is active
    assert not list(cache.iterdir())
    with service._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM extension_recipe_versions WHERE ext_id=?', (ext_id,)).fetchone()[0] == history


@pytest.mark.asyncio
async def test_upgrade_does_not_fall_back_to_an_older_cached_apk(installed, monkeypatch, extension_apk):
    service, ext_id, cache = installed
    before = row_for(service, ext_id)
    old_bytes = extension_apk(selector='.old-card')
    service._apk_cache_path(before).write_bytes(old_bytes)
    (cache / 'review.source.apk').write_bytes(old_bytes)
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', AsyncMock(side_effect=httpx.ConnectError('offline')))
    with pytest.raises(ValueError):
        await service.update_extension(ext_id)
    assert row_for(service, ext_id) == before


@pytest.mark.asyncio
async def test_compile_ignores_unversioned_and_other_version_cache(installed, monkeypatch, extension_apk):
    service, ext_id, cache = installed
    original = row_for(service, ext_id)
    old_bytes = extension_apk(selector='.old-card')
    service._apk_cache_path(original).write_bytes(old_bytes)
    (cache / 'review.source.apk').write_bytes(old_bytes)
    target = service._available_target(original)
    new_bytes = extension_apk(selector='.new-card')
    get = AsyncMock(return_value=httpx.Response(200, content=new_bytes,
                    request=httpx.Request('GET', target['apk_url'])))
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', get)
    recipe = await service._compile_extension_recipe(target)
    assert recipe['popular_selector'] == '.new-card'
    assert get.await_count == 1
    assert service._apk_cache_path(target).read_bytes() == new_bytes
    get.reset_mock()
    assert (await service._compile_extension_recipe(target))['popular_selector'] == '.new-card'
    get.assert_not_awaited()
    assert service._apk_cache_path(original).read_bytes() == old_bytes


@pytest.mark.asyncio
async def test_update_persists_new_domain_only_after_success_and_restart(installed, monkeypatch, extension_apk):
    service, ext_id, cache = installed
    remote = [{'pkg':'review.source', 'version':'2', 'apk':'v2.apk',
               'sources':[{'baseUrl':'https://newsource.example'}]}]
    async def get(client, url, **kwargs):
        return httpx.Response(200, request=httpx.Request('GET', url), **(
            {'json':remote} if url.endswith('.json') else {'content':extension_apk('https://newsource.example')}))
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', get)
    await service.check_updates()
    pending = row_for(service, ext_id)
    assert pending['installed_version'] == '1' and pending['base_url'] == 'https://source.example'
    assert pending['available_base_url'] == 'https://newsource.example'
    # The pending domain survives a process restart.
    service = ExtensionService(service.db_path)
    result = await service.update_extension(ext_id)
    updated = row_for(service, ext_id)
    assert result['success'] and updated['installed_version'] == '2' and not updated['has_update']
    assert updated['base_url'] == 'https://newsource.example'
    restarted = ExtensionService(service.db_path)
    assert restarted._active_container_sources['review.source'].base_url == 'https://newsource.example'
    assert restarted._active_container_sources['review.source'].recipe.popular_selector == '.new-card'


@pytest.mark.asyncio
@pytest.mark.parametrize('name', ['franime', 'hanime'])
async def test_api_markers_can_be_configured_but_invalid_css_is_rejected(installed, monkeypatch, name):
    service, ext_id, _ = installed
    recipe = SourceRecipe(pkg=f'eu.kanade.tachiyomi.animeextension.fr.{name}',
                          name=name, base_url=f'https://{name}.example')
    AniyomiDexParser._fill_heuristics(recipe)
    with service._get_conn() as conn:
        conn.execute('UPDATE imported_extensions SET pkg=?,base_url=?,recipe_json=? WHERE id=?',
                     (recipe.pkg, recipe.base_url, json.dumps(recipe.to_dict()), ext_id))
    assert (await service.configure_extension(ext_id, recipe.to_dict()))['success']
    with pytest.raises(ValueError, match='Sélecteur invalide'):
        await service.configure_extension(ext_id, {'search_selector': 'api:unknown'})
    with pytest.raises(ValueError, match='Sélecteur invalide'):
        await service.configure_extension(ext_id, {'item_title_selector': '['})


def test_pending_domain_migration_keeps_version_8_installations(tmp_path):
    from animelab.database import create_database_engine
    from animelab.migrations import migrate, MIGRATIONS
    engine = create_database_engine('sqlite:///' + str(tmp_path / 'version8.sqlite'))
    try:
        migrate(engine, MIGRATIONS[:8])
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO extension_repos(id,url,name,is_active) VALUES (1,'https://repo.example/index.json','Review',1)")
            conn.exec_driver_sql("""INSERT INTO imported_extensions
                (repo_id,pkg,name,lang,version,installed_version,available_version,base_url,recipe_json,is_enabled,has_update)
                VALUES (1,'review.source','Review','fr','1','1','2','https://old.example','{}',1,1)""")
        migrate(engine)
        migrate(engine)
        with engine.connect() as conn:
            row = conn.exec_driver_sql('SELECT installed_version,available_version,base_url,available_base_url,has_update FROM imported_extensions').one()
        assert tuple(row) == ('1', '2', 'https://old.example', None, 1)
    finally:
        engine.dispose()


@pytest.mark.asyncio
async def test_index_without_new_apk_url_does_not_reinstall_old_apk_as_new(installed, monkeypatch):
    service, ext_id, _ = installed
    get = AsyncMock(return_value=httpx.Response(200,
        json=[{'pkg':'review.source', 'version':'2'}],
        request=httpx.Request('GET', 'https://repo.example/index.json')))
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', get)
    await service.check_updates()
    before = row_for(service, ext_id)
    get.reset_mock()
    with pytest.raises(ValueError, match='aucune URL'):
        await service.update_extension(ext_id)
    assert row_for(service, ext_id) == before
    get.assert_not_awaited()


@pytest.mark.asyncio
async def test_enabling_a_missing_recipe_does_not_mask_an_upgrade_failure(installed, monkeypatch):
    service, ext_id, _ = installed
    with service._get_conn() as conn:
        conn.execute('UPDATE imported_extensions SET recipe_json=NULL,is_enabled=0 WHERE id=?', (ext_id,))
    before = row_for(service, ext_id)
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', AsyncMock(side_effect=httpx.ConnectError('offline')))
    with pytest.raises(ValueError):
        await service.toggle_extension(ext_id, True)
    assert row_for(service, ext_id) == before
