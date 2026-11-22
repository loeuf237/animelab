import pytest
from bs4 import BeautifulSoup
from animelab.services.voiranime_service import voiranime_service

SAMPLE_MADARA_CARD_HTML = """
<div class="page-item-detail video">
  <div class="item-thumb c-image-hover" data-post-id="114035">
    <a href="https://voir-anime.to/anime/kaiju-girl-caramelise/" title="Kaiju Girl Caramelise">
      <img src="https://voir-anime.to/wp-content/uploads/thumb.png" alt="thumb" class="img-responsive"/>
    </a>
  </div>
  <div class="item-summary">
    <div class="post-title">
      <h3 class="h4">
        <a href="https://voir-anime.to/anime/kaiju-girl-caramelise/">Kaiju Girl Caramelise</a>
      </h3>
    </div>
    <div class="list-chapter">
      <div class="chapter-item">
        <span class="btn-link">11</span>
      </div>
    </div>
  </div>
</div>
"""

SAMPLE_SEARCH_CARD_HTML = """
<div class="row c-tabs-item__content">
  <div class="col-4">
    <div class="tab-thumb c-image-hover">
      <a href="https://voir-anime.to/anime/boruto-naruto-next-generations-vf/" title="Boruto: Naruto Next Generations (VF)">
        <img src="https://voir-anime.to/wp-content/uploads/boruto.jpg" class="img-responsive"/>
        <div class="manga-vf-flag">VF</div>
      </a>
    </div>
  </div>
  <div class="col-8">
    <div class="tab-summary">
      <div class="post-title">
        <h3 class="h4">
          <a href="https://voir-anime.to/anime/boruto-naruto-next-generations-vf/">Boruto: Naruto Next Generations (VF)</a>
        </h3>
      </div>
    </div>
  </div>
</div>
"""

SAMPLE_CHAPTERS_HTML = """
<div class="listing-chapters_wrap">
  <ul class="main version-chap">
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-03-vostfr/">Test Anime - 03 VOSTFR - 03</a>
    </li>
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-02-vostfr/">Test Anime - 02 VOSTFR - 02</a>
    </li>
    <li class="wp-manga-chapter">
      <a href="https://voir-anime.to/anime/test-anime/test-anime-01-vostfr/">Test Anime - 01 VOSTFR - 01</a>
    </li>
  </ul>
</div>
"""

SAMPLE_MASTER_M3U8 = """#EXTM3U
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=3326401,RESOLUTION=1920x1080,FRAME-RATE=23.974
https://cdn.example.com/hls/index-1080p.m3u8?token=xyz
#EXT-X-STREAM-INF:PROGRAM-ID=1,BANDWIDTH=516133,RESOLUTION=852x480,FRAME-RATE=23.974
https://cdn.example.com/hls/index-480p.m3u8?token=xyz
"""

def test_voiranime_parse_cards():
    results = voiranime_service.parse_cards(SAMPLE_MADARA_CARD_HTML)
    assert len(results) == 1
    r = results[0]
    assert r.title == "Kaiju Girl Caramelise"
    assert r.url == "https://voir-anime.to/anime/kaiju-girl-caramelise/"
    assert r.imageUrl == "https://voir-anime.to/wp-content/uploads/thumb.png"
    assert r.version == "VOSTFR"
    assert "11" in r.episodeInfo

def test_voiranime_parse_search_cards_with_vf():
    results = voiranime_service.parse_cards(SAMPLE_SEARCH_CARD_HTML)
    assert len(results) == 1
    r = results[0]
    assert "Boruto" in r.title
    assert r.version == "VF"
    assert r.url == "https://voir-anime.to/anime/boruto-naruto-next-generations-vf/"

def test_voiranime_episode_number_parsing():
    cases = [
        ("Kaiju Girl Caramelise - 11 VOSTFR - 11", "https://voir-anime.to/anime/kaiju/ep-11-vostfr/", 11),
        ("Boruto Naruto Next Generations - 293 VF - 293", "https://voir-anime.to/anime/boruto/ep-293-vf/", 293),
        ("(FILM VF) Kimetsu no Yaiba Movie 1", "https://voir-anime.to/anime/kimetsu/film-vf-1/", 1),
        ("(OAV VOSTFR) Naruto x UT", "https://voir-anime.to/anime/naruto/oav-vostfr/", 1),
        ("Solo Leveling 2 - 13 VOSTFR - 13", "https://voir-anime.to/anime/solo-2/ep-13/", 13),
        ("One Piece Episode 1050 VOSTFR", "https://voir-anime.to/anime/op/1050/", 1050),
    ]
    for title, url, expected in cases:
        parsed = voiranime_service._parse_episode_number(title, url, fallback=1)
        assert parsed == expected, f"Failed for {title}: expected {expected}, got {parsed}"


@pytest.mark.parametrize("title, slug, expected", [
    ("Gintama - 001x002 VOSTFR - 001x002", "gintama-001x002-vostfr", 1),
    ("Gintama - 011x012 VOSTFR - 011x012", "gintama-011x012-vostfr", 11),
    ("86 Eighty-Six - 001x002 VOSTFR", "86-eighty-six-001x002-vostfr", 1),
    ("Épisodes 01 et 02", "gintama-01-et-02-vostfr", 1),
    ("Episodes 01 & 02 VOSTFR", "gintama-01-02-vostfr", 1),
    ("Ep. 01 + 02", "gintama-01-02-vostfr", 1),
    ("Gintama - 01 × 02 VOSTFR", "gintama-01x02-vostfr", 1),
    ("Gintama - 01-02 VOSTFR", "gintama-01-02-vostfr", 1),
    ("Épisodes 01–02", "gintama-01-02-vostfr", 1),
    ("Épisodes 01 à 02", "gintama-01-a-02-vostfr", 1),
    ("01 / 02", "gintama-01-02-vostfr", 1),
    ("Gintama 01 and 02 VOSTFR", "gintama-01-and-02-vostfr", 1),
    ("Gintama", "gintama-001x002-vostfr", 1),
    ("Gintama", "gintama-01-02-vostfr", 1),
])
def test_voiranime_grouped_episode_uses_first_number(title, slug, expected):
    assert voiranime_service._parse_episode_number(
        title, f"https://voir-anime.to/anime/gintama/{slug}/?ref=365", fallback=365,
    ) == expected


@pytest.mark.parametrize("title, slug, expected", [
    ("Solo Leveling 2 - 13 VOSTFR - 13", "solo-leveling-2-13-vostfr", 13),
    ("Épisode 3 - 720x1080", "test-03-vostfr", 3),
    ("Épisodes 03 VOSTFR", "test-03-vostfr", 3),
    ("Gintama - 003 VOSTFR - 003", "gintama-003-vostfr", 3),
    ("(FILM VF) Movie 1", "movie-film-1-vf", 1),
])
def test_voiranime_grouped_parsing_preserves_single_episodes(title, slug, expected):
    assert voiranime_service._parse_episode_number(
        title, f"https://voir-anime.to/anime/test/{slug}/", fallback=365,
    ) == expected


@pytest.mark.asyncio
async def test_voiranime_grouped_chapters_survive_number_deduplication():
    # Voiranime's descending Gintama list uses these exact compound labels.
    # An index fallback can collide with a normal episode already encountered.
    labels = [f"{n:03d}" for n in range(20, 12, -1)]
    labels += ["011x012"] + [f"{n:03d}" for n in range(10, 2, -1)] + ["001x002"]
    chapters = "".join(
        f'<li class="wp-manga-chapter"><a href="/anime/gintama/gintama-{label}-vostfr/">'
        f'Gintama - {label} VOSTFR - {label}</a></li>' for label in labels
    )
    episodes = await voiranime_service.fetch_episodes(
        "https://voir-anime.to/anime/gintama/", BeautifulSoup(chapters, "html.parser"),
    )
    assert [ep.number for ep in episodes] == [1, *range(3, 11), 11, *range(13, 21)]
    assert episodes[0].title == "Épisodes 1–2"
    assert episodes[9].title == "Épisodes 11–12"
    assert episodes[0].playerUrl.endswith("gintama-001x002-vostfr/")
    assert episodes[0].downloadPageUrl == episodes[0].playerUrl
    assert len({ep.playerUrl for ep in episodes}) == len(labels)

@pytest.mark.asyncio
async def test_voiranime_fetch_episodes_chronological_order():
    soup = BeautifulSoup(SAMPLE_CHAPTERS_HTML, "html.parser")
    episodes = await voiranime_service.fetch_episodes("https://voir-anime.to/anime/test-anime/", soup)
    assert len(episodes) == 3
    # Verify sorting is ascending: 1, 2, 3
    assert episodes[0].number == 1
    assert episodes[1].number == 2
    assert episodes[2].number == 3
    assert episodes[0].playerUrl == "https://voir-anime.to/anime/test-anime/test-anime-01-vostfr/"

def test_voiranime_extract_qualities_from_m3u8(monkeypatch):
    class MockResponse:
        status_code = 200
        text = SAMPLE_MASTER_M3U8

    class MockClient:
        def get(self, url, headers=None):
            return MockResponse()

    qualities = voiranime_service._extract_qualities_from_m3u8("https://cdn.example.com/hls/master.m3u8", MockClient())
    assert "1080p" in qualities
    assert "480p" in qualities
    assert "index-1080p.m3u8" in qualities["1080p"]
    assert "index-480p.m3u8" in qualities["480p"]

def test_voiranime_resolve_streamtape_modern_obfuscation():
    sample_streamtape_html = """
    <html>
      <body>
        <div id="robotlink" style="display:none;">decoy</div>
        <script>
          document.getElementById('robotlink').innerHTML = '//streamtape.com/get_video'+ ('xcd?id=testId123&expires=1789187309&ip=127.0.0.1&token=validToken').substring(2).substring(1);
          document.getElementById('ideoolink').innerHTML = '//streamtape.comb/get_video'+ ('fake').substring(1);
        </script>
      </body>
    </html>
    """
    class MockStreamtapeClient:
        def get(self, url, headers=None, follow_redirects=True, timeout=None):
            class Resp:
                def __init__(self, sc, text, headers=None):
                    self.status_code = sc
                    self.text = text
                    self.headers = headers or {}
            if "streamtape.com/e/" in url:
                return Resp(200, sample_streamtape_html)
            elif "streamtape.com/get_video?" in url:
                return Resp(302, "", {"location": "https://cdn.tapecontent.net/video.mp4"})
            return Resp(404, "")

    res = voiranime_service._resolve_streamtape("https://streamtape.com/e/testId123", "https://voir-anime.to/", MockStreamtapeClient())
    assert res == "https://cdn.tapecontent.net/video.mp4"

def test_voiranime_resolve_streamtape_deleted_video():
    deleted_html = """
    <div id="realcontent">
      <h1 class="white">Video not found!</h1>
      <p class="subheading white">Maybe it got deleted by the creator!</p>
    </div>
    """
    class MockDeletedClient:
        def get(self, url, headers=None, follow_redirects=True, timeout=None):
            class Resp:
                status_code = 200
                text = deleted_html
                headers = {}
            return Resp()

    res = voiranime_service._resolve_streamtape("https://streamtape.com/e/deleted", "https://voir-anime.to/", MockDeletedClient())
    assert res is None

def test_voiranime_parse_asp_html():
    sample_asp_html = """
    ___ASPSTART_HTML___<div id="asp-res-2188" class='item asp_r_pagepost asp_r_pagepost_2188 asp_r_wp-manga'>
        <div class='asp_content'>
            <a class='asp_res_image_url' href='https://voir-anime.to/anime/monster-vf/'>
                <div class='asp_image' data-src="https://voir-anime.to/wp-content/uploads/2020/01/thumb_5e10806794066.jpg">
                    <img loading="lazy" alt="Monster (VF)" src="https://voir-anime.to/wp-content/uploads/2020/01/thumb_5e10806794066.jpg">
                    <div class='void'></div>
                </div>
            </a>
            <h3><a class='asp_res_url' href='https://voir-anime.to/anime/monster-vf/'>Monster (VF)<span class='overlap'></span></a></h3>
            <div class='etc'></div>
            <div class='asp_res_text'>Kenzo Tenma est un medecin japonais...</div>
        </div>
        <div class='clear'></div>
    </div>___ASPEND_HTML___
    """
    items = voiranime_service.parse_asp_html(sample_asp_html, default_version="VF")
    assert len(items) == 1
    assert items[0].title == "Monster (VF)"
    assert items[0].url == "https://voir-anime.to/anime/monster-vf/"
    assert items[0].version == "VF"
    assert "thumb_5e10806794066.jpg" in items[0].imageUrl


def test_voiranime_default_base_url_is_cx():
    from animelab.config import settings

    assert settings.VOIR_ANIME_URL == "https://voiranime.cx"
    assert voiranime_service.base_url == "https://voiranime.cx"


def test_normalize_voiranime_url():
    from animelab.services.voiranime_service import normalize_voiranime_url

    assert (
        normalize_voiranime_url("https://voir-anime.to/anime/frieren/?ref=1")
        == "https://voiranime.cx/anime/frieren/?ref=1"
    )
    assert (
        normalize_voiranime_url("https://www.voir-anime.to/anime/frieren/")
        == "https://voiranime.cx/anime/frieren/"
    )
    assert (
        normalize_voiranime_url("https://voiranime.to/anime/frieren/")
        == "https://voiranime.cx/anime/frieren/"
    )
    assert (
        normalize_voiranime_url("https://voiranime.cx/anime/frieren/")
        == "https://voiranime.cx/anime/frieren/"
    )
    assert (
        normalize_voiranime_url("https://voiranime.io/anime/frieren/")
        == "https://voiranime.io/anime/frieren/"
    )
    assert normalize_voiranime_url("ftp://voir-anime.to/file") == "ftp://voir-anime.to/file"
    assert (
        normalize_voiranime_url("https://example.com/anime/frieren/")
        == "https://example.com/anime/frieren/"
    )


def test_voiranime_load_persistent_cache_migrates_legacy_urls(monkeypatch, tmp_path):
    import json
    from animelab.config import settings
    from animelab.services.voiranime_service import VoirAnimeScrapingService

    cache_file = tmp_path / "latest_voir_anime.json"
    cache_file.write_text(
        json.dumps(
            {
                "timestamp": 1700000000.0,
                "items": [
                    {
                        "id": "frieren",
                        "title": "Frieren",
                        "imageUrl": "https://voir-anime.to/wp-content/uploads/frieren.jpg",
                        "url": "https://voir-anime.to/anime/frieren/",
                        "version": "VOSTFR",
                        "type": "Anime",
                        "episodeInfo": "Ep 28",
                        "source": "voir-anime",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(settings, "CACHE_DIR", tmp_path)
    svc = VoirAnimeScrapingService()
    assert len(svc.latest_cache) == 1
    assert svc.latest_cache[0].url == "https://voiranime.cx/anime/frieren/"
    assert svc.latest_cache[0].imageUrl == "https://voiranime.cx/wp-content/uploads/frieren.jpg"
    assert svc.last_cache_time == 0.0


@pytest.mark.asyncio
async def test_voiranime_service_methods_normalize_legacy_urls(monkeypatch):
    from unittest.mock import MagicMock
    from animelab.services.voiranime_service import VoirAnimeScrapingService

    svc = VoirAnimeScrapingService()
    requested_async: list[str] = []
    requested_sync: list[str] = []

    class DummyAsyncResp:
        status_code = 200
        text = "<html><h1>Frieren</h1></html>"

    class DummyAsyncClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def get(self, url, **kwargs):
            requested_async.append(url)
            return DummyAsyncResp()

    class DummySyncResp:
        status_code = 200
        text = '<script>const thisChapterSources = {"LECTEUR myTV": "https://voembed.net/embed-1.html"};</script>'

    class DummySyncClient:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            pass

        def get(self, url, **kwargs):
            requested_sync.append(url)
            return DummySyncResp()

    monkeypatch.setattr(svc, "_get_async_client", lambda **kwargs: DummyAsyncClient())
    monkeypatch.setattr(svc, "_get_client", lambda **kwargs: DummySyncClient())
    monkeypatch.setattr(svc, "_resolve_mytv", lambda *args, **kwargs: ("", {}, "", {}))

    detail = await svc.get_anime_detail("https://voir-anime.to/anime/frieren/")
    assert detail is not None
    assert detail.url == "https://voiranime.cx/anime/frieren/"
    assert requested_async == ["https://voiranime.cx/anime/frieren/"]

    servers = svc.get_episode_servers("https://voir-anime.to/anime/frieren/ep-1/")
    assert servers["servers"] == ["myTV"]
    assert requested_sync[-1] == "https://voiranime.cx/anime/frieren/ep-1/"

    info = svc.extract_download_info("https://voir-anime.to/anime/frieren/ep-1/")
    assert "myTV" in info["availableServers"]
    assert requested_sync[-1] == "https://voiranime.cx/anime/frieren/ep-1/"


@pytest.mark.asyncio
async def test_download_manager_detects_voiranime_cx_without_explicit_source(monkeypatch):
    import json
    from animelab.services.download_manager import download_manager
    from animelab.services.extension_service import extension_service

    ep_url = "https://voiranime.cx/anime/test-cx/ep-unique-cx/"
    called_with: list[str] = []

    def fake_extract(url, **kwargs):
        called_with.append(url)
        return {
            "videoUrl": "https://cdn.example.com/video.m3u8",
            "videoQualities": json.dumps({"1080p": "https://cdn.example.com/video.m3u8"}),
            "videoChunks": json.dumps(["https://cdn.example.com/video.m3u8"]),
            "availableServers": json.dumps(["myTV"]),
            "serverType": "myTV",
            "selectedQuality": "1080p",
            "size": 1234,
            "formattedSize": "1.2 Ko",
            "qualitiesSizes": "{}",
            "subtitleUrl": "",
            "subtitles": "[]",
        }

    monkeypatch.setattr(extension_service, "get_enabled_container_sources", lambda: [])
    monkeypatch.setattr(voiranime_service, "extract_download_info", fake_extract)
    download_manager.resolved_info_cache.clear()
    try:
        info = await download_manager.get_or_resolve_episode_info(ep_url, source=None)
        assert info is not None
        assert info.server_type == "myTV"
        assert called_with == [ep_url]
    finally:
        download_manager.resolved_info_cache.clear()


def test_media_proxies_normalize_legacy_voiranime_urls(monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from animelab.routers import media

    seen_calls: list[tuple[str, str]] = []

    class DummyStreamResp:
        status_code = 200
        headers = {"content-type": "image/jpeg"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_bytes(self, size):
            yield b"JPEGDATA"

    class DummyGetResp:
        status_code = 200
        text = "WEBVTT\n\n00:00:01.000 --> 00:00:02.000\nTest"

    class DummyClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None):
            seen_calls.append((url, (headers or {}).get("Referer", "")))
            return DummyStreamResp()

        async def get(self, url, headers=None):
            seen_calls.append((url, (headers or {}).get("Referer", "")))
            return DummyGetResp()

    monkeypatch.setattr(media, "_get_memory_cached_image", lambda url: None)
    monkeypatch.setattr(media, "_get_disk_cached_image", lambda url: None)
    monkeypatch.setattr(media, "_save_disk_cached_image", lambda *args: None)
    monkeypatch.setattr(media, "_put_memory_cached_image", lambda *args: None)
    monkeypatch.setattr(media, "_get_media_async_client", lambda **kwargs: DummyClient())

    test_app = FastAPI()
    test_app.include_router(media.router)
    with TestClient(test_app) as client:
        r_img = client.get(
            "/api/media/image-proxy",
            params={"url": "https://voir-anime.to/wp-content/uploads/poster.jpg"},
        )
        assert r_img.status_code == 200
        assert r_img.content == b"JPEGDATA"

        r_sub = client.get(
            "/api/media/subtitle-proxy",
            params={"url": "https://voir-anime.to/subs/ep1.vtt"},
        )
        assert r_sub.status_code == 200
        assert "WEBVTT" in r_sub.text

    assert seen_calls == [
        ("https://voiranime.cx/wp-content/uploads/poster.jpg", "https://voiranime.cx/"),
        ("https://voiranime.cx/subs/ep1.vtt", "https://voiranime.cx/"),
    ]


def test_voiranime_extracts_high_res_srcset_and_skips_lazy_placeholders():
    card_html = """
    <div class="page-item-detail video">
      <div class="item-thumb c-image-hover">
        <a href="https://voiranime.cx/anime/frieren/" title="Frieren">
          <img
            src="data:image/svg+xml;base64,PHN2Zz4="
            data-src="https://voiranime.cx/wp-content/uploads/2026/09/poster-110x150.jpg"
            srcset="https://voiranime.cx/wp-content/uploads/2026/09/poster-110x150.jpg 110w, https://voiranime.cx/wp-content/uploads/2026/09/poster-460x630.jpg 460w, https://voiranime.cx/wp-content/uploads/2026/09/poster-900x1200.jpg 900w"
            class="img-responsive"
          />
        </a>
      </div>
      <div class="item-summary">
        <div class="post-title"><h3 class="h4"><a href="https://voiranime.cx/anime/frieren/">Frieren</a></h3></div>
      </div>
    </div>
    """
    cards = voiranime_service.parse_cards(card_html)
    assert len(cards) == 1
    assert cards[0].imageUrl == "https://voiranime.cx/wp-content/uploads/2026/09/poster-460x630.jpg"

    asp_html = """___ASPSTART_HTML___
    <div class="item">
      <div class="asp_image" style="background-image: url('/wp-content/uploads/bg-poster.jpg')"></div>
      <h3><a class="asp_res_url" href="https://voiranime.cx/anime/dandadan/">Dandadan</a></h3>
    </div>
    <div class="item">
      <div class="asp_image">
        <img src="data:image/gif;base64,R0lGODlhAQABAIAAAAAAAP///ywAAAAAAQABAAACAUwAOw==" data-src="/wp-content/uploads/lazy-350x476.jpg" />
      </div>
      <h3><a class="asp_res_url" href="https://voiranime.cx/anime/bleach/">Bleach</a></h3>
    </div>
    ___ASPEND_HTML___"""
    asp_items = voiranime_service.parse_asp_html(asp_html)
    assert [i.imageUrl for i in asp_items] == [
        "https://voiranime.cx/wp-content/uploads/bg-poster.jpg",
        "https://voiranime.cx/wp-content/uploads/lazy-350x476.jpg",
    ]


@pytest.mark.asyncio
async def test_image_proxy_coalesces_concurrent_requests_and_prunes_disk_cache(monkeypatch, tmp_path):
    import asyncio
    from collections import OrderedDict
    import os
    import time
    import httpx
    from fastapi import FastAPI
    from animelab.routers import media

    calls = []

    class SlowStreamResp:
        status_code = 200
        headers = {"content-type": "image/jpeg"}

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def aiter_bytes(self, size):
            await asyncio.sleep(0.05)
            yield b"VOIRANIME_JPEG"

    class CountingClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        def stream(self, method, url, headers=None):
            calls.append((url, (headers or {}).get("Referer", "")))
            return SlowStreamResp()

    monkeypatch.setattr(media, "IMAGE_CACHE", OrderedDict())
    monkeypatch.setattr(media, "IMAGE_CACHE_CURRENT_BYTES", 0)
    monkeypatch.setattr(media, "IMAGE_DISK_CACHE_DIR", tmp_path)
    monkeypatch.setattr(media, "MAX_IMAGE_DISK_CACHE_FILES", 2)
    monkeypatch.setattr(media, "_get_media_async_client", lambda **kwargs: CountingClient())

    test_app = FastAPI()
    test_app.include_router(media.router)
    target = "https://voiranime.cx/wp-content/uploads/2026/09/poster-460x630.jpg"
    async with httpx.AsyncClient(transport=httpx.ASGITransport(test_app), base_url="http://127.0.0.1") as client:
        r1, r2 = await asyncio.gather(
            client.get("/api/media/image-proxy", params={"url": target}),
            client.get("/api/media/image-proxy", params={"url": target}),
        )
        assert r1.status_code == 200 and r1.content == b"VOIRANIME_JPEG"
        assert r2.status_code == 200 and r2.content == b"VOIRANIME_JPEG"
        assert len(calls) == 1
        assert calls[0] == (target, "https://voiranime.cx/")

        # Write 2 more distinct cached images and verify oldest is pruned when cap is 2 files.
        now = time.time()
        first_bin = next(tmp_path.glob("*.bin"))
        os.utime(first_bin, (now - 120, now - 120))
        media._save_disk_cached_image("https://voiranime.cx/2.jpg", b"TWO", "image/jpeg")
        second_bin = [p for p in tmp_path.glob("*.bin") if p != first_bin][0]
        os.utime(second_bin, (now - 60, now - 60))
        media._save_disk_cached_image("https://voiranime.cx/3.jpg", b"THREE", "image/jpeg")
        assert len(list(tmp_path.glob("*.bin"))) == 2
        assert not first_bin.exists()

