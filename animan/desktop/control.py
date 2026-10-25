"""Separate loopback control plane, usable even when FastAPI or the GUI fails."""
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
from pathlib import Path
import secrets
import threading
from urllib.request import ProxyHandler, Request, build_opener

from .state import read_json
from animan.diagnostics import remember_secret


class ControlServer:
    def __init__(self, controller):
        self.token = secrets.token_urlsafe(32)
        remember_secret(self.token)
        self.controller = controller
        owner = self

        class Handler(BaseHTTPRequestHandler):
            def log_message(self, *_):
                pass  # Never log capabilities or request payloads.

            def reply(self, status, payload, content_type='application/json'):
                body = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
                self.send_response(status)
                for key, value in {
                    'Content-Type': content_type, 'Content-Length': str(len(body)),
                    'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff',
                    'X-Frame-Options': 'DENY', 'Referrer-Policy': 'no-referrer',
                    'Content-Security-Policy': "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; base-uri 'none'; frame-ancestors 'none'; form-action 'none'",
                }.items():
                    self.send_header(key, value)
                self.end_headers()
                self.wfile.write(body)

            def permitted(self, authenticated=True):
                # Binding to loopback alone does not prevent DNS rebinding / CSRF.
                if self.headers.get('Host') != owner.authority:
                    self.reply(403, {'error': 'Invalid host'})
                    return False
                origin = self.headers.get('Origin')
                if (origin and origin != owner.origin) or self.headers.get('Sec-Fetch-Site') == 'cross-site':
                    self.reply(403, {'error': 'Invalid origin'})
                    return False
                authorization = self.headers.get('Authorization', '')
                if authenticated and not secrets.compare_digest(authorization.encode('utf-8'), ('Bearer ' + owner.token).encode('ascii')):
                    self.reply(401, {'error': 'Open administration from the AnimeLab launcher'})
                    return False
                return True

            def do_GET(self):
                self.connection.settimeout(10)
                if not self.permitted(authenticated=self.path not in ('/', '/panel.js', '/panel.css')):
                    return
                if self.path in ('/', '/panel.js', '/panel.css'):
                    name, kind = {'/': ('panel.html', 'text/html; charset=utf-8'),
                                  '/panel.js': ('panel.js', 'text/javascript; charset=utf-8'),
                                  '/panel.css': ('panel.css', 'text/css; charset=utf-8')}[self.path]
                    self.reply(200, (Path(__file__).parent / name).read_bytes(), kind)
                elif self.path == '/api/status':
                    self.reply(200, owner.controller.status())
                elif self.path == '/api/diagnostics':
                    self.reply(200, owner.controller.diagnose())
                elif self.path == '/api/launcher-config':
                    self.reply(200, owner.controller.config)
                else:
                    self.reply(404, {'error': 'Not found'})

            def do_POST(self):
                self.connection.settimeout(10)
                if not self.permitted():
                    return
                try:
                    length = int(self.headers.get('Content-Length', '0'))
                    if not 0 < length <= 8192:
                        raise ValueError('Invalid request size')
                    if self.headers.get_content_type() != 'application/json':
                        raise ValueError('Expected JSON')
                    data = json.loads(self.rfile.read(length))
                    if self.path == '/api/config':
                        owner.controller.save_config(data)
                        self.reply(200, owner.controller.status())
                    elif self.path == '/api/launcher-config':
                        owner.controller.save_launcher_config(data)
                        self.reply(200, owner.controller.status())
                    elif self.path == '/api/action' and isinstance(data, dict) and data.get('action') in ('restart', 'stop'):
                        owner.controller.command(data['action'])
                        self.reply(202, {'accepted': True})
                    else:
                        self.reply(404, {'error': 'Unknown action'})
                except (ValueError, TypeError) as error:
                    self.reply(400, {'error': str(error)})
                except OSError:
                    self.reply(500, {'error': 'Unable to save desktop settings'})

        self.server = ThreadingHTTPServer(('127.0.0.1', 0), Handler)
        self.authority = f'127.0.0.1:{self.server.server_port}'
        self.origin = 'http://' + self.authority
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True, name='AnimeLabControl')

    @property
    def url(self):
        return self.origin + '/#' + self.token

    def start(self):
        self.thread.start()

    def close(self):
        if self.thread.is_alive():
            self.server.shutdown()
        self.server.server_close()
        if self.thread.is_alive():
            self.thread.join(timeout=5)


def remote_call(record, endpoint='/api/status', data=None, timeout=15):
    """Talk only to a loopback authority, never to a URL injected into a state file."""
    if not isinstance(record, dict) or type(record.get('port')) is not int or not 1 <= record['port'] <= 65535:
        raise ValueError('No active AnimeLab desktop instance')
    token = record.get('token')
    if not isinstance(token, str) or len(token) < 32:
        raise ValueError('Invalid desktop capability')
    request = Request(f"http://127.0.0.1:{record['port']}{endpoint}",
        data=None if data is None else json.dumps(data).encode(),
        headers={'Authorization': 'Bearer ' + token, 'Content-Type': 'application/json'})
    with build_opener(ProxyHandler({})).open(request, timeout=timeout) as response:
        result = json.load(response)
    if endpoint == '/api/status' and result.get('instanceId') != record.get('instanceId'):
        raise ValueError('Desktop instance identity mismatch')
    return result


def running_record(directory):
    return read_json(directory / 'runtime.json')
