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
    than its exact pixels. OpenCV is already part of the matching runtime, so
    this does not pull a second image decoder into packaged Runners.
    """
    try:
        import cv2

        image = cv2.imread(path, cv2.IMREAD_GRAYSCALE)
        if image is None or image.size == 0:
            return None
        small = cv2.resize(image, _RESIZE, interpolation=cv2.INTER_LANCZOS4)
    except Exception:
        return None

    bits = 0
    for y in range(_RESIZE[1]):
        for x in range(_RESIZE[0] - 1):
            bits = (bits << 1) | (1 if small[y, x] > small[y, x + 1] else 0)
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
