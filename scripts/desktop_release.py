"""Prepare, check and archive desktop release artifacts on their native runners."""
import hashlib
from importlib import metadata
import json
import os
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
import time
import zipfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from animan import __version__


def prepare():
    tag = os.environ.get('RELEASE_TAG', 'v' + __version__)
    if tag != 'v' + __version__: raise ValueError('Tag does not match the application version')
    target = ROOT / 'build' / 'release-metadata'
    target.mkdir(parents=True, exist_ok=True)
    packages = {item.metadata['Name']:item.version for item in metadata.distributions()}
    tools = {}
    for name in ('ffmpeg', 'ffprobe'):
        path = os.getenv('ANIMAN_' + name.upper() + '_BINARY') or shutil.which(name)
        if not path: raise RuntimeError(f'{name} is not installed')
        result = subprocess.run([path, '-version'], capture_output=True, text=True, check=True)
        tools[name] = result.stdout.splitlines()[0]
        license_text = subprocess.run([path, '-L'], capture_output=True, text=True, check=True)
        (target / (name + '-license.txt')).write_text(license_text.stdout + license_text.stderr)
    manifest = {'version':__version__, 'commit':subprocess.check_output(['git','rev-parse','HEAD'], text=True).strip(),
                'platform':platform.system(), 'architecture':platform.machine(), 'python':platform.python_version(),
                'macos_hardware_tested':False, 'media_tools':tools, 'packages':packages}
    (target / 'build-info.json').write_text(json.dumps(manifest, indent=2))
    (target / 'MEDIA-SOURCES.txt').write_text(
        'FFmpeg project: https://ffmpeg.org/\nLinux: Ubuntu package repositories\n'
        'macOS: Homebrew ffmpeg formula\nWindows: Chocolatey ffmpeg package / Gyan builds\n'
        'Build versions and license notices are recorded beside this file.\n')
    license_dir = target / 'python-package-licenses'
    for package in metadata.distributions():
        for item in package.files or []:
            if re.search(r'(license|copying|notice)', item.name, re.I) and item.name.lower().endswith(('.txt','.md','.rst','license','copying','notice')):
                source = package.locate_file(item)
                if source.is_file():
                    destination = license_dir / package.metadata['Name'] / str(item).split('.dist-info/')[-1]
                    destination.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copyfile(source, destination)


def packaged_binary():
    if sys.platform == 'darwin': binary = ROOT / 'dist/AnimeLab.app/Contents/MacOS/AnimeLab'
    else: binary = ROOT / ('dist/AnimeLab/AnimeLab.exe' if os.name == 'nt' else 'dist/AnimeLab/AnimeLab')
    return binary


def gui_check():
    command = [sys.executable, str(ROOT / 'desktop.py')] if '--source' in sys.argv else [str(packaged_binary())]
    logfile = ROOT / 'build/native-window-check.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(command + ['--gui-self-test'], timeout=60, check=True,
                       env={**os.environ, 'ANIMAN_LOG_FILE': str(logfile)})
    finally:
        if logfile.exists(): print(logfile.read_text(encoding='utf-8'))


def launcher_check():
    command = [sys.executable, str(ROOT / 'desktop.py')] if '--source' in sys.argv else [str(packaged_binary())]
    logfile = ROOT / 'build/native-launcher-check.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    try:
        subprocess.run(command + ['--launcher-self-test'], timeout=60, check=True,
                       env={**os.environ, 'ANIMAN_LOG_FILE': str(logfile)})
    finally:
        if logfile.exists(): print(logfile.read_text(encoding='utf-8'))


def check():
    binary = packaged_binary()
    logfile = ROOT / 'build' / 'packaged-self-test.log'
    logfile.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run([str(binary), '--self-test'], timeout=90,
                            env={**os.environ, 'ANIMAN_LOG_FILE':str(logfile)})
    if logfile.exists(): print(logfile.read_text())
    if result.returncode: raise RuntimeError('Packaged offline check failed')
    # This checks subprocess collection, private administration assets and graceful exit.
    # The previous backend-only self-test could not detect the Windows GUI regression.
    from animan.desktop.control import remote_call
    from animan.desktop.state import InstanceLock, read_json
    with tempfile.TemporaryDirectory(prefix='animelab-packaged-lifecycle-') as temporary:
        root = Path(temporary)
        env = {**os.environ, 'HOME': temporary, 'USERPROFILE': temporary,
               'ANIMAN_DB_PATH': str(root / 'db.sqlite3'), 'ANIMAN_CACHE_DIR': str(root / 'cache'),
               'ANIMAN_DOWNLOAD_DIR': str(root / 'downloads'), 'ANIMAN_STARTUP_REFRESH': 'false',
               'ANIMAN_ALLOWED_HOSTS': '127.0.0.1,localhost'}
        process = subprocess.Popen([str(binary), '--headless'], env=env)
        try:
            deadline = time.monotonic() + 55
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                record = read_json(root / '.animan/desktop/runtime.json')
                try:
                    ready = remote_call(record)['ready']
                    if ready: break
                except (OSError, ValueError): pass
                time.sleep(.2)
            if not ready: raise RuntimeError('Packaged desktop supervisor failed to start')
            # Exercise a real bundled static panel, not just API JSON.
            from urllib.request import ProxyHandler, build_opener
            with build_opener(ProxyHandler({})).open(f"http://127.0.0.1:{record['port']}/", timeout=5) as response:
                if b'config-form' not in response.read(): raise RuntimeError('Packaged administration panel is missing')
            report = remote_call(record, '/api/diagnostics')
            if not report['ok']: raise RuntimeError('Packaged desktop diagnostics failed: ' + json.dumps(report))
            remote_call(record, '/api/action', {'action': 'stop'})
            if process.wait(timeout=45): raise RuntimeError('Packaged desktop failed to stop cleanly')
            if (root / '.animan/desktop/runtime.json').exists(): raise RuntimeError('Desktop instance state was not cleaned')
            process = subprocess.Popen([str(binary), '--headless'], env=env)
            deadline = time.monotonic() + 55
            ready = False
            while process.poll() is None and time.monotonic() < deadline:
                record = read_json(root / '.animan/desktop/runtime.json')
                try:
                    ready = remote_call(record)['ready']
                    if ready: break
                except (OSError, ValueError): pass
                time.sleep(.2)
            if not ready: raise RuntimeError('Packaged desktop did not relaunch')
            engine_lock = InstanceLock(root / '.animan/desktop', 'engine.lock')
            if engine_lock.acquire():
                engine_lock.release()
                raise RuntimeError('Packaged engine is not holding its library lock')
            process.kill()  # Only this owned supervisor, to test real orphan recovery.
            process.wait(timeout=10)
            deadline = time.monotonic() + 45
            recovered = False
            while time.monotonic() < deadline:
                if engine_lock.acquire():
                    engine_lock.release()
                    recovered = True
                    break
                time.sleep(.2)
            if not recovered: raise RuntimeError('Packaged orphan engine failed to exit')
        finally:
            if process.poll() is None:
                process.terminate()
                process.wait(timeout=10)


def shortcuts(directory, binary, windows=False, mac=False):
    shutil.copyfile(ROOT / 'docs/desktop-distribution.md', directory / 'DESKTOP-TOOLS.md')
    for name, flag in [('Administration', '--admin'), ('Browser', '--browser'), ('Stop', '--stop')]:
        if windows:
            content = f'@echo off\r\nstart "" /wait "%~dp0{binary}" {flag}\r\n'
            path = directory / (name + '.cmd')
        else:
            content = f'#!/bin/sh\ncd -- "$(dirname -- "$0")" || exit 1\nexec "./{binary}" {flag}\n'
            path = directory / (name + ('.command' if mac else '.sh'))
        path.write_bytes(content.encode('utf-8'))
        path.chmod(0o755)


def archive():
    label = os.environ['PLATFORM_LABEL']
    if not re.fullmatch(r'[A-Za-z0-9-]+',label): raise ValueError('Invalid platform label')
    output = ROOT / 'release-assets'
    output.mkdir(exist_ok=True)
    filename = f'AnimeLab-v{__version__}-{label}'
    if sys.platform == 'darwin':
        destination = output / (filename + '-UNTESTED.zip')
        wrapper = ROOT / 'build/macos-package/AnimeLab'
        wrapper.mkdir(parents=True, exist_ok=True)
        shutil.copytree(ROOT / 'dist/AnimeLab.app', wrapper / 'AnimeLab.app', dirs_exist_ok=True, symlinks=True)
        shortcuts(wrapper, 'AnimeLab.app/Contents/MacOS/AnimeLab', mac=True)
        subprocess.run(['ditto','-c','-k','--sequesterRsrc','--keepParent',str(wrapper),str(destination)],check=True)
    elif os.name == 'nt':
        shortcuts(ROOT / 'dist/AnimeLab', 'AnimeLab.exe', windows=True)
        destination = output / (filename + '.zip')
        with zipfile.ZipFile(destination,'w',zipfile.ZIP_DEFLATED) as handle:
            for path in (ROOT / 'dist/AnimeLab').rglob('*'):
                if path.is_file(): handle.write(path,path.relative_to(ROOT / 'dist'))
    else:
        shortcuts(ROOT / 'dist/AnimeLab', 'AnimeLab')
        destination = output / (filename + '.tar.gz')
        with tarfile.open(destination,'w:gz') as handle:
            handle.add(ROOT / 'dist/AnimeLab',arcname='AnimeLab')
    shutil.copyfile(ROOT / 'build/release-metadata/build-info.json',output / (filename + '-build-info.json'))
    print(destination)


def checksums():
    root = Path(sys.argv[2])
    archives = sorted(p for p in root.iterdir() if p.name.endswith(('.zip','.tar.gz')))
    expected = {'Windows-x64','Linux-x64','macOS-arm64-UNTESTED','macOS-x64-UNTESTED'}
    if {p.name.removeprefix(f'AnimeLab-v{__version__}-').removesuffix('.tar.gz').removesuffix('.zip') for p in archives} != expected:
        raise RuntimeError('Release is incomplete or contains unexpected platform archives')
    with (root / 'SHA256SUMS.txt').open('w') as handle:
        for path in sorted(p for p in root.iterdir() if p.name != 'SHA256SUMS.txt'):
            with path.open('rb') as source:
                digest = hashlib.file_digest(source,'sha256').hexdigest()
            handle.write(f'{digest}  {path.name}\n')


if __name__ == '__main__':
    {'prepare':prepare,'check':check,'gui-check':gui_check,'launcher-check':launcher_check,
     'archive':archive,'checksums':checksums}[sys.argv[1]]()
