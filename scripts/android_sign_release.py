"""Sign release-flag validation APKs locally; never transfer the private key.

The CI validation variant inherits release flags and changes only its signing
identity. Both app and instrumentation APKs are re-signed with the same dedicated
identity, then the signed app must pass the device tests before publication.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]


def signing_identity():
    os.umask(0o077)
    folder = ROOT / 'android/keystore'
    folder.mkdir(mode=0o700, exist_ok=True)
    folder.chmod(0o700)
    config, key = folder / 'local-signing.json', folder / 'animan-release.p12'
    if config.exists():
        values = json.loads(config.read_text())
        if not key.is_file(): raise RuntimeError('Saved identity has no keystore; restore its backup before signing')
        config.chmod(0o600); key.chmod(0o600)
        return key, values
    if key.exists(): raise RuntimeError('Existing keystore has no signing configuration; do not overwrite it')
    password = secrets.token_urlsafe(48)
    values = {'alias': 'animelab', 'store_password': password, 'key_password': password}
    env = {**os.environ, 'ANIMAN_LOCAL_STORE_PASS': password, 'ANIMAN_LOCAL_KEY_PASS': password}
    subprocess.run(['keytool', '-genkeypair', '-noprompt', '-keystore', str(key), '-storetype', 'PKCS12',
                    '-alias', values['alias'], '-keyalg', 'RSA', '-keysize', '3072', '-validity', '10000',
                    '-dname', 'CN=Animan', '-storepass:env', 'ANIMAN_LOCAL_STORE_PASS',
                    '-keypass:env', 'ANIMAN_LOCAL_KEY_PASS'], env=env, check=True, capture_output=True, text=True)
    key.chmod(0o600)
    descriptor = os.open(config, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as stream: json.dump(values, stream)
    return key, values


def sign(source, destination, tools):
    from android_release import inspect_apk
    info = json.loads((source / 'Android-build-info.json').read_text())
    app = source / 'AnimeLab-Android-under-test.apk'
    for line in (source / 'SHA256SUMS.txt').read_text().splitlines():
        expected, name = line.split('  ', 1)
        if Path(name).name != name: raise ValueError('Invalid checksum path')
        assert hashlib.file_digest((source / name).open('rb'), 'sha256').hexdigest() == expected
    inspect_apk(app)
    badging = subprocess.check_output([str(tools / 'aapt2'), 'dump', 'badging', str(app)], text=True)
    if 'application-debuggable' in badging or "name='com.animan.app'" not in badging:
        raise RuntimeError('Release signing requires the non-debuggable AnimeLab package')
    key, values = signing_identity()
    env = {**os.environ, 'ANIMAN_LOCAL_STORE_PASS': values['store_password'], 'ANIMAN_LOCAL_KEY_PASS': values['key_password']}
    destination.mkdir(parents=True, exist_ok=True)
    for name in ['AnimeLab-Android-under-test.apk', 'AnimeLab-instrumentation.apk']:
        subprocess.run([str(tools / 'apksigner'), 'sign', '--ks', str(key), '--ks-key-alias', values['alias'],
                        '--ks-pass', 'env:ANIMAN_LOCAL_STORE_PASS', '--key-pass', 'env:ANIMAN_LOCAL_KEY_PASS',
                        '--out', str(destination / name), str(source / name)], env=env, check=True, capture_output=True, text=True)
        subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(destination / name)], check=True)
    certificate = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--print-certs', str(destination / app.name)], text=True)
    fingerprint = re.search(r'certificate SHA-256 digest: ([a-f0-9]+)', certificate).group(1)
    test_certificate = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--print-certs', str(destination / 'AnimeLab-instrumentation.apk')], text=True)
    if fingerprint not in test_certificate: raise RuntimeError('Instrumentation signing identity differs from the app')
    info.update(validation_key_only=False, signing_method='local_apksigner',
                source_build_variant='validation_with_release_flags', signing_certificate_sha256=fingerprint)
    (destination / 'Android-build-info.json').write_text(json.dumps(info, indent=2))
    (destination / 'SHA256SUMS.txt').write_text(''.join(hashlib.file_digest(p.open('rb'), 'sha256').hexdigest() + '  ' + p.name + '\n'
                                                    for p in sorted(destination.iterdir()) if p.is_file() and p.name != 'SHA256SUMS.txt'))
    print(json.dumps({'directory': str(destination.resolve()), 'source_commit': info['commit'],
                      'signing_certificate_sha256': fingerprint, 'private_key_uploaded': False}, indent=2))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('source', type=Path)
    parser.add_argument('destination', type=Path)
    parser.add_argument('--build-tools', type=Path, required=True)
    args = parser.parse_args()
    sign(args.source, args.destination, args.build_tools)
