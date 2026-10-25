"""Offline proxy preferences use the same SQLite table as the running engine."""
import re
from contextlib import closing
import sqlite3

FIELDS = {'enabled': False, 'proxy_type': 'http', 'host': '', 'port': '',
          'username': '', 'password': '', 'custom_url': ''}


def raw_settings(path):
    if path.is_file():
        with closing(sqlite3.connect(path.resolve().as_uri() + '?mode=ro', uri=True)) as db:
            db.row_factory = sqlite3.Row
            try:
                row = db.execute('SELECT * FROM network_proxy_settings WHERE id=1').fetchone()
            except sqlite3.OperationalError:
                row = None
        if row:
            return {key: row[key] for key in FIELDS}
    return dict(FIELDS)


def masked_url(url):
    return re.sub(r'(://[^/@:]+):[^/@]*@', r'\1:******@', url or '')


def load_proxy(path):
    data = raw_settings(path)
    return {**data, 'enabled': bool(data['enabled']), 'port': data['port'] or '',
            'password': '******' if data['password'] else '', 'custom_url': masked_url(data['custom_url'])}


def save_proxy(path, values):
    old = raw_settings(path)
    data = {**old, **values}
    if data['proxy_type'] not in ('http', 'https', 'socks5', 'socks5h', 'socks4', 'socks4a'):
        raise ValueError('Invalid proxy protocol')
    port = data['port']
    if port not in ('', None) and not 1 <= int(port) <= 65535:
        raise ValueError('Invalid proxy port')
    data['port'] = int(port) if port not in ('', None) else None
    if data['password'] == '******': data['password'] = old['password']
    if data['custom_url'] == masked_url(old['custom_url']): data['custom_url'] = old['custom_url']
    from animan.database import init_db
    path.parent.mkdir(parents=True, exist_ok=True)
    init_db(str(path))
    with closing(sqlite3.connect(path)) as db, db:
        db.execute('''INSERT INTO network_proxy_settings
            (id, enabled, proxy_type, host, port, username, password, custom_url)
            VALUES (1, :enabled, :proxy_type, :host, :port, :username, :password, :custom_url)
            ON CONFLICT(id) DO UPDATE SET enabled=excluded.enabled, proxy_type=excluded.proxy_type,
            host=excluded.host, port=excluded.port, username=excluded.username,
            password=excluded.password, custom_url=excluded.custom_url''', data)
    return load_proxy(path)
