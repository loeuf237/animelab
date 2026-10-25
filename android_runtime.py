"""Android bootstrap. Configure storage and JNI before importing the engine."""
import asyncio
from contextlib import asynccontextmanager
from email.utils import formatdate
from http.cookies import SimpleCookie
import json
import os
from pathlib import Path
import time
from urllib.parse import urlparse

_loop = None


class VerificationWindow:
    def __init__(self, url, bridge):
        self.url, self.bridge = url, bridge
        from animelab.services.source_http import USER_AGENT
        self.bridge.open(url, USER_AGENT)

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


def start(data_dir, cache_dir, port, token, test_mode=False):
    global _loop
    os.environ.update({
        # Shared engine cache also contains installed extensions and user proxy
        # lists. Android may evict cacheDir, so preserve this state in filesDir.
        "ANIMAN_DATA_DIR": data_dir, "ANIMAN_CACHE_DIR": str(Path(data_dir) / "engine-state"),
        "ANIMAN_DB_PATH": str(Path(data_dir) / "db/animan.sqlite3"),
        "ANIMAN_DOWNLOAD_DIR": str(Path(data_dir) / "downloads"),
        "ANIMAN_HOST": "127.0.0.1", "ANIMAN_PORT": str(port),
    })
    if test_mode:
        os.environ["ANIMAN_STARTUP_REFRESH"] = "false"
    import tempfile
    tempfile.tempdir = cache_dir
    from java import jclass
    from animelab import media_tools, platform_events
    media_tools.configure_android(jclass("com.animan.app.MediaBridge"), jclass("com.animan.app.CryptoBridge"))
    hooks = jclass("com.animan.app.NativeHooks")
    verification = jclass("com.animan.app.VerificationBridge")
    storage = jclass("com.animan.app.StorageAccess")
    platform_events.storage_status_handler = lambda: json.loads(str(storage.status()))
    platform_events.storage_action_handler = lambda action: json.loads(str(storage.request(action)))
    import run
    from animelab.android_security import AndroidSessionMiddleware
    from animelab.models.download_task import DownloadStatus, ExportStatus
    from animelab.services.download_manager import download_manager
    run.app.add_middleware(AndroidSessionMiddleware, token=token)
    run.browser_verification.platform = "android"
    run.browser_verification.webview_opener = lambda url: VerificationWindow(url, verification)

    def notify(task):
        active = [t for t in download_manager.get_all_tasks() if t.status in (
            DownloadStatus.PENDING, DownloadStatus.DOWNLOADING, DownloadStatus.RETRYING, DownloadStatus.MUXING)
            or (t.exportStatus == ExportStatus.EXPORTING and not t.paused and not t.cancelled)]
        native_status = "CANCELLED" if task.cancelled else "PAUSED" if task.paused else "EXPORTING" if task.exportStatus == ExportStatus.EXPORTING else task.status.value
        if not hooks.progress(len(active), int(task.progress), task.fileName, task.id, native_status) and active and _loop:
            _loop.call_soon_threadsafe(download_manager.pause_all_downloads)

    platform_events.progress_handler = notify
    def export_completed(task):
        from animelab.services.subtitle_service import normalize_subtitles
        if not task.savePath or not Path(task.savePath).is_file():
            raise FileNotFoundError("The private download is missing")
        paths = [task.savePath]
        for track in normalize_subtitles(task.subtitlesJson):
            if not track.get("muxed") and track.get("path"):
                paths.append(track["path"])
        if task.savePathSubtitle and not any(track.get("muxed") for track in normalize_subtitles(task.subtitlesJson)):
            try:
                sidecars = json.loads(task.savePathSubtitle)
            except (ValueError, TypeError):
                sidecars = task.savePathSubtitle
            paths.extend(sidecars if isinstance(sidecars, list) else [sidecars])
        uris = [str(hooks.exportFile(path, task.id)) for path in dict.fromkeys(paths) if path and Path(path).is_file()]
        if not uris:
            raise FileNotFoundError("The private download is missing")
        return {"uris": uris, "destination": json.loads(str(storage.status()))["destination"]}

    platform_events.completed_handler = export_completed
    original_lifespan = run.app.router.lifespan_context

    @asynccontextmanager
    async def lifespan(app):
        global _loop
        _loop = asyncio.get_running_loop()
        async with original_lifespan(app):
            hooks.ready()
            yield
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
