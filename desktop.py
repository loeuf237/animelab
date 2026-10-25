"""Desktop launcher and offline checks for the packaged Python + Vue app."""
import argparse
import gc
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import tempfile
import threading
import time
from urllib.request import ProxyHandler, build_opener
import webbrowser
from animan import __version__

# Windowed PyInstaller executables have no console streams on Windows.
for _stream in ("stdin", "stdout", "stderr"):
    if getattr(sys, _stream) is None:
        setattr(sys, _stream, open(os.devnull, "r" if _stream == "stdin" else "w", encoding="utf-8"))

logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(name)s: %(message)s")
logger = logging.getLogger("animan.desktop")
if os.getenv("ANIMAN_LOG_FILE"):
    logging.getLogger().addHandler(logging.FileHandler(os.environ["ANIMAN_LOG_FILE"], encoding="utf-8"))


def configure_bundled_tools():
    if getattr(sys, "frozen", False):
        directory = Path(sys._MEIPASS) / "bin"
        os.environ["PATH"] = str(directory) + os.pathsep + os.environ.get("PATH", "")


def find_available_port(default_port=8080):
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        try:
            sock.bind(("127.0.0.1", default_port))
        except OSError:
            sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


def wait_for_server(port, max_retries=80, delay=.25):
    opener = build_opener(ProxyHandler({}))
    for _ in range(max_retries):
        try:
            with opener.open(f"http://127.0.0.1:{port}/openapi.json", timeout=.5) as response:
                if json.load(response)["info"]["version"] == __version__:
                    return True
        except (OSError, ValueError, KeyError):
            pass
        time.sleep(delay)
    return False


def start_server(port):
    os.environ.update(ANIMAN_PORT=str(port), ANIMAN_HOST="127.0.0.1", ANIMAN_RELOAD="false",
                      ANIMAN_ALLOWED_HOSTS='127.0.0.1,localhost')
    from animan.config import settings
    settings.PORT, settings.HOST = port, "127.0.0.1"
    settings.ALLOWED_HOSTS = ['127.0.0.1', 'localhost']
    from run import app
    import uvicorn
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port,
        log_level="warning", log_config=None, access_log=False, timeout_graceful_shutdown=10))
    worker = threading.Thread(target=server.run, daemon=True, name="AnimeLabServer")
    worker.start()
    if not wait_for_server(port) or not worker.is_alive() or not server.started:
        server.should_exit = True
        worker.join(timeout=15)
        raise RuntimeError("AnimeLab server did not become ready")
    return server, worker


def self_test():
    with tempfile.TemporaryDirectory(prefix="animan-package-check-") as directory:
        os.environ.update(ANIMAN_DB_PATH=str(Path(directory) / "test.sqlite3"),
            ANIMAN_CACHE_DIR=str(Path(directory) / "cache"), ANIMAN_DOWNLOAD_DIR=directory,
            ANIMAN_STARTUP_REFRESH="false")
        server, worker = start_server(find_available_port(0))
        try:
            from run import frontend_dist
            index = frontend_dist / "index.html"
            if not index.is_file() or not (frontend_dist / "assets").is_dir():
                raise RuntimeError("Packaged Vue frontend is missing")
            import re
            opener = build_opener(ProxyHandler({}))
            base = f"http://127.0.0.1:{server.config.port}"
            with opener.open(base + "/spa/", timeout=5) as response:
                html = response.read().decode()
            assets = re.findall(r'(?:src|href)="(/assets/[^" ]+)"', html)
            if not assets: raise RuntimeError("Vue asset URLs are missing")
            for asset in assets:
                with opener.open(base + asset, timeout=5) as response:
                    if not response.read(): raise RuntimeError("Empty frontend asset")
            from curl_cffi.requests import Session
            with Session(impersonate="chrome", trust_env=False) as client:
                response = client.get(base + "/openapi.json", timeout=5)
                response.raise_for_status()
                assert response.json()["info"]["version"] == __version__
            import webview
            from animan.services.extractors import extractor_registry
            import yt_dlp
            target = Path(directory) / "probe.mp4"
            for tool in ("ffmpeg", "ffprobe"):
                if not shutil.which(tool): raise RuntimeError(f"Missing bundled media tool: {tool}")
            subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "lavfi", "-i",
                "color=c=black:s=32x32:d=1", "-c:v", "mpeg4", str(target)],
                stdin=subprocess.DEVNULL, capture_output=True, check=True, timeout=30)
            probe = subprocess.run(["ffprobe", "-v", "error", "-show_streams", "-of", "json", str(target)],
                                   stdin=subprocess.DEVNULL, check=True, capture_output=True, text=True, timeout=30)
            assert any(stream["codec_type"] == "video" for stream in json.loads(probe.stdout)["streams"])
            from animan.services.verification_service import verification_service
            result = verification_service.verify_file(str(target))
            if not result.valid: raise RuntimeError(f"Packaged media integrity check failed: {result.error}")
            print(json.dumps({"version":__version__, "frontend":True, "http":True,
                              "curl_cffi":True, "media_tools":True, "gui_hardware_tested":False}))
        finally:
            server.should_exit = True
            worker.join(timeout=20)
            if worker.is_alive(): raise RuntimeError("Packaged server failed to stop")
            from animan.database import engine
            engine.dispose()
            gc.collect()  # Release SQLite handles before Windows removes temporary storage.


def configure_file_logging(path):
    from animan.diagnostics import install_logging
    install_logging()
    logging.getLogger().addHandler(RotatingFileHandler(path, maxBytes=2_000_000, backupCount=2, encoding='utf-8'))


def engine_worker(args, directory):
    """An owned child. A native crash can never take the administration console down."""
    configure_file_logging(directory / 'engine.log')
    # WinForms can raise on its GUI thread, outside main()'s try/except.
    def thread_failure(arguments):
        logger.error('Uncaught desktop engine thread error',
                     exc_info=(arguments.exc_type, arguments.exc_value, arguments.exc_traceback))
    threading.excepthook = thread_failure
    if args.control_url:
        from animan.diagnostics import remember_secret
        remember_secret(args.control_url.partition('#')[2])
    workdir = Path(args.worker)
    from animan.desktop.lifetime import acquire_engine_lock, parent_watch
    done, monitor = parent_watch(args.control_url, workdir)
    lock = None
    try:
        lock = acquire_engine_lock(directory, workdir)
        run_engine(args, workdir)
    finally:
        done.set()
        monitor.join(timeout=4)
        if lock:
            lock.release()


def run_engine(args, workdir):
    server, worker = start_server(args.port)
    (workdir / 'ready').touch()
    try:
        if args.headless:
            while worker.is_alive() and not (workdir / 'stop').exists():
                time.sleep(.2)
        else:
            from animan.desktop.window import open_window
            open_window(f'http://127.0.0.1:{args.port}/spa/', args.control_url, workdir)
    finally:
        # Lifespan shutdown pauses/persists transfers on the server event loop.
        server.should_exit = True
        worker.join(timeout=20)
        if worker.is_alive():
            raise RuntimeError('Engine did not shut down within 20 seconds')
        from animan.database import engine
        engine.dispose()


def main():
    parser = argparse.ArgumentParser(description="AnimeLab desktop")
    parser.add_argument("--version", action="version", version=__version__)
    parser.add_argument("--self-test", action="store_true", help="Offline packaged backend/frontend/media checks")
    parser.add_argument("--headless", action="store_true", help="Run without opening a window")
    parser.add_argument('--admin', action='store_true', help='Open desktop administration in the browser')
    parser.add_argument('--browser', action='store_true', help='Use the installed browser instead of a native window')
    parser.add_argument('--port', type=int, help='Local server port (1-65535); saved for future launches')
    commands = parser.add_mutually_exclusive_group()
    commands.add_argument('--stop', action='store_true', help='Stop the active desktop instance gracefully')
    commands.add_argument('--status', action='store_true', help='Report the active desktop instance status')
    commands.add_argument('--diagnose', action='store_true', help='Export quick desktop diagnostics as JSON')
    parser.add_argument('--report-file', type=Path, help='Destination JSON for --status or --diagnose')
    parser.add_argument('--gui-self-test', action='store_true', help='Create, render and close a real native window')
    parser.add_argument('--worker', help=argparse.SUPPRESS)
    parser.add_argument('--control-url', help=argparse.SUPPRESS)
    args = parser.parse_args()
    configure_bundled_tools()
    if args.self_test:
        self_test()
        return
    if args.gui_self_test:
        from animan.desktop.window import open_window
        with tempfile.TemporaryDirectory(prefix='animelab-gui-check-') as temporary:
            open_window(workdir=Path(temporary), probe=True)
        return
    from animan.desktop.state import InstanceLock, load_config, state_directory, valid_port, write_json
    from animan.desktop.control import remote_call, running_record
    from animan.desktop.supervisor import Supervisor
    directory = state_directory()
    if args.worker:
        if args.port is None:
            parser.error('A worker requires --port')
        valid_port(args.port)
        engine_worker(args, directory)
        return
    configure_file_logging(directory / 'desktop.log')
    record = running_record(directory)
    if args.stop or args.status or args.diagnose:
        if args.stop:
            remote_call(record, '/api/action', {'action': 'stop'})
            deadline = time.monotonic() + 45
            while time.monotonic() < deadline:
                try:
                    remote_call(record)
                except (OSError, ValueError):
                    return
                time.sleep(.2)
            raise RuntimeError('AnimeLab did not finish shutting down within 45 seconds')
        if args.diagnose:
            try:
                result = remote_call(record, '/api/diagnostics')
            except (OSError, ValueError):
                supervisor = Supervisor(directory, load_config(directory), headless=True)
                try:
                    result = supervisor.diagnose()
                finally:
                    supervisor.control.close()
            write_json(args.report_file or directory / 'diagnostics.json', result)
        else:
            result = remote_call(record)
            if args.report_file:
                write_json(args.report_file, result)
        print(json.dumps(result, indent=2))
        return
    lock = InstanceLock(directory)
    if not lock.acquire():
        # Wait briefly if another launcher is still creating its control plane.
        for _ in range(50):
            try:
                record = running_record(directory)
                status = remote_call(record)
                if args.port is not None or args.browser:
                    remote_call(record, '/api/config', {
                        'port': valid_port(args.port) if args.port is not None else status['configuredPort'],
                        'browser': args.browser or status['browser'],
                    })
                if not args.headless:
                    target = f"http://127.0.0.1:{record['port']}/#{record['token']}"
                    webbrowser.open(target if args.admin or not status['ready'] else status['url'])
                return
            except (OSError, ValueError):
                time.sleep(.1)
        raise RuntimeError('Another desktop instance owns the lock but is not responding')
    try:
        try:
            config = load_config(directory)
        except ValueError:
            if args.port is None:
                raise
            config = {'port': valid_port(args.port), 'browser': False}
        if args.port is not None:
            config['port'] = valid_port(args.port)
            write_json(directory / 'config.json', config)
        elif os.getenv('ANIMAN_PORT'):
            config['port'] = valid_port(int(os.environ['ANIMAN_PORT']))
        if args.browser:
            config['browser'] = True
        Supervisor(directory, config, headless=args.headless, admin=args.admin).run()
    finally:
        lock.release()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        logger.exception("AnimeLab failed to start or complete its package checks")
        if sys.platform == 'win32' and not any(flag in sys.argv for flag in ('--worker', '--self-test', '--gui-self-test')):
            import ctypes
            ctypes.windll.user32.MessageBoxW(None,
                'AnimeLab could not start. Check ~/.animan/desktop/desktop.log in your user folder.\n'
                'Open Administration from the extracted application folder, or use --admin --port 8080.',
                'AnimeLab — Startup error', 0x10)
        raise SystemExit(1)
