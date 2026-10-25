from datetime import datetime, timezone
from typing import List, Optional, Set

from animelab.database import SessionLocal, transaction
from animelab.models.favorite import FavoriteAnime
from animelab.models.watch_progress import WatchProgress
from animelab.models.auto_download import AutoDownloadEpisode, episode_version
from animelab.models.download_task import DownloadTask, DownloadTaskEntity, DownloadStatus, ExportStatus
from sqlalchemy import or_, and_, func

class LibraryService:
    # -------------------------------------------------------------------------
    # FAVORIS
    # -------------------------------------------------------------------------

    def add_favorite(self, url: str, title: str, image_url: str = "", source: str = "french-manga",
                     auto_download_version: str = "") -> FavoriteAnime:
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                return fav
            fav = FavoriteAnime(
                url=url,
                title=title,
                imageUrl=image_url,
                source=source,
                autoDownloadVersion=episode_version(auto_download_version),
                addedAt=datetime.now(timezone.utc),
            )
            db.add(fav)
            db.flush()
            db.refresh(fav)
            return fav

    def remove_favorite(self, url: str):
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                db.query(AutoDownloadEpisode).filter_by(animeUrl=fav.url, source=fav.source).delete()
                db.delete(fav)
                db.flush()

    def remove_all_favorites(self):
        with transaction(SessionLocal) as db:
            db.query(AutoDownloadEpisode).delete()
            db.query(FavoriteAnime).delete()
            db.flush()

    def is_favorite(self, url: str) -> bool:
        with transaction(SessionLocal) as db:
            return db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first() is not None

    def get_favorite(self, url: str) -> Optional[FavoriteAnime]:
        with transaction(SessionLocal) as db:
            return db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()

    def get_all_favorites(self) -> List[FavoriteAnime]:
        with transaction(SessionLocal) as db:
            return db.query(FavoriteAnime).order_by(FavoriteAnime.addedAt.desc()).all()

    def update_auto_download(self, url: str, auto_download: bool, **options) -> Optional[FavoriteAnime]:
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                fav.autoDownload = auto_download
                for key in ("autoDownloadVersion", "autoDownloadSubtitles", "autoDownloadServer", "autoDownloadQuality"):
                    if key in options:
                        setattr(fav, key, episode_version(options[key]) if key == "autoDownloadVersion" else options[key])
                fav.autoDownloadError = None
                db.flush()
                db.refresh(fav)
                return fav
            return None

    def set_auto_download_error(self, url, error):
        with transaction(SessionLocal) as db:
            db.query(FavoriteAnime).filter_by(url=url).update({"autoDownloadError": error})
            db.flush()

    def discover_auto_episodes(self, favorite, episodes, selected_versions):
        """Snapshot every variant, with separate discovery and task outcomes.

        A legacy numeric cursor is used only for the initial baseline. Once the
        snapshot exists, a new version of an old number is still a new identity.
        Ignored variants are baselined so changing a preference doesn't silently
        backfill an entire alternate-language catalogue.
        """
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter_by(id=favorite.id).first()
            if not fav or not fav.autoDownload:
                return []
            existing = {(e.episodeNumber, e.version): e for e in db.query(AutoDownloadEpisode).filter_by(
                source=fav.source, animeUrl=fav.url).all()}
            for episode, version, url in episodes:
                key = (episode.number, version)
                if key in existing:
                    # Signed player URLs may renew without changing the episode identity.
                    existing[key].episodeUrl = url
                    continue
                baseline = (version not in selected_versions or
                            (not fav.autoDownloadInitialized and episode.number <= (fav.lastKnownEpisode or 0)))
                entry = AutoDownloadEpisode(source=fav.source, animeUrl=fav.url,
                    episodeNumber=episode.number, version=version, episodeUrl=url,
                    state="BASELINE" if baseline else "DISCOVERED")
                db.add(entry)
                existing[key] = entry
            fav.autoDownloadInitialized = True
            fav.lastKnownEpisode = max([fav.lastKnownEpisode or 0] + [ep.number for ep, _, _ in episodes])
            fav.lastCheckedAt = datetime.now(timezone.utc)
            fav.autoDownloadError = None
            db.flush()
            return db.query(AutoDownloadEpisode).filter_by(source=fav.source, animeUrl=fav.url).filter(
                AutoDownloadEpisode.state == "DISCOVERED",
                AutoDownloadEpisode.version.in_(selected_versions)).all()

    def attach_auto_download_task(self, entry_id, task):
        with transaction(SessionLocal) as db:
            entry = db.get(AutoDownloadEpisode, entry_id)
            if entry:
                entry.taskId = task.id
                entry.state = task.status.value if task.status in (
                    DownloadStatus.COMPLETED, DownloadStatus.CANCELLED, DownloadStatus.FAILED) else "PLANNED"
                db.flush()

    def find_episode_task(self, source, anime_url, number, version):
        with transaction(SessionLocal) as db:
            return db.query(DownloadTaskEntity).filter(
                DownloadTaskEntity.source == source, DownloadTaskEntity.animeUrl == anime_url,
                DownloadTaskEntity.episodeNumber == number,
                func.upper(func.trim(DownloadTaskEntity.version)) == episode_version(version)
            ).order_by(DownloadTaskEntity.createdAt.desc()).first()

    def recover_interrupted_exports(self):
        with transaction(SessionLocal) as db:
            db.query(DownloadTaskEntity).filter_by(exportStatus=ExportStatus.EXPORTING.value).update({
                "exportStatus": ExportStatus.PENDING.value,
                "exportError": "Export interrupted; retry from the private library copy.",
            })
            db.flush()

    def update_last_known_episode(self, url: str, episode_count: int):
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            if fav:
                fav.lastKnownEpisode = episode_count
                fav.lastCheckedAt = datetime.now(timezone.utc)
                db.flush()

    # -------------------------------------------------------------------------
    # PROGRESSION
    # -------------------------------------------------------------------------

    def _mark_as_downloaded(self, db, anime_url, anime_name, episode_number, version):
        prog = db.query(WatchProgress).filter(
            WatchProgress.animeUrl == anime_url,
            WatchProgress.episodeNumber == episode_number,
            WatchProgress.version == version
        ).first()
        if not prog:
            prog = WatchProgress(
                animeUrl=anime_url,
                animeName=anime_name,
                episodeNumber=episode_number,
                version=version
            )
            db.add(prog)
        prog.downloaded = True
        prog.downloadedAt = datetime.now(timezone.utc)
        db.flush()
        return prog

    def mark_as_downloaded(self, anime_url: str, anime_name: str, episode_number: int, version: str = "") -> WatchProgress:
        with transaction(SessionLocal) as db:
            return self._mark_as_downloaded(db, anime_url, anime_name, episode_number, version)

    def mark_as_watched(self, anime_url: str, anime_name: str, episode_number: int, version: str = "", watched: bool = True) -> WatchProgress:
        with transaction(SessionLocal) as db:
            prog = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.episodeNumber == episode_number,
                WatchProgress.version == version
            ).first()
            if not prog:
                prog = WatchProgress(
                    animeUrl=anime_url,
                    animeName=anime_name,
                    episodeNumber=episode_number,
                    version=version
                )
                db.add(prog)
            prog.watched = watched
            prog.watchedAt = datetime.now(timezone.utc) if watched else None
            db.flush()
            db.refresh(prog)
            return prog

    def get_progress_for_anime(self, anime_url: str) -> List[WatchProgress]:
        with transaction(SessionLocal) as db:
            return db.query(WatchProgress).filter(WatchProgress.animeUrl == anime_url).all()

    def get_downloaded_episodes_set(self, anime_url: str) -> Set[str]:
        with transaction(SessionLocal) as db:
            progs = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.downloaded == True
            ).all()
            return {f"{p.episodeNumber}-{p.version}" for p in progs}

    def get_watched_episodes_set(self, anime_url: str) -> Set[str]:
        with transaction(SessionLocal) as db:
            progs = db.query(WatchProgress).filter(
                WatchProgress.animeUrl == anime_url,
                WatchProgress.watched == True
            ).all()
            return {f"{p.episodeNumber}-{p.version}" for p in progs}

    # -------------------------------------------------------------------------
    # HISTORIQUE & PERSISTANCE DES TÂCHES
    # -------------------------------------------------------------------------

    def _populate_entity(self, entity: DownloadTaskEntity, task: DownloadTask):
        entity.animeName = task.animeName
        entity.episodeNumber = task.episodeNumber
        entity.version = task.version
        entity.animeUrl = task.animeUrl
        entity.fileName = task.fileName
        entity.fileUrl = task.fileUrl
        entity.savePath = task.savePath
        entity.savePathSubtitle = task.savePathSubtitle
        entity.downloadPageUrl = task.downloadPageUrl
        entity.directDownloadUrl = task.directDownloadUrl
        entity.subtitleUrl = task.subtitleUrl
        entity.subtitlesJson = task.subtitlesJson
        entity.error = task.error
        entity.status = task.status.value
        entity.progress = task.progress
        entity.downloadedBytes = task.downloadedBytes
        entity.totalBytes = task.totalBytes
        entity.maxSpeedLimit = task.maxSpeedLimit
        entity.retryCount = task.retryCount
        entity.downloadSubtitles = task.downloadSubtitles
        entity.scheduledStartTime = task.scheduledStartTime
        entity.completedAt = task.completedAt
        entity.source = task.source
        entity.verificationStatus = task.verificationStatus
        entity.videoDuration = task.videoDuration
        entity.verifiedAt = task.verifiedAt
        entity.verificationError = task.verificationError
        entity.selectedServer = task.selectedServer
        entity.selectedQuality = task.selectedQuality
        entity.exportStatus = task.exportStatus.value
        entity.exportUrisJson = task.exportUrisJson
        entity.exportDestination = task.exportDestination
        entity.exportError = task.exportError
        entity.exportAttempts = task.exportAttempts
        entity.exportedAt = task.exportedAt

    def _update_auto_download_outcome(self, db, task):
        state = task.status.value if task.status in (
            DownloadStatus.COMPLETED, DownloadStatus.FAILED, DownloadStatus.CANCELLED) else "PLANNED"
        db.query(AutoDownloadEpisode).filter_by(taskId=task.id).update({"state": state})
        if task.status == DownloadStatus.COMPLETED:
            self._mark_as_downloaded(db, task.animeUrl or task.downloadPageUrl or "",
                                     task.animeName, task.episodeNumber, task.version)

    def save_task(self, task: DownloadTask):
        with transaction(SessionLocal) as db:
            entity = db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task.id).first()
            if entity:
                self._populate_entity(entity, task)
            else:
                db.add(task.to_entity())
            self._update_auto_download_outcome(db, task)
            db.flush()

    def save_tasks_batch(self, tasks: List[DownloadTask]):
        if not tasks:
            return
        with transaction(SessionLocal) as db:
            task_ids = [t.id for t in tasks]
            existing_entities = {
                e.id: e for e in db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id.in_(task_ids)).all()
            }
            for task in tasks:
                entity = existing_entities.get(task.id)
                if entity:
                    self._populate_entity(entity, task)
                else:
                    db.add(task.to_entity())
                self._update_auto_download_outcome(db, task)
            db.flush()

    def get_history(self, anime_name: Optional[str] = None) -> List[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            q = db.query(DownloadTaskEntity)
            if anime_name:
                q = q.filter(DownloadTaskEntity.animeName == anime_name)
            return q.order_by(DownloadTaskEntity.createdAt.desc()).all()

    def get_task_entity(self, task_id: str) -> Optional[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            return db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task_id).first()

    def delete_task_entity(self, task_id: str) -> bool:
        with transaction(SessionLocal) as db:
            entity = db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task_id).first()
            if entity:
                db.delete(entity)
                db.flush()
                return True
            return False

    def clear_history(self, status: Optional[str] = None, anime_name: Optional[str] = None):
        with transaction(SessionLocal) as db:
            q = db.query(DownloadTaskEntity).filter(
                DownloadTaskEntity.exportStatus != ExportStatus.EXPORTING.value,
                ~and_(DownloadTaskEntity.status == DownloadStatus.COMPLETED.value,
                    DownloadTaskEntity.exportStatus.in_([ExportStatus.PENDING.value, ExportStatus.EXPORT_FAILED.value])))
            if anime_name:
                q = q.filter(DownloadTaskEntity.animeName == anime_name)
            if status:
                statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
                q = q.filter(DownloadTaskEntity.status.in_(statuses))
            q.delete(synchronize_session=False)
            db.flush()

    def get_completed_tasks(self) -> List[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            return db.query(DownloadTaskEntity).filter(
                DownloadTaskEntity.status == DownloadStatus.COMPLETED.value
            ).order_by(DownloadTaskEntity.createdAt.desc()).all()

    def get_unfinished_tasks(self) -> List[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            return db.query(DownloadTaskEntity).filter(
                or_(DownloadTaskEntity.status.in_([
                    DownloadStatus.PENDING.value,
                    DownloadStatus.SCHEDULED.value,
                    DownloadStatus.DOWNLOADING.value,
                    DownloadStatus.RETRYING.value,
                    DownloadStatus.PAUSED.value,
                    DownloadStatus.VERIFICATION_REQUIRED.value,
                    DownloadStatus.FAILED.value,
                    DownloadStatus.MUXING.value,
                ]), and_(DownloadTaskEntity.status == DownloadStatus.COMPLETED.value,
                    DownloadTaskEntity.exportStatus.in_([ExportStatus.PENDING.value,
                        ExportStatus.EXPORTING.value, ExportStatus.EXPORT_FAILED.value])))
            ).all()

    def find_downloaded_episode(
        self,
        anime_name: str,
        episode_number: int,
        version: str = "",
        episode_url: str = ""
    ) -> Optional[DownloadTaskEntity]:
        """
        Recherche une tâche de téléchargement terminée correspondant à l'épisode,
        ET valide que le fichier existe physiquement sur le disque dur et est non vide.
        """
        import os
        from sqlalchemy import or_

        with transaction(SessionLocal) as db:
            q = db.query(DownloadTaskEntity).filter(
                DownloadTaskEntity.status == DownloadStatus.COMPLETED.value,
                DownloadTaskEntity.episodeNumber == episode_number
            )

            if episode_url:
                # The episode URL identifies the version; a matching title must
                # never override a different URL (e.g. VF versus VOSTFR).
                q = q.filter(or_(
                    DownloadTaskEntity.downloadPageUrl == episode_url,
                    DownloadTaskEntity.fileUrl == episode_url,
                ))
            elif anime_name and not version:
                q = q.filter(DownloadTaskEntity.animeName.ilike(anime_name.strip()))
            else:
                # Legacy tasks do not store a language version. Without an
                # episode URL we cannot safely match a requested version.
                return None

            candidates = q.order_by(DownloadTaskEntity.completedAt.desc(), DownloadTaskEntity.createdAt.desc()).all()

            for task in candidates:
                if task.savePath and os.path.isfile(task.savePath) and os.path.getsize(task.savePath) > 0:
                    return task

            return None

library_service = LibraryService()
