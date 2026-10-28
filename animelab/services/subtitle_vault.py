"""Optional secret persistence, encrypted with an operator-supplied external key.

No key is generated beside the database. Without a key file, credentials live
only in the private worker's memory. File encryption does not protect a running
account from a compromised host or an administrator who controls that host.
"""
import hashlib
import json
import os
from pathlib import Path
import stat

from animelab.database import sqlite_connection
from animelab.services.subtitle_provider import ProviderError


class SubtitleVault:
    def __init__(self, db_path, download_dir, cache_dir, key_file=None, *, provider='opensubtitles'):
        if provider not in ('opensubtitles', 'subdl'):
            raise ValueError('Unknown subtitle provider')
        self.provider = provider
        self.db_path = str(db_path)
        self.protected = [Path(db_path).absolute().parent, Path(download_dir).absolute(), Path(cache_dir).absolute()]
        self.key_file = key_file if key_file is not None else os.getenv('ANIMELAB_SUBTITLE_KEY_FILE')
        self.scope = hashlib.sha256(str(Path(db_path).resolve()).encode()).hexdigest()

    def cipher(self):
        if not self.key_file:
            raise ValueError('No external encryption key')
        path = Path(self.key_file)
        if not path.is_absolute() or any(path.resolve().is_relative_to(root.resolve()) for root in self.protected):
            raise ValueError('Encryption key must be outside account data and downloads')
        info = path.stat()
        if not stat.S_ISREG(info.st_mode) or info.st_size > 256:
            raise ValueError('Invalid key file')
        if os.name == 'posix' and (info.st_mode & 0o077):
            raise ValueError('Encryption key permissions must be private')
        from cryptography.fernet import Fernet
        return Fernet(path.read_bytes().strip())

    def available(self):
        try:
            self.cipher()
            return True
        except (ValueError, OSError, ImportError):
            return False

    def load(self):
        with sqlite_connection(self.db_path) as db:
            row = db.execute('SELECT payload FROM subtitle_provider_secret WHERE provider=?', (self.provider,)).fetchone()
        if not row:
            return None
        try:
            from cryptography.fernet import InvalidToken
            data = json.loads(self.cipher().decrypt(row['payload'].encode()))
            if (data.get('scope') != self.scope or data.get('provider', 'opensubtitles') != self.provider
                    or not isinstance(data.get('credentials'), dict)):
                raise ValueError()
            return data['credentials']
        except Exception as exc:
            raise ProviderError('Les identifiants sauvegardés ne peuvent pas être déchiffrés ; reconnectez le fournisseur', 'provider_storage') from exc

    def save(self, credentials):
        try:
            value = self.cipher().encrypt(json.dumps(dict(scope=self.scope, provider=self.provider, credentials=credentials)).encode()).decode()
        except (ValueError, OSError, ImportError) as exc:
            raise ProviderError('Clé de chiffrement externe indisponible', 'provider_storage') from exc
        with sqlite_connection(self.db_path) as db:
            db.execute('INSERT INTO subtitle_provider_secret(provider,payload) VALUES(?,?) '
                       'ON CONFLICT(provider) DO UPDATE SET payload=excluded.payload', (self.provider, value))

    def clear(self):
        with sqlite_connection(self.db_path) as db:
            db.execute('DELETE FROM subtitle_provider_secret WHERE provider=?', (self.provider,))
