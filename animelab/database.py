"""Shared SQLite connection policy, migrations and explicit units of work."""
from contextlib import contextmanager
from pathlib import Path
import threading

from sqlalchemy import create_engine, event
from sqlalchemy.orm import declarative_base, sessionmaker
from animelab.config import settings
from animelab.sqlite_conn import configure_connection, sqlite_connection

Base = declarative_base()
_INIT_DB_LOCK = threading.Lock()


def create_database_engine(url):
    result = create_engine(url, connect_args={'check_same_thread': False, 'timeout': 5}, echo=False)
    event.listen(result, 'connect', lambda connection, record: configure_connection(connection))
    return result


engine = create_database_engine(settings.DATABASE_URL)
SessionLocal = sessionmaker(autocommit=False, autoflush=False, expire_on_commit=False, bind=engine)


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
    with _INIT_DB_LOCK:
        import animelab.models  # Register models before applying the first migration.
        animelab.models.register_all()
        from animelab.migrations import migrate
        owned = path is not None and str(path) != str(settings.DATABASE_PATH)
        db_path = str(path or settings.DATABASE_PATH)
        if db_path != ':memory:':
            Path(db_path).parent.mkdir(parents=True, exist_ok=True)
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
