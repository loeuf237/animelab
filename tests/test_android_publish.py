import hashlib
import json
from pathlib import Path
import pytest
from scripts import android_publish


def checksums(folder):
    (folder / 'SHA256SUMS.txt').write_text(''.join(
        hashlib.sha256(p.read_bytes()).hexdigest() + '  ' + p.name + '\n'
        for p in sorted(folder.iterdir()) if p.name != 'SHA256SUMS.txt'))


@pytest.fixture
def candidate(tmp_path, monkeypatch):
    source = tmp_path / 'signed'
    source.mkdir()
    for name in ['AnimeLab-Android-under-test.apk', 'AnimeLab-instrumentation.apk']:
        (source / name).write_bytes(b'signed fixture')
    info = dict(commit='a' * 40, version='0.1.0', version_code=214,
                validation_key_only=False, signing_certificate_sha256=android_publish.SIGNING_CERTIFICATE)
    (source / 'Android-build-info.json').write_text(json.dumps(info))
    checksums(source)
    monkeypatch.setattr(android_publish, 'inspect_apk', lambda *args, **kwargs: {})
    def output(arguments, **kwargs):
        if 'badging' in arguments:
            return "package: name='com.animan.app' versionCode='214' versionName='0.1.0'\napplication-label:'AnimeLab'\n"
        return 'Signer #1 certificate SHA-256 digest: ' + android_publish.SIGNING_CERTIFICATE
    monkeypatch.setattr(android_publish.subprocess, 'check_output', output)
    monkeypatch.setattr(android_publish.subprocess, 'run', lambda *args, **kwargs: None)
    return source, tmp_path / 'release'


def prepare(candidate, **overrides):
    source, output = candidate
    arguments = dict(tag='android-v0.1.0-beta.2', source_commit='a' * 40,
                     candidate_run_id=123, signed_run_id=456)
    arguments.update(overrides)
    return android_publish.prepare(source, output, Path('/sdk/tools'), **arguments)


def test_release_preserves_exact_signed_bytes_and_verifiable_checksums(candidate):
    result = prepare(candidate)
    source, output = candidate
    assert (output / result['apk']).read_bytes() == (source / 'AnimeLab-Android-under-test.apk').read_bytes()
    for line in (output / 'SHA256SUMS.txt').read_text().splitlines():
        digest, name = line.split('  ', 1)
        assert hashlib.sha256((output / name).read_bytes()).hexdigest() == digest
    info = json.loads((output / 'Android-build-info.json').read_text())
    assert not info['physical_device_tested'] and not info['signing_private_key_uploaded']
    assert info['candidate_actions_run_id'] == 123


def test_release_rejects_changed_artifact(candidate):
    (candidate[0] / 'AnimeLab-Android-under-test.apk').write_bytes(b'changed')
    with pytest.raises(ValueError, match='checksum'):
        prepare(candidate)


def test_github_signing_records_actual_key_location_and_run(candidate):
    prepare(candidate, signing_method='github_actions')
    info = json.loads((candidate[1] / 'Android-build-info.json').read_text())
    assert info['signing_private_key_uploaded'] is True
    assert info['signing_method'] == 'github_actions'
    assert info['signing_actions_run_id'] == 123
    assert 'signed_assembly_actions_run_id' not in info


def test_unknown_signing_method_is_rejected(candidate):
    with pytest.raises(ValueError, match='signing method'):
        prepare(candidate, signing_method='unknown')


def test_release_rejects_different_source_commit(candidate):
    with pytest.raises(ValueError, match='commit'):
        prepare(candidate, source_commit='b' * 40)


def test_release_rejects_wrong_version_tag(candidate):
    with pytest.raises(ValueError, match='tag'):
        prepare(candidate, tag='android-v0.2.0-beta.2')


def test_release_rejects_validation_identity(candidate):
    source, _ = candidate
    info = json.loads((source / 'Android-build-info.json').read_text())
    info['validation_key_only'] = True
    (source / 'Android-build-info.json').write_text(json.dumps(info))
    checksums(source)
    with pytest.raises(ValueError, match='production signing'):
        prepare(candidate)


def test_release_checks_actual_apk_certificate(candidate, monkeypatch):
    monkeypatch.setattr(android_publish.subprocess, 'check_output', lambda *a, **kw: 'certificate SHA-256 digest: ' + 'b' * 64)
    with pytest.raises(ValueError, match='certificate differs'):
        prepare(candidate)


def test_unified_release_accepts_matching_common_tag(candidate):
    result = prepare(candidate, tag='v0.1.0', signing_method='github_actions')
    assert result['tag'] == 'v0.1.0'
    assert result['apk'] == 'AnimeLab-v0.1.0-Android-arm64.apk'


@pytest.mark.parametrize('tag',['v0.1.0-beta.1','android-v0.1.0-beta.2'])
def test_beta_filename_retains_the_public_channel_marker(candidate,tag):
    result=prepare(candidate,tag=tag,signing_method='github_actions')
    assert result['apk']=='AnimeLab-'+tag.removeprefix('android-')+'-Android-arm64.apk'
