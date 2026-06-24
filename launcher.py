"""
ADB Game Automation — GUI Launcher (PyWebView)

Usage::

    python launcher.py

Opens a game picker window.  Click a game to launch its automation GUI.
``scan_games`` and ``load_game_class`` are also importable by other modules.
"""
from __future__ import annotations

import importlib
import sys
from pathlib import Path
from typing import Dict, Optional, Type

import webview

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.utils import log_error, log_info  # noqa: E402


# ---------------------------------------------------------------------------
# Shared game-discovery utilities (imported by run.py and other callers)
# ---------------------------------------------------------------------------

def scan_games() -> Dict[str, Dict[str, str]]:
    """Discover games under ``src/games/``.

    A game is any directory ``src/games/<name>/`` that contains a
    ``<name>.py`` module.  Directories starting with ``__`` are skipped.
    """
    games_dir = _PROJECT_ROOT / "src" / "games"
    games: Dict[str, Dict[str, str]] = {}
    if not games_dir.exists():
        log_error(f"Games directory not found: {games_dir}")
        return games
    for item in sorted(games_dir.iterdir()):
        if not item.is_file() or item.suffix != ".py" or item.stem.startswith("__"):
            continue
        games[item.stem] = {
            "module_path":  f"src.games.{item.stem}",
            "display_name": item.stem.upper(),
        }
    return games


def load_game_class(game_info: Dict[str, str]) -> Optional[Type]:
    """Import and return the game class for *game_info*."""
    try:
        module = importlib.import_module(game_info["module_path"])
    except Exception as e:
        log_error(f"Could not import {game_info['module_path']}: {e}", exc_info=True)
        return None
    target = game_info["display_name"].lower()
    for attr in dir(module):
        if attr.lower() == target:
            return getattr(module, attr)
    log_error(f"No class matching '{target}' in {game_info['module_path']}")
    return None


# ---------------------------------------------------------------------------
# PyWebView launcher
# ---------------------------------------------------------------------------

class _LauncherAPI:
    def __init__(self, games: Dict[str, Dict[str, str]]) -> None:
        self._games = games
        self._window: Optional[webview.Window] = None

    def _attach(self, window: webview.Window) -> None:
        self._window = window

    def get_games(self) -> list:
        return [{"name": k, "display": v["display_name"]} for k, v in self._games.items()]

    def launch(self, game_name: str) -> bool:
        info = self._games.get(game_name)
        if not info:
            return False
        game_class = load_game_class(info)
        if not game_class:
            log_error(f"Could not load {info['display_name']}")
            return False
        title = f"{info['display_name']} Automation"
        log_info(f"Launching {title}")
        from src.gui.pywebview_gui import create_pywebview_window
        create_pywebview_window(game_class, title)
        if self._window:
            self._window.destroy()
        return True


def _build_html(games: Dict[str, Dict[str, str]]) -> str:
    items = "\n".join(
        f'<button class="game-btn" onclick="launch(\'{name}\')">'
        f'<span class="game-name">{info["display_name"]}</span>'
        f'<svg class="arrow" viewBox="0 0 16 16" fill="none">'
        f'<path d="M5 3l6 5-6 5" stroke="currentColor" stroke-width="1.8"'
        f' stroke-linecap="round" stroke-linejoin="round"/></svg>'
        f'</button>'
        for name, info in games.items()
    )
    return f"""<!DOCTYPE html>
<html lang="vi">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>ADB Game Automation</title>
<style>
*,*::before,*::after{{box-sizing:border-box;margin:0;padding:0}}
:root{{
  --bg:#eef0f3;--panel:#fff;--surface:#f7f9fc;--border:#e4e7ec;
  --ink:#19222e;--muted:#9aa3ae;--accent:#2f6fed;
  --r:10px;--sans:"Segoe UI",system-ui,sans-serif;color-scheme:light;
}}
html,body{{height:100%;background:var(--bg);font-family:var(--sans);
  font-size:13px;color:var(--ink);-webkit-font-smoothing:antialiased;
  user-select:none;overflow:hidden;}}
#app{{height:100%;display:flex;flex-direction:column;padding:12px 10px 8px;gap:8px;}}
.header{{background:var(--panel);border:1px solid var(--border);
  border-radius:var(--r);padding:13px 15px;}}
.title{{font-size:15px;font-weight:700;}}
.subtitle{{font-size:11px;color:var(--muted);margin-top:2px;}}
.label{{font-size:10px;font-weight:700;letter-spacing:.06em;
  color:var(--muted);text-transform:uppercase;padding:0 2px;}}
.list{{flex:1;min-height:0;overflow-y:auto;display:flex;flex-direction:column;gap:4px;}}
::-webkit-scrollbar{{width:5px}}
::-webkit-scrollbar-thumb{{background:#d3d9e0;border-radius:3px}}
.game-btn{{width:100%;display:flex;align-items:center;gap:10px;
  background:var(--panel);border:1px solid var(--border);border-radius:var(--r);
  padding:11px 13px;cursor:pointer;font-family:var(--sans);text-align:left;
  transition:background .12s,border-color .12s,transform .1s;}}
.game-btn:hover{{background:var(--surface);border-color:#d0d6de;transform:translateY(-1px);}}
.game-btn:active{{transform:translateY(0);}}
.game-btn.busy{{opacity:.55;pointer-events:none;}}
.game-name{{flex:1;font-size:13px;font-weight:600;}}
.arrow{{width:15px;height:15px;flex-shrink:0;color:var(--muted);
  transition:color .12s,transform .12s;}}
.game-btn:hover .arrow{{color:var(--accent);transform:translateX(2px);}}
#status{{font-size:11px;color:var(--muted);text-align:center;min-height:16px;}}
</style>
</head>
<body>
<div id="app">
  <div class="header">
    <div class="title">ADB Game Automation</div>
    <div class="subtitle">Chọn game để mở giao diện tự động hoá</div>
  </div>
  <div class="label">GAME</div>
  <div class="list">{items}</div>
  <div id="status"></div>
</div>
<script>
async function launch(name) {{
  document.querySelectorAll('.game-btn').forEach(b => b.classList.add('busy'));
  document.getElementById('status').textContent = 'Đang mở...';
  try {{
    await window.pywebview.api.launch(name);
  }} catch(e) {{
    document.getElementById('status').textContent = 'Lỗi: ' + e;
    document.querySelectorAll('.game-btn').forEach(b => b.classList.remove('busy'));
  }}
}}
</script>
</body>
</html>"""


def main() -> int:
    games = scan_games()
    if not games:
        log_error("No games found in src/games/")
        return 1

    api = _LauncherAPI(games)
    window = webview.create_window(
        "ADB Game Automation",
        html=_build_html(games),
        js_api=api,
        width=340,
        height=min(148 + len(games) * 52, 540),
        resizable=False,
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    webview.start(debug=False, private_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
