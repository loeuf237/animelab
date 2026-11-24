"""Discovery and safe in-memory registry for locally downloaded files without DB tasks."""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass, field
import hashlib
import json
from pathlib import Path
import re
import threading
from typing import Optional, Union

from animelab.config import settings
from animelab.models.auto_download import episode_version
from animelab.security import is_safe_path

_VIDEO_EXTENSIONS = frozenset({".mp4", ".mkv", ".webm", ".avi", ".mov", ".m4v"})
_SUBTITLE_EXTENSIONS = frozenset({".vtt", ".srt", ".ass", ".ssa"})
_VARIANT_SUFFIX_RE = re.compile(r"(?:\.hardsub|\.subtitled-[A-Za-z0-9_-]+)+$", re.IGNORECASE)
_VERSION_TAG_RE = re.compile(r"\s*\[([^\[\]]+)\]\s*$")
_SXE_RE = re.compile(r"(?i)\bS(\d{1,2})E(\d{1,4})(?!\d)")
_EP_NUM_RE = re.compile(r"(?i)(?:episode|épisode|ep)[\s._-]*0*(\d{1,4})(?!\d)")
_SEASON_DIR_RE = re.compile(r"(?i)^season[\s._-]*(\d{1,2})$")
_MAX_REGISTRY_ENTRIES = 2000


def _sanitize_name(name: str) -> str:
    """Sanitize anime/file names using the same rules as DownloadManagerService."""
    if not name:
        return "download"
    clean = name.replace("\0", "")
    clean = re.sub(r'[<>:"/\\|?*\x00-\x1f]', "_", clean)
    clean = re.sub(r"\.{2,}", "_", clean)
    clean = re.sub(r"\s+", " ", clean).strip(" .")
    return clean or "download"


def _strip_variant_suffix(stem: str) -> tuple[str, bool]:
    stripped = _VARIANT_SUFFIX_RE.sub("", stem)
    return stripped, stripped != stem


def _parse_filename_meta(path: Path) -> tuple[Optional[int], Optional[int], str, bool]:
    """Extract (season, episode_number, normalized_version, is_subtitled_variant)."""
    work, is_variant = _strip_variant_suffix(path.stem)
    version = ""
    ver_match = _VERSION_TAG_RE.search(work)
    if ver_match:
        version = episode_version(ver_match.group(1))
        work = work[:ver_match.start()]

    season: Optional[int] = None
    ep_num: Optional[int] = None
    sxe_match = _SXE_RE.search(work)
    if sxe_match:
        season = int(sxe_match.group(1))
        ep_num = int(sxe_match.group(2))
    else:
        ep_match = _EP_NUM_RE.search(work)
        if ep_match:
            ep_num = int(ep_match.group(1))
            dir_match = _SEASON_DIR_RE.match(path.parent.name)
            if dir_match:
                season = int(dir_match.group(1))

    return season, ep_num, version, is_variant


def discover_sidecar_subtitles(video_path: Path, allowed_root: Path) -> list[str]:
    """Discover non-empty sidecar subtitle files alongside a local video file."""
    parent = video_path.parent
    if not parent.is_dir():
        return []
    stem = video_path.stem
    base_stem, _ = _strip_variant_suffix(stem)
    prefixes = (f"{stem}.", f"{base_stem}.") if base_stem != stem else (f"{stem}.",)

    found: list[str] = []
    try:
        for candidate in sorted(parent.iterdir(), key=lambda p: p.name.lower()):
            if candidate.suffix.lower() not in _SUBTITLE_EXTENSIONS:
                continue
            if not any(candidate.name.startswith(prefix) for prefix in prefixes):
                continue
            if not is_safe_path(candidate, [allowed_root]):
                continue
            try:
                if candidate.is_file() and candidate.stat().st_size > 0:
                    found.append(str(candidate.resolve()))
            except OSError:
                continue
    except OSError:
        return []
    return found


def _resolve_anime_dirs(root: Path, clean_anime: str) -> list[Path]:
    """Return candidate directories inside download root for the given anime."""
    if not root.is_dir() or not clean_anime:
        return []
    exact = root / clean_anime
    anime_dir: Optional[Path] = exact if exact.is_dir() and is_safe_path(exact, [root]) else None
    if anime_dir is None:
        target_lower = clean_anime.lower()
        try:
            for child in root.iterdir():
                if child.is_dir() and child.name.lower() == target_lower and is_safe_path(child, [root]):
                    anime_dir = child
                    break
        except OSError:
            return []
    if anime_dir is None:
        return []

    dirs = [anime_dir]
    try:
        for sub in sorted(anime_dir.iterdir(), key=lambda p: p.name.lower()):
            if sub.is_dir() and _SEASON_DIR_RE.match(sub.name) and is_safe_path(sub, [root]):
                dirs.append(sub)
    except OSError:
        pass
    return dirs


def _collect_matching_disk_files(
    anime_name: str,
    episode_number: int,
    version: str = "",
    season: Optional[int] = None,
    download_dir: Optional[Union[str, Path]] = None,
) -> list[tuple[int, int, float, Path]]:
    if not anime_name or episode_number is None:
        return []
    try:
        root = Path(download_dir or settings.DOWNLOAD_DIR).resolve()
    except Exception:
        return []

    clean_anime = _sanitize_name(anime_name)
    search_dirs = _resolve_anime_dirs(root, clean_anime)
    if not search_dirs:
        return []

    req_ver = episode_version(version)
    req_season = season if (isinstance(season, int) and season > 0) else None
    candidates: list[tuple[int, int, float, Path]] = []

    for directory in search_dirs:
        try:
            entries = list(directory.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.name.startswith("."):
                continue
            ext = entry.suffix.lower()
            if ext not in _VIDEO_EXTENSIONS:
                continue
            if not is_safe_path(entry, [root]):
                continue
            try:
                if not entry.is_file():
                    continue
                stat = entry.stat()
                if stat.st_size <= 0:
                    continue
            except OSError:
                continue

            file_season, file_ep, file_ver, is_variant = _parse_filename_meta(entry)
            if file_ep != episode_number:
                continue
            # Strict version match: tagged requests only match matching tags; untagged only untagged.
            if req_ver:
                if file_ver != req_ver:
                    continue
            elif file_ver:
                continue

            if req_season is not None and file_season is not None and file_season != req_season:
                continue

            season_score = 1 if (req_season is not None and file_season == req_season) else 0
            candidates.append((season_score, 1 if is_variant else 0, stat.st_mtime, entry.resolve()))

    candidates.sort(key=lambda item: (item[0], item[1], item[2]), reverse=True)
    return candidates


def find_downloaded_file_on_disk(
    anime_name: str,
    episode_number: int,
    version: str = "",
    season: Optional[int] = None,
    download_dir: Optional[Union[str, Path]] = None,
) -> Optional[Path]:
    """Find a non-empty downloaded video on disk matching anime, episode, and strict version."""
    candidates = _collect_matching_disk_files(
        anime_name=anime_name,
        episode_number=episode_number,
        version=version,
        season=season,
        download_dir=download_dir,
    )
    return candidates[0][3] if candidates else None


def find_all_downloaded_files_on_disk(
    anime_name: str,
    episode_number: int,
    version: str = "",
    season: Optional[int] = None,
    download_dir: Optional[Union[str, Path]] = None,
) -> list[Path]:
    """Return every safe downloaded video file on disk matching the episode."""
    return [
        item[3]
        for item in _collect_matching_disk_files(
            anime_name=anime_name,
            episode_number=episode_number,
            version=version,
            season=season,
            download_dir=download_dir,
        )
    ]


@dataclass
class LocalMediaEntry:
    """Lightweight task-compatible descriptor for cleaned/disk-discovered downloads."""

    id: str
    savePath: str
    fileName: str
    animeName: str
    episodeNumber: int
    version: str = ""
    animeUrl: str = ""
    source: str = ""
    savePathSubtitle: Optional[str] = None
    exportUrisJson: str = "[]"
    mediaJson: str = "{}"
    _allowed_root: Optional[Path] = field(default=None, repr=False, compare=False)


class LocalMediaRegistry:
    """Thread-safe bounded registry mapping local-<hash> IDs to disk media entries."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._entries: OrderedDict[str, LocalMediaEntry] = OrderedDict()

    @staticmethod
    def _entry_id(resolved_path: Path) -> str:
        digest = hashlib.sha256(str(resolved_path).encode("utf-8")).hexdigest()[:16]
        return f"local-{digest}"

    def register(
        self,
        file_path: Path,
        *,
        anime_name: str,
        episode_number: int,
        version: str = "",
        anime_url: str = "",
        source: str = "",
        allowed_root: Optional[Path] = None,
    ) -> LocalMediaEntry:
        """Register an existing disk video file and return its deterministic entry."""
        resolved = file_path.resolve()
        root = allowed_root.resolve() if allowed_root is not None else Path(settings.DOWNLOAD_DIR).resolve()
        subs = discover_sidecar_subtitles(resolved, root)
        if len(subs) > 1:
            sub_field: Optional[str] = json.dumps(subs)
        elif len(subs) == 1:
            sub_field = subs[0]
        else:
            sub_field = None

        entry = LocalMediaEntry(
            id=self._entry_id(resolved),
            savePath=str(resolved),
            fileName=resolved.name,
            animeName=anime_name,
            episodeNumber=episode_number,
            version=version,
            animeUrl=anime_url,
            source=source,
            savePathSubtitle=sub_field,
            _allowed_root=allowed_root.resolve() if allowed_root is not None else None,
        )
        with self._lock:
            self._entries[entry.id] = entry
            self._entries.move_to_end(entry.id)
            while len(self._entries) > _MAX_REGISTRY_ENTRIES:
                self._entries.popitem(last=False)
        return entry

    def find_and_register(
        self,
        anime_name: str,
        episode_number: int,
        version: str = "",
        season: Optional[int] = None,
        anime_url: str = "",
        source: str = "",
        download_dir: Optional[Union[str, Path]] = None,
    ) -> Optional[LocalMediaEntry]:
        """Locate a downloaded file on disk and register it when present."""
        found = find_downloaded_file_on_disk(
            anime_name=anime_name,
            episode_number=episode_number,
            version=version,
            season=season,
            download_dir=download_dir,
        )
        if found is None:
            return None
        root = Path(download_dir).resolve() if download_dir is not None else Path(settings.DOWNLOAD_DIR).resolve()
        return self.register(
            found,
            anime_name=anime_name,
            episode_number=episode_number,
            version=version,
            anime_url=anime_url,
            source=source,
            allowed_root=root if download_dir is not None else None,
        )

    def get(self, entry_id: str) -> Optional[LocalMediaEntry]:
        """Return a registered disk entry if the underlying file still exists safely."""
        with self._lock:
            entry = self._entries.get(entry_id)
        if entry is None:
            return None
        path = Path(entry.savePath)
        allowed = [entry._allowed_root] if entry._allowed_root is not None else None
        try:
            valid = is_safe_path(path, allowed) and path.is_file() and path.stat().st_size > 0
        except OSError:
            valid = False
        if not valid:
            with self._lock:
                self._entries.pop(entry_id, None)
            return None
        return entry

    def remove(self, entry_id: str) -> Optional[LocalMediaEntry]:
        """Remove a registered disk entry ID from the in-memory registry."""
        with self._lock:
            return self._entries.pop(entry_id, None)

    def find_all_on_disk(
        self,
        anime_name: str,
        episode_number: int,
        version: str = "",
        season: Optional[int] = None,
        download_dir: Optional[Union[str, Path]] = None,
    ) -> list[Path]:
        """Find every matching video file on disk for the specified episode."""
        return find_all_downloaded_files_on_disk(
            anime_name=anime_name,
            episode_number=episode_number,
            version=version,
            season=season,
            download_dir=download_dir,
        )


local_media = LocalMediaRegistry()
