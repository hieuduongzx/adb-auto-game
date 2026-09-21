"""Light obfuscation for a packaged Runner's bundled ``workflow.json`` + template
images — stops a player who browses into ``<Runner>/_internal/workflow/`` from
casually reading the automation logic in a text editor or the match-template
screenshots in an image viewer.

**Not real security.** The key lives in this file, shipped inside the Runner
itself; anyone with Macro2k's source (or a debugger attached to a running
Runner) can always recover it and decrypt everything — the same ceiling every
offline, no-server DRM scheme runs into. Don't rely on this to keep an asset
secret from someone determined to extract it.

Format: ``MAGIC + 16-byte random nonce + XOR(plaintext, keystream)``, where the
keystream is ``SHA-256(KEY + nonce + counter)`` chunks concatenated (stdlib
``hashlib`` only — no extra dependency; the Runner build deliberately excludes
the ``cryptography`` package to keep it lean). The magic prefix is what makes
every reader here auto-detect encrypted vs. plain: a workflow saved by the
Designer, or a Runner running from source, has no prefix and is read as plain
bytes exactly as before. Encryption only ever happens as a
``packaging/build_runner.py`` packaging step (:func:`encrypt_tree`); nothing
in the repo itself, nor a Designer/Hub build, ever writes ciphertext.
"""
from __future__ import annotations

import hashlib
import os

MAGIC = b"M2KE1"
_NONCE_LEN = 16
# Obfuscation only (see module docstring) — not a secret worth protecting hard,
# just non-obvious to a casual "strings" scan.
_KEY = bytes.fromhex(
    "d41f0c9a7e2b68530f9a4dc1b6e2708f"
    "3a5c917e0b4d68f2a1c9e07db5384f6a"
)


def _keystream(nonce: bytes, length: int) -> bytes:
    out = bytearray()
    counter = 0
    while len(out) < length:
        out += hashlib.sha256(_KEY + nonce + counter.to_bytes(4, "big")).digest()
        counter += 1
    return bytes(out[:length])


def _xor(data: bytes, nonce: bytes) -> bytes:
    """XOR ``data`` with the keystream. Big-int arithmetic — much faster than a
    per-byte Python loop for the image/JSON sizes this handles."""
    if not data:
        return b""
    ks = _keystream(nonce, len(data))
    a = int.from_bytes(data, "big")
    b = int.from_bytes(ks, "big")
    return (a ^ b).to_bytes(len(data), "big")


def is_encrypted(data: bytes) -> bool:
    return data.startswith(MAGIC)


def encrypt_bytes(data: bytes) -> bytes:
    """Plaintext -> ``MAGIC``-tagged ciphertext (a fresh random nonce each call,
    so encrypting the same bytes twice never produces the same output)."""
    nonce = os.urandom(_NONCE_LEN)
    return MAGIC + nonce + _xor(data, nonce)


def decrypt_bytes(data: bytes) -> bytes:
    """``MAGIC``-tagged ciphertext -> plaintext. Raises ValueError otherwise."""
    if not is_encrypted(data):
        raise ValueError("not M2KE1 data")
    nonce = data[len(MAGIC):len(MAGIC) + _NONCE_LEN]
    body = data[len(MAGIC) + _NONCE_LEN:]
    return _xor(body, nonce)


def maybe_decrypt(data: bytes) -> bytes:
    """``data`` unchanged when it isn't ours, else the decrypted plaintext.

    The read path every runtime loader (workflow JSON, template images) should
    call — it works the same whether ``data`` came from an encrypted packaged
    Runner or a plain file from source/the Designer."""
    return decrypt_bytes(data) if is_encrypted(data) else data


def encrypt_file(path: str) -> bool:
    """Encrypt one file in place. No-op (returns False) if already encrypted."""
    with open(path, "rb") as fh:
        raw = fh.read()
    if is_encrypted(raw):
        return False
    with open(path, "wb") as fh:
        fh.write(encrypt_bytes(raw))
    return True


def encrypt_tree(root: str, extensions: tuple = (".png", ".jpg", ".jpeg", ".webp", ".bmp")) -> int:
    """Encrypt every file under ``root`` (recursive) whose name matches
    ``extensions`` (case-insensitive), in place. Returns how many were touched."""
    n = 0
    for dirpath, _dirs, files in os.walk(root):
        for name in files:
            if name.lower().endswith(extensions):
                if encrypt_file(os.path.join(dirpath, name)):
                    n += 1
    return n
