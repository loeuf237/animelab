"""Prepare a signed Android release only after the workflow's device gates pass."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import shutil
import subprocess

try:
    from scripts.android_release import inspect_apk
except ModuleNotFoundError:
    from android_release import inspect_apk

# Public certificate of the existing installation; never the private identity.
SIGNING_CERTIFICATE = 'bdfde1d5b941680c8efb28f8692d894294762a9ad02292805457d5a82a3160b5'


def digest(path):
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def prepare(source, output, tools, tag, source_commit, candidate_run_id, signed_run_id,
            signing_method='local_apksigner'):
    if signing_method not in ('local_apksigner', 'github_actions'):
        raise ValueError('Unknown signing method')
    expected = {'AnimeLab-Android-under-test.apk', 'AnimeLab-instrumentation.apk', 'Android-build-info.json'}
    verified = set()
    for line in (source / 'SHA256SUMS.txt').read_text().splitlines():
        checksum, name = line.split('  ', 1)
        if name not in expected or name in verified or digest(source / name) != checksum:
            raise ValueError('Signed artifact checksum mismatch or unexpected file')
        verified.add(name)
    if verified != expected:
        raise ValueError('Incomplete signed artifact checksums')
    info = json.loads((source / 'Android-build-info.json').read_text())
    if not re.fullmatch(r'[0-9a-f]{40}', source_commit) or info.get('commit') != source_commit:
        raise ValueError('Signed APK does not match the requested build commit')
    if info.get('validation_key_only') is not False or info.get('signing_certificate_sha256') != SIGNING_CERTIFICATE:
        raise ValueError('A production signing identity is required')
    version = info['version']
    if (not re.fullmatch(r'\d+\.\d+\.\d+', version) or
            (tag != 'v' + version and not re.fullmatch(r'(?:android-)?'+re.escape('v' + version) + r'-beta\.[1-9]\d*', tag))):
        raise ValueError('Release tag does not match APK version')
    app = source / 'AnimeLab-Android-under-test.apk'
    inspect_apk(app, require_optimized=True)
    for name in ('AnimeLab-Android-under-test.apk', 'AnimeLab-instrumentation.apk'):
        certificate = subprocess.check_output([str(tools / 'apksigner'), 'verify', '--print-certs', str(source / name)], text=True)
        fingerprints = re.findall(r'certificate SHA-256 digest: ([a-f0-9]+)', certificate)
        if fingerprints != [SIGNING_CERTIFICATE]:
            raise ValueError('APK signing certificate differs from the existing installation')
        subprocess.run([str(tools / 'zipalign'), '-c', '-P', '16', '4', str(source / name)], check=True)
    badging = subprocess.check_output([str(tools / 'aapt2'), 'dump', 'badging', str(app)], text=True)
    package = re.search(r"package: name='([^']+)' versionCode='(\d+)' versionName='([^']+)'", badging)
    if ('application-debuggable' in badging or not package or package.group(1) != 'com.animan.app'
            or int(package.group(2)) != info.get('version_code') or int(package.group(2)) < 214
            or package.group(3) != version or "application-label:'AnimeLab'" not in badging):
        raise ValueError('APK package, version or label is unsuitable for this release')
    output.mkdir(parents=True, exist_ok=False)
    filename = f'AnimeLab-{tag.removeprefix("android-")}-Android-arm64.apk'
    shutil.copyfile(app, output / filename)
    info.update(emulator_api_levels_tested=[29, 30, 35],
                runtime_api_levels_tested=[30, 35], runtime_test_abi='arm64-v8a via Android native translation',
                media_test_abi='x86_64, same Kotlin JNI bridge',
                full_arm64_media_pipeline_tested=False, physical_device_tested=False,
                candidate_actions_run_id=candidate_run_id,
                signing_method=signing_method,
                signing_private_key_uploaded=signing_method == 'github_actions', release_tag=tag)
    if signing_method == 'github_actions':
        info['signing_actions_run_id'] = candidate_run_id
        info.pop('signed_assembly_actions_run_id', None)
    else:
        info['signed_assembly_actions_run_id'] = signed_run_id
    (output / 'Android-build-info.json').write_text(json.dumps(info, indent=2) + '\n')
    (output / 'SHA256SUMS.txt').write_text(''.join(digest(p) + '  ' + p.name + '\n' for p in sorted(output.iterdir())))
    return {'tag': tag, 'commit': source_commit, 'apk': filename, 'size': (output / filename).stat().st_size}


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('source', type=Path)
    parser.add_argument('output', type=Path)
    parser.add_argument('--build-tools', required=True, type=Path)
    parser.add_argument('--tag', required=True)
    parser.add_argument('--source-commit', required=True)
    parser.add_argument('--candidate-run-id', required=True, type=int)
    parser.add_argument('--signed-run-id', default=0, type=int)
    parser.add_argument('--signing-method', choices=['local_apksigner', 'github_actions'], default='local_apksigner')
    args = parser.parse_args()
    print(json.dumps(prepare(args.source, args.output, args.build_tools, args.tag, args.source_commit,
                             args.candidate_run_id, args.signed_run_id, args.signing_method), indent=2))
