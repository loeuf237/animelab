import json
import os
import re
from datetime import datetime, timezone
from typing import Any, List, Optional, Set
from urllib.parse import urlparse, urlunparse

from animelab import platform_events
from animelab.config import settings
from animelab.database import SessionLocal, transaction
from animelab.models.favorite import FavoriteAnime
from animelab.models.anime_detail_cache import AnimeDetailSnapshot
from animelab.models.watch_progress import WatchProgress
from animelab.models.auto_download import AutoDownloadEpisode, episode_version
from animelab.models.download_task import DownloadTask, DownloadTaskEntity, DownloadStatus, ExportStatus
from sqlalchemy import or_, and_, func

_VOIRANIME_MIRROR_HOSTS = frozenset({
    "voir-anime.to",
    "www.voir-anime.to",
    "voiranime.to",
    "www.voiranime.to",
    "voiranime.cx",
    "www.voiranime.cx",
})

_FRENCH_STREAM_MIRROR_RE = re.compile(r"^fs\d+\.[a-z0-9-]+$", re.IGNORECASE)
_FRENCH_STREAM_HOSTS = frozenset({
    "french-stream.net",
    "www.french-stream.net",
    "fstream.net",
    "www.fstream.net",
    "fs016.lol",
})


def equivalent_url_variants(url: str) -> list[str]:
    """Return deduplicated URL variants handling trailing slashes and mirror hosts."""
    if not url or not isinstance(url, str):
        return []
    stripped = url.strip()
    if not stripped:
        return []

    variants: list[str] = []

    def _add_slash_variants(candidate: str) -> None:
        if candidate not in variants:
            variants.append(candidate)
        if "?" not in candidate and "#" not in candidate:
            no_slash = candidate.rstrip("/")
            with_slash = f"{no_slash}/"
            if no_slash and no_slash not in variants:
                variants.append(no_slash)
            if with_slash not in variants:
                variants.append(with_slash)

    _add_slash_variants(stripped)
    try:
        parsed = urlparse(stripped)
    except Exception:
        return variants

    host = (parsed.hostname or "").lower()
    if parsed.scheme in ("http", "https") and host in _VOIRANIME_MIRROR_HOSTS:
        active = urlparse((settings.VOIR_ANIME_URL or "").rstrip("/"))
        mirror_targets: list[tuple[str, str]] = []
        if active.scheme and active.netloc:
            mirror_targets.append((active.scheme, active.netloc))
        for mirror_host in ("voiranime.cx", "voir-anime.to", "voiranime.to"):
            mirror_targets.append((parsed.scheme, mirror_host))
        for scheme, netloc in mirror_targets:
            rewritten = urlunparse(parsed._replace(scheme=scheme, netloc=netloc))
            _add_slash_variants(rewritten)
    elif parsed.scheme in ("http", "https") and (
        host in _FRENCH_STREAM_HOSTS or _FRENCH_STREAM_MIRROR_RE.fullmatch(host)
    ):
        fs_active = urlparse((settings.FRENCH_STREAM_URL or "").rstrip("/"))
        fs_targets: list[tuple[str, str]] = []
        if fs_active.scheme and fs_active.netloc:
            fs_targets.append((fs_active.scheme, fs_active.netloc))
        for fs_host in ("fs016.lol", "french-stream.net", "fstream.net"):
            fs_targets.append((parsed.scheme, fs_host))
        for scheme, netloc in fs_targets:
            rewritten = urlunparse(parsed._replace(scheme=scheme, netloc=netloc))
            _add_slash_variants(rewritten)

    return variants


def _exported_uris_from_task(task) -> list[str]:
    try:
        raw = json.loads(getattr(task, "exportUrisJson", "[]") or "[]")
        if isinstance(raw, list):
            return [u for u in raw if isinstance(u, str) and u.startswith("content://")]
    except (TypeError, ValueError):
        pass
    return []


def _task_is_playable_locally(task) -> bool:
    """Return True if a task has a non-empty local file or a verified Android exported copy."""
    save_path = getattr(task, "savePath", None)
    if save_path:
        try:
            if os.path.isfile(save_path) and os.path.getsize(save_path) > 0:
                return True
        except OSError:
            pass
    for uri in _exported_uris_from_task(task):
        if platform_events.exported_copy_exists(uri) is True:
            return True
    return False

class LibraryService:
    MAX_UNPINNED_DETAIL_SNAPSHOTS = 25

    # -------------------------------------------------------------------------
    # FAVORIS
    # -------------------------------------------------------------------------

    def _pin_snapshots_in_tx(self, db, url: str, pinned: bool) -> None:
        variants = equivalent_url_variants(url)
        if variants:
            values: dict[str, Any] = {"pinned": bool(pinned)}
            if not pinned:
                values["updatedAt"] = datetime.now(timezone.utc)
            db.query(AnimeDetailSnapshot).filter(
                AnimeDetailSnapshot.animeUrl.in_(variants)
            ).update(values, synchronize_session=False)

    def _prune_unpinned_snapshots(self, db) -> None:
        unpinned_ids = [
            row[0]
            for row in db.query(AnimeDetailSnapshot.id)
            .filter(AnimeDetailSnapshot.pinned.is_(False))
            .order_by(AnimeDetailSnapshot.updatedAt.desc(), AnimeDetailSnapshot.id.desc())
            .all()
        ]
        stale_ids = unpinned_ids[self.MAX_UNPINNED_DETAIL_SNAPSHOTS :]
        if stale_ids:
            db.query(AnimeDetailSnapshot).filter(
                AnimeDetailSnapshot.id.in_(stale_ids)
            ).delete(synchronize_session=False)

    def add_favorite(self, url: str, title: str, image_url: str = "", source: str = "french-manga",
                     auto_download_version: str = "") -> FavoriteAnime:
        with transaction(SessionLocal) as db:
            fav = db.query(FavoriteAnime).filter(FavoriteAnime.url == url).first()
            self._pin_snapshots_in_tx(db, url, True)
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
            self._pin_snapshots_in_tx(db, url, False)
            self._prune_unpinned_snapshots(db)
            db.flush()

    def remove_all_favorites(self):
        with transaction(SessionLocal) as db:
            db.query(AutoDownloadEpisode).delete()
            db.query(FavoriteAnime).delete()
            db.query(AnimeDetailSnapshot).update({"pinned": False}, synchronize_session=False)
            self._prune_unpinned_snapshots(db)
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

    # -------------------------------------------------------------------------
    # SNAPSHOTS HORS-LIGNE DES FICHES ANIMÉS
    # -------------------------------------------------------------------------

    def get_anime_detail_snapshot(self, urls: list[str] | str) -> Optional[AnimeDetailSnapshot]:
        raw_urls = [urls] if isinstance(urls, str) else list(urls)
        candidates: list[str] = []
        for raw in raw_urls:
            for variant in equivalent_url_variants(raw):
                if variant not in candidates:
                    candidates.append(variant)
        if not candidates:
            return None
        with transaction(SessionLocal) as db:
            return (
                db.query(AnimeDetailSnapshot)
                .filter(AnimeDetailSnapshot.animeUrl.in_(candidates))
                .order_by(AnimeDetailSnapshot.updatedAt.desc(), AnimeDetailSnapshot.id.desc())
                .first()
            )

    def save_anime_detail_snapshot(
        self,
        anime_url: str,
        source: str,
        source_name: str,
        detail_payload: dict,
        *,
        pinned: bool = False,
    ) -> Optional[AnimeDetailSnapshot]:
        canonical = (anime_url or "").strip()
        if not canonical:
            return None
        variants = equivalent_url_variants(canonical)
        serialized = json.dumps(detail_payload, ensure_ascii=False)
        now = datetime.now(timezone.utc)
        title = str(detail_payload.get("title") or "")
        with transaction(SessionLocal) as db:
            row = (
                db.query(AnimeDetailSnapshot)
                .filter(AnimeDetailSnapshot.animeUrl.in_(variants or [canonical]))
                .order_by(AnimeDetailSnapshot.updatedAt.desc(), AnimeDetailSnapshot.id.desc())
                .first()
            )
            if row is None:
                row = AnimeDetailSnapshot(
                    animeUrl=canonical,
                    source=source or "",
                    sourceName=source_name or "",
                    title=title,
                    detailJson=serialized,
                    pinned=bool(pinned),
                    updatedAt=now,
                )
                db.add(row)
            else:
                if row.animeUrl != canonical:
                    conflict = (
                        db.query(AnimeDetailSnapshot)
                        .filter(
                            AnimeDetailSnapshot.animeUrl == canonical,
                            AnimeDetailSnapshot.id != row.id,
                        )
                        .first()
                    )
                    if conflict is None:
                        row.animeUrl = canonical
                row.source = source or ""
                row.sourceName = source_name or ""
                row.title = title
                row.detailJson = serialized
                row.pinned = bool(pinned)
                row.updatedAt = now
            db.flush()
            self._prune_unpinned_snapshots(db)
            db.flush()
            db.refresh(row)
            return row

    def set_anime_detail_snapshot_pinned(self, url: str, pinned: bool) -> None:
        with transaction(SessionLocal) as db:
            self._pin_snapshots_in_tx(db, url, pinned)
            if not pinned:
                self._prune_unpinned_snapshots(db)
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

    def clear_downloaded(
        self,
        anime_url: str,
        episode_number: int,
        version: str = "",
        anime_name: str = "",
    ) -> int:
        """Reset WatchProgress.downloaded flag for an episode without altering watched state."""
        req_ver = episode_version(version)
        variants = equivalent_url_variants(anime_url) if anime_url else []
        clean_name = (anime_name or "").strip()
        if not variants and not clean_name:
            return 0
        with transaction(SessionLocal) as db:
            filters = [WatchProgress.episodeNumber == episode_number]
            if variants and clean_name:
                filters.append(or_(WatchProgress.animeUrl.in_(variants), WatchProgress.animeName.ilike(clean_name)))
            elif variants:
                filters.append(WatchProgress.animeUrl.in_(variants))
            else:
                filters.append(WatchProgress.animeName.ilike(clean_name))

            rows = db.query(WatchProgress).filter(*filters).all()
            updated = 0
            for prog in rows:
                if episode_version(prog.version) != req_ver:
                    continue
                if prog.downloaded:
                    prog.downloaded = False
                    prog.downloadedAt = None
                    updated += 1
            if updated:
                db.flush()
            return updated

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
        from animelab.services.output_profiles import private_snapshot
        import json
        entity.subtitlesJson = json.dumps(private_snapshot(json.loads(task.subtitlesJson)))
        entity.mediaJson = json.dumps(private_snapshot(json.loads(task.mediaJson)))
        entity.outputProfileJson = task.outputProfileJson
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
        if getattr(task, '_removed', False):
            return
        with transaction(SessionLocal) as db:
            entity = db.query(DownloadTaskEntity).filter(DownloadTaskEntity.id == task.id).first()
            if entity:
                self._populate_entity(entity, task)
            else:
                db.add(task.to_entity())
            self._update_auto_download_outcome(db, task)
            db.flush()
            from animelab.models.media_state import sync_media_state
            sync_media_state(db, task)

    def save_tasks_batch(self, tasks: List[DownloadTask]):
        tasks = [task for task in tasks if not getattr(task, '_removed', False)]
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

            from animelab.models.media_state import sync_media_state
            for task in tasks:
                sync_media_state(db, task)

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

    @staticmethod
    def _clear_history_query(db, status: Optional[str] = None, anime_name: Optional[str] = None):
        q = db.query(DownloadTaskEntity).filter(
            DownloadTaskEntity.exportStatus != ExportStatus.EXPORTING.value,
            ~and_(DownloadTaskEntity.status == DownloadStatus.COMPLETED.value,
                DownloadTaskEntity.exportStatus.in_([ExportStatus.PENDING.value, ExportStatus.EXPORT_FAILED.value])))
        if anime_name:
            q = q.filter(DownloadTaskEntity.animeName == anime_name)
        if status:
            statuses = [s.strip().upper() for s in status.split(",") if s.strip()]
            q = q.filter(DownloadTaskEntity.status.in_(statuses))
        return q

    def get_clearable_history(self, status: Optional[str] = None, anime_name: Optional[str] = None) -> List[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            return self._clear_history_query(db, status=status, anime_name=anime_name).all()

    def get_all_tasks_snapshot(self) -> List[DownloadTaskEntity]:
        with transaction(SessionLocal) as db:
            return db.query(DownloadTaskEntity).all()

    def clear_history(self, status: Optional[str] = None, anime_name: Optional[str] = None):
        with transaction(SessionLocal) as db:
            self._clear_history_query(db, status=status, anime_name=anime_name).delete(synchronize_session=False)
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

    def _matching_downloaded_tasks_in_tx(
        self,
        db,
        anime_name: str,
        episode_number: int,
        version: str = "",
        episode_url: str = "",
        anime_url: str = "",
        source: str = "",
        *,
        require_playable: bool = True,
    ) -> list[DownloadTaskEntity]:
        req_ver = episode_version(version)
        ep_variants = equivalent_url_variants(episode_url) if episode_url else []
        anime_variants = equivalent_url_variants(anime_url) if anime_url else []

        base_q = db.query(DownloadTaskEntity).filter(
            DownloadTaskEntity.status == DownloadStatus.COMPLETED.value,
            DownloadTaskEntity.episodeNumber == episode_number,
        ).order_by(DownloadTaskEntity.completedAt.desc(), DownloadTaskEntity.createdAt.desc())

        matches: list[DownloadTaskEntity] = []
        seen_ids: set[str] = set()

        def _collect(candidates: list[DownloadTaskEntity]) -> None:
            filtered = [t for t in candidates if not require_playable or _task_is_playable_locally(t)]
            if source:
                filtered.sort(key=lambda t: (t.source or "") != source)
            for t in filtered:
                if t.id not in seen_ids:
                    seen_ids.add(t.id)
                    matches.append(t)

        # Tier 1: exact or mirror-equivalent episode URL match.
        if ep_variants:
            url_candidates = base_q.filter(or_(
                DownloadTaskEntity.downloadPageUrl.in_(ep_variants),
                DownloadTaskEntity.fileUrl.in_(ep_variants),
            )).all()
            url_filtered = [
                t for t in url_candidates
                if not (req_ver and episode_version(t.version) and episode_version(t.version) != req_ver)
            ]
            _collect(url_filtered)

        # Tier 2: matching anime URL (incl. mirrors) + strict version.
        if anime_variants and req_ver:
            anime_candidates = base_q.filter(
                DownloadTaskEntity.animeUrl.in_(anime_variants),
                func.upper(func.trim(DownloadTaskEntity.version)) == req_ver,
            ).all()
            _collect(anime_candidates)

        # Tier 3: anime name + strict version (never match legacy version="" for a tagged request).
        if anime_name:
            if req_ver:
                name_candidates = base_q.filter(
                    DownloadTaskEntity.animeName.ilike(anime_name.strip()),
                    func.upper(func.trim(DownloadTaskEntity.version)) == req_ver,
                ).all()
            elif not ep_variants:
                name_candidates = base_q.filter(
                    DownloadTaskEntity.animeName.ilike(anime_name.strip()),
                ).all()
            else:
                name_candidates = []
            _collect(name_candidates)

        return matches

    def find_downloaded_episode(
        self,
        anime_name: str,
        episode_number: int,
        version: str = "",
        episode_url: str = "",
        anime_url: str = "",
        source: str = "",
    ) -> Optional[DownloadTaskEntity]:
        """
        Recherche une tâche de téléchargement terminée correspondant à l'épisode,
        ET valide que le fichier existe physiquement sur le disque dur (ou via URI Android exportée).
        """
        with transaction(SessionLocal) as db:
            matches = self._matching_downloaded_tasks_in_tx(
                db,
                anime_name=anime_name,
                episode_number=episode_number,
                version=version,
                episode_url=episode_url,
                anime_url=anime_url,
                source=source,
                require_playable=True,
            )
            return matches[0] if matches else None

    def find_all_downloaded_episode_tasks(
        self,
        anime_name: str,
        episode_number: int,
        version: str = "",
        episode_url: str = "",
        anime_url: str = "",
        source: str = "",
    ) -> list[DownloadTaskEntity]:
        """Return every completed DB task matching the episode (even if already removed from disk)."""
        with transaction(SessionLocal) as db:
            return self._matching_downloaded_tasks_in_tx(
                db,
                anime_name=anime_name,
                episode_number=episode_number,
                version=version,
                episode_url=episode_url,
                anime_url=anime_url,
                source=source,
                require_playable=False,
            )

library_service = LibraryService()
