"""Offline tests for the native French-Stream source (fstream.net -> fs*.lol)."""
from unittest.mock import AsyncMock, MagicMock, patch
import json

from fastapi import FastAPI
from fastapi.testclient import TestClient
import httpx
import pytest

from animelab import config as app_config
from animelab.api_errors import install_error_handlers
from animelab.routers import anime as anime_router, media as media_router
from animelab.services.french_stream_service import (
    FrenchStreamService,
    extract_mirror_from_portal_html,
    is_french_stream_url,
    normalize_french_stream_url,
)
from animelab.services.library_service import equivalent_url_variants
from animelab.services.source_catalogue import source_catalogue
from animelab.services.source_http import VerificationRequired
from animelab.services.source_registry import source_registry


PORTAL_HTML = """
<html><body>
  <a href="https://fstv.rest/">Regarder la TV</a>
  <a href="https://fsound.lol/">Musique</a>
  <a href="https://fs016.lol/premium.php">Accès Membre</a>
  <a href="https://fs016.lol">fs 016 .lol</a>
  <a href="https://fs016.lol">Regarder en streaming</a>
</body></html>
"""

LISTING_HTML = """
<html><body>
  <div class="short"><div class="short-in nl">
    <span class="film-version"><a href="/index.php?do=xfsearch&xfname=version-serie&xf=VF">VF</a></span>
    <a class="short-poster" href="/index.php?newsid=15140560" alt="Tracker - Saison 4">
      <img src="https://image.tmdb.org/t/p/w342/poster-serie.jpg" />
    </a>
    <span class="mli-eps">Ep 01 sur 13</span>
    <div class="short-title">Tracker - Saison 4</div>
  </div></div>
  <div class="short"><div class="short-in nl">
    <span class="film-quality"><a href="/xfsearch/qualit/HD/">HD</a></span>
    <span class="film-version"><a href="/index.php?do=xfsearch&xfname=version-film&xf=VF%2BVOSTFR">VF+VOSTFR</a></span>
    <a class="short-poster" href="/15125818-naruto-the-last-le-film.html" alt="Naruto the Last">
      <img src="https://image.tmdb.org/t/p/w300/poster-film.jpg" />
    </a>
    <div class="short-title">Naruto the Last : Le Film</div>
  </div></div>
</body></html>
"""

AJAX_SEARCH_HTML = """
<div class='search-item' onclick="location.href='/15125818-naruto-the-last-le-film.html'">
  <div class='search-poster'><img src='https://image.tmdb.org/t/p/w300/naruto.jpg' alt='Naruto' /></div>
  <div class='search-info'><div class='search-title'>Naruto the Last : Le Film (2014)</div></div>
</div>
"""

SERIES_DETAIL_HTML = """
<html>
<head><title>Tracker - Saison 4 | French Stream</title></head>
<body>
  <header><nav>
    <a href="/films/spectacle/">SpectacleNav</a>
    <a href="/s-tv/comedie/">ComedieNav</a>
  </nav></header>
  <main id="dle-content">
    <div id="serie-data" data-newsid="15140560" data-title="Tracker - Saison 4"
         data-affiche="https://image.tmdb.org/t/p/w342/tracker.jpg" style="display:none;"></div>
    <div class="fdesc">Colter Shaw parcourt le pays en camping-car.</div>
    <a href="/index.php?do=xfsearch&xfname=genre-1&xf=Policier">Policier</a>
    <a href="/index.php?do=xfsearch&xfname=version-serie&xf=VF%2BVOSTFR">VF+VOSTFR</a>
    <div id="vf-episodes"></div>
    <div id="vostfr-episodes"></div>
  </main>
</body>
</html>
"""

EP_DATA_JSON = {
    "vf": {
        "1": {
            "premium": "https://fsvid.lol/embed-prem1.html",
            "vidzy": "https://vidzy.org/embed-tracker1vf.html",
            "uqload": "https://uqload.vc/embed-uq1.html",
        }
    },
    "vostfr": {
        "1": {
            "uqload": "https://uqload.vc/embed-uqvost1.html",
            "vidzy": "https://vidzy.org/embed-tracker1vostfr.html",
        },
        "2": {
            "uqload": "https://uqload.vc/embed-uqvost2.html",
        },
    },
    "vo": {
        "1": {"uqload": "https://uqload.vc/embed-uqvo1.html"}
    },
    "info": {
        "1": {
            "title": "Pilot One",
            "synopsis": "First episode synopsis.",
            "poster": "https://image.tmdb.org/t/p/w342/ep1.jpg",
        }
    },
}

FILM_DETAIL_HTML = """
<html>
<body>
  <header><nav><a href="/films/spectacle/">SpectacleMenu</a></nav></header>
  <main id="dle-content">
    <div id="film-data" data-newsid="15141563" data-title="Wicker"
         data-affiche="https://image.tmdb.org/t/p/w300/wicker.jpg"
         data-affiche2="https://image.tmdb.org/t/p/w1066_and_h600_bestv2/wicker-bg.jpg"></div>
    <p class="fdesc">Une fable fantastique.</p>
    <a href="/films/fantastiques/">Fantastique</a>
    <a href="/index.php?do=xfsearch&xfname=version-film&xf=VF%2BVOSTFR">VF+VOSTFR</a>
  </main>
</body>
</html>
"""

FILM_API_JSON = {
    "players": {
        "vidzy": {
            "default": "https://vidzy.org/embed-wickervf.html",
            "vfq": "https://vidzy.org/embed-wickervf.html",
            "vostfr": "https://vidzy.org/embed-wickervost.html",
        },
        "uqload": {
            "default": "https://uqload.vc/embed-wickeruq.html",
            "vostfr": "https://uqload.vc/embed-wickervostuq.html",
        },
    },
    "meta": {
        "affiche": "https://image.tmdb.org/t/p/w300/wicker.jpg",
        "affiche2": "https://image.tmdb.org/t/p/w1066_and_h600_bestv2/wicker-bg.jpg",
    },
}


def test_portal_mirror_extraction_and_url_normalization():
    assert extract_mirror_from_portal_html(PORTAL_HTML) == "https://fs016.lol"
    assert extract_mirror_from_portal_html("<p>nothing here</p>") is None
    assert is_french_stream_url("https://fstream.net/123-item.html")
    assert is_french_stream_url("https://fs099.lol/index.php?newsid=42")
    assert not is_french_stream_url("https://fstv.rest/")

    assert (
        normalize_french_stream_url("https://french-stream.net/15125818-naruto.html", "https://fs016.lol")
        == "https://fs016.lol/15125818-naruto.html"
    )
    variants = equivalent_url_variants("https://fs016.lol/15125818-naruto.html")
    assert "https://french-stream.net/15125818-naruto.html" in variants
    assert "https://fstream.net/15125818-naruto.html" in variants


def test_parse_cards_for_listing_series_films_and_ajax_search(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.settings, "CACHE_DIR", tmp_path)
    svc = FrenchStreamService()
    svc.base_url = "https://fs016.lol"

    items = svc.parse_search_results(LISTING_HTML)
    assert len(items) == 2
    assert items[0].source == "french-stream"
    assert items[0].id == "15140560"
    assert items[0].type == "Série"
    assert items[0].version == "VF"
    assert items[0].episodeInfo == "Ep 01 sur 13"

    assert items[1].id == "15125818"
    assert items[1].type == "Film"
    assert items[1].version == "VF+VOSTFR"

    ajax_items = svc.parse_search_results(AJAX_SEARCH_HTML)
    assert len(ajax_items) == 1
    assert ajax_items[0].id == "15125818"
    assert ajax_items[0].url == "https://fs016.lol/15125818-naruto-the-last-le-film.html"


@pytest.mark.asyncio
async def test_series_and_film_detail_parsing_excludes_nav_genres_and_deduplicates_players(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(app_config.settings, "CACHE_DIR", tmp_path)
    svc = FrenchStreamService()
    svc.base_url = "https://fs016.lol"
    monkeypatch.setattr("animelab.services.french_stream_service.is_safe_url", lambda url: True)

    async def fake_request(method, path_or_url, **_kwargs):
        url_str = str(path_or_url)
        if "newsid=15140560" in url_str:
            return httpx.Response(200, text=SERIES_DETAIL_HTML, request=httpx.Request("GET", "https://fs016.lol/index.php?newsid=15140560"))
        if "/ep-data.php?id=15140560" in url_str:
            return httpx.Response(200, text=json.dumps(EP_DATA_JSON), request=httpx.Request("GET", "https://fs016.lol/ep-data.php?id=15140560"))
        if "newsid=15141563" in url_str:
            return httpx.Response(200, text=FILM_DETAIL_HTML, request=httpx.Request("GET", "https://fs016.lol/index.php?newsid=15141563"))
        if "/engine/ajax/film_api.php?id=15141563" in url_str:
            return httpx.Response(200, text=json.dumps(FILM_API_JSON), request=httpx.Request("GET", "https://fs016.lol/engine/ajax/film_api.php?id=15141563"))
        return httpx.Response(404, request=httpx.Request("GET", "https://fs016.lol/404"))

    svc._request = fake_request  # type: ignore[method-assign]

    series = await svc.get_anime_detail("https://fs016.lol/index.php?newsid=15140560")
    assert series is not None
    assert series.source == "french-stream"
    assert series.title == "Tracker - Saison 4"
    assert series.genres == ["Policier"]
    assert "SpectacleNav" not in series.genres
    assert series.version == "VF + VOSTFR"
    assert len(series.episodes) == 4
    ep1_vf = next(ep for ep in series.episodes if ep.number == 1 and ep.version == "VF")
    assert ep1_vf.title == "Pilot One"
    assert ep1_vf.synopsis == "First episode synopsis."
    assert ep1_vf.playerUrl == "https://vidzy.org/embed-tracker1vf.html"
    assert ep1_vf.downloadPageUrl == "https://vidzy.org/d/tracker1vf_n"
    ep2_vostfr = next(ep for ep in series.episodes if ep.number == 2 and ep.version == "VOSTFR")
    assert ep2_vostfr.playerUrl == "https://uqload.vc/embed-uqvost2.html"

    film = await svc.get_anime_detail("https://fs016.lol/index.php?newsid=15141563")
    assert film is not None
    assert film.title == "Wicker"
    assert film.bannerUrl == "https://image.tmdb.org/t/p/w1066_and_h600_bestv2/wicker-bg.jpg"
    assert "SpectacleMenu" not in film.genres
    assert "Fantastique" in film.genres
    # Default ("VF") and VFQ shared identical URL, so only VOSTFR and VF distinct versions remain.
    assert [ep.version for ep in film.episodes] == ["VOSTFR", "VF"]
    assert film.episodes[0].playerUrl == "https://vidzy.org/embed-wickervost.html"
    assert film.episodes[1].title == "Film complet (VF)"
    assert film.episodes[1].playerUrl == "https://vidzy.org/embed-wickervf.html"


@pytest.mark.asyncio
async def test_mirror_fallback_and_verification_challenge_propagation(tmp_path, monkeypatch):
    monkeypatch.setattr(app_config.settings, "CACHE_DIR", tmp_path)
    svc = FrenchStreamService()
    svc.base_url = "https://fs015.lol"
    monkeypatch.setattr("animelab.services.french_stream_service.is_safe_url", lambda url: True)

    seen_urls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        seen_urls.append(url)
        if url.startswith("https://fstream.net"):
            return httpx.Response(200, text=PORTAL_HTML)
        if url.startswith("https://fs015.lol"):
            raise httpx.ConnectError("mirror down", request=request)
        if url.startswith("https://fs016.lol"):
            return httpx.Response(200, text=LISTING_HTML)
        return httpx.Response(404)

    class MockSourceAsyncClient(httpx.AsyncClient):
        async def request(self, method, url, *args, **kwargs):
            kwargs.pop("retry_safe", None)
            return await super().request(method, url, *args, **kwargs)

    monkeypatch.setattr(
        "animelab.services.french_stream_service.source_http.async_client",
        lambda **_kw: MockSourceAsyncClient(transport=httpx.MockTransport(handler), trust_env=False),
    )

    resp = await svc._request("GET", "/", retry_safe=True)
    assert resp.status_code == 200
    assert svc.base_url == "https://fs016.lol"
    assert any(u.startswith("https://fs016.lol") for u in seen_urls)

    # VerificationRequired during portal resolution is never swallowed.
    class ChallengeTransport(httpx.AsyncBaseTransport):
        async def handle_async_request(self, request: httpx.Request) -> httpx.Response:
            raise VerificationRequired("https://fstream.net/")

    monkeypatch.setattr(
        "animelab.services.french_stream_service.source_http.async_client",
        lambda **_kw: MockSourceAsyncClient(transport=ChallengeTransport(), trust_env=False),
    )
    with pytest.raises(VerificationRequired):
        await svc.resolve_active_base_url(force=True)


@pytest.mark.asyncio
async def test_registry_catalogue_home_feed_and_stream_resolution(monkeypatch):
    # Registry recognizes french-stream and dynamic fs*.lol hosts.
    fs_provider = source_registry.get("french-stream")
    assert fs_provider.name == "French-Stream"
    assert fs_provider.capabilities.popular
    assert fs_provider.capabilities.featured
    assert fs_provider.capabilities.catalogue
    assert source_registry.detect("https://fs099.lol/index.php?newsid=99") == "french-stream"

    # Source catalogue filters and browse modes work for french-stream.
    sample_html = (
        '<nav><a href="/films/actions/">Action</a><a href="/s-tv/s-vf/">VF</a></nav>'
        + LISTING_HTML
    )
    monkeypatch.setattr(source_catalogue, "html", AsyncMock(return_value=(sample_html, fs_provider.base_url + "/")))
    filters = await source_catalogue.filters("french-stream")
    assert any(t["label"] == "Action" for t in filters["tags"])
    assert any(t["label"] == "VF" for t in filters["tags"])
    popular_page = await source_catalogue.browse("french-stream", mode="popular")
    assert len(popular_page["results"]) == 2
    assert all(item.source == "french-stream" for item in popular_page["results"])

    # Home feed exposes french-stream without breaking other providers.
    mock_result = [MagicMock(model_dump=lambda: {"id": "1", "title": "Tracker", "url": "https://fs016.lol/1", "source": "french-stream"})]
    with patch.object(anime_router, "source_registry", source_registry):
        for p in source_registry.all():
            monkeypatch.setattr(p.service, "get_latest_releases", AsyncMock(return_value=[] if p.id != "french-stream" else [
                next(iter(source_registry.get("french-stream").service.parse_search_results(LISTING_HTML)))
            ]))
        monkeypatch.setattr(anime_router.library_service, "get_all_favorites", lambda: [])
        monkeypatch.setattr(anime_router.library_service, "get_history", lambda: [])
        home = await anime_router.api_home_feed()
    assert "french-stream" in home["latestReleases"]
    assert len(home["latestFrenchStream"]) == 1
    assert home["latestFrenchStream"][0]["source"] == "french-stream"

    # Media stream resolution supports both Vidzy and Uqload embeds for french-stream.
    app = FastAPI()
    install_error_handlers(app)
    app.include_router(media_router.router)

    monkeypatch.setattr(media_router.library_service, "find_downloaded_episode", lambda **_kw: None)
    monkeypatch.setattr(media_router.local_media, "find_and_register", lambda **_kw: None)
    monkeypatch.setattr(
        media_router.scraping_service,
        "extract_download_info",
        lambda url: {"videoUrl": "https://v6.vidzy.org/v/video.mp4", "subtitleUrl": ""},
    )
    monkeypatch.setattr(
        media_router.download_manager,
        "resolve_imported_video_stream",
        AsyncMock(return_value={"videoUrl": "https://m.uqload.vc/video.mp4", "serverType": "Uqload", "selectedQuality": "HD"}),
    )

    with TestClient(app) as client:
        r_vidzy = client.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "Wicker",
                "episodeNumber": 1,
                "episodeUrl": "https://vidzy.org/embed-wickervf.html",
                "source": "french-stream",
            },
        )
        assert r_vidzy.status_code == 200
        assert r_vidzy.json()["serverType"] == "vidzy"
        assert "v6.vidzy.org" in r_vidzy.json()["streamUrl"]

        r_uq = client.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "Tracker",
                "episodeNumber": 2,
                "episodeUrl": "https://uqload.vc/embed-uqvost2.html",
                "source": "french-stream",
            },
        )
        assert r_uq.status_code == 200
        assert r_uq.json()["serverType"] == "Uqload"
        assert "m.uqload.vc" in r_uq.json()["streamUrl"]
    assert len(mock_result) == 1
