import pytest
from unittest.mock import AsyncMock, patch
from animelab.models.anime import AnimeResult, AnimeDetail, Episode
from animelab.services.scraping_service import scraping_service

def test_unify_animes_duplicates():
    # Deux cartes pour le même anime : une VF et une VOSTFR
    card_vf = AnimeResult(
        id="101",
        title="Solo Leveling (VF)",
        imageUrl="https://w16.french-manga.net/uploads/poster1.jpg",
        url="https://w16.french-manga.net/101-solo-leveling-vf.html",
        version="VF",
        type="Anime",
        episodeInfo="12 épisodes",
        source="french-manga"
    )
    card_vostfr = AnimeResult(
        id="102",
        title="Solo Leveling (VOSTFR)",
        imageUrl="https://w16.french-manga.net/uploads/poster2.jpg",
        url="https://w16.french-manga.net/102-solo-leveling-vostfr.html",
        version="VOSTFR",
        type="Anime",
        episodeInfo="12 épisodes",
        source="french-manga"
    )
    card_standalone = AnimeResult(
        id="201",
        title="Frieren (VOSTFR)",
        imageUrl="https://w16.french-manga.net/uploads/frieren.jpg",
        url="https://w16.french-manga.net/201-frieren-vostfr.html",
        version="VOSTFR",
        type="Anime",
        episodeInfo="28 épisodes",
        source="french-manga"
    )

    results = [card_vf, card_vostfr, card_standalone]
    unified = scraping_service.unify_animes(results)

    # Doit résulter en 2 animés : Solo Leveling unifié et Frieren
    assert len(unified) == 2

    solo = next(x for x in unified if "Solo Leveling" in x.title)
    assert "VF" in solo.title and "VOSTFR" in solo.title
    assert solo.id == "101,102"
    assert "merged_ids=101,102" in solo.url
    assert "VF" in solo.version and "VOSTFR" in solo.version

    frieren = next(x for x in unified if "Frieren" in x.title)
    assert frieren.id == "201"
    assert frieren.url == "https://w16.french-manga.net/201-frieren-vostfr.html"

@pytest.mark.asyncio
async def test_get_anime_detail_multi_id_merge():
    # Simule get_anime_detail avec URL contenant merged_ids
    anime_url = "https://w16.french-manga.net/101-test.html?merged_ids=101,102"

    html_page = """
    <html>
      <head><title>Test Anime | French Manga</title></head>
      <body>
        <h1 class="full-title">Test Anime</h1>
        <div class="fdesc">Synopsis de test de l'anime.</div>
      </body>
    </html>
    """

    api_json_101 = """{
        "vf": {
            "1": {"vidzy": "https://vidzy.live/e/vf1"},
            "2": {"vidzy": "https://vidzy.live/e/vf2"}
        }
    }"""

    api_json_102 = """{
        "vostfr": {
            "1": {"vidzy": "https://vidzy.live/e/vostfr1"},
            "2": {"vidzy": "https://vidzy.live/e/vostfr2"}
        }
    }"""

    class MockResp:
        def __init__(self, status_code, text):
            self.status_code = status_code
            self.text = text

    class MockAsyncClient:
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            pass
        async def get(self, url, headers=None):
            if "manga_episodes_api.php?id=101" in url:
                return MockResp(200, api_json_101)
            elif "manga_episodes_api.php?id=102" in url:
                return MockResp(200, api_json_102)
            elif "101-test.html" in url:
                return MockResp(200, html_page)
            return MockResp(404, "")

    with patch.object(scraping_service, "_get_async_client", return_value=MockAsyncClient()):
        detail = await scraping_service.get_anime_detail(anime_url)

        assert detail is not None
        assert detail.title == "Test Anime"
        assert detail.version == "VF + VOSTFR"
        # Doit contenir 4 épisodes (2 VF + 2 VOSTFR)
        assert len(detail.episodes) == 4

        ep1_vf = next(ep for ep in detail.episodes if ep.number == 1 and ep.version == "VF")
        ep1_vostfr = next(ep for ep in detail.episodes if ep.number == 1 and ep.version == "VOSTFR")
        assert ep1_vf.playerUrl == "https://vidzy.live/e/vf1"
        assert ep1_vostfr.playerUrl == "https://vidzy.live/e/vostfr1"
