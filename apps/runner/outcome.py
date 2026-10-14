"""How a run ended (completed / stopped / failed), rounds, and its history record."""
from __future__ import annotations

import datetime
import os
import re
import time
from typing import List, Optional

from src import notify, run_history
from src.utils import (
    LOG_KIND_RUN,
    confined_path,
    load_ui_settings,
    log_error,
    log_info,
    log_success,
    log_warning,
    save_ui_settings,
)


class OutcomeMixin:
    """How a run ended (completed / stopped / failed), rounds, and its history record."""

    # ── Run outcome (completed / stopped / failed) ───────────────────────────
    # The engine only announces "a run started" and "a run stopped": a finished
    # pass, a user Stop and a fatal abort all end in on_stop, and an activity
    # cancelled mid-flight reports ok=False exactly like a failed one. So the
    # Stop *intent* is recorded here (stop()) and combined with the engine's own
    # failure signals — on_activity_crash, a failed activity, and the ``_fatal``
    # abort — to say truthfully how a run ended. No engine logic is changed.

    _OUTCOME_LABELS = {"completed": "Completed", "stopped": "Stopped", "failed": "Failed"}

    def _engine_stop_flags(self) -> tuple:
        """``(stopping, fatal)`` peeked read-only out of the engine.

        ``_stop`` is set by a user Stop, a workflow Stop block and by
        ``_fail_run``'s abort alike; ``_fatal`` is set *only* by ``_fail_run``
        (a Launch program with no program to start) — the one "stopped" that is
        genuinely a failure. Both are missing on a fresh engine, hence getattr.
        """
        event = getattr(self.engine, "_stop", None)
        try:
            stopping = bool(event is not None and event.is_set())
        except Exception:
            stopping = False
        return stopping, bool(str(getattr(self.engine, "_fatal", "") or ""))

    def _reset_run_tracking(self) -> None:
        self._stop_intent = False
        self._run_failed = False
        self._run_counts = {"completed": 0, "failed": 0, "stopped": 0}

    def _run_live(self) -> bool:
        """True between a run's on_start and its on_stop.

        Deliberately wider than ``engine.is_running()``: the engine flips
        ``running`` to False *just before* it emits on_stop, so a run that is
        still being wound down must not look idle to _begin_run()/stop().
        """
        return bool(self._run_active or self.engine.is_running())

    def _begin_run(self) -> None:
        """Start fresh outcome bookkeeping for a run that is about to be asked
        to start.

        Every entry point (Start, per-activity Run) calls this *before* it can
        bail out, so a blocked Start (a Launch program with no path) or a
        refused run_activity can never hand the previous run's Stop intent /
        failure flag to the next one. A run still winding down is left alone.
        """
        if not self._run_live():
            self._reset_run_tracking()

    def _outcome_fields(self) -> dict:
        """The last terminal outcome as flat keys, shared by ``running_state``
        and :meth:`get_state` so the page reads the same shape from either.

        ``outcome`` is None while a run is live and before the first run ever
        ended; the rest describe the run it belongs to (``runId``).
        """
        info = self._outcome or {}
        return {
            "outcome": info.get("kind"),
            "outcomeLabel": str(info.get("label") or ""),
            "outcomeReason": str(info.get("reason") or ""),
            "outcomeAt": str(info.get("at") or ""),
            "runId": int(info.get("runId") or self._run_id),
            "runCounts": dict(info.get("counts") or self._run_counts),
        }

    def _running_payload(self) -> dict:
        payload = {"running": self.engine.is_running(), "paused": self.engine.is_paused()}
        payload["runScope"] = self._run_scope
        payload["startedAt"] = self._run_started_at
        payload["round"] = dict(self._round) if self._round else None
        payload.update(self._outcome_fields())
        return payload

    def _on_engine_start(self) -> None:
        self._run_id += 1
        self._run_active = True
        self._run_started_at = time.time()
        activities = self.flow.get("activities", []) or []
        ids = self._run_scope if self._run_scope is not None else [str(a.get("id")) for a in activities]
        # A resumed run skips what came before its starting activity.
        resume = getattr(self, "_resume_from", None) if self._run_scope is None else None
        skipping = bool(resume) and resume in ids
        for activity_id in ids:
            if skipping and activity_id == resume:
                skipping = False
            status = "skipped" if skipping else "pending"
            self._act_status[activity_id] = status
            self._push("activity_update", {"id": activity_id, "status": status})
        self._resume_from = None
        self._reset_run_tracking()
        self._outcome = None
        self._round = None
        self._run_acts = {}
        self._act_t0 = {}
        self._push("running_state", self._running_payload())

    def _on_engine_stop(self) -> None:
        """Every terminal path lands here — classify the run once."""
        if self._run_active:
            self._run_active = False
            self._outcome = self._classify_outcome()
            if self._outcome["kind"] == "stopped":
                # A background activity cancelled by the Stop never reports
                # back (the engine just ends its loop), so settle its row.
                self._settle_stopped_activities()
            self._log_outcome(self._outcome)
            self._record_history(self._outcome)
            self._notify_outcome(self._outcome)
            self._round = None
        self._push("running_state", self._running_payload())

    def _classify_outcome(self) -> dict:
        """Decide how the run that just ended actually ended.

        Priority: a fatal abort is a failure even though it stopped the engine;
        a Stop (mine or the workflow's) is "stopped" and never a failure — which
        is the whole point of tracking intent, since a cancelled activity comes
        back as ok=False; otherwise a run that had any failed activity failed,
        and a clean pass completed.
        """
        stopping, fatal = self._engine_stop_flags()
        counts = dict(self._run_counts)
        intent = bool(self._stop_intent)
        if fatal:
            kind, reason = "failed", fatal
        elif intent or stopping:
            kind = "stopped"
            reason = "Stopped by you" if intent else "Stopped by the workflow"
        elif self._run_failed:
            kind = "failed"
            failed = counts.get("failed", 0)
            reason = (f"{failed} of {sum(counts.values())} activities failed"
                      if failed else "An activity failed")
        else:
            kind = "completed"
            done = counts.get("completed", 0)
            reason = (f"{done} activit{'y' if done == 1 else 'ies'} completed"
                      if done else "Run finished")
        rounds = int((self._round or {}).get("round") or 0)
        if rounds > 1 or (self._round and self._round.get("total") != 1):
            reason = f"{rounds} round{'s' if rounds != 1 else ''} · {reason}"
        return {"kind": kind, "label": self._OUTCOME_LABELS[kind], "reason": reason,
                "at": datetime.datetime.now().strftime("%H:%M:%S"),
                "epoch": time.time(), "runId": self._run_id, "counts": counts}

    def _log_outcome(self, info: dict) -> None:
        """One line in the Runner log per terminal outcome.

        The log is what an operator reads (and exports) after an unattended
        run, so how the run ended belongs in it rather than being inferred from
        the lines above it.
        """
        text = f"■ Run {info['label'].lower()}"
        if info.get("reason"):
            text += f" ({info['reason']})"
        if info["kind"] == "failed":
            log_error(text, kind=LOG_KIND_RUN)
        elif info["kind"] == "stopped":
            log_info(text, kind=LOG_KIND_RUN)
        else:
            log_success(text, kind=LOG_KIND_RUN)

    def _settle_stopped_activities(self) -> None:
        for act_id, status in list(self._act_status.items()):
            if status != "running":
                continue
            self._act_status[act_id] = "stopped"
            self._push("activity_update", {"id": act_id, "status": "stopped"})

    def _on_round(self, info: dict) -> None:
        """A repeating Start began a round or is resting before the next one.

        Every new round after the first puts the sequence rows back to
        "waiting", so the list reads as this round's progress rather than a
        mix of the last round's results and this one's."""
        info = dict(info or {})
        self._round = info
        if info.get("phase") == "running" and int(info.get("round") or 0) > 1:
            for act in self.flow.get("activities", []) or []:
                if act.get("type") == "background" or not act.get("enabled", True):
                    continue
                act_id = str(act.get("id"))
                self._act_status[act_id] = "pending"
                self._push("activity_update", {"id": act_id, "status": "pending"})
        self._push("running_state", self._running_payload())

    def _on_activity_start(self, act: dict) -> None:
        act_id = (act or {}).get("id")
        if act_id is not None:
            self._act_status[str(act_id)] = "running"
            self._act_t0[str(act_id)] = time.time()
        self._push("activity_update", {"id": act_id, "status": "running"})

    def _on_activity_complete(self, act: dict, ok: bool) -> None:
        """Paint one activity's terminal state and count it for the outcome."""
        status = self._activity_status(ok)
        act_id = (act or {}).get("id")
        if act_id is not None:
            self._act_status[str(act_id)] = status
            self._tally_activity(act, status)
        self._run_counts[status] = self._run_counts.get(status, 0) + 1
        if status == "failed":
            self._run_failed = True
        self._push("activity_update", {"id": act_id, "status": status})

    def _act_row(self, act: dict) -> dict:
        act_id = str(act.get("id"))
        return self._run_acts.setdefault(act_id, {
            "id": act_id, "name": str(act.get("name") or act_id),
            "completed": 0, "failed": 0, "stopped": 0, "seconds": 0.0})

    def _tally_activity(self, act: dict, status: str) -> None:
        act_id = str(act.get("id"))
        row = self._act_row(act)
        row[status] = row.get(status, 0) + 1
        started = self._act_t0.pop(act_id, None)
        if started:
            row["seconds"] = round(row["seconds"] + max(0.0, time.time() - started), 1)

    # ── Run history ──────────────────────────────────────────────────────────
    # One record per finished run (src/run_history.py): what an operator wants
    # to know the morning after — did it finish, how long, which activity broke.

    def _history_path(self) -> str:
        if not self.flow:
            return ""
        return run_history.history_path(str(self.flow.get("name") or ""), self.flow_path or "")

    def _record_history(self, outcome: dict) -> None:
        path = self._history_path()
        if not path:
            return
        end = time.time()
        start = float(self._run_started_at or end)
        scope = self._run_scope
        names = {str(a.get("id")): str(a.get("name") or a.get("id"))
                 for a in self.flow.get("activities", []) or []}
        round_info = self._round or {}
        record = {
            "v": 1, "workflow": str(self.flow.get("name") or ""),
            "start": round(start, 1), "end": round(end, 1),
            "seconds": round(max(0.0, end - start), 1),
            "outcome": outcome.get("kind"), "reason": outcome.get("reason", ""),
            "counts": dict(outcome.get("counts") or {}),
            "rounds": int(round_info.get("round") or 0),
            "scope": names.get(scope[0], scope[0]) if scope else "",
            "activities": list(self._run_acts.values()),
        }
        if run_history.append(path, record):
            self._push("history_added", record)

    # ── Run notifications ────────────────────────────────────────────────────
    # A desktop balloon and/or a Discord message when a full run ends — the
    # operator is usually not at the desk. One machine-wide preference in the
    # shared UI settings (key ``runNotify``), so every Runner on this PC uses
    # the same webhook. Single-activity runs are interactive and never notify.

    NOTIFY_WHEN = ("off", "failed", "all")
    NOTIFY_DEFAULT = {"when": "failed", "desktop": True, "discord": ""}

    def get_notify(self) -> dict:
        saved = load_ui_settings().get("runNotify")
        cfg = dict(self.NOTIFY_DEFAULT)
        if isinstance(saved, dict):
            if saved.get("when") in self.NOTIFY_WHEN:
                cfg["when"] = saved["when"]
            cfg["desktop"] = bool(saved.get("desktop", cfg["desktop"]))
            cfg["discord"] = str(saved.get("discord") or "").strip()
        return cfg

    def set_notify(self, patch: dict) -> dict:
        """Change when / how run notifications go out. Returns ``{ok, error,
        notify}``; a webhook that is not a Discord webhook URL is refused."""
        cfg = self.get_notify()
        patch = patch if isinstance(patch, dict) else {}
        if patch.get("when") in self.NOTIFY_WHEN:
            cfg["when"] = patch["when"]
        if "desktop" in patch:
            cfg["desktop"] = bool(patch["desktop"])
        if "discord" in patch:
            url = str(patch.get("discord") or "").strip()
            if url and not notify.is_webhook_url(url):
                return {"ok": False, "error": "That is not a Discord webhook URL "
                        "(https://discord.com/api/webhooks/…)", "notify": self.get_notify()}
            cfg["discord"] = url
        ok = save_ui_settings({"runNotify": cfg})
        return {"ok": ok, "error": "" if ok else "Couldn't save the setting", "notify": cfg}

    def test_notify(self) -> dict:
        """Send a sample through every configured channel, now."""
        cfg = self.get_notify()
        name = str(self.flow.get("name") or "Macro2k")
        title, message = f"{name} — test", "Run notifications reach you here."
        if cfg["desktop"]:
            notify.desktop(title, message)
        if cfg["discord"]:
            error = notify.send_discord(cfg["discord"], title, message, "info")
            if error:
                return {"ok": False, "error": f"Discord: {error}"}
        if not cfg["desktop"] and not cfg["discord"]:
            return {"ok": False, "error": "Turn on Windows notifications or add a Discord webhook first"}
        return {"ok": True, "error": ""}

    @staticmethod
    def _notify_text(name: str, outcome: dict, record: dict) -> tuple:
        """``(title, message, fields)`` for one finished run (pure)."""
        kind = str(outcome.get("kind") or "")
        title = f"{name} — {outcome.get('label') or kind.title()}"
        secs = int(round(float(record.get("seconds") or 0)))
        h, rem = divmod(secs, 3600)
        length = f"{h}h {rem // 60:02d}m" if h else f"{rem // 60}m {rem % 60:02d}s"
        message = str(outcome.get("reason") or "")
        failed = [a.get("name") for a in record.get("activities") or [] if a.get("failed")]
        fields = {"Duration": length}
        if record.get("rounds"):
            fields["Rounds"] = record["rounds"]
        counts = outcome.get("counts") or {}
        fields["Activities"] = f"{counts.get('completed', 0)} ✓ · {counts.get('failed', 0)} ✗"
        if failed:
            fields["Failed"] = ", ".join(str(n) for n in failed[:8]) + ("…" if len(failed) > 8 else "")
        return title, f"{message} · {length}" if message else length, fields

    def _notify_outcome(self, outcome: dict) -> None:
        if self._run_scope or not self.flow:
            return
        cfg = self.get_notify()
        kind = outcome.get("kind")
        if cfg["when"] == "off" or (cfg["when"] == "failed" and kind != "failed"):
            return
        record = {"seconds": max(0.0, time.time() - float(self._run_started_at or time.time())),
                  "rounds": int((self._round or {}).get("round") or 0),
                  "activities": list(self._run_acts.values())}
        title, message, fields = self._notify_text(str(self.flow.get("name") or "Macro2k"),
                                                   outcome, record)
        if cfg["desktop"]:
            notify.desktop(title, message)
        if cfg["discord"]:
            notify.discord_async(cfg["discord"], title, message, str(kind or "info"), fields)

    def get_history(self, limit: int = 50) -> List[dict]:
        path = self._history_path()
        return run_history.load(path, limit) if path else []

    def clear_history(self) -> bool:
        path = self._history_path()
        ok = run_history.clear(path) if path else False
        if ok:
            log_info("Run history cleared")
        return ok

    def _on_activity_crash(self, act: dict, crash: Optional[dict]) -> None:
        """The engine emits this only for a genuine failure — a user Stop and a
        Stop block are excluded there — so it is the dependable "this run did
        not simply finish" signal."""
        self._run_failed = True
        path = self._save_failure_shot(act)
        if path:
            self._act_row(act or {})["shot"] = path

    # ── Failure screenshots ──────────────────────────────────────────────────
    # The screen as it was when an activity failed — the first thing anyone
    # asks after an unattended run. One JPEG per failure in the workflow's
    # Runner folder (failures/), newest FAILURE_SHOTS_KEEP kept, linked from
    # the run's history record.

    FAILURE_SHOTS_KEEP = 40

    def _failure_dir(self) -> str:
        if not self.flow:
            return ""
        return os.path.join(run_history.runner_dir(str(self.flow.get("name") or ""),
                                                   self.flow_path or ""), "failures")

    def _save_failure_shot(self, act: Optional[dict]) -> str:
        folder = self._failure_dir()
        if not folder:
            return ""
        try:
            img = self.engine.auto.capture_screen()
            if img is None:
                return ""
            import cv2
            ok, buf = cv2.imencode(".jpg", img, [int(cv2.IMWRITE_JPEG_QUALITY), 85])
            if not ok:
                return ""
            os.makedirs(folder, exist_ok=True)
            name = re.sub(r"[^\w.-]+", "_", str((act or {}).get("name") or (act or {}).get("id") or "activity"))
            path = os.path.join(folder, f"{time.strftime('%Y%m%d_%H%M%S')}_{name[:40]}.jpg")
            buf.tofile(path)        # unicode-safe, unlike cv2.imwrite
            self._prune_failure_shots(folder)
            return path
        except Exception as exc:
            log_warning(f"Couldn't save the failure screenshot: {exc}")
            return ""

    def _prune_failure_shots(self, folder: str) -> None:
        try:
            shots = sorted((e for e in os.scandir(folder) if e.is_file() and e.name.lower().endswith(".jpg")),
                           key=lambda e: e.stat().st_mtime, reverse=True)
        except OSError:
            return
        for entry in shots[self.FAILURE_SHOTS_KEEP:]:
            try:
                os.remove(entry.path)
            except OSError:
                pass

    def open_failure_shot(self, path: str) -> dict:
        """Open a failure screenshot in the default image viewer. Only files in
        this workflow's failures/ folder — the path comes from the page."""
        safe = confined_path(self._failure_dir(), path, (".jpg", ".png"))
        if not safe or not os.path.isfile(safe):
            return {"ok": False, "error": "Screenshot not found (it may have been pruned)"}
        try:
            os.startfile(safe)
            return {"ok": True, "error": ""}
        except Exception as exc:
            return {"ok": False, "error": str(exc)}

    def _activity_status(self, ok: bool) -> str:
        """A stopped activity is reported as stopped, not failed.

        The engine reports a cancelled activity as ok=False (indistinguishable
        from a failure at that level) and, for a stop landing inside a wait,
        even as ok=True — so an in-effect Stop outranks ``ok``. ``_fatal`` still
        wins: an aborted run did fail.
        """
        stopping, fatal = self._engine_stop_flags()
        if fatal:
            return "failed"
        if stopping or self._stop_intent:
            return "stopped"
        return "completed" if ok else "failed"
