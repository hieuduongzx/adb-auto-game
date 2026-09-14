"""Perceptual image hashing, for finding near-duplicate template crops.

Templates in this project are cropped by hand from a game screen, often more
than once from the same button — once when the node was written, again after a
UI tweak — so a folder of 269 files can hold dozens of pairs that differ only by
a pixel or two of offset. Exact byte comparison misses all of them.

``dhash`` (difference hash) answers the question the Library actually asks:
*do these two crops show the same thing?* It survives a small shift, a slight
rescale and lossy re-encoding, and it costs one grayscale resize plus 64 bit
comparisons per image — cheap enough to run over a whole folder in one call.
"""
from typing import Optional

HASH_BITS = 64          # 8×8 gradient grid
_RESIZE = (HASH_BITS // 8 + 1, HASH_BITS // 8)   # 9 wide → 8 comparisons per row


def dhash(path: str) -> Optional[int]:
    """64-bit difference hash of an image, or ``None`` if it cannot be read.

    Each bit is "is this pixel brighter than the one to its right", which makes
    the hash a fingerprint of the image's horizontal gradient structure rather
    than its exact pixels. Pillow is imported lazily so this module stays
    importable in builds that never touch an image.
    """
    try:
        from PIL import Image
        with Image.open(path) as im:
            small = im.convert("L").resize(_RESIZE, Image.LANCZOS)
        pixels = list(small.getdata())
    except Exception:
        return None

    width = _RESIZE[0]
    bits = 0
    for y in range(_RESIZE[1]):
        row = y * width
        for x in range(width - 1):
            bits = (bits << 1) | (1 if pixels[row + x] > pixels[row + x + 1] else 0)
    return bits


def hamming(a: int, b: int) -> int:
    """Number of differing bits between two hashes — the distance between them.

    0 means identical structure, 64 means unrelated. ``int.bit_count`` exists
    from Python 3.10; the fallback keeps this working on 3.9 builds.
    """
    x = a ^ b
    try:
        return x.bit_count()
    except AttributeError:                              # pragma: no cover - py<3.10
        return bin(x).count("1")
