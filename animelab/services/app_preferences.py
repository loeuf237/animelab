"""Installation/account preferences, independent of WebView origins and ports."""
import json
import sqlite3
from animelab.sqlite_conn import sqlite_connection

DEFAULTS = {'onboardingCompleted': False, 'theme': None, 'palette': None,
            'checkUpdates': True, 'updateChannel': 'beta', 'downloadDirectory': None, 'lastSeenVersion': None}


def _read_startup_row():
    with sqlite_connection() as conn:
        return conn.execute("SELECT value FROM app_preferences WHERE key='startup'").fetchone()


def _needs_schema_init(exc: sqlite3.OperationalError) -> bool:
    detail = str(exc).lower()
    return 'app_preferences' in detail or 'locked' in detail or 'busy' in detail


def load():
    try:
        row = _read_startup_row()
    except sqlite3.OperationalError as exc:
        if not _needs_schema_init(exc):
            raise
        from animelab.database import init_db
        init_db()
        row = _read_startup_row()
    return {**DEFAULTS, **(json.loads(row['value']) if row else {})}


def _write_startup_values(changes):
    with sqlite_connection() as conn:
        conn.execute('BEGIN IMMEDIATE')
        row = conn.execute("SELECT value FROM app_preferences WHERE key='startup'").fetchone()
        values = {**DEFAULTS, **(json.loads(row['value']) if row else {}), **changes}
        conn.execute("INSERT INTO app_preferences(key,value) VALUES('startup',?) "
                     'ON CONFLICT(key) DO UPDATE SET value=excluded.value', (json.dumps(values),))
    return values


def save(changes):
    # Read/merge/write under the same write lock: completing setup must not
    # overwrite a concurrent update-channel or appearance change.
    try:
        return _write_startup_values(changes)
    except sqlite3.OperationalError as exc:
        if not _needs_schema_init(exc):
            raise
        from animelab.database import init_db
        init_db()
        return _write_startup_values(changes)


def restore_download_directory():
    from animelab.config import settings, IS_ANDROID
    from animelab.environment import getenv
    if IS_ANDROID or getenv('ANIMELAB_SHARED_WORKER') == '1':
        return
    # An explicit operator/launcher override always wins over a saved choice.
    directory = load()['downloadDirectory']
    current_override = getenv('ANIMELAB_DOWNLOAD_DIR')
    if directory and (not current_override or current_override == load().get('downloadDirectoryOrigin')):
        from animelab.services.download_manager import download_manager
        settings.DOWNLOAD_DIR = download_manager.download_dir = directory
