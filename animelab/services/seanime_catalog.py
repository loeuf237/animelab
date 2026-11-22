"""Bounded catalog and manifest readers for Seanime marketplaces, repositories, and manifests."""
from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
import hashlib
import json
import re
from typing import Any, Awaitable, Callable
from urllib.parse import urljoin, urlsplit, urlunsplit

from .extension_versions import newer

SEANIME_TYPES = (
    'onlinestream-provider',
    'anime-torrent-provider',
    'manga-provider',
    'custom-source',
    'plugin',
)
EXECUTABLE_SEANIME_TYPES = ('onlinestream-provider',)
SEANIME_LANGUAGES = ('javascript', 'typescript', 'go')

MAX_SEANIME_INDEX_BYTES = 8 * 1024 * 1024
MAX_SEANIME_PAYLOAD_BYTES = 2 * 1024 * 1024
MAX_SEANIME_ENTRIES = 5_000
MAX_REPO_URLS = 400

_ID_RE = re.compile(r'^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$')
_SEMVER_RE = re.compile(r'^v?(\d+)(?:\.(\d+))?(?:\.(\d+))?(?:[-+].*)?$', re.IGNORECASE)

FetchBytesFn = Callable[[str, int], Awaitable[bytes]]


def canonical_seanime_url(value: Any) -> str:
    """Validate and canonicalize an HTTP(S) URL for a Seanime marketplace, repository, or manifest."""
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('URL Seanime invalide.')
    cleaned = value.strip()
    if not cleaned or any(ord(ch) < 32 for ch in cleaned):
        raise ValueError('URL Seanime invalide.')
    parsed = urlsplit(cleaned)
    if (
        parsed.scheme.lower() not in ('https', 'http')
        or not parsed.hostname
        or parsed.username
        or parsed.password
        or parsed.fragment
    ):
        raise ValueError('URL Seanime invalide.')
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), parsed.path or '/', parsed.query, ''))


def _clean_optional_http_url(value: Any, *, base_url: str = '') -> str:
    if not isinstance(value, str):
        return ''
    cleaned = value.strip()
    if not cleaned or len(cleaned) > 4096 or any(ord(ch) < 32 for ch in cleaned):
        return ''
    if cleaned.startswith(('http://', 'https://')):
        return cleaned
    if base_url and cleaned.startswith('/'):
        return urljoin(base_url, cleaned)
    if base_url and '://' not in cleaned and not cleaned.startswith(('data:', 'javascript:', 'file:')):
        return urljoin(base_url, cleaned)
    return ''


def validate_seanime_id(value: Any) -> str:
    """Validate a Seanime extension identifier."""
    if not isinstance(value, str):
        raise ValueError("Identifiant d'extension Seanime invalide.")
    cleaned = value.strip()
    if '..' in cleaned or not _ID_RE.fullmatch(cleaned):
        raise ValueError(f"Identifiant d'extension Seanime invalide : {cleaned!r}")
    return cleaned


def normalize_seanime_lang(lang: Any) -> str:
    """Normalize language codes matching Seanime's GetExtensionLang semantics."""
    if not isinstance(lang, str):
        return 'en'
    cleaned = lang.strip().lower()
    if not cleaned:
        return 'en'
    if cleaned == 'all':
        return 'multi'
    return cleaned


def _str_field(value: Any, *, max_len: int = 16384, default: str = '') -> str:
    if not isinstance(value, str):
        return default
    return value.strip()[:max_len]


def normalize_user_config(raw: Any) -> dict[str, Any]:
    """Validate and normalize a Seanime extension userConfig schema."""
    if not isinstance(raw, dict):
        return {}
    raw_fields = raw.get('fields')
    if not isinstance(raw_fields, list):
        raw_fields = []
    fields: list[dict[str, Any]] = []
    for item in raw_fields[:100]:
        if not isinstance(item, dict):
            continue
        ftype = str(item.get('type') or 'text').strip().lower()
        if ftype not in ('text', 'switch', 'select'):
            continue
        name = _str_field(item.get('name'), max_len=128)
        if not name:
            continue
        label = _str_field(item.get('label'), max_len=256) or name
        default_val = item.get('default')
        if isinstance(default_val, bool):
            default_str = 'true' if default_val else 'false'
        elif default_val is None:
            default_str = ''
        else:
            default_str = str(default_val)[:4096]
        field_obj: dict[str, Any] = {
            'type': ftype,
            'name': name,
            'label': label,
            'default': default_str,
        }
        if ftype == 'select' and isinstance(item.get('options'), list):
            opts: list[dict[str, str]] = []
            for opt in item['options'][:200]:
                if not isinstance(opt, dict):
                    continue
                val = _str_field(opt.get('value'), max_len=1024)
                lbl = _str_field(opt.get('label'), max_len=1024) or val
                if val or lbl:
                    opts.append({'value': val, 'label': lbl})
            field_obj['options'] = opts
        fields.append(field_obj)
    try:
        version = int(raw.get('version') or 1)
    except (TypeError, ValueError):
        version = 1
    return {
        'version': version,
        'requiresConfig': bool(raw.get('requiresConfig', False)),
        'fields': fields,
    }


def _extract_marketplace_meta(raw: dict[str, Any]) -> dict[str, Any]:
    keys = (
        'workingTag',
        'brokenTag',
        'deprecatedTag',
        'stars',
        'flags',
        'permalink',
        'scannedOnVersion',
        'lastWorkingVersion',
        'updatedAt',
        'addedAt',
        'tags',
    )
    return {k: raw[k] for k in keys if k in raw and raw[k] is not None}


def normalize_manifest(raw: Any, *, fallback_manifest_uri: str = '') -> dict[str, Any]:
    """Validate and normalize a Seanime marketplace entry or manifest JSON object."""
    if not isinstance(raw, dict):
        raise ValueError('Manifeste Seanime invalide.')
    if raw.get('isDevelopment') is True:
        raise ValueError("Les extensions Seanime en mode développement ne sont pas autorisées.")
    ext_id = validate_seanime_id(raw.get('id'))
    ext_type = _str_field(raw.get('type'), max_len=64).lower()
    if ext_type not in SEANIME_TYPES:
        raise ValueError(f"Type d'extension Seanime non pris en charge : {ext_type or 'inconnu'}")
    language = _str_field(raw.get('language'), max_len=32).lower() or 'javascript'
    if language not in SEANIME_LANGUAGES:
        raise ValueError(f"Langage d'extension Seanime non pris en charge : {language}")
    manifest_uri = _clean_optional_http_url(raw.get('manifestURI')) or fallback_manifest_uri
    base_for_rel = manifest_uri or fallback_manifest_uri
    payload_uri = _clean_optional_http_url(raw.get('payloadURI'), base_url=base_for_rel)
    raw_payload = raw.get('payload')
    payload: str = raw_payload if isinstance(raw_payload, str) else ''
    if len(payload.encode('utf-8', errors='ignore')) > MAX_SEANIME_PAYLOAD_BYTES:
        raise ValueError("Code source d'extension Seanime trop volumineux.")
    return {
        'ext_id': ext_id,
        'name': _str_field(raw.get('name'), max_len=256) or ext_id,
        'version': _str_field(raw.get('version'), max_len=64) or '1.0.0',
        'ext_type': ext_type,
        'language': language,
        'lang': normalize_seanime_lang(raw.get('lang')),
        'author': _str_field(raw.get('author'), max_len=256),
        'description': _str_field(raw.get('description'), max_len=4096),
        'notes': _str_field(raw.get('notes'), max_len=8192),
        'icon_url': _clean_optional_http_url(raw.get('icon'), base_url=base_for_rel),
        'website': _clean_optional_http_url(raw.get('website'), base_url=base_for_rel),
        'readme': _clean_optional_http_url(raw.get('readme'), base_url=base_for_rel),
        'manifest_uri': manifest_uri,
        'payload_uri': payload_uri,
        'payload': payload,
        'user_config': normalize_user_config(raw.get('userConfig')),
        'marketplace_meta': _extract_marketplace_meta(raw),
    }


def compare_seanime_versions(available: str | None, installed: str | None) -> bool:
    """Compare remote vs installed Seanime semver strings cleanly."""
    if not available or not installed:
        return False
    avail_clean = str(available).strip()
    inst_clean = str(installed).strip()
    if not avail_clean or avail_clean == inst_clean:
        return False
    if newer(avail_clean.lstrip('vV'), inst_clean.lstrip('vV')):
        return True
    m_avail = _SEMVER_RE.fullmatch(avail_clean)
    m_inst = _SEMVER_RE.fullmatch(inst_clean)
    if m_avail and m_inst:
        t_avail = tuple(int(g or 0) for g in m_avail.groups())
        t_inst = tuple(int(g or 0) for g in m_inst.groups())
        if t_avail != t_inst:
            return t_avail > t_inst
    return False


def derive_repo_name(clean_url: str, fallback: str = 'Marketplace Seanime') -> str:
    """Derive a human-friendly repository display name from its URL."""
    parsed = urlsplit(clean_url)
    parts = [p for p in parsed.path.split('/') if p]
    if parsed.hostname == 'raw.githubusercontent.com' and len(parts) >= 2:
        return f'{parts[0]}/{parts[1]}'
    if len(parts) >= 2 and parsed.hostname and 'github' in parsed.hostname:
        return f'{parts[0]}/{parts[1]}'
    if parsed.hostname:
        return parsed.hostname
    return fallback


@dataclass
class SeanimeCatalog:
    url: str
    name: str
    kind: str  # 'marketplace' | 'repository' | 'direct'
    entries: list[dict[str, Any]] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


async def read_seanime_catalog(url: str, fetch_bytes: FetchBytesFn) -> SeanimeCatalog:
    """Load a Seanime Marketplace array, `{urls:[...]}` repository, or direct manifest JSON."""
    clean_url = canonical_seanime_url(url)
    raw_bytes = await fetch_bytes(clean_url, MAX_SEANIME_INDEX_BYTES)
    try:
        decoded = json.loads(raw_bytes.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Index ou manifeste Seanime JSON invalide.') from exc

    if isinstance(decoded, list):
        if len(decoded) > MAX_SEANIME_ENTRIES:
            raise ValueError('Catalogue Seanime trop volumineux.')
        entries: list[dict[str, Any]] = []
        seen: set[str] = set()
        warnings: list[str] = []
        for item in decoded:
            if not isinstance(item, dict) or not item.get('id') or not item.get('manifestURI'):
                continue
            try:
                norm = normalize_manifest(item)
            except ValueError as exc:
                warnings.append(f"{item.get('id')}: {exc}")
                continue
            if norm['ext_id'] in seen:
                continue
            seen.add(norm['ext_id'])
            entries.append(norm)
        if decoded and not entries:
            raise ValueError('Le catalogue Seanime ne contient aucune extension valide.')
        return SeanimeCatalog(
            url=clean_url,
            name=derive_repo_name(clean_url),
            kind='marketplace',
            entries=entries,
            warnings=warnings,
        )

    if isinstance(decoded, dict) and isinstance(decoded.get('urls'), list):
        raw_urls = [u for u in decoded['urls'][:MAX_REPO_URLS] if isinstance(u, str) and u.strip()]
        if not raw_urls:
            raise ValueError('Le dépôt Seanime ne contient aucune URL de manifeste.')
        sem = asyncio.Semaphore(6)
        warnings = []

        async def _load_one(manifest_url: str) -> dict[str, Any] | None:
            async with sem:
                try:
                    m_url = canonical_seanime_url(urljoin(clean_url, manifest_url.strip()))
                    m_bytes = await fetch_bytes(m_url, MAX_SEANIME_INDEX_BYTES)
                    m_json = json.loads(m_bytes.decode('utf-8-sig'))
                    return normalize_manifest(m_json, fallback_manifest_uri=m_url)
                except Exception as exc:
                    warnings.append(f'{manifest_url}: {exc}')
                    return None

        loaded = await asyncio.gather(*(_load_one(u) for u in raw_urls))
        entries = []
        seen = set()
        for entry in loaded:
            if entry is None or entry['ext_id'] in seen:
                continue
            if entry['ext_type'] == 'plugin':
                # Matches Seanime's repository importer rule while still informing user via warning.
                warnings.append(f"{entry['ext_id']}: plugin ignoré dans un dépôt multi-URL.")
                continue
            seen.add(entry['ext_id'])
            entries.append(entry)
        if not entries:
            raise ValueError("Aucune extension Seanime valide n'a pu être importée depuis ce dépôt.")
        return SeanimeCatalog(
            url=clean_url,
            name=_str_field(decoded.get('name'), max_len=256) or derive_repo_name(clean_url, 'Dépôt Seanime'),
            kind='repository',
            entries=entries,
            warnings=warnings,
        )

    if isinstance(decoded, dict) and decoded.get('id') and decoded.get('type'):
        norm = normalize_manifest(decoded, fallback_manifest_uri=clean_url)
        return SeanimeCatalog(
            url=clean_url,
            name=norm['name'],
            kind='direct',
            entries=[norm],
            warnings=[],
        )

    raise ValueError('Format de catalogue ou manifeste Seanime non reconnu.')


async def fetch_full_manifest(
    manifest_uri: str,
    fetch_bytes: FetchBytesFn,
    *,
    fallback_payload_uri: str = '',
) -> dict[str, Any]:
    """Fetch complete manifest + remote payloadURI (if payload is empty) and compute SHA-256."""
    clean_manifest_uri = canonical_seanime_url(manifest_uri)
    raw_bytes = await fetch_bytes(clean_manifest_uri, MAX_SEANIME_INDEX_BYTES)
    try:
        decoded = json.loads(raw_bytes.decode('utf-8-sig'))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ValueError('Manifeste Seanime JSON invalide.') from exc

    norm = normalize_manifest(decoded, fallback_manifest_uri=clean_manifest_uri)
    payload = norm['payload']
    payload_uri = norm['payload_uri'] or fallback_payload_uri
    if not payload and payload_uri:
        clean_payload_uri = canonical_seanime_url(payload_uri)
        p_bytes = await fetch_bytes(clean_payload_uri, MAX_SEANIME_PAYLOAD_BYTES)
        if len(p_bytes) > MAX_SEANIME_PAYLOAD_BYTES:
            raise ValueError('Le script Seanime dépasse la taille maximale autorisée (2 Mo).')
        try:
            payload = p_bytes.decode('utf-8-sig')
        except UnicodeDecodeError as exc:
            raise ValueError('Le script Seanime doit être encodé en UTF-8.') from exc
    if not payload or not payload.strip():
        raise ValueError("L'extension Seanime ne contient aucun code exécutable (payload vide).")
    norm['payload'] = payload
    norm['payload_uri'] = payload_uri
    norm['payload_sha256'] = hashlib.sha256(payload.encode('utf-8')).hexdigest()
    return norm
