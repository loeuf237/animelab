import pytest
from unittest.mock import patch, AsyncMock, MagicMock
from fastapi.testclient import TestClient

from run import app
from animelab.models.anime import AnimeResult
from animelab.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.extension_service import extension_service


@pytest.fixture
def client():
    with TestClient(app) as c:
        yield c


def test_animesama_heuristics_and_selector_deduction():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.animesama",
        base_url="https://anime-sama.to",
        raw_strings=[
            "#containerAjoutsAnimes > div",
            "#list_catalog > div a",
            "/catalogue/",
            "search",
            "addQueryParameter",
        ]
    )
    AniyomiDexParser._fill_heuristics(recipe)

    assert "#list_catalog > div" in recipe.search_selector
    assert "catalog-card" in recipe.search_selector
    assert recipe.search_request_path == "/catalogue/?search={query}"
    assert recipe.search_query_param == "search"
    assert "card-title" in recipe.item_title_selector or "img[alt]" in recipe.item_title_selector


@pytest.mark.asyncio
async def test_animesama_html_search_parsing():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.animesama",
        name="Anime-Sama",
        base_url="https://anime-sama.to",
        search_request_path="/catalogue/?search={query}",
        search_selector="#list_catalog > div, #list_catalog > div a, .catalog-card",
        item_title_selector=".card-title, img[alt]",
        item_thumb_selector="img.card-image, img[src]",
        item_link_selector="a[href]",
    )
    source = AniyomiContainerSource(recipe)

    mock_html = """
    <html>
      <body>
        <div id="list_catalog">
          <div class="shrink-0 catalog-card card-base">
            <a href="https://anime-sama.to/catalogue/naruto/">
              <div class="card-image-container">
                <img alt="Naruto" class="card-image" src="https://cdn.example.com/naruto.webp" />
              </div>
            </a>
          </div>
          <div class="shrink-0 catalog-card card-base">
            <a href="https://anime-sama.to/catalogue/boruto/">
              <div class="card-image-container">
                <img alt="Boruto" class="card-image" src="https://cdn.example.com/boruto.webp" />
              </div>
            </a>
          </div>
        </div>
      </body>
    </html>
    """

    with patch.object(source, "_fetch_html", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = mock_html
        results = await source.search_anime("naruto")

    assert len(results) == 2
    assert results[0].title == "Naruto"
    assert results[0].url == "https://anime-sama.to/catalogue/naruto/"
    assert results[1].title == "Boruto"


@pytest.mark.asyncio
async def test_animesama_detail_episodes_parsing():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.fr.animesama",
        name="Anime-Sama",
        base_url="https://anime-sama.to",
    )
    source = AniyomiContainerSource(recipe)

    mock_detail_html = """
    <html>
      <head><title>Naruto :: Anime-Sama</title></head>
      <body>
        <h1 id="titreOeuvre">Naruto</h1>
        <script>
          panneauAnime("nom", "url");
          panneauAnime("Saison 1", "saison1/vostfr");
        </script>
      </body>
    </html>
    """

    mock_episodes_js = """
    var eps1 = ['https://player.example.com/ep1', 'https://player.example.com/ep2'];
    """

    async def mock_fetch_side_effect(url, **kwargs):
        if url.endswith(".js"):
            return mock_episodes_js
        return mock_detail_html

    with patch.object(source, "_fetch_html", side_effect=mock_fetch_side_effect):
        detail = await source.get_anime_detail("https://anime-sama.to/catalogue/naruto/")

    assert detail is not None
    assert detail.title == "Naruto"
    assert len(detail.episodes) == 2
    assert detail.episodes[0].number == 1
    assert detail.episodes[0].playerUrl == "https://player.example.com/ep1"
    assert detail.episodes[1].number == 2


def test_api_search_includes_extensions(client, monkeypatch):
    from animelab.routers import anime
    for source in (anime.scraping_service, anime.voiranime_service, anime.animepahe_service):
        monkeypatch.setattr(source, "search_anime", AsyncMock(return_value=[]))
    mock_source = MagicMock()
    mock_source.pkg = "eu.kanade.tachiyomi.animeextension.fr.mockext"
    mock_source.name = "MockExtension"
    mock_source.search_anime = AsyncMock(return_value=[
        AnimeResult(
            id="mock1",
            title="Mock Anime Title",
            url="https://mock.example.com/anime/1",
            source="eu.kanade.tachiyomi.animeextension.fr.mockext",
        )
    ])

    with patch.object(extension_service, "get_enabled_container_sources", return_value=[mock_source]):
        with patch.object(extension_service, "get_container_source_by_id", return_value=mock_source):
            # 1. Targeted search on extension
            resp_target = client.get("/api/search?q=test&source=eu.kanade.tachiyomi.animeextension.fr.mockext")
            assert resp_target.status_code == 200
            data_target = resp_target.json()
            assert len(data_target) == 1
            assert data_target[0]["title"] == "Mock Anime Title"

            # 2. Multi-source search with source=all includes the extension
            resp_all = client.get("/api/search?q=test&source=all")
            assert resp_all.status_code == 200
            data_all = resp_all.json()
            assert any(item.get("title") == "Mock Anime Title" for item in data_all)
