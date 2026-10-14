"""Game path, game files, shared emulator, speed hack and UI settings."""
from __future__ import annotations

import math
import os
import shutil
from typing import List

from src.utils import (
    app_dir,
    is_frozen,
    load_ui_settings,
    log_error,
    log_info,
    log_success,
    log_warning,
    save_ui_settings,
)

from runner.common import (
    EMULATOR_KINDS,
    REQUIREMENTS_DIR,
    REQUIREMENTS_SKIP,
    REQUIREMENTS_SRC,
    _copy_tree_elevated,
)


class SettingsMixin:
    """Game path, game files, shared emulator, speed hack and UI settings."""

    # ── Project game path (Win32) ────────────────────────────────────────────

    def set_game_path(self, value: str) -> dict:
        """Override the project game path used by Launch program nodes set to
        "Project game path". An empty value restores the workflow's own path."""
        if self.engine.is_running() or not self.flow or self._controller() != "win32":
            return {"ok": False, "path": str((self.flow.get("win32") or {}).get("path") or "")}
        override = str(value or "").strip()
        effective = override or self._flow_game_path
        with self._runner_config_lock:
            if not self._persist_runner_config({("win32Path",): override} if override else {},
                                               remove=() if override else ("win32Path",)):
                return {"ok": False, "path": str((self.flow.get("win32") or {}).get("path") or "")}
            self.engine.set_win32_path(effective)  # also writes self.flow["win32"]["path"]
        return {"ok": True, "path": effective, "requirements": self._requirements_payload(),
                "gamePath": self._game_path_status()}

    # ── Game requirements (files for the game's own folder) ──────────────────

    def _requirements_dir(self) -> str:
        """Folder holding the game requirements, or "" when there are none."""
        if is_frozen():
            folder = os.path.join(app_dir(), REQUIREMENTS_DIR)
        elif self.flow_path:
            folder = os.path.join(os.path.dirname(os.path.abspath(self.flow_path)), REQUIREMENTS_SRC)
        else:
            return ""
        return folder if self._requirement_files(folder) else ""

    @staticmethod
    def _requirement_files(folder: str) -> List[str]:
        """Relative paths of every shipped file under ``folder``."""
        found: List[str] = []
        for root, _dirs, files in os.walk(folder):
            for name in files:
                if name not in REQUIREMENTS_SKIP:
                    found.append(os.path.relpath(os.path.join(root, name), folder))
        return found

    def _game_dir(self) -> str:
        """Folder of the project game path (Settings → Game), if it exists."""
        path = str((self.flow.get("win32") or {}).get("path") or "").strip()
        folder = os.path.dirname(path) if path else ""
        return folder if folder and os.path.isdir(folder) else ""

    def _requirements_payload(self) -> dict:
        """``{}`` when this game ships no requirements; else what to copy and
        whether every file is already present in the game folder."""
        folder = self._requirements_dir()
        if not folder:
            return {}
        files = self._requirement_files(folder)
        game_dir = self._game_dir()
        missing = ([f for f in files if not os.path.exists(os.path.join(game_dir, f))]
                   if game_dir else files)
        items = sorted((n + (os.sep if os.path.isdir(os.path.join(folder, n)) else "")
                        for n in os.listdir(folder) if n not in REQUIREMENTS_SKIP), key=str.lower)
        return {"folder": folder, "items": items, "fileCount": len(files),
                "gameDir": game_dir, "missing": len(missing),
                "installed": bool(game_dir) and not missing}

    def open_requirements(self) -> bool:
        """Reveal the requirements folder in Explorer."""
        folder = self._requirements_dir()
        if not folder:
            return False
        try:
            os.startfile(folder)  # type: ignore[attr-defined]
            return True
        except Exception as exc:
            log_warning(f"Couldn't open {folder}: {exc}")
            return False

    def copy_requirements_to_game(self) -> dict:
        """Copy the requirements into the game folder (merging, overwriting).

        Tries a normal copy first; if the folder refuses the write (Program
        Files and other protected locations), retries through an elevated
        robocopy, which raises one UAC prompt."""
        if self.engine.is_running():
            return {"ok": False, "error": "Stop the run first"}
        folder = self._requirements_dir()
        if not folder:
            return {"ok": False, "error": "This game has no required files"}
        game_dir = self._game_dir()
        if not game_dir:
            return {"ok": False, "error": "Choose the game's .exe in Settings → Game first"}

        elevated = False
        try:
            shutil.copytree(folder, game_dir, dirs_exist_ok=True,
                            ignore=shutil.ignore_patterns(*REQUIREMENTS_SKIP))
        except (shutil.Error, OSError) as exc:
            detail = exc.args[0][0][2] if isinstance(exc, shutil.Error) and exc.args and exc.args[0] else exc
            log_warning(f"Normal copy blocked ({detail}) — retrying with admin rights")

        payload = self._requirements_payload()
        if not payload.get("installed"):
            # Nothing (or not everything) landed — do it as admin.
            log_info("Copying game files with administrator rights — confirm the UAC prompt…")
            if _copy_tree_elevated(folder, game_dir):
                elevated = True
            payload = self._requirements_payload()

        if payload.get("installed"):
            log_success(f"Copied game files into {game_dir} — restart the game to load them")
            return {"ok": True, "requirements": payload, "elevated": elevated}
        log_error(f"Couldn't copy game files into {game_dir}")
        return {"ok": False, "requirements": payload,
                "error": f"Couldn't copy into {game_dir} — close the game, or run the "
                         f"Runner as administrator and try again."}

    def pick_game_path(self, start: str = "") -> dict:
        """Choose the game .exe with the native picker, then save it."""
        if self.engine.is_running() or not self.flow:
            return {"ok": False, "path": ""}
        value = self._ask_path("file", start or self._flow_game_path,
                               ("Programs (*.exe;*.bat;*.cmd;*.com)", "All files (*.*)"))
        if not value:
            return {"ok": False, "path": ""}
        return self.set_game_path(value)

    # ── Shared emulator setting (ADB) ────────────────────────────────────────

    def set_emulator(self, kind: str, path: str, index=None) -> dict:
        """Override the shared emulator family + install folder + instance index
        used by emulator nodes on "Project emulator setting". ``index=None``
        keeps the stored index, so a kind/folder edit never resets it.
        Returns the effective setting."""
        if self.engine.is_running() or not self.flow or self._controller() == "win32":
            return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
        kind = str(kind or "").strip().lower()
        if kind not in EMULATOR_KINDS:
            kind = str((self.flow.get("emulator") or {}).get("kind") or "ldplayer").strip().lower()
        if kind not in EMULATOR_KINDS:
            kind = "ldplayer"
        path = str(path or "").strip()
        idx = None
        if index is not None:
            try:
                idx = max(0, int(float(index)))
            except (TypeError, ValueError, OverflowError):
                return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
        with self._runner_config_lock:
            changes = {("emulator", "kind"): kind, ("emulator", "path"): path}
            if idx is not None:
                changes[("emulator", "index")] = idx
            if not self._persist_runner_config(changes):
                return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
            self.engine.set_emulator_config(kind, path, idx)
            cur = self.flow.get("emulator")
            eff_index = cur.get("index", 0) if isinstance(cur, dict) else 0
        return {"ok": True, "emulator": {"kind": kind, "path": path, "index": eff_index},
                "emulatorDefault": self._flow_emulator}

    def pick_emulator_path(self, start: str = "") -> dict:
        """Choose the emulator install folder with the native picker, then save."""
        if self.engine.is_running() or not self.flow or self._controller() == "win32":
            return {"ok": False, "emulator": dict(self.flow.get("emulator") or {})}
        cur = dict(self.flow.get("emulator") or {})
        value = self._ask_path("folder", start or str(cur.get("path") or ""),
                               ("All files (*.*)",))
        if not value:
            return {"ok": False, "emulator": cur}
        return self.set_emulator(str(cur.get("kind") or ""), value)

    def reorder_activities(self, ordered_ids: List[str]) -> bool:
        """Reorder ``flow['activities']`` to match the drag-and-drop order.

        ``ordered_ids`` lists every activity id in its new order. The list is
        rewritten *in place* so the engine (which shares the same dict) picks up
        the new sequence order on the next run. Ignored while a run is in
        progress to avoid mutating the list mid-iteration.
        """
        if self._run_live():
            log_warning("Activities can't be reordered while running")
            return False
        acts = self.flow.get("activities") or []
        by_id = {a.get("id"): a for a in acts}
        new_order, seen = [], set()
        for activity_id in ordered_ids:
            if activity_id in by_id and activity_id not in seen:
                seen.add(activity_id)
                new_order.append(by_id[activity_id])
        # Append any activity not mentioned (defensive), keeping its relative order.
        for a in acts:
            if a not in new_order:
                new_order.append(a)
        with self._runner_config_lock:
            order = [str(a.get("id")) for a in new_order if a.get("id")]
            if not self._persist_runner_config({("order",): order}):
                return False
            acts[:] = new_order
        return True

    # ── Speedhack (live scale slider) ─────────────────────────────────────────

    def set_speedhack(self, enabled: bool, speed: float = None,
                      package: str = None) -> dict:
        """Toggle the speedhack and/or update its speed/package.

        Applies live when a run is in progress, otherwise just stores the
        config so the next Start picks it up.
        """
        try:
            changes = {("speedhack", "enabled"): bool(enabled)}
            if speed is not None:
                speed = float(speed)
                if not math.isfinite(speed) or speed <= 0:
                    return {**self.engine.speedhack_info(), "ok": False}
                changes[("speedhack", "speed")] = speed
            if not self._persist_runner_config(changes):
                return {**self.engine.speedhack_info(), "ok": False}
            self.engine.configure_speedhack(
                enabled=bool(enabled),
                speed=speed,
                package=package,
            )
        except Exception as exc:
            log_error(f"Speed hack failed: {exc}")
            return {**self.engine.speedhack_info(), "ok": False}
        info = self.engine.speedhack_info()
        self._push("speedhack_update", info)
        return {**info, "ok": True}

    def _rounds_payload(self) -> dict:
        return {"count": int(getattr(self.engine, "rounds", 1)),
                "rest": float(getattr(self.engine, "round_rest", 0.0))}

    def set_rounds(self, count, rest=0) -> dict:
        """How many times Start runs the sequence (0 = until stopped) and the
        rest between rounds in seconds. A Runner setting, saved per workflow;
        it applies from the next Start, so it can't change under a live run."""
        if self._run_live():
            return {"ok": False, **self._rounds_payload()}
        wanted = self.engine.configure_rounds(count, rest)
        with self._runner_config_lock:
            ok = self._persist_runner_config({("rounds",): {"count": wanted["rounds"],
                                                            "rest": wanted["rest"]}})
        if not ok:
            saved = self._runner_config.get("rounds") or {}
            self.engine.configure_rounds(saved.get("count", 1), saved.get("rest", 0))
        return {"ok": ok, **self._rounds_payload()}

    def set_speed_scale(self, scale: float) -> dict:
        """Change the live time scale while a run is in progress."""
        try:
            value = float(scale)
            if not math.isfinite(value) or value <= 0:
                return {**self.engine.speedhack_info(), "ok": False}
            if not self._persist_runner_config({("speedhack", "speed"): value}):
                return {**self.engine.speedhack_info(), "ok": False}
            self.engine.set_speed_scale(value)
        except Exception as exc:
            log_error(f"Speed hack failed: {exc}")
            return {**self.engine.speedhack_info(), "ok": False}
        info = self.engine.speedhack_info()
        self._push("speedhack_update", info)
        return {**info, "ok": True}

    def clear_log(self) -> bool:
        self._log_buffer.clear()
        self._push("log_cleared", {})
        return True

    # ── Shared UI settings ───────────────────────────────────────────────────
    # Backed by the same file the Designer writes, so a theme or density picked
    # in any window is what every other window opens with. ``web/shared/
    # theme.js`` calls both of these.
    def get_settings(self) -> dict:
        return load_ui_settings()

    def save_settings(self, settings: dict) -> bool:
        return save_ui_settings(settings)
