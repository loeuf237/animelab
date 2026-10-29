import hashlib
import os
import sys
import json
import subprocess
from pathlib import Path
import pytest
from scripts import desktop_release


@pytest.mark.parametrize('version', ['0.1.0', '0.1.1', '0.1.2', '0.1.3'])
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


def test_release_title_and_body_follow_structured_notes(tmp_path, monkeypatch):
    monkeypatch.setenv('RELEASE_TAG', 'v0.1.3')
    monkeypatch.setattr(desktop_release, '__version__', '0.1.3')
    monkeypatch.setattr(desktop_release, 'ROOT', tmp_path)
    notes = tmp_path / 'docs/releases/v0.1.3.md'
    notes.parent.mkdir(parents=True)
    body = '\n'.join('## ' + name + '\n\nDetails.\n' for name in
        ('Major Changes', 'Added', 'Changed', 'Fixed', 'WebUI', 'Downloads', 'Contributors'))
    notes.write_text('# AnimeLab v0.1.3 — Native launcher\n\n' + body, encoding='utf-8')
    output = tmp_path / 'github-output'
    monkeypatch.setenv('GITHUB_OUTPUT', str(output))
    desktop_release.release_info()
    assert output.read_text(encoding='utf-8') == 'title=AnimeLab v0.1.3 — Native launcher\n'
    assert (tmp_path / 'build/release-notes.md').read_text(encoding='utf-8') == body
    notes.write_text('# AnimeLab v0.1.3\n\n## Major Changes\n', encoding='utf-8')
    with pytest.raises(ValueError, match='missing sections'):
        desktop_release.release_metadata()
    notes.write_text('# AnimeLab v0.1.2\n\n' + body, encoding='utf-8')
    with pytest.raises(ValueError, match='title'):
        desktop_release.release_metadata()


def test_desktop_publisher_generates_notes_before_uploading_assets():
    import yaml
    workflow = yaml.safe_load((desktop_release.ROOT / '.github/workflows/release-desktop.yml').read_text())
    publish = workflow['jobs']['publish']
    assert publish['needs'] == ['build', 'android']
    steps = publish['steps']
    notes = next(i for i, step in enumerate(steps) if step.get('id') == 'release')
    upload = next(i for i, step in enumerate(steps) if step.get('uses', '').startswith('softprops/action-gh-release@'))
    assert notes < upload
    assert 'release-info' in steps[notes]['run']
    assert steps[upload]['with']['name'] == '${{ steps.release.outputs.title }}'
    assert steps[upload]['with']['body_path'] == 'build/release-notes.md'
    assert steps[upload]['with']['prerelease'] is False
    assert steps[upload]['with']['make_latest'] is True
    gate=next(i for i,step in enumerate(steps) if 'head_sha=' in step.get('run',''))
    assert gate<upload and publish['permissions']['actions']=='read'


@pytest.mark.parametrize('headings',[('Changes','Downloads'),('Changements','Téléchargements')])
def test_compact_release_notes_keep_the_correct_tag_without_requiring_seven_sections(tmp_path,monkeypatch,headings):
    monkeypatch.setattr(desktop_release,'ROOT',tmp_path)
    monkeypatch.setattr(desktop_release,'__version__','0.1.6')
    monkeypatch.setenv('RELEASE_TAG','v0.1.6-beta.3')
    notes=tmp_path/'docs/releases/v0.1.6-beta.3.md'
    notes.parent.mkdir(parents=True)
    notes.write_text('# AnimeLab v0.1.6-beta.3\n\n## '+headings[0]+'\n\n- Fix.\n\n## '+headings[1]+'\n\n[Windows](https://example.test/app.zip)\n')
    result=desktop_release.release_metadata()
    assert result['title']=='AnimeLab v0.1.6-beta.3'
    assert '[Windows]' in result['body']


@pytest.mark.parametrize('tag',['v0.1.6-beta.1','v0.1.6-beta.12'])
def test_beta_tag_is_valid_without_changing_the_numeric_application_version(monkeypatch,tag):
    monkeypatch.setattr(desktop_release,'__version__','0.1.6')
    monkeypatch.setenv('RELEASE_TAG',tag)
    assert desktop_release.release_tag()==tag


@pytest.mark.parametrize('tag',['v0.1.6-beta.0','v0.1.6-beta.01','v0.1.7-beta.1','v0.1.6-beta.1/other'])
def test_invalid_or_mismatched_beta_tags_are_rejected(monkeypatch,tag):
    monkeypatch.setattr(desktop_release,'__version__','0.1.6')
    monkeypatch.setenv('RELEASE_TAG',tag)
    with pytest.raises(ValueError,match='Tag'):
        desktop_release.release_tag()


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


@pytest.mark.parametrize('windows,mac,binary,extension', [
    (True, False, 'AnimeLab.exe', '.cmd'),
    (False, False, 'AnimeLab', '.sh'),
    (False, True, 'AnimeLab.app/Contents/MacOS/AnimeLab', '.command'),
])
def test_archives_ship_quoted_administration_shortcuts(tmp_path, windows, mac, binary, extension):
    folder = tmp_path / 'Application with spaces'
    folder.mkdir()
    desktop_release.shortcuts(folder, binary, windows=windows, mac=mac)
    assert (folder / 'DESKTOP-TOOLS.md').is_file()
    for name, flag in [('Administration', '--admin'), ('Browser', '--browser'), ('Stop', '--stop')]:
        shortcut = folder / (name + extension)
        text = shortcut.read_text()
        assert flag in text and binary in text
        assert ('"%~dp0' + binary + '"') in text if windows else ('"./' + binary + '"') in text
        # Target format and host filesystem are independent: Windows can generate
        # these POSIX scripts, but cannot represent their Unix executable bits.
        if not windows and os.name == 'posix':
            assert shortcut.stat().st_mode & 0o111


@pytest.mark.parametrize('tag',['v0.1.4','v0.1.4-beta.1'])
def test_unified_release_requires_signed_android_and_matching_manifests(tmp_path, monkeypatch,tag):
    from scripts.android_publish import SIGNING_CERTIFICATE
    monkeypatch.setattr(desktop_release, '__version__', '0.1.4')
    monkeypatch.setenv('RELEASE_TAG',tag)
    monkeypatch.setattr(desktop_release.subprocess, 'check_output', lambda *a, **kw: 'a' * 40)
    monkeypatch.setattr(sys, 'argv', ['release', 'checksums', str(tmp_path), '--include-android'])
    for platform, extension in [('Windows-x64', '.zip'), ('Linux-x64', '.tar.gz'),
                                ('macOS-arm64-UNTESTED', '.zip'), ('macOS-x64-UNTESTED', '.zip')]:
        (tmp_path / ('AnimeLab-'+tag+'-' + platform + extension)).write_bytes(b'archive')
        manifest = 'AnimeLab-'+tag+'-' + platform.removesuffix('-UNTESTED') + '-build-info.json'
        (tmp_path / manifest).write_text(json.dumps(dict(version='0.1.4', commit='a' * 40)))
    with pytest.raises(RuntimeError, match='incomplete'):
        desktop_release.checksums()
    apk = tmp_path / ('AnimeLab-'+tag+'-Android-arm64.apk')
    apk.write_bytes(b'signed apk')
    info = dict(version='0.1.4', commit='a' * 40, release_tag=tag, validation_key_only=False,
                experimental_apk_runtime_enabled=True,
                signing_certificate_sha256=SIGNING_CERTIFICATE, emulator_api_levels_tested=[29, 30, 35])
    manifest = tmp_path / 'Android-build-info.json'
    manifest.write_text(json.dumps(info))
    desktop_release.checksums()
    assert len((tmp_path / 'SHA256SUMS.txt').read_text().splitlines()) == 10
    if '-beta.' in tag:
        info['experimental_apk_runtime_enabled']=False
        manifest.write_text(json.dumps(info))
        with pytest.raises(RuntimeError,match='experimental APK runtime'):
            desktop_release.checksums()
        info['experimental_apk_runtime_enabled']=True
    info['commit'] = 'b' * 40
    manifest.write_text(json.dumps(info))
    with pytest.raises(RuntimeError, match='source version and commit'):
        desktop_release.checksums()
    info['commit'] = 'a' * 40
    info['validation_key_only'] = True
    manifest.write_text(json.dumps(info))
    with pytest.raises(RuntimeError, match='production signing'):
        desktop_release.checksums()
    (tmp_path / 'AnimeLab-instrumentation.apk').write_bytes(b'never public')
    with pytest.raises(RuntimeError, match='unexpected'):
        desktop_release.checksums()


def test_unified_workflow_keeps_android_tests_before_publication():
    import yaml
    workflow = yaml.safe_load((desktop_release.ROOT / '.github/workflows/release-android.yml').read_text())
    jobs = workflow['jobs']
    assert jobs['prepare-release']['needs'] == ['build', 'device-tests']
    assert jobs['device-tests']['strategy']['matrix']['api'] == [29, 30, 35]
    publisher = yaml.safe_load((desktop_release.ROOT / '.github/workflows/release-desktop.yml').read_text())['jobs']
    assert publisher['android']['uses'] == './.github/workflows/release-android.yml'
    assert publisher['android']['with']['publish'] is False
    assert any('--include-android' in step.get('run', '') for step in publisher['publish']['steps'])
    build=next(step['run'] for step in jobs['build']['steps'] if step.get('name')=='Build installed test target and APK')
    assert ':app:assembleRelease :app:assembleReleaseAndroidTest' in build
    assert ':app:assembleValidation :app:assembleValidationAndroidTest' in build
