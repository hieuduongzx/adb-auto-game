"""Version, changelog and self-update of a standalone Runner build."""
from __future__ import annotations


from src import runner_update
from src.utils import (
    log_success,
)



class UpdateMixin:
    """Version, changelog and self-update of a standalone Runner build."""

    # ── Version + self-update (standalone Runner builds) ─────────────────────

    def _runner_payload(self) -> dict:
        info = self._runner_info
        return {
            "version": str(info.get("version") or ""),
            "appName": str(info.get("appName") or ""),
            "repo": str(info.get("repo") or ""),
            "builtAt": str(info.get("builtAt") or ""),
            "supported": runner_update.updates_supported(info),
            "update": dict(self._update),
            "changelog": self._changelog_payload(),
        }

    def _changelog_auto_show_enabled(self) -> bool:
        with self._runner_config_lock:
            raw = (self._runner_config or {}).get("autoShowChangelog", True)
        return raw is not False

    def _changelog_payload(self, refresh: bool = False) -> dict:
        info = self._runner_info
        history = runner_update.refresh_history(info) if refresh else runner_update.load_history(info)
        pending = runner_update.read_pending(info)
        if pending and not any(row.get("version") == pending.get("version") for row in history):
            history = [pending] + history
        history.sort(key=lambda row: runner_update.parse_version(row.get("version")), reverse=True)
        current = str(info.get("version") or "")
        with self._runner_config_lock:
            shown = str((self._runner_config or {}).get("shownChangelogVersion") or "")
        auto = self._changelog_auto_show_enabled()
        notes = (pending or {}).get("markdown") or ""
        should = bool(
            pending and pending.get("version") == current and str(notes).strip()
            and pending.get("autoShow") is True and auto and shown != current
        )
        return {
            "history": history,
            "pending": pending,
            "autoShowEnabled": auto,
            "shownVersion": shown,
            "shouldAutoShow": should,
        }

    def changelog_refresh(self) -> dict:
        return self._changelog_payload(refresh=True)

    def set_changelog_auto_show(self, enabled: bool) -> dict:
        with self._runner_config_lock:
            self._runner_config["autoShowChangelog"] = bool(enabled)
            self._save_runner_config()
        return self._changelog_payload()

    def acknowledge_changelog(self, version: str) -> dict:
        version = str(version or "")
        current = str(self._runner_info.get("version") or "")
        if version and version == current:
            with self._runner_config_lock:
                self._runner_config["shownChangelogVersion"] = version
                self._save_runner_config()
            runner_update.acknowledge_pending(self._runner_info, version)
        return self._changelog_payload()

    def open_external_url(self, url: str) -> bool:
        """Open an https link from a changelog. Rejects every other scheme."""
        from urllib.parse import urlparse
        import webbrowser
        parsed = urlparse(str(url or ""))
        if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
            return False
        try:
            return bool(webbrowser.open(parsed.geturl()))
        except Exception:
            return False

    def _auto_check_update(self) -> None:
        result = runner_update.check(self._runner_info)
        self._update = result
        try:
            runner_update.refresh_history(self._runner_info)
        except Exception:
            pass
        if result.get("available"):
            log_success(f"Update available: v{result.get('version')}")
            self._push("update_available", result)

    def update_check(self) -> dict:
        """Ask GitHub for a newer release of this Runner."""
        result = runner_update.check(self._runner_info)
        self._update = result
        try:
            runner_update.refresh_history(self._runner_info)
        except Exception:
            pass
        result["changelog"] = self._changelog_payload()
        return result

    def update_apply(self) -> dict:
        """Download + install the newest release and restart. Returns only on
        failure or when already up to date."""
        if self.engine.is_running():
            return {"applied": False, "error": "Stop the run before updating", "upToDate": False}
        return runner_update.apply(
            self._runner_info,
            on_progress=lambda pct, stage: self._push("update_progress", {"pct": pct, "stage": stage}),
            before_exit=self._close,
        )
