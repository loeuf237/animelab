"""Bounded structured telemetry. Export accepts only an explicit field allowlist."""
from collections import deque, OrderedDict
from datetime import datetime, timezone
import json
import logging
import re
import threading
import time
import traceback
from urllib.parse import urlsplit

_LOCK = threading.RLock()
_SECRETS = deque(maxlen=256)
_SAFE = re.compile(r'^[A-Za-z0-9_.:-]{1,255}$')
_URL = re.compile(r'https?://[^\s<>\"\']+')


def remember_secret(value):
    if isinstance(value, str) and len(value) >= 4:
        with _LOCK:
            if value not in _SECRETS: _SECRETS.append(value)


def redact_text(value):
    text = str(value)
    # Header dumps and key/value credential lines are deliberately discarded.
    if re.search(r'(?i)(?:cookie|authorization|password|passwd|secret|access[_-]?token|animan[_-]?session)\s*[\"\']?\s*[:=]', text):
        return '[redacted sensitive log]'
    def origin(match):
        try: return urlsplit(match.group()).scheme + '://' + (urlsplit(match.group()).hostname or '[host]') + '/[resource]'
        except ValueError: return '[url]'
    text = _URL.sub(origin, text)
    with _LOCK:
        for secret in _SECRETS: text = text.replace(secret, '[redacted]')
    text = re.sub(r'(?i)([?&](?:token|key|signature|auth|session)[^=\s]*=)[^\s&]+', r'\1[redacted]', text)
    text = re.sub(r'(?i)Bearer\s+\S+', 'Bearer [redacted]', text)
    return text


def install_logging():
    previous = logging.getLogRecordFactory()
    if getattr(previous, '_animan_safe', False): return
    def factory(*args, **kwargs):
        record = previous(*args, **kwargs)
        if record.name == 'uvicorn.access' and isinstance(record.args, tuple) and len(record.args) == 5:
            client, method, path, version, status = record.args
            record.args = (client, method, str(path).split('?')[0], version, status)
        else:
            record.msg, record.args = redact_text(record.getMessage()), ()
        if record.exc_info:
            record.exc_text = redact_text(''.join(traceback.format_exception(*record.exc_info)))
            record.exc_info = None
        return record
    factory._animan_safe = True
    logging.setLogRecordFactory(factory)


def domain(url):
    if not isinstance(url,str): return ''
    try: return urlsplit(url or '').hostname or ''
    except ValueError: return ''


class Telemetry:
    def __init__(self, capacity=2000):
        self.events = deque(maxlen=capacity)
        self.phases = OrderedDict()
        self.lock = threading.RLock()

    def event(self, event, **fields):
        row = {'time': datetime.now(timezone.utc).isoformat(), 'event': event if _SAFE.fullmatch(event) else 'event'}
        for key in ('taskId','source','domain','phase','status','code','operation'):
            value = fields.get(key)
            if isinstance(value, str) and _SAFE.fullmatch(value):
                with _LOCK:
                    row[key] = 'redacted' if any(secret in value for secret in _SECRETS) else value
        for key in ('durationMs','waitMs','count','attempt'):
            value = fields.get(key)
            if isinstance(value, (int,float)) and 0 <= value < 1e12: row[key] = round(value, 2)
        with self.lock: self.events.append(row)
        logging.getLogger('animelab.events').info(json.dumps(row, ensure_ascii=False))
        return row

    def task_phase(self, task):
        phase = task.phase or task.status.value.lower()
        current = (phase, task.status.value)
        context = {'taskId':task.id, 'source':task.source or 'unknown',
                   'domain':domain(task.verificationUrl or task.directDownloadUrl or task.fileUrl)}
        now = time.monotonic()
        with self.lock:
            old = self.phases.get(task.id)
            if old and old[:2] == current: return
            if old: self.event('phase_finished', **context, phase=old[0],status=old[1],durationMs=(now-old[2])*1000)
            self.event('phase_started', **context, phase=phase,status=task.status.value)
            self.phases[task.id] = (*current, now)
            self.phases.move_to_end(task.id)
            if len(self.phases) > 1000: self.phases.popitem(last=False)

    def snapshot(self):
        with self.lock: return [dict(row) for row in self.events]


telemetry = Telemetry()
