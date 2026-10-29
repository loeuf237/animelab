"""The physical-test driver must leave unknown packages and APKs untouched."""
from argparse import Namespace
import hashlib
from types import SimpleNamespace

import pytest

from scripts import android_extension_verify as driver


@pytest.fixture
def device(tmp_path, monkeypatch):
    calls = []
    for name in ('app-validation.apk', 'app-validation-androidTest.apk'):
        (tmp_path / name).write_bytes(b'controlled CI output')
    digest = hashlib.sha256(b'controlled CI output').hexdigest()

    def run(command, **kwargs):
        calls.append(command)
        if command[1:4] == ['shell', 'pm', 'path']:
            return SimpleNamespace(returncode=0, stdout='package:/controlled/base.apk')
        if command[1:3] == ['shell', 'sha256sum']:
            return SimpleNamespace(returncode=0, stdout=digest + ' /controlled/base.apk')
        pytest.fail('Unexpected device mutation')

    monkeypatch.setattr(driver.subprocess, 'run', run)
    args = Namespace(artifacts=tmp_path, output=tmp_path / 'proof', device=None, community_package=[])
    return args, calls, run


def test_existing_fixture_is_not_silently_uninstalled(device):
    args, calls, _ = device
    with pytest.raises(ValueError, match='nothing was removed'):
        driver.validate(args)
    assert all('uninstall' not in call and 'appops' not in call for call in calls)


def test_installed_app_must_match_the_selected_ci_artifact(device, monkeypatch):
    args, calls, run = device

    def changed(command, **kwargs):
        if 'sha256sum' in command:
            return SimpleNamespace(returncode=0, stdout='0' * 64 + ' /controlled/base.apk')
        return run(command, **kwargs)

    monkeypatch.setattr(driver.subprocess, 'run', changed)
    with pytest.raises(ValueError, match='differs'):
        driver.validate(args)
    assert all('appops' not in call for call in calls)


def test_community_corpus_cannot_target_an_arbitrary_android_app(device):
    args, calls, _ = device
    args.community_package = ['unrelated.application']
    with pytest.raises(ValueError, match='community extension'):
        driver.validate(args)
    assert all('instrument' not in call and 'appops' not in call for call in calls)
