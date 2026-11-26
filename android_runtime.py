"""Android bootstrap. Configure storage and JNI before importing the engine."""
import asyncio
from contextlib import asynccontextmanager, suppress
from email.utils import formatdate
from http.cookies import SimpleCookie
import json
import os
from animelab.environment import update_environment
from pathlib import Path
import time
from urllib.parse import urlparse

_loop = None
_configured_bridges = set()


def _ensure_source_http_configured():
    if "source_http" in _configured_bridges:
        return
    try:
        from java import jclass
    except ImportError:
        return
    from animelab.services.source_http import source_http
    verification = jclass("com.animan.app.VerificationBridge")
    source_http.default_user_agent = source_http.valid_user_agent(str(verification.userAgent()))
    _configured_bridges.add("source_http")


def _ensure_android_extensions_configured():
    if "android_extensions" in _configured_bridges:
        return
    try:
        from java import jclass
    except ImportError:
        return
    from animelab.services import android_extensions
    if jclass("com.animan.app.BuildConfig").EXTENSION_RUNTIME_ENABLED:
        android_extensions.configure(jclass("com.animan.app.ExtensionBridge"))
    _configured_bridges.add("android_extensions")


def _ensure_seanime_configured():
    if "seanime" in _configured_bridges:
        return
    try:
        from java import jclass
    except ImportError:
        return
    from animelab.services.seanime_runtime import seanime_runtime
    seanime_runtime.configure_android(jclass("com.animan.app.SeanimeJsBridge"))
    _configured_bridges.add("seanime")


def _ensure_browser_verification_configured():
    if "browser_verification" in _configured_bridges:
        return
    try:
        from java import jclass
    except ImportError:
        return
    from animelab.services.browser_verification import browser_verification
    verification = jclass("com.animan.app.VerificationBridge")
    browser_verification.platform = "android"
    opener = lambda url, auto_close=True: VerificationWindow(url, verification, auto_close=auto_close)
    opener.seed_cookies = lambda url, cookies: VerificationWindow.seed_cookies(url, cookies, verification)
    opener.user_agent = lambda: str(verification.userAgent())
    browser_verification.webview_opener = opener
    _configured_bridges.add("browser_verification")


def _ensure_download_hooks_configured():
    if "download_hooks" in _configured_bridges:
        return
    from java import jclass
    from animelab import platform_events
    from animelab.models.download_task import DownloadStatus, ExportStatus
    from animelab.services.download_manager import download_manager

    hooks = jclass("com.animan.app.NativeHooks")
    storage = jclass("com.animan.app.StorageAccess")

    def notify(task):
        active = [t for t in download_manager.get_all_tasks() if t.status in (
            DownloadStatus.PENDING, DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING, DownloadStatus.MUXING)
            or (t.exportStatus == ExportStatus.EXPORTING and not t.paused and not t.cancelled)]
        native_status = "CANCELLED" if task.cancelled else "PAUSED" if task.paused else "EXPORTING" if task.exportStatus == ExportStatus.EXPORTING else task.status.value
        if not hooks.progress(len(active), int(task.progress), task.fileName, task.id, native_status) and active and _loop:
            _loop.call_soon_threadsafe(download_manager.pause_all_downloads)

    def export_completed(task):
        if not task.savePath or not Path(task.savePath).is_file():
            raise FileNotFoundError("The private download is missing")
        paths = [path for path in dict.fromkeys(platform_events.completed_paths(task)) if path and Path(path).is_file()]
        if not paths:
            raise FileNotFoundError("The private download is missing")
        uris = [str(hooks.exportFile(path, task.id)) for path in paths]
        destination = json.loads(str(storage.status()))["destination"]
        # Release private staging copies once every file is verified & published in shared storage.
        download_manager._release_private_paths(paths)
        return {"uris": uris, "destination": destination}

    platform_events.progress_handler = notify
    platform_events.completed_handler = export_completed
    _configured_bridges.add("download_hooks")


def seanime_fetch(payload, extension_id=""):
    """Execute one Seanime fetch() call through Python's SSRF-protected transport."""
    _ensure_source_http_configured()
    _ensure_seanime_configured()
    from animelab.services.seanime_runtime import (
        AndroidSeanimeRuntime,
        host_fetch_json_sync,
        seanime_runtime,
    )

    backend = seanime_runtime.backend
    if isinstance(backend, AndroidSeanimeRuntime):
        return backend.fetch_sync(str(payload or "{}"), extension_id=str(extension_id or ""))
    return host_fetch_json_sync(str(payload or "{}"))


def extension_http(payload):
    """Native default OkHttp gateway: keep the shared URL/cookie/proxy policy."""
    import base64
    _ensure_source_http_configured()
    from animelab.services.source_http import source_http, VerificationRequired, RateLimited, SourceNetworkError
    if json.loads(payload).get('action') == 'user_agent':
        return json.dumps({'userAgent':source_http.default_user_agent})
    async def request():
        data = json.loads(payload)
        body = base64.b64decode(data.get('body', ''), validate=True)
        if len(body) > 2_000_000:
            raise ValueError('Request exceeds budget')
        method = data['method'].upper()
        if method not in ('GET', 'HEAD', 'POST', 'PUT', 'PATCH', 'DELETE', 'OPTIONS'):
            raise ValueError('Unsupported HTTP method')
        milliseconds = int(data.get('readTimeoutMillis',30000))
        timeout = 30 if milliseconds<=0 else min(30,max(.1,milliseconds/1000))
        req_headers = dict(data.get('headers') or [])
        state = source_http.state(data['url'])
        with state.condition:
            managed_clearance = {
                c.name for c in state.cookies
                if c.name in ('cf_clearance', '__cf_bm', '__ddg2_', 'ddg_clearance') and not c.is_expired()
            }
        if managed_clearance:
            for h_key in [k for k in req_headers if str(k).lower() == 'cookie']:
                kept = []
                for part in str(req_headers[h_key]).split(';'):
                    name = part.split('=', 1)[0].strip()
                    if name and name not in managed_clearance:
                        kept.append(part.strip())
                if kept:
                    req_headers[h_key] = '; '.join(kept)
                else:
                    del req_headers[h_key]
        async with source_http.async_client(timeout=timeout, follow_redirects=data.get('followRedirects',True) is True) as client:
            response = await client.request(method, data['url'], headers=req_headers,
                                            content=body or None, max_response_bytes=8_000_000,
                                            _follow_ssl_redirects=data.get('followSslRedirects',True) is True)
            return {'status':response.status_code, 'url':str(response.url),
                    'headers':list(response.headers.multi_items()), 'contentType':response.headers.get('content-type',''),
                    'body':base64.b64encode(response.content).decode()}
    try:
        return json.dumps(asyncio.run(request()))
    except VerificationRequired as error:
        return json.dumps({'error':'verification_required','url':error.url})
    except RateLimited:
        return json.dumps({'error':'rate_limited'})
    except SourceNetworkError as error:
        return json.dumps({'error':{'dns':'network_dns','tls':'network_tls','timeout':'network_timeout'}.get(error.kind,'network_error')})
    except Exception:
        return json.dumps({'error':'source_network_error'})


class VerificationWindow:
    _seeds = {}

    @classmethod
    def seed_cookies(cls, url, cookies, bridge):
        cls._seeds[url] = cookies
        cls._write_cookies(url, cookies, bridge)

    @staticmethod
    def _write_cookies(url, cookies, bridge):
        headers = []
        for item in cookies:
            jar = SimpleCookie()
            jar[item["name"]] = item["value"]
            cookie = jar[item["name"]]
            cookie["path"] = item.get("path", "/")
            if item.get("domain", "").startswith("."): cookie["domain"] = item["domain"]
            cookie["secure"] = bool(item.get("secure"))
            cookie["httponly"] = bool(item.get("httpOnly"))
            if item.get('sameSite'): cookie['samesite'] = item['sameSite']
            if item.get("expires"): cookie["expires"] = formatdate(item["expires"], usegmt=True)
            headers.append(cookie.OutputString())
        bridge.setCookies(url, json.dumps(headers))

    def __init__(self, url, bridge, auto_close=True):
        self.url, self.bridge = url, bridge
        self.metadata = {(item["domain"], item["path"], item["name"]): item for item in self._seeds.pop(url, [])}
        ua = str(self.bridge.userAgent())
        try:
            self.bridge.open(url, ua, bool(auto_close))
        except (TypeError, AttributeError):
            self.bridge.open(url, ua)

    def set_cookies(self, cookies):
        self._write_cookies(self.url, cookies, self.bridge)
        for item in cookies:
            key = (item['domain'], item['path'], item['name'])
            if item.get('expires') and item['expires'] <= time.time():
                self.metadata.pop(key, None)
            else:
                self.metadata[key] = item

    def get_cookie_records(self):
        jar = SimpleCookie()
        jar.load(str(self.bridge.cookies(self.url)))
        result = []
        for name, cookie in jar.items():
            matches = [item for item in self.metadata.values() if item['name'] == name]
            if len(matches) > 1:
                # CookieManager omits domain/path: do not guess which duplicate
                # was modified, or collapse distinct HTTP sessions into one.
                result.extend(dict(item) for item in matches)
                continue
            previous = matches[0] if matches else None
            item = dict(previous) if previous else {
                'domain': urlparse(self.url).hostname,
                'path': '/' if name in ('cf_clearance', '__cf_bm') else urlparse(self.url).path or '/',
                'secure': urlparse(self.url).scheme == 'https', 'httpOnly': True,
                'expires': time.time() + 3600}
            if previous and previous.get('expires') and previous['expires'] <= time.time():
                item['expires'] = time.time() + 3600
            item.update(name=name, value=cookie.value)
            self.metadata[(item['domain'], item['path'], name)] = item
            result.append(item)
        return result

    def get_cookies(self):
        jar = SimpleCookie()
        jar.load(str(self.bridge.cookies(self.url)))
        for cookie in jar.values():
            cookie["domain"] = urlparse(self.url).hostname
            cookie["path"] = "/"
            cookie["secure"] = urlparse(self.url).scheme == "https"
            # CookieManager does not expose expiry. Revalidate within an hour
            # instead of turning a browser session cookie into permanent access.
            cookie["expires"] = formatdate(time.time() + 3600, usegmt=True)
        return [jar]

    def destroy(self):
        self.bridge.close(self.url)

    def is_closed(self):
        return not bool(self.bridge.isOpen(self.url))


def start(data_dir, cache_dir, port, token, test_mode=False):
    global _loop
    update_environment({
        # Shared engine cache also contains installed extensions and user proxy
        # lists. Android may evict cacheDir, so preserve this state in filesDir.
        "ANIMAN_DATA_DIR": data_dir, "ANIMAN_CACHE_DIR": str(Path(data_dir) / "engine-state"),
        "ANIMAN_DB_PATH": str(Path(data_dir) / "db/animan.sqlite3"),
        "ANIMAN_DOWNLOAD_DIR": str(Path(data_dir) / "downloads"),
        "ANIMAN_HOST": "127.0.0.1", "ANIMAN_PORT": str(port),
        "ANIMELAB_PROGRESSIVE_BOOT": os.environ.get("ANIMELAB_PROGRESSIVE_BOOT", "1"),
    })
    if test_mode:
        update_environment(ANIMAN_STARTUP_REFRESH="false", ANIMELAB_UPDATE_CHECK_DISABLED="true")
    import tempfile
    tempfile.tempdir = cache_dir
    from java import jclass
    from animelab import media_tools, platform_events
    media_tools.configure_android(jclass("com.animan.app.MediaBridge"), jclass("com.animan.app.CryptoBridge"))
    hooks = jclass("com.animan.app.NativeHooks")
    storage = jclass("com.animan.app.StorageAccess")
    engine_host = jclass("com.animan.app.EngineHost")
    update_environment(ANIMELAB_RELEASE_VERSION=str(jclass('com.animan.app.BuildConfig').RELEASE_VERSION))
    platform_events.storage_status_handler = lambda: json.loads(str(storage.status()))
    platform_events.storage_action_handler = lambda action: json.loads(str(storage.request(action)))
    platform_events.exported_copy_exists_handler = lambda uri: bool(hooks.exportedCopyExists(uri))
    import base64
    platform_events.exported_copy_size_handler = lambda uri: int(hooks.exportedCopySize(uri))
    platform_events.read_exported_copy_handler = lambda uri, offset, length: base64.b64decode(
        str(hooks.readExportedCopyBase64(uri, int(offset), int(length)))
    )
    platform_events.delete_exported_copy_handler = lambda uri: bool(hooks.deleteExportedCopy(uri))
    extension_bridge = jclass("com.animan.app.ExtensionBridge")
    platform_events.app_update_install_handler = lambda path: json.loads(str(extension_bridge.installAppUpdate(path)))
    platform_events.app_update_status_handler = lambda op_id: json.loads(str(extension_bridge.appUpdateStatus(op_id or "")))
    platform_events.app_update_confirm_handler = lambda op_id, path: json.loads(str(extension_bridge.confirmAppUpdate(op_id or "", path or "")))

    import run
    from animelab.android_security import AndroidSessionMiddleware
    run.app.add_middleware(AndroidSessionMiddleware, token=token)

    def _configure_core_bridges():
        _ensure_source_http_configured()
        _ensure_browser_verification_configured()
        _ensure_download_hooks_configured()
        _ensure_android_extensions_configured()
        _ensure_seanime_configured()

    run.progressive_loader.register_hook("core_services", _configure_core_bridges)
    run.progressive_loader.register_hook("extensions", _ensure_android_extensions_configured)
    run.progressive_loader.register_hook("sources", _ensure_seanime_configured)

    original_lifespan = run.app.router.lifespan_context

    async def startup_cleanup():
        try:
            from animelab.services.download_manager import download_manager
            await asyncio.to_thread(
                download_manager.startup_android_storage_cleanup,
                lambda uri: bool(hooks.exportedCopyExists(uri)),
            )
        except asyncio.CancelledError:
            raise
        except Exception as failure:
            import logging
            logging.getLogger('animelab.download_manager').warning('Nettoyage stockage ignoré (%s)', type(failure).__name__)

    @asynccontextmanager
    async def lifespan(app):
        global _loop
        _loop = asyncio.get_running_loop()
        post_warmup_tasks = []

        def _on_full_ready():
            engine_host.markFullReady()
            from animelab.services.extension_service import extension_service

            async def discover_apks():
                try:
                    await asyncio.to_thread(extension_service.sync_android_extensions)
                except Exception as failure:
                    import logging
                    logging.getLogger('animelab.extensions').warning('Découverte APK indisponible (%s)', type(failure).__name__)

            if _loop is not None:
                post_warmup_tasks.append(_loop.create_task(discover_apks()))
                post_warmup_tasks.append(_loop.create_task(startup_cleanup()))

        run.progressive_loader.register_hook("full_ready", _on_full_ready)

        async with original_lifespan(app):
            hooks.ready()
            if not run.PROGRESSIVE_BOOT:
                _on_full_ready()
            try:
                yield
            finally:
                for task in post_warmup_tasks:
                    task.cancel()
                for task in post_warmup_tasks:
                    with suppress(asyncio.CancelledError):
                        await task
        _loop = None

    run.app.router.lifespan_context = lifespan
    run.start_embedded_server("127.0.0.1", port, data_dir)


def command(action):
    if _loop is None:
        return False
    from animelab.services.download_manager import download_manager
    actions = {"pause": download_manager.pause_all_downloads, "resume": download_manager.resume_all_downloads}
    if action not in actions:
        raise ValueError("Unknown Android download action")
    _loop.call_soon_threadsafe(actions[action])
    return True


def native_probe(include_media=True):
    """Called by instrumentation, not by a public API or untrusted WebView."""
    import cffi, curl_cffi, pydantic, sqlalchemy, websockets, yt_dlp
    from bs4 import BeautifulSoup
    from animelab import media_tools
    from animelab.database import engine
    from animelab.services.source_http import source_http
    from animelab.models.anime import AnimeResult
    assert AnimeResult(id="probe", title="Offline", url="https://example.com").model_dump()["id"] == "probe"
    with engine.connect() as connection:
        assert connection.exec_driver_sql("SELECT 1").scalar() == 1
    assert media_tools.which("ffmpeg") and media_tools.which("ffprobe")
    # Exercise the exact publication step implicated in Errno 13 without
    # relying on ARM-translated FFmpeg command execution in the emulator.
    from animelab.config import settings
    from animelab.services.download_manager import download_manager
    publish_root = Path(settings.DOWNLOAD_DIR) / "native-publish-probe"
    publish_root.mkdir(parents=True, exist_ok=True)
    original = publish_root / "episode.mkv"
    staging = publish_root / "staging.tmp"
    original.write_bytes(b"existing episode")
    staging.write_bytes(b"verified mux output")
    published = download_manager._publish_mux_file(staging, publish_root / "episode.mp4", original, "native-publish")
    assert published != original and original.read_bytes() == b"existing episode"
    assert published.read_bytes() == b"verified mux output"
    published.unlink(); original.unlink(); staging.unlink(missing_ok=True)
    assert media_tools.run(["ffmpeg", "-version"], check=True).stdout
    # TLS + Chrome impersonation, outside source security/cache policy.
    response = curl_cffi.requests.get("https://example.com", impersonate="chrome", timeout=20)
    assert response.status_code == 200
    # Exercise the parser used by built-in and imported source adapters.
    soup = BeautifulSoup('<article class="anime"><a href="/episode">Probe</a></article>', "html.parser")
    assert soup.select_one(".anime a")["href"] == "/episode"
    # This exercises the actual Python-to-Java AES boundary even when the
    # emulator's ARM binary translation cannot execute FFmpeg CLI commands.
    key = bytes.fromhex("2b7e151628aed2a6abf7158809cf4f3c")
    iv = bytes.fromhex("000102030405060708090a0b0c0d0e0f")
    assert media_tools.decrypt_aes_cbc(bytes.fromhex("7649abac8119b246cee98e9b12e9197d"), key, iv) == bytes.fromhex("6bc1bee22e409f96e93d7e117393172a")
    import subprocess
    try:
        media = media_pipeline_probe() if include_media else {}
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        raise RuntimeError(f"Native media validation failed: {exc}; diagnostics: {str(exc.stderr)[-2048:]}") from exc
    return json.dumps({"python_engine": True, "curl_cffi": curl_cffi.__version__,
                       "pydantic": pydantic.__version__, "ffmpeg_jni": True, "tls": True,
                       "java_aes": True, "atomic_media_publish": True, "media_commands_tested": bool(include_media), **media})


def media_pipeline_probe():
    """Real JNI media operations and the shared direct/HLS/subtitle pipeline."""
    import httpx
    from java import jclass
    from animelab import media_tools
    from animelab.config import settings
    from animelab.models.download_task import DownloadTask, DownloadStatus
    import importlib
    media_module = importlib.import_module("animelab.services.download_stages.media")
    from animelab.services.download_manager import download_manager as manager
    from animelab.services.download_resume import write_metadata
    from animelab.services.verification_service import verification_service
    root = Path(settings.DOWNLOAD_DIR) / "native-probe"
    root.mkdir(parents=True, exist_ok=True)
    source = root / "fixture.mp4"
    media_tools.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i", "color=c=black:s=160x90:r=10",
                     "-f", "lavfi", "-i", "sine=frequency=440", "-t", "40", "-c:v", "mpeg4", "-c:a", "aac",
                     str(source)], check=True)
    payload = source.read_bytes()
    segment = root / "fixture.ts"
    media_tools.run(["ffmpeg", "-v", "error", "-y", "-i", str(source), "-t", "2", "-c:v", "mpeg2video",
                     "-c:a", "aac", "-f", "mpegts", str(segment)], check=True)
    key, iv = b"0123456789abcdef", bytes(16)
    cipher = jclass("javax.crypto.Cipher").getInstance("AES/CBC/PKCS5Padding")
    cipher.init(1, jclass("javax.crypto.spec.SecretKeySpec")(key, "AES"), jclass("javax.crypto.spec.IvParameterSpec")(iv))
    encrypted = bytes(value & 255 for value in cipher.doFinal(segment.read_bytes()))
    requested_ranges = []

    def handler(request):
        if request.url.path.endswith(".m3u8"):
            return httpx.Response(200, text='#EXTM3U\n#EXT-X-TARGETDURATION:2\n#EXT-X-KEY:METHOD=AES-128,URI="key",IV=0x00000000000000000000000000000000\n#EXTINF:2,\nsegment.ts\n#EXT-X-ENDLIST\n')
        if request.url.path.endswith("/key"): return httpx.Response(200, content=key)
        if request.url.path.endswith(".ts"): return httpx.Response(200, content=encrypted)
        if request.url.path.endswith(".srt"):
            return httpx.Response(200, text="1\n00:00:00,000 --> 00:00:01,000\nNative subtitle probe\n")
        start = 0
        headers = {"content-type": "video/mp4", "etag": '"native-fixture-v1"', "accept-ranges": "bytes"}
        if "range" in request.headers:
            requested_ranges.append(request.headers["range"])
            start = int(request.headers["range"].split("=")[1].split("-")[0])
            headers["content-range"] = f"bytes {start}-{len(payload)-1}/{len(payload)}"
        headers["content-length"] = str(len(payload) - start)
        return httpx.Response(206 if "range" in request.headers else 200, headers=headers, content=payload[start:])

    async def transfer():
        original_client, original_safe = manager._create_async_client, media_module.is_safe_url
        manager._create_async_client = lambda **kwargs: httpx.AsyncClient(transport=httpx.MockTransport(handler), trust_env=False)
        media_module.is_safe_url = lambda url, *a, **kw: urlparse(str(url)).hostname == "fixtures.animan.invalid"
        tasks = []
        try:
            url = "https://fixtures.animan.invalid/video.mp4"
            direct = DownloadTask(animeName="Native probe", episodeNumber=1, version="VO", fileName="direct.mp4",
                savePath=str(root / "direct.mp4"), fileUrl=url, status=DownloadStatus.DOWNLOADING,
                downloadSubtitles=True, subtitlesJson=json.dumps([{"url": "https://fixtures.animan.invalid/sub.srt", "lang": "en", "label": "English"}]))
            tasks.append(direct); manager.tasks[direct.id] = direct; manager.task_order.append(direct.id)
            Path(direct.savePath + ".part").write_bytes(payload[:len(payload)//2])
            write_metadata(Path(direct.savePath + ".part.resume.json"), {"validator": '"native-fixture-v1"', "total": len(payload)})
            await manager._download_single_file(direct, url)
            assert direct.status == DownloadStatus.COMPLETED, direct.error
            assert not direct.error, direct.error
            assert requested_ranges and direct.savePath.endswith(".mkv")
            streams = json.loads(media_tools.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", direct.savePath], check=True).stdout)["streams"]
            assert any(s["codec_type"] == "subtitle" and s["tags"].get("language") == "eng" for s in streams)
            hls = DownloadTask(animeName="Native probe", episodeNumber=2, version="VO", fileName="hls.mp4",
                              savePath=str(root / "hls.mp4"), status=DownloadStatus.DOWNLOADING)
            tasks.append(hls); manager.tasks[hls.id] = hls; manager.task_order.append(hls.id)
            await manager._download_hls_segments_native(hls, "https://fixtures.animan.invalid/playlist.m3u8")
            assert hls.status == DownloadStatus.COMPLETED, hls.error
            assert not hls.error, hls.error
            verification = verification_service.verify_file(hls.savePath)
            assert verification.valid and "mp4" in verification.formatName, verification.error
            # Instrumentation also opens the shared copies and compares hashes.
            return {"direct_resume": True, "aes128_hls": True, "subtitle_mux": True,
                    "media_paths": [direct.savePath, hls.savePath], "decode_verification": True}
        finally:
            manager._create_async_client, media_module.is_safe_url = original_client, original_safe
            for task in tasks:
                manager.tasks.pop(task.id, None)
                if task.id in manager.task_order: manager.task_order.remove(task.id)

    assert _loop is not None
    return asyncio.run_coroutine_threadsafe(transfer(), _loop).result(timeout=180)
