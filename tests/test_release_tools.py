import hashlib
import sys
import json
import subprocess
from pathlib import Path
import pytest
from scripts import desktop_release


@pytest.mark.parametrize('version', ['0.1.0', '0.1.1', '0.1.2'])
def test_publication_rejects_missing_platform_and_checksums_exact_files(tmp_path, monkeypatch, version):
    monkeypatch.setattr(desktop_release, '__version__', version)
    names = ['Windows-x64.zip', 'Linux-x64.tar.gz', 'macOS-arm64-UNTESTED.zip', 'macOS-x64-UNTESTED.zip']
    for name in names[:-1]:
        (tmp_path / (f'AnimeLab-v{version}-' + name)).write_bytes(b'package')
    monkeypatch.setattr(sys, 'argv', ['release','checksums',str(tmp_path)])
    with pytest.raises(RuntimeError, match='incomplete'):
        desktop_release.checksums()
    (tmp_path / (f'AnimeLab-v{version}-' + names[-1])).write_bytes(b'mac')
    (tmp_path / 'build-info.json').write_bytes(b'{}')
    desktop_release.checksums()
    for line in (tmp_path / 'SHA256SUMS.txt').read_text().splitlines():
        digest, filename = line.split('  ')
        assert hashlib.sha256((tmp_path / filename).read_bytes()).hexdigest() == digest
    assert len((tmp_path / 'SHA256SUMS.txt').read_text().splitlines()) == 5


def test_preparation_rejects_mismatched_release_version(monkeypatch):
    monkeypatch.setenv('RELEASE_TAG','v2.1.0')
    with pytest.raises(ValueError, match='Tag'):
        desktop_release.prepare()


def test_windowed_entry_point_can_configure_server_without_console(tmp_path):
    result = tmp_path / 'streams.json'
    code = '''
import sys, json
sys.stdin = sys.stdout = sys.stderr = None
import desktop, uvicorn
async def app(scope, receive, send): pass
uvicorn.Config(app, log_config=None, access_log=False)
with open(sys.argv[1], 'w') as handle:
    json.dump({name:getattr(sys,name) is not None for name in ('stdin','stdout','stderr')}, handle)
'''
    subprocess.run([sys.executable, '-c', code, str(result)],
                   cwd=Path(__file__).resolve().parents[1], check=True, timeout=20)
    assert json.loads(result.read_text()) == {'stdin':True,'stdout':True,'stderr':True}
