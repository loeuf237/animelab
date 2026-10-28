"""Additive media ledger in each user's existing private database."""
import hashlib
import json
from pathlib import Path

from sqlalchemy import Column, ForeignKey, Integer, String, Table, delete, select

from animelab.database import Base

tracks = Table('media_track', Base.metadata,
    Column('task_id', String, ForeignKey('download_tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('track_id', String, primary_key=True), Column('kind', String, nullable=False),
    Column('metadata_json', String, nullable=False))
selections = Table('task_track_selection', Base.metadata,
    Column('task_id', String, ForeignKey('download_tasks.id', ondelete='CASCADE'), primary_key=True),
    Column('track_id', String, primary_key=True), Column('selection_json', String, nullable=False))
assets = Table('subtitle_asset', Base.metadata, Column('id', String, primary_key=True),
    Column('task_id', String, ForeignKey('download_tasks.id', ondelete='CASCADE'), nullable=False),
    Column('track_id', String, nullable=False), Column('path', String, nullable=False),
    Column('fingerprint', String), Column('provider', String))
attempts = Table('transfer_attempt', Base.metadata, Column('id', String, primary_key=True),
    Column('task_id', String, ForeignKey('download_tasks.id', ondelete='CASCADE'), nullable=False),
    Column('backend', String, nullable=False), Column('version', String, nullable=False),
    Column('representation', String, nullable=False), Column('status', String, nullable=False),
    Column('checkpoint_json', String, nullable=False, default='{}'))
artifacts = Table('output_artifact', Base.metadata, Column('id', String, primary_key=True),
    Column('task_id', String, ForeignKey('download_tasks.id', ondelete='CASCADE'), nullable=False),
    Column('path', String, nullable=False), Column('profile_json', String, nullable=False),
    Column('verified', Integer, nullable=False, default=0))


def sync_media_state(db, task):
    from animelab.services.media_contracts import normalize_tracks
    from animelab.services.output_profiles import private_snapshot
    from animelab.services.subtitle_service import normalize_subtitles
    info = json.loads(task.mediaJson)
    inventory = normalize_tracks(normalize_subtitles(task.subtitlesJson, task.downloadPageUrl or task.fileUrl), kind='subtitle')
    inventory += normalize_tracks(info.get('audioTracks'), task.downloadPageUrl or task.fileUrl)
    inventory += info.get('localSubtitleTracks', [])
    old = dict(db.execute(select(tracks.c.track_id, tracks.c.metadata_json).where(tracks.c.task_id == task.id)).all())
    for track in inventory:
        data = json.dumps(private_snapshot(track), sort_keys=True)
        if old.get(track['id']) == data:
            continue
        db.execute(delete(tracks).where(tracks.c.task_id == task.id, tracks.c.track_id == track['id']))
        db.execute(tracks.insert().values(task_id=task.id, track_id=track['id'], kind=track['kind'], metadata_json=data))
    # Retain past track/assets for recovery; selections are a task-local snapshot.
    db.execute(delete(selections).where(selections.c.task_id == task.id))
    for selection in json.loads(task.outputProfileJson).get('selections', []):
        db.execute(selections.insert().values(task_id=task.id, track_id=selection['trackId'], selection_json=json.dumps(selection)))
    attempt = info.get('transferAttempt')
    if attempt:
        db.execute(delete(attempts).where(attempts.c.id == attempt['id']))
        db.execute(attempts.insert().values(task_id=task.id, **attempt))
    for track in inventory:
        if track.get('path'):
            asset_id = hashlib.sha256((task.id + track['id'] + track['path']).encode()).hexdigest()
            db.execute(delete(assets).where(assets.c.id == asset_id))
            db.execute(assets.insert().values(id=asset_id, task_id=task.id, track_id=track['id'],
                path=track['path'], fingerprint=track.get('sha256'),
                provider=track.get('provider') or (track.get('provenance') or {}).get('provider')
                if isinstance(track.get('provenance'), dict) else track.get('provider')))
    if task.status.value == 'COMPLETED' and task.savePath:
        artifact_id = hashlib.sha256((task.id + task.savePath).encode()).hexdigest()
        db.execute(delete(artifacts).where(artifacts.c.id == artifact_id))
        db.execute(artifacts.insert().values(id=artifact_id, task_id=task.id, path=task.savePath,
            profile_json=task.outputProfileJson, verified=int(task.verificationStatus == 'VALID')))
