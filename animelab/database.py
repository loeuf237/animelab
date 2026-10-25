"""Shared SQLite connection policy, migrations and explicit units of work."""
from contextlib import contextmanager
from pathlib import Path
import sqlite3

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from animelab.config import settings

Base = declarative_base()


def configure_connection(connection):
    cursor = connection.cursor()
    try:
        cursor.execute('PRAGMA journal_mode=WAL')
        cursor.execute('PRAGMA synchronous=NORMAL')
        cursor.execute('PRAGMA busy_timeout=5000')
        cursor.execute('PRAGMA foreign_keys=ON')
    finally:
        cursor.close()


def create_database_engine(url):
    result = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 5}, echo=False)
    event.listen(result, 'connect', lambda connection, record: configure_connection(connection))
    return result


engine = create_database_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


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


@contextmanager
def transaction(factory=None):
    """One ORM unit of work; return loaded objects safely after its commit."""
    db = (factory or SessionLocal)(expire_on_commit=False)
    try:
        yield db
        db.commit()
    except BaseException:
        db.rollback()
        raise
    finally:
        db.close()


def init_db(path=None):
    import animelab.models  # Register models before applying the first migration.
    from animelab.migrations import migrate
    owned = path is not None and str(path) != str(settings.DATABASE_PATH)
    if owned and str(path) != ':memory:':
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    target = create_database_engine('sqlite:///' + str(path)) if owned else engine
    try:
        migrate(target)
    except Exception as exc:
        raise RuntimeError('Unable to update the AnimeLab database schema') from exc
    finally:
        if owned:
            target.dispose()


def get_db():
    with transaction() as db:
        yield db
