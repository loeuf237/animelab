"""Private desktop settings and a lifetime lock shared by all launcher commands."""
import json
import os
from pathlib import Path
import tempfile


def state_directory():
    path = Path.home() / '.animan' / 'desktop'
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    return path


def valid_port(value):
    if isinstance(value, bool) or not isinstance(value, int) or not 1 <= value <= 65535:
        raise ValueError('Port must be an integer between 1 and 65535')
    return value


def read_json(path):
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (OSError, ValueError):
        return None


def write_json(path, data):
    # Same-directory replace is atomic, including on Windows. Never leave half a config.
    fd, temporary = tempfile.mkstemp(dir=path.parent, prefix=path.name + '.')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as handle:
            json.dump(data, handle, indent=2)
        os.replace(temporary, path)
    finally:
        Path(temporary).unlink(missing_ok=True)


def load_config(directory):
    data = read_json(directory / 'config.json')
    if data is None:
        if (directory / 'config.json').exists():
            raise ValueError('Invalid desktop config.json; use --port to repair it')
        return {'port': 8080, 'browser': False}
    if not isinstance(data, dict) or not isinstance(data.get('browser', False), bool):
        raise ValueError('Invalid desktop configuration')
    base = {'port': valid_port(data.get('port')), 'browser': data.get('browser', False)}
    if 'launcher' in data:
        from .options import normalize_config
        return normalize_config({**base, 'launcher': data['launcher']})
    return base


class InstanceLock:
    """OS releases this lock on crash. A stale PID is never a reason to kill a process."""
    def __init__(self, directory, name='instance.lock'):
        self.path = directory / name
        self.handle = None

    def acquire(self):
        self.handle = self.path.open('a+b')
        self.handle.seek(0, os.SEEK_END)
        if not self.handle.tell():
            self.handle.write(b'0')
            self.handle.flush()
        self.handle.seek(0)
        try:
            if os.name == 'nt':
                import msvcrt
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            self.handle.close()
            self.handle = None
            return False
        return True

    def release(self):
        if self.handle:
            if os.name == 'nt':
                import msvcrt
                self.handle.seek(0)
                msvcrt.locking(self.handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl
                fcntl.flock(self.handle.fileno(), fcntl.LOCK_UN)
            self.handle.close()
            self.handle = None
