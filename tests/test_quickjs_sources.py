"""The source-built JNI bridge must consume exact, bounded upstream inputs."""
import copy

import pytest

from scripts.prepare_quickjs import git_blob, prepare


@pytest.fixture
def upstream():
    files={'LICENSE':b'Apache license fixture',
           'quickjs/common/native/quickjs/quickjs.c':b'/* MIT license fixture */\nint source_fixture;',
           'quickjs/common/java/app/cash/quickjs/QuickJs.java':b'// Java ABI fixture'}
    manifest={'commit':'a'*40,'version':'0.9.2','files':[
        {'path':name,'size':len(data),'git_blob':git_blob(data)} for name,data in files.items()]}
    calls=[]
    def fetch(url,size):
        assert url.startswith('https://raw.githubusercontent.com/cashapp/zipline/'+'a'*40+'/')
        name=url.split('/'+'a'*40+'/',1)[1]
        calls.append(name)
        return files[name]
    return manifest,files,calls,fetch


def test_exact_sources_are_cached_without_changes_and_both_licenses_are_preserved(tmp_path,upstream):
    manifest,files,calls,fetch=upstream
    receipt=prepare(tmp_path,manifest,fetch)
    assert receipt['sources_modified'] is False and len(calls)==3
    for name,data in files.items():
        assert (tmp_path/name).read_bytes()==data
    assert (tmp_path/'licenses/QuickJS-wrapper-APACHE-2.0.txt').read_bytes()==files['LICENSE']
    assert b'MIT license fixture' in (tmp_path/'licenses/QuickJS-engine-MIT.txt').read_bytes()
    prepare(tmp_path,manifest,fetch)
    assert len(calls)==3
    (tmp_path/'LICENSE').write_bytes(b'altered cache')
    prepare(tmp_path,manifest,fetch)
    assert len(calls)==4 and (tmp_path/'LICENSE').read_bytes()==files['LICENSE']


def test_download_with_the_same_size_but_wrong_identity_is_rejected(tmp_path,upstream):
    manifest,_,_,_=upstream
    with pytest.raises(ValueError,match='identity mismatch'):
        prepare(tmp_path,manifest,lambda url,size:b'x'*size)
    assert not (tmp_path/'licenses/QuickJS-source-info.json').exists()


def test_source_budget_and_path_traversal_are_rejected(tmp_path,upstream):
    manifest,_,_,fetch=upstream
    oversized=copy.deepcopy(manifest)
    oversized['files'][0]['size']=4_000_001
    with pytest.raises(ValueError,match='budget'):
        prepare(tmp_path,oversized,fetch)
    malicious=copy.deepcopy(manifest)
    malicious['files'][0]['path']='../escape'
    with pytest.raises(ValueError,match='path'):
        prepare(tmp_path,malicious,fetch)


def test_pinned_module_replaces_the_legacy_aar_and_keeps_all_native_alignment_checks():
    import json
    from pathlib import Path
    root=Path(__file__).resolve().parents[1]
    manifest=json.loads((root/'android/quickjs-compat/upstream.json').read_text())
    assert manifest['commit']=='a738129cc4aa99206c00ae49e9c5b15cb58ad880'
    assert len(manifest['files'])==31
    cmake=(root/'android/quickjs-compat/CMakeLists.txt').read_text()
    assert '-z,max-page-size=16384' in cmake and '-z,common-page-size=16384' in cmake
    runtime=(root/'android/extension-runtime/build.gradle.kts').read_text()
    assert 'api(project(":quickjs-compat"))' in runtime
    assert 'app.cash.quickjs:quickjs-android:0.9.2' not in runtime
