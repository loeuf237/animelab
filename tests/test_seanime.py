"""Comprehensive offline unit & integration tests for Seanime extension support."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import httpx
import pytest
from fastapi.testclient import TestClient

from animelab.database import init_db, sqlite_connection
from animelab.services.seanime_catalog import (
    compare_seanime_versions,
    normalize_manifest,
    read_seanime_catalog,
)
from animelab.services.seanime_runtime import (
    MiniRacerSeanimeRuntime,
    SeanimeRuntimeError,
    host_fetch_json,
)
from animelab.services.seanime_service import SeanimeExtensionService
from animelab.services.seanime_ts import transpile_typescript
from animelab.services.source_resolvers import resolve_imported
from run import app


SAMPLE_TS_PROVIDER = """
interface SearchEntry { id: string; title: string; }
declare function fetch(url: string, options?: { method?: string }): Promise<any>;
declare const Buffer: any;

type HeadersMap = { [key: string]: string };

class Provider {
  getSettings(): Settings {
    return {
      episodeServers: ["vidcloud", "backup"],
      supportsDub: true,
    };
  }

  private ajaxHeaders(): { [key: string]: string } {
    return { "X-Custom": $getUserPreference("apiKey") || "default-key" };
  }

  async search(opts: QueryOptions): Promise<SearchResult[]> {
    const cacheKey = opts.query as string;
    const prev = $store.get<Record<string, SearchEntry[]>>("search_cache") || {};
    const domain = $getUserPreference("domain") || "https://anime.example.org";
    const resp = await fetch(`${domain}/search?q=${encodeURIComponent(cacheKey)}`, {
      headers: this.ajaxHeaders(),
    });
    const $ = LoadDoc(resp.text());
    const cards = $(".card");
    const out: SearchResult[] = [];
    for (let i = 0; i < cards.length(); i++) {
      const el = cards.eq(i);
      const id = el.attr("data-id") || "";
      const title = el.find("h3").text().trim();
      const href = el.find("a").attr("href") || "";
      out.push({
        id,
        title,
        url: href.startsWith("http") ? href : "",
        subOrDub: opts.dub ? "dub" : "sub",
      });
    }
    prev[cacheKey] = out;
    $store.set("search_cache", prev);
    return out;
  }

  async findEpisodes(id: string): Promise<EpisodeDetails[]> {
    const domain = $getUserPreference("domain") || "https://anime.example.org";
    const resp = await fetch(`${domain}/episodes/${id}`);
    const data = resp.json<{ list: { epId: string; num: number; name?: string }[] }>();
    return (data?.list || []).map((item) => ({
      id: item.epId,
      number: item.num,
      url: "",
      title: item.name || `Ep ${item.num}`,
    }));
  }

  async findEpisodeServer(episode: EpisodeDetails, server: string): Promise<EpisodeServer> {
    const typeLabel = server === "backup" ? ("mp4" as VideoSourceType) : ("hls" as VideoSourceType);
    const key = CryptoJS.enc.Utf8.parse("1234567890123456");
    const iv = CryptoJS.enc.Utf8.parse("6543210987654321");
    const encrypted = CryptoJS.AES.encrypt("secret-token", key, { iv }).toString();
    const decrypted = CryptoJS.AES.decrypt(encrypted, key, { iv }).toString(CryptoJS.enc.Utf8);
    if (decrypted !== "secret-token") {
      throw new Error("CryptoJS roundtrip mismatch");
    }
    const ext = typeLabel === "hls" ? "playlist.m3u8" : "video.mp4";
    return {
      server,
      headers: { Referer: "https://player.example.org/", "X-Server": server },
      videoSources: [
        {
          url: `https://cdn.example.org/${episode.id}/${ext}`,
          type: typeLabel,
          quality: "1080p",
          subtitles: [
            {
              id: "fr",
              url: `https://cdn.example.org/${episode.id}/subs.vtt`,
              language: "fr",
              isDefault: true,
            },
          ],
        },
      ],
    };
  }
}
"""


def _make_manifest(
    *,
    ext_id: str = "demo-stream",
    version: str = "1.0.0",
    ext_type: str = "onlinestream-provider",
    language: str = "typescript",
    payload: str = SAMPLE_TS_PROVIDER,
    domain_default: str = "https://anime.example.org",
) -> dict:
    return {
        "id": ext_id,
        "name": "Demo Seanime Stream",
        "version": version,
        "manifestURI": f"https://repo.example.org/{ext_id}/manifest.json",
        "language": language,
        "type": ext_type,
        "lang": "fr",
        "author": "Tester",
        "description": "Extension Seanime de test",
        "website": "https://anime.example.org",
        "userConfig": {
            "version": 1,
            "requiresConfig": False,
            "fields": [
                {
                    "type": "text",
                    "name": "domain",
                    "label": "Domaine",
                    "default": domain_default,
                },
                {
                    "type": "text",
                    "name": "apiKey",
                    "label": "Clé API",
                    "default": "init-key",
                },
            ],
        },
        "payload": payload,
    }


def test_seanime_catalog_formats_and_validation():
    assert compare_seanime_versions("1.2.0", "1.1.9") is True
    assert compare_seanime_versions("1.0.0", "1.0.0") is False
    assert compare_seanime_versions("v2.0.1", "2.0.0") is True

    with pytest.raises(ValueError):
        normalize_manifest({"id": "../bad", "type": "onlinestream-provider"})
    with pytest.raises(ValueError):
        normalize_manifest({"id": "dev-ext", "type": "onlinestream-provider", "isDevelopment": True})

    async def fake_fetch(url: str, _max_bytes: int) -> bytes:
        if url.endswith("Main.json"):
            return json.dumps(
                [
                    {
                        "id": "ext-one",
                        "name": "Ext One",
                        "version": "1.0.0",
                        "manifestURI": "https://repo.example.org/ext-one.json",
                        "language": "typescript",
                        "type": "onlinestream-provider",
                        "lang": "all",
                    },
                    {
                        "id": "ext-manga",
                        "name": "Ext Manga",
                        "version": "1.0.0",
                        "manifestURI": "https://repo.example.org/ext-manga.json",
                        "language": "javascript",
                        "type": "manga-provider",
                        "lang": "en",
                    },
                ]
            ).encode()
        if url.endswith("repo.json"):
            return json.dumps(
                {
                    "name": "Community Repo",
                    "urls": [
                        "https://repo.example.org/a.json",
                        "https://repo.example.org/plugin.json",
                    ],
                }
            ).encode()
        if url.endswith("a.json"):
            return json.dumps(_make_manifest(ext_id="repo-ext")).encode()
        if url.endswith("plugin.json"):
            return json.dumps(
                _make_manifest(ext_id="ignored-plugin", ext_type="plugin", language="javascript", payload="")
            ).encode()
        return json.dumps(_make_manifest(ext_id="direct-ext")).encode()

    async def run():
        marketplace = await read_seanime_catalog("https://repo.example.org/Main.json", fake_fetch)
        assert marketplace.kind == "marketplace"
        assert len(marketplace.entries) == 2
        assert marketplace.entries[0]["lang"] == "multi"

        repo = await read_seanime_catalog("https://repo.example.org/repo.json", fake_fetch)
        assert repo.kind == "repository"
        assert repo.name == "Community Repo"
        assert [e["ext_id"] for e in repo.entries] == ["repo-ext"]
        assert any("ignored-plugin" in w for w in repo.warnings)

        direct = await read_seanime_catalog("https://repo.example.org/manifest.json", fake_fetch)
        assert direct.kind == "direct"
        assert direct.entries[0]["ext_id"] == "direct-ext"

    asyncio.run(run())


def test_seanime_ts_transpiler_constructs():
    ts_code = """
    import type { Foo } from './types';
    export interface Bar { id: string; nested: { ok: boolean } }
    declare function fetch(url: string, opts?: Record<string, string>): Promise<Response>;
    enum Mode { A = 'a', B = 2 }
    class Provider {
      private mapHeaders(): { [key: string]: string } {
        const cached = $store.get<Record<string, { url: string; id: number }[]>>('cache') || {};
        const tag = Math.random() > 0.5 ? 'hls' as VideoSourceType : 'mp4';
        return { 'X-Tag': tag, 'X-Has': String(Boolean(cached)) };
      }
    }
    """
    js_out = transpile_typescript(ts_code)
    rt = MiniRacerSeanimeRuntime()
    ok, err = rt.validate_syntax(js_out, language="javascript", extension_id="ts-unit")
    assert ok, err


@pytest.mark.asyncio
async def test_miniracer_runtime_globals_crypto_dom_formdata_ssrf():
    seen_requests: list[tuple[str, str, bytes]] = []

    class FakeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method: str, url: str, **kwargs):
            content = kwargs.get("content") or b""
            seen_requests.append((method, url, content))
            if "form" in url:
                return httpx.Response(200, json={"received": "formdata" in str(kwargs.get("headers", {})).lower()}, request=httpx.Request(method, url))
            return httpx.Response(
                200,
                text='<div class="box"><span data-id="7">Salut</span></div>',
                request=httpx.Request(method, url),
            )

    # SSRF blocking on private/loopback/non-HTTP URLs
    for bad_url in (
        "http://127.0.0.1:8080/secret",
        "http://169.254.169.254/latest/meta-data/",
        "file:///etc/passwd",
    ):
        raw_resp = json.loads(await host_fetch_json(json.dumps({"url": bad_url}), client_factory=FakeClient))
        assert "error" in raw_resp

    rt = MiniRacerSeanimeRuntime(client_factory=FakeClient)
    provider_js = """
    class Provider {
      async getSettings() {
        const keyBytes = $toBytes(new Uint8Array([1,2,3,4,5,6,7,8,9,10,11,12,13,14,15,16]));
        const ivHex = CryptoJS.enc.Hex.parse('000102030405060708090a0b0c0d0e0f');
        const cipher = CryptoJS.AES.encrypt('', keyBytes, { iv: ivHex }).toString(CryptoJS.enc.Hex);
        const sha = CryptoJS.SHA256('abc').toString(CryptoJS.enc.Hex);
        const fd = new FormData();
        fd.append('token', 'xyz');
        const postRes = await fetch('https://api.example.org/form', { method: 'POST', body: fd });
        const htmlRes = await fetch('https://api.example.org/page');
        const $ = LoadDoc(htmlRes.text());
        $store.set('cipher', cipher);
        return {
          cipherLen: cipher.length,
          sha,
          formJson: postRes.json(),
          domText: $('.box span').text(),
          domAttr: $('.box span').attr('data-id'),
          pref: $getUserPreference('mirror'),
        };
      }
    }
    """
    result, store, _logs = await rt.invoke(
        extension_id="shim-test",
        source=provider_js,
        language="javascript",
        method="getSettings",
        user_config={"mirror": "https://mirror.example.org"},
    )
    assert result["cipherLen"] == 32
    assert len(result["sha"]) == 64
    assert result["domText"] == "Salut"
    assert result["domAttr"] == "7"
    assert result["pref"] == "https://mirror.example.org"
    assert store["cipher"]
    assert any(method == "POST" and b'name="token"' in body for method, _u, body in seen_requests)

    # Disallow unsafe fetch from inside V8 script
    with pytest.raises(SeanimeRuntimeError):
        await rt.invoke(
            extension_id="ssrf-js",
            source="""class Provider { async getSettings() { await fetch('http://127.0.0.1/admin'); } }""",
            language="javascript",
            method="getSettings",
        )


@pytest.mark.asyncio
async def test_seanime_service_and_end_to_end_api_flow(tmp_path, monkeypatch):
    db_file = tmp_path / "animelab.db"
    init_db(db_file)

    manifest_v1 = _make_manifest(version="1.0.0")
    manifest_v2 = _make_manifest(version="2.0.0")
    non_stream_entry = _make_manifest(
        ext_id="manga-only",
        ext_type="manga-provider",
        language="javascript",
        payload="class Provider {}",
    )
    current_version = {"v": "1.0.0"}

    class FakeSourceClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method: str, url: str, **kwargs):
            return httpx.Response(
                200,
                text='<div class="card" data-id="anime-42"><h3>Naruto</h3><a href="#"></a></div>',
                request=httpx.Request(method, url),
            )

    runtime = MiniRacerSeanimeRuntime(client_factory=FakeSourceClient)
    service = SeanimeExtensionService(db_path=str(db_file), runtime=runtime)

    async def fake_fetch_bytes(url: str, _max_bytes: int) -> bytes:
        if "Main.json" in url:
            ver = current_version["v"]
            m = _make_manifest(version=ver)
            m.pop("payload", None)
            m2 = dict(non_stream_entry)
            m2.pop("payload", None)
            return json.dumps([m, m2]).encode()
        if "demo-stream" in url:
            return json.dumps(manifest_v1 if current_version["v"] == "1.0.0" else manifest_v2).encode()
        return json.dumps(non_stream_entry).encode()

    monkeypatch.setattr(service, "_fetch_bytes", fake_fetch_bytes)

    # Wire isolated service & DB cleanly into FastAPI routers & source registry
    import animelab.services.seanime_service as seanime_mod
    from animelab.config import settings
    from animelab.services.source_registry import SourceRegistry
    import animelab.routers.anime as anime_router
    import animelab.services.source_catalogue as cat_mod
    from animelab.services.tmdb_service import tmdb_service
    from animelab.services.watchdog_service import watchdog_service

    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(seanime_mod, "seanime_service", service)
    monkeypatch.setattr(
        "animelab.services.extension_service.extension_service.db_path",
        str(db_file),
    )

    async def noop_enrich(detail):
        return detail

    monkeypatch.setattr(tmdb_service, "enrich_anime_detail", noop_enrich)
    monkeypatch.setattr(watchdog_service, "start", lambda: None)

    dummy_natives = {
        sid: SimpleNamespace(name=sid, base_url=f"https://{sid}.example", lang="fr")
        for sid in ("voir-anime", "animepahe", "french-manga", "french-stream")
    }
    test_registry = SourceRegistry(
        natives=dummy_natives,
        extensions=SimpleNamespace(
            get_enabled_container_sources=lambda: [],
            get_container_source_by_id=lambda _sid: None,
        ),
        seanime=service,
    )
    monkeypatch.setattr(anime_router, "source_registry", test_registry)
    monkeypatch.setattr(cat_mod, "source_registry", test_registry)
    monkeypatch.setattr(
        "animelab.services.extension_service.extension_service.get_container_source_by_id",
        lambda _sid: None,
    )
    monkeypatch.setattr(
        "animelab.services.extension_service.extension_service.get_enabled_container_sources",
        lambda: [],
    )
    monkeypatch.setattr(
        "animelab.services.extension_service.extension_service.get_visible_extensions",
        lambda: [],
    )

    with sqlite_connection(db_file) as conn:
        tables = {
            row["name"]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        assert {"seanime_repos", "seanime_extensions"}.issubset(tables)

    with TestClient(app) as client:
        # 1. Import marketplace
        r_imp = client.post(
            "/api/extensions/seanime/repositories",
            json={"url": "https://repo.example.org/Main.json"},
        )
        assert r_imp.status_code == 200, r_imp.text
        assert r_imp.json()["count"] == 2
        assert r_imp.json()["executable_count"] == 1

        # 2. Reject non-streaming extension install cleanly with 400
        r_non_stream = client.post("/api/extensions/seanime/manga-only/install")
        assert r_non_stream.status_code == 400

        # 3. Install streaming extension -> appears in /api/sources with seanime capability
        r_inst = client.post("/api/extensions/seanime/demo-stream/install")
        assert r_inst.status_code == 200, r_inst.text
        inst_data = r_inst.json()
        assert inst_data["installed"] is True
        assert inst_data["enabled"] is True
        assert inst_data["source_id"] == "seanime:demo-stream"

        r_sources = client.get("/api/sources")
        assert r_sources.status_code == 200
        src_list = r_sources.json()["sources"]
        seanime_entry = next(s for s in src_list if s["id"] == "seanime:demo-stream")
        assert seanime_entry["runtime"] == "seanime"
        assert seanime_entry["capabilities"]["search"] is True
        assert seanime_entry["capabilities"]["latest"] is False
        assert "anime.example.org" in service.get_allowed_domains()

        # 4. Configure custom domain + apiKey via API
        r_cfg = client.put(
            "/api/extensions/seanime/demo-stream/config",
            json={"values": {"domain": "https://custom.example.org", "apiKey": "my-secret"}},
        )
        assert r_cfg.status_code == 200
        assert r_cfg.json()["values"]["domain"] == "https://custom.example.org"

        # 5. Diagnose runs search + episodes + server stream extraction cleanly
        # Patch FakeSourceClient JSON response for episodes call
        async def custom_request(self, method: str, url: str, **kwargs):
            if "/episodes/" in url:
                return httpx.Response(
                    200,
                    json={"list": [{"epId": "ep-99", "num": 1, "name": "Pilote"}]},
                    request=httpx.Request(method, url),
                )
            assert "/search" in url
            assert url.startswith("https://custom.example.org/")
            assert kwargs.get("headers", {}).get("X-Custom") == "my-secret"
            return httpx.Response(
                200,
                text='<div class="card" data-id="anime-42"><h3>Naruto</h3><a href="#"></a></div>',
                request=httpx.Request(method, url),
            )

        monkeypatch.setattr(FakeSourceClient, "request", custom_request)

        r_diag = client.post("/api/extensions/seanime/demo-stream/diagnose", json={"query": "naruto"})
        assert r_diag.status_code == 200, r_diag.text
        diag = r_diag.json()
        assert diag["ok"] is True
        assert diag["search_count"] == 1
        assert diag["episode_count"] == 1
        assert diag["stream_count"] >= 1

        # 6. Full AnimeLab search -> detail (synthetic seanime.local ref) -> media stream resolve -> download resolver
        r_search = client.get("/api/search", params={"q": "naruto", "source": "seanime:demo-stream"})
        assert r_search.status_code == 200, r_search.text
        search_payload = r_search.json()
        anime_item = (search_payload["results"] if isinstance(search_payload, dict) else search_payload)[0]
        assert anime_item["url"].startswith("https://seanime.local/demo-stream/anime/")

        r_detail = client.get(
            "/api/anime/detail",
            params={"url": anime_item["url"], "source": "seanime:demo-stream"},
        )
        assert r_detail.status_code == 200, r_detail.text
        ep = r_detail.json()["anime"]["episodes"][0]
        assert ep["playerUrl"].startswith("https://seanime.local/demo-stream/episode/")

        r_stream = client.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "Naruto",
                "episodeNumber": 1,
                "episodeUrl": ep["playerUrl"],
                "source": "seanime:demo-stream",
            },
        )
        assert r_stream.status_code == 200, r_stream.text
        stream_json = r_stream.json()
        assert stream_json["success"] is True
        assert "/api/media/extension-resource/" in stream_json["streamUrl"]
        assert len(stream_json["subtitles"]) == 1

        # 7. source_resolvers.resolve_imported for download queue
        fake_ctx = SimpleNamespace(_update_resolved_subtitles=MagicMock())
        task = SimpleNamespace(
            source="seanime:demo-stream",
            fileUrl=ep["playerUrl"],
            selectedServer="backup",
            selectedQuality="1080p",
            fileName="Naruto-01.mp4",
            mediaJson="{}",
            requestHeaders={},
            directDownloadUrl="",
            subtitleUrl="",
            totalBytes=0,
        )
        dl_url, srv_type, _chunks = await resolve_imported(fake_ctx, task, ep["playerUrl"], True)
        assert dl_url == "https://cdn.example.org/ep-99/video.mp4"
        assert srv_type == "backup"
        assert task.requestHeaders["Referer"] == "https://player.example.org/"
        fake_ctx._update_resolved_subtitles.assert_called_once()

        # 8. Update preserves saved user_config & enabled state
        current_version["v"] = "2.0.0"
        r_chk = client.post("/api/extensions/seanime/check-updates")
        assert r_chk.status_code == 200
        assert r_chk.json()["count"] == 1

        r_upd = client.post("/api/extensions/seanime/demo-stream/update")
        assert r_upd.status_code == 200
        upd_json = r_upd.json()
        assert upd_json["installed_version"] == "2.0.0"
        assert upd_json["enabled"] is True
        assert upd_json["saved_config"]["domain"] == "https://custom.example.org"
        assert upd_json["saved_config"]["apiKey"] == "my-secret"

        # 9. Toggle & Uninstall cleanup
        r_tog = client.post("/api/extensions/seanime/demo-stream/toggle", json={"enabled": False})
        assert r_tog.status_code == 200 and r_tog.json()["enabled"] is False
        r_uninst = client.delete("/api/extensions/seanime/demo-stream")
        assert r_uninst.status_code == 200 and r_uninst.json()["installed"] is False


@pytest.mark.asyncio
async def test_swallowed_verification_required_bubbles_on_empty_result():
    from animelab.services.source_http import VerificationRequired

    class ChallengeClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, _method: str, url: str, **_kwargs):
            raise VerificationRequired(url)

    rt = MiniRacerSeanimeRuntime(client_factory=ChallengeClient)
    swallowing_provider = """
    class Provider {
      async search(opts) {
        try {
          await fetch('https://protected.example.org/search?q=' + encodeURIComponent(opts.query));
        } catch (_e) {
          return [];
        }
        return [];
      }
    }
    """
    with pytest.raises(VerificationRequired):
        await rt.invoke(
            extension_id="cf-test",
            source=swallowing_provider,
            language="javascript",
            method="search",
            args=[{"query": "naruto"}],
        )


@pytest.mark.asyncio
async def test_shim_script_style_each_headers_abort_and_placeholders():
    from animelab.services.seanime_runtime import apply_user_config_placeholders

    captured_headers: list[dict[str, str]] = []

    class CaptureClient:
        def __init__(self, **kwargs):
            captured_headers.append(dict(kwargs.get("headers") or {}))

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method: str, url: str, **_kwargs):
            return httpx.Response(200, json={"ok": True}, request=httpx.Request(method, url))

    provider_js = """
    class Provider {
      async checkAll() {
        const html = '<html><head><style>.a { color: red; }</style></head><body>' +
          '<script>var eps1 = ["lien:1"];</script>' +
          '<ul><li>One</li><li>Two</li><li>Three</li></ul>' +
          '</body></html>';
        const $ = LoadDoc(html);
        const scriptText = $('script').first().text().trim();
        const styleText = $('style').first().text().trim();

        const visited = [];
        $('li').each((_, el) => {
          visited.push(el.text());
          if (el.text() === 'Two') return false;
        });

        const hdrs = new Headers({ 'X-First': '1' });
        hdrs.append('X-First', '2');
        hdrs.set('X-Token', '{{apiKey}}');
        const res = await fetch('{{domain}}/ping', { headers: hdrs });
        const pingData = res.json();

        const ctrl = new AbortController();
        ctrl.abort();
        let abortedErr = '';
        try {
          await fetch('{{domain}}/aborted', { signal: ctrl.signal });
        } catch (err) {
          abortedErr = err.message;
        }

        const literalUnrelated = '{{") || url.includes("}}';
        return { scriptText, styleText, visited, pingOk: pingData.ok, abortedErr, literalUnrelated };
      }
    }
    """
    rendered = apply_user_config_placeholders(
        provider_js,
        {"apiKey": "secret-123"},
        {"domain": "https://mirror.example.org", "apiKey": ""},
    )
    assert "{{domain}}" not in rendered
    assert "{{apiKey}}" not in rendered
    assert '{{") || url.includes("}}' in rendered

    rt = MiniRacerSeanimeRuntime(client_factory=CaptureClient)
    result, _, _logs = await rt.invoke(
        extension_id="shim-fixes",
        source=provider_js,
        language="javascript",
        method="checkAll",
        user_config={"apiKey": "secret-123"},
        defaults={"domain": "https://mirror.example.org", "apiKey": ""},
    )
    assert result["scriptText"] == 'var eps1 = ["lien:1"];'
    assert result["styleText"] == ".a { color: red; }"
    assert result["visited"] == ["One", "Two"]
    assert result["pingOk"] is True
    assert "Abort" in result["abortedErr"]
    assert result["literalUnrelated"] == '{{") || url.includes("}}'
    assert captured_headers[0]["X-First"] == "1, 2"
    assert captured_headers[0]["X-Token"] == "secret-123"


@pytest.mark.asyncio
async def test_source_no_results_fast_server_return_canonical_pref_and_diagnose(tmp_path):
    import time as time_mod
    from animelab.services.seanime_source import SeanimeSource

    class SlowServerClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return False

        async def request(self, method: str, url: str, **_kwargs):
            if "hang" in url:
                await asyncio.sleep(10.0)
            return httpx.Response(200, json={"url": "https://cdn.example.org/fast.m3u8"}, request=httpx.Request(method, url))

    rt = MiniRacerSeanimeRuntime(client_factory=SlowServerClient)
    db_file = str(tmp_path / "source_unit.db")
    init_db(db_file)

    provider_code = """
    class Provider {
      getSettings() {
        return { episodeServers: ['VidCloud', 'HangingServer'], supportsDub: false };
      }
      async search(opts) {
        console.log('search query=' + opts.query);
        if (opts.query === 'empty') {
          throw new Error('No results found');
        }
        return [{ id: opts.query, title: 'Hit', url: '', subOrDub: 'sub' }];
      }
      async findEpisodes(id) {
        if (id === 'no-eps') return [];
        return [{ id: 'ep-1', number: 1, url: '', title: 'Ep 1' }];
      }
      async findEpisodeServer(ep, server) {
        console.log('server=' + server);
        if (server === 'HangingServer') {
          await fetch('https://hang.example.org/embed');
          return { server, headers: {}, videoSources: [] };
        }
        if (ep.id === 'ep-1' && server === 'VidCloud') {
          if (ep.url === 'no-streams') return { server, headers: {}, videoSources: [] };
          return {
            server,
            headers: {},
            videoSources: [{ url: 'https://cdn.example.org/video.m3u8', type: 'hls', quality: '1080p', subtitles: [] }],
          };
        }
        return { server, headers: {}, videoSources: [] };
      }
    }
    """
    src = SeanimeSource(
        db_path=db_file,
        extension_id="fast-test",
        name="Fast Test",
        runtime_backend=rt,
        state_loader=lambda _eid: {
            "payload": provider_code,
            "language": "javascript",
            "saved_config": {},
            "defaults": {},
            "store": {},
        },
        store_saver=lambda _eid, _s: None,
    )

    # 1. "No results found" maps to [] instead of bubbling 500
    assert await src.search_anime("empty") == []

    # 2. Fast-return cancels hanging sibling server within ~3s grace window
    t0 = time_mod.monotonic()
    cands = await src.get_episode_sources("https://seanime.local/fast-test/episode/ep-1")
    elapsed = time_mod.monotonic() - t0
    assert len(cands) == 1
    assert cands[0]["server"] == "VidCloud"
    assert elapsed < 5.5

    # 3. Canonical casing match for preferred_server returns immediately without touching HangingServer
    t1 = time_mod.monotonic()
    pref_cands = await src.get_episode_sources(
        "https://seanime.local/fast-test/episode/ep-1",
        preferred_server="vidcloud",
    )
    assert len(pref_cands) == 1
    assert pref_cands[0]["server"] == "VidCloud"
    assert (time_mod.monotonic() - t1) < 1.5

    # 4. diagnose() reports ok=False + clear error when episode_count == 0
    diag_no_eps = await src.diagnose("no-eps")
    assert diag_no_eps["ok"] is False
    assert diag_no_eps["search_count"] == 1
    assert diag_no_eps["episode_count"] == 0
    assert diag_no_eps["error"]
    assert any("search query=no-eps" in line for line in diag_no_eps["logs"])


@pytest.mark.asyncio
async def test_anilist_enrichment_and_502_on_runtime_error(tmp_path, monkeypatch):
    import animelab.routers.anime as anime_router
    import animelab.services.seanime_service as seanime_mod
    import animelab.services.seanime_source as source_mod
    import animelab.services.source_catalogue as cat_mod
    from animelab.config import settings
    from animelab.services.source_registry import SourceRegistry

    db_file = tmp_path / "err_502.db"
    init_db(db_file)
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_file))

    captured_media: list[dict] = []
    manifest_failing = _make_manifest(
        ext_id="broken-src",
        language="javascript",
        payload="""
        class Provider {
          getSettings() { return { episodeServers: ['default'], supportsDub: false }; }
          async search(opts) {
            if (opts.media && opts.media.id === 9999) {
              return [{ id: '9999', title: 'AniList Hit', url: '', subOrDub: 'sub' }];
            }
            throw new Error('Upstream provider crashed');
          }
          async findEpisodes() { return []; }
          async findEpisodeServer() { return { server: 'default', headers: {}, videoSources: [] }; }
        }
        """,
    )

    runtime = MiniRacerSeanimeRuntime()
    service = SeanimeExtensionService(db_path=str(db_file), runtime=runtime)

    async def fake_fetch_bytes(_url: str, _max_bytes: int) -> bytes:
        return json.dumps(manifest_failing).encode()

    monkeypatch.setattr(service, "_fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr(seanime_mod, "seanime_service", service)
    test_registry = SourceRegistry(
        natives={},
        extensions=SimpleNamespace(
            get_enabled_container_sources=lambda: [],
            get_container_source_by_id=lambda _sid: None,
        ),
        seanime=service,
    )
    monkeypatch.setattr(anime_router, "source_registry", test_registry)
    monkeypatch.setattr(cat_mod, "source_registry", test_registry)

    await service.import_repository("https://repo.example.org/broken.json")
    await service.install_extension("broken-src", enable=True)

    # First verify AniList helper hook populates opts.media.id when provider references media.id
    async def fake_anilist(query: str):
        captured_media.append({"q": query})
        return {
            "id": 9999,
            "idMal": 8888,
            "status": "FINISHED",
            "format": "TV",
            "englishTitle": "Test Title",
            "romajiTitle": "Test Romaji",
            "synonyms": ["Alias"],
            "isAdult": False,
            "episodeCount": 12,
            "startDate": {"year": 2020, "month": 4, "day": 1},
        }

    monkeypatch.setattr(source_mod, "_lookup_anilist_media", fake_anilist)
    src = service.get_source_by_id("seanime:broken-src")
    hits = await src.search_anime("naruto")
    assert len(hits) == 1
    assert hits[0].id == "9999"
    assert captured_media == [{"q": "naruto"}]

    # Now make AniList return None so provider throws Error -> router returns 502 (not 500)
    async def no_anilist(_query: str):
        return None

    monkeypatch.setattr(source_mod, "_lookup_anilist_media", no_anilist)
    with TestClient(app) as client:
        r_cat = client.get("/api/sources/seanime:broken-src/catalogue", params={"mode": "search", "q": "boom"})
        assert r_cat.status_code == 502, r_cat.text

        r_stream = client.get("/api/sources/seanime:broken-src/catalogue/stream", params={"mode": "search", "q": "boom"})
        assert r_stream.status_code == 200
        events = [json.loads(line) for line in r_stream.text.splitlines() if line.strip()]
        assert any(ev.get("type") == "error" and ev.get("status") == 502 for ev in events)


@pytest.mark.asyncio
async def test_detail_returns_502_on_seanime_error_and_non_seanime_stream_resolves(tmp_path, monkeypatch):
    import animelab.routers.anime as anime_router
    import animelab.routers.media as media_router
    import animelab.services.seanime_service as seanime_mod
    from animelab.config import settings
    from animelab.services.library_service import library_service
    from animelab.services.source_registry import SourceRegistry

    db_file = tmp_path / "detail_502_and_apk.db"
    init_db(db_file)
    monkeypatch.setattr(settings, "DATABASE_PATH", str(db_file))
    monkeypatch.setattr(library_service, "find_downloaded_episode", lambda **_kw: None)

    manifest = _make_manifest(
        ext_id="detail-boom",
        language="javascript",
        payload="""
        class Provider {
          getSettings() { return { episodeServers: ['default'], supportsDub: false }; }
          async search() { return []; }
          async findEpisodes() { throw new Error('Detail upstream failed'); }
          async findEpisodeServer() { return { server: 'default', headers: {}, videoSources: [] }; }
        }
        """,
    )
    runtime = MiniRacerSeanimeRuntime()
    service = SeanimeExtensionService(db_path=str(db_file), runtime=runtime)

    async def fake_fetch_bytes(_url: str, _max_bytes: int) -> bytes:
        return json.dumps(manifest).encode()

    monkeypatch.setattr(service, "_fetch_bytes", fake_fetch_bytes)
    monkeypatch.setattr(seanime_mod, "seanime_service", service)
    test_registry = SourceRegistry(
        natives={},
        extensions=SimpleNamespace(
            get_enabled_container_sources=lambda: [],
            get_container_source_by_id=lambda _sid: None,
        ),
        seanime=service,
    )
    monkeypatch.setattr(anime_router, "source_registry", test_registry)

    await service.import_repository("https://repo.example.org/detail_boom.json")
    await service.install_extension("detail-boom", enable=True)

    # Non-Seanime container source (e.g., android-apk) must still resolve candidates in media.py
    class FakeApkContainer:
        runtime = "android-apk"
        name = "Fake APK"
        base_url = "https://apk.example.org"

        async def get_episode_sources(self, _episode_url: str):
            return [
                {
                    "url": "https://cdn.example.org/ep1.m3u8",
                    "server": "ApkServer",
                    "quality": "1080p",
                }
            ]

        async def resolve_candidate(self, cand: dict):
            return {
                "videoUrl": cand["url"],
                "headers": {"Referer": "https://apk.example.org/"},
                "subtitles": [],
                "serverType": cand["server"],
                "selectedQuality": cand["quality"],
                "unsupportedArguments": False,
                "audioTracks": [],
            }

    monkeypatch.setattr(
        media_router.extension_service,
        "get_container_source_by_id",
        lambda sid: FakeApkContainer() if sid == "ext:fake-apk" else None,
    )

    with TestClient(app) as client:
        r_detail = client.get(
            "/api/anime/detail",
            params={"url": "https://seanime.local/detail-boom/anime/123", "source": "seanime:detail-boom"},
        )
        assert r_detail.status_code == 502, r_detail.text
        detail_err = r_detail.json()
        assert detail_err["code"] == "upstream_error"
        assert detail_err["problem"]["category"] == "network"

        r_apk = client.get(
            "/api/media/stream/resolve",
            params={
                "animeName": "Test",
                "episodeNumber": 1,
                "episodeUrl": "https://apk.example.org/watch/1",
                "source": "ext:fake-apk",
            },
        )
        assert r_apk.status_code == 200, r_apk.text
        apk_json = r_apk.json()
        assert apk_json["success"] is True
        assert "/api/media/extension-resource/" in apk_json["streamUrl"]
        assert apk_json["serverType"] == "ApkServer"


@pytest.mark.asyncio
async def test_seanime_detail_resolves_per_episode_version_from_json_id(tmp_path):
    db_file = tmp_path / "seanime_ep_version.db"
    init_db(db_file)

    manifest = _make_manifest(
        ext_id="anime-sama-like",
        language="javascript",
        payload="""
        class Provider {
          getSettings() { return { episodeServers: ['default'], supportsDub: true }; }
          async search() {
            return [{ id: 'op-kai10', title: 'One Piece: Kai - Saga 10', url: 'https://site.test/op', image: '', subOrDub: 'both' }];
          }
          async findEpisodes() {
            return [
              { id: JSON.stringify({ base: 'catalogue/op/kai10', lang: 'vostfr', index: 0 }), number: 1, title: 'Episode 1', url: 'https://site.test/op/vostfr#1' },
              { id: JSON.stringify({ base: 'catalogue/op/kai10', lang: 'vf', index: 0 }), number: 1, title: 'Episode 1', url: 'https://site.test/op/vf#1' },
            ];
          }
          async findEpisodeServer() { return { server: 'default', headers: {}, videoSources: [] }; }
        }
        """,
    )
    runtime = MiniRacerSeanimeRuntime()
    service = SeanimeExtensionService(db_path=str(db_file), runtime=runtime)

    async def fake_fetch_bytes(_url: str, _max_bytes: int) -> bytes:
        return json.dumps(manifest).encode()

    service._fetch_bytes = fake_fetch_bytes
    await service.import_repository("https://repo.example.org/op_kai.json")
    await service.install_extension("anime-sama-like", enable=True)

    provider = service.get_source_by_id("seanime:anime-sama-like")
    assert provider is not None
    results = await provider.search_anime("one piece", dub=True)
    assert len(results) == 1
    assert results[0].version == "VOSTFR / VF"

    detail = await provider.get_anime_detail(results[0].url)
    assert [(ep.number, ep.version) for ep in detail.episodes] == [(1, "VOSTFR"), (1, "VF")]


@pytest.mark.asyncio
async def test_seanime_fetch_bytes_retries_with_app_user_agent_on_403(tmp_path, monkeypatch):
    from animelab import __version__
    from animelab.services.source_http import AsyncSourceClient

    db_file = tmp_path / "seanime_403.db"
    init_db(db_file)
    service = SeanimeExtensionService(db_path=str(db_file), runtime=MiniRacerSeanimeRuntime())

    async def always_safe(_url: str, *, allow_private: bool = False) -> bool:
        return True

    monkeypatch.setattr("animelab.services.seanime_service.is_safe_url_async", always_safe)

    expected_ua = f"AnimeLab/{__version__}"
    calls: list[tuple[str, str, dict[str, object]]] = []

    async def fake_request(self, method, url, **kwargs):
        calls.append((method, url, dict(kwargs)))
        ua = (kwargs.get("headers") or {}).get("User-Agent")
        if ua != expected_ua:
            return httpx.Response(
                403,
                content=b"Access denied, old Chrome version.",
                request=httpx.Request(method, url),
            )
        return httpx.Response(
            200,
            content=b'{"ok":true}',
            request=httpx.Request(method, url),
        )

    monkeypatch.setattr(AsyncSourceClient, "request", fake_request)

    data = await service._fetch_bytes("https://codeberg.org/example/repo/manifest.json", 1024 * 1024)
    assert data == b'{"ok":true}'
    assert len(calls) == 2
    assert "headers" not in calls[0][2]
    assert calls[1][2]["headers"] == {"User-Agent": expected_ua}


