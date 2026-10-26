"""Admin-managed identities, single-use invitations and revocable sessions."""
from contextlib import closing, contextmanager
import hashlib
import hmac
from pathlib import Path
import re
import secrets
import sqlite3
import threading
import time
import uuid
import json

PERMISSIONS = {'download', 'extensions'}
SCRYPT_N = 2 ** 17
_HASH_LOCK = threading.BoundedSemaphore(1)  # One 128 MiB computation; no waiting queue.
LEGACY_SCRYPT = (2 ** 17, 8, 1)


class PasswordBusy(Exception):
    """Password work is temporarily at capacity, without recording a failure."""


def _derive(password, salt, n, r, p):
    if not isinstance(password, str) or not 12 <= len(password) <= 256:
        raise ValueError('Use a password of 12 to 256 characters')
    # Reject malformed/corrupt stored parameters before allocating memory.
    if (n < 1024 or n > 2 ** 20 or n & (n - 1) or not 1 <= r <= 32
            or not 1 <= p <= 16 or n * r > 2 ** 20 or n * r * p > 2 ** 22):
        raise ValueError('Invalid scrypt parameters')
    salt_bytes = bytes.fromhex(salt)
    if len(salt_bytes) != 16:
        raise ValueError('Invalid password salt')
    if not _HASH_LOCK.acquire(blocking=False):
        raise PasswordBusy('Password verification is busy; try again shortly')
    try:
        return hashlib.scrypt(password.encode(), salt=salt_bytes, n=n, r=r, p=p,
                              maxmem=256 * 1024 * 1024).hex()
    finally:
        _HASH_LOCK.release()


def _parameters(encoded):
    if not isinstance(encoded, str) or len(encoded) > 256:
        raise ValueError('Invalid password hash')
    if encoded.startswith('scrypt$'):
        algorithm, n, r, p, salt, key = encoded.split('$')
        params = (int(n), int(r), int(p))
    else:
        salt, key = encoded.split(':')
        params = LEGACY_SCRYPT
    if len(bytes.fromhex(key)) != 64:
        raise ValueError('Invalid password key')
    return (*params, salt, key)


def password_hash(password, salt=None):
    salt = salt or secrets.token_hex(16)
    key = _derive(password, salt, SCRYPT_N, 8, 1)
    return f'scrypt${SCRYPT_N}$8$1${salt}${key}'


def password_matches(password, encoded):
    try:
        n, r, p, salt, key = _parameters(encoded)
        return hmac.compare_digest(_derive(password, salt, n, r, p), key)
    except (ValueError, TypeError, AttributeError):
        return False


def digest(token):
    return hashlib.sha256(token.encode()).hexdigest()


def grants(permissions):
    if not isinstance(permissions, list) or any(p not in PERMISSIONS for p in permissions):
        raise ValueError('Unknown permission')
    return json.dumps(sorted(set(permissions)))


def username_value(username):
    if not isinstance(username, str) or not re.fullmatch(r'[a-zA-Z0-9][a-zA-Z0-9_.-]{2,39}', username):
        raise ValueError('Username: 3 to 40 letters, digits, dots, underscores or hyphens')
    return username.lower()


class Accounts:
    def __init__(self, root, *, lifetime=43200, idle=1800):
        self.root = Path(root).resolve()
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.root.chmod(0o700)
        self.path = self.root / 'accounts.sqlite3'
        self.lifetime, self.idle = lifetime, idle
        with self.connect() as db:
            db.executescript('''
                CREATE TABLE IF NOT EXISTS users (
                    id TEXT PRIMARY KEY, username TEXT UNIQUE NOT NULL, password TEXT NOT NULL,
                    admin INTEGER NOT NULL, enabled INTEGER NOT NULL DEFAULT 1, permissions TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS sessions (
                    token TEXT PRIMARY KEY, user_id TEXT NOT NULL REFERENCES users(id),
                    created REAL NOT NULL, touched REAL NOT NULL, expires REAL NOT NULL);
                CREATE INDEX IF NOT EXISTS sessions_user ON sessions(user_id);
                CREATE TABLE IF NOT EXISTS codes (
                    token TEXT PRIMARY KEY, user_id TEXT REFERENCES users(id),
                    expires REAL NOT NULL, permissions TEXT NOT NULL);
            ''')
            if 'expires' not in {row['name'] for row in db.execute('PRAGMA table_info(sessions)')}:
                db.execute('ALTER TABLE sessions ADD COLUMN expires REAL NOT NULL DEFAULT 0')
                db.execute('UPDATE sessions SET expires=created+43200')
        self.path.chmod(0o600)
        self.dummy = password_hash(secrets.token_urlsafe(32))

    @contextmanager
    def connect(self):
        with closing(sqlite3.connect(self.path, timeout=10)) as db:
            db.row_factory = sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON')
            with db:
                yield db

    @staticmethod
    def public(row):
        return {'id': row['id'], 'username': row['username'],
                'admin': bool(row['admin']), 'enabled': bool(row['enabled']),
                'permissions': json.loads(row['permissions'])}

    def users(self):
        with self.connect() as db:
            return [self.public(row) for row in db.execute('SELECT * FROM users ORDER BY username')]

    def create(self, username, password, admin=False, permissions=None):
        username = username_value(username)
        encoded = password_hash(password)
        permissions = grants(['download'] if permissions is None else permissions)
        user_id = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                self._insert(db, user_id, username, encoded, admin, permissions)
        except sqlite3.IntegrityError as exc:
            raise ValueError('Username already exists') from exc
        return user_id

    def bootstrap(self, username, password):
        """Local operator only; atomically refuse replacement of an existing admin."""
        username = username_value(username)
        encoded = password_hash(password)
        user_id = uuid.uuid4().hex
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                if db.execute('SELECT id FROM users WHERE admin=1 AND enabled=1').fetchone():
                    raise ValueError('An administrator is already configured')
                self._insert(db, user_id, username, encoded, True, grants(['download', 'extensions']))
        except sqlite3.IntegrityError as exc:
            raise ValueError('Username already exists') from exc
        return user_id

    @staticmethod
    def _insert(db, user_id, username, encoded, admin, permissions):
        if db.execute('SELECT COUNT(*) FROM users').fetchone()[0] >= 100:
            raise ValueError('Account limit reached (100)')
        db.execute('INSERT INTO users VALUES (?,?,?,?,1,?)',
                   (user_id, username, encoded, int(admin), permissions))

    def _verified_record(self, username, password):
        username = username.lower() if isinstance(username, str) else ''
        with self.connect() as db:
            row = db.execute('SELECT * FROM users WHERE username=?', (username,)).fetchone()
        valid = password_matches(password, row['password'] if row else self.dummy)
        return row if valid and row and row['enabled'] else None

    def authenticate(self, username, password):
        row = self._verified_record(username, password)
        return self.public(row) if row else None

    def login(self, username, password):
        row = self._verified_record(username, password)
        if not row:
            return None
        # Rehash only after successful verification, without holding SQLite
        # during scrypt. The comparison below lets an administrator reset win.
        n, r, p, _, _ = _parameters(row['password'])
        replacement = None
        if not row['password'].startswith('scrypt$') or (n, r, p) != (SCRYPT_N, 8, 1):
            replacement = password_hash(password)
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            current = db.execute('SELECT * FROM users WHERE id=? AND enabled=1', (row['id'],)).fetchone()
            if not current or current['password'] != row['password']:
                return None
            if replacement:
                db.execute('UPDATE users SET password=? WHERE id=?', (replacement, row['id']))
            return self._new_session(db, row['id'])

    def new_session(self, user_id):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            if not db.execute('SELECT id FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone():
                raise ValueError('Account not found or disabled')
            return self._new_session(db, user_id)

    def _new_session(self, db, user_id):
        token = secrets.token_urlsafe(32)
        now = time.time()
        db.execute('DELETE FROM sessions WHERE created<? OR touched<? OR expires<=?',
                   (now - self.lifetime, now - self.idle, now))
        db.execute('DELETE FROM sessions WHERE user_id=? AND token NOT IN '
                   '(SELECT token FROM sessions WHERE user_id=? ORDER BY created DESC LIMIT 9)',
                   (user_id, user_id))
        db.execute('INSERT INTO sessions VALUES (?,?,?,?,?)', (digest(token), user_id, now, now, now + self.lifetime))
        return token

    def change_password(self, token, old_password, password):
        user = self.session(token, touch=False)
        row = self._verified_record(user['username'], old_password) if user else None
        if not row:
            raise ValueError('Current password is incorrect')
        encoded = password_hash(password)
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            active = db.execute('SELECT u.password FROM sessions s JOIN users u ON u.id=s.user_id '
                'WHERE s.token=? AND s.created>? AND s.touched>? AND s.expires>? AND u.enabled=1',
                (digest(token), now - self.lifetime, now - self.idle, now)).fetchone()
            if not active or active['password'] != row['password']:
                raise ValueError('Session was revoked')
            db.execute('UPDATE users SET password=? WHERE id=?', (encoded, user['id']))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user['id'],))
            db.execute('DELETE FROM codes WHERE user_id=?', (user['id'],))

    def session(self, token, *, touch=True):
        if not token or len(token) > 128:
            return None
        now = time.time()
        with self.connect() as db:
            row = db.execute('SELECT u.* FROM sessions s JOIN users u ON u.id=s.user_id '
                             'WHERE s.token=? AND s.created>? AND s.touched>? AND s.expires>? AND u.enabled=1',
                             (digest(token), now - self.lifetime, now - self.idle, now)).fetchone()
            if row and touch:
                db.execute('UPDATE sessions SET touched=? WHERE token=?', (now, digest(token)))
        return self.public(row) if row else None

    def revoke(self, token):
        with self.connect() as db:
            db.execute('DELETE FROM sessions WHERE token=?', (digest(token),))

    def update(self, user_id, *, password=None, enabled=None, admin=None, permissions=None):
        encoded = password_hash(password) if password is not None else None
        permission_json = grants(permissions) if permissions is not None else None
        for value in (enabled, admin):
            if value is not None and not isinstance(value, bool):
                raise ValueError('Enabled and admin must be booleans')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            row = db.execute('SELECT * FROM users WHERE id=?', (user_id,)).fetchone()
            if not row:
                raise ValueError('Account not found')
            if (enabled is False or admin is False) and row['admin'] and row['enabled']:
                count = db.execute('SELECT COUNT(*) FROM users WHERE admin=1 AND enabled=1').fetchone()[0]
                if count <= 1:
                    raise ValueError('The last administrator cannot be disabled or demoted')
            if encoded:
                db.execute('UPDATE users SET password=? WHERE id=?', (encoded, user_id))
            if enabled is not None:
                db.execute('UPDATE users SET enabled=? WHERE id=?', (int(enabled), user_id))
            if admin is not None:
                db.execute('UPDATE users SET admin=? WHERE id=?', (int(admin), user_id))
            if permission_json is not None:
                db.execute('UPDATE users SET permissions=? WHERE id=?', (permission_json, user_id))
            db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
            db.execute('DELETE FROM codes WHERE user_id=?', (user_id,))

    def code(self, *, user_id=None, permissions=None):
        encoded_permissions = grants(['download'] if permissions is None else permissions)
        code = secrets.token_urlsafe(32)
        now = time.time()
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            db.execute('DELETE FROM codes WHERE expires<?', (now,))
            if user_id:
                row = db.execute('SELECT * FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone()
                if not row:
                    raise ValueError('Account not found or disabled')
                db.execute('DELETE FROM codes WHERE user_id=?', (user_id,))
            if db.execute('SELECT COUNT(*) FROM codes').fetchone()[0] >= 100:
                raise ValueError('Code limit reached (100)')
            db.execute('INSERT INTO codes VALUES (?,?,?,?)',
                       (digest(code), user_id, now + (86400 if user_id else 7 * 86400), encoded_permissions))
        return code

    def codes(self):
        with self.connect() as db:
            return [dict(id=row['token'], user_id=row['user_id'], expires=row['expires'])
                    for row in db.execute('SELECT * FROM codes WHERE expires>? ORDER BY expires', (time.time(),))]

    def revoke_code(self, code_id):
        with self.connect() as db:
            db.execute('DELETE FROM codes WHERE token=?', (code_id,))

    def redeem(self, code, password, username=None, *, issue_session=False):
        # Password work happens before acquiring SQLite's write lock.
        encoded = password_hash(password)
        if not isinstance(code, str) or len(code) > 128:
            raise ValueError('Invalid or expired code')
        try:
            with self.connect() as db:
                db.execute('BEGIN IMMEDIATE')
                row = db.execute('SELECT * FROM codes WHERE token=? AND expires>?', (digest(code), time.time())).fetchone()
                if not row:
                    raise ValueError('Invalid or expired code')
                user_id = row['user_id']
                if user_id:
                    if not db.execute('SELECT id FROM users WHERE id=? AND enabled=1', (user_id,)).fetchone():
                        raise ValueError('Invalid or expired code')
                    db.execute('UPDATE users SET password=? WHERE id=?', (encoded, user_id))
                    db.execute('DELETE FROM sessions WHERE user_id=?', (user_id,))
                else:
                    user_id = uuid.uuid4().hex
                    self._insert(db, user_id, username_value(username), encoded, False, row['permissions'])
                db.execute('DELETE FROM codes WHERE token=?', (digest(code),))
                if issue_session:
                    return self._new_session(db, user_id)
        except sqlite3.IntegrityError as exc:
            raise ValueError('Username already exists') from exc
        return user_id
