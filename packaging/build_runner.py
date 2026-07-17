"""Build a standalone **single-workflow Runner** .exe.

Produces ``dist/<Name>-Runner/`` containing just the Runner GUI, the one
workflow (bundled into the exe), and only the ``vendor/`` pieces that workflow
actually needs — no Designer, no Hub, no DevScope. This is the lean counterpart
to ``packaging/build.ps1`` (which builds the full Macro2k suite).

Usage (from the project root, with the dev Python that has PyInstaller)::

    python packaging/build_runner.py --workflow workflows/BrownDust2
    python packaging/build_runner.py --workflow workflows/BrownDust2 --version 1.2.0

The Workflow Designer's **Build EXE** button shells out to exactly this script.

Vendor trimming
---------------
The workflow JSON is scanned to decide which vendor tools ship:

* ``adb``       — ADB controller, an ``adb`` capture source, or any emulator node
* ``scrcpy``    — ADB projects using the scrcpy capture source
* ``tesseract`` — any OCR text node (``if_text`` / ``wait_text`` / ``read_var`` /
                  ``parse_var``)
* ``frida``     — an enabled ADB speed hack only (``vendor/frida`` is the Android
                  frida-inject binary; Win32 input uses Win32 messaging, not
                  frida, so Win32 workflows never need it)

Progress lines are printed with a ``>>`` prefix so a caller (the designer) can
surface them in its log.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import shutil
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SPEC = os.path.join(ROOT, "packaging", "runner_build.spec")
VENDOR_SRC = os.path.join(ROOT, "vendor")

# The vendor sub-tools we know how to trim to.
VENDOR_TOOLS = ("adb", "scrcpy", "tesseract", "frida")
OCR_NODES = {"if_text", "wait_text", "read_var", "parse_var"}
EMULATOR_NODES = {"launch_emulator", "if_emulator", "wait_emulator"}


def log(msg: str) -> None:
    """Emit a progress line the caller (designer) can parse + display."""
    print(f">> {msg}", flush=True)


def _sanitize(raw: str) -> str:
    import re

    cleaned = re.sub(r"[^A-Za-z0-9_\-]+", "_", (raw or "").strip())
    return cleaned.strip("._-") or "Workflow"


def find_workflow_json(folder: str) -> str | None:
    """Pick the primary JSON in a workflow folder (workflow.json preferred)."""
    if not os.path.isdir(folder):
        return None
    names = [n for n in os.listdir(folder) if n.lower().endswith(".json")]
    if not names:
        return None
    lower = {n.lower(): n for n in names}
    if "workflow.json" in lower:
        return os.path.join(folder, lower["workflow.json"])
    base = os.path.basename(folder.rstrip("/\\"))
    if f"{base}.json".lower() in lower:
        return os.path.join(folder, lower[f"{base}.json".lower()])
    names.sort(key=str.lower)
    return os.path.join(folder, names[0])


def compute_vendor_needs(flow: dict) -> set[str]:
    """Which vendor sub-tools this workflow requires at runtime."""
    controller = str(flow.get("controller") or "adb").strip().lower()
    capture = str(flow.get("capture") or "scrcpy").strip().lower()
    speedhack = flow.get("speedhack") or {}

    node_types: set[str] = set()
    for coll in ("activities", "functions"):
        for item in flow.get(coll) or []:
            for node in ((item.get("graph") or {}).get("nodes") or []):
                t = node.get("type")
                if t:
                    node_types.add(str(t))

    is_adb = controller == "adb"
    has_emulator = bool(node_types & EMULATOR_NODES)

    needs: set[str] = set()
    # adb.exe — any ADB device work (device controller, adb capture, emulator).
    if is_adb or has_emulator or capture == "adb":
        needs.add("adb")
    # scrcpy — only ADB projects using the scrcpy frame source.
    if (is_adb or has_emulator) and capture == "scrcpy":
        needs.add("scrcpy")
    # tesseract — any OCR text node.
    if node_types & OCR_NODES:
        needs.add("tesseract")
    # frida — ADB speed hack ONLY. vendor/frida is the Android frida-inject
    # binary; Win32 input uses Win32 messaging (PostMessage/SendMessage), never
    # frida, so a Win32 workflow never needs this ~107 MB tree.
    if is_adb and bool(speedhack.get("enabled")):
        needs.add("frida")
    return needs


def _dir_size_mb(path: str) -> float:
    total = 0
    for root, _dirs, files in os.walk(path):
        for f in files:
            try:
                total += os.path.getsize(os.path.join(root, f))
            except OSError:
                pass
    return total / (1024 * 1024)


def _trim_build(final: str) -> None:
    """Delete dead weight PyInstaller pulls in but this runner never uses.

    * ``cv2/opencv_videoio_ffmpeg*.dll`` (~54 MB) — OpenCV's bundled ffmpeg for
      ``cv2.VideoCapture``. The engine only does image ops (matchTemplate /
      imread / imdecode / resize / cvtColor); scrcpy video is decoded by PyAV,
      not cv2. Confirmed safe: cv2 still imports + matches without these.
    """
    internal = os.path.join(final, "_internal")
    removed = 0.0
    for dll in glob.glob(os.path.join(internal, "cv2", "opencv_videoio_ffmpeg*.dll")):
        try:
            removed += os.path.getsize(dll) / (1024 * 1024)
            os.remove(dll)
        except OSError:
            pass
    if removed:
        log(f"Trimmed cv2 videoio ffmpeg DLLs (−{removed:.0f} MB, unused)")


def _copy_vendor(needs: set[str], dest_root: str) -> None:
    dest_vendor = os.path.join(dest_root, "vendor")
    for tool in sorted(needs):
        src = os.path.join(VENDOR_SRC, tool)
        if not os.path.isdir(src):
            log(f"WARNING: vendor/{tool} not found — skipping (runtime may fail)")
            continue
        dst = os.path.join(dest_vendor, tool)
        log(f"Copying vendor/{tool} …")
        if os.path.isdir(dst):
            shutil.rmtree(dst, ignore_errors=True)
        shutil.copytree(src, dst)


def build(workflow_dir: str, name: str = "", version: str = "1.0.0",
          out_dir: str = "") -> str:
    """Build the runner exe. Returns the output folder path.

    Raises on failure (missing workflow, PyInstaller error).
    """
    workflow_dir = os.path.abspath(workflow_dir)
    flow_path = find_workflow_json(workflow_dir)
    if not flow_path:
        raise FileNotFoundError(f"No workflow JSON found in {workflow_dir}")

    with open(flow_path, "r", encoding="utf-8") as fh:
        flow = json.load(fh) or {}

    app_name = _sanitize(name or flow.get("name") or os.path.basename(workflow_dir))
    version = str(version or flow.get("buildVersion") or "1.0.0").strip() or "1.0.0"
    needs = compute_vendor_needs(flow)

    log(f"Workflow : {flow.get('name') or app_name}")
    log(f"Exe name : {app_name}.exe   (version {version})")
    log(f"Vendor   : {', '.join(sorted(needs)) or '(none)'}")

    stage = os.path.join(ROOT, "build", "_runner_stage")
    work = os.path.join(ROOT, "build", "_runner_work")
    out_root = out_dir or os.path.join(ROOT, "dist")
    final = os.path.join(out_root, f"{app_name}-Runner")

    # Write the build config the spec reads via MACRO2K_RUNNER_BUILD_CFG.
    # PyAV (ffmpeg, ~65 MB) only matters for the scrcpy capture source.
    include_av = "scrcpy" in needs
    if not include_av:
        log("Excluding PyAV/ffmpeg (−~65 MB, no scrcpy capture in this workflow)")
    cfg = {
        "root": ROOT,
        "workflow_dir": workflow_dir,
        "app_name": app_name,
        "version": version,
        "include_av": include_av,
    }
    cfg_fd, cfg_path = tempfile.mkstemp(prefix="runner_build_", suffix=".json")
    with os.fdopen(cfg_fd, "w", encoding="utf-8") as fh:
        json.dump(cfg, fh)

    try:
        # Ensure PyInstaller is importable in this interpreter.
        try:
            import PyInstaller  # noqa: F401
        except Exception:
            raise RuntimeError(
                "PyInstaller is not installed in this Python. "
                "Run: python -m pip install pyinstaller"
            )

        env = dict(os.environ)
        env["MACRO2K_RUNNER_BUILD_CFG"] = cfg_path

        log("Running PyInstaller … (this can take a minute)")
        cmd = [
            sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
            "--distpath", stage, "--workpath", work, SPEC,
        ]
        proc = subprocess.Popen(
            cmd, cwd=ROOT, env=env,
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, bufsize=1,
        )
        assert proc.stdout is not None
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                # Surface PyInstaller errors/warnings; keep the rest terse.
                if any(k in line for k in ("ERROR", "Error", "WARNING", "Traceback", "Building")):
                    log(line)
        code = proc.wait()
        if code != 0:
            raise RuntimeError(f"PyInstaller failed (exit {code})")

        staged = os.path.join(stage, f"{app_name}-Runner")
        if not os.path.isdir(staged):
            raise RuntimeError(f"PyInstaller did not produce {staged}")

        # Promote staging -> dist/<Name>-Runner (wipe any previous build).
        # NB: don't ignore_errors on the wipe — a half-deleted folder makes
        # shutil.move nest the new build inside the old one. A locked file here
        # almost always means the built runner is still open.
        log(f"Assembling {final}")
        if os.path.isdir(final):
            try:
                shutil.rmtree(final)
            except OSError as exc:
                raise RuntimeError(
                    f"Couldn't clear the previous build at {final} ({exc}). "
                    f"Close {app_name}.exe if it's still running, then rebuild."
                )
        os.makedirs(out_root, exist_ok=True)
        shutil.move(staged, final)

        # Drop dead weight, then copy only the vendor pieces this workflow needs.
        _trim_build(final)
        if needs:
            _copy_vendor(needs, final)

        log(f"Total size: {_dir_size_mb(final):.0f} MB")
        log(f"DONE: {os.path.join(final, app_name + '.exe')}")
        return final
    finally:
        try:
            os.remove(cfg_path)
        except OSError:
            pass
        shutil.rmtree(stage, ignore_errors=True)
        shutil.rmtree(work, ignore_errors=True)


def main() -> int:
    ap = argparse.ArgumentParser(description="Build a single-workflow Runner exe.")
    ap.add_argument("--workflow", required=True,
                    help="Path to the workflow folder (contains workflow.json).")
    ap.add_argument("--name", default="", help="Override the exe base name.")
    ap.add_argument("--version", default="", help="Build version (e.g. 1.0.0).")
    ap.add_argument("--out", default="", help="Output root (default: dist/).")
    args = ap.parse_args()
    try:
        build(args.workflow, name=args.name, version=args.version, out_dir=args.out)
    except Exception as exc:
        log(f"BUILD FAILED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
