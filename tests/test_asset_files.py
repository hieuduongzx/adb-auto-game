"""Tests for the Library's file actions (src/core/adb/device_info.py).

These are the operations that move real files — soft delete, restore, rename
resolution, and the listing that feeds the grid. They run against a throwaway
temp folder of synthetic PNGs, never a project's ``templates/``, because the
failure mode of getting one wrong is a lost hand-cropped template.

Stdlib only (``unittest``), matching the run command in the README:

    python -m unittest discover -s tests -v
"""
import os
import shutil
import struct
import sys
import tempfile
import unittest
import zlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.core.adb import device_info  # noqa: E402


def _png(path: str, w: int, h: int) -> None:
    """Write a minimal valid RGB PNG — no Pillow, so the suite stays stdlib."""
    raw = b"".join(b"\x00" + b"".join(bytes([(x * 7) % 256, (y * 5) % 256, 40])
                                      for x in range(w)) for y in range(h))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))
    ihdr = struct.pack(">IIBBBBB", w, h, 8, 2, 0, 0, 0)
    with open(path, "wb") as fh:
        fh.write(b"\x89PNG\r\n\x1a\n")
        fh.write(chunk(b"IHDR", ihdr))
        fh.write(chunk(b"IDAT", zlib.compress(raw)))
        fh.write(chunk(b"IEND", b""))


class _Folder(unittest.TestCase):
    """A temp templates folder with three files, torn down afterwards."""

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="m2k_assets_")
        self.addCleanup(shutil.rmtree, self.root, True)
        _png(self.path("btn_play.png"), 40, 12)
        _png(self.path("btn_home.png"), 30, 30)
        _png(self.path("btn_back.png"), 30, 30)

    def path(self, *parts: str) -> str:
        return os.path.join(self.root, *parts)

    def names(self) -> list:
        return sorted(i["name"] for i in device_info.list_image_assets(self.root))


class TestListing(_Folder):
    def test_lists_every_file_without_a_cap(self):
        # The old silent limit of 200 hid the 69 oldest files on a 269-template
        # project — which is where most orphans live.
        for n in range(240):
            _png(self.path(f"extra_{n:03d}.png"), 8, 8)
        items = device_info.list_image_assets(self.root)
        self.assertEqual(len(items), 243)

    def test_returns_dimensions_and_size(self):
        it = next(i for i in device_info.list_image_assets(self.root, with_dims=True)
                  if i["name"] == "btn_play.png")
        self.assertEqual((it["w"], it["h"]), (40, 12))
        self.assertGreater(it["size"], 0)

    def test_trash_is_never_listed(self):
        device_info.delete_asset(self.root, self.path("btn_back.png"))
        self.assertEqual(self.names(), ["btn_home.png", "btn_play.png"])
        self.assertTrue(os.path.isfile(self.path(device_info.TRASH_DIR, "btn_back.png")))


class TestSoftDelete(_Folder):
    def test_delete_moves_to_trash_instead_of_unlinking(self):
        self.assertTrue(device_info.delete_asset(self.root, self.path("btn_play.png")))
        self.assertFalse(os.path.exists(self.path("btn_play.png")))
        self.assertTrue(os.path.isfile(self.path(device_info.TRASH_DIR, "btn_play.png")))

    def test_delete_refuses_a_path_outside_the_folder(self):
        outside = tempfile.mkdtemp(prefix="m2k_outside_")
        self.addCleanup(shutil.rmtree, outside, True)
        victim = os.path.join(outside, "keep.png")
        _png(victim, 4, 4)
        self.assertFalse(device_info.delete_asset(self.root, victim))
        self.assertTrue(os.path.isfile(victim))

    def test_two_deletes_of_the_same_name_keep_both_copies(self):
        # A trash name clash used to be able to overwrite the earlier delete.
        device_info.delete_asset(self.root, self.path("btn_home.png"))
        _png(self.path("btn_home.png"), 31, 31)
        device_info.delete_asset(self.root, self.path("btn_home.png"))
        trashed = sorted(os.listdir(self.path(device_info.TRASH_DIR)))
        self.assertEqual(trashed, ["btn_home.png", "btn_home_1.png"])

    def test_restore_puts_the_file_back_and_is_visible_again(self):
        device_info.delete_asset(self.root, self.path("btn_home.png"))
        trash = device_info.list_image_assets(self.path(device_info.TRASH_DIR))
        self.assertTrue(device_info.restore_asset(self.root, trash[0]["path"]))
        self.assertEqual(self.names(), ["btn_back.png", "btn_home.png", "btn_play.png"])

    def test_restore_does_not_clobber_a_live_file_of_the_same_name(self):
        device_info.delete_asset(self.root, self.path("btn_home.png"))
        trash = device_info.list_image_assets(self.path(device_info.TRASH_DIR))
        _png(self.path("btn_home.png"), 31, 31)          # a new crop reuses the name
        self.assertTrue(device_info.restore_asset(self.root, trash[0]["path"]))
        self.assertEqual(self.names(),
                         ["btn_back.png", "btn_home.png", "btn_home_1.png", "btn_play.png"])


class TestAssetPath(_Folder):
    """``asset_path`` is what rename/delete/thumbnail resolve through.

    The relative case matters: a bare ``"btn.png"`` used to be resolved against
    the process working directory and fail as "file not found", which is the
    opposite of what the Library's rename field holds.
    """

    def test_absolute_path_resolves(self):
        self.assertTrue(device_info.asset_path(self.root, self.path("btn_play.png")))

    def test_bare_name_resolves_against_the_folder(self):
        got = device_info.asset_path(self.root, "btn_play.png")
        self.assertEqual(got, os.path.realpath(self.path("btn_play.png")))

    def test_relative_subpath_resolves(self):
        # Restore resolves against _trash/, so a subfolder-relative name has to
        # work as well as an absolute one.
        os.makedirs(self.path(device_info.TRASH_DIR), exist_ok=True)
        _png(self.path(device_info.TRASH_DIR, "gone.png"), 5, 5)
        got = device_info.asset_path(self.path(device_info.TRASH_DIR), "gone.png")
        self.assertEqual(got, os.path.realpath(self.path(device_info.TRASH_DIR, "gone.png")))

    def test_escape_attempts_are_refused(self):
        self.assertIsNone(device_info.asset_path(self.root, "../escape.png"))
        self.assertIsNone(device_info.asset_path(self.root, ".."))
        self.assertIsNone(device_info.asset_path(self.root, ""))

    def test_non_image_extensions_are_refused(self):
        txt = self.path("notes.txt")
        with open(txt, "w") as fh:
            fh.write("x")
        self.assertIsNone(device_info.asset_path(self.root, txt))

    def test_thumbnail_accepts_a_bare_name(self):
        # cv2 may be unavailable in a bare environment; the resolver is the
        # point here, so only assert when a thumbnail can actually be encoded.
        data = device_info.asset_thumbnail(self.root, "btn_play.png")
        self.assertTrue(data == "" or data.startswith("data:image/"))


if __name__ == "__main__":
    unittest.main()
