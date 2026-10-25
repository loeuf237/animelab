"""Persisted media identity and strict bounds for interrupted downloads."""
import hashlib
import json
import os
import re
import shutil
from collections.abc import Mapping
from pathlib import Path
from typing import Any


RESUME_OVERLAP = 65536


class ResumeMismatch(ConnectionError):
    """The new route serves different bytes from the existing partial file."""


def read_metadata(path: Path) -> dict[str, Any]:
    try:
        if path.stat().st_size > 4096:
            return {}
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def write_metadata(path: Path, data: Mapping[str, Any]) -> None:
    temp = path.with_name(path.name + ".tmp")
    temp.write_text(json.dumps(data), encoding="utf-8")
    os.replace(temp, path)


def representation(headers: Mapping[str, str], total: int) -> dict[str, str | int]:
    etag = headers.get("etag", "")
    validator = etag if etag and not etag.startswith("W/") else headers.get("last-modified", "")
    return {"validator": validator, "total": total}


def response_range(headers: Mapping[str, str], expected_start: int) -> tuple[int, int]:
    match = re.fullmatch(r"bytes\s+(\d+)-(\d+)/(\d+|\*)",
                         headers.get("content-range", "").strip(), re.IGNORECASE)
    if not match:
        raise ConnectionError("Invalid or missing Content-Range in HTTP 206 response")
    start, end = int(match[1]), int(match[2])
    total = int(match[3]) if match[3] != "*" else 0
    length = end - start + 1
    declared = headers.get("content-length")
    if (start != expected_start or end < start or (total and end >= total)
            or (declared is not None and (not declared.isdigit() or int(declared) != length))):
        raise ConnectionError("Invalid Content-Range bounds in resume response")
    return total, length


def prepare_hls_cache(directory: Path, playlist_url: str, playlist_text: str) -> None:
    # A changed playlist/variant must never reuse segments solely by their index.
    # Exact identity is deliberately conservative when signed URLs are renewed.
    fingerprint = hashlib.sha256(json.dumps([playlist_url, playlist_text]).encode()).hexdigest()
    manifest = directory / "manifest.json"
    if read_metadata(manifest).get("fingerprint") != fingerprint:
        shutil.rmtree(directory)
        directory.mkdir(parents=True, exist_ok=True)
    write_metadata(manifest, {"fingerprint": fingerprint})


def segment_digest(path: Path) -> dict[str, str | int]:
    digest = hashlib.sha256()
    with path.open('rb') as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b''):
            digest.update(chunk)
    return {'size': path.stat().st_size, 'sha256': digest.hexdigest()}


def valid_cached_segment(path: Path) -> bool:
    metadata = read_metadata(path.with_suffix('.json'))
    return path.is_file() and path.stat().st_size > 0 and metadata == segment_digest(path)


def commit_segment(staging: Path, destination: Path) -> None:
    # Persist bytes before the identity record. A crash in between results in a
    # safe re-download, never reuse of an uncommitted partial segment.
    with staging.open('rb') as source:
        os.fsync(source.fileno())
    staging.replace(destination)
    write_metadata(destination.with_suffix('.json'), segment_digest(destination))


def publish_file(staging: Path, destination: Path) -> None:
    """Publish completed bytes without replacing a destination created meanwhile."""
    import errno
    try:
        os.link(staging, destination)
    except OSError as exc:
        if exc.errno not in (errno.EACCES, errno.EPERM, errno.ENOSYS, errno.EOPNOTSUPP):
            raise
        # Android filesystems/providers may refuse hard links. Reserve our own
        # name exclusively; never delete or replace a file owned by another task.
        fd = os.open(destination, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o600)
        os.close(fd)
        try:
            os.replace(staging, destination)
        except BaseException:
            destination.unlink(missing_ok=True)
            raise
    else:
        staging.unlink()


def media_resource(url: str) -> str:
    from urllib.parse import urlsplit, urlunsplit
    parsed = urlsplit(url)
    # Signed query parameters can expire while the resource stays identical.
    # Ports are part of the origin, credentials are never part of this record.
    host = parsed.hostname or ''
    if ':' in host:
        host = '[' + host + ']'
    authority = host + (':' + str(parsed.port) if parsed.port else '')
    identity = urlunsplit((parsed.scheme, authority, parsed.path, '', ''))
    return hashlib.sha256(identity.encode()).hexdigest()
