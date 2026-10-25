"""A11: packaging must preserve runtime bytes, upstream inputs and public URLs."""
import hashlib
import json
import os
from pathlib import Path
import shutil
import subprocess
from zipfile import ZIP_DEFLATED, ZipFile

import pytest

from scripts.android_optimize import deduplicate_sources, optimize_requirements, runtime_layout


def test_dedup_only_removes_identical_public_copies(tmp_path):
    paths = {
        "frontend/dist/img/logo.png": b"same",
        "animelab/static/img/logo.png": b"same",
        "frontend/dist/img/custom.png": b"custom",
        "frontend/dist/img/changed.png": b"new",
        "animelab/static/img/changed.png": b"old",
        "frontend/dist/manifest.json": b"{}",
        "animelab/static/manifest.json": b"{}",
        "frontend/dist/assets/player.js": b"same",
        "frontend/dist/index.html": b"same",
    }
    for name, content in paths.items():
        target = tmp_path / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(content)
    removed = deduplicate_sources(tmp_path)
    assert sorted(removed) == ["frontend/dist/img/logo.png", "frontend/dist/manifest.json"]
    for name, content in paths.items():
        if name not in removed:
            assert (tmp_path / name).read_bytes() == content
    assert deduplicate_sources(tmp_path) == []


@pytest.fixture
def native_archive(tmp_path):
    compiler = shutil.which("cc")
    strip = os.environ.get("ANIMAN_LLVM_STRIP") or shutil.which("llvm-strip")
    if not compiler or not strip:
        pytest.skip("C compiler and LLVM strip needed for binary preservation regression")
    source = tmp_path / "source.c"
    source.write_text("int exposed_function(int x) { return x + 42; }\n")
    library = tmp_path / "libtest.so"
    subprocess.run([compiler, "-g", "-shared", "-fPIC", str(source), "-o", str(library)], check=True)
    raw = library.read_bytes()
    root = tmp_path / "requirements"
    root.mkdir()
    archive = root / "requirements-common.imy"
    with ZipFile(archive, "w", compression=ZIP_DEFLATED) as package:
        package.writestr("package/libtest.so", raw)
        package.writestr("package-1.dist-info/LICENSE", "license text")
        package.writestr("package/__init__.pyc", b"bytecode")
    return root, archive, raw, strip


def test_strip_preserves_loadable_bytes_and_keeps_originals(native_archive, tmp_path):
    root, archive, raw, strip = native_archive
    output = tmp_path / "audit"
    before = archive.stat().st_size
    report = optimize_requirements(root, output, strip)
    assert archive.stat().st_size < before
    with ZipFile(archive) as package:
        actual = package.read("package/libtest.so")
        assert runtime_layout(actual) == runtime_layout(raw)
        assert package.read("package-1.dist-info/LICENSE") == b"license text"
        assert package.read("package/__init__.pyc") == b"bytecode"
    record = report["libraries"][0]
    assert (output / record["original_file"]).read_bytes() == raw
    assert record["optimized_sha256"] == hashlib.sha256(actual).hexdigest()
    assert json.loads((output / "native-optimization.json").read_text()) == report
    # The regression fixture also runs on the build host, exercising dynamic symbols.
    import ctypes
    target = tmp_path / "stripped.so"
    target.write_bytes(actual)
    assert ctypes.CDLL(str(target)).exposed_function(3) == 45


def test_corrupt_strip_output_never_replaces_archive(native_archive, tmp_path, monkeypatch):
    root, archive, raw, strip = native_archive
    original = archive.read_bytes()
    real_run = subprocess.run
    def corrupt(command, **kwargs):
        result = real_run(command, **kwargs)
        if "--strip-unneeded" in command:
            target = Path(command[-1])
            data = bytearray(target.read_bytes())
            # Change the first program header rather than just unused symbols.
            data[64] ^= 1
            target.write_bytes(data)
        return result
    monkeypatch.setattr(subprocess, "run", corrupt)
    with pytest.raises(ValueError, match="runtime ELF"):
        optimize_requirements(root, tmp_path / "audit", strip)
    assert archive.read_bytes() == original
