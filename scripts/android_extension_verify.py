"""Run opt-in extension tests on an already installed, isolated CI build.

No builds, downloads, package removals or production-app changes. APK identities
are checked before granting the dedicated test app its install permission.
"""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import uuid
import zipfile

PACKAGE = 'com.animan.app.a11test'
FIXTURE = 'eu.kanade.tachiyomi.animeextension.all.animelabfixture.api17'


def apk_file(root: Path, name: str) -> Path:
    matches = list(root.rglob(name))
    if len(matches) != 1:
        raise ValueError('Expected exactly one ' + name)
    return matches[0]


def validate(args: argparse.Namespace) -> None:
    def adb(*command: str, timeout: int = 30, missing: bool = False) -> str:
        result = subprocess.run(['adb', *(['-s', args.device] if args.device else []), *command],
                                capture_output=True, text=True, timeout=timeout)
        if result.returncode and not missing:
            # ADB errors and TimeoutExpired command arguments can contain device identifiers.
            raise RuntimeError('Android command failed; device details withheld')
        return result.stdout.strip()

    for pkg, name in ((PACKAGE, 'app-validation.apk'), (PACKAGE + '.test', 'app-validation-androidTest.apk')):
        expected = hashlib.sha256(apk_file(args.artifacts, name).read_bytes()).hexdigest()
        installed = adb('shell', 'pm', 'path', pkg, missing=True)
        if not installed.startswith('package:'):
            raise ValueError('Install the isolated CI application and its test APK first')
        actual = adb('shell', 'sha256sum', installed.partition(':')[2]).split()[0]
        if actual != expected:
            raise ValueError('Installed test APK differs from the supplied CI artifact')

    command = ['shell', 'am', 'instrument', '-w', '-r']
    if args.community_package:
        if len(args.community_package) > 3 or any(not re.fullmatch(
                r'eu\.kanade\.tachiyomi\.animeextension\.[a-z0-9_.]+', pkg) or
                'animelabfixture' in pkg for pkg in args.community_package):
            raise ValueError('Select at most three installed community extension packages')
        command += ['-e', 'community_packages', ','.join(args.community_package)]
        method = 'selected_community_apks_through_embedded_python_and_network'
        key = 'communityAPKOperations'
        expected_fixture = None
    else:
        if adb('shell', 'pm', 'path', FIXTURE, missing=True).startswith('package:'):
            raise ValueError('Fresh installation requires the controlled API17 fixture to be absent; nothing was removed')
        with zipfile.ZipFile(apk_file(args.artifacts, 'app-validation-androidTest.apk')) as archive:
            expected_fixture = hashlib.sha256(archive.read('assets/extension-fixture-api17-debug.apk')).hexdigest()
        # This AppOp must be set before instrumentation: changing it can kill Android 11 tests.
        adb('shell', 'appops', 'set', PACKAGE, 'REQUEST_INSTALL_PACKAGES', 'allow')
        command += ['-e', 'install_native_fixture', 'true']
        method = 'original_apk_through_python_and_optimized_application'
        key = 'packageInstallerViaPythonAPI'
    run_id = uuid.uuid4().hex
    command += ['-e', 'probe_run_id', run_id, '-e', 'class', 'com.animan.app.NativeExtensionIntegrationTest#' + method,
                PACKAGE + '.test/androidx.test.runner.AndroidJUnitRunner']
    report = adb(*command, timeout=960)
    args.output.mkdir(parents=True, exist_ok=True)
    (args.output / 'instrumentation.txt').write_text(report)
    # A busy phone can produce >1000 unrelated log lines before this read.
    # Filter every retained buffer and bind evidence to this exact invocation.
    logs = adb('logcat', '-d', '-b', 'all', '-s', 'ANIMELAB_APK_PROOF:I', '*:S')
    proofs = []
    for line in logs.splitlines():
        if 'ANIMELAB_APK_PROOF' not in line or '{' not in line:
            continue
        try:
            value = json.loads(line[line.index('{'):])
        except ValueError:
            continue
        if key not in value or value.get('probeRunId') != run_id:
            continue
        if expected_fixture and (value.get('artifactSha256') != expected_fixture or value[key] is not True):
            continue
        if args.community_package and {case['pkg'] for case in value[key]} != set(args.community_package):
            continue
        proofs.append(value)
    passed = bool(re.search(r'OK \(1 test\)', report)) and 'FAILURES' not in report and bool(proofs)
    if proofs:
        proofs[-1]['instrumentationPassed'] = passed
        (args.output / 'proof.json').write_text(json.dumps(proofs[-1], ensure_ascii=False, indent=2) + '\n')
    summary: dict[str, bool | int] = {'instrumentationPassed': passed, 'proofRecorded': bool(proofs)}
    if args.community_package and proofs:
        cases = proofs[-1].get('communityAPKOperations', [])
        summary.update(metadataPathsPassed=sum(case['state'] == 'metadata_path_passed' for case in cases),
                       casesRequiringVerification=sum(case['state'] != 'metadata_path_passed' for case in cases))
    elif proofs:
        summary['packageInstallerViaPythonAPI'] = proofs[-1].get('packageInstallerViaPythonAPI', False)
    print(json.dumps(summary))
    if not passed:
        raise RuntimeError('Device validation failed; inspect the local instrumentation report and partial proof')


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('artifacts', type=Path)
    parser.add_argument('--device', help='Optional ADB target; never written to reports')
    parser.add_argument('--community-package', action='append', default=[])
    parser.add_argument('--output', type=Path, default=Path('artifacts/extension-device'))
    try:
        validate(parser.parse_args())
    except (ValueError, RuntimeError) as error:
        parser.exit(1, str(error) + '\n')
    except (OSError, subprocess.SubprocessError):
        parser.exit(1, 'Extension device validation did not complete; check the selected artifacts, device and local report.\n')
