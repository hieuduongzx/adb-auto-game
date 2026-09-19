"""Tests for the UTF-8 stdout/stderr guard in ``src/utils``.

A windowed (no-console) frozen build starts with ``sys.stdout``/``stderr`` set to
``None``. If nothing fills them in first, PyWebView's ``webview.http`` module
does — with ``open(os.devnull, 'w')``, which encodes using the machine's **ANSI
code page** (cp1252 on most PCs). Every log line a workflow prints in Vietnamese
then dies with ``'charmap' codec can't encode character``, which is invisible on
the UTF-8 dev machine and breaks on everyone else's. ``_force_utf8_streams()``
must claim the ``None`` case with a UTF-8 sink so PyWebView's substitution can
never happen, and must reconfigure a stream that already exists.

Stdlib only (``unittest``), matching the run command in the README::

    python -m unittest discover -s tests -v
"""
import os
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.utils import _force_utf8_streams, log_info  # noqa: E402


def _utf8(encoding) -> bool:
    return (encoding or "").lower().replace("-", "") == "utf8"


class _Utf8Streams(unittest.TestCase):
    def setUp(self):
        self._saved = (sys.stdout, sys.stderr)
        self.addCleanup(self._restore)

    def _restore(self):
        created = [s for s in (sys.stdout, sys.stderr)
                   if s is not None and s not in self._saved]
        sys.stdout, sys.stderr = self._saved
        for stream in created:
            try:
                stream.close()
            except Exception:
                pass

    def test_none_streams_are_claimed_with_utf8(self):
        # The windowed-frozen case: PyWebView must find them already non-None.
        sys.stdout = sys.stderr = None
        _force_utf8_streams()
        for stream in (sys.stdout, sys.stderr):
            self.assertIsNotNone(stream)
            self.assertTrue(_utf8(stream.encoding), stream.encoding)

    def test_existing_cp1252_stream_is_reconfigured(self):
        # The console / redirected case: reconfigure in place, don't replace.
        stream = open(os.devnull, "w", encoding="cp1252")
        self.addCleanup(stream.close)
        sys.stdout = stream
        sys.stderr = None
        _force_utf8_streams()
        self.assertIs(sys.stdout, stream)
        self.assertTrue(_utf8(stream.encoding), stream.encoding)

    def test_unicode_log_line_never_raises(self):
        # ``ắ`` and ``→`` are outside cp1252 — the exact characters that crashed
        # a released Runner with 'charmap' errors.
        sys.stdout = sys.stderr = None
        _force_utf8_streams()
        log_info("arrow \u2192 viet \u1eaf emoji \U0001F600")


if __name__ == "__main__":
    unittest.main()
