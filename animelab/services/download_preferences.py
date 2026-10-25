"""Persistent server preferences, independent of the lifetime of a process."""
from animelab.database import sqlite_connection


def load():
    with sqlite_connection() as conn:
        row = conn.execute('SELECT max_concurrent, global_limit, plex_org, user_agent, default_server '
                           'FROM download_preferences WHERE id=1').fetchone()
    return dict(row) if row else None


def save(values):
    with sqlite_connection() as conn:
        conn.execute('INSERT INTO download_preferences '
            '(id, max_concurrent, global_limit, plex_org, user_agent, default_server) '
            'VALUES (1, :max_concurrent, :global_limit, :plex_org, :user_agent, :default_server) '
            'ON CONFLICT(id) DO UPDATE SET max_concurrent=excluded.max_concurrent, '
            'global_limit=excluded.global_limit, plex_org=excluded.plex_org, '
            'user_agent=excluded.user_agent, default_server=excluded.default_server', values)
