import hashlib
import io
import json
import zipfile

import pytest

from animelab.services.extension_backup import export_backup,restore_backup
from animelab.services.extension_service import ExtensionService


@pytest.fixture
def services(tmp_path,monkeypatch):
    cache=tmp_path/'cache'; cache.mkdir()
    monkeypatch.setattr('animelab.services.extension_service.APKS_DIR',cache)
    source=ExtensionService(str(tmp_path/'source.sqlite'))
    target=ExtensionService(str(tmp_path/'target.sqlite'))
    with source._get_conn() as conn:
        conn.execute("INSERT INTO extension_repos(id,url,name,signing_key) VALUES (1,'https://repo.example/index.min.json','Repo',?)",('a'*64,))
        conn.execute("INSERT INTO imported_extensions(id,repo_id,pkg,name,lang,runtime,installed_version,is_enabled,recipe_json) VALUES (1,1,'fixture.one','Fixture','fr','android-apk','17.1',1,?)",(json.dumps({'headers':{'Authorization':'must-not-export'}}),))
        conn.execute("INSERT INTO extension_sources(source_key,ext_id,upstream_id,pkg,name,lang,base_url,runtime,preferences_json,pinned) VALUES ('aniyomi:1152921504606846977',1,'1152921504606846977','fixture.one','Fixture','fr','https://fixture.example','android-apk',?,1)",(json.dumps({'token':'must-not-export'}),))
        conn.execute("INSERT INTO extension_trust(pkg,version_code,signer) VALUES ('fixture.one',1,?)",('b'*64,))
    return source,target,cache


def test_offline_metadata_restore_keeps_ids_and_stubs_without_granting_execution(services):
    source,target,_=services
    raw=export_backup(source)
    with zipfile.ZipFile(io.BytesIO(raw)) as archive:
        text=archive.read('extensions.json').decode()
        assert 'must-not-export' not in text and '1152921504606846977' in text
    result=restore_backup(target,raw)
    assert result['installedAPKCount']==0 and result['requiresRevalidation']
    assert result['warnings'][0]['code']=='restored_key_requires_verification'
    with target._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM extension_trust').fetchone()[0]==0
        assert conn.execute('SELECT is_active,signing_key FROM extension_repos').fetchone()[:]==(0,None)
        assert conn.execute('SELECT is_enabled,installed_version FROM imported_extensions').fetchone()[:]==(0,None)
        row=conn.execute('SELECT source_key,enabled,pinned FROM extension_sources').fetchone()
        assert row[:]==('aniyomi:1152921504606846977',0,1)
    assert restore_backup(target,raw)['extensions']==1


def test_optional_artifact_archive_hash_is_verified_before_any_restoration(services):
    source,target,cache=services
    data=b'controlled fixture archive bytes'
    digest=hashlib.sha256(data).hexdigest()
    path=cache/(digest+'.apk'); path.write_bytes(data)
    with source._get_conn() as conn:
        conn.execute('INSERT INTO extension_artifacts(sha256,pkg,path,authentication) VALUES (?,?,?,?)',(digest,'fixture.one',str(path),'test'))
    raw=export_backup(source,True)
    path.unlink()
    result=restore_backup(target,raw)
    assert result['artifacts']==1 and path.read_bytes()==data
    bad=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as original, zipfile.ZipFile(bad,'w') as output:
        for name in original.namelist():
            output.writestr(name,b'altered' if name.endswith('.apk') else original.read(name))
    with pytest.raises(ValueError,match='Empreinte'):
        restore_backup(target,bad.getvalue())


@pytest.mark.parametrize('name',['../outside','/absolute','apks/not-a-hash.apk'])
def test_restore_rejects_paths_and_retains_existing_state(services,name):
    source,target,_=services
    raw=export_backup(source)
    output=io.BytesIO()
    with zipfile.ZipFile(io.BytesIO(raw)) as original,zipfile.ZipFile(output,'w') as changed:
        changed.writestr('extensions.json',original.read('extensions.json'))
        changed.writestr(name,b'bad')
    with pytest.raises(ValueError,match='Chemin'):
        restore_backup(target,output.getvalue())
    with target._get_conn() as conn:
        assert conn.execute('SELECT count(*) FROM extension_repos').fetchone()[0]==0
