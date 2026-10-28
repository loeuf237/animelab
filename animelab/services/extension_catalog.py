"""Bounded readers for legacy and extensions-lib store JSON/Protobuf indexes."""
from dataclasses import dataclass
import json
import re
from urllib.parse import urljoin, urlsplit, urlunsplit
import zlib

from .extension_versions import version_code

MAX_INDEX_BYTES = 8 * 1024 * 1024
MAX_ENTRIES = 20_000
MAX_REFERENCES = 6


def canonical_url(value):
    if not isinstance(value, str) or len(value) > 4096:
        raise ValueError('URL de dépôt invalide.')
    parsed = urlsplit(value.strip())
    if parsed.scheme not in ('https', 'http') or not parsed.hostname or parsed.username or parsed.password or parsed.fragment:
        raise ValueError('URL de dépôt invalide.')
    path = parsed.path
    if not path or path.endswith('/') or not path.rsplit('/', 1)[-1].count('.'):
        path = path.rstrip('/') + '/index.min.json'
    return urlunsplit((parsed.scheme.lower(), parsed.netloc.lower(), path, parsed.query, ''))


def _varint(data, offset):
    value = 0
    for shift in range(0, 70, 7):
        if offset >= len(data):
            raise ValueError('Protobuf tronqué.')
        byte = data[offset]
        offset += 1
        value |= (byte & 127) << shift
        if byte < 128:
            if value > 2**64 - 1:
                raise ValueError('Entier Protobuf hors limites.')
            return value, offset
    raise ValueError('Entier Protobuf invalide.')


SCHEMA = {
    'Index': {1: ('name', 'str'), 2: ('badgeLabel', 'str'), 3: ('signingKey', 'str'),
              4: ('contact', 'Contact'), 101: ('extensionList', 'List'), 102: ('extensionListUrl', 'str')},
    'Contact': {1: ('website', 'str'), 2: ('discord', 'str')},
    'List': {1: ('extensions', 'Extension')},
    'Extension': {1: ('name', 'str'), 2: ('packageName', 'str'), 3: ('resources', 'Resources'),
                  4: ('extensionLib', 'str'), 5: ('versionCode', 'int'), 6: ('versionName', 'str'),
                  7: ('contentWarning', 'int'), 8: ('isTorrent', 'int'), 9: ('sources', 'Source')},
    'Resources': {1: ('apkUrl', 'str'), 2: ('iconUrl', 'str')},
    'Source': {1: ('id', 'int'), 2: ('name', 'str'), 3: ('language', 'str'),
               4: ('homeUrl', 'str'), 5: ('mirrorUrls', 'str'), 6: ('message', 'str')},
}
REPEATED = {'extensions', 'sources', 'mirrorUrls'}


def _protobuf(data, kind, depth=0):
    if depth > 6:
        raise ValueError('Protobuf trop imbriqué.')
    result, offset, count = {}, 0, 0
    while offset < len(data):
        count += 1
        if count > MAX_ENTRIES * 16:
            raise ValueError('Index trop volumineux.')
        tag, offset = _varint(data, offset)
        field, wire = tag >> 3, tag & 7
        if not field:
            raise ValueError('Champ Protobuf invalide.')
        if wire == 0:
            value, offset = _varint(data, offset)
        elif wire == 2:
            size, offset = _varint(data, offset)
            if size > len(data) - offset:
                raise ValueError('Champ Protobuf tronqué.')
            value, offset = data[offset:offset+size], offset+size
        elif wire in (1, 5):
            offset += 8 if wire == 1 else 4
            if offset > len(data):
                raise ValueError('Champ Protobuf tronqué.')
            continue
        else:
            raise ValueError('Type Protobuf non pris en charge.')
        spec = SCHEMA[kind].get(field)
        if not spec:
            continue
        key, target = spec
        if (target == 'int') != (wire == 0):
            raise ValueError('Type de champ Protobuf invalide.')
        if target != 'int':
            value = value.decode('utf-8') if target == 'str' else _protobuf(value, target, depth+1)
        if key in REPEATED:
            result.setdefault(key, []).append(value)
            if len(result[key]) > MAX_ENTRIES:
                raise ValueError('Trop d’entrées dans l’index.')
        else:
            result[key] = value
    return result


def decode_index(data, kind='Index'):
    if len(data) > MAX_INDEX_BYTES:
        raise ValueError('Index trop volumineux.')
    if data.startswith(b'\x1f\x8b'):
        decoder = zlib.decompressobj(16 + zlib.MAX_WBITS)
        try:
            data = decoder.decompress(data, MAX_INDEX_BYTES+1)
        except zlib.error as exc:
            raise ValueError('Index gzip invalide.') from exc
        if len(data) > MAX_INDEX_BYTES or not decoder.eof or decoder.unused_data:
            raise ValueError('Index gzip tronqué ou trop volumineux.')
    clean = data.removeprefix(b'\xef\xbb\xbf').lstrip()
    if not clean:
        raise ValueError('Index vide.')
    if clean[:1] in (b'[', b'{'):
        try:
            return json.loads(clean)
        except (ValueError, RecursionError) as exc:
            raise ValueError('Index JSON invalide.') from exc
    return _protobuf(data, kind)


@dataclass
class Catalog:
    url: str
    metadata: dict
    entries: list[dict]


def normalize_entries(entries, base):
    if not isinstance(entries, list) or len(entries) > MAX_ENTRIES:
        raise ValueError('Liste d’extensions invalide.')
    normalized, seen = [], set()
    for entry in entries:
        if not isinstance(entry, dict):
            raise ValueError('Entrée d’extension invalide.')
        pkg = entry.get('packageName', entry.get('pkg'))
        if not isinstance(pkg, str) or len(pkg) > 255 or not re.fullmatch(r'[A-Za-z0-9_]+(?:\.[A-Za-z0-9_]+)+', pkg):
            raise ValueError('Package d’extension invalide.')
        if pkg in seen:
            raise ValueError('Package dupliqué dans le même index.')
        seen.add(pkg)
        resources = entry.get('resources') or {}
        apk = resources.get('apkUrl') or entry.get('apk') or ''
        icon = resources.get('iconUrl') or entry.get('icon') or ''
        sources = entry.get('sources') or []
        if not isinstance(sources, list) or len(sources) > 1000:
            raise ValueError('Liste de sources invalide.')
        clean_sources = []
        for source in sources:
            if not isinstance(source, dict):
                raise ValueError('Source invalide.')
            sid = source.get('id')
            if sid is not None and version_code(sid) is None:
                raise ValueError('Identifiant de source invalide.')
            clean_sources.append({**source, 'id': str(sid) if sid is not None else None,
                                  'lang': str(source.get('language', source.get('lang', 'all'))),
                                  'baseUrl': str(source.get('homeUrl', source.get('baseUrl', '')))})
        languages = {s['lang'] for s in clean_sources}
        warning = entry.get('contentWarning', 0)
        nsfw = warning in (2, 3, 'MIXED', 'NSFW', 'CONTENT_WARNING_MIXED', 'CONTENT_WARNING_NSFW')
        normalized.append({**entry, 'pkg': pkg, 'version': str(entry.get('versionName', entry.get('version', entry.get('code', '1.0')))),
                           'code': version_code(entry.get('versionCode', entry.get('code'))),
                           'name': str(entry.get('name') or pkg),
                           'lang': entry.get('lang') or (next(iter(languages)) if len(languages) == 1 else 'all'),
                           'apk': urljoin(base + '/apk/', apk) if apk else '',
                           'icon': urljoin(base + '/icon/', icon) if icon else base + '/icon/' + pkg + '.png',
                           'sources': clean_sources, 'nsfw': int(nsfw or entry.get('nsfw') == 1)})
    return normalized


async def read_catalog(url, fetch):
    original, current, visited = canonical_url(url), canonical_url(url), set()
    metadata = {}
    for _ in range(MAX_REFERENCES):
        if current in visited:
            raise ValueError('Boucle de migration de dépôt.')
        visited.add(current)
        data = decode_index(await fetch(current))
        base = current.rsplit('/', 1)[0]
        if isinstance(data, list):
            # Legacy indexes without metadata remain readable but untrusted.
            try:
                meta = decode_index(await fetch(base + '/repo.json'))
                if isinstance(meta, dict) and isinstance(meta.get('meta'), dict):
                    metadata = meta['meta']
                    if meta.get('index_v2'):
                        current = canonical_url(urljoin(current, meta['index_v2']))
                        continue
            except (ValueError, OSError):
                pass
            return Catalog(original, metadata, normalize_entries(data, base))
        if not isinstance(data, dict):
            raise ValueError('Format de store invalide.')
        if isinstance(data.get('meta'), dict):
            metadata = data['meta']
            if data.get('index_v2'):
                current = canonical_url(urljoin(current, data['index_v2']))
                continue
            entries = decode_index(await fetch(base + '/index.min.json'))
            return Catalog(original, metadata, normalize_entries(entries, base))
        if not isinstance(data.get('name'), str):
            raise ValueError('Store sans identité.')
        metadata = {**data, 'signingKeyFingerprint': data.get('signingKey')}
        embedded, external = data.get('extensionList'), data.get('extensionListUrl')
        if embedded is not None and external:
            raise ValueError('Store ambigu : deux listes d’extensions.')
        if external:
            external = canonical_url(urljoin(current, external))
            if external in visited:
                raise ValueError('Liste externe circulaire.')
            embedded = decode_index(await fetch(external), 'List')
        if not isinstance(embedded, dict):
            raise ValueError('Store sans liste d’extensions.')
        return Catalog(original, metadata, normalize_entries(embedded.get('extensions', []), base))
    raise ValueError('Trop de migrations de dépôt.')
