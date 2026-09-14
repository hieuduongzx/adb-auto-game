"""Human-readable names for key codes.

Key presses reach the engine as bare integers — Windows virtual-key codes for
Win32 projects, Android keycodes for ADB ones — and the log used to echo that
number straight back ("⌨ VK13 nhấn 80ms"). Nobody reads a run log to learn that
13 means Enter.

The designer already solved this on its side: ``WF_WIN_KEYS`` +
``wfWinKeyLabel()`` (apps/web/wf/js/workflow.js) render the same codes for the
node inspector. ``_VK_NAMES`` below mirrors that table deliberately — a key the
user picked from a dropdown as "↑ Up" must come back in the log as "↑ Up", not
as "VK38", or the two surfaces disagree about the same key.
"""
from typing import Dict, Optional

# ── Windows virtual-key codes ────────────────────────────────────────────────
#
# Mirrors WF_WIN_KEYS in apps/web/wf/js/workflow.js. Keep the two in step.
_VK_NAMES: Dict[int, str] = {
    0x08: "Backspace", 0x09: "Tab", 0x0D: "Enter", 0x1B: "Escape", 0x20: "Space",
    0x10: "Shift", 0x11: "Ctrl", 0x12: "Alt",
    0x21: "Page Up", 0x22: "Page Down", 0x23: "End", 0x24: "Home",
    0x25: "← Left", 0x26: "↑ Up", 0x27: "→ Right", 0x28: "↓ Down",
    0x2D: "Insert", 0x2E: "Delete",
}
# F1–F12 (0x70–0x7B), A–Z (0x41–0x5A), 0–9 (0x30–0x39) — generated rather than
# written out, exactly as the JS table builds them.
_VK_NAMES.update({0x70 + i: f"F{i + 1}" for i in range(12)})
_VK_NAMES.update({ord(c): c for c in "ABCDEFGHIJKLMNOPQRSTUVWXYZ"})
_VK_NAMES.update({ord(c): c for c in "0123456789"})

# Modifier name → the bit the caller passes to ``vk_combo``. Order matters: it
# fixes the rendering as Ctrl+Shift+Alt+Win, the order every Windows UI uses.
_MODIFIER_ORDER = (
    ("ctrl", "Ctrl"),
    ("shift", "Shift"),
    ("alt", "Alt"),
    ("win", "Win"),
)


def vk_name(vk: int) -> str:
    """Name of a Windows virtual-key code ("Enter", "↑ Up", …).

    Falls back to ``"VK{n}"`` for codes outside the table — still a leak, but a
    recognisable one, and the alternative (returning "") would lose the only clue
    the user has about which key was pressed.
    """
    try:
        code = int(vk)
    except (TypeError, ValueError):
        return f"VK{vk}"
    return _VK_NAMES.get(code, f"VK{code}")


def vk_combo(vk: int, ctrl: bool = False, shift: bool = False,
             alt: bool = False, win: bool = False) -> str:
    """Render a keypress with its modifiers: ``"Ctrl+Shift+A"``.

    A modifier is only printed when it is set — a plain ``A`` is not
    ``Ctrl+Alt+None+A``.
    """
    flags = {"ctrl": ctrl, "shift": shift, "alt": alt, "win": win}
    parts = [label for key, label in _MODIFIER_ORDER if flags.get(key)]
    parts.append(vk_name(vk))
    return "+".join(parts)


# ── Android keycodes ─────────────────────────────────────────────────────────
#
# The subset worth naming: the codes a game-automation flow actually sends. A
# code outside this table is still valid for `input keyevent`, so the lookup
# falls back to the number rather than pretending to know it.
_ANDROID_NAMES: Dict[int, str] = {
    3: "HOME", 4: "BACK", 5: "CALL", 6: "ENDCALL",
    19: "DPAD_UP", 20: "DPAD_DOWN", 21: "DPAD_LEFT", 22: "DPAD_RIGHT",
    23: "DPAD_CENTER", 24: "VOLUME_UP", 25: "VOLUME_DOWN",
    26: "POWER", 27: "CAMERA", 28: "CLEAR",
    61: "TAB", 62: "SPACE", 66: "ENTER", 67: "DEL", 82: "MENU", 84: "SEARCH",
    85: "MEDIA_PLAY_PAUSE", 86: "MEDIA_STOP", 87: "MEDIA_NEXT",
    88: "MEDIA_PREVIOUS",
    122: "MOVE_HOME", 123: "MOVE_END", 124: "INSERT", 125: "FORWARD_DEL",
    126: "MEDIA_PLAY", 127: "MEDIA_PAUSE",
    164: "VOLUME_MUTE", 187: "APP_SWITCH",
    220: "BRIGHTNESS_DOWN", 221: "BRIGHTNESS_UP",
}
_ANDROID_NAMES.update({131 + i: f"F{i + 1}" for i in range(12)})


def android_key_name(code) -> str:
    """Name of an Android keycode, or the input unchanged when unrecognised.

    Accepts either form the ``key`` block can hold, because its inspector field
    is a free-text box (default ``"BACK"``) rather than a dropdown:

    * an int or numeric string — ``4`` / ``"4"`` → ``"BACK"``
    * a ``KEYCODE_``-prefixed name — ``"KEYCODE_BACK"`` → ``"BACK"``, since
      ``input keyevent`` accepts either spelling and the short one reads better
    * any other string is passed through untouched (the user may be sending a
      keyevent name this table simply does not list)
    """
    if isinstance(code, bool):        # bool is an int subclass — not a key code
        return str(code)
    if isinstance(code, int):
        return _ANDROID_NAMES.get(code, str(code))

    text = str(code).strip()
    if not text:
        return ""
    # Numeric string → same lookup as the int form.
    try:
        return _ANDROID_NAMES.get(int(text), text)
    except ValueError:
        pass
    # "KEYCODE_BACK" and "back" both normalise to the table's spelling.
    bare = text.upper()
    if bare.startswith("KEYCODE_"):
        bare = bare[len("KEYCODE_"):]
    for name in _ANDROID_NAMES.values():
        if name == bare:
            return name
    return text


def android_key_is_known(code) -> bool:
    """Whether ``code`` resolves to a named keycode.

    Lets the engine warn about a typo'd ``key`` block (``"BACKK"``) instead of
    silently sending it to ``input keyevent`` and getting a failure back.
    """
    if isinstance(code, bool):
        return False
    if isinstance(code, int):
        return code in _ANDROID_NAMES
    text = str(code).strip()
    if not text:
        return False
    try:
        return int(text) in _ANDROID_NAMES
    except ValueError:
        pass
    bare = text.upper()
    if bare.startswith("KEYCODE_"):
        bare = bare[len("KEYCODE_"):]
    return bare in _ANDROID_NAMES.values()


def vk_is_known(vk) -> bool:
    """Whether ``vk`` is a virtual-key code this module can name."""
    try:
        return int(vk) in _VK_NAMES
    except (TypeError, ValueError):
        return False


def describe_key_event(kind: str, code, mode: str = "press",
                       hold_ms: Optional[int] = None) -> str:
    """One-line description of a key action, for the run log.

    ``kind`` is ``"win"`` or ``"android"``; ``mode`` follows the ``win_key``
    block's press/down/up. Returns the text *after* the ⌨ prefix, so the caller
    keeps control of the leading glyph.
    """
    if kind == "android":
        return android_key_name(code)
    name = vk_name(code)
    if mode == "down":
        return f"{name} giữ"
    if mode == "up":
        return f"{name} nhả"
    if hold_ms is None:
        return name
    return f"{name} nhấn {hold_ms}ms"
