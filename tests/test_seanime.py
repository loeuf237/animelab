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
        for sid in ("voir-anime", "animepahe", "french-manga")
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
