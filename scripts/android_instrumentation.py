"""Install the APK under test and require a successful instrumentation report."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
import time
import uuid


def validate(app, tests, output, skip_native_media=False, package="com.animan.app", require_hardsub=False):
    output.mkdir(parents=True, exist_ok=True)
    is_engine = package == "com.animan.app" or package.startswith("com.animan.app.")
    for apk in (app, tests):
        subprocess.run(["adb", "install", "-r", str(apk)], check=True, timeout=90)
    api = int(subprocess.check_output(["adb", "shell", "getprop", "ro.build.version.sdk"], text=True).strip())
    if api >= 33:
        if is_engine:
            subprocess.run(["adb", "shell", "pm", "grant", package, "android.permission.POST_NOTIFICATIONS"], check=True, timeout=15)
    # Installing a large APK can outlast the phone's screen timeout. Wake only
    # for the test; Android still requires normal authentication on a secure lock.
    subprocess.run(["adb", "shell", "input", "keyevent", "KEYCODE_WAKEUP"], check=True, timeout=15)
    subprocess.run(["adb", "shell", "wm", "dismiss-keyguard"], check=True, timeout=15)
    time.sleep(2)
    command = ["adb", "shell", "am", "instrument", "-w", "-r"]
    probe_id=uuid.uuid4().hex if package=='com.animan.nativeprobe' else None
    if probe_id:
        command += ['-e','probe_run_id',probe_id]
    if is_engine:
        # Physical original-APK tests require a separate validation package and
        # explicit fixture arguments. They are not production-package smoke tests.
        command += ["-e", "class", "com.animan.app.EmbeddedEngineTest"]
    if skip_native_media: command += ["-e", "skip_native_media", "true"]
    command += [package + ".test/androidx.test.runner.AndroidJUnitRunner"]
    result = subprocess.run(command,
                            capture_output=True, text=True, timeout=480)
    report = result.stdout + result.stderr
    (output / "instrumentation.txt").write_text(report)
    pid = subprocess.run(["adb", "shell", "pidof", package], capture_output=True, text=True, timeout=15)
    target_pids = pid.stdout.split()
    if probe_id:
        logs=subprocess.run(['adb','logcat','-d','-b','all','-s','ANIMAN_MEDIA_PROOF:I'],
            capture_output=True,text=True,timeout=30)
        fresh='\n'.join(line for line in logs.stdout.splitlines() if probe_id in line)
        (output/'logcat.txt').write_text(fresh+'\n')
    elif target_pids and target_pids[0].isdigit():
        logs = subprocess.run(["adb", "logcat", "-d", "--pid=" + target_pids[0]],
                              capture_output=True, text=True, timeout=30)
        (output / "logcat.txt").write_text(logs.stdout)
    else:
        (output / "logcat.txt").write_text("Target process exited; see instrumentation.txt.\n")
    if is_engine:
        subprocess.run(["adb", "pull", f"/sdcard/Android/data/{package}/files/screen.png", str(output / "screen.png")], timeout=15)
        subprocess.run(["adb", "pull", f"/sdcard/Android/data/{package}/files/footprint.json",
                        str(output / "footprint.json")], timeout=15)
    print(report)
    if result.returncode or not re.search(r"OK \(1 test\)", report) or "FAILURES" in report or "INSTRUMENTATION_FAILED" in report:
        raise RuntimeError("The installed Android engine did not pass instrumentation")
    if require_hardsub or probe_id:
        validate_hardsub_report(report + '\n' + (output / 'logcat.txt').read_text(), output, api,expected_probe_id=probe_id)
    if is_engine:
        footprint_path = output / "footprint.json"
        footprint = json.loads(footprint_path.read_text())
        if footprint["apk_bytes"] != app.stat().st_size:
            raise RuntimeError("Installed footprint does not match the APK under test")
        with app.open("rb") as source:
            footprint["apk_sha256"] = hashlib.file_digest(source, "sha256").hexdigest()
        footprint["package"] = package
        footprint_path.write_text(json.dumps(footprint, indent=2) + "\n")


def validate_hardsub_report(text, output, api, *, expected_probe_id=None):
    matches = re.findall(r'ANIMAN_NATIVE_MEDIA_PROBE=(\{[^\r\n]*\})', text)
    if not matches:
        raise RuntimeError('Missing JNI hardsub evidence')
    values=[json.loads(match) for match in matches]
    if expected_probe_id:
        values=[value for value in values if value.get('probeRunId')==expected_probe_id]
    if not values:
        raise RuntimeError('Missing fresh JNI hardsub evidence')
    value = values[-1]
    proof = value.get('hardsub', {})
    if not (proof.get('available') is True and proof.get('renderVerified') is True and
            proof.get('pixelDifference', 0) > 10000 and proof.get('api') == api and
            proof.get('pageSize') in (4096, 16384) and value.get('managed_cancellation') is True and
            value.get('managed_progress') is True and
            value.get('storage_export') is True):
        raise RuntimeError('Incomplete JNI hardsub rendering, cancellation or export evidence')
    (output / 'hardsub-proof.json').write_text(json.dumps(value, indent=2) + '\n')


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("app", type=Path)
    parser.add_argument("tests", type=Path)
    parser.add_argument("output", type=Path)
    parser.add_argument("--skip-native-media", action="store_true")
    parser.add_argument("--package", default="com.animan.app")
    parser.add_argument("--require-hardsub", action="store_true")
    args = parser.parse_args()
    validate(args.app, args.tests, args.output, args.skip_native_media, args.package, args.require_hardsub)
