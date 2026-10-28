"""Closed experimental perimeter, reproducible failure cases and no default adoption."""
import asyncio
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
from types import SimpleNamespace
import xml.etree.ElementTree as ET

import httpx
import pytest

from animelab.services.experimental.manifest_relay import ManifestRelay,byte_range
from animelab.services.experimental.nm3u8dl_backend import N_m3u8Backend,namespace_available,LOCK
from animelab.services.media_contracts import ResolvedMedia,UnsupportedMedia
from animelab.services.media_execution import MediaInterrupted
from scripts.evaluate_nm3u8dl import FixtureOrigin
from scripts.nm3u8dl_fixtures import generate


@pytest.fixture
def corpus(tmp_path):
    generate(tmp_path/'fixtures')
    return FixtureOrigin(tmp_path/'fixtures')


def relay(tmp_path,origin,name='relay',**kwargs):
    return ManifestRelay(tmp_path/name,client_factory=origin.client,validator=origin.validate,**kwargs)


@pytest.mark.asyncio
@pytest.mark.parametrize('case',['simple','aes','fmp4','dash','subtitle','discontinuity'])
async def test_rewrites_all_supported_references_to_verified_local_files(tmp_path,corpus,case):
    r=relay(tmp_path,corpus,clock_probe=case=='discontinuity')
    suffix='mpd' if case=='dash' else 'm3u8'
    entry=await r.materialize(f'https://fixture.example/{case}/index.{suffix}')
    plan=r.seal(entry)
    assert plan['expectedDuration']==4 and len(plan['files'])>1
    for name,expected in plan['files'].items():
        data=r.read(r.capability,name).read_bytes()
        assert hashlib.sha256(data).hexdigest()==expected['sha256']
        if name.endswith('.m3u8'):assert b'https://' not in data and b'file://' not in data
    if case=='fmp4':
        text=(r.directory/entry).read_text()
        assert '#EXT-X-BYTERANGE:10511@0' in text
        assert any(req.headers.get('range')=='bytes=1354-11864' for req in corpus.calls)
    if case=='dash':
        root=ET.fromstring((r.directory/entry).read_bytes())
        templates=[item for item in root.iter() if item.tag.endswith('SegmentTemplate')]
        assert len(templates)==2 and all('$Number$' in item.get('media') for item in templates)
        assert 'https://' not in json.dumps(plan)
    r.revoke()
    with pytest.raises(PermissionError):r.read('old',entry)


@pytest.mark.asyncio
async def test_capabilities_cannot_cross_tasks_or_survive_revocation(tmp_path,corpus):
    a,b=relay(tmp_path,corpus,'a'),relay(tmp_path,corpus,'b')
    entry=await a.materialize('https://fixture.example/simple/index.m3u8')
    with pytest.raises(PermissionError):b.read(a.capability,entry)
    cap=a.capability;a.revoke()
    with pytest.raises(PermissionError):a.read(cap,entry)
    with pytest.raises(MediaInterrupted):await a.materialize('https://fixture.example/simple/index.m3u8')


@pytest.mark.asyncio
async def test_private_redirect_rejected_before_request_and_headers_origin_scoped(tmp_path,corpus):
    corpus.redirect='http://127.0.0.1/private'
    r=relay(tmp_path,corpus,headers={'Authorization':'secret','Cookie':'private'})
    with pytest.raises((ValueError,UnsupportedMedia)):await r.materialize('https://fixture.example/simple/index.m3u8')
    assert len(corpus.calls)==1
    calls=[]
    def handler(request):
        calls.append(request)
        if request.url.host=='fixture.example':return httpx.Response(302,headers={'location':'https://cdn.example/resource'})
        assert 'authorization'not in request.headers and 'cookie'not in request.headers
        return httpx.Response(200,content=b'valid bytes',headers={'content-length':'11'})
    def valid(url):
        if httpx.URL(url).host not in ('fixture.example','cdn.example'):raise ValueError('Denied')
    r=ManifestRelay(tmp_path/'cross',validator=valid,headers={'Authorization':'secret','Cookie':'private'},client_factory=lambda **kw:httpx.AsyncClient(transport=httpx.MockTransport(handler),**kw))
    r.origin='fixture.example'
    await r.resource('https://fixture.example/redirect')
    assert len(calls)==2
    assert 'secret'not in (r.directory/'cache.json').read_text()


@pytest.mark.asyncio
@pytest.mark.parametrize('uri',['file:///etc/passwd','ftp://fixture.example/a','https://user:pass@fixture.example/x','http://127.0.0.1/private','https://attacker.example/segment'])
async def test_manifest_child_cannot_introduce_arbitrary_destinations(tmp_path,corpus,uri):
    p=corpus.root/'simple/index.m3u8';p.write_text('#EXTM3U\n#EXTINF:1,\n'+uri+'\n#EXT-X-ENDLIST\n')
    with pytest.raises((ValueError,UnsupportedMedia)):await relay(tmp_path,corpus).materialize('https://fixture.example/simple/index.m3u8')
    assert len(corpus.calls)==1


@pytest.mark.asyncio
@pytest.mark.parametrize('body',[
 '#EXTM3U\n#EXTINF:1,\nsegment.ts\n',
 '#EXTM3U\n#EXT-X-KEY:METHOD=SAMPLE-AES,URI="x"\n#EXT-X-ENDLIST\n',
 '#EXTM3U\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="a",URI="a.m3u8"\n#EXT-X-MEDIA:TYPE=AUDIO,GROUP-ID="b",URI="b.m3u8"\n#EXT-X-ENDLIST\n',
 '#EXTM3U\n#EXT-X-BYTERANGE:100\nindex0.ts\n#EXT-X-ENDLIST\n',
 '#EXTM3U\n#EXT-X-PART:URI="partial.ts"\n#EXT-X-ENDLIST\n',
 '#EXTM3U\n#EXT-X-STREAM-INF:BANDWIDTH=1\nindex.m3u8\n',
])
async def test_unsupported_hls_refused_without_silent_track_loss(tmp_path,corpus,body):
    (corpus.root/'simple/index.m3u8').write_text(body)
    with pytest.raises(UnsupportedMedia):await relay(tmp_path,corpus).materialize('https://fixture.example/simple/index.m3u8')


@pytest.mark.asyncio
@pytest.mark.parametrize('body',[
 '<!DOCTYPE MPD [<!ENTITY x SYSTEM "file:///etc/passwd">]><MPD/>',
 '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011" type="dynamic"/>',
 '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period/><Period/></MPD>',
 '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><ContentProtection/><Period/></MPD>',
 '<MPD xmlns="urn:mpeg:dash:schema:mpd:2011"><Period><Location>https://bad</Location></Period></MPD>',
])
async def test_dash_live_drm_entities_and_unsupported_periods_are_refused(tmp_path,corpus,body):
    (corpus.root/'dash/index.mpd').write_text(body)
    with pytest.raises(UnsupportedMedia):await relay(tmp_path,corpus).materialize('https://fixture.example/dash/index.mpd')


@pytest.mark.asyncio
async def test_etag_cache_revalidated_corruption_and_changed_manifest_never_mix(tmp_path,corpus):
    url='https://fixture.example/simple/index.m3u8'
    a=relay(tmp_path,corpus);entry=await a.materialize(url);first=a.seal(entry)
    a.revoke()
    b=relay(tmp_path,corpus);entry=await b.materialize(url)
    assert b.downloaded < a.downloaded
    assert any(req.headers.get('if-none-match') for req in corpus.calls)
    assert b.seal(entry)['representation']==first['representation']
    asset=next(path for path in b.directory.glob('*.ts'));asset.write_bytes(b'corrupt')
    c=relay(tmp_path,corpus);entry=await c.materialize(url)
    assert c.seal(entry)['representation']==first['representation']
    assert asset.read_bytes()!=b'corrupt'
    # Signed URLs and content changes are conservative representation changes.
    data=(corpus.root/'simple/index.m3u8').read_text().replace('index0.ts','index0.ts?signature=renewed')
    (corpus.root/'simple/index.m3u8').write_text(data)
    d=relay(tmp_path,corpus);entry=await d.materialize(url)
    assert d.seal(entry)['representation']!=first['representation']
    assert 'renewed'not in (d.directory/'plan.json').read_text()
    assert 'renewed'not in (d.directory/'cache.json').read_text()


@pytest.mark.asyncio
async def test_network_cut_truncation_and_stop_leave_only_complete_verified_fragments(tmp_path,corpus):
    corpus.truncated='index1.ts'
    a=relay(tmp_path,corpus)
    with pytest.raises(ConnectionError):await a.materialize('https://fixture.example/simple/index.m3u8')
    assert not list(a.directory.glob('*.partial'))
    assert list(a.directory.glob('*.ts'))
    corpus.truncated=None;corpus.offline=True
    with pytest.raises(httpx.ConnectError):await relay(tmp_path,corpus).materialize('https://fixture.example/simple/index.m3u8')
    corpus.offline=False;stopped=False
    def stop():
        nonlocal stopped
        stopped=True
    corpus.cancel=stop
    b=relay(tmp_path,corpus,'cancel',cancel=lambda:stopped)
    with pytest.raises(MediaInterrupted):await b.materialize('https://fixture.example/simple/index.m3u8')
    corpus.cancel=None
    assert not list(b.directory.glob('*.ts'))
    c=relay(tmp_path,corpus);entry=await c.materialize('https://fixture.example/simple/index.m3u8');assert c.seal(entry)


def test_production_never_silently_selects_the_experimental_backend(tmp_path):
    from animelab.services.transfer_backends import TransferPlanner
    with pytest.raises(UnsupportedMedia):N_m3u8Backend(tmp_path,'/missing')
    planner=TransferPlanner(object())
    assert planner.select(ResolvedMedia('https://fixture.example/a.mp4')).name=='http-range'
    with pytest.raises(UnsupportedMedia):planner.select(ResolvedMedia('https://fixture.example/a.mpd',protocol='dash'))
    assert all('nm3u8'not in b.name for b in planner.backends)


@pytest.mark.skipif(not os.getenv('ANIMELAB_NM3U8DL_EVAL_PATH'),reason='Pinned optional binary not supplied')
@pytest.mark.asyncio
async def test_real_binary_and_namespace_against_known_corpus(tmp_path):
    from scripts.evaluate_nm3u8dl import evaluate
    assert namespace_available()
    report=await evaluate(Path(os.environ['ANIMELAB_NM3U8DL_EVAL_PATH']),tmp_path/'étude with spaces')
    assert all(row['success'] and row['videoFramesMatchReference'] for row in report['cases'] if not row['negativeClockProbe'])
    assert next(row for row in report['cases'] if row['negativeClockProbe'])['success'] is False
    assert all(row.get('subtitleClockCorrect',True) for row in report['cases'] if row['case']!='discontinuity')
    assert next(row for row in report['cases'] if row['case']=='discontinuity')['subtitleClockCorrect'] is False
    assert report['corruptToolCache']['upstreamReportedSuccess'] is True
    assert report['corruptToolCache']['accepted'] is False
    assert report['corruptToolCache']['safeRebuildFramesMatchReference'] is True


@pytest.mark.asyncio
async def test_known_bad_discontinuity_is_refused_unless_explicit_negative_probe(tmp_path,corpus):
    r=relay(tmp_path,corpus)
    with pytest.raises(UnsupportedMedia,match='Discontinuités'):
        await r.materialize('https://fixture.example/discontinuity/index.m3u8')
    assert not list(r.directory.glob('*.ts'))


@pytest.mark.skipif(sys.platform!='linux',reason='Linux namespace boundary')
def test_actual_network_namespace_has_no_external_route():
    if not namespace_available():pytest.skip('Unprivileged user namespaces unavailable')
    code='import socket,os,json; s=socket.socket();s.settimeout(.1);print(json.dumps({"namespace":os.readlink("/proc/self/ns/net"),"external":s.connect_ex(("192.0.2.1",443))}))'
    result=subprocess.run(['unshare','--user','--map-root-user','--net',sys.executable,'-c',code],capture_output=True,text=True,check=True,timeout=5)
    value=json.loads(result.stdout)
    assert value['namespace']!=os.readlink('/proc/self/ns/net') and value['external']==101


@pytest.mark.asyncio
async def test_relay_uses_source_http_refreshed_sessions_and_account_isolation(tmp_path,monkeypatch):
    from animelab.services.source_http import SourceHTTPService
    from animelab.services.proxy_service import proxy_service
    from test_source_http import FakeSession
    monkeypatch.setattr('animelab.services.source_http.is_safe_url',lambda url:True)
    monkeypatch.setattr(proxy_service,'get_random_proxy',lambda:None)
    seen=[]
    class Raw:
        def __init__(self,url,content,status=200):
            self.url=url;self.content=content;self.status_code=status
            self.headers=httpx.Headers({'content-type':'application/octet-stream','content-length':str(len(content))})
        def iter_content(self):yield self.content
        def close(self):pass
    def handler(session,method,url,kwargs):
        seen.append(session.cookies.get_dict().copy())
        if url.endswith('index.m3u8'):
            session.cookies.set('clearance','fresh',domain='fixture.example')
            return Raw(url,b'#EXTM3U\n#EXTINF:1,\nsegment.ts\n#EXT-X-ENDLIST\n')
        assert session.cookies.get_dict()['clearance']=='fresh'
        return Raw(url,b'synthetic segment bytes')
    services=[]
    try:
        for name,cookie in [('a','account-a'),('b','account-b')]:
            service=SourceHTTPService(storage=tmp_path/name/'sessions',min_interval=0,session_factory=lambda **kw:FakeSession(handler,**kw));services.append(service)
            service.import_cookies('https://fixture.example', [{'name':'clearance','value':cookie,'domain':'fixture.example','secure':True}])
            r=ManifestRelay(tmp_path/name/'relay',client_factory=lambda **kw:service.async_client(url_validator=lambda url:None,**kw),validator=lambda url:None)
            await r.materialize('https://fixture.example/index.m3u8')
        assert seen[0]['clearance']=='account-a' and seen[1]['clearance']=='fresh'
        assert seen[2]['clearance']=='account-b' and seen[3]['clearance']=='fresh'
        for service in services:
            assert 'clearance' not in json.dumps(service.diagnostics())
    finally:
        for service in services:service.close()


@pytest.mark.skipif(not os.getenv('ANIMELAB_NM3U8DL_EVAL_PATH'),reason='Pinned optional binary not supplied')
@pytest.mark.asyncio
async def test_real_process_cancellation_preserves_verified_resources_for_restart(tmp_path,corpus,monkeypatch):
    import threading
    from animelab.services.experimental import nm3u8dl_backend as module
    original=module.run_process;started=threading.Event()
    def supervised(args,**kwargs):
        if args[0]=='unshare':
            emit=kwargs['emit']
            def observe(event):
                if event.kind=='started':started.set()
                emit(event)
            kwargs['emit']=observe
        return original(args,**kwargs)
    monkeypatch.setattr(module,'run_process',supervised)
    monkeypatch.setenv('ANIMELAB_NM3U8DL_EVAL_DELAY','2')
    backend=N_m3u8Backend(tmp_path/'jobs',os.environ['ANIMELAB_NM3U8DL_EVAL_PATH'],evaluation=True,client_factory=corpus.client,validator=corpus.validate)
    task=SimpleNamespace(id='cancel-process',paused=False,cancelled=False)
    media=ResolvedMedia('https://fixture.example/simple/index.m3u8',protocol='hls')
    job=asyncio.create_task(backend.transfer(task,media,lambda event:None))
    assert await asyncio.to_thread(started.wait,10)
    await asyncio.sleep(.3)
    assert not job.done()
    task.cancelled=True
    with pytest.raises(MediaInterrupted):await job
    assert backend.last_relay.revoked and list(backend.last_relay.directory.glob('*.ts'))
    state=json.loads((backend.last_relay.directory.parent/'checkpoint.json').read_text())
    assert state['status']=='interrupted'
    monkeypatch.delenv('ANIMELAB_NM3U8DL_EVAL_DELAY');task.cancelled=False
    restored=await backend.transfer(task,media,lambda event:None)
    assert restored.complete


def test_evaluation_fetcher_checks_archive_and_never_extracts_extra_paths(tmp_path,monkeypatch):
    import io,zipfile
    from scripts import fetch_nm3u8dl_eval as fetcher
    content=io.BytesIO()
    with zipfile.ZipFile(content,'w') as bundle:
        bundle.writestr('../../unrelated.txt','must not be extracted')
        bundle.writestr('tool/N_m3u8DL-RE.exe',b'fake executable for extraction test')
    archive=tmp_path/'upstream.zip';archive.write_bytes(content.getvalue())
    metadata={'name':'fixture.zip','bytes':archive.stat().st_size,'sha256':hashlib.sha256(archive.read_bytes()).hexdigest(),'url':'https://unused.example'}
    monkeypatch.setitem(fetcher.LOCK['assets'],'win-x64',metadata)
    receipt=fetcher.prepare('win-x64',tmp_path/'output',archive)
    assert receipt['adoption'].startswith('evaluation-only')
    assert (tmp_path/'output/N_m3u8DL-RE.exe').read_bytes()==b'fake executable for extraction test'
    assert sorted(p.name for p in (tmp_path/'output').iterdir())==['N_m3u8DL-RE.exe','receipt.json']
    assert not (tmp_path.parent/'unrelated.txt').exists()
    archive.write_bytes(b'corrupted')
    with pytest.raises(ValueError,match='SHA-256'):fetcher.prepare('win-x64',tmp_path/'output',archive)


def test_manual_workflow_does_not_publish_or_bundle_the_prototype():
    root=Path(__file__).resolve().parents[1]
    workflow=(root/'.github/workflows/nm3u8dl-evaluation.yml').read_text()
    assert 'workflow_dispatch:' in workflow and 'contents: read' in workflow
    assert 'contents: write' not in workflow and 'tags:' not in workflow and 'push:' not in workflow
    assert 'build/nm3u8dl-evaluation/N_m3u8DL-RE' not in (root/'animelab.spec').read_text()
    assert 'N_m3u8DL' not in (root/'Dockerfile').read_text()
