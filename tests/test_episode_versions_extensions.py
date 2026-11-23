import json
from unittest.mock import AsyncMock, MagicMock
import pytest
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.download_manager import download_manager as manager
from animelab.services.library_service import library_service
from animelab.services.extension_service import ExtensionService
from animelab.services.aniyomi_dex_parser import SourceRecipe, AniyomiDexParser
from animelab.services.aniyomi_container import AniyomiContainerSource


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
async def test_repository_refresh_preserves_installed_recipe_and_retires_stale(isolated, tmp_path, monkeypatch):
    service = ExtensionService(str(tmp_path / 'extensions.db'))
    rows = [{'pkg':'ext.alpha','name':'Alpha','version':'1','sources':[{'baseUrl':'https://alpha.example'}]}, {'pkg':'ext.beta','name':'Beta'}]
    response = MagicMock()
    response.status_code = 200
    async def fetch(url):
        if not url.endswith('index.min.json'):
            raise ValueError('No optional repository metadata')
        return json.dumps(rows).encode()
    monkeypatch.setattr(service, '_fetch_catalog_bytes', fetch)
    await service.import_repository('https://repo.example/index.min.json')
    first = service.get_visible_extensions()[0]
    await service.configure_extension(first['id'], {'base_url':'https://alpha.example','search_selector':'article'})
    await service.toggle_extension(first['id'], True)
    rows[:] = [{**rows[0], 'version':'2'}]
    await service.import_repository('https://repo.example/index.min.json')
    visible = service.get_visible_extensions()
    assert len(visible) == 2
    assert next(row for row in visible if row['pkg']=='ext.beta')['catalog_state'] == 'retired'
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
    from animelab.services.source_http import SourceHTTPService
    calls = []
    class FakeSession:
        def __init__(self, **kwargs): self.cookies = Cookies()
        def request(self, method, url, **kwargs):
            calls.append(url)
            return httpx.Response(302, headers={'location':'http://127.0.0.1/admin'}, request=httpx.Request(method, url))
        def close(self): pass
    transport = SourceHTTPService(storage=tmp_path, session_factory=FakeSession)
    monkeypatch.setattr('animelab.services.aniyomi_container.source_http', transport)
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


def test_versioned_filename_with_slash_in_version_or_title_does_not_collide(isolated, monkeypatch):
    monkeypatch.setattr(manager, 'plex_organization', False)
    title = 'One Piece: Kai - Saga 10 (Pays des Wa)'
    tasks = manager.start_batch_download(
        title,
        [
            {
                'number': n,
                'url': f'https://seanime.local/anime-sama-anime/episode/%7B%22index%22%3A{n}%7D',
                'version': 'VOSTFR / VF',
                'fileName': f'{title} - Episode {n} [VOSTFR / VF].mp4',
                'animeUrl': 'https://seanime.local/anime-sama-anime/anime/kai10',
            }
            for n in (1, 2, 3)
        ],
        source='seanime:anime-sama-anime',
    )
    assert len(tasks) == 3
    names = [t.fileName for t in tasks]
    assert len(set(names)) == 3
    assert len({t.savePath for t in tasks}) == 3
    for n, t in zip((1, 2, 3), tasks):
        assert 'One Piece_ Kai' in t.fileName
        assert f'Episode {n}' in t.fileName
        assert not t.fileName.startswith('VF]')
        assert manager._has_destination_conflict(t) is False

    fate = manager.start_download(
        'Fate/stay night',
        1,
        'https://anime.example/fate/1',
        'Fate/stay night - Episode 1 [VOSTFR].mp4',
        version='VOSTFR',
    )
    assert 'Fate_stay night - Episode 1 [VOSTFR].mp4' == fate.fileName


@pytest.mark.parametrize('plex', [False, True])
def test_multi_season_distinct_urls_do_not_collide_and_replace_conflicted_paused_tasks(isolated, monkeypatch, plex):
    monkeypatch.setattr(manager, 'plex_organization', plex)
    tasks = manager.start_batch_download(
        'Black Clover',
        [
            {
                'number': 1,
                'url': 'https://on.jetanimes.com/episodes/black-clover-saison-1-episode-1/',
                'version': 'VOSTFR',
                'fileName': 'Black Clover - S01E01 [VOSTFR].mp4',
            },
            {
                'number': 1,
                'url': 'https://on.jetanimes.com/episodes/black-clover-saison-2-episode-1/',
                'version': 'VOSTFR',
                'fileName': 'Black Clover - S02E01 [VOSTFR].mp4',
            },
        ],
        source='eu.kanade.tachiyomi.animeextension.fr.jetanime',
    )
    assert len(tasks) == 2
    assert tasks[0].savePath != tasks[1].savePath
    assert not manager._has_destination_conflict(tasks[0])
    assert not manager._has_destination_conflict(tasks[1])

    # Unhinted same-episode distinct URLs still get unique paths
    unhinted = manager.start_batch_download(
        'The Ramparts of Ice',
        [
            {
                'number': 1,
                'url': 'https://on.jetanimes.com/episodes/ramparts-1/',
                'version': 'VOSTFR',
                'fileName': 'The Ramparts of Ice - Episode 1 [VOSTFR].mp4',
            },
            {
                'number': 1,
                'url': 'https://on.jetanimes.com/episodes/ramparts-2/',
                'version': 'VOSTFR',
                'fileName': 'The Ramparts of Ice - Episode 1 [VOSTFR].mp4',
            },
        ],
        source='eu.kanade.tachiyomi.animeextension.fr.jetanime',
    )
    assert len(unhinted) == 2
    assert unhinted[0].savePath != unhinted[1].savePath

    # Seed legacy conflicted PAUSED tasks and re-launch one from anime page
    shared_path = str(manager.download_dir) + '/Legacy/legacy.mp4'
    legacy_a = DownloadTask(
        animeName='Legacy',
        episodeNumber=1,
        savePath=shared_path,
        fileName='legacy.mp4',
        downloadPageUrl='https://source.example/ep/1',
        fileUrl='https://source.example/ep/1',
        source='eu.kanade.tachiyomi.animeextension.fr.jetanime',
        version='VOSTFR',
        status=DownloadStatus.PAUSED,
    )
    legacy_b = DownloadTask(
        animeName='Legacy',
        episodeNumber=1,
        savePath=shared_path,
        fileName='legacy.mp4',
        downloadPageUrl='https://source.example/ep/2',
        fileUrl='https://source.example/ep/2',
        source='eu.kanade.tachiyomi.animeextension.fr.jetanime',
        version='VOSTFR',
        status=DownloadStatus.PAUSED,
    )
    manager.tasks[legacy_a.id] = legacy_a
    manager.tasks[legacy_b.id] = legacy_b
    relaunched = manager.start_download(
        'Legacy',
        1,
        'https://source.example/ep/1',
        'Legacy - Episode 1 [VOSTFR].mp4',
        source='eu.kanade.tachiyomi.animeextension.fr.jetanime',
        version='VOSTFR',
    )
    assert relaunched.id != legacy_a.id
    assert legacy_a.status == DownloadStatus.CANCELLED
    assert relaunched.status == DownloadStatus.PENDING
    assert not manager._has_destination_conflict(relaunched)


@pytest.mark.asyncio
async def test_jetanime_dooplay_deduplicates_episodes_excludes_sidebar_and_preserves_seasons(monkeypatch):
    recipe = SourceRecipe(
        pkg='eu.kanade.tachiyomi.animeextension.fr.jetanime',
        base_url='https://on.jetanimes.com',
        episode_list_selector="ul.episodios > li, #seasons .episodiotitle a, .episodiotitle a, a[href*='/episodes/']",
    )
    source = AniyomiContainerSource(recipe)
    assert "a[href*='/episodes/']" not in source.recipe.episode_list_selector

    html = """
    <html><body>
      <h1 class="title">The Ramparts of Ice</h1>
      <div id="seasons">
        <div class="se-c">
          <div class="se-a">
            <ul class="episodios">
              <li>
                <div class="imagen"><img src="https://on.jetanimes.com/img/s1e2.jpg"></div>
                <div class="numerando">1 - 2</div>
                <div class="episodiotitle"><a href="https://on.jetanimes.com/episodes/ramparts-1x2/">LE SERRURIER</a><span class="date">Apr. 09, 2026</span></div>
              </li>
              <li>
                <div class="imagen"><img src="https://on.jetanimes.com/img/s1e1.jpg"></div>
                <div class="numerando">1 - 1</div>
                <div class="episodiotitle"><a href="https://on.jetanimes.com/episodes/ramparts-1x1/">Épisode 1 NOUVEAU</a><span class="date">Apr. 02, 2026</span></div>
              </li>
            </ul>
          </div>
        </div>
        <div class="se-c">
          <div class="se-a">
            <ul class="episodios">
              <li>
                <div class="imagen"><img src="https://on.jetanimes.com/img/s2e1.jpg"></div>
                <div class="numerando">2 - 1</div>
                <div class="episodiotitle"><a href="https://on.jetanimes.com/episodes/ramparts-2x1/">Épisode 1 NOUVEAU</a><span class="date">Oct. 01, 2026</span></div>
              </li>
            </ul>
          </div>
        </div>
      </div>
      <aside>
        <h3>DERNIERS EPISODES</h3>
        <a href="https://on.jetanimes.com/episodes/tokyo-revengers-saison-4-ep-1/">Tokyo Revengers</a>
      </aside>
    </body></html>
    """
    monkeypatch.setattr('animelab.services.aniyomi_container.is_safe_url', lambda _url: True)
    monkeypatch.setattr(source, '_fetch_html', AsyncMock(return_value=html))
    detail = await source.get_anime_detail('https://on.jetanimes.com/serie/the-ramparts-of-ice/')
    assert detail is not None
    assert len(detail.episodes) == 3
    assert [ep.downloadPageUrl for ep in detail.episodes] == [
        'https://on.jetanimes.com/episodes/ramparts-1x1/',
        'https://on.jetanimes.com/episodes/ramparts-1x2/',
        'https://on.jetanimes.com/episodes/ramparts-2x1/',
    ]
    assert [ep.nativeMetadata.get('season') for ep in detail.episodes] == [1, 1, 2]
    assert [ep.number for ep in detail.episodes] == [1, 2, 1]
    assert detail.episodes[0].title == 'S01E01 — Épisode 1 NOUVEAU'
    assert detail.episodes[1].title == 'S01E02 — LE SERRURIER'
    assert detail.episodes[2].title == 'S02E01 — Épisode 1 NOUVEAU'
