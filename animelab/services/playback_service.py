import uuid
from datetime import datetime, timezone
from pydantic import BaseModel, Field, ConfigDict
from sqlalchemy import select
from animelab.database import transaction
from animelab.models.playback import PlaybackProgress
from animelab.models.download_task import DownloadTaskEntity
from animelab.models.auto_download import episode_version
from animelab.api_errors import APIProblem


class PlaybackSelection(BaseModel):
    quality: str = Field(default='HD',max_length=150)
    server: str = Field(default='auto',max_length=4096)
    subtitle: str | None = Field(default='auto',max_length=500)
    audio: str | None = Field(default=None,max_length=500)


class PlaybackOpen(BaseModel):
    taskId: str | None = Field(default=None,max_length=36)
    source: str = Field(default='',max_length=255)
    animeUrl: str = Field(default='',max_length=4096)
    animeName: str = Field(default='',max_length=500)
    episodeNumber: int = Field(default=0,ge=0)
    version: str = Field(default='',max_length=40)


class PlaybackSave(BaseModel):
    model_config = ConfigDict(allow_inf_nan=False)
    sessionId: str = Field(pattern=r'^[0-9a-f]{32}$')
    sequence: int = Field(ge=1,le=2147483647)
    positionSeconds: float = Field(ge=0,le=604800)
    durationSeconds: float = Field(ge=0,le=604800)
    selection: PlaybackSelection = Field(default_factory=PlaybackSelection)
    final: bool = False
    ended: bool = False


class PlaybackState(BaseModel):
    sessionId: str
    source: str
    animeUrl: str
    episodeNumber: int
    version: str
    positionSeconds: float
    durationSeconds: float
    selection: PlaybackSelection


class PlaybackService:
    def open(self, body: PlaybackOpen):
        source, url, number, version = body.source,body.animeUrl,body.episodeNumber,episode_version(body.version)
        with transaction() as db:
            # Serialize the read/update pair across browser windows/processes.
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            if body.taskId:
                task=db.get(DownloadTaskEntity,body.taskId)
                if not task: raise APIProblem('playback_task_missing',status=404,category='not_found')
                source=task.source or 'french-manga';url=task.animeUrl or 'task:'+task.id
                number=task.episodeNumber;version=episode_version(task.version)
            if not source or not url:
                raise APIProblem('playback_identity_missing',category='validation')
            row=db.scalar(select(PlaybackProgress).filter_by(source=source,animeUrl=url,episodeNumber=number,version=version))
            if row is None:
                row=PlaybackProgress(source=source,animeUrl=url,episodeNumber=number,version=version)
                db.add(row)
            row.sessionId=uuid.uuid4().hex;row.lastSequence=0
            db.flush()
            position=row.positionSeconds
            if position < 3 or (row.durationSeconds and position >= row.durationSeconds-5): position=0
            return PlaybackState(sessionId=row.sessionId,source=source,animeUrl=url,episodeNumber=number,version=version,
                positionSeconds=position,durationSeconds=row.durationSeconds,selection=PlaybackSelection.model_validate_json(row.selectionJson))

    def save(self, body: PlaybackSave):
        with transaction() as db:
            db.connection().exec_driver_sql('BEGIN IMMEDIATE')
            row=db.scalar(select(PlaybackProgress).filter_by(sessionId=body.sessionId))
            if row is None or body.sequence <= row.lastSequence:
                return {'success':True,'accepted':False,'reason':'superseded'}
            now=datetime.now(timezone.utc)
            previous=row.updatedAt.replace(tzinfo=timezone.utc) if row.updatedAt.tzinfo is None else row.updatedAt
            selection=body.selection.model_dump_json()
            if not body.final and not body.ended and selection==row.selectionJson and (now-previous).total_seconds()<2:
                return {'success':True,'accepted':False,'reason':'throttled'}
            row.lastSequence=body.sequence
            row.positionSeconds=0 if body.ended else min(body.positionSeconds,body.durationSeconds) if body.durationSeconds else body.positionSeconds
            row.durationSeconds=body.durationSeconds
            row.selectionJson=selection;row.updatedAt=now
            return {'success':True,'accepted':True}


playback_service=PlaybackService()
