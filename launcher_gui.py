"""
GUI Game Launcher — PyWebView-based game selector.

Usage::

    python launcher_gui.py

A compact window lists all discovered games.  Click a game to open its
automation window.
"""
from __future__ import annotations

import sys
from pathlib import Path
from typing import Dict, Optional

import webview

_PROJECT_ROOT = Path(__file__).resolve().parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from launcher import load_game_class, scan_games
from src.utils import log_error, log_info


# ---------------------------------------------------------------------------
# API bridge
# ---------------------------------------------------------------------------

class LauncherAPI:
    def __init__(self, games: Dict[str, Dict[str, str]]) -> None:
        self._games = games
        self._window: Optional[webview.Window] = None

    def _attach(self, window: webview.Window) -> None:
        self._window = window

    def get_games(self) -> list:
        return [
            {"name": k, "display": v["display_name"]}
            for k, v in self._games.items()
        ]

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
        # Create game window in the same webview session, then close launcher.
        from src.gui.pywebview_gui import create_pywebview_window
        create_pywebview_window(game_class, title)
        if self._window:
            self._window.destroy()
        return True


# ---------------------------------------------------------------------------
# Launcher HTML (fully self-contained, no external resources)
# ---------------------------------------------------------------------------

def _launcher_html(games: Dict[str, Dict[str, str]]) -> str:
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
  --bg:#eef0f3;--panel:#ffffff;--surface:#f7f9fc;--border:#e4e7ec;
  --ink:#19222e;--dim:#5a6573;--muted:#9aa3ae;
  --accent:#2f6fed;--accent-bg:#e8f1ff;
  --r:10px;
  --sans:"Segoe UI",system-ui,sans-serif;
  color-scheme:light;
}}
html,body{{height:100%;background:var(--bg);font-family:var(--sans);
  font-size:13px;color:var(--ink);-webkit-font-smoothing:antialiased;
  user-select:none;overflow:hidden;}}
#app{{
  height:100%;display:flex;flex-direction:column;
  padding:14px 10px 10px;gap:10px;
}}
.header{{
  background:var(--panel);border:1px solid var(--border);
  border-radius:var(--r);padding:14px 16px;
}}
.title{{font-size:16px;font-weight:700;color:var(--ink);line-height:1.1;}}
.subtitle{{font-size:11px;color:var(--muted);margin-top:3px;}}
.section-label{{
  font-size:10.5px;font-weight:700;letter-spacing:.06em;
  color:var(--muted);text-transform:uppercase;padding:0 2px;
}}
.game-list{{
  flex:1;min-height:0;overflow-y:auto;
  display:flex;flex-direction:column;gap:4px;
}}
::-webkit-scrollbar{{width:5px}}
::-webkit-scrollbar-thumb{{background:#d3d9e0;border-radius:3px}}
.game-btn{{
  width:100%;display:flex;align-items:center;gap:10px;
  background:var(--panel);border:1px solid var(--border);
  border-radius:var(--r);padding:11px 13px;
  cursor:pointer;font-family:var(--sans);
  text-align:left;transition:background .12s,border-color .12s,transform .1s;
}}
.game-btn:hover{{background:var(--surface);border-color:#d0d6de;transform:translateY(-1px);}}
.game-btn:active{{transform:translateY(0);background:#eef0f3;}}
.game-btn.launching{{opacity:.6;pointer-events:none;}}
.game-name{{flex:1;font-size:13px;font-weight:600;color:var(--ink);}}
.arrow{{width:16px;height:16px;flex-shrink:0;color:var(--muted);
  transition:color .12s,transform .12s;}}
.game-btn:hover .arrow{{color:var(--accent);transform:translateX(2px);}}
#status{{
  font-size:11px;color:var(--muted);text-align:center;padding:2px 0;
  min-height:18px;
}}
</style>
</head>
<body>
<div id="app">
  <div class="header">
    <div class="title">ADB Game Automation</div>
    <div class="subtitle">Chọn game để mở giao diện tự động hoá</div>
  </div>
  <div class="section-label">GAME</div>
  <div class="game-list" id="game-list">
    {items}
  </div>
  <div id="status"></div>
</div>
<script>
async function launch(name) {{
  document.querySelectorAll('.game-btn').forEach(b => b.classList.add('launching'));
  document.getElementById('status').textContent = 'Đang mở...';
  try {{
    await window.pywebview.api.launch(name);
  }} catch(e) {{
    document.getElementById('status').textContent = 'Lỗi: ' + e;
    document.querySelectorAll('.game-btn').forEach(b => b.classList.remove('launching'));
  }}
}}
</script>
</body>
</html>"""


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main() -> int:
    games = scan_games()
    if not games:
        log_error("No games found in src/games/")
        return 1

    api = LauncherAPI(games)
    window = webview.create_window(
        "ADB Game Automation — Launcher",
        html=_launcher_html(games),
        js_api=api,
        width=340,
        height=min(160 + len(games) * 54, 560),
        resizable=False,
        background_color="#eef0f3",
    )
    window.events.loaded += lambda: api._attach(window)
    webview.start(debug=False, private_mode=False)
    return 0


if __name__ == "__main__":
    sys.exit(main())
