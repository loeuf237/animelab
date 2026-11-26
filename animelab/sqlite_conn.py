"""Lightweight SQLite connection policy usable before SQLAlchemy loads."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3
import threading
import time

from animelab.config import settings

_WAL_LOCK = threading.Lock()


def configure_connection(connection):
    cursor = connection.cursor()
    try:
        cursor.execute('PRAGMA busy_timeout=30000')
        mode = cursor.execute('PRAGMA journal_mode').fetchone()
        if not mode or str(mode[0]).lower() != 'wal':
            with _WAL_LOCK:
                mode = cursor.execute('PRAGMA journal_mode').fetchone()
                if not mode or str(mode[0]).lower() != 'wal':
                    for attempt in range(6):
                        try:
                            cursor.execute('PRAGMA journal_mode=WAL')
                            break
                        except sqlite3.OperationalError as exc:
                            detail = str(exc).lower()
                            if 'locked' not in detail and 'busy' not in detail:
                                raise
                            if attempt == 5:
                                raise
                            time.sleep(0.05 * (attempt + 1))
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()


@contextmanager
def sqlite_connection(path=None):
    """Commit/rollback and CLOSE every settings connection, including failures."""
    path = str(path or settings.DATABASE_PATH)
    if path != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=30)
    connection.row_factory = sqlite3.Row
    try:
        configure_connection(connection)
        with connection:
            yield connection
    finally:
        connection.close()
