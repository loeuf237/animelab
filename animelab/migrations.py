"""Ordered, transactional SQLite upgrades. No destructive downgrade on user data."""
from dataclasses import dataclass
from collections.abc import Callable, Sequence
from sqlalchemy.engine import Connection, Engine


@dataclass(frozen=True)
class Migration:
    version: int
    name: str
    apply: Callable[[Connection], None]


def bootstrap(conn):
    from animelab.database import Base
    Base.metadata.create_all(bind=conn)


def download_identity(conn):
    # Vérifier colonnes existantes de download_tasks
    result = conn.exec_driver_sql("PRAGMA table_info(download_tasks)").fetchall()
    existing_cols = {row[1] for row in result}
    new_cols = [
        ("verificationUrl", "VARCHAR"),
        ("animeUrl", "VARCHAR DEFAULT ''"),
        ("version", "VARCHAR DEFAULT ''"),
        ("verificationStatus", "VARCHAR DEFAULT 'UNVERIFIED'"),
        ("videoDuration", "FLOAT"),
        ("verifiedAt", "DATETIME"),
        ("verificationError", "VARCHAR"),
        ("selectedServer", "VARCHAR"),
        ("selectedQuality", "VARCHAR"),
        ("exportStatus", "VARCHAR NOT NULL DEFAULT 'NOT_REQUESTED'"),
        ("exportUrisJson", "VARCHAR NOT NULL DEFAULT '[]'"),
        ("exportDestination", "VARCHAR"),
        ("exportError", "VARCHAR"),
        ("exportAttempts", "INTEGER NOT NULL DEFAULT 0"),
        ("exportedAt", "DATETIME"),
    ]
    for col_name, col_type in new_cols:
        if col_name not in existing_cols:
            conn.exec_driver_sql(f"ALTER TABLE download_tasks ADD COLUMN {col_name} {col_type}")


def tracking_and_exports(conn):
    existing_favorites = {row[1] for row in conn.exec_driver_sql("PRAGMA table_info(favorites)")}
    for name, declaration in [
        ("autoDownloadVersion", "VARCHAR DEFAULT ''"),
        ("autoDownloadSubtitles", "BOOLEAN DEFAULT 0"),
        ("autoDownloadServer", "VARCHAR"),
        ("autoDownloadQuality", "VARCHAR"),
        ("autoDownloadInitialized", "BOOLEAN DEFAULT 0"),
        ("autoDownloadError", "VARCHAR"),
    ]:
        if name not in existing_favorites:
            conn.exec_driver_sql(f'ALTER TABLE favorites ADD COLUMN "{name}" {declaration}')
    # Older Android builds stored export failure in the transfer error.
    # Do not infer EXPORTED for old completed tasks without URI evidence.
    conn.exec_driver_sql("""
        UPDATE download_tasks SET exportStatus='EXPORT_FAILED', exportError=error,
            exportAttempts=MAX(exportAttempts, 1), error=NULL
        WHERE status='COMPLETED' AND error LIKE 'Android export failed;%'
    """)


def configuration_tables(conn):
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS network_proxy_settings (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            enabled INTEGER NOT NULL DEFAULT 0,
            proxy_type TEXT NOT NULL DEFAULT 'http',
            host TEXT NOT NULL DEFAULT '',
            port INTEGER DEFAULT NULL,
            username TEXT DEFAULT '',
            password TEXT DEFAULT '',
            custom_url TEXT DEFAULT '',
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS source_settings (
            source_id TEXT PRIMARY KEY,
            settings_json TEXT NOT NULL,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS extension_repos (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT UNIQUE NOT NULL,
            name TEXT NOT NULL,
            is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
    """)
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS imported_extensions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            repo_id INTEGER NOT NULL,
            pkg TEXT NOT NULL,
            name TEXT NOT NULL,
            lang TEXT NOT NULL,
            version TEXT,
            apk_url TEXT,
            base_url TEXT,
            icon_url TEXT,
            sources_meta TEXT,
            is_enabled INTEGER DEFAULT 0,
            recipe_json TEXT,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            FOREIGN KEY (repo_id) REFERENCES extension_repos(id) ON DELETE CASCADE,
            UNIQUE(repo_id, pkg)
        );
    """)
    conn.exec_driver_sql("""
        CREATE TABLE IF NOT EXISTS public_proxy_pool (id INTEGER PRIMARY KEY CHECK(id=1), payload TEXT NOT NULL)
    """)



def playback_tracking(conn):
    from animelab.models.playback import PlaybackProgress
    PlaybackProgress.__table__.create(bind=conn,checkfirst=True)


def extension_observability(conn):
    columns={row[1] for row in conn.exec_driver_sql('PRAGMA table_info(imported_extensions)')}
    if 'recipe_revision' not in columns:
        conn.exec_driver_sql('ALTER TABLE imported_extensions ADD COLUMN recipe_revision INTEGER NOT NULL DEFAULT 0')
    conn.exec_driver_sql('CREATE TABLE IF NOT EXISTS extension_recipe_versions ('
        'id INTEGER PRIMARY KEY, ext_id INTEGER NOT NULL REFERENCES imported_extensions(id) ON DELETE CASCADE, '
        'revision INTEGER NOT NULL, schema_version INTEGER NOT NULL, fingerprint TEXT NOT NULL, '
        'recipe_json TEXT NOT NULL, reason TEXT NOT NULL, created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, UNIQUE(ext_id,revision))')
    conn.exec_driver_sql('CREATE TABLE IF NOT EXISTS extension_health ('
        'ext_id INTEGER NOT NULL REFERENCES imported_extensions(id) ON DELETE CASCADE, operation TEXT NOT NULL, '
        'status TEXT NOT NULL, code TEXT NOT NULL, checked_at TEXT NOT NULL, success_at TEXT, '
        'failure_streak INTEGER NOT NULL DEFAULT 0, duration_ms FLOAT NOT NULL DEFAULT 0, result_count INTEGER NOT NULL DEFAULT 0, '
        'recipe_revision INTEGER NOT NULL DEFAULT 0, PRIMARY KEY(ext_id,operation))')


def download_preferences(conn):
    conn.exec_driver_sql('CREATE TABLE IF NOT EXISTS download_preferences ('
        'id INTEGER PRIMARY KEY CHECK(id=1), '
        'max_concurrent INTEGER NOT NULL CHECK(max_concurrent>=1), '
        'global_limit INTEGER NOT NULL CHECK(global_limit>=0), '
        'plex_org INTEGER NOT NULL CHECK(plex_org IN (0,1)), '
        'user_agent TEXT NOT NULL, default_server TEXT NOT NULL)')


def extension_update_management(conn):
    columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info(imported_extensions)')}
    new_cols = [
        ('installed_version', 'TEXT'),
        ('available_version', 'TEXT'),
        ('available_apk_url', 'TEXT'),
        ('has_update', 'INTEGER NOT NULL DEFAULT 0'),
        ('updated_at', 'TEXT'),
    ]
    for col_name, col_type in new_cols:
        if col_name not in columns:
            conn.exec_driver_sql(f'ALTER TABLE imported_extensions ADD COLUMN {col_name} {col_type}')
    conn.exec_driver_sql("""
        UPDATE imported_extensions
        SET available_version = COALESCE(available_version, version),
            available_apk_url = COALESCE(available_apk_url, apk_url),
            installed_version = CASE
                WHEN installed_version IS NOT NULL THEN installed_version
                WHEN is_enabled = 1 OR (recipe_json IS NOT NULL AND recipe_json != '') THEN version
                ELSE NULL
            END
    """)


def extension_update_source_url(conn):
    # Separate migration: installations may already have applied version 8.
    columns = {row[1] for row in conn.exec_driver_sql('PRAGMA table_info(imported_extensions)')}
    if 'available_base_url' not in columns:
        conn.exec_driver_sql('ALTER TABLE imported_extensions ADD COLUMN available_base_url TEXT')


MIGRATIONS = (
    Migration(1, 'core_tables', bootstrap),
    Migration(2, 'download_identity_and_verification', download_identity),
    Migration(3, 'tracking_and_native_export', tracking_and_exports),
    Migration(4, 'source_extension_and_network_settings', configuration_tables),
    Migration(5, 'playback_positions_and_selection', playback_tracking),
    Migration(6, 'extension_recipe_history_and_health', extension_observability),
    Migration(7, 'persistent_download_preferences', download_preferences),
    Migration(8, 'extension_update_management', extension_update_management),
    Migration(9, 'extension_update_source_url', extension_update_source_url),
)


def migrate(engine: Engine, migrations: Sequence[Migration] = MIGRATIONS) -> None:
    versions = [m.version for m in migrations]
    if versions != list(range(1, len(versions) + 1)):
        raise ValueError('Migration versions must be consecutive and start at 1')
    with engine.connect() as conn:
        try:
            # Explicit BEGIN is necessary: pysqlite otherwise auto-commits DDL.
            # IMMEDIATE also serializes simultaneous first starts across processes.
            conn.exec_driver_sql('BEGIN IMMEDIATE')
            conn.exec_driver_sql('CREATE TABLE IF NOT EXISTS schema_migrations ('
                                 'version INTEGER PRIMARY KEY, name TEXT NOT NULL, '
                                 'applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)')
            applied = dict(conn.exec_driver_sql('SELECT version, name FROM schema_migrations').all())
            if list(sorted(applied)) != versions[:len(applied)]:
                raise RuntimeError('Unknown or incomplete database migration history; use a compatible AnimeLab version')
            for migration in migrations:
                if migration.version in applied:
                    if applied[migration.version] != migration.name:
                        raise RuntimeError('Database migration identity mismatch')
                    continue
                migration.apply(conn)
                conn.exec_driver_sql('INSERT INTO schema_migrations(version, name) VALUES (?, ?)',
                                     (migration.version, migration.name))
            conn.commit()
        except BaseException:
            conn.rollback()
            raise
