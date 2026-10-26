import json
import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from run import app
from animelab.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.extension_service import ExtensionService

@pytest.fixture(scope="module")
def client():
    with TestClient(app, headers={"Accept-Language": "fr"}) as c:
        yield c

def test_dex_parser_heuristics():
    """Vérifie la génération des heuristiques de scraping quand aucun APK n'est fourni."""
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.testsource",
        base_url="https://testsource.example.com"
    )
    AniyomiDexParser._fill_heuristics(recipe)

    assert recipe.search_request_path == "/?s={query}"
    assert "title" in recipe.item_title_selector
    assert "a[href]" in recipe.item_link_selector
    assert "img" in recipe.item_thumb_selector

@pytest.mark.asyncio
async def test_container_source_parsing():
    """Vérifie le parsing HTML dans le conteneur Aniyomi."""
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.testsource",
        name="TestSource",
        base_url="https://testsource.example.com",
        search_request_path="/search?q={query}",
        search_selector=".anime-entry",
        item_title_selector=".title",
        item_link_selector="a",
        item_thumb_selector="img",
        episode_list_selector=".episodes-list a",
    )
    source = AniyomiContainerSource(recipe)

    sample_search_html = """
    <html>
        <body>
            <div class="anime-entry">
                <a href="/anime/naruto-shippuden">
                    <img src="https://testsource.example.com/covers/naruto.jpg" />
                    <span class="title">Naruto Shippuden</span>
                </a>
            </div>
            <div class="anime-entry">
                <a href="/anime/bleach">
                    <img src="/covers/bleach.jpg" />
                    <span class="title">Bleach</span>
                </a>
            </div>
        </body>
    </html>
    """
    with patch.object(source, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = sample_search_html
        results = await source.search_anime("naruto")
        assert len(results) == 2
        assert results[0].title == "Naruto Shippuden"
        assert results[0].url == "https://testsource.example.com/anime/naruto-shippuden"
        assert results[0].imageUrl == "https://testsource.example.com/covers/naruto.jpg"
        assert results[1].title == "Bleach"
        assert results[1].url == "https://testsource.example.com/anime/bleach"

    sample_detail_html = """
    <html>
        <head><title>Naruto Shippuden Details</title></head>
        <body>
            <h1 class="title">Naruto Shippuden</h1>
            <div class="synopsis">Un jeune ninja en quête de reconnaissance...</div>
            <div class="episodes-list">
                <a href="/watch/naruto-ep-1">Épisode 1</a>
                <a href="/watch/naruto-ep-2">Épisode 2</a>
            </div>
        </body>
    </html>
    """
    with patch("animelab.services.aniyomi_container.is_safe_url", return_value=True):
        with patch.object(source, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
            mock_fetch.return_value = sample_detail_html
            detail = await source.get_anime_detail("https://testsource.example.com/anime/naruto-shippuden")
            assert detail is not None
            assert detail.title == "Naruto Shippuden"
            assert "jeune ninja" in detail.synopsis
            assert len(detail.episodes) == 2
            assert detail.episodes[0].number == 1
            assert detail.episodes[0].playerUrl == "https://testsource.example.com/watch/naruto-ep-1"
            assert detail.episodes[1].number == 2

@pytest.mark.asyncio
async def test_extension_service_business_rules(tmp_path):
    """
    Vérifie les deux règles d'or demandées par l'utilisateur:
    1. Règle du dernier magasin ajouté (seules ses sources sont visibles).
    2. Toutes les sources importées sont désactivées par défaut (is_enabled = 0).
    """
    db_file = str(tmp_path / "test_extensions.sqlite3")
    service = ExtensionService(db_path=db_file)

    # Dépôt 1 : 2 extensions
    repo1_data = [
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.fr.repo1_alpha",
            "name": "Repo1 Alpha",
            "lang": "fr",
            "version": "1.0",
            "apk": "repo1_alpha.apk",
            "sources": [{"baseUrl": "https://alpha.repo1.com"}],
        },
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.fr.repo1_beta",
            "name": "Repo1 Beta",
            "lang": "fr",
            "version": "1.0",
            "apk": "repo1_beta.apk",
            "sources": [{"baseUrl": "https://beta.repo1.com"}],
        }
    ]

    mock_resp1 = MagicMock()
    mock_resp1.status_code = 200
    mock_resp1.json.return_value = repo1_data

    with patch("animelab.services.source_http.AsyncSourceClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp1
        res1 = await service.import_repository("https://example.com/repo1/index.min.json")
        assert res1["success"] is True
        assert res1["count"] == 2

    # RÈGLE 2: Par défaut, toutes les sources importées sont désactivées
    visible1 = service.get_visible_extensions()
    assert len(visible1) == 2
    for ext in visible1:
        assert ext["is_enabled"] == 0, "Toutes les sources importées doivent être désactivées par défaut"

    assert len(service.get_enabled_container_sources()) == 0

    # RÈGLE 1: Importation d'un second dépôt -> Il devient le SEUL magasin actif visible
    repo2_data = [
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.en.repo2_gamma",
            "name": "Repo2 Gamma",
            "lang": "en",
            "version": "2.0",
            "apk": "repo2_gamma.apk",
            "sources": [{"baseUrl": "https://gamma.repo2.com"}],
        }
    ]

    mock_resp2 = MagicMock()
    mock_resp2.status_code = 200
    mock_resp2.json.return_value = repo2_data

    with patch("animelab.services.source_http.AsyncSourceClient.get", new_callable=AsyncMock) as mock_get:
        mock_get.return_value = mock_resp2
        res2 = await service.import_repository("https://example.com/repo2/index.min.json")
        assert res2["success"] is True
        assert res2["count"] == 1

    # Vérification que SEUL le dernier magasin ajouté (repo2) est visible
    visible2 = service.get_visible_extensions()
    assert len(visible2) == 1
    assert visible2[0]["name"] == "Repo2 Gamma"
    assert visible2[0]["is_enabled"] == 0

    # Activation manuelle d'une extension par l'utilisateur
    gamma_id = visible2[0]["id"]
    with patch("animelab.services.extension_service.is_safe_url", return_value=True), patch.object(service, "_compile_extension_recipe", new_callable=AsyncMock) as mock_compile:
        mock_compile.return_value = SourceRecipe(
            pkg="eu.kanade.tachiyomi.animeextension.en.repo2_gamma",
            name="Repo2 Gamma",
            base_url="https://gamma.repo2.com"
        ).to_dict()

        toggle_res = await service.toggle_extension(gamma_id, True)
        assert toggle_res["success"] is True
        assert toggle_res["is_enabled"] is True

    # Vérification en mémoire et whitelist SSRF
    enabled_sources = service.get_enabled_container_sources()
    assert len(enabled_sources) == 1
    assert enabled_sources[0].pkg == "eu.kanade.tachiyomi.animeextension.en.repo2_gamma"
    assert "gamma.repo2.com" in service.get_allowed_domains()

    # Désactivation
    toggle_off = await service.toggle_extension(gamma_id, False)
    assert toggle_off["is_enabled"] is False
    assert len(service.get_enabled_container_sources()) == 0
    assert "gamma.repo2.com" not in service.get_allowed_domains()

def test_api_extensions_routes(client):
    """Teste les routes API du routeur extensions."""
    # 1. Page HTML /extensions
    resp = client.get('/extensions', follow_redirects=False)
    assert resp.status_code == 303
    assert resp.headers['location'] == '/app/extensions'

    # 2. Liste des extensions
    resp_list = client.get("/api/extensions/list")
    assert resp_list.status_code == 200
    data = resp_list.json()
    assert "extensions" in data
    assert isinstance(data["extensions"], list)

@pytest.mark.asyncio
async def test_hanime_search_and_detail():
    """Vérifie la recherche et les détails pour l'extension Hanime.tv via le catalogue API."""
    from animelab.services.aniyomi_container import AniyomiContainerSource
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.en.hanime",
        name="Hanime",
        base_url="https://hanime.tv"
    )
    source = AniyomiContainerSource(recipe)

    mock_catalog = [
        {
            "id": 1234,
            "name": "Overflow Season 1",
            "slug": "overflow-season-1",
            "search_titles": "Overflow Season 1 hentai",
            "poster_url": "https://hanime-cdn.com/images/posters/overflow.jpg",
            "description": "<p>A nice bath experience.</p>",
            "tags": ["romance", "comedy"],
            "created_at_unix": 1600000000
        },
        {
            "id": 5678,
            "name": "Another Show",
            "slug": "another-show",
            "search_titles": "Another Show hentai",
            "poster_url": "https://hanime-cdn.com/images/posters/another.jpg",
            "description": "Another synopsis",
            "tags": ["action"],
            "created_at_unix": 1500000000
        }
    ]

    with patch.object(source, "_fetch_html", new_callable=AsyncMock, return_value=json.dumps(mock_catalog)):

        # Recherche
        results = await source.search_anime("overflow")
        assert len(results) == 1
        assert results[0].title == "Overflow Season 1"
        assert results[0].url == "https://hanime.tv/videos/hentai/overflow-season-1"
        assert results[0].imageUrl == "https://hanime-cdn.com/images/posters/overflow.jpg"
        assert results[0].source == "eu.kanade.tachiyomi.animeextension.en.hanime"

        # Dernières sorties
        latest = await source.get_latest_releases()
        assert len(latest) == 2
        assert latest[0].title == "Overflow Season 1"

        # Détails
        detail = await source.get_anime_detail("https://hanime.tv/videos/hentai/overflow-season-1")
        assert detail is not None
        assert detail.title == "Overflow Season 1"
        assert detail.synopsis == "A nice bath experience."
        assert len(detail.episodes) == 1
        assert detail.episodes[0].downloadPageUrl == "https://hanime.tv/videos/hentai/overflow-season-1"

@pytest.mark.asyncio
async def test_resolve_imported_video_stream():
    """Vérifie la résolution de flux directs pour les hébergeurs embed vidéo (Vidmoly, Sibnet)."""
    from animelab.services.download_manager import download_manager

    # Test Vidmoly/Ansembed
    mock_html_vidmoly = """
    <html><body><script>
    var player = jwplayer("vplayer").setup({
        sources: [{ file: "https://cdn.example.com/hls/master.m3u8" }]
    });
    </script></body></html>
    """
    with patch("animelab.services.extractors.base.source_http.async_client") as mock_client_ctx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html_vidmoly
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_ctx.return_value.__aenter__.return_value = mock_client

        with patch.object(download_manager, "estimate_hls_size", new_callable=AsyncMock) as mock_est:
            mock_est.return_value = 150_000_000
            res = await download_manager.resolve_imported_video_stream("https://ansembed.net/embed-test.html")
            assert res is not None
            assert res["videoUrl"] == "https://cdn.example.com/hls/master.m3u8"
            assert res["serverType"] == "Vidmoly"
            assert res["size"] == 150_000_000

    # Test Sibnet
    mock_html_sibnet = """
    <html><body>
    <script>
    player.src([ { type: "video/mp4", src: "/v/abcdef12345/123456.mp4" } ]);
    </script>
    </body></html>
    """
    with patch("animelab.services.extractors.base.source_http.async_client") as mock_client_ctx:
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = mock_html_sibnet
        mock_resp.headers = {}
        mock_client = AsyncMock()
        mock_client.get.return_value = mock_resp
        mock_client_ctx.return_value.__aenter__.return_value = mock_client

        with patch.object(download_manager, "get_remote_file_size", new_callable=AsyncMock) as mock_sz:
            mock_sz.return_value = 250_000_000
            res = await download_manager.resolve_imported_video_stream("https://video.sibnet.ru/shell.php?videoid=123456")
            assert res is not None
            assert res["videoUrl"] == "https://video.sibnet.ru/v/abcdef12345/123456.mp4"
            assert res["serverType"] == "Sibnet"
            assert res["size"] == 250_000_000

def test_download_task_source_propagation():
    """Vérifie la propagation du champ source dans start_download et start_batch_download."""
    from animelab.services.download_manager import download_manager

    with patch("animelab.services.download_manager.library_service.save_task"), \
         patch("animelab.services.download_manager.library_service.save_tasks_batch"), \
         patch.object(download_manager, "check_existing_file", return_value=None), \
         patch.object(download_manager, "_trigger_process_queue"):

        task = download_manager.start_download(
            anime_name="Custom Anime",
            episode_number=1,
            download_page_url="https://ansembed.net/embed-123.html",
            file_name="Custom Anime - Episode 1.mp4",
            source="eu.kanade.tachiyomi.animeextension.fr.animesama"
        )
        assert task.source == "eu.kanade.tachiyomi.animeextension.fr.animesama"
        download_manager.tasks.pop(task.id, None)
        if task.id in download_manager.task_order:
            download_manager.task_order.remove(task.id)

        batch_tasks = download_manager.start_batch_download(
            anime_name="Batch Anime",
            episodes=[
                {"number": 1, "url": "https://video.sibnet.ru/shell.php?videoid=999", "fileName": "Batch - 1.mp4"}
            ],
            source="eu.kanade.tachiyomi.animeextension.fr.animesama"
        )
        assert len(batch_tasks) == 1
        assert batch_tasks[0].source == "eu.kanade.tachiyomi.animeextension.fr.animesama"
        for bt in batch_tasks:
            download_manager.tasks.pop(bt.id, None)
            if bt.id in download_manager.task_order:
                download_manager.task_order.remove(bt.id)


def test_dex_parser_popular_tags_and_custom_feeds():
    """Vérifie que chaque profil d'extension Aniyomi expose ses recettes de populaires, tags, groupes et flux dédiés."""
    pkgs = [
        "eu.kanade.tachiyomi.animeextension.fr.animesama",
        "eu.kanade.tachiyomi.animeextension.fr.animevostfr",
        "eu.kanade.tachiyomi.animeextension.fr.anisama",
        "eu.kanade.tachiyomi.animeextension.fr.franime",
        "eu.kanade.tachiyomi.animeextension.fr.jetanime",
        "eu.kanade.tachiyomi.animeextension.fr.voiranime",
        "eu.kanade.tachiyomi.animeextension.fr.vostfree",
        "eu.kanade.tachiyomi.animeextension.de.aniworld",
        "eu.kanade.tachiyomi.animeextension.en.hanime",
        "eu.kanade.tachiyomi.animeextension.en.hentaihaven",
    ]
    for pkg in pkgs:
        recipe = SourceRecipe(pkg=pkg)
        AniyomiDexParser._fill_heuristics(recipe)
        assert recipe.base_url.startswith("https://")
        assert recipe.popular_request_path
        assert recipe.popular_selector
        assert recipe.latest_request_path
        assert len(recipe.filter_tags) > 0
        assert len(recipe.custom_feeds) > 0

    animesama = SourceRecipe(pkg="eu.kanade.tachiyomi.animeextension.fr.animesama")
    AniyomiDexParser._fill_heuristics(animesama)
    feed_ids = {f["id"] for f in animesama.custom_feeds}
    assert {"pepites", "classiques", "films"} <= feed_ids
    assert len(animesama.filter_groups) == 2

    vostfree = SourceRecipe(pkg="eu.kanade.tachiyomi.animeextension.fr.vostfree")
    AniyomiDexParser._fill_heuristics(vostfree)
    vf_feeds = {f["id"] for f in vostfree.custom_feeds}
    assert {"animes_vostfr", "animes_vf", "films"} <= vf_feeds


@pytest.mark.asyncio
async def test_extension_update_detection_and_user_triggered_upgrade(tmp_path, extension_apk):
    """Vérifie la détection de nouvelle version sans écrasement automatique et la mise à jour au souhait de l'utilisateur."""
    db_file = str(tmp_path / "test_updates.sqlite3")
    service = ExtensionService(db_path=db_file)

    repo_v1 = [
        {
            "pkg": "eu.kanade.tachiyomi.animeextension.fr.animesama",
            "name": "Aniyomi: Anime-Sama",
            "lang": "fr",
            "version": "1.4.29",
            "apk": "animesama-1.4.29.apk",
            "sources": [{"baseUrl": "https://anime-sama.to"}],
        }
    ]
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.content = extension_apk('https://anime-sama.to')
    mock_resp.json.side_effect = lambda: repo_v1

    with patch("animelab.services.source_http.AsyncSourceClient.get", new_callable=AsyncMock) as mock_get, \
         patch("animelab.services.extension_service.is_safe_url", return_value=True):
        mock_get.return_value = mock_resp
        await service.import_repository("https://example.com/repo/index.min.json")
        ext = service.get_visible_extensions()[0]
        await service.toggle_extension(ext["id"], True)

        installed_ext = service.get_visible_extensions()[0]
        assert installed_ext["is_installed"] is True
        assert installed_ext["installed_version"] == "1.4.29"
        assert installed_ext["available_version"] == "1.4.29"
        assert installed_ext["has_update"] is False
        assert installed_ext["capabilities_summary"]["popular"] is True
        assert installed_ext["capabilities_summary"]["tags_count"] > 50

        # Une nouvelle version 1.4.30 est publiée sur le dépôt
        repo_v1[0] = {
            **repo_v1[0],
            "version": "1.4.30",
            "apk": "animesama-1.4.30.apk",
        }
        check_res = await service.check_updates()
        assert check_res["success"] is True
        assert check_res["count"] == 1
        assert check_res["updates"][0]["installed_version"] == "1.4.29"
        assert check_res["updates"][0]["available_version"] == "1.4.30"

        # Tant que l'utilisateur n'a pas cliqué sur "Mettre à jour", installed_version reste 1.4.29
        pending_ext = service.get_visible_extensions()[0]
        assert pending_ext["installed_version"] == "1.4.29"
        assert pending_ext["available_version"] == "1.4.30"
        assert pending_ext["has_update"] is True

        # L'utilisateur déclenche la mise à jour à son souhait
        upd_res = await service.update_extension(ext["id"])
        assert upd_res["success"] is True
        assert upd_res["installed_version"] == "1.4.30"
        assert upd_res["has_update"] is False

        updated_ext = service.get_visible_extensions()[0]
        assert updated_ext["installed_version"] == "1.4.30"
        assert updated_ext["available_version"] == "1.4.30"
        assert updated_ext["has_update"] is False

