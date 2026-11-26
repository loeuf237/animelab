"""Lightweight SQLite connection policy usable before SQLAlchemy loads."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from animelab.config import settings


def configure_connection(connection):
    cursor = connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()


@contextmanager
def sqlite_connection(path=None):
    """Commit/rollback and CLOSE every settings connection, including failures."""
    path = str(path or settings.DATABASE_PATH)
    if path != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5)
    connection.row_factory = sqlite3.Row
    try:
        configure_connection(connection)
        with connection:
            yield connection
    finally:
        connection.close()
