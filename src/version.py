"""Single source of truth for the application version.

Bump ``__version__`` here and every surface (window titles, Hub badge, packaged
``.exe`` metadata) follows automatically. Keep it a plain ``MAJOR.MINOR`` /
``MAJOR.MINOR.PATCH`` string so it can also feed the Windows version resource.
"""

import os

APP_NAME = "Macro2k"
# Semantic version (MAJOR.MINOR.PATCH). Velopack / NuGet require three parts, so
# keep it three parts even for a round "1.0" release → "1.0.0".
__version__ = "1.0.1"

# Display string used in window titles / UI, e.g. ``"Macro2k 1.0.0"``.
APP_VERSION = __version__

# ── Auto-update (Velopack) ───────────────────────────────────────────────────
# The GitHub repository whose *Releases* host the update feed (Setup.exe +
# *-full.nupkg + RELEASES.* files, published by ``vpk``). Override at runtime
# with the MACRO2K_UPDATE_URL env var (handy for testing against a fork).
UPDATE_REPO_URL = os.environ.get(
    "MACRO2K_UPDATE_URL",
    "https://github.com/hieuduongzx/adb-auto-game",
)
# Release channel to track (None = the default channel the build was packed on).
UPDATE_CHANNEL = os.environ.get("MACRO2K_UPDATE_CHANNEL") or None


def version_tuple() -> tuple[int, ...]:
    """``"1.0"`` → ``(1, 0)``. Non-numeric suffixes (e.g. ``"1.0-rc1"``) are
    dropped so the result is always a clean tuple of ints — handy for the
    Windows version resource, which needs four integers."""
    nums = []
    for part in __version__.replace("-", ".").split("."):
        if part.isdigit():
            nums.append(int(part))
        else:
            break
    return tuple(nums)


def titled(base: str = APP_NAME) -> str:
    """Compose a window title like ``"Macro2k Runner 1.0"``."""
    return f"{base} {__version__}"
