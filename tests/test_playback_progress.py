"""A12: stable variant identity, bounded writes and stale-session exclusion."""
import math
import pytest
from sqlalchemy.orm import sessionmaker
from pydantic import ValidationError
from animelab import database
from animelab.database import create_database_engine,transaction
from animelab.migrations import migrate
from animelab.models.download_task import DownloadTaskEntity
from animelab.models.playback import PlaybackProgress
from animelab.services.playback_service import PlaybackOpen,PlaybackSave,PlaybackSelection,PlaybackService


@pytest.fixture
def playback(tmp_path,monkeypatch):
    engine=create_database_engine('sqlite:///'+str(tmp_path/'playback.sqlite'))
    migrate(engine)
    monkeypatch.setattr(database,'SessionLocal',sessionmaker(bind=engine,expire_on_commit=False))
    yield PlaybackService()
    engine.dispose()


def open_episode(service,version='VF',**extra):
    return service.open(PlaybackOpen(**{'source':'source','animeUrl':'https://example.org/series','episodeNumber':3,'version':version,**extra}))


def save(service,state,position=120,sequence=1,**extra):
    return service.save(PlaybackSave(**{'sessionId':state.sessionId,'sequence':sequence,'positionSeconds':position,'durationSeconds':1500,'final':True,**extra}))


def test_versions_sources_and_episodes_do_not_share_a_position(playback):
    vf=open_episode(playback,' vf ')
    assert save(playback,vf)['accepted']
    assert open_episode(playback,'VF').positionSeconds==120
    assert open_episode(playback,'VOSTFR').positionSeconds==0
    assert open_episode(playback,'VO').positionSeconds==0
    assert open_episode(playback,source='other').positionSeconds==0
    assert open_episode(playback,episodeNumber=4).positionSeconds==0


def test_local_and_online_share_original_identity_not_signed_url(playback):
    with transaction() as db:
        db.add(DownloadTaskEntity(id='local',animeName='Series',animeUrl='https://example.org/series',source='source',episodeNumber=3,version='VF',fileName='vf.mp4',status='COMPLETED'))
    local=playback.open(PlaybackOpen(taskId='local'))
    save(playback,local,87)
    assert open_episode(playback).positionSeconds==87


def test_late_requests_and_old_windows_cannot_overwrite_new_progress(playback):
    first=open_episode(playback)
    save(playback,first,321,sequence=5)
    assert not save(playback,first,10,sequence=4)['accepted']
    new=open_episode(playback)
    assert new.positionSeconds==321
    assert not save(playback,first,0,sequence=6)['accepted']
    save(playback,new,555)
    assert open_episode(playback).positionSeconds==555


def test_bounded_saving_selection_and_completed_restart(playback):
    state=open_episode(playback)
    selection=PlaybackSelection(quality='720p',subtitle='["subtitles","en","English"]',audio='["audio","ja",""]')
    save(playback,state,200,selection=selection)
    result=save(playback,state,220,sequence=2,final=False,selection=selection)
    assert result['reason']=='throttled'
    assert save(playback,state,230,sequence=3,final=True,selection=selection)['accepted']
    current=open_episode(playback)
    assert current.positionSeconds==230 and current.selection==selection
    save(playback,current,1500,ended=True,selection=selection)
    assert open_episode(playback).positionSeconds==0


@pytest.mark.parametrize('value',[float('nan'),float('inf'),-1,604801])
def test_invalid_clocks_are_rejected(value):
    with pytest.raises(ValidationError):
        PlaybackSave(sessionId='a'*32,sequence=1,positionSeconds=value,durationSeconds=1500)


@pytest.mark.asyncio
async def test_playback_api_contract_and_missing_identity(playback):
    import httpx
    from fastapi import FastAPI
    from animelab.routers.playback import router
    from animelab.api_errors import install_error_handlers,ErrorContractMiddleware
    app=FastAPI();app.include_router(router);install_error_handlers(app);app.add_middleware(ErrorContractMiddleware)
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app),base_url='http://test') as client:
        result=await client.post('/api/playback/session',json={'source':'source','animeUrl':'https://example.org/series','episodeNumber':3,'version':'VF'})
        assert result.status_code==200
        body=result.json();assert body['selection']['subtitle']=='auto'
        checkpoint=await client.post('/api/playback/checkpoint',json={'sessionId':body['sessionId'],'sequence':1,'positionSeconds':60,'durationSeconds':1000,'final':True})
        assert checkpoint.json()['accepted']
        assert (await client.post('/api/playback/session',json={'taskId':'missing'})).status_code==404
        assert (await client.post('/api/playback/session',json={})).status_code==400
