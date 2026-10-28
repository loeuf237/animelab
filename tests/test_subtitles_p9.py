"""P9: provider contracts, matching evidence and reversible timing operations."""
import asyncio
import copy
import hashlib
import json
import os
from pathlib import Path
import random
import threading

import httpx
import pytest
from pydantic import ValidationError

from animelab.database import init_db, sqlite_connection
from animelab.services.download_subtitles import DownloadSubtitles
from animelab.services.media_execution import MediaInterrupted
from animelab.services.subdl_provider import SubDLProvider, normalize_subdl
from animelab.services.subtitle_matching import compare, deduplicate
from animelab.services.subtitle_provider import ProviderError, SubtitleQuery, match_criteria
from animelab.services.subtitle_sync import TimingCorrection, correct, timing_srt, replace_times, overlap, capabilities, alass_times
from animelab.services.subtitle_timing import intervals
from animelab.services.subtitle_vault import SubtitleVault
import test_subtitles_p8 as previous

media_case = previous.media_case
output_case = previous.output_case
SRT = previous.SRT


def subdl(handler):
    result = SubDLProvider(client_factory=lambda: httpx.AsyncClient(transport=httpx.MockTransport(handler)))
    result.key = 'fake-api-key'
    result.request_interval = 0
    return result


def response():
    return dict(status=True, results=[dict(sd_id='sd10', name='Show', imdb_id='tt000100', tmdb_id=12)],
        subtitles=[dict(n_id='abc42', sd_id='sd10', name='Show.S01E02', release_name='WEB 1080p', language='French',
                        season=1, episode=2, fps=25, duration=1400, md5='a'*32)])


@pytest.mark.asyncio
async def test_subdl_v2_auth_identifiers_download_quota_and_cdn_isolation():
    seen = []
    def handler(request):
        seen.append(request)
        if request.url.host == 'dl.subdl.com':
            assert 'authorization' not in request.headers and 'cookie' not in request.headers
            return httpx.Response(200, content=previous.zip_bytes([('Show.S01E02.srt', SRT)]))
        assert request.headers['authorization'] == 'Bearer fake-api-key'
        assert 'api_key' not in request.url.params
        if request.url.path.endswith('/me'):
            return httpx.Response(200, json={'usage': {'downloads': {'remaining': 47, 'limit': 50}}})
        if request.url.path.endswith('/search'):
            assert dict(request.url.params) == dict(imdb_id='tt100', type='tv', languages='en,fr', season='1', episode='2')
            return httpx.Response(200, json=response(), headers={'X-RateLimit-Remaining':'9'})
        assert request.url.path == '/api/v2/subtitles/abc42/download'
        assert request.url.params['format'] == 'zip'
        return httpx.Response(302, headers={'Location':'https://dl.subdl.com/subtitle/abc42.zip'})
    provider = subdl(handler)
    await provider.configure('fake-api-key')
    data = await provider.search(SubtitleQuery(query='Show', imdbId='tt000100', languages='fr,en', season=1, episode=2))
    row = data['data'][0]['attributes']
    assert row['language'] == 'fr' and row['feature_details']['parent_imdb_id'] == '100'
    assert (await provider.download('abc42'))[1] == 'abc42.zip'
    assert provider.status()['quota']['downloads']['remaining'] == 47
    assert provider.status()['quota']['requestRemaining'] == 9
    assert 'fake-api-key' not in json.dumps(provider.status())
    assert len(seen) == 4


@pytest.mark.asyncio
@pytest.mark.parametrize('status,code', [(401,'provider_auth'),(403,'provider_quota_or_access'),(402,'provider_quota_or_access'),(429,'provider_rate_limit'),(503,'provider_unavailable')])
async def test_subdl_errors_are_bounded_and_actionable(status,code):
    calls = []
    provider = subdl(lambda request: calls.append(request) or httpx.Response(status, headers={'Retry-After':'60'}))
    with pytest.raises(ProviderError) as caught:
        await provider.search(SubtitleQuery(query='Show'))
    assert caught.value.code == code and len(calls) == 1
    if status == 429:
        with pytest.raises(ProviderError):
            await provider.search(SubtitleQuery(query='Show'))
        assert len(calls) == 1


@pytest.mark.asyncio
@pytest.mark.parametrize('target', ['https://attacker.example/subtitle/a.zip','http://dl.subdl.com/subtitle/a.zip','https://api.subdl.com/api/v2/me?api_key=leak','https://127.0.0.1/subtitle/a.zip'])
async def test_subdl_redirects_never_export_key_to_arbitrary_urls(target):
    calls = []
    provider = subdl(lambda request: calls.append(request) or httpx.Response(302, headers={'Location':target}))
    with pytest.raises(ProviderError):
        await provider.download('abc42')
    assert len(calls) == 1


@pytest.mark.asyncio
async def test_subdl_rejects_invalid_identity_schema_pagination_and_episode_id():
    provider = subdl(lambda request: httpx.Response(200,json={'subtitles':[{'n_id':'https://bad'}]}))
    with pytest.raises(ProviderError):
        await provider.download('../me')
    for query in (SubtitleQuery(query='Show',page=2), SubtitleQuery(imdbId='tt100',idType='episode'), SubtitleQuery(query='Show')):
        with pytest.raises(ProviderError):
            await provider.search(query)
    data = response()
    data['subtitles'][0].pop('n_id')
    with pytest.raises(ProviderError, match='nId'):
        normalize_subdl(data,SubtitleQuery(query='Show'))


def test_missing_provider_metadata_never_inherits_requested_identity_or_absolute_number():
    query = SubtitleQuery(query='Show',imdbId='tt100',absoluteEpisode=100)
    data = normalize_subdl(dict(subtitles=[dict(nId='abc',language='fr')]),query)
    feature = data['data'][0]['attributes']['feature_details']
    checks,warnings = match_criteria(query,feature)
    assert all(row['state']=='unknown' for row in checks)
    assert warnings and 'parent_imdb_id' not in feature


def test_comparison_bad_fps_duration_release_language_and_unknown_data():
    query = SubtitleQuery(query='Show',languages='fr',expectedFps=23.976,expectedDuration=1400,expectedRelease='Show WEB 1080p GroupA')
    rows = compare(query,dict(language='en',fps=25,duration=1500,release='Show DVD GroupB'),{})
    assert len(rows)==4 and all(row['state']=='mismatch' for row in rows)
    unknown = compare(query,dict(language='fr',release=''),{})
    assert [r['state'] for r in unknown]==['match','unknown','unknown','unknown']
    with pytest.raises(ValidationError):
        SubtitleQuery(query='Show',expectedFps=float('nan'))


def test_dedup_preserves_provenance_and_does_not_merge_similar_releases_or_roles():
    def row(id,provider,**kw):
        return dict(id=id,provider=provider,providerIdentity=id,fingerprint='a'*32,language='fr',release='WEB',forced=False,
                    hearingImpaired=False,provenances=[{'provider':provider}],**kw)
    a,b = row('1','opensubtitles'),row('2','subdl')
    role = row('3','subdl');role['forced']=True
    release = row('4','subdl');release['release']='DVD'
    no_digest = row('5','subdl');no_digest['fingerprint']=None
    result = deduplicate([a,b,role,release,no_digest])
    assert len(result)==4
    assert result[0]['alternatives']==[dict(id='1',provider='opensubtitles'),dict(id='2',provider='subdl')]
    assert len(result[0]['provenances'])==2 and 'fingerprint' not in result[0]


def test_provider_vaults_independent_and_ciphertext_cannot_be_swapped(tmp_path):
    from cryptography.fernet import Fernet
    data = tmp_path/'data';data.mkdir()
    db = data/'db';init_db(db)
    key = tmp_path/'key';key.write_bytes(Fernet.generate_key());key.chmod(0o600)
    op = SubtitleVault(db,data/'downloads',data/'cache',str(key))
    sd = SubtitleVault(db,data/'downloads',data/'cache',str(key),provider='subdl')
    op.save({'apiKey':'one'});sd.save({'apiKey':'two'})
    assert op.load()['apiKey']=='one' and sd.load()['apiKey']=='two'
    with sqlite_connection(db) as conn:
        conn.execute("UPDATE subtitle_provider_secret SET payload=(SELECT payload FROM subtitle_provider_secret WHERE provider='opensubtitles') WHERE provider='subdl'")
    with pytest.raises(ProviderError):
        sd.load()
    sd.clear()
    assert sd.load() is None and op.load()['apiKey']=='one'


def request(**kw):
    return TimingCorrection(importId='a'*32,entryId='b'*32,**kw)


def test_manual_offset_fps_and_styles_unchanged():
    assert alass_times(b'2\n00:00:04,000 --> 00:00:05,000\nCue 2\n\n1\n00:00:02,000 --> 00:00:03,000\nCue 1\n', 2) == [(2,3),(4,5)]
    with pytest.raises(ProviderError):
        alass_times(b'1\n00:00:02,000 --> 00:00:03,000\nWrong marker\n', 1)
    content = b'1\n00:00:10,000 --> 00:00:12,000\nHello\n'
    output,info = correct(content,'.srt',request(sourceFps=25,targetFps=23.976,offsetSeconds=2))
    assert intervals(output,'.srt')[0][0] == pytest.approx(12.427,abs=.001)
    assert b'Hello' in output and info['kind']=='drift'
    assert content==b'1\n00:00:10,000 --> 00:00:12,000\nHello\n'
    ass = b'[Script Info]\nTitle: Styled\n[Events]\nFormat: Layer, Start, End, Style, Text\nDialogue: 0,0:00:01.00,0:00:02.00,Default,{\\i1}Hello\nDialogue: 0,0:00:03.00,0:00:04.00,Default,World\n'
    corrected = replace_times(ass,'.ass',[(2,3),(4,5)])
    assert corrected.count(b'\nDialogue:')==2 and b'{\\i1}Hello\n' in corrected
    assert intervals(corrected,'.ass')==[(2,3),(4,5)]
    clipped,_ = correct(content,'.srt',request(offsetSeconds=-11))
    assert intervals(clipped,'.srt')==[(0,1)]


@pytest.mark.parametrize('kw',[dict(sourceFps=25),dict(method='alass'),dict(method='alass',referenceTrackId='x',referenceConfirmed=True,offsetSeconds=1),dict(offsetSeconds=float('nan')),dict(method='manual',referenceTrackId='x')])
def test_invalid_correction_contract(kw):
    with pytest.raises(ValidationError):
        request(**kw)


@pytest.mark.asyncio
async def test_partial_provider_failure_and_opaque_download_routing(output_case):
    manager,task,files,requests = output_case
    manager.tasks[task.id]=task
    service = DownloadSubtitles(manager, previous.make_provider(lambda r:httpx.Response(401)))
    service.providers['subdl'] = subdl(lambda r:httpx.Response(200,json=response()) if r.url.path.endswith('/search') else httpx.Response(200,content=previous.zip_bytes([('Show.srt',SRT)])))
    data = await service.search(task.id,SubtitleQuery(query='Show',providers=['opensubtitles','subdl']))
    assert len(data['errors'])==1 and data['errors'][0]['provider']=='opensubtitles'
    assert len(data['results'])==1 and data['results'][0]['provider']=='subdl'
    package = await service.provider_preview(task.id,data['results'][0]['id'])
    assert package['provenance']['provider']=='subdl' and package['entries'][0]['cues']==1


@pytest.mark.asyncio
async def test_transform_copy_attach_restore_restart_integrity_and_other_task_rejected(output_case):
    manager,task,files,requests = output_case
    manager.tasks[task.id]=task
    provider = previous.make_provider(lambda r:httpx.Response(200))
    service = DownloadSubtitles(manager,provider)
    original = await service.upload(task.id,SRT,'episode.srt')
    rid,eid = original['importId'],original['entries'][0]['id']
    info = json.loads(task.mediaJson);path = Path(info['subtitleImports'][rid]['entries'][0]['path'])
    before = hashlib.sha256(path.read_bytes()).hexdigest()
    corrected = await service.transform(task.id,TimingCorrection(importId=rid,entryId=eid,offsetSeconds=2))
    assert corrected['importId']!=rid and corrected['originalImportId']==rid
    assert hashlib.sha256(path.read_bytes()).hexdigest()==before
    assert corrected['entries'][0]['firstCue']==pytest.approx(2.2)
    added = await service.attach(task.id,corrected['importId'],corrected['entries'][0]['id'],'fr','Corrected',True)
    service = DownloadSubtitles(manager,provider)  # persisted provenance survives restart
    restored = await service.restore_track(task.id,added['trackId'])
    tracks = service.processor.inventory(task)[0]
    assert next(t for t in tracks if t.id==added['trackId']).public()['canRestore']
    assert not next(t for t in tracks if t.id==restored['trackId']).public()['canRestore']
    assert restored['trackId']!=added['trackId']
    other = copy.copy(task);other.id='another';other.mediaJson='{}';manager.tasks[other.id]=other
    with pytest.raises(ProviderError) as caught:
        await service.transform(other.id,TimingCorrection(importId=rid,entryId=eid,offsetSeconds=1))
    assert caught.value.status==404 and path.read_bytes()==SRT


@pytest.mark.asyncio
async def test_cancel_sync_retains_lock_until_actual_worker_stops(output_case,monkeypatch):
    manager,task,files,requests = output_case;manager.tasks[task.id]=task
    service = DownloadSubtitles(manager,previous.make_provider(lambda r:httpx.Response(200)))
    package = await service.upload(task.id,SRT,'x.srt')
    started,ended = threading.Event(),threading.Event()
    def blocking(task,body,operation):
        started.set()
        assert operation['cancel'].wait(5)
        ended.set()
        raise MediaInterrupted('cancelled')
    monkeypatch.setattr(service,'_correct',blocking)
    job = asyncio.create_task(service.transform(task.id,TimingCorrection(importId=package['importId'],entryId=package['entries'][0]['id'],offsetSeconds=1)))
    assert await asyncio.to_thread(started.wait,5)
    assert task.id in manager._subtitle_mutations
    assert service.cancel_sync(task.id)
    with pytest.raises(ProviderError) as caught:
        await job
    assert caught.value.code=='subtitle_sync_cancelled' and ended.is_set()
    assert task.id not in manager._subtitle_mutations and not task.cancelled
    assert service.package(task,package['importId'])['entries'][0]['preview'].endswith('Équipage à bâbord !\n')


def test_sync_optional_path_and_android(monkeypatch,tmp_path):
    import animelab.services.subtitle_sync as sync
    monkeypatch.setattr(sync.media_tools,'is_native',lambda:False)
    monkeypatch.setenv('ANIMELAB_ALASS_PATH','relative/alass')
    assert capabilities()['alass'] is False
    monkeypatch.setattr(sync.media_tools,'is_native',lambda:True)
    assert capabilities()['alass'] is False and 'Android' in capabilities()['reason']


@pytest.mark.skipif(not os.getenv('ANIMELAB_ALASS_PATH'),reason='Optional real alass 2.0.0 not supplied')
def test_real_alass_known_corpus_and_incompatible_montage(tmp_path):
    assert capabilities()['alass']
    rng=random.Random(9321);times=[];cursor=15
    for _ in range(70):
        cursor+=rng.uniform(1.5,8);length=rng.uniform(.7,3.5);times.append((cursor,cursor+length));cursor+=length
    ref=timing_srt(times)
    for kind,values in [('offset',[(a+3.2,b+3.2) for a,b in times]),('fps',[(a*23.976/25,b*23.976/25) for a,b in times]),('cut',[(a+(20 if i>=35 else 0),b+(20 if i>=35 else 0)) for i,(a,b) in enumerate(times)])]:
        output,details=correct(timing_srt(values),'.srt',request(method='alass',referenceTrackId='local:x',referenceConfirmed=True,allowSplits=True),reference=(ref,'.srt'),directory=tmp_path)
        assert overlap(times,intervals(output,'.srt'))>.99,kind
        assert details['version']=='2.0.0'
    incompatible=[(a*1.3+10+(i%3)*2,b*1.3+10+(i%3)*2) for i,(a,b) in enumerate(times)]
    with pytest.raises(ProviderError) as caught:
        correct(timing_srt(incompatible),'.srt',request(method='alass',referenceTrackId='local:x',referenceConfirmed=True,allowSplits=True),reference=(ref,'.srt'),directory=tmp_path)
    assert caught.value.code=='subtitle_sync_incompatible'

@pytest.mark.asyncio
async def test_corrected_track_is_muxed_and_restored_with_actual_ffmpeg(output_case):
    import subprocess
    from animelab.models.download_task import DownloadStatus
    manager,task,files,requests=output_case;manager.tasks[task.id]=task
    service=DownloadSubtitles(manager,previous.make_provider(lambda r:httpx.Response(200)))
    original=await service.upload(task.id,SRT,'original.srt')
    corrected=await service.transform(task.id,TimingCorrection(importId=original['importId'],entryId=original['entries'][0]['id'],offsetSeconds=.3))
    added=await service.attach(task.id,corrected['importId'],corrected['entries'][0]['id'],'fr','Timing corrigé',True)
    async def produce(track_id,expected):
        await manager.reprocess_output(task.id,{'mode':'MKV_SOFT','selections':[{'trackId':'embedded:audio:1'},{'trackId':track_id}]})
        await manager._execute_download(task)
        assert task.status==DownloadStatus.COMPLETED,task.error
        packet=json.loads(subprocess.run(['ffprobe','-v','error','-select_streams','s','-show_packets','-of','json',task.savePath],check=True,capture_output=True,text=True).stdout)['packets'][0]
        assert float(packet['pts_time'])==pytest.approx(expected,abs=.01)
    await produce(added['trackId'],.5)
    restored=await service.restore_track(task.id,added['trackId'])
    await produce(restored['trackId'],.2)
    assert files['mkv'].exists() and not requests


def test_timing_routes_validation_reference_scope_and_missing_tool(output_case,monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from animelab.routers import subtitles as routes
    manager,task,files,requests=output_case;manager.tasks[task.id]=task
    service=DownloadSubtitles(manager,previous.make_provider(lambda r:httpx.Response(200)))
    monkeypatch.setattr(routes,'service',lambda:service)
    monkeypatch.setenv('ANIMELAB_ALASS_PATH','invalid-relative-path')
    app=FastAPI();app.include_router(routes.router)
    with TestClient(app) as client:
        root=f'/api/download/{task.id}/subtitles'
        package=client.post(root+'/import?filename=x.srt',content=SRT).json()
        body=dict(importId=package['importId'],entryId=package['entries'][0]['id'],offsetSeconds=1)
        assert client.post(root+'/transform',json={**body,'command':'/bin/sh'}).status_code==422
        assert client.post(root+'/transform',json={**body,'entryId':'f'*32}).status_code==404
        assert client.post(root+'/transform',json={**body,'offsetSeconds':0,'method':'alass','referenceTrackId':'https://bad','referenceConfirmed':True}).status_code==400
        assert client.get(root+'/imports/'+package['importId']).status_code==200
        assert client.get(root+'/imports/'+'f'*32).status_code==404
        assert client.get('/api/download/subtitle-sync-capabilities').json()['alass'] is False
        assert client.get('/api/download/subtitle-provider?provider=arbitrary').status_code==422
        assert client.post(root+'/cancel-sync').json()=={'cancelled':False}


def test_shared_worker_inherits_only_operator_tool_path_not_provider_secrets(tmp_path,monkeypatch):
    from animelab.shared.workers import Workers
    monkeypatch.setenv('ANIMELAB_ALASS_PATH','/opt/tools/alass-cli')
    monkeypatch.setenv('SUBDL_API_KEY','do-not-inherit')
    worker=Workers(tmp_path)
    env=worker.environment(worker.home('a'*32),'worker-token')
    assert env['ANIMELAB_ALASS_PATH']=='/opt/tools/alass-cli'
    assert 'SUBDL_API_KEY' not in env


@pytest.mark.asyncio
async def test_nontext_reference_returns_actionable_error_without_changing_import(output_case,monkeypatch):
    from animelab.services.output_processor import OutputError
    manager,task,files,requests=output_case;manager.tasks[task.id]=task
    service=DownloadSubtitles(manager,previous.make_provider(lambda r:httpx.Response(200)))
    package=await service.upload(task.id,SRT,'original.srt')
    reference=next(t for t in service.processor.inventory(task)[0] if t.kind=='subtitle' and t.remote is None)
    def reject(*args):
        raise OutputError('Bitmap unsupported')
    monkeypatch.setattr(service.processor,'text_file',reject)
    with pytest.raises(ProviderError) as caught:
        await service.transform(task.id,TimingCorrection(importId=package['importId'],entryId=package['entries'][0]['id'],method='alass',referenceTrackId=reference.id,referenceConfirmed=True))
    assert caught.value.code=='subtitle_sync_reference' and caught.value.status==409
    assert len(json.loads(task.mediaJson)['subtitleImports'])==1
