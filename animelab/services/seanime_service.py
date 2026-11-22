"""SQLite-backed lifecycle & catalog service for Seanime extensions."""

from __future__ import annotations

import json
import logging
from typing import Any
from urllib.parse import urlparse

from animelab.config import settings
from animelab.database import sqlite_connection
from animelab.security import is_safe_url_async
from animelab.services.seanime_catalog import (
    EXECUTABLE_SEANIME_TYPES,
    SEANIME_TYPES,
    compare_seanime_versions,
    fetch_full_manifest,
    normalize_manifest,
    read_seanime_catalog,
)
from animelab.services.seanime_runtime import seanime_runtime
from animelab.services.seanime_source import SeanimeSource
from animelab.services.source_http import source_http

logger = logging.getLogger(__name__)


def _safe_json_loads(raw: Any, default: Any) -> Any:
    if isinstance(raw, (dict, list)):
        return raw
    if not isinstance(raw, str) or not raw.strip():
        return default
    try:
        return json.loads(raw)
    except Exception:
        return default


def _build_defaults(schema: dict[str, Any]) -> dict[str, str]:
    fields = schema.get("fields")
    if not isinstance(fields, list):
        return {}
    defaults: dict[str, str] = {}
    for field in fields:
        if isinstance(field, dict) and field.get("name"):
            defaults[str(field["name"])] = str(field.get("default") or "")
    return defaults


class SeanimeExtensionService:
    """Manages Seanime marketplaces, repositories, installed extensions, and configs."""

    def __init__(self, *, db_path: str | None = None, runtime: Any | None = None) -> None:
        self.db_path = db_path or settings.DATABASE_PATH
        self.runtime = runtime or seanime_runtime
        self._schema_checked = False

    def _ensure_tables(self) -> None:
        if self._schema_checked and self.db_path != ":memory:":
            return
        with sqlite_connection(self.db_path) as conn:
            exists = conn.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='seanime_repos'"
            ).fetchone()
            if not exists:
                conn.executescript(
                    """
                    CREATE TABLE IF NOT EXISTS seanime_repos (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        url TEXT UNIQUE NOT NULL,
                        name TEXT NOT NULL,
                        kind TEXT NOT NULL DEFAULT 'marketplace',
                        is_active INTEGER NOT NULL DEFAULT 1,
                        last_error TEXT,
                        checked_at TEXT,
                        snapshot_hash TEXT,
                        created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
                    );
                    CREATE TABLE IF NOT EXISTS seanime_extensions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        repo_id INTEGER NOT NULL REFERENCES seanime_repos(id) ON DELETE CASCADE,
                        ext_id TEXT NOT NULL,
                        name TEXT NOT NULL,
                        version TEXT NOT NULL DEFAULT '1.0.0',
                        installed_version TEXT,
                        available_version TEXT,
                        has_update INTEGER NOT NULL DEFAULT 0,
                        ext_type TEXT NOT NULL,
                        language TEXT NOT NULL DEFAULT 'javascript',
                        lang TEXT NOT NULL DEFAULT 'en',
                        author TEXT NOT NULL DEFAULT '',
                        description TEXT NOT NULL DEFAULT '',
                        notes TEXT NOT NULL DEFAULT '',
                        icon_url TEXT NOT NULL DEFAULT '',
                        website TEXT NOT NULL DEFAULT '',
                        readme TEXT NOT NULL DEFAULT '',
                        manifest_uri TEXT NOT NULL DEFAULT '',
                        payload_uri TEXT NOT NULL DEFAULT '',
                        payload TEXT NOT NULL DEFAULT '',
                        payload_sha256 TEXT NOT NULL DEFAULT '',
                        user_config_json TEXT NOT NULL DEFAULT '{}',
                        saved_config_json TEXT NOT NULL DEFAULT '{}',
                        marketplace_meta_json TEXT NOT NULL DEFAULT '{}',
                        catalog_state TEXT NOT NULL DEFAULT 'available',
                        is_installed INTEGER NOT NULL DEFAULT 0,
                        is_enabled INTEGER NOT NULL DEFAULT 0,
                        last_error TEXT,
                        health_json TEXT NOT NULL DEFAULT '{}',
                        installed_at TEXT,
                        updated_at TEXT,
                        UNIQUE(repo_id, ext_id)
                    );
                    CREATE INDEX IF NOT EXISTS idx_seanime_extensions_ext_id ON seanime_extensions(ext_id);
                    CREATE INDEX IF NOT EXISTS idx_seanime_extensions_enabled ON seanime_extensions(is_enabled);
                    """
                )
        self._schema_checked = True

    async def _fetch_bytes(self, url: str, max_bytes: int) -> bytes:
        if not await is_safe_url_async(url, allow_private=False):
            raise ValueError(f"URL Seanime bloquée par la protection SSRF : {url}")
        async with source_http.async_client(timeout=25.0, follow_redirects=True) as client:
            resp = await client.request("GET", url, max_response_bytes=max_bytes)
        if resp.status_code >= 400:
            raise ValueError(f"Échec du téléchargement Seanime (HTTP {resp.status_code}) pour {url}")
        return resp.content or b""

    def _row_to_repo_dict(self, row: Any) -> dict[str, Any]:
        return {
            "id": row["id"],
            "url": row["url"],
            "name": row["name"],
            "kind": row["kind"],
            "is_active": bool(row["is_active"]),
            "last_error": row["last_error"],
            "checked_at": row["checked_at"],
            "created_at": row["created_at"],
            "extension_count": row["extension_count"] if "extension_count" in row.keys() else 0,
            "installed_count": row["installed_count"] if "installed_count" in row.keys() else 0,
        }

    def _row_to_ext_dict(self, row: Any, *, include_payload: bool = False) -> dict[str, Any]:
        schema = _safe_json_loads(row["user_config_json"], {})
        saved_config = _safe_json_loads(row["saved_config_json"], {})
        meta = _safe_json_loads(row["marketplace_meta_json"], {})
        health = _safe_json_loads(row["health_json"], {})
        ext_type = str(row["ext_type"])
        supported = ext_type in EXECUTABLE_SEANIME_TYPES
        installed = bool(row["is_installed"])
        enabled = bool(row["is_enabled"])
        fields = schema.get("fields") if isinstance(schema, dict) else []
        needs_config = bool(
            isinstance(schema, dict)
            and schema.get("requiresConfig")
            and isinstance(fields, list)
            and any(
                isinstance(f, dict)
                and f.get("name")
                and not str(saved_config.get(f["name"], "")).strip()
                for f in fields
            )
        )
        data: dict[str, Any] = {
            "id": row["id"],
            "repo_id": row["repo_id"],
            "repo_name": row["repo_name"] if "repo_name" in row.keys() else "",
            "ext_id": row["ext_id"],
            "source_id": f"seanime:{row['ext_id']}".lower() if (installed and supported) else None,
            "name": row["name"],
            "version": row["version"],
            "installed_version": row["installed_version"],
            "available_version": row["available_version"] or row["version"],
            "has_update": bool(row["has_update"]),
            "ext_type": ext_type,
            "supported": supported,
            "language": row["language"],
            "lang": row["lang"],
            "author": row["author"],
            "description": row["description"],
            "notes": row["notes"],
            "icon_url": row["icon_url"],
            "website": row["website"],
            "readme": row["readme"],
            "manifest_uri": row["manifest_uri"],
            "payload_uri": row["payload_uri"],
            "payload_sha256": row["payload_sha256"],
            "user_config": schema if isinstance(schema, dict) else {},
            "saved_config": saved_config if isinstance(saved_config, dict) else {},
            "needs_config": needs_config,
            "marketplace_meta": meta if isinstance(meta, dict) else {},
            "health": {k: v for k, v in health.items() if k != "store"} if isinstance(health, dict) else {},
            "catalog_state": row["catalog_state"],
            "installed": installed,
            "enabled": enabled,
            "last_error": row["last_error"],
            "installed_at": row["installed_at"],
            "updated_at": row["updated_at"],
        }
        if include_payload:
            data["payload"] = row["payload"]
        return data

    def _upsert_catalog_entries(
        self,
        conn: Any,
        repo_id: int,
        entries: list[dict[str, Any]],
    ) -> None:
        existing_rows = {
            row["ext_id"]: row
            for row in conn.execute(
                "SELECT * FROM seanime_extensions WHERE repo_id = ?",
                (repo_id,),
            ).fetchall()
        }
        seen_ext_ids: set[str] = set()
        for entry in entries:
            ext_id = entry["ext_id"]
            seen_ext_ids.add(ext_id)
            prev = existing_rows.get(ext_id)
            installed_version = prev["installed_version"] if prev else None
            has_update = int(compare_seanime_versions(entry["version"], installed_version))
            schema_json = json.dumps(entry.get("user_config") or {}, ensure_ascii=False)
            meta_json = json.dumps(entry.get("marketplace_meta") or {}, ensure_ascii=False)

            if prev is None:
                inline_payload = entry.get("payload") or ""
                conn.execute(
                    """
                    INSERT INTO seanime_extensions (
                        repo_id, ext_id, name, version, installed_version, available_version,
                        has_update, ext_type, language, lang, author, description, notes,
                        icon_url, website, readme, manifest_uri, payload_uri, payload,
                        user_config_json, marketplace_meta_json, catalog_state
                    ) VALUES (?, ?, ?, ?, NULL, ?, 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'available')
                    """,
                    (
                        repo_id,
                        ext_id,
                        entry["name"],
                        entry["version"],
                        entry["version"],
                        entry["ext_type"],
                        entry["language"],
                        entry["lang"],
                        entry["author"],
                        entry["description"],
                        entry["notes"],
                        entry["icon_url"],
                        entry["website"],
                        entry["readme"],
                        entry["manifest_uri"],
                        entry["payload_uri"],
                        inline_payload,
                        schema_json,
                        meta_json,
                    ),
                )
            else:
                # Preserve installed payload/version/user config until an explicit update.
                new_schema = prev["user_config_json"] if prev["is_installed"] else schema_json
                conn.execute(
                    """
                    UPDATE seanime_extensions SET
                        name = ?,
                        version = CASE WHEN is_installed = 1 THEN version ELSE ? END,
                        available_version = ?,
                        has_update = ?,
                        ext_type = ?,
                        language = ?,
                        lang = ?,
                        author = ?,
                        description = ?,
                        notes = ?,
                        icon_url = ?,
                        website = ?,
                        readme = ?,
                        manifest_uri = ?,
                        payload_uri = CASE WHEN is_installed = 1 AND payload_uri != '' THEN payload_uri ELSE ? END,
                        user_config_json = ?,
                        marketplace_meta_json = ?,
                        catalog_state = CASE WHEN is_installed = 1 THEN 'installed' ELSE 'available' END
                    WHERE id = ?
                    """,
                    (
                        entry["name"],
                        entry["version"],
                        entry["version"],
                        has_update,
                        entry["ext_type"],
                        entry["language"],
                        entry["lang"],
                        entry["author"],
                        entry["description"],
                        entry["notes"],
                        entry["icon_url"],
                        entry["website"],
                        entry["readme"],
                        entry["manifest_uri"],
                        entry["payload_uri"],
                        new_schema,
                        meta_json,
                        prev["id"],
                    ),
                )

        # Mark non-installed entries missing from latest index as removed instead of breaking installed ones.
        for ext_id, prev in existing_rows.items():
            if ext_id not in seen_ext_ids and not prev["is_installed"]:
                conn.execute("DELETE FROM seanime_extensions WHERE id = ?", (prev["id"],))

    async def import_repository(self, url: str, *, name: str | None = None) -> dict[str, Any]:
        """Import or refresh a Seanime Marketplace, ``{urls:[...]}`` repo, or direct manifest."""
        self._ensure_tables()
        catalog = await read_seanime_catalog(url, self._fetch_bytes)
        display_name = (name or "").strip() or catalog.name

        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                INSERT INTO seanime_repos (url, name, kind, is_active, last_error, checked_at)
                VALUES (?, ?, ?, 1, NULL, CURRENT_TIMESTAMP)
                ON CONFLICT(url) DO UPDATE SET
                    name = excluded.name,
                    kind = excluded.kind,
                    is_active = 1,
                    last_error = NULL,
                    checked_at = CURRENT_TIMESTAMP
                """,
                (catalog.url, display_name, catalog.kind),
            )
            repo_row = conn.execute(
                "SELECT * FROM seanime_repos WHERE url = ?",
                (catalog.url,),
            ).fetchone()
            repo_id = repo_row["id"]
            self._upsert_catalog_entries(conn, repo_id, catalog.entries)
            refreshed = conn.execute(
                """
                SELECT r.*,
                       COUNT(e.id) AS extension_count,
                       SUM(CASE WHEN e.is_installed = 1 THEN 1 ELSE 0 END) AS installed_count
                FROM seanime_repos r
                LEFT JOIN seanime_extensions e ON e.repo_id = r.id
                WHERE r.id = ?
                GROUP BY r.id
                """,
                (repo_id,),
            ).fetchone()

        return {
            "repo": self._row_to_repo_dict(refreshed),
            "count": len(catalog.entries),
            "executable_count": sum(
                1 for entry in catalog.entries if entry["ext_type"] in EXECUTABLE_SEANIME_TYPES
            ),
            "warnings": catalog.warnings,
        }

    def list_repositories(self) -> list[dict[str, Any]]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT r.*,
                       COUNT(e.id) AS extension_count,
                       SUM(CASE WHEN e.is_installed = 1 THEN 1 ELSE 0 END) AS installed_count
                FROM seanime_repos r
                LEFT JOIN seanime_extensions e ON e.repo_id = r.id
                GROUP BY r.id
                ORDER BY r.id ASC
                """
            ).fetchall()
        return [self._row_to_repo_dict(row) for row in rows]

    def set_repository_enabled(self, repo_id: int, enabled: bool) -> dict[str, Any]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM seanime_repos WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                raise KeyError(f"Dépôt Seanime {repo_id} introuvable")
            conn.execute(
                "UPDATE seanime_repos SET is_active = ? WHERE id = ?",
                (1 if enabled else 0, repo_id),
            )
            if not enabled:
                conn.execute(
                    "UPDATE seanime_extensions SET is_enabled = 0 WHERE repo_id = ?",
                    (repo_id,),
                )
            refreshed = conn.execute(
                """
                SELECT r.*,
                       COUNT(e.id) AS extension_count,
                       SUM(CASE WHEN e.is_installed = 1 THEN 1 ELSE 0 END) AS installed_count
                FROM seanime_repos r
                LEFT JOIN seanime_extensions e ON e.repo_id = r.id
                WHERE r.id = ?
                GROUP BY r.id
                """,
                (repo_id,),
            ).fetchone()
        return self._row_to_repo_dict(refreshed)

    def delete_repository(self, repo_id: int) -> None:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute("SELECT * FROM seanime_repos WHERE id = ?", (repo_id,)).fetchone()
            if not row:
                raise KeyError(f"Dépôt Seanime {repo_id} introuvable")
            ext_rows = conn.execute(
                "SELECT ext_id FROM seanime_extensions WHERE repo_id = ?",
                (repo_id,),
            ).fetchall()
            for item in ext_rows:
                self.runtime.clear_store(item["ext_id"])
            conn.execute("DELETE FROM seanime_extensions WHERE repo_id = ?", (repo_id,))
            conn.execute("DELETE FROM seanime_repos WHERE id = ?", (repo_id,))

    async def refresh_repositories(self, repo_id: int | None = None) -> dict[str, Any]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            if repo_id is not None:
                repos = conn.execute("SELECT * FROM seanime_repos WHERE id = ?", (repo_id,)).fetchall()
            else:
                repos = conn.execute("SELECT * FROM seanime_repos WHERE is_active = 1").fetchall()

        refreshed: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for repo in repos:
            try:
                res = await self.import_repository(repo["url"], name=repo["name"])
                refreshed.append(res)
            except Exception as exc:
                errors.append({"repo_id": repo["id"], "url": repo["url"], "error": str(exc)})
                with sqlite_connection(self.db_path) as conn:
                    conn.execute(
                        "UPDATE seanime_repos SET last_error = ?, checked_at = CURRENT_TIMESTAMP WHERE id = ?",
                        (str(exc), repo["id"]),
                    )
        return {"refreshed": refreshed, "errors": errors}

    def list_extensions(
        self,
        *,
        repo_id: int | None = None,
        ext_type: str | None = None,
        installed_only: bool = False,
        search: str | None = None,
        supported_only: bool = False,
    ) -> dict[str, Any]:
        self._ensure_tables()
        clauses = ["1=1"]
        params: list[Any] = []
        if repo_id is not None:
            clauses.append("e.repo_id = ?")
            params.append(repo_id)
        if ext_type and ext_type in SEANIME_TYPES:
            clauses.append("e.ext_type = ?")
            params.append(ext_type)
        if installed_only:
            clauses.append("e.is_installed = 1")
        if supported_only:
            clauses.append("e.ext_type = 'onlinestream-provider'")
        if search and search.strip():
            like = f"%{search.strip().lower()}%"
            clauses.append(
                "(LOWER(e.name) LIKE ? OR LOWER(e.ext_id) LIKE ? OR LOWER(e.description) LIKE ? OR LOWER(e.author) LIKE ?)"
            )
            params.extend([like, like, like, like])

        where_sql = " AND ".join(clauses)
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                f"""
                SELECT e.*, r.name AS repo_name
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE {where_sql}
                ORDER BY e.is_installed DESC, e.is_enabled DESC,
                         CASE WHEN e.ext_type = 'onlinestream-provider' THEN 0 ELSE 1 END,
                         LOWER(e.name) ASC
                """,
                params,
            ).fetchall()
            counts_rows = conn.execute(
                """
                SELECT ext_type,
                       COUNT(*) AS total,
                       SUM(CASE WHEN is_installed = 1 THEN 1 ELSE 0 END) AS installed,
                       SUM(CASE WHEN is_enabled = 1 THEN 1 ELSE 0 END) AS enabled,
                       SUM(CASE WHEN has_update = 1 AND is_installed = 1 THEN 1 ELSE 0 END) AS updates
                FROM seanime_extensions
                GROUP BY ext_type
                """
            ).fetchall()

        by_type = {
            r["ext_type"]: {
                "total": r["total"],
                "installed": r["installed"] or 0,
                "enabled": r["enabled"] or 0,
                "updates": r["updates"] or 0,
            }
            for r in counts_rows
        }
        return {
            "runtime_available": self.runtime.is_available(),
            "engine": self.runtime.engine_name(),
            "extensions": [self._row_to_ext_dict(row) for row in rows],
            "counts": by_type,
            "repositories": self.list_repositories(),
        }

    def _find_extension_row(
        self,
        conn: Any,
        ext_id: str,
        *,
        repo_id: int | None = None,
    ) -> Any:
        if repo_id is not None:
            row = conn.execute(
                """
                SELECT e.*, r.name AS repo_name, r.is_active AS repo_active
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.ext_id = ? AND e.repo_id = ?
                """,
                (ext_id, repo_id),
            ).fetchone()
        else:
            row = conn.execute(
                """
                SELECT e.*, r.name AS repo_name, r.is_active AS repo_active
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.ext_id = ?
                ORDER BY e.is_installed DESC, e.id ASC
                LIMIT 1
                """,
                (ext_id,),
            ).fetchone()
        if not row:
            raise KeyError(f"Extension Seanime '{ext_id}' introuvable.")
        return row

    async def install_extension(
        self,
        ext_id: str,
        *,
        repo_id: int | None = None,
        enable: bool = True,
    ) -> dict[str, Any]:
        """Fetch full manifest/payload, verify V8 compilation, and install an extension."""
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id, repo_id=repo_id)

        if row["ext_type"] not in EXECUTABLE_SEANIME_TYPES:
            raise ValueError(
                f"Type Seanime '{row['ext_type']}' non pris en charge pour la lecture vidéo (onlinestream-provider uniquement)."
            )

        manifest_uri = str(row["manifest_uri"] or "").strip()
        if manifest_uri:
            full = await fetch_full_manifest(
                manifest_uri,
                self._fetch_bytes,
                fallback_payload_uri=str(row["payload_uri"] or ""),
            )
        elif row["payload"]:
            raw_obj = {
                "id": row["ext_id"],
                "name": row["name"],
                "version": row["version"],
                "type": row["ext_type"],
                "language": row["language"],
                "lang": row["lang"],
                "author": row["author"],
                "description": row["description"],
                "notes": row["notes"],
                "icon": row["icon_url"],
                "website": row["website"],
                "readme": row["readme"],
                "payload": row["payload"],
                "userConfig": _safe_json_loads(row["user_config_json"], {}),
            }
            full = normalize_manifest(raw_obj)
            import hashlib

            full["payload_sha256"] = hashlib.sha256(full["payload"].encode("utf-8")).hexdigest()
        else:
            raise ValueError(f"Aucun manifeste ni code source disponible pour '{ext_id}'.")

        if full["ext_type"] not in EXECUTABLE_SEANIME_TYPES:
            raise ValueError(
                f"Type Seanime '{full['ext_type']}' non pris en charge (onlinestream-provider uniquement)."
            )

        ok, syntax_err = self.runtime.validate_syntax(
            full["payload"],
            language=full["language"],
            extension_id=full["ext_id"],
        )
        if not ok:
            with sqlite_connection(self.db_path) as conn:
                conn.execute(
                    "UPDATE seanime_extensions SET last_error = ? WHERE id = ?",
                    (syntax_err, row["id"]),
                )
            raise ValueError(f"Validation JS/TS échouée pour {ext_id} : {syntax_err}")

        saved_config = _safe_json_loads(row["saved_config_json"], {})
        defaults = _build_defaults(full["user_config"])
        for k, v in defaults.items():
            saved_config.setdefault(k, v)

        with sqlite_connection(self.db_path) as conn:
            conn.execute(
                """
                UPDATE seanime_extensions SET
                    name = ?,
                    version = ?,
                    installed_version = ?,
                    available_version = ?,
                    has_update = 0,
                    language = ?,
                    lang = ?,
                    author = ?,
                    description = ?,
                    notes = ?,
                    icon_url = ?,
                    website = ?,
                    readme = ?,
                    manifest_uri = COALESCE(NULLIF(?, ''), manifest_uri),
                    payload_uri = COALESCE(NULLIF(?, ''), payload_uri),
                    payload = ?,
                    payload_sha256 = ?,
                    user_config_json = ?,
                    saved_config_json = ?,
                    catalog_state = 'installed',
                    is_installed = 1,
                    is_enabled = ?,
                    last_error = NULL,
                    installed_at = COALESCE(installed_at, CURRENT_TIMESTAMP),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?
                """,
                (
                    full["name"],
                    full["version"],
                    full["version"],
                    full["version"],
                    full["language"],
                    full["lang"],
                    full["author"],
                    full["description"],
                    full["notes"],
                    full["icon_url"],
                    full["website"],
                    full["readme"],
                    full["manifest_uri"],
                    full["payload_uri"],
                    full["payload"],
                    full["payload_sha256"],
                    json.dumps(full["user_config"], ensure_ascii=False),
                    json.dumps(saved_config, ensure_ascii=False),
                    1 if enable else 0,
                    row["id"],
                ),
            )
            updated = conn.execute(
                """
                SELECT e.*, r.name AS repo_name
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.id = ?
                """,
                (row["id"],),
            ).fetchone()
        return self._row_to_ext_dict(updated)

    async def install_from_manifest_url(self, manifest_url: str, *, enable: bool = True) -> dict[str, Any]:
        """Import a standalone manifest URL into Seanime repos and immediately install it."""
        self._ensure_tables()
        imported = await self.import_repository(manifest_url)
        entries = self.list_extensions(repo_id=imported["repo"]["id"])["extensions"]
        if not entries:
            raise ValueError("Aucune extension trouvée dans ce manifeste.")
        target = entries[0]
        return await self.install_extension(
            target["ext_id"],
            repo_id=imported["repo"]["id"],
            enable=enable,
        )

    def toggle_extension(self, ext_id: str, enabled: bool) -> dict[str, Any]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
            if not row["is_installed"]:
                raise ValueError(f"L'extension '{ext_id}' doit être installée avant d'être activée.")
            if enabled and row["ext_type"] not in EXECUTABLE_SEANIME_TYPES:
                raise ValueError(f"Type Seanime '{row['ext_type']}' non exécutable.")
            conn.execute(
                "UPDATE seanime_extensions SET is_enabled = ? WHERE id = ?",
                (1 if enabled else 0, row["id"]),
            )
            updated = conn.execute(
                """
                SELECT e.*, r.name AS repo_name
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.id = ?
                """,
                (row["id"],),
            ).fetchone()
        return self._row_to_ext_dict(updated)

    def uninstall_extension(self, ext_id: str) -> dict[str, Any]:
        self._ensure_tables()
        self.runtime.clear_store(ext_id)
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
            conn.execute(
                """
                UPDATE seanime_extensions SET
                    installed_version = NULL,
                    has_update = 0,
                    payload = '',
                    payload_sha256 = '',
                    catalog_state = 'available',
                    is_installed = 0,
                    is_enabled = 0,
                    last_error = NULL
                WHERE id = ?
                """,
                (row["id"],),
            )
            updated = conn.execute(
                """
                SELECT e.*, r.name AS repo_name
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.id = ?
                """,
                (row["id"],),
            ).fetchone()
        return self._row_to_ext_dict(updated)

    async def check_updates(self) -> dict[str, Any]:
        refresh_info = await self.refresh_repositories()
        listing = self.list_extensions(installed_only=True)
        updates = [item for item in listing["extensions"] if item["has_update"]]
        return {
            "updates": updates,
            "count": len(updates),
            "refresh": refresh_info,
        }

    async def update_extension(self, ext_id: str) -> dict[str, Any]:
        """Update an installed extension while preserving ``saved_config`` and ``is_enabled``."""
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
            if not row["is_installed"]:
                raise ValueError(f"L'extension '{ext_id}' n'est pas installée.")
            was_enabled = bool(row["is_enabled"])
        return await self.install_extension(ext_id, repo_id=row["repo_id"], enable=was_enabled)

    async def update_all_extensions(self) -> dict[str, Any]:
        self._ensure_tables()
        listing = self.list_extensions(installed_only=True)
        targets = [item["ext_id"] for item in listing["extensions"] if item["has_update"]]
        updated: list[dict[str, Any]] = []
        errors: list[dict[str, Any]] = []
        for ext_id in targets:
            try:
                updated.append(await self.update_extension(ext_id))
            except Exception as exc:
                errors.append({"ext_id": ext_id, "error": str(exc)})
        return {"updated": updated, "errors": errors}

    def get_user_config(self, ext_id: str) -> dict[str, Any]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
        schema = _safe_json_loads(row["user_config_json"], {})
        saved = _safe_json_loads(row["saved_config_json"], {})
        defaults = _build_defaults(schema if isinstance(schema, dict) else {})
        return {
            "ext_id": row["ext_id"],
            "name": row["name"],
            "schema": schema if isinstance(schema, dict) else {},
            "values": {**defaults, **(saved if isinstance(saved, dict) else {})},
            "defaults": defaults,
        }

    def save_user_config(self, ext_id: str, values: dict[str, Any]) -> dict[str, Any]:
        self._ensure_tables()
        if not isinstance(values, dict):
            raise ValueError("Configuration invalide.")
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
            schema = _safe_json_loads(row["user_config_json"], {})
            allowed_keys = {
                str(f["name"])
                for f in (schema.get("fields") or [])
                if isinstance(f, dict) and f.get("name")
            }
            clean_values: dict[str, str] = {}
            for k, v in values.items():
                key = str(k)
                if allowed_keys and key not in allowed_keys:
                    continue
                if isinstance(v, bool):
                    clean_values[key] = "true" if v else "false"
                elif v is not None:
                    clean_values[key] = str(v)[:4096]
            conn.execute(
                "UPDATE seanime_extensions SET saved_config_json = ?, updated_at = CURRENT_TIMESTAMP WHERE id = ?",
                (json.dumps(clean_values, ensure_ascii=False), row["id"]),
            )
        return self.get_user_config(ext_id)

    def _load_source_state(self, ext_id: str) -> dict[str, Any]:
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT ext_id, language, payload, user_config_json, saved_config_json, health_json
                FROM seanime_extensions
                WHERE ext_id = ? AND is_installed = 1
                ORDER BY is_enabled DESC, id ASC
                LIMIT 1
                """,
                (ext_id,),
            ).fetchone()
        if not row:
            return {}
        schema = _safe_json_loads(row["user_config_json"], {})
        saved = _safe_json_loads(row["saved_config_json"], {})
        health = _safe_json_loads(row["health_json"], {})
        store = health.get("store") if isinstance(health, dict) and isinstance(health.get("store"), dict) else {}
        return {
            "payload": row["payload"] or "",
            "language": row["language"] or "javascript",
            "defaults": _build_defaults(schema if isinstance(schema, dict) else {}),
            "saved_config": saved if isinstance(saved, dict) else {},
            "store": store,
        }

    def _save_source_store(self, ext_id: str, new_store: dict[str, Any]) -> None:
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                "SELECT id, health_json FROM seanime_extensions WHERE ext_id = ? AND is_installed = 1 LIMIT 1",
                (ext_id,),
            ).fetchone()
            if not row:
                return
            health = _safe_json_loads(row["health_json"], {})
            if not isinstance(health, dict):
                health = {}
            health["store"] = dict(new_store or {})
            conn.execute(
                "UPDATE seanime_extensions SET health_json = ? WHERE id = ?",
                (json.dumps(health, ensure_ascii=False), row["id"]),
            )

    def _build_source(self, row: Any) -> SeanimeSource:
        return SeanimeSource(
            db_path=self.db_path,
            extension_id=row["ext_id"],
            name=row["name"],
            lang=row["lang"] or "en",
            icon=row["icon_url"] or "",
            base_url=row["website"] or "",
            version=row["installed_version"] or row["version"] or "1.0.0",
            runtime_backend=self.runtime,
            state_loader=self._load_source_state,
            store_saver=self._save_source_store,
        )

    def get_enabled_sources(self) -> list[SeanimeSource]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT e.*
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE e.is_installed = 1
                  AND e.is_enabled = 1
                  AND e.ext_type = 'onlinestream-provider'
                  AND r.is_active = 1
                ORDER BY LOWER(e.name) ASC
                """
            ).fetchall()
        seen: set[str] = set()
        sources: list[SeanimeSource] = []
        for row in rows:
            if row["ext_id"] in seen:
                continue
            seen.add(row["ext_id"])
            sources.append(self._build_source(row))
        return sources

    def get_source_by_id(self, source_id: str) -> SeanimeSource | None:
        self._ensure_tables()
        cleaned = (source_id or "").strip()
        if not cleaned:
            return None
        lower = cleaned.lower()
        ext_key = lower.removeprefix("seanime:") if lower.startswith("seanime:") else lower
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute(
                """
                SELECT e.*
                FROM seanime_extensions e
                JOIN seanime_repos r ON r.id = e.repo_id
                WHERE LOWER(e.ext_id) = ?
                  AND e.is_installed = 1
                  AND e.ext_type = 'onlinestream-provider'
                ORDER BY (e.is_enabled AND r.is_active) DESC, e.id ASC
                LIMIT 1
                """,
                (ext_key,),
            ).fetchone()
        if not row:
            return None
        return self._build_source(row)

    async def diagnose_extension(self, ext_id: str, *, query: str = "naruto") -> dict[str, Any]:
        self._ensure_tables()
        with sqlite_connection(self.db_path) as conn:
            row = self._find_extension_row(conn, ext_id)
        if not row["is_installed"]:
            raise ValueError(f"L'extension '{ext_id}' doit être installée avant le diagnostic.")
        if row["ext_type"] not in EXECUTABLE_SEANIME_TYPES:
            raise ValueError(f"Type Seanime '{row['ext_type']}' non exécutable.")
        source = self._build_source(row)
        report = await source.diagnose(query=query)
        with sqlite_connection(self.db_path) as conn:
            cur = _safe_json_loads(row["health_json"], {})
            if not isinstance(cur, dict):
                cur = {}
            cur["last_diagnose"] = report
            conn.execute(
                "UPDATE seanime_extensions SET health_json = ?, last_error = ? WHERE id = ?",
                (json.dumps(cur, ensure_ascii=False), report.get("error"), row["id"]),
            )
        return report

    def get_allowed_domains(self) -> set[str]:
        self._ensure_tables()
        domains: set[str] = set()
        with sqlite_connection(self.db_path) as conn:
            rows = conn.execute(
                """
                SELECT website, manifest_uri, payload_uri, user_config_json, saved_config_json
                FROM seanime_extensions
                WHERE is_installed = 1 AND is_enabled = 1
                """
            ).fetchall()
        for row in rows:
            candidates: list[str] = [row["website"] or "", row["manifest_uri"] or "", row["payload_uri"] or ""]
            for col in (row["user_config_json"], row["saved_config_json"]):
                obj = _safe_json_loads(col, {})
                if isinstance(obj, dict):
                    for v in obj.values():
                        if isinstance(v, str) and v.startswith(("http://", "https://")):
                            candidates.append(v)
                    for field in obj.get("fields") or []:
                        if isinstance(field, dict) and isinstance(field.get("default"), str):
                            if field["default"].startswith(("http://", "https://")):
                                candidates.append(field["default"])
            for raw in candidates:
                if not raw:
                    continue
                host = (urlparse(raw).hostname or "").lower()
                if host and host != "seanime.local":
                    domains.add(host)
        return domains


seanime_service = SeanimeExtensionService()
