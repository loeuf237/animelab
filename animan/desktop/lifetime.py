"""The engine must not outlive a crashed supervisor, even in windowless builds."""
import logging
import os
import threading
import time
from urllib.parse import urlsplit

from .control import remote_call
from .state import InstanceLock


def parent_watch(control_url, workdir):
    url = urlsplit(control_url)
    if url.scheme != 'http' or url.hostname != '127.0.0.1' or not url.port or len(url.fragment) < 32:
        raise ValueError('A worker requires a private loopback supervisor URL')
    record = {'port': url.port, 'token': url.fragment, 'instanceId': url.fragment[:16]}
    done = threading.Event()

    def watch():
        failures = 0
        while not done.wait(1):
            if (workdir / 'stop').exists():
                return
            try:
                remote_call(record, timeout=2)
                failures = 0
            except (OSError, ValueError):
                failures += 1
                if failures >= 3:
                    logging.getLogger('animan.desktop').warning('Supervisor unavailable; stopping its engine')
                    (workdir / 'stop').touch()
                    if not done.wait(30):
                        logging.getLogger('animan.desktop').error('Engine shutdown timed out after losing its supervisor')
                        os._exit(1)  # Only this orphaned child, after its graceful shutdown deadline.
                    return

    thread = threading.Thread(target=watch, daemon=True, name='AnimeLabParentWatch')
    thread.start()
    return done, thread


def acquire_engine_lock(directory, workdir):
    # A replacement supervisor waits for an orphan to finish its graceful shutdown.
    lock = InstanceLock(directory, 'engine.lock')
    deadline = time.monotonic() + 50
    while not lock.acquire():
        if (workdir / 'stop').exists() or time.monotonic() >= deadline:
            raise RuntimeError('Previous desktop engine is still stopping; retry from Administration')
        time.sleep(.2)
    return lock
