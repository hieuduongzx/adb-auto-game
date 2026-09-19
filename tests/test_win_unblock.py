"""Tests for the Mark-of-the-Web strip in the frozen bundle (src/utils).

A build downloaded as a .zip keeps Windows' ``Zone.Identifier`` on its files,
and the .NET Framework refuses to load a marked assembly — Python.NET then dies
with ``Failed to resolve Python.Runtime.Loader.Initialize``, which is how a
released Runner fails on every machine except the one that built it. These
tests cover the strip itself: which files it clears, that it leaves the file
contents alone, and that it is a no-op for an unmarked folder.

The full failure is reproducible by hand (Windows, dev venv)::

    Set-Content -Path .venv/Lib/site-packages/pythonnet/runtime/Python.Runtime.dll `
                 -Stream Zone.Identifier -Value "[ZoneTransfer]`r`nZoneId=3"
    python -c "import clr"     # -> Failed to resolve Python.Runtime.Loader...
    # then unblock_bundled_files([...]) clearing it fixes the import again

Stdlib only (``unittest``), matching the run command in the README:

    python -m unittest discover -s tests -v
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import unblock_bundled_files  # noqa: E402

_ZONE = "[ZoneTransfer]\r\nZoneId=3\r\nHostUrl=https://example.test/x.zip\r\n"


def _has_mark(path: str) -> bool:
    """True when ``path`` carries a Zone.Identifier stream."""
    return os.path.exists(f"{path}:Zone.Identifier")


def _mark(path: str) -> None:
    """Give ``path`` the Mark-of-the-Web, as extracting a downloaded .zip does."""
    with open(f"{path}:Zone.Identifier", "w", encoding="ascii") as fh:
        fh.write(_ZONE)


@unittest.skipUnless(sys.platform == "win32", "alternate data streams are NTFS/Windows only")
class _Bundle(unittest.TestCase):
    """A temp stand-in for an extracted build: two marked DLLs, one clean file."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="m2k_motw_")
        self.addCleanup(self._rmtree)
        self.marked = [self.write("_internal/pythonnet/runtime/Python.Runtime.dll", b"dll-bytes"),
                       self.write("_internal/webview/lib/Microsoft.Web.WebView2.Core.dll", b"wv2-bytes")]
        self.clean = self.write("_internal/web/shared/app.css", b"body{}")
        for path in self.marked:
            _mark(path)
        if not _has_mark(self.marked[0]):
            self.skipTest("temp volume does not support alternate data streams")

    def _rmtree(self):
        # A marked file cannot be removed recursively until its stream is gone.
        for dirpath, _dirs, names in os.walk(self.root):
            for name in names:
                try:
                    os.remove(f"{os.path.join(dirpath, name)}:Zone.Identifier")
                except OSError:
                    pass
        import shutil
        shutil.rmtree(self.root, True)

    def write(self, rel: str, data: bytes) -> str:
        path = os.path.join(self.root, *rel.split("/"))
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "wb") as fh:
            fh.write(data)
        return path

    def test_clears_the_mark_and_keeps_the_bytes(self):
        self.assertEqual(unblock_bundled_files([self.root]), 2)
        for path in self.marked:
            self.assertFalse(_has_mark(path), f"{path} is still marked")
        # The strip must delete the stream, never the file.
        self.assertEqual(Path(self.marked[0]).read_bytes(), b"dll-bytes")
        self.assertTrue(os.path.isfile(self.clean))

    def test_second_pass_finds_nothing_left(self):
        unblock_bundled_files([self.root])
        self.assertEqual(unblock_bundled_files([self.root]), 0)

    def test_unmarked_folder_is_left_alone(self):
        root = tempfile.mkdtemp(prefix="m2k_motw_clean_")
        self.addCleanup(self._rmtree_root_only, root)
        path = os.path.join(root, "app.dll")
        with open(path, "wb") as fh:
            fh.write(b"x")
        self.assertEqual(unblock_bundled_files([root]), 0)
        self.assertEqual(Path(path).read_bytes(), b"x")

    def _rmtree_root_only(self, root):
        import shutil
        shutil.rmtree(root, True)

    def test_no_roots_is_a_noop(self):
        # Source runs / an unfrozen interpreter own no bundle: nothing to do,
        # and no exception either way.
        self.assertEqual(unblock_bundled_files([]), 0)


if __name__ == "__main__":
    unittest.main()
