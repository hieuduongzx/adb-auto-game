import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import cv2
import numpy as np

from src.core.imghash import dhash, hamming


class ImageHashTests(unittest.TestCase):
    def test_hashing_does_not_require_pillow(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "gradient.png"
            image = np.tile(np.arange(0, 255, 8, dtype=np.uint8), (32, 1))
            self.assertTrue(cv2.imwrite(str(path), image))

            with patch.dict(sys.modules, {"PIL": None, "PIL.Image": None}):
                value = dhash(str(path))

        self.assertIsInstance(value, int)
        self.assertEqual(hamming(value, value), 0)

    def test_invalid_image_has_no_hash(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "broken.png"
            path.write_text("not an image", encoding="utf-8")
            self.assertIsNone(dhash(str(path)))


if __name__ == "__main__":
    unittest.main()
