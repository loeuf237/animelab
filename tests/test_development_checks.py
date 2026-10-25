"""Regression coverage for running checks without a personal library."""
import json
import subprocess
import sys
from pathlib import Path

from scripts import check


def test_backend_check_environment_does_not_inherit_personal_settings(tmp_path, monkeypatch):
    monkeypatch.setenv("ANIMAN_DB_PATH", "/personal/library.sqlite3")
    monkeypatch.setenv("ANIMAN_PROXIES", "http://personal-proxy.invalid:8080")
    monkeypatch.setenv("TMDB_API_KEY", "personal-secret")
    env = check.test_environment(tmp_path)
    code = """
import json
from pathlib import Path
import tempfile
from animelab.config import settings, DEFAULT_DB_DIR
print(json.dumps({"database": settings.DATABASE_PATH, "downloads": settings.DOWNLOAD_DIR,
                  "cache": str(settings.CACHE_DIR), "home": str(Path.home()),
                  "defaultDb": str(DEFAULT_DB_DIR), "scratch": tempfile.gettempdir(),
                  "proxy": settings.PROXIES_CONFIG,
                  "key": settings.TMDB_API_KEY}))
"""
    result = subprocess.run([sys.executable, "-c", code], cwd=check.ROOT,
                            env=env, capture_output=True, text=True, check=True)
    values = json.loads(result.stdout)
    for field in ("database", "downloads", "cache", "home", "defaultDb", "scratch"):
        assert str(tmp_path) in values[field]
    assert not Path(values["home"]).is_relative_to(values["scratch"])
    assert values["proxy"] == values["key"] == ""
    assert env["ANIMAN_STARTUP_REFRESH"] == "false"
