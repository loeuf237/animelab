"""Audit of the studied commit: passing assertions reproduce known limitations.

Run through verify_current.py to isolate user data. These are not acceptance
tests for the future fixes; their expectations must change after implementation.
"""
import io
import json
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest

from animelab.services.extension_service import ExtensionService
from animelab.services.aniyomi_dex_parser import SourceRecipe

@pytest.fixture
def service(tmp_path, monkeypatch):
    cache = tmp_path / 'apks'
    cache.mkdir()
    monkeypatch.setattr('animelab.services.extension_service.APKS_DIR', cache)
    monkeypatch.setattr('animelab.services.extension_service.is_safe_url', lambda _: True)
    return ExtensionService(str(tmp_path / 'study.sqlite'))

def item(pkg='study.alpha', version='14.2', sources=None):
    return {'pkg':pkg, 'name':pkg, 'lang':'fr', 'version':version, 'code':int(version.rsplit('.', 1)[-1]), 'apk':pkg+'.apk',
            'sources': sources or [{'id':101,'lang':'fr','name':'Alpha','baseUrl':'https://source.example'}]}

def response(monkeypatch, entries):
    monkeypatch.setattr('animelab.services.source_http.AsyncSourceClient.get', AsyncMock(return_value=
        httpx.Response(200,json=entries,request=httpx.Request('GET','https://repo.example/index.min.json'))))

def mark_installed(service, pkg='study.alpha', enabled=True):
    recipe=SourceRecipe(pkg=pkg,name='Alpha',base_url='https://source.example')
    with service._get_conn() as conn:
        conn.execute('UPDATE imported_extensions SET recipe_json=?, installed_version=version, is_enabled=? WHERE pkg=?',
                     (json.dumps(recipe.to_dict()),int(enabled),pkg))
    service._load_enabled_sources()

@pytest.mark.asyncio
async def test_importing_second_repo_removes_first_sources_from_runtime(service,monkeypatch):
    response(monkeypatch,[item()])
    await service.import_repository('https://repo-a.example/index.min.json')
    mark_installed(service)
    assert 'study.alpha' in service._active_container_sources
    response(monkeypatch,[item('study.beta')])
    await service.import_repository('https://repo-b.example/index.min.json')
    assert 'study.alpha' not in service._active_container_sources
    with service._get_conn() as conn:
        assert conn.execute('SELECT is_enabled FROM imported_extensions WHERE pkg=?',('study.alpha',)).fetchone()[0] == 1

@pytest.mark.asyncio
async def test_catalog_removal_deletes_installed_extension_and_recipe_history(service,monkeypatch):
    response(monkeypatch,[item(),item('study.beta')])
    await service.import_repository('https://repo.example/index.min.json')
    mark_installed(service)
    with service._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM extension_recipe_versions').fetchone()[0] > 0
    response(monkeypatch,[item('study.beta')])
    await service.import_repository('https://repo.example/index.min.json')
    with service._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM imported_extensions WHERE pkg=?',('study.alpha',)).fetchone()[0] == 0
        assert conn.execute('SELECT count(*) FROM extension_recipe_versions').fetchone()[0] == 0

@pytest.mark.asyncio
async def test_multi_source_package_registers_only_one_source(service,monkeypatch):
    sources=[{'id':101,'lang':'fr','name':'Alpha','baseUrl':'https://alpha.example'},
             {'id':102,'lang':'en','name':'Beta','baseUrl':'https://beta.example'}]
    response(monkeypatch,[item(sources=sources)])
    await service.import_repository('https://repo.example/index.min.json')
    mark_installed(service)
    assert list(service._active_container_sources) == ['study.alpha']
    assert service._active_container_sources['study.alpha'].source_id == 'study.alpha'
    with service._get_conn() as conn:
        assert len(json.loads(conn.execute('SELECT sources_meta FROM imported_extensions').fetchone()[0])) == 2

@pytest.mark.asyncio
async def test_lower_remote_version_is_reported_as_update(service,monkeypatch):
    response(monkeypatch,[item(version='14.20')])
    await service.import_repository('https://repo.example/index.min.json')
    mark_installed(service,enabled=False)
    response(monkeypatch,[item(version='14.2')])
    await service.check_updates()
    with service._get_conn() as conn:
        assert conn.execute('SELECT has_update FROM imported_extensions').fetchone()[0] == 1

@pytest.mark.asyncio
async def test_refresh_clears_recipe_of_installed_disabled_extension(service,monkeypatch):
    response(monkeypatch,[item(version='14.1')])
    await service.import_repository('https://repo.example/index.min.json')
    mark_installed(service,enabled=False)
    response(monkeypatch,[item(version='14.2')])
    await service.import_repository('https://repo.example/index.min.json')
    with service._get_conn() as conn:
        row=conn.execute('SELECT installed_version,version,recipe_json FROM imported_extensions').fetchone()
        assert tuple(row) == ('14.1','14.2',None)

def test_dex_zip_without_manifest_or_signature_passes_apk_validator():
    data=io.BytesIO()
    with zipfile.ZipFile(data,'w') as archive:
        archive.writestr('classes.dex', b'dex\n035\0'+bytes(104))
    ExtensionService._validate_apk(data.getvalue())
