from animelab.services.extension_observability import save_recipe_revision,extension_observability,HEALTH_MESSAGES
from animelab.database import init_db, sqlite_connection
from animelab.services.source_http import source_http, VerificationRequired
import asyncio
import json
import hashlib
import io
import logging
import os
import re
import urllib.request
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Any, Optional, Set
from urllib.parse import urlparse, urljoin
import httpx
import zipfile

from animelab.security import is_safe_url
from animelab.config import settings
from animelab.services.aniyomi_dex_parser import AniyomiDexParser, SourceRecipe
from animelab.services.aniyomi_container import AniyomiContainerSource
from animelab.services.extension_versions import newer, version_code
from animelab.services.extension_catalog import read_catalog, MAX_INDEX_BYTES

logger = logging.getLogger("animelab.extensions")

EXTENSIONS_DIR = Path.home() / ".animan" / "extensions"
APKS_DIR = EXTENSIONS_DIR / "apks"
EXTENSIONS_DIR.mkdir(parents=True, exist_ok=True)
APKS_DIR.mkdir(parents=True, exist_ok=True)


class ExtensionService:
    """Service de gestion des dépôts et extensions Aniyomi compatibles."""

    def __init__(self, db_path: Optional[str] = None):
        self.db_path = db_path or settings.DATABASE_PATH
        self._active_container_sources: Dict[str, AniyomiContainerSource] = {}
        self._init_db()
        self._load_enabled_sources()

    def _get_conn(self):
        return sqlite_connection(self.db_path)

    def _init_db(self):
        init_db(self.db_path)

    # -------------------------------------------------------------------------
    # Gestion des dépôts
    # -------------------------------------------------------------------------

    async def import_repository(self, repo_url: str) -> Dict[str, Any]:
        """Importe massivement un catalogue d'extensions depuis une URL compatible Aniyomi (index.min.json).
        Les dépôts coexistent ; le catalogue ne modifie jamais une installation.
        RÈGLE : Toutes les sources importées sont désactivées par défaut (is_enabled = 0).
        """
        catalog = await read_catalog(repo_url, self._fetch_catalog_bytes)
        clean_url, data = catalog.url, catalog.entries
        metadata = catalog.metadata
        declared_key = str(metadata.get('signingKeyFingerprint') or '')
        if declared_key and not re.fullmatch(r'[0-9a-fA-F]{64}', declared_key):
            raise ValueError('Empreinte de signature de dépôt invalide.')
        declared_key = declared_key.lower() or None

        # Déduction du nom du dépôt et de la racine des APKs
        parsed_url = urlparse(clean_url)
        path_parts = parsed_url.path.strip("/").split("/")
        repo_name = "Magasin Aniyomi"
        if len(path_parts) >= 2:
            repo_name = f"{path_parts[0]}/{path_parts[1]}"
        elif parsed_url.netloc:
            repo_name = f"Dépôt {parsed_url.netloc}"

        repo_name = str(metadata.get('name') or repo_name)
        # Racine relative pour les APKs
        # Ex: https://raw.githubusercontent.com/yuzono/anime-repo/repo/index.min.json -> https://raw.githubusercontent.com/yuzono/anime-repo/repo/apk/
        repo_base = clean_url.rsplit("/", 1)[0]
        apk_base_dir = f"{repo_base}/apk"

        # Insertion en base et bascule du magasin actif
        with self._get_conn() as conn:
            cursor = conn.cursor()

            # 1. RÈGLE : Désactive tous les dépôts existants
            # Repository visibility and installed source lifetime are independent.

            # 2. Insère ou réactive le dépôt ciblé
            cursor.execute("""
                INSERT INTO extension_repos (url, name, is_active, created_at)
                VALUES (?, ?, 1, CURRENT_TIMESTAMP)
                ON CONFLICT(url) DO UPDATE SET
                    name = excluded.name,
                    is_active = 1,
                    created_at = CURRENT_TIMESTAMP;
            """, (clean_url, repo_name))

            cursor.execute("SELECT id FROM extension_repos WHERE url = ?;", (clean_url,))
            repo_id = cursor.fetchone()["id"]

            previous_key = cursor.execute('SELECT signing_key FROM extension_repos WHERE id=?', (repo_id,)).fetchone()['signing_key']
            pending = declared_key if previous_key and declared_key and previous_key != declared_key else None
            cursor.execute('UPDATE extension_repos SET signing_key=COALESCE(signing_key,?), pending_signing_key=?, metadata_json=?, checked_at=CURRENT_TIMESTAMP, snapshot_hash=? WHERE id=?',
                           (declared_key, pending, json.dumps({k:v for k,v in metadata.items() if k not in ('extensionList','extensionListUrl')}),
                            hashlib.sha256(json.dumps(data,sort_keys=True).encode()).hexdigest(), repo_id))
            cursor.execute('UPDATE extension_offers SET present=0 WHERE repo_id=?', (repo_id,))

            # 3. Importe massivement toutes les extensions (désactivées par défaut)
            imported_count = 0
            seen_packages = set()
            for item in data:
                if not isinstance(item, dict):
                    continue
                pkg = item.get("pkg") or ""
                if not isinstance(pkg, str) or not re.fullmatch(r"[A-Za-z0-9_.]+", pkg) or pkg in seen_packages:
                    continue
                seen_packages.add(pkg)
                name = item.get("name") or pkg
                lang = item.get("lang") or "all"
                version = item.get("version") or str(item.get("code") or "1.0")
                remote_code = version_code(item.get('code'))
                raw_apk = item.get("apk") or ""

                if raw_apk.startswith("http"):
                    apk_url = raw_apk
                elif raw_apk:
                    apk_url = f"{apk_base_dir}/{raw_apk}"
                else:
                    apk_url = ""

                sources = item.get("sources") or []
                base_url = ""
                if sources and isinstance(sources, list) and isinstance(sources[0], dict):
                    base_url = sources[0].get("baseUrl") or ""

                icon_url = ""
                icon_file = item.get("icon")
                if icon_file:
                    icon_url = f"{repo_base}/icon/{icon_file}" if not icon_file.startswith("http") else icon_file

                cursor.execute("""
                    INSERT INTO imported_extensions (
                        repo_id, pkg, name, lang, version, available_version, apk_url, available_apk_url,
                        base_url, available_base_url, icon_url, sources_meta, is_enabled, has_update, available_code
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0, 0, ?)
                    ON CONFLICT(repo_id, pkg) DO UPDATE SET
                        name = excluded.name,
                        lang = excluded.lang,
                        version = CASE WHEN installed_version IS NOT NULL OR recipe_json IS NOT NULL OR is_enabled=1 THEN version ELSE excluded.version END,
                        available_version = excluded.version,
                        apk_url = CASE WHEN installed_version IS NOT NULL OR recipe_json IS NOT NULL OR is_enabled=1 THEN apk_url ELSE excluded.apk_url END,
                        available_apk_url = excluded.apk_url,
                        available_base_url = excluded.base_url,
                        base_url = CASE WHEN installed_version IS NOT NULL OR recipe_json IS NOT NULL OR is_enabled=1 THEN base_url ELSE excluded.base_url END,
                        icon_url = excluded.icon_url,
                        sources_meta = excluded.sources_meta,
                        catalog_state = 'available',
                        available_code = excluded.available_code;
                """, (
                    repo_id, pkg, name, lang, version, version, apk_url, apk_url, base_url, base_url, icon_url, json.dumps(sources), remote_code
                ))
                extension_lib = item.get('extensionLib')
                cursor.execute('UPDATE imported_extensions SET extension_lib=?, declared_signer=? WHERE repo_id=? AND pkg=?',
                               (extension_lib, declared_key, repo_id, pkg))
                cursor.execute("INSERT INTO extension_offers(repo_id,pkg,version_code,version_name,extension_lib,signer,apk_url,metadata_json,present) VALUES (?,?,?,?,?,?,?,?,1) "
                               "ON CONFLICT(repo_id,pkg) DO UPDATE SET version_code=excluded.version_code,version_name=excluded.version_name,extension_lib=excluded.extension_lib,signer=excluded.signer,apk_url=excluded.apk_url,metadata_json=excluded.metadata_json,present=1",
                               (repo_id,pkg,remote_code,version,extension_lib,declared_key,apk_url,json.dumps(item)))
                imported_count += 1

            if data and not seen_packages:
                raise ValueError("Le dépôt ne contient aucune extension valide.")
            if seen_packages:
                placeholders = ",".join("?" for _ in seen_packages)
                cursor.execute(f"UPDATE imported_extensions SET catalog_state='retired', has_update=0 WHERE repo_id=? AND pkg NOT IN ({placeholders})", (repo_id, *seen_packages))
            else:
                cursor.execute("UPDATE imported_extensions SET catalog_state='retired', has_update=0 WHERE repo_id=?", (repo_id,))
            for row in cursor.execute('SELECT * FROM imported_extensions WHERE repo_id=?', (repo_id,)).fetchall():
                update = row['catalog_state'] == 'available' and newer(row['available_version'], row['installed_version'], row['available_code'], row['installed_code'])
                cursor.execute('UPDATE imported_extensions SET has_update=? WHERE id=?', (int(update), row['id']))
            conn.commit()

        # Réinitialise le cache des sources en mémoire pour ne conserver que celles du dépôt actif
        self._load_enabled_sources()

        logger.info("[extensions] %d extensions imported from %s (All disabled by default)", imported_count, repo_name)
        return {
            "success": True,
            "repo_id": repo_id,
            "repo_name": repo_name,
            "repo_url": clean_url,
            "count": imported_count,
        }

    async def _fetch_catalog_bytes(self, url):
        async with source_http.async_client(timeout=15.0, verify=settings.SSL_VERIFY, follow_redirects=True,
                                            event_hooks={'request': [self._validate_request]}) as client:
            response = await client.get(url, headers={'User-Agent': settings.DEFAULT_USER_AGENT}, max_response_bytes=MAX_INDEX_BYTES)
            if response.status_code != 200:
                raise ValueError(f'Catalogue indisponible (HTTP {response.status_code}).')
            if len(response.content) > MAX_INDEX_BYTES:
                raise ValueError('Index trop volumineux.')
            return response.content

    def get_active_repository(self) -> Optional[Dict[str, Any]]:
        """Retourne le dernier magasin d'extensions ajouté (seul actif)."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM extension_repos WHERE is_active = 1 ORDER BY id DESC LIMIT 1;")
            row = cursor.fetchone()
            return dict(row) if row else None

    @staticmethod
    def _build_capabilities_summary(entry: Dict[str, Any]) -> Dict[str, Any]:
        """Résume les recettes disponibles (populaires, tags, tris, flux dédiés) d'une extension."""
        recipe_data: Dict[str, Any] = {}
        if entry.get("recipe_json"):
            try:
                recipe_data = json.loads(entry["recipe_json"])
            except Exception:
                recipe_data = {}
        try:
            recipe = SourceRecipe.from_dict(recipe_data) if recipe_data else SourceRecipe(
                pkg=entry.get("pkg") or "",
                name=entry.get("name") or "",
                base_url=entry.get("base_url") or "",
                lang=entry.get("lang") or "all",
            )
            AniyomiDexParser._fill_heuristics(recipe)
            if recipe_data:
                recipe = SourceRecipe.from_dict({
                    **recipe.to_dict(),
                    **{k: v for k, v in recipe_data.items() if v not in ("", None, [])},
                })
        except Exception:
            recipe = SourceRecipe(
                pkg=entry.get("pkg") or "",
                name=entry.get("name") or "",
                base_url=entry.get("base_url") or "",
                lang=entry.get("lang") or "all",
            )
            AniyomiDexParser._fill_heuristics(recipe)
        return {
            "popular": bool(recipe.popular_request_path and recipe.popular_selector),
            "latest": bool(recipe.latest_request_path and recipe.latest_selector),
            "search": bool(recipe.search_request_path and recipe.search_selector),
            "multi_tags": bool(recipe.multi_tags),
            "tags_count": len(recipe.filter_tags or []),
            "orders_count": len(recipe.filter_orders or []),
            "feeds_count": len(recipe.custom_feeds or []),
            "custom_feeds": [
                f.get("label", f.get("id", ""))
                for f in (recipe.custom_feeds or [])
                if isinstance(f, dict) and (f.get("label") or f.get("id"))
            ],
            "multisrc_theme": recipe.multisrc_theme or "",
        }

    def get_visible_extensions(self, query: Optional[str] = None, lang: Optional[str] = None, enabled_only: bool = False) -> List[Dict[str, Any]]:
        """Retourne uniquement les extensions présentes dans le dernier magasin ajouté."""
        sql = ("SELECT e.*, r.name AS repo_name, r.url AS repo_url FROM imported_extensions e "
               "JOIN extension_repos r ON r.id=e.repo_id WHERE (r.is_active=1 OR e.installed_version IS NOT NULL OR e.recipe_json IS NOT NULL OR e.is_enabled=1)")
        params: List[Any] = []

        if query:
            sql += " AND (e.name LIKE ? OR e.pkg LIKE ? OR e.base_url LIKE ?)"
            q_like = f"%{query.strip()}%"
            params.extend([q_like, q_like, q_like])

        if lang and lang != "all":
            sql += " AND lang = ?"
            params.append(lang.lower().strip())

        if enabled_only:
            sql += " AND is_enabled = 1"

        sql += " ORDER BY has_update DESC, is_enabled DESC, lang = 'fr' DESC, e.name ASC;"

        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute(sql, tuple(params))
            rows = cursor.fetchall()
            entries = [dict(r) for r in rows]
            for entry in entries:
                entry["health"] = extension_observability.health(conn, entry["id"])
                is_installed = bool(entry.get("is_enabled") or entry.get("recipe_json") or entry.get("installed_version"))
                installed_ver = entry.get("installed_version") or (entry.get("version") if is_installed else None)
                available_ver = entry.get("available_version") or entry.get("version")
                has_update = entry.get('catalog_state') == 'available' and is_installed and newer(
                    available_ver, installed_ver, entry.get('available_code'), entry.get('installed_code'))
                entry["is_installed"] = is_installed
                entry["installed_version"] = installed_ver
                entry["available_version"] = available_ver
                entry["has_update"] = has_update
                entry["capabilities_summary"] = self._build_capabilities_summary(entry)
            return entries

    # -------------------------------------------------------------------------
    # Activation, Mise à jour & Compilation de Recette
    # -------------------------------------------------------------------------

    async def toggle_extension(self, ext_id: int, enabled: bool) -> Dict[str, Any]:
        """Active ou désactive manuellement une extension du magasin actif."""
        with self._get_conn() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM imported_extensions WHERE id = ?;", (ext_id,))
            row = cursor.fetchone()
            if not row:
                raise ValueError("Extension introuvable.")

            ext_data = dict(row)
            if enabled and not ext_data.get('installed_version') and not ext_data.get('recipe_json'):
                repo = cursor.execute('SELECT is_active FROM extension_repos WHERE id=?', (ext_data['repo_id'],)).fetchone()
                if not repo or not repo['is_active'] or ext_data.get('catalog_state') == 'retired':
                    raise ValueError('Cette extension ne dispose pas d’une offre active.')
            pkg = ext_data["pkg"]

            if enabled:
                # Si activée et recette non encore compilée, télécharger l'APK et compiler
                recipe_dict = None
                if ext_data.get("recipe_json"):
                    try:
                        recipe_dict = json.loads(ext_data["recipe_json"])
                    except VerificationRequired:
                        raise
                    except Exception:
                        pass

                installed_ver = ext_data.get("installed_version") or ext_data.get("available_version") or ext_data.get("version")
                avail_ver = ext_data.get("available_version") or ext_data.get("version")
                has_upd = int(newer(avail_ver, installed_ver, ext_data.get('available_code'), ext_data.get('installed_code')))

                if not recipe_dict:
                    compile_target = self._available_target(ext_data)
                    upgrading = bool(ext_data.get('installed_version') and compile_target['version'] != ext_data['installed_version'])
                    recipe_dict = await self._compile_extension_recipe(compile_target, force_download=upgrading)
                    installed_ver = avail_ver or installed_ver
                    has_upd = 0
                    cursor.execute(
                        """
                        UPDATE imported_extensions
                        SET recipe_json = ?, is_enabled = 1,
                            installed_version = ?, version = ?, apk_url = ?, base_url = ?, installed_code=available_code,
                            available_version = COALESCE(available_version, version),
                            has_update = ?, updated_at = CURRENT_TIMESTAMP
                        WHERE id = ?;
                        """,
                        (json.dumps(recipe_dict), installed_ver, installed_ver, compile_target['apk_url'],
                         recipe_dict['base_url'], has_upd, ext_id),
                    )
                else:
                    cursor.execute(
                        """
                        UPDATE imported_extensions
                        SET is_enabled = 1,
                            installed_version = COALESCE(installed_version, version),
                            available_version = COALESCE(available_version, version),
                            has_update = ?
                        WHERE id = ?;
                        """,
                        (has_upd, ext_id),
                    )

                recipe = SourceRecipe.from_dict(recipe_dict)
                if not recipe.base_url or not await asyncio.to_thread(is_safe_url, recipe.base_url):
                    raise ValueError("Aucune adresse de source valide : configurez sa recette avant activation.")
                source = AniyomiContainerSource(recipe)
                source._diagnostics_db_path = self.db_path
                source._diagnostics_recipe_revision = save_recipe_revision(conn, ext_id, source.recipe.to_dict(), 'activate')
                self._active_container_sources[pkg] = source
                logger.info("[extensions] Extension enabled: %s (%s)", ext_data["name"], pkg)
            else:
                cursor.execute("UPDATE imported_extensions SET is_enabled = 0 WHERE id = ?;", (ext_id,))
                self._active_container_sources.pop(pkg, None)
                logger.info("[extensions] Extension disabled: %s (%s)", ext_data["name"], pkg)

            conn.commit()

        return {
            "success": True,
            "id": ext_id,
            "pkg": pkg,
            "is_enabled": enabled,
            "name": ext_data["name"],
        }

    def list_repositories(self):
        with self._get_conn() as conn:
            return [dict(row) for row in conn.execute('SELECT * FROM extension_repos ORDER BY id')]

    def set_repository_enabled(self, repo_id, enabled):
        if type(enabled) is not bool:
            raise ValueError('enabled doit être un booléen.')
        with self._get_conn() as conn:
            if not conn.execute('SELECT id FROM extension_repos WHERE id=?', (repo_id,)).fetchone():
                raise ValueError('Dépôt introuvable.')
            conn.execute('UPDATE extension_repos SET is_active=? WHERE id=?', (int(enabled), repo_id))
        # Installed sources remain loaded when a repository stops publishing.
        return {'success': True, 'id': repo_id, 'is_active': enabled}

    async def refresh_repositories(self):
        results, errors = [], []
        for repo in self.list_repositories():
            if not repo['is_active']:
                continue
            try:
                results.append(await self.import_repository(repo['url']))
                with self._get_conn() as conn:
                    conn.execute('UPDATE extension_repos SET last_error=NULL, checked_at=CURRENT_TIMESTAMP WHERE id=?', (repo['id'],))
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                code = type(exc).__name__
                errors.append({'id': repo['id'], 'code': code})
                with self._get_conn() as conn:
                    conn.execute('UPDATE extension_repos SET last_error=?, checked_at=CURRENT_TIMESTAMP WHERE id=?', (code, repo['id']))
        return {'success': not errors, 'repositories': results, 'errors': errors}

    async def check_updates(self) -> Dict[str, Any]:
        result = await self.refresh_repositories()
        updates = [entry for entry in self.get_visible_extensions() if entry['has_update']]
        return {**result, 'count': len(updates), 'updates': updates,
                'message': f'{len(updates)} mise(s) à jour disponible(s).'}

    async def update_extension(self, ext_id: int) -> Dict[str, Any]:
        """Met à jour une extension à la demande de l'utilisateur en téléchargeant le nouvel APK et en recompilant sa recette."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM imported_extensions WHERE id = ?;", (ext_id,)).fetchone()
            if not row:
                raise ValueError("Extension introuvable.")
            ext_data = dict(row)
            repo = conn.execute('SELECT is_active FROM extension_repos WHERE id=?', (ext_data['repo_id'],)).fetchone()
            if not repo or not repo['is_active'] or ext_data.get('catalog_state') == 'retired':
                raise ValueError('Cette extension ne dispose pas d’une offre active.')

        compile_target = self._available_target(ext_data)
        target_version = compile_target['version']
        target_apk_url = compile_target['apk_url']
        # Updates must never silently install cached older bytes or a heuristic recipe.
        recipe_dict = await self._compile_extension_recipe(compile_target, force_download=True)
        recipe = SourceRecipe.from_dict(recipe_dict)
        if not recipe.base_url or not await asyncio.to_thread(is_safe_url, recipe.base_url):
            raise ValueError('URL de source invalide dans la mise à jour.')

        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if ext_data.get("recipe_json"):
                try:
                    save_recipe_revision(conn, ext_id, json.loads(ext_data["recipe_json"]), "legacy")
                except Exception:
                    pass
            conn.execute(
                """
                UPDATE imported_extensions
                SET version = ?,
                    installed_version = ?,
                    installed_code = available_code,
                    available_version = ?,
                    apk_url = ?,
                    available_apk_url = ?,
                    available_base_url = ?,
                    base_url = COALESCE(NULLIF(?, ''), base_url),
                    recipe_json = ?,
                    has_update = 0,
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (
                    target_version,
                    target_version,
                    target_version,
                    target_apk_url,
                    target_apk_url,
                    recipe.base_url,
                    recipe.base_url,
                    json.dumps(recipe_dict),
                    ext_id,
                ),
            )
            save_recipe_revision(conn, ext_id, recipe_dict, "update", force=True)
            conn.commit()

        self._load_enabled_sources()
        return {
            "success": True,
            "id": ext_id,
            "pkg": ext_data["pkg"],
            "name": ext_data["name"],
            "version": target_version,
            "installed_version": target_version,
            "available_version": target_version,
            "has_update": False,
            "message": f"{ext_data['name']} mis à jour vers v{target_version}.",
        }

    async def update_all_extensions(self) -> Dict[str, Any]:
        """Met à jour toutes les extensions du dépôt actif disposant d'une nouvelle version."""
        visible = self.get_visible_extensions()
        to_update = [ext for ext in visible if ext.get("has_update")]
        updated_ids: List[int] = []
        for ext in to_update:
            await self.update_extension(int(ext["id"]))
            updated_ids.append(int(ext["id"]))
        return {
            "success": True,
            "count": len(updated_ids),
            "updated_ids": updated_ids,
            "message": (
                f"{len(updated_ids)} extension(s) mise(s) à jour."
                if updated_ids
                else "Aucune mise à jour en attente."
            ),
        }

    async def recompile_extension(self, ext_id: int) -> Dict[str, Any]:
        """Recompile la recette DEX d'une extension depuis son APK (local ou distant)."""
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM imported_extensions WHERE id = ?;", (ext_id,)).fetchone()
            if not row:
                raise ValueError("Extension introuvable.")
            ext_data = dict(row)
            repo = conn.execute('SELECT is_active FROM extension_repos WHERE id=?', (ext_data['repo_id'],)).fetchone()
            if not repo or not repo['is_active'] or ext_data.get('catalog_state') == 'retired':
                raise ValueError('Cette extension ne dispose pas d’une offre active.')

        recipe_dict = await self._compile_extension_recipe(ext_data)
        recipe = SourceRecipe.from_dict(recipe_dict)
        with self._get_conn() as conn:
            conn.execute("BEGIN IMMEDIATE")
            if ext_data.get("recipe_json"):
                try:
                    save_recipe_revision(conn, ext_id, json.loads(ext_data["recipe_json"]), "legacy")
                except Exception:
                    pass
            conn.execute(
                """
                UPDATE imported_extensions
                SET recipe_json = ?,
                    base_url = COALESCE(NULLIF(?, ''), base_url),
                    installed_version = COALESCE(installed_version, version),
                    updated_at = CURRENT_TIMESTAMP
                WHERE id = ?;
                """,
                (json.dumps(recipe_dict), recipe.base_url, ext_id),
            )
            save_recipe_revision(conn, ext_id, recipe_dict, "recompile", force=True)
            conn.commit()

        self._load_enabled_sources()
        return {
            "success": True,
            "id": ext_id,
            "pkg": ext_data["pkg"],
            "name": ext_data["name"],
            "message": f"Recette recompilée pour {ext_data['name']}.",
        }

    @staticmethod
    def _available_target(ext_data):
        return {
            **ext_data,
            'version': ext_data.get('available_version') or ext_data.get('version'),
            'apk_url': (ext_data['available_apk_url'] if ext_data.get('available_apk_url') is not None else ext_data.get('apk_url')) or '',
            'base_url': ext_data.get('available_base_url') or ext_data.get('base_url') or '',
        }

    @staticmethod
    def _apk_cache_path(ext_data):
        identity = f"{ext_data.get('pkg') or ''}:{ext_data.get('version')}:{ext_data.get('apk_url') or ''}"
        return APKS_DIR / f'{hashlib.sha256(identity.encode()).hexdigest()}.apk'

    @staticmethod
    def _validate_apk(apk_bytes):
        try:
            with zipfile.ZipFile(io.BytesIO(apk_bytes)) as archive:
                names = [name for name in archive.namelist() if re.fullmatch(r'classes(?:\d+)?\.dex', name)]
                if not names:
                    raise ValueError('L’APK ne contient aucun fichier DEX.')
                for name in names:
                    with archive.open(name) as stream:
                        header = stream.read(112)
                    if len(header) < 112 or not header.startswith(b'dex\n'):
                        raise ValueError('Fichier DEX invalide dans l’APK.')
        except (zipfile.BadZipFile, OSError, EOFError, RuntimeError) as exc:
            raise ValueError('Le fichier reçu n’est pas un APK valide.') from exc

    async def _compile_extension_recipe(self, ext_data: Dict[str, Any], force_download: bool = False) -> Dict[str, Any]:
        """Télécharge l'APK et extrait la recette de scraping via AniyomiDexParser."""
        apk_url = ext_data.get("apk_url") or ""
        pkg = ext_data.get("pkg") or ""
        base_url = ext_data.get("base_url") or ""
        name = ext_data.get("name") or pkg
        lang = ext_data.get("lang") or "all"

        apk_bytes = b""
        local_apk = self._apk_cache_path(ext_data)

        if not force_download and local_apk.exists():
            try:
                cached = local_apk.read_bytes()
                self._validate_apk(cached)
                apk_bytes = cached
            except (OSError, ValueError):
                logger.warning('[extensions] Ignoring invalid APK cache for %s', pkg)
        if not apk_bytes and apk_url:
            logger.info("[extensions] Downloading APK for %s from %s", name, apk_url)
            try:
                async with source_http.async_client(timeout=25.0, verify=settings.SSL_VERIFY, follow_redirects=True, event_hooks={"request": [self._validate_request]}) as client:
                    resp = await client.get(apk_url, headers={"User-Agent": settings.DEFAULT_USER_AGENT})
                    if resp.status_code != 200:
                        raise ValueError(f'Téléchargement de l’APK impossible (HTTP {resp.status_code}).')
                    self._validate_apk(resp.content)
                    apk_bytes = resp.content
            except VerificationRequired:
                raise
            except Exception as e:
                logger.warning("[extensions] Failed downloading APK for %s: %s", name, e)
                if force_download:
                    raise ValueError('Mise à jour annulée : impossible de récupérer un APK valide.') from e

        if force_download and not apk_bytes:
            raise ValueError('Mise à jour annulée : aucune URL d’APK disponible.')

        if apk_bytes:
            recipe = AniyomiDexParser.parse_apk(apk_bytes, pkg_name=pkg, default_base_url=base_url, strict=force_download)
            # Publish a complete cache entry only after validation and parsing.
            import tempfile
            with tempfile.NamedTemporaryFile(dir=APKS_DIR, delete=False) as cached:
                scratch = Path(cached.name)
                cached.write(apk_bytes)
            try:
                scratch.replace(local_apk)
            finally:
                scratch.unlink(missing_ok=True)
        else:
            # Recette heuristique basée sur les métadonnées déclarées
            recipe = SourceRecipe(pkg=pkg, base_url=base_url)
            AniyomiDexParser._fill_heuristics(recipe)

        recipe.name = name
        recipe.lang = lang
        return recipe.to_dict()

    def _load_enabled_sources(self):
        """Charge au démarrage toutes les sources activées du magasin actif."""
        loaded = {}
        failures = []
        with self._get_conn() as conn:
            conn.execute('BEGIN IMMEDIATE')
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM imported_extensions WHERE is_enabled = 1 ORDER BY id;")
            rows = cursor.fetchall()
            for r in rows:
                ext = dict(r)
                if not ext.get("recipe_json"):
                    recipe = SourceRecipe(pkg=ext["pkg"], name=ext["name"], base_url=ext["base_url"] or "", lang=ext["lang"])
                    AniyomiDexParser._fill_heuristics(recipe)
                    cached_apk = self._apk_cache_path({**ext, 'version': ext.get('installed_version') or ext.get('version')})
                    if cached_apk.exists():
                        try:
                            apk_bytes = cached_apk.read_bytes()
                            self._validate_apk(apk_bytes)
                            recipe = AniyomiDexParser.parse_apk(apk_bytes, pkg_name=ext['pkg'], default_base_url=ext['base_url'] or '')
                            recipe.name, recipe.lang = ext['name'], ext['lang']
                        except (OSError, ValueError):
                            logger.warning('[extensions] Ignoring invalid APK cache for %s', ext['pkg'])
                    if recipe.base_url:
                        loaded[ext["pkg"]] = AniyomiContainerSource(recipe)
                        effective=loaded[ext['pkg']].recipe.to_dict()
                        conn.execute('UPDATE imported_extensions SET recipe_json=? WHERE id=?',(json.dumps(effective),ext['id']))
                        loaded[ext['pkg']]._diagnostics_recipe_revision=save_recipe_revision(conn,ext['id'],effective,'load')
                        conn.execute("DELETE FROM extension_health WHERE ext_id=? AND operation='load'",(ext['id'],))
                if ext.get("recipe_json"):
                    try:
                        recipe_data = json.loads(ext["recipe_json"])
                        recipe = SourceRecipe.from_dict(recipe_data)
                        from animelab.services.recipe_plans import repair_legacy_recipe
                        if repair_legacy_recipe(recipe):
                            save_recipe_revision(conn, ext['id'], recipe_data, 'before_identity_repair')
                            recipe_data = recipe.to_dict()
                            conn.execute('UPDATE imported_extensions SET base_url=? WHERE id=?', (recipe.base_url, ext['id']))
                        AniyomiDexParser._fill_heuristics(recipe)
                        # Keep user-defined paths/selectors; fill only missing values.
                        recipe = SourceRecipe.from_dict({**recipe.to_dict(), **{key: value for key, value in recipe_data.items() if value not in ("", None, [])}})
                        updated_dict = recipe.to_dict()
                        if updated_dict != recipe_data:
                            save_recipe_revision(conn,ext['id'],recipe_data,'legacy')
                            cursor.execute("UPDATE imported_extensions SET recipe_json = ? WHERE id = ?;", (json.dumps(updated_dict), ext["id"]))
                        loaded[ext["pkg"]] = AniyomiContainerSource(recipe)
                        effective=loaded[ext['pkg']].recipe.to_dict()
                        cursor.execute('UPDATE imported_extensions SET recipe_json=? WHERE id=?',(json.dumps(effective),ext['id']))
                        loaded[ext['pkg']]._diagnostics_recipe_revision=save_recipe_revision(conn,ext['id'],effective,'load')
                        conn.execute("DELETE FROM extension_health WHERE ext_id=? AND operation='load'",(ext['id'],))
                    except Exception as e:
                        failures.append((ext, e))
                        logger.warning("[extensions] Error loading source %s: %s", ext["name"], type(e).__name__)

        for ext,error in failures:
            extension_observability.record(ext['pkg'],'load',error=error,db_path=self.db_path)
        for source in loaded.values(): source._diagnostics_db_path = self.db_path
        self._active_container_sources = loaded
        logger.info("[extensions] %d Aniyomi source(s) enabled in memory", len(self._active_container_sources))

    # -------------------------------------------------------------------------
    # Accesseurs pour le coeur d'Animan
    # -------------------------------------------------------------------------

    @staticmethod
    async def _validate_request(request):
        if not await asyncio.to_thread(is_safe_url, str(request.url)):
            raise ValueError("URL du dépôt ou de l’APK non autorisée.")

    async def configure_extension(self, ext_id: int, data: Dict[str, Any], *, revision_reason='configure', force_revision=False):
        unknown = set(data) - set(SourceRecipe.__dataclass_fields__)
        if unknown:
            raise ValueError("Champs de recette inconnus : " + ", ".join(sorted(unknown)))
        with self._get_conn() as conn:
            row = conn.execute("SELECT * FROM imported_extensions WHERE id = ?", (ext_id,)).fetchone()
            if not row:
                raise ValueError("Extension introuvable dans le dépôt actif.")
            existing = json.loads(row["recipe_json"] or "{}")
            previous = dict(existing)
            existing.update(data)
            existing.update(pkg=row["pkg"], name=row["name"], lang=row["lang"])
            recipe = SourceRecipe.from_dict(existing)
            if not isinstance(recipe.base_url, str) or not await asyncio.to_thread(is_safe_url, recipe.base_url):
                raise ValueError("URL de source invalide.")
            from bs4 import BeautifulSoup
            from animelab.services.recipe_plans import source_key
            key = source_key(recipe.pkg, recipe.base_url)
            api_marker = f'api:{key}' if key in ('franime', 'hanime') else None
            for key, value in recipe.to_dict().items():
                if key.endswith("selector"):
                    if not isinstance(value, str):
                        raise ValueError("Les sélecteurs doivent être du texte.")
                    if value:
                        if value == api_marker and key in ('popular_selector', 'latest_selector', 'search_selector', 'episode_list_selector'):
                            continue
                        try:
                            BeautifulSoup("", "html.parser").select(value)
                        except VerificationRequired:
                            raise
                        except Exception as exc:
                            raise ValueError(f"Sélecteur invalide : {key}") from exc
            try:
                re.compile(recipe.video_iframe_regex)
            except (TypeError, re.error) as exc:
                raise ValueError("Expression de lecteur invalide.") from exc
            conn.execute('BEGIN IMMEDIATE')
            if previous: save_recipe_revision(conn,ext_id,previous,'legacy')
            conn.execute("UPDATE imported_extensions SET recipe_json = ?, base_url = ? WHERE id = ?",
                         (json.dumps(recipe.to_dict()), recipe.base_url, ext_id))
            save_recipe_revision(conn,ext_id,recipe.to_dict(),revision_reason,force=force_revision)
        self._load_enabled_sources()
        return {"success": True, "id": ext_id}

    async def diagnose_extension(self, ext_id: int):
        ext = next((ext for ext in self.get_visible_extensions() if ext["id"] == ext_id), None)
        if not ext:
            raise ValueError("Extension introuvable dans le dépôt actif.")
        recipe = SourceRecipe.from_dict(json.loads(ext["recipe_json"])) if ext.get("recipe_json") else SourceRecipe(
            pkg=ext["pkg"], name=ext["name"], base_url=ext["base_url"] or "", lang=ext["lang"])
        stored = recipe.to_dict()
        AniyomiDexParser._fill_heuristics(recipe)
        if ext.get("recipe_json"):
            recipe = SourceRecipe.from_dict({**recipe.to_dict(), **{k: v for k, v in stored.items() if v not in ("", None, [])}})
        source = AniyomiContainerSource(recipe)
        from animelab.services.source_registry import source_registry
        from animelab.services.extension_observability import classify
        source._diagnostics_db_path=self.db_path
        source._diagnostics_recipe_revision=ext['recipe_revision']
        provider=source_registry.describe(ext['pkg'],source)
        try:
            results = await asyncio.wait_for(provider.get_latest_releases(), timeout=20)
        except VerificationRequired:
            raise
        except Exception as exc:
            status,code=classify(exc)
            from animelab.api_errors import APIProblem
            if isinstance(exc,(TimeoutError,APIProblem)):
                extension_observability.record(ext['pkg'],'latest',error=exc,db_path=self.db_path,base_url=source.base_url,recipe_revision=ext['recipe_revision'])
            return {'success':False,'count':0,'status':status,'code':code,'message':HEALTH_MESSAGES[status]}
        return {'success':bool(results),'count':len(results),'status':'healthy' if results else 'empty',
                'message':HEALTH_MESSAGES['healthy' if results else 'empty']}

    def recipe_history(self,ext_id):
        if not any(ext['id']==ext_id for ext in self.get_visible_extensions()):
            raise ValueError('Extension introuvable dans le dépôt actif.')
        with self._get_conn() as conn:
            return {'revisions':extension_observability.history(conn,ext_id)}

    async def restore_recipe(self,ext_id,revision):
        self.recipe_history(ext_id)
        with self._get_conn() as conn:
            row=conn.execute('SELECT recipe_json FROM extension_recipe_versions WHERE ext_id=? AND revision=?',(ext_id,revision)).fetchone()
        if not row: raise ValueError('Révision de recette introuvable.')
        # Restore creates a new revision; the historical snapshot is immutable.
        return await self.configure_extension(ext_id,json.loads(row['recipe_json']),revision_reason='restore',force_revision=True)

    def get_enabled_container_sources(self) -> List[AniyomiContainerSource]:
        """Retourne la liste des conteneurs de sources actuellement activés."""
        return list(self._active_container_sources.values())

    def get_container_source_by_id(self, source_id: str) -> Optional[AniyomiContainerSource]:
        """Recherche une source active par identifiant ou nom de package."""
        if not source_id:
            return None
        sid = source_id.lower().strip()
        for k, src in self._active_container_sources.items():
            if k.lower() == sid or src.name.lower() == sid or src.pkg.lower() == sid:
                return src
        return None

    def get_allowed_domains(self) -> Set[str]:
        """Retourne les domaines des sources activées pour la whitelist SSRF."""
        domains = set()
        for src in self._active_container_sources.values():
            if src.base_url:
                try:
                    host = urlparse(src.base_url).hostname
                    if host:
                        domains.add(host.lower())
                except Exception:
                    pass
        return domains


extension_service = ExtensionService()
