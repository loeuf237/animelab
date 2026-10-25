"""Regression for native libraries which align correctly but cannot load."""
import struct
import zipfile
import json
import hashlib

import pytest
from scripts.android_release import inspect_apk


def apk_fixture(tmp_path, *, mapped_end, alignment=16384, relro_size=0x1000):
    elf = bytearray(64 + 2 * 56)
    elf[:6] = b'\x7fELF\x02\x01'
    struct.pack_into('<H', elf, 18, 183)
    struct.pack_into('<Q', elf, 32, 64)
    struct.pack_into('<HH', elf, 54, 56, 2)
    for index, (kind, address, size, align) in enumerate([(1, 0, mapped_end, alignment), (0x6474E552, 0x4000, relro_size, 1)]):
        struct.pack_into('<IIQQQQQQ', elf, 64 + index * 56, kind, 0, 0, address, 0, size, size, align)
    apk = tmp_path / 'candidate.apk'
    with zipfile.ZipFile(apk, 'w') as archive:
        for marker in ['frontend/dist/index.html', 'android_runtime.py', 'animelab/services/download_manager.py',
                       'curl_cffi/_wrapper.py', 'pydantic_core/_pydantic_core.py']:
            archive.writestr(marker, '')
        archive.writestr('lib/arm64-v8a/libffmpegkit.so', elf)
    return apk


def test_rejects_aligned_library_with_unmapped_relro(tmp_path):
    with pytest.raises(ValueError, match='RELRO exceeds'):
        inspect_apk(apk_fixture(tmp_path, mapped_end=0x5000, relro_size=0x4000))


def test_accepts_padded_relro_mapping(tmp_path):
    assert inspect_apk(apk_fixture(tmp_path, mapped_end=0x8000))['native_16kb_alignment']


def test_accepts_valid_load_ending_mid_page(tmp_path):
    assert inspect_apk(apk_fixture(tmp_path, mapped_end=0x5000))['native_16kb_alignment']


def test_rejects_old_page_alignment(tmp_path):
    with pytest.raises(ValueError, match='not 16 KB aligned'):
        inspect_apk(apk_fixture(tmp_path, mapped_end=0x8000, alignment=4096))


def test_rejects_archive_changed_after_chaquopy_hashing(tmp_path):
    apk = apk_fixture(tmp_path, mapped_end=0x8000)
    with zipfile.ZipFile(apk, "a") as archive:
        archive.writestr("assets/chaquopy/requirements-common.imy", b"optimized")
        archive.writestr("assets/chaquopy/build.json", json.dumps({
            "assets": {"requirements-common.imy": hashlib.sha1(b"original").hexdigest()}
        }))
    with pytest.raises(ValueError, match="asset hash mismatch"):
        inspect_apk(apk)
