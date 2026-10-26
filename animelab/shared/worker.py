"""Internal entry point, launched only by the shared gateway with private env."""
import asyncio
from contextlib import asynccontextmanager
import json
import hashlib
import os
from pathlib import Path
import socket
import sys
import threading
import logging


def parent_input():
    if sys.stdin is not None:
        return sys.stdin.buffer
    if os.name == 'nt':
        # Windowed PyInstaller builds set sys.stdin=None even when Popen gave
        # them a valid inherited pipe. Read that OS handle, not os.devnull.
        import ctypes
        from ctypes import wintypes
        import msvcrt
        kernel = ctypes.WinDLL('kernel32', use_last_error=True)
        kernel.GetStdHandle.argtypes = [wintypes.DWORD]
        kernel.GetStdHandle.restype = wintypes.HANDLE
        handle = kernel.GetStdHandle(wintypes.DWORD(-10).value)
        if handle in (None, 0, ctypes.c_void_p(-1).value):
            raise RuntimeError('Missing parent lifetime pipe')
        return os.fdopen(msvcrt.open_osfhandle(handle, os.O_RDONLY | os.O_BINARY), 'rb')
    raise RuntimeError('Missing parent lifetime pipe')


def main():
    token = os.environ.get('ANIMELAB_SHARED_WORKER_TOKEN', '')
    if len(token) < 32 or os.environ.get('ANIMELAB_SHARED_WORKER') != '1':
        raise SystemExit('This is an internal worker entry point')
    os.umask(0o077)
    channel = parent_input()
    if sys.stdout is None or getattr(sys.stdout, 'name', None) == os.devnull:
        logging.getLogger().addHandler(logging.FileHandler(Path.home() / 'engine.log', encoding='utf-8'))
    from animelab.desktop.state import InstanceLock
    engine_lock = InstanceLock(Path.home(), 'engine.lock')
    if not engine_lock.acquire():
        raise SystemExit('An engine already owns this account workspace')
    # A blocked native import must leave useful evidence before the supervisor's
    # startup deadline, including on windowed Windows executables.
    import faulthandler
    startup_trace = (Path.home() / 'engine.log').open('ab')
    faulthandler.dump_traceback_later(40, file=startup_trace)
    import uvicorn
    from run import app, lifespan
    from animelab.shared.workers import WorkerBoundary

    listener = socket.socket()
    listener.bind(('127.0.0.1', 0))
    listener.listen(128)
    ready = Path.home() / 'ready.json'

    @asynccontextmanager
    async def private_lifespan(app):
        async with lifespan(app):
            if os.environ.get('ANIMELAB_SHARED_DOWNLOAD') != '1':
                from animelab.services.watchdog_service import watchdog_service
                from animelab.services.download_manager import download_manager
                watchdog_service.stop()
                await download_manager.shutdown()
            temporary = ready.with_suffix('.tmp')
            temporary.write_text(json.dumps({'pid': os.getpid(), 'port': listener.getsockname()[1],
                                             'instance': hashlib.sha256(token.encode()).hexdigest()}))
            temporary.replace(ready)
            faulthandler.cancel_dump_traceback_later()
            startup_trace.close()
            try:
                yield
            finally:
                ready.unlink(missing_ok=True)

    app.router.lifespan_context = private_lifespan
    server = uvicorn.Server(uvicorn.Config(WorkerBoundary(app, token), log_level='warning',
        access_log=False, proxy_headers=False, timeout_graceful_shutdown=20))

    def parent_watch():
        while channel.read(1):
            pass
        channel.close()
        server.should_exit = True

    threading.Thread(target=parent_watch, daemon=True).start()
    try:
        asyncio.run(server.serve(sockets=[listener]))
    finally:
        listener.close()
        ready.unlink(missing_ok=True)
        engine_lock.release()


if __name__ == '__main__':
    main()
