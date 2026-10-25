"""A05: upgrades on copies, real DDL rollback and atomic state/progress/export."""
import sqlite3
from pathlib import Path

import pytest
from sqlalchemy.orm import sessionmaker

from animelab import database
from animelab.database import create_database_engine, sqlite_connection, transaction, Base
from animelab.migrations import MIGRATIONS, Migration, migrate
from animelab.models.download_task import DownloadTask, DownloadStatus, DownloadTaskEntity, ExportStatus
from animelab.models.watch_progress import WatchProgress
from animelab.services.library_service import library_service
from animelab.services.proxy_service import ProxyService
from animelab.services.source_settings_service import SourceSettingsService
from animelab.services.extension_service import ExtensionService


def test_upgrade_backup_is_repeatable_and_keeps_all_existing_rows(tmp_path):
    from animelab.models.favorite import FavoriteAnime
    # The old-schema fixture intentionally omits A01/A02 fields.
    from sqlalchemy import MetaData, Table
    legacy = tmp_path / 'old.sqlite'
    original = create_database_engine('sqlite:///' + str(legacy))
    metadata = MetaData()
    for model in (DownloadTaskEntity, FavoriteAnime, WatchProgress):
        table = model.__table__.to_metadata(metadata)
        for column in list(table.columns):
            if column.name.startswith(('export', 'autoDownload')) and column.name != 'autoDownload':
                table._columns.remove(column)
    metadata.create_all(original)
    with original.begin() as db:
        db.exec_driver_sql("INSERT INTO favorites(url,title,source,autoDownload,lastKnownEpisode) VALUES ('https://series.example','Series','animepahe',1,12)")
        db.execute(metadata.tables['download_tasks'].insert().values(id='episode',animeName='Series',episodeNumber=2,fileName='episode.mp4',status='COMPLETED',error='Android export failed; denied'))
        db.exec_driver_sql("INSERT INTO watch_progress(animeUrl,animeName,episodeNumber,version,watched,downloaded) VALUES ('https://series.example','Series',2,'VF',1,1)")
    original.dispose()
    copy = tmp_path / 'upgrade-copy.sqlite'
    with sqlite3.connect(legacy) as source, sqlite3.connect(copy) as destination:
        source.backup(destination)
    engine = create_database_engine('sqlite:///' + str(copy))
    try:
        migrate(engine); migrate(engine)
        with engine.connect() as db:
            assert db.exec_driver_sql('SELECT version FROM schema_migrations ORDER BY version').scalars().all() == [m.version for m in MIGRATIONS]
            assert db.exec_driver_sql('SELECT source,lastKnownEpisode,autoDownload FROM favorites').one() == ('animepahe', 12, 1)
            assert db.exec_driver_sql('SELECT watched,downloaded,version FROM watch_progress').one() == (1, 1, 'VF')
            task = db.exec_driver_sql('SELECT status,error,exportStatus,exportError FROM download_tasks').one()
            assert task == ('COMPLETED', None, 'EXPORT_FAILED', 'Android export failed; denied')
        with sqlite3.connect(legacy) as db:
            assert 'exportStatus' not in {row[1] for row in db.execute('PRAGMA table_info(download_tasks)')}
    finally:
        engine.dispose()


def test_failed_ddl_and_data_migration_roll_back_together_then_retry(tmp_path):
    engine = create_database_engine('sqlite:///' + str(tmp_path / 'rollback.sqlite'))
    migrate(engine)
    def fault(conn):
        conn.exec_driver_sql('ALTER TABLE favorites ADD COLUMN accidental TEXT')
        conn.exec_driver_sql("INSERT INTO source_settings(source_id,settings_json) VALUES ('partial','{}')")
        raise RuntimeError('simulated migration failure')
    try:
        with pytest.raises(RuntimeError, match='simulated'):
            migrate(engine, (*MIGRATIONS, Migration(len(MIGRATIONS)+1, 'failing_upgrade', fault)))
        with engine.connect() as conn:
            assert 'accidental' not in {r[1] for r in conn.exec_driver_sql('PRAGMA table_info(favorites)')}
            assert conn.exec_driver_sql("SELECT count(*) FROM source_settings WHERE source_id='partial'").scalar() == 0
            assert conn.exec_driver_sql('SELECT MAX(version) FROM schema_migrations').scalar() == len(MIGRATIONS)
        migrate(engine)
        with engine.begin() as conn:
            conn.exec_driver_sql("INSERT INTO schema_migrations(version,name) VALUES (99,'future')")
        with pytest.raises(RuntimeError, match='Unknown'):
            migrate(engine)
    finally:
        engine.dispose()


def test_settings_connections_share_policy_rollback_and_close(tmp_path):
    path = tmp_path / 'settings.sqlite'
    proxy, sources, extensions = ProxyService(str(path)), SourceSettingsService(str(path)), ExtensionService(str(path))
    for service in (proxy, sources, extensions):
        with service._get_conn() as conn:
            assert conn.execute('PRAGMA foreign_keys').fetchone()[0] == 1
            assert conn.execute('PRAGMA journal_mode').fetchone()[0] == 'wal'
            assert conn.execute('PRAGMA busy_timeout').fetchone()[0] == 5000
        with pytest.raises(sqlite3.ProgrammingError): conn.execute('select 1')
    with pytest.raises(RuntimeError):
        with sqlite_connection(path) as conn:
            conn.execute("INSERT INTO source_settings(source_id,settings_json) VALUES ('rollback','{}')")
            raise RuntimeError('abort transaction')
    with sqlite_connection(path) as conn:
        assert conn.execute("SELECT count(*) FROM source_settings WHERE source_id='rollback'").fetchone()[0] == 0


def test_completion_progress_export_and_tracking_commit_or_roll_back_as_one(tmp_path, monkeypatch):
    import importlib
    library = importlib.import_module('animelab.services.library_service')
    from animelab.models.auto_download import AutoDownloadEpisode
    engine = create_database_engine('sqlite:///' + str(tmp_path / 'atomic.sqlite'))
    migrate(engine)
    sessions = sessionmaker(bind=engine)
    monkeypatch.setattr(library, 'SessionLocal', sessions)
    task = DownloadTask(animeName='Series',animeUrl='https://series.example', episodeNumber=2, version='VF')
    library_service.save_task(task)
    with transaction(sessions) as db:
        db.add(AutoDownloadEpisode(source=task.source,animeUrl=task.animeUrl,episodeNumber=2,version='VF',episodeUrl='https://series.example/2',taskId=task.id,state='PLANNED'))
    mark = library_service._mark_as_downloaded
    def fail_after_progress(db, *args):
        mark(db, *args)
        raise RuntimeError('failure after progress update')
    task.status = DownloadStatus.COMPLETED
    task.exportStatus = ExportStatus.EXPORTED
    task.exportUrisJson = '["content://downloads/2"]'
    try:
        with monkeypatch.context() as fault:
            fault.setattr(library_service, '_mark_as_downloaded', fail_after_progress)
            with pytest.raises(RuntimeError): library_service.save_task(task)
        with sessions() as db:
            stored=db.get(DownloadTaskEntity,task.id)
            assert stored.status == 'PENDING' and stored.exportStatus == 'NOT_REQUESTED'
            assert db.query(WatchProgress).count() == 0
            assert db.query(AutoDownloadEpisode).one().state == 'PLANNED'
        library_service.save_task(task)
        with sessions() as db:
            stored=db.get(DownloadTaskEntity,task.id)
            assert stored.status == 'COMPLETED' and stored.exportUrisJson == task.exportUrisJson
            assert db.query(WatchProgress).one().downloaded
            assert db.query(AutoDownloadEpisode).one().state == 'COMPLETED'
    finally:
        engine.dispose()
