"""Private, bounded native callback data keyed by source and public library URL.

The original APK URL can be relative, absolute or contain a fragment. Rebuilding
it from the displayed URL loses information, particularly after process restart.
These records are not executable trust and are excluded from metadata backups.
"""
import json

from animelab.api_errors import APIProblem
from animelab.database import sqlite_connection

MAX_BYTES = 64 * 1024 * 1024
MAX_ROWS = 250_000
MAX_ITEM_BYTES = 700_000  # Match the native result's UTF-8 byte budget.
MAX_ITEM_UNITS = 240_000  # Leave room inside the 256K UTF-16 request envelope.


class NativeReferences:
    def __init__(self, db_path, source_key, *, max_bytes=MAX_BYTES, max_rows=MAX_ROWS):
        self.db_path, self.source_key = db_path, source_key
        self.max_bytes, self.max_rows = max_bytes, max_rows

    def remember(self, kind, public_url, metadata):
        self.remember_many([(kind, public_url, metadata)])

    def remember_many(self, records):
        prepared = []
        for kind, public_url, metadata in records:
            if kind not in ('anime', 'episode') or not isinstance(public_url,str) or not isinstance(metadata,dict):
                raise APIProblem('extension_reference_invalid',status=422,category='validation')
            native_url = metadata.get('url')
            if not isinstance(native_url,str) or not public_url or len(native_url)>8192 or len(public_url)>16384:
                raise APIProblem('extension_reference_invalid',status=422,category='validation')
            encoded = json.dumps(metadata,ensure_ascii=False,allow_nan=False)
            size = len(encoded.encode('utf-8'))
            if size>MAX_ITEM_BYTES or len(encoded.encode('utf-16-le'))//2>MAX_ITEM_UNITS:
                raise APIProblem('extension_reference_too_large',status=413,category='validation')
            prepared.append((kind,public_url,native_url,encoded,size))
        if not prepared:
            return
        with sqlite_connection(self.db_path) as conn:
            conn.execute('BEGIN IMMEDIATE')
            budget = conn.execute('SELECT used_bytes,used_rows FROM extension_reference_budget WHERE id=1').fetchone()
            used_bytes, used_rows = budget['used_bytes'], budget['used_rows']
            for kind, public_url, native_url, encoded, size in prepared:
                old = conn.execute('SELECT metadata_size FROM extension_native_references WHERE source_key=? AND kind=? AND public_url=?',
                                   (self.source_key,kind,public_url)).fetchone()
                used_bytes += size-(old['metadata_size'] if old else 0)
                used_rows += int(old is None)
                if used_bytes>self.max_bytes or used_rows>self.max_rows:
                    # Roll back the whole batch. Never evict a library reference silently.
                    raise APIProblem('extension_reference_budget',status=507,category='internal')
                conn.execute('INSERT INTO extension_native_references(source_key,kind,public_url,native_url,metadata_json,metadata_size) '
                             'VALUES (?,?,?,?,?,?) ON CONFLICT(source_key,kind,public_url) DO UPDATE SET '
                             'native_url=excluded.native_url,metadata_json=excluded.metadata_json,metadata_size=excluded.metadata_size,updated_at=CURRENT_TIMESTAMP',
                             (self.source_key,kind,public_url,native_url,encoded,size))
            conn.execute('UPDATE extension_reference_budget SET used_bytes=?,used_rows=? WHERE id=1',(used_bytes,used_rows))

    def get(self, kind, public_url):
        with sqlite_connection(self.db_path) as conn:
            row = conn.execute('SELECT metadata_json FROM extension_native_references WHERE source_key=? AND kind=? AND public_url=?',
                               (self.source_key,kind,public_url)).fetchone()
        if not row:
            return None
        value = json.loads(row['metadata_json'])
        if not isinstance(value,dict):
            raise APIProblem('extension_reference_invalid',status=422,category='validation')
        return value
