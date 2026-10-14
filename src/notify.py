"""Tell the operator something happened: a desktop balloon, a Discord message.

Used by the workflow's Notify block and by the Runner when a run ends. Both
channels are fire-and-forget on a worker thread — a slow or failing network
must never hold up a run — and report problems as log warnings.
"""
from __future__ import annotations

import json
import os
import re
import subprocess
import threading
import urllib.error
import urllib.request
from typing import Optional

from src.utils import log_warning

# Discord's incoming-webhook URLs: https://discord.com/api/webhooks/<id>/<token>
# (also the legacy discordapp.com host and the ptb/canary subdomains).
_WEBHOOK_RE = re.compile(
    r"^https://(?:(?:ptb|canary)\.)?discord(?:app)?\.com/api/webhooks/\d+/[\w-]+/?$")

# Embed side colours for the run outcomes the Runner reports.
COLORS = {"completed": 0x2A7F46, "failed": 0xD6483F, "stopped": 0xC27C0E, "info": 0x0B737C}

_TIMEOUT = 10.0


def is_webhook_url(url: str) -> bool:
    return bool(_WEBHOOK_RE.match(str(url or "").strip()))


def beep() -> None:
    try:
        import winsound
        winsound.MessageBeep(winsound.MB_ICONASTERISK)
    except Exception:
        pass


def desktop(title: str, message: str) -> None:
    """A Windows tray balloon. Title and message travel in the environment:
    they may carry OCR text or {var} values, and interpolating those into the
    PowerShell source broke on quotes and let $(...) run as code."""
    ps = (
        "Add-Type -AssemblyName System.Windows.Forms;"
        "$n=New-Object System.Windows.Forms.NotifyIcon;"
        "$n.Icon=[System.Drawing.SystemIcons]::Information;"
        "$n.Visible=$true;"
        "$n.ShowBalloonTip(6000,$env:M2K_NOTIFY_TITLE,$env:M2K_NOTIFY_MSG,"
        "[System.Windows.Forms.ToolTipIcon]::Info);"
        "Start-Sleep 7;$n.Dispose()"
    )
    try:
        subprocess.Popen(
            ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", ps],
            env={**os.environ, "M2K_NOTIFY_TITLE": str(title), "M2K_NOTIFY_MSG": str(message)},
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
        )
    except Exception:
        pass


def discord_payload(title: str, message: str, kind: str = "info",
                    fields: Optional[dict] = None) -> dict:
    """The JSON body for one Discord embed (pure — tested without a network)."""
    embed = {"title": str(title)[:256], "description": str(message)[:4000],
             "color": COLORS.get(kind, COLORS["info"])}
    if fields:
        embed["fields"] = [{"name": str(k)[:256], "value": str(v)[:1024] or "-", "inline": True}
                           for k, v in list(fields.items())[:10]]
    return {"username": "Macro2k", "embeds": [embed]}


def send_discord(url: str, title: str, message: str, kind: str = "info",
                 fields: Optional[dict] = None) -> Optional[str]:
    """POST one embed; returns None on success, else a short error. Blocking."""
    url = str(url or "").strip()
    if not is_webhook_url(url):
        return "not a Discord webhook URL"
    body = json.dumps(discord_payload(title, message, kind, fields)).encode("utf-8")
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Content-Type": "application/json", "User-Agent": "Macro2k (run notifications)"})
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            if 200 <= resp.status < 300:
                return None
            return f"HTTP {resp.status}"
    except urllib.error.HTTPError as exc:
        return f"HTTP {exc.code}"
    except Exception as exc:
        return str(exc) or exc.__class__.__name__


def discord_async(url: str, title: str, message: str, kind: str = "info",
                  fields: Optional[dict] = None) -> None:
    def work() -> None:
        error = send_discord(url, title, message, kind, fields)
        if error:
            log_warning(f"Discord notification failed: {error}")
    threading.Thread(target=work, daemon=True).start()
