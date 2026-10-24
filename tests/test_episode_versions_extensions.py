import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from animan.models.download_task import DownloadTask, DownloadStatus
from animan.services.download_manager import download_manager as manager
from animan.services.library_service import library_service
from animan.services.extension_service import ExtensionService
from animan.services.aniyomi_dex_parser import SourceRecipe, AniyomiDexParser
from animan.services.aniyomi_container import AniyomiContainerSource


@pytest.fixture
def isolated(monkeypatch, tmp_path):
    monkeypatch.setattr(manager, 'download_dir', str(tmp_path))
    monkeypatch.setattr(manager, 'tasks', {})
    monkeypatch.setattr(manager, 'task_order', [])
    monkeypatch.setattr(manager, '_trigger_process_queue', lambda: None)
    monkeypatch.setattr(manager, 'broadcast_update', lambda task: None)
    monkeypatch.setattr(library_service, 'save_task', lambda task: None)
    monkeypatch.setattr(library_service, 'save_tasks_batch', lambda tasks: None)


@pytest.mark.parametrize('plex', [False, True])
def test_versions_have_separate_single_batch_and_existing_paths(isolated, monkeypatch, plex):
    monkeypatch.setattr(manager, 'plex_organization', plex)
    single = manager.start_download('Anime', 1, 'https://anime/vf/1', 'Anime - Episode 1.mp4', version='VF', anime_url='https://anime/title')
    batch = manager.start_batch_download('Anime', [{'number':1, 'url':'https://anime/vo/1', 'version':'VOSTFR', 'animeUrl':'https://anime/title'}])[0]
    assert single.savePath != batch.savePath
    assert single.version == 'VF'
    assert batch.version == 'VOSTFR'
    assert single.animeUrl == batch.animeUrl == 'https://anime/title'
    from pathlib import Path
    Path(single.savePath).write_bytes(b'video')
    assert manager.check_existing_file('Anime', 'Anime - Episode 1.mp4', 1, 'VF') == Path(single.savePath)
    assert manager.check_existing_file('Anime', 'Anime - Episode 1.mp4', 1, 'VOSTFR') is None
    restored = single.to_entity().to_task()
    assert restored.version == 'VF' and restored.animeUrl == single.animeUrl
    assert restored.to_dict()['version'] == 'VF'


@pytest.mark.asyncio
async def test_anisama_ajax_episodes_and_sources(isolated, monkeypatch):
    recipe = SourceRecipe(pkg='eu.kanade.tachiyomi.animeextension.fr.anisama', base_url='https://v1.animesz.xyz')
    AniyomiDexParser._fill_heuristics(recipe)
    source = AniyomiContainerSource(recipe)
    assert source.recipe.runtime['episodes']['kind'] == 'json_html'
    async def fetch(url, **kwargs):
        if '/ajax/episode/list/' in url:
            assert url.endswith('/123')
            return json.dumps({'html':'<a class="ep-item" data-number="2" href="?ep=222" title="Episode 2"></a><a class="ep-item" data-number="1" href="?ep=111"></a>'})
        if '/ajax/episode/servers' in url:
            return json.dumps({'html':'<div class="server-item" data-id="99">Sibnet</div>'})
        if '/ajax/episode/sources' in url:
            assert 'id=99' in url and 'epid=111' in url
            return json.dumps({'link':'https://video.sibnet.ru/shell.php?videoid=1'})
        return '<h1>Naruto</h1>'
    monkeypatch.setattr(source, '_fetch_html', fetch)
    detail = await source.get_anime_detail('https://v1.animesz.xyz/anime/naruto-123')
    assert [e.number for e in detail.episodes] == [1,2]
    sources = await source.get_episode_sources(detail.episodes[0].playerUrl)
    assert sources[0]['url'] == 'https://video.sibnet.ru/shell.php?videoid=1'


@pytest.mark.asyncio
async def test_franime_api_language_season_and_players(isolated, monkeypatch):
    source = AniyomiContainerSource(SourceRecipe(pkg='eu.kanade.tachiyomi.animeextension.fr.franime', base_url='https://franime.fr'))
    catalogue = [{'id':17, 'title':'Naruto', 'originalTitle':'Naruto', 'seasons':[{'episodes':[
        {'title':'One', 'languages':{'vo':{'players':['sendvid']}, 'vf':{'players':['sibnet']}}},
        {'title':'Two', 'languages':{'vo':{'players':['sendvid']}, 'vf':{'players':[]}}},
    ]}]}]
    async def fetch(url, **kwargs):
        if url.endswith('/animes/'):
            return json.dumps(catalogue)
        assert url.endswith('/anime/17/0/0/vf/0')
        return 'https://video.sibnet.ru/shell.php?videoid=17'
    monkeypatch.setattr(source, '_fetch_html', fetch)
    entries = await source.search_anime('naruto')
    assert {e.version for e in entries} == {'VF','VOSTFR'}
    vf = next(e for e in entries if e.version == 'VF')
    detail = await source.get_anime_detail(vf.url)
    assert len(detail.episodes) == 1 and detail.episodes[0].version == 'VF'
    assert (await source.get_episode_sources(detail.episodes[0].playerUrl))[0]['server'] == 'sibnet'


@pytest.mark.asyncio
async def test_vostfree_numbers_and_player_ids(isolated, monkeypatch):
    recipe = SourceRecipe(pkg='eu.kanade.tachiyomi.animeextension.fr.vostfree', base_url='https://vostfree.ws')
    AniyomiDexParser._fill_heuristics(recipe)
    source = AniyomiContainerSource(recipe)
    html = '''<h1>Naruto VF</h1><select class="new_player_selector"><option value="">Choisir</option><option value="1">Episode 1</option><option value="2">Episode 2</option></select>
    <div id="buttons_2"><div id="ep2sibnet">sibnet</div></div><div id="content_ep2sibnet">12345</div>'''
    monkeypatch.setattr(source, '_fetch_html', AsyncMock(return_value=html))
    detail = await source.get_anime_detail('https://vostfree.ws/naruto.html')
    assert [e.number for e in detail.episodes] == [1,2]
    assert all(e.version == 'VF' for e in detail.episodes)
    assert detail.episodes[1].playerUrl.endswith('?episode=2')
    sources = await source.get_episode_sources(detail.episodes[1].playerUrl)
    assert sources[0]['url'].endswith('videoid=12345')


@pytest.mark.asyncio
async def test_dooplay_loads_player_and_relative_iframe(isolated, monkeypatch):
    source = AniyomiContainerSource(SourceRecipe(pkg='jetanime', base_url='https://ssl.jetanimes.com'))
    async def fetch(url, **kwargs):
        if '/wp-json/' in url:
            return json.dumps({'embed_url':'https://player.example/embed/42'})
        return '<iframe data-src="../player/1"></iframe><ul id="playeroptionsul"><li data-post="22" data-nume="1" data-type="tv"></li></ul>'
    monkeypatch.setattr(source, '_fetch_html', fetch)
    sources = await source.get_episode_sources('https://ssl.jetanimes.com/episodes/test/1')
    assert {s['url'] for s in sources} == {'https://ssl.jetanimes.com/episodes/player/1','https://player.example/embed/42'}


@pytest.mark.asyncio
async def test_repository_refresh_invalidates_changed_recipes_and_removes_stale(isolated, tmp_path, monkeypatch):
    service = ExtensionService(str(tmp_path / 'extensions.db'))
    rows = [{'pkg':'ext.alpha','name':'Alpha','version':'1','sources':[{'baseUrl':'https://alpha.example'}]}, {'pkg':'ext.beta','name':'Beta'}]
    response = MagicMock()
    response.status_code = 200
    response.json.side_effect = lambda: rows
    monkeypatch.setattr('animan.services.source_http.AsyncSourceClient.get', AsyncMock(return_value=response))
    await service.import_repository('https://repo.example/index.min.json')
    first = service.get_visible_extensions()[0]
    await service.configure_extension(first['id'], {'base_url':'https://alpha.example','search_selector':'article'})
    await service.toggle_extension(first['id'], True)
    rows[:] = [{**rows[0], 'version':'2'}]
    await service.import_repository('https://repo.example/index.min.json')
    visible = service.get_visible_extensions()
    assert len(visible) == 1
    # A13 stores the regenerated effective recipe as a new revision after invalidation.
    assert json.loads(visible[0]['recipe_json'])['schema_version'] == 1
    assert service.recipe_history(visible[0]['id'])['revisions']
    assert visible[0]['is_enabled'] == 1
    assert service.get_container_source_by_id('ext.alpha') is not None
    assert service.get_container_source_by_id('alp') is None
    with pytest.raises(ValueError):
        await service.configure_extension(first['id'], {'search_selector':'['})


@pytest.mark.asyncio
async def test_failed_activation_does_not_persist_enabled(isolated, tmp_path, monkeypatch):
    service = ExtensionService(str(tmp_path / 'extensions.db'))
    with service._get_conn() as conn:
        conn.execute("INSERT INTO extension_repos(url,name) VALUES ('https://repo.example','Repo')")
        conn.execute("INSERT INTO imported_extensions(repo_id,pkg,name,lang) VALUES (1,'no.domain','No domain','fr')")
    monkeypatch.setattr(service, '_compile_extension_recipe', AsyncMock(return_value=SourceRecipe(pkg='no.domain').to_dict()))
    with pytest.raises(ValueError):
        await service.toggle_extension(1, True)
    assert service.get_visible_extensions()[0]['is_enabled'] == 0


def test_repeated_requests_do_not_queue_same_episode_twice(isolated, monkeypatch):
    monkeypatch.setattr(manager, 'plex_organization', False)
    first = manager.start_download('Anime', 1, 'https://anime/vf/1', 'vf.mp4', version='VF')
    second = manager.start_download('Anime', 1, 'https://anime/vf/1', 'vf.mp4', version='VF')
    assert first.id == second.id
    assert manager.start_batch_download('Anime', [{'number':1, 'url':'https://anime/vf/1', 'version':'VF'}]) == []
    assert len(manager.tasks) == 1


@pytest.mark.asyncio
async def test_source_http_blocks_redirect_to_private_host(isolated, monkeypatch, tmp_path):
    import httpx
    from curl_cffi.requests import Cookies
    from animan.services.source_http import SourceHTTPService
    calls = []
    class FakeSession:
        def __init__(self, **kwargs): self.cookies = Cookies()
        def request(self, method, url, **kwargs):
            calls.append(url)
            return httpx.Response(302, headers={'location':'http://127.0.0.1/admin'}, request=httpx.Request(method, url))
        def close(self): pass
    transport = SourceHTTPService(storage=tmp_path, session_factory=FakeSession)
    monkeypatch.setattr('animan.services.aniyomi_container.source_http', transport)
    source = AniyomiContainerSource(SourceRecipe(pkg='test', base_url='https://source.example'))
    try:
        with pytest.raises(ValueError, match='URL source non autorisée'):
            await source._fetch_html('https://source.example')
        assert len(calls) == 1 and 'non autorisée' in source.last_error
    finally:
        transport.close()


def test_legacy_shared_destination_is_paused_before_file_validation(isolated, monkeypatch, tmp_path):
    path = tmp_path / 'shared.mp4'
    path.write_bytes(b'old video')
    tasks = [DownloadTask(animeName='Anime', episodeNumber=1, savePath=str(path), fileName=path.name,
             downloadPageUrl=f'https://anime/{version}/1', status=DownloadStatus.PENDING) for version in ['vf','vo']]
    monkeypatch.setattr(library_service, 'get_unfinished_tasks', lambda: [task.to_entity() for task in tasks])
    monkeypatch.setattr(library_service, 'get_completed_tasks', lambda: [])
    manager.init_from_db()
    assert all(t.status == DownloadStatus.PAUSED for t in manager.tasks.values())
    assert manager.resume_download(tasks[0].id) is False
    assert path.read_bytes() == b'old video'
