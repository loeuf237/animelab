import json
from unittest.mock import AsyncMock, patch
import pytest
from animan.services.aniyomi_container import AniyomiContainerSource
from animan.services.aniyomi_dex_parser import SourceRecipe

@pytest.mark.asyncio
async def test_json_recipe_search_detail_sources():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.en.hanime",
        name="Hanime",
        base_url="https://hanime.tv",
    )
    container = AniyomiContainerSource(recipe)

    fake_catalog = [
        {
            "id": 101,
            "name": "Overflow Season 1",
            "slug": "overflow-season-1",
            "poster_url": "https://hanime-cdn.com/images/posters/overflow.jpg",
            "description": "<p>Super anime</p>",
            "tags": ["romance", "comedy"],
            "created_at_unix": 1700000000,
        },
        {
            "id": 102,
            "name": "Another Title",
            "slug": "another-title",
            "poster_url": "https://hanime-cdn.com/images/posters/another.jpg",
            "description": "Another description",
            "tags": ["action"],
            "created_at_unix": 1600000000,
        },
    ]

    with patch.object(container, "_fetch_html", new_callable=AsyncMock, return_value=json.dumps(fake_catalog)):

        # 1. Search
        search_res = await container.search_anime("overflow")
        assert len(search_res) == 1
        assert search_res[0].title == "Overflow Season 1"
        assert search_res[0].url == "https://hanime.tv/videos/hentai/overflow-season-1"

        # 2. Latest
        latest_res = await container.get_latest_releases()
        assert len(latest_res) == 2
        assert latest_res[0].title == "Overflow Season 1"

        # 3. Detail
        detail = await container.get_anime_detail("https://hanime.tv/videos/hentai/overflow-season-1")
        assert detail is not None
        assert detail.title == "Overflow Season 1"
        assert detail.synopsis == "Super anime"
        assert len(detail.episodes) == 1

        # 4. Sources
        fake_api_manifest = {
            "videos_manifest": {
                "servers": [
                    {
                        "name": "Server 1",
                        "streams": [
                            {"height": "1080", "url": "https://cdn.hanime.tv/1080p/manifest.m3u8"},
                            {"height": "720", "url": "https://cdn.hanime.tv/720p/manifest.m3u8"},
                        ]
                    }
                ]
            }
        }
        with patch.object(container, "_fetch_html", new_callable=AsyncMock, return_value=json.dumps(fake_api_manifest)):
            sources = await container.get_episode_sources("https://hanime.tv/videos/hentai/overflow-season-1")
            assert len(sources) == 2
            assert sources[0]["server"] == "Server 1"
            assert sources[0]["quality"] == "1080p"

@pytest.mark.asyncio
async def test_episode_recipe_js_array_extraction():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.animesama",
        name="Anime-Sama",
        base_url="https://anime-sama.fr",
    )
    container = AniyomiContainerSource(recipe)

    fake_detail_html = '''
    <html>
        <body>
            <h1 id="titreAnime">Solo Leveling</h1>
            <img id="coverAnime" src="/images/solo_leveling.jpg" />
            <p id="synopsis">L'histoire du plus faible des chasseurs devenant le plus fort.</p>
            <script>
                var eps1 = ['https://video.sibnet.ru/shell.php?videoid=111', 'https://video.sibnet.ru/shell.php?videoid=222'];
                var eps2 = ['https://sendvid.com/ep1', 'https://sendvid.com/ep2'];
            </script>
        </body>
    </html>
    '''

    with patch.object(container, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = fake_detail_html

        detail = await container.get_anime_detail("https://anime-sama.fr/catalogue/solo-leveling/saison1/vostfr/")
        assert detail is not None
        assert detail.title == "Solo Leveling"
        assert len(detail.episodes) == 2
        assert detail.episodes[0].number == 1
        assert detail.episodes[0].playerUrl.startswith("https://video.sibnet.ru/shell.php?videoid=111")
        assert detail.episodes[1].number == 2
        assert detail.episodes[1].playerUrl.startswith("https://video.sibnet.ru/shell.php?videoid=222")

    # Test sources d'un épisode direct
    sources = await container.get_episode_sources("https://video.sibnet.ru/shell.php?videoid=111")
    assert len(sources) == 1
    assert sources[0]["server"] == "Sibnet"
    assert sources[0]["url"].startswith("https://video.sibnet.ru/shell.php?videoid=111")


@pytest.mark.asyncio
async def test_serialized_data_recipe_runs_for_unknown_package_without_dispatch():
    recipe = SourceRecipe(pkg='independent.publisher', base_url='https://independent.example', runtime={
        'catalogue': {'url': '{base}/catalogue.json', 'kind': 'flat',
            'entry_url': '{base}/series/{slug}', 'version': 'VO',
            'popular_order': 'views', 'latest_order': 'created_at_unix'},
    })
    source = AniyomiContainerSource(SourceRecipe.from_dict(json.loads(json.dumps(recipe.to_dict()))))
    source._fetch_html = AsyncMock(return_value=json.dumps([{
        'id': 1, 'title': 'Example', 'slug': 'example', 'genres': ['Adventure'], 'poster': '',
    }]))
    results = await source.search_anime('Example')
    assert results[0].url == 'https://independent.example/series/example'
    detail = await source.get_anime_detail(results[0].url)
    assert detail.title == 'Example'
    assert detail.genres == ['Adventure']
    assert source._fetch_html.await_count == 1


@pytest.mark.asyncio
async def test_literal_arrays_preserve_missing_player_positions():
    source = AniyomiContainerSource(SourceRecipe(pkg='independent.arrays', base_url='https://independent.example', runtime={
        'episodes': {'kind': 'js_arrays', 'array_pattern': r'(?:var|let|const)\s+(eps\w*)\s*=\s*\[([^\]]*)\]'},
    }))
    source._fetch_html = AsyncMock(return_value='''<h1>Example</h1><script>
        var eps1 = ['', 'https://sendvid.com/two'];
        var eps2 = ['https://sendvid.com/one', null];
    </script>''')
    detail = await source.get_anime_detail('https://independent.example/show')
    assert [(e.number, e.playerUrl) for e in detail.episodes] == [
        (1, 'https://sendvid.com/one'), (2, 'https://sendvid.com/two'),
    ]
