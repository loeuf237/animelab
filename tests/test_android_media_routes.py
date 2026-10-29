"""UI calls use private native references, while typed failures survive the API."""
import json
from unittest.mock import AsyncMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from animelab.api_errors import APIProblem, install_error_handlers
from animelab.routers import media, download
from animelab.services.android_extensions import AndroidAPKSource
from animelab.services.extension_service import extension_service


@pytest.fixture
def native_client(monkeypatch):
    source=AndroidAPKSource({'pkg':'fixture.media'}, {'id':'17','name':'Fixture','baseUrl':'https://fixture.example'})
    source._episodes['https://fixture.example/episode']={'url':'/original','name':'One','memo':{'ticket':'private'}}
    monkeypatch.setattr(extension_service,'get_container_source_by_id',lambda key:source if key==source.source_id else None)
    monkeypatch.setattr(media.library_service,'find_downloaded_episode',lambda **kwargs:None)
    monkeypatch.setattr('animelab.security.is_safe_url',lambda url:True)
    monkeypatch.setattr('animelab.services.extension_media.validate_media_url',lambda url:None)
    app=FastAPI()
    install_error_handlers(app)
    app.include_router(media.router)
    app.include_router(download.router)
    with TestClient(app) as client:
        yield source,client


@pytest.mark.asyncio
async def test_all_hoster_failures_are_reported_but_a_working_hoster_remains_usable():
    source=AndroidAPKSource({'pkg':'fixture.media'}, {'id':'17','name':'Fixture'})
    problem=APIProblem('extension_abi_incompatible',status=422,category='validation')
    hosts=[{'hosterName':'A'},{'hosterName':'B'}]
    source.call=AsyncMock(side_effect=[hosts,problem,problem])
    with pytest.raises(APIProblem) as caught:
        await source.get_episode_sources('https://fixture.example/episode')
    assert caught.value is problem
    source.call=AsyncMock(side_effect=[hosts,problem,[{'videoUrl':'https://fixture.example/video','videoTitle':'720p'}]])
    assert (await source.get_episode_sources('https://fixture.example/episode'))[0]['server']=='B'


def test_servers_and_stream_routes_keep_private_native_inputs_out_of_responses(native_client):
    source,client=native_client
    video={'videoUrl':'https://fixture.example/video.m3u8?token=private', 'videoTitle':'720p',
           'headers':[['Authorization','private-auth']], 'memo':{'ticket':'private-video'}}
    async def call(operation,payload):
        if operation=='hosters':
            assert payload['url']=='/original' and payload['memo']=={'ticket':'private'}
            return [{'hosterName':'Fixture','videoList':[video]}]
        assert operation=='resolve_video' and payload['memo']=={'ticket':'private-video'}
        return video
    source.call=call
    response=client.get('/api/episode/servers',params={'url':'https://fixture.example/episode','source':source.source_id})
    assert response.json()=={'success':True,'servers':['Fixture'],'qualities':['720p'],'defaultServer':'auto'}
    response=client.get('/api/media/stream/resolve',params={'animeName':'One','episodeNumber':1,
                        'episodeUrl':'https://fixture.example/episode','source':source.source_id})
    assert response.status_code==200
    assert response.json()['streamUrl'].startswith('/api/media/extension-resource/')
    assert 'private' not in response.text and response.json()['qualities']=={}


@pytest.mark.parametrize('phase',['hosters','resolve_video'])
def test_native_failure_keeps_its_code_and_status_through_stream_route(native_client,phase):
    source,client=native_client
    async def call(operation,payload):
        if operation==phase:
            raise APIProblem('extension_abi_incompatible',status=422,category='validation')
        return [{'hosterName':'Fixture','videoList':[{'videoUrl':'https://fixture.example/video'}]}]
    source.call=call
    response=client.get('/api/media/stream/resolve',params={'animeName':'One','episodeNumber':1,
                        'episodeUrl':'https://fixture.example/episode','source':source.source_id})
    assert response.status_code==422 and response.json()['code']=='extension_abi_incompatible'
    if phase=='hosters':
        response=client.get('/api/episode/servers',params={'url':'https://fixture.example/episode','source':source.source_id})
        assert response.status_code==422 and response.json()['code']=='extension_abi_incompatible'
