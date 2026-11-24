"""Regression tests for Aniyomi/Anikku DEX parser, container engine, and Android bridge fixes."""
import io
import json
import struct
import zipfile
from unittest.mock import AsyncMock

import httpx
import pytest

import android_runtime
from animelab.services import android_extensions as native
from animelab.services.aniyomi_container import (
    AniyomiContainerSource,
    _join_base_url,
    _safe_select,
)
from animelab.services.aniyomi_dex_parser import (
    AniyomiDexParser,
    SourceRecipe,
    _reconstruct_request_path,
    _reconstruct_search_path,
)
from animelab.services.extension_observability import APIOnlyExtensionError, classify
from animelab.services.source_http import source_http


def _uleb128(val: int) -> bytes:
    out = bytearray()
    while True:
        b = val & 0x7F
        val >>= 7
        if val:
            out.append(b | 0x80)
        else:
            out.append(b)
            return bytes(out)


def _build_synthetic_dex_apk(
    *,
    class_desc: str,
    super_desc: str,
    method_const_strings: dict[str, list[str]],
) -> bytes:
    """Build a minimal valid APK containing classes.dex with real class_defs/methods/const-string."""
    all_strings = list(
        dict.fromkeys(
            [class_desc, super_desc]
            + list(method_const_strings.keys())
            + [s for vals in method_const_strings.values() for s in vals]
        )
    )
    str_index = {s: idx for idx, s in enumerate(all_strings)}
    types = [class_desc, super_desc]
    type_index = {t: idx for idx, t in enumerate(types)}
    method_names = list(method_const_strings.keys())

    header_size = 0x70
    str_ids_off = header_size
    type_ids_off = str_ids_off + 4 * len(all_strings)
    proto_ids_off = type_ids_off + 4 * len(types)
    method_ids_off = proto_ids_off
    class_defs_off = method_ids_off + 8 * len(method_names)
    data_start = class_defs_off + 32

    dex = bytearray(data_start)
    dex[:8] = b"dex\n035\x00"

    for i, s in enumerate(all_strings):
        struct.pack_into("<I", dex, str_ids_off + 4 * i, len(dex))
        raw = s.encode("utf-8")
        dex.extend(_uleb128(len(s)))
        dex.extend(raw)
        dex.append(0)

    for i, t in enumerate(types):
        struct.pack_into("<I", dex, type_ids_off + 4 * i, str_index[t])

    for i, m_name in enumerate(method_names):
        # class_idx (H), proto_idx (H), name_idx (I)
        struct.pack_into("<HHI", dex, method_ids_off + 8 * i, type_index[class_desc], 0, str_index[m_name])

    code_offsets: list[int] = []
    for m_name in method_names:
        while len(dex) % 4:
            dex.append(0)
        code_offsets.append(len(dex))
        insns = bytearray()
        for s in method_const_strings[m_name]:
            # const-string v0, string@idx -> opcode 0x1A, reg 0x00, 16-bit string idx
            insns.extend(struct.pack("<BBH", 0x1A, 0x00, str_index[s]))
        insns.extend(struct.pack("<H", 0x0E00))  # return-void
        insns_size = len(insns) // 2
        dex.extend(struct.pack("<HHHHII", 1, 0, 0, 0, 0, insns_size))
        dex.extend(insns)

    class_data_off = len(dex)
    # 0 static fields, 0 instance fields, 0 direct methods, N virtual methods
    dex.extend(_uleb128(0))
    dex.extend(_uleb128(0))
    dex.extend(_uleb128(0))
    dex.extend(_uleb128(len(method_names)))
    prev_idx = 0
    for idx, code_off in enumerate(code_offsets):
        dex.extend(_uleb128(idx - prev_idx))
        prev_idx = idx
        dex.extend(_uleb128(0x0001))  # ACC_PUBLIC
        dex.extend(_uleb128(code_off))

    struct.pack_into(
        "<IIIIIIII",
        dex,
        class_defs_off,
        type_index[class_desc],
        0x0001,
        type_index[super_desc],
        0,
        0,
        0,
        class_data_off,
        0,
    )

    struct.pack_into("<II", dex, 0x38, len(all_strings), str_ids_off)
    struct.pack_into("<II", dex, 0x40, len(types), type_ids_off)
    struct.pack_into("<II", dex, 0x48, 0, proto_ids_off)
    struct.pack_into("<II", dex, 0x58, len(method_names), method_ids_off)
    struct.pack_into("<II", dex, 0x60, 1, class_defs_off)

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as zf:
        zf.writestr("classes.dex", bytes(dex))
    return buf.getvalue()


def test_reconstruct_request_and_search_paths():
    assert _reconstruct_request_path(["&status=ongoing", "/anime?page="]) == "/anime?page=1&status=ongoing"
    assert _reconstruct_request_path(["&"]) == ""
    assert _reconstruct_request_path(["/movies/page/", "/"]) == "/movies/page/1/"
    assert _reconstruct_request_path(["/page/", "/?m_orderby=views"]) == "/page/1/?m_orderby=views"
    assert _reconstruct_request_path(["bad path with spaces", "/catalog?page="]) == "/catalog?page=1"

    assert _reconstruct_search_path(["/page/", "/?s="]) == ("/page/1/?s={query}", "s")
    assert _reconstruct_search_path(["/search/title/"]) == ("/search/title/{query}", "")
    assert _reconstruct_search_path(["&", "/filter?keyword="]) == ("/filter?keyword={query}", "keyword")


def test_dex_parser_filters_pagination_and_picks_element_titles():
    apk = _build_synthetic_dex_apk(
        class_desc="Leu/kanade/tachiyomi/animeextension/en/demo/Demo;",
        super_desc="Leu/kanade/tachiyomi/animesource/online/ParsedAnimeHttpSource;",
        method_const_strings={
            "getBaseUrl": ["https://demo.example/v1"],
            "popularAnimeRequest": ["&", "/anime?page="],
            "searchAnimeRequest": ["/search/title/"],
            "popularAnimeParse": ["div.pagination a.next", "li.next", "div.anime-grid div.card"],
            "popularAnimeFromElement": ["https://demo.example/ignore", "h4.tt", "img.poster"],
        },
    )
    recipe = AniyomiDexParser.parse_apk(apk, pkg_name="eu.kanade.tachiyomi.animeextension.en.demo")
    assert recipe.base_url == "https://demo.example/v1"
    assert recipe.popular_request_path == "/anime?page=1"
    assert recipe.search_request_path == "/search/title/{query}"
    assert recipe.popular_selector == "div.anime-grid div.card"
    assert "next" not in recipe.popular_selector.lower()
    assert recipe.item_title_selector == "h4.tt"
    assert recipe.item_thumb_selector == "img.poster"
    assert not recipe.runtime.get("api_only_apk")


def test_api_only_apk_detection_and_classification():
    apk = _build_synthetic_dex_apk(
        class_desc="Leu/kanade/tachiyomi/animeextension/en/apionly/ApiOnly;",
        super_desc="Leu/kanade/tachiyomi/animesource/online/AnimeHttpSource;",
        method_const_strings={
            "getBaseUrl": ["https://graphql.api.example"],
            "popularAnimeRequest": ["/graphql"],
            "popularAnimeParse": ["application/json", "query { Page { media { id } } }"],
        },
    )
    recipe = AniyomiDexParser.parse_apk(apk, pkg_name="eu.kanade.tachiyomi.animeextension.en.apionly")
    assert recipe.runtime.get("api_only_apk") is True

    source = AniyomiContainerSource(recipe)
    assert classify(APIOnlyExtensionError("android only")) == ("unsupported", "api_only_apk")
    with pytest.raises(APIOnlyExtensionError):
        import asyncio
        asyncio.run(source.get_popular_anime())


def test_join_base_url_and_jsoup_contains_translation():
    assert _join_base_url("https://api.example/v1", "/anime/list") == "https://api.example/v1/anime/list"
    assert _join_base_url("https://api.example/v1", "/v1/anime/list") == "https://api.example/v1/anime/list"
    assert _join_base_url("https://api.example", "/anime/list") == "https://api.example/anime/list"

    from bs4 import BeautifulSoup

    soup = BeautifulSoup("<div><span>Streaming</span><span>Trailer</span></div>", "html.parser")
    matched = _safe_select(soup, "span:contains(Streaming), span:containsOwn(Trailer)")
    assert [el.get_text(strip=True) for el in matched] == ["Streaming", "Trailer"]


@pytest.mark.asyncio
async def test_container_handles_trailing_equals_page_404_noise_and_popover_episodes():
    recipe = SourceRecipe(
        pkg="eu.kanade.tachiyomi.animeextension.en.yuzono",
        base_url="https://yuzono.example/v1",
        popular_request_path="/movies/page/1/",
        popular_selector="div.grid a",
        search_request_path="/?s=",
        search_selector="div.grid a",
        item_title_selector="span.title, a",
        episode_list_selector="#episodeLists",
    )
    source = AniyomiContainerSource(recipe)
    seen_urls: list[str] = []

    async def fake_fetch(url: str, method: str = "GET", data=None, timeout: float = 10.0) -> str:
        seen_urls.append(url)
        if url.endswith("/v1/movies/page/1/"):
            req = httpx.Request("GET", url)
            raise httpx.HTTPStatusError("404", request=req, response=httpx.Response(404, request=req))
        if url.endswith("/v1/movies/"):
            return """
            <div class="grid">
              <a href="/tip/">Tip Hub</a>
              <a href="https://ads.other-tracker.invalid/click">Ad</a>
              <a href="/anime/solo-leveling"><span class="title">Solo Leveling</span></a>
            </div>
            """
        if "/v1/?s=solo+leveling" in url:
            return '<div class="grid"><a href="/anime/solo-leveling"><span class="title">Solo Leveling</span></a></div>'
        if "/anime/solo-leveling" in url:
            return """
            <h1>Solo Leveling</h1>
            <a id="episodeLists" data-toggle="popover"
               data-content="&lt;a href='/anime/solo-leveling/episode/1'&gt;Episode 1&lt;/a&gt;&lt;a href='/anime/solo-leveling/episode/2'&gt;Episode 2&lt;/a&gt;"
               href="#">Liste des épisodes</a>
            """
        raise AssertionError(f"Unexpected URL: {url}")

    source._fetch_html = fake_fetch  # type: ignore[method-assign]

    popular = await source.get_popular_anime()
    assert seen_urls == [
        "https://yuzono.example/v1/movies/page/1/",
        "https://yuzono.example/v1/movies/",
    ]
    assert [a.title for a in popular] == ["Solo Leveling"]
    assert popular[0].url == "https://yuzono.example/v1/anime/solo-leveling"

    searched = await source.search_anime("solo leveling")
    assert seen_urls[-1] == "https://yuzono.example/v1/?s=solo+leveling"
    assert [a.title for a in searched] == ["Solo Leveling"]

    detail = await source.get_anime_detail("https://yuzono.example/v1/anime/solo-leveling")
    assert detail is not None
    assert [ep.number for ep in detail.episodes] == [1, 2]
    assert detail.episodes[0].playerUrl == "https://yuzono.example/v1/anime/solo-leveling/episode/1"


@pytest.mark.asyncio
async def test_android_apk_seasons_expansion_and_clear_cookies(monkeypatch):
    monkeypatch.setattr(native, "_bridge", object())
    pkg_info = {"pkg": "fixture.seasons", "name": "SeasonsDemo", "version": "16.1", "versionCode": "1"}
    src_meta = {
        "id": "1234",
        "name": "SeasonsDemo",
        "lang": "fr",
        "baseUrl": "https://seasons.example",
        "supportsLatest": True,
    }
    src = native.AndroidAPKSource(pkg_info, src_meta)

    async def fake_call(operation: str, payload):
        if operation == "detail":
            u = payload.get("url", "")
            if u.endswith("/season/1"):
                return {"anime": payload, "episodes": [{"url": "/watch/s1e1", "name": "Episode 1", "episode_number": 1.0}]}
            if u.endswith("/season/2"):
                return {"anime": payload, "episodes": [{"url": "/watch/s2e1", "name": "Episode 1", "episode_number": 1.0}]}
            return {
                "anime": {
                    "url": "/anime/main",
                    "title": "Demo Anime",
                    "description": "Synopsis",
                    "fetch_type": "SEASONS",
                },
                "episodes": [],
                "seasons": [
                    {"url": "/season/1", "title": "Saison 1", "season_number": 1.0},
                    {"url": "/season/2", "title": "Saison 2", "season_number": 2.0},
                ],
            }
        raise AssertionError(f"Unexpected op: {operation}")

    monkeypatch.setattr(src, "call", fake_call)
    detail = await src.get_anime_detail("https://seasons.example/anime/main")
    assert detail is not None
    assert len(detail.episodes) == 2
    assert detail.episodes[0].title == "Saison 1 — Episode 1"
    assert detail.episodes[1].nativeMetadata["season"] == 2

    called_requests: list[dict] = []

    class FakeBridge:
        def invoke(self, raw: str):
            called_requests.append(json.loads(raw))
            return json.dumps({"ok": True, "result": {"cleared": 2}})

    monkeypatch.setattr(native, "_bridge", FakeBridge())
    removed = await native.clear_cookies("seasons.example")
    assert removed == 2
    assert called_requests[0]["operation"] == "clear_cookies"
    assert called_requests[0]["payload"]["domain"] == "seasons.example"


def test_android_runtime_extension_http_deduplicates_clearance_cookies(tmp_path, monkeypatch):
    recorded_headers: list[tuple[str, str]] = []

    class FakeClient:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def request(self, method: str, url: str, headers=None, content=None, max_response_bytes=None, _follow_ssl_redirects=True):
            recorded_headers.extend((headers or {}).items())
            return httpx.Response(
                200,
                text="ok",
                headers={"content-type": "text/plain"},
                request=httpx.Request(method, url),
            )

    monkeypatch.setattr(source_http, "async_client", lambda **kwargs: FakeClient())
    state = source_http.state("https://demo.example/page")
    state.cookies.set_cookie(
        source_http.cookie(".demo.example", "cf_clearance", "fresh_token", "/", True)
    )

    payload = json.dumps(
        {
            "method": "GET",
            "url": "https://demo.example/page",
            "headers": [["Cookie", "cf_clearance=stale_token; session=abc"]],
            "body": "",
        }
    )
    res = json.loads(android_runtime.extension_http(payload))
    assert res["status"] == 200
    cookie_headers = [v for k, v in recorded_headers if k.lower() == "cookie"]
    assert cookie_headers == ["session=abc"]
