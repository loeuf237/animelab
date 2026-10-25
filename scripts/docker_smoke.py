"""Exercise the server image with disposable Compose volumes, never user data.

Build animelab:local first. Run from any directory with Docker Compose v2.
"""
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.request import Request, ProxyHandler, build_opener
import uuid

ROOT = Path(__file__).resolve().parents[1]


def main():
    project = 'animelab-smoke-' + uuid.uuid4().hex[:12]
    env = {**os.environ, 'ANIMELAB_PORT': '0', 'ANIMELAB_BIND_ADDRESS': '127.0.0.1',
           'ANIMELAB_STARTUP_REFRESH': 'false'}
    compose = ['docker', 'compose', '-f', str(ROOT / 'compose.yaml'), '-p', project]

    def command(*args, **kwargs):
        return subprocess.check_output([*compose, *args], env=env, cwd=ROOT, text=True, **kwargs).strip()

    def start():
        command('up', '-d', '--no-build', '--wait', '--wait-timeout', '120')
        address = command('port', 'animelab', '8080')
        return 'http://' + address

    opener = build_opener(ProxyHandler({}))

    def request(base, path, payload=None, headers=None):
        req = Request(base + path, data=json.dumps(payload).encode() if payload is not None else None,
                      headers={'Content-Type': 'application/json', 'Origin': base, **(headers or {})})
        return opener.open(req, timeout=15)

    def api(base, path, payload=None):
        with request(base, path, payload) as response:
            return json.load(response)

    try:
        base = start()
        with request(base, '/app/') as response:
            page = response.read().decode()
        script = re.search(r'src="(/assets/[^\"]+\.js)"', page)
        if 'AnimeLab' not in page or not script:
            raise RuntimeError('Compiled Vue application is missing')
        with request(base, script.group(1)) as response:
            if response.status != 200 or not response.read(128):
                raise RuntimeError('Compiled Vue asset is not served')
        if not api(base, '/api/download/settings')['ffmpegAvailable']:
            raise RuntimeError('The server cannot find FFmpeg')
        api(base, '/api/favorites', {'url': 'https://example.invalid/docker-smoke',
                                   'title': 'Docker persistence check', 'autoDownload': False})
        preferences = {'maxConcurrentDownloads': 2, 'globalSpeedLimit': 4096, 'plexOrganization': True,
                       'selectedUserAgent': 'Chrome', 'voiranimeDefaultServer': 'sibnet'}
        api(base, '/api/download/settings', preferences)
        fixture = command('exec', '-T', 'animelab', 'python', '-c', '''
import json, os, subprocess
from pathlib import Path
from animelab.config import settings
from animelab.models.download_task import DownloadTask, DownloadStatus
from animelab.services.library_service import library_service
assert os.getuid() == 1000 and os.getgid() == 1000
assert Path.home() == Path('/data')
assert not Path('/app/android').exists() and not Path('/app/.git').exists()
assert not Path('/app/frontend/node_modules').exists()
p = Path(settings.DOWNLOAD_DIR) / 'docker-smoke.mp4'
subprocess.run(['ffmpeg', '-v', 'error', '-f', 'lavfi', '-i', 'color=c=black:s=64x64:r=10',
                '-t', '0.3', '-c:v', 'libx264', '-pix_fmt', 'yuv420p', str(p)], check=True)
subprocess.run(['ffmpeg', '-v', 'error', '-i', str(p), '-f', 'null', '-'], check=True)
duration = subprocess.check_output(['ffprobe', '-v', 'error', '-show_entries', 'format=duration',
                                  '-of', 'default=noprint_wrappers=1:nokey=1', str(p)], text=True)
assert float(duration) > 0
for parent in [Path.home()/'.animan/extensions', settings.CACHE_DIR/'http_sessions']:
    parent.mkdir(parents=True, exist_ok=True)
    (parent/'.docker-smoke-marker').write_text('persistent')
task = DownloadTask(id='docker-smoke-media', animeName='Docker smoke', episodeNumber=1,
    fileName=p.name, savePath=str(p), status=DownloadStatus.COMPLETED, progress=100,
    totalBytes=p.stat().st_size, downloadedBytes=p.stat().st_size,
    verificationStatus='VALID', videoDuration=float(duration))
library_service.save_task(task)
print(json.dumps({'prefix':p.read_bytes()[:64].hex(), 'size':p.stat().st_size}))
''')
        media = json.loads(fixture)
        container = command('ps', '-q', 'animelab')
        command('stop', '--timeout', '30')
        exit_code = subprocess.check_output(['docker', 'inspect', '--format', '{{.State.ExitCode}}', container], text=True).strip()
        # Uvicorn re-raises the received SIGTERM after its lifespan cleanup;
        # Docker/init then reports 128 + SIGTERM (143), even on a clean stop.
        # Require completed cleanup too, and reject forced SIGKILL (137).
        shutdown_logs = command('logs', '--no-color', 'animelab')
        if (exit_code not in ('0', '143') or 'Application shutdown complete.' not in shutdown_logs
                or 'Finished server process' not in shutdown_logs):
            raise RuntimeError('Server did not shut down gracefully: ' + exit_code)
        command('down', '--timeout', '30')  # Recreate the container, retaining only its volumes.
        base = start()
        favorites = api(base, '/api/favorites')
        if not any(f['title'] == 'Docker persistence check' for f in favorites):
            raise RuntimeError('Library did not survive container replacement')
        restored = api(base, '/api/download/settings')
        if any(restored[key] != value for key, value in preferences.items()):
            raise RuntimeError('Settings did not survive container replacement')
        command('exec', '-T', 'animelab', 'python', '-c', '''
from pathlib import Path
from animelab.config import settings
for parent in [Path.home()/'.animan/extensions', settings.CACHE_DIR/'http_sessions']:
    assert (parent/'.docker-smoke-marker').read_text() == 'persistent'
''')
        with request(base, '/api/media/stream/docker-smoke-media', headers={'Range': 'bytes=0-63'}) as response:
            if (response.status != 206 or response.read().hex() != media['prefix']
                    or response.headers['Content-Range'] != f"bytes 0-63/{media['size']}"):
                raise RuntimeError('Persisted video cannot be played with HTTP Range')
        print('Docker checks passed: non-root startup, Vue/API, FFmpeg encode/decode, graceful stop, '
              'persistent library/settings/extensions/sessions/video and local playback after replacement.')
    except BaseException:
        subprocess.run([*compose, 'logs', '--no-color'], env=env, cwd=ROOT, check=False)
        raise
    finally:
        subprocess.run([*compose, 'down', '--volumes', '--remove-orphans', '--timeout', '30'],
                       env=env, cwd=ROOT, check=False)


if __name__ == '__main__':
    main()
