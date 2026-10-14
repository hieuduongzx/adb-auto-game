"""runner_update.apply refuses bad packages and never leaves a half update."""
import os
import zipfile
from unittest import mock

import pytest

from src import runner_update as RU

INFO = {"repo": "owner/game", "appName": "Game", "version": "1.0.0", "folder": "Game"}


def _zip(path, members):
    with zipfile.ZipFile(path, "w") as zf:
        for name, data in members.items():
            zf.writestr(name, data)


def test_unsafe_member_is_refused(tmp_path):
    z = tmp_path / "u.zip"
    _zip(z, {"ok.txt": "x", "../escape.txt": "y"})
    with pytest.raises(RuntimeError, match="Unsafe path"):
        RU._safe_extract(str(z), str(tmp_path / "out"))
    assert not (tmp_path / "escape.txt").exists()


@pytest.fixture
def staged(monkeypatch, tmp_path):
    temps = []
    real_mkdtemp = RU.tempfile.mkdtemp

    def mkdtemp(prefix=""):
        path = real_mkdtemp(prefix=prefix, dir=str(tmp_path))
        temps.append(path)
        return path
    monkeypatch.setattr(RU.tempfile, "mkdtemp", mkdtemp)
    monkeypatch.setattr(RU, "updates_supported", lambda info: True)
    monkeypatch.setattr(RU, "check", lambda info: {"available": True, "url": "https://x/u.zip",
                                                   "version": "1.0.1"})
    return temps


def test_package_without_the_runner_exe_fails_cleanly(monkeypatch, staged):
    monkeypatch.setattr(RU, "download", lambda url, dest, cb=None: _zip(dest, {"readme.txt": "x"}))
    exit_ = mock.Mock()
    monkeypatch.setattr(RU.os, "_exit", exit_)
    out = RU.apply(INFO)
    assert out["applied"] is False and "Game-Runner.exe" in out["error"]
    exit_.assert_not_called()
    assert all(not os.path.exists(p) for p in staged)       # temp folder removed


def test_corrupt_download_reports_and_cleans_up(monkeypatch, staged):
    def broken(url, dest, cb=None):
        with open(dest, "wb") as fh:
            fh.write(b"PK\x03\x04 truncated")
    monkeypatch.setattr(RU, "download", broken)
    out = RU.apply(INFO)
    assert out["applied"] is False and out["error"]
    assert all(not os.path.exists(p) for p in staged)


def test_up_to_date_and_check_errors_do_not_download(monkeypatch):
    monkeypatch.setattr(RU, "updates_supported", lambda info: True)
    dl = mock.Mock()
    monkeypatch.setattr(RU, "download", dl)
    monkeypatch.setattr(RU, "check", lambda info: {"available": False})
    assert RU.apply(INFO) == {"applied": False, "error": None, "upToDate": True}
    monkeypatch.setattr(RU, "check", lambda info: {"error": "rate limited"})
    assert RU.apply(INFO)["error"] == "rate limited"
    dl.assert_not_called()


def test_no_update_source_is_refused():
    assert RU.apply({"appName": "Game"})["error"] == "This Runner has no update source"
