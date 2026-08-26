"""Shared device-inspection helpers for DevScope and the Workflow Designer.

Both GUIs expose the same Preview toolset (device info panel, colour pick,
template-match tester, asset library). The logic lives here once so the two
apps stay behaviourally identical; each app keeps only its thin JS-binding
glue (logging + ``window.__recv`` pushes).
"""
from __future__ import annotations

import base64
import os
import re
from typing import Any, Callable, Dict, List, Optional

import cv2
import numpy as np

from src.utils import confined_path, log_warning

# Properties fetched for the device info panel.
DEVICE_INFO_PROPS = (
    "ro.product.model",
    "ro.product.manufacturer",
    "ro.product.brand",
    "ro.product.device",
    "ro.product.cpu.abi",
    "ro.build.version.release",
    "ro.build.version.sdk",
    "ro.build.version.security_patch",
    "ro.build.display.id",
    "ro.serialno",
)

_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".bmp")

_DISCONNECTED_INFO = {
    "status": "Disconnected", "serial": "-", "model": "-",
    "brand": "-", "android": "-", "abi": "-", "screen_size": "-",
    "density": "-", "app": "-", "battery": "-", "ip": "-", "uptime": "-",
}


def shell(device, cmd: str) -> str:
    """Run an ADB shell command, returning stripped output ("" on failure)."""
    try:
        return (device.shell(cmd) or "").strip()
    except Exception:
        return ""


def safe_detect_app(device) -> Optional[str]:
    """Best-effort foreground package detection (``None`` when unavailable)."""
    try:
        from src.core.adb.controller import _detect_current_app
        return _detect_current_app(device)
    except Exception:
        return None


def collect_device_info(
    device,
    app_name_resolver: Optional[Callable[[str], str]] = None,
) -> Dict[str, Any]:
    """Gather the device-info panel payload for *device*.

    Returns :data:`_DISCONNECTED_INFO` when ``device`` is ``None``; otherwise a
    dict with keys ``status/serial/model/brand/android/abi/screen_size/
    density/app/battery/ip/uptime``. ``app_name_resolver`` (e.g.
    ``controller.get_app_name``) optionally turns the foreground package into a
    human-readable name.
    """
    if device is None:
        return dict(_DISCONNECTED_INFO)
    info: Dict[str, Any] = {"serial": getattr(device, "serial", "-"),
                            "status": "Connected"}

    getprop_cmd = " ; ".join(f"getprop {p}" for p in DEVICE_INFO_PROPS)
    values = [v.strip() for v in shell(device, getprop_cmd).splitlines()]
    while len(values) < len(DEVICE_INFO_PROPS):
        values.append("")
    for key, val in zip(DEVICE_INFO_PROPS, values):
        info[key] = val or "-"

    def _wm(prop: str) -> str:
        for line in shell(device, prop).splitlines():
            if ":" in line:
                return line.split(":", 1)[1].strip() or "-"
        return "-"

    info["screen_size"] = _wm("wm size")
    info["screen_density"] = _wm("wm density")

    batt = {"level": "-", "status": "-", "temperature": "-",
            "AC powered": "-", "USB powered": "-"}
    for line in shell(device, "dumpsys battery").splitlines():
        line = line.strip()
        for key in list(batt.keys()):
            prefix = f"{key}:"
            if line.startswith(prefix):
                batt[key] = line[len(prefix):].strip()
    status_map = {"1": "Unknown", "2": "Charging", "3": "Discharging",
                  "4": "Not charging", "5": "Full"}
    status_text = status_map.get(batt["status"], batt["status"])
    temp_c = "-"
    try:
        temp_c = f"{int(batt['temperature']) / 10:.1f}C"
    except (TypeError, ValueError):
        pass
    powered = []
    if batt["AC powered"].lower() == "true":
        powered.append("AC")
    if batt["USB powered"].lower() == "true":
        powered.append("USB")
    powered_str = ", ".join(powered) if powered else "battery"
    info["battery"] = f"{batt['level']}% ({status_text}, {powered_str}, {temp_c})"

    pkg = safe_detect_app(device)
    app_str = "-"
    if pkg:
        app_name = ""
        if app_name_resolver is not None:
            try:
                app_name = app_name_resolver(pkg) or ""
            except Exception:
                app_name = ""
        app_str = (f"{app_name}  ({pkg})" if app_name and app_name != "-" else pkg)
    info["app"] = app_str

    ip_addr = "-"
    for line in shell(device, "ip route").splitlines():
        if " src " in line:
            parts = line.split(" src ")
            if len(parts) > 1:
                ip_addr = parts[1].split()[0]
                break
    info["ip"] = ip_addr or "-"

    uptime_str = "-"
    try:
        secs = float(shell(device, "cat /proc/uptime").split()[0])
        hours, rem = divmod(int(secs), 3600)
        mins, _ = divmod(rem, 60)
        uptime_str = f"{hours}h {mins}m"
    except (ValueError, IndexError):
        pass
    info["uptime"] = uptime_str

    android = info.get("ro.build.version.release", "-")
    sdk = info.get("ro.build.version.sdk", "-")
    android_str = f"{android} (SDK {sdk})" if sdk and sdk != "-" else android
    brand = info.get("ro.product.brand", "-")
    manufacturer = info.get("ro.product.manufacturer", "-")
    if (manufacturer and manufacturer != "-"
            and manufacturer.lower() != brand.lower()):
        brand_str = f"{brand} / {manufacturer}"
    else:
        brand_str = brand

    return {
        "status": "Connected",
        "serial": info.get("serial", "-"),
        "model": info.get("ro.product.model", "-"),
        "brand": brand_str,
        "android": android_str,
        "abi": info.get("ro.product.cpu.abi", "-"),
        "screen_size": info.get("screen_size", "-"),
        "density": info.get("screen_density", "-"),
        "app": app_str,
        "battery": info.get("battery", "-"),
        "ip": info.get("ip", "-"),
        "uptime": uptime_str,
    }


# ── Screen inspection (pure functions over the latest frame) ─────────────────

def pixel_color(img: Optional[np.ndarray], w: int, h: int,
                x: int, y: int) -> Dict[str, str]:
    """RGB/HEX of one pixel, or empty strings when out of bounds."""
    if img is None or not (0 <= y < h and 0 <= x < w):
        return {"hex": "", "rgb": ""}
    b, g, r = img[y, x][:3]
    r, g, b = int(r), int(g), int(b)
    return {"hex": f"#{r:02X}{g:02X}{b:02X}", "rgb": f"{r}, {g}, {b}"}


def check_color_at(img: Optional[np.ndarray], w: int, h: int, x: int, y: int,
                   hex_color: str, tolerance: int = 10) -> Dict[str, Any]:
    """Compare the pixel at (x, y) against *hex_color* within *tolerance*
    (per-channel Chebyshev distance)."""
    if img is None:
        return {"match": False, "error": "No screenshot"}
    x, y, tolerance = int(x), int(y), int(tolerance)
    if not (0 <= y < h and 0 <= x < w):
        return {"match": False, "error": "Out of bounds"}
    b, g, r = img[y, x][:3]
    r, g, b = int(r), int(g), int(b)
    actual_hex = f"#{r:02X}{g:02X}{b:02X}"
    target = (hex_color or "").lstrip("#")
    if len(target) != 6:
        return {"match": False, "error": "Invalid hex"}
    try:
        tr = int(target[0:2], 16)
        tg = int(target[2:4], 16)
        tb = int(target[4:6], 16)
    except ValueError:
        return {"match": False, "error": "Invalid hex"}
    dist = max(abs(r - tr), abs(g - tg), abs(b - tb))
    return {"match": dist <= tolerance, "actual": actual_hex,
            "dist": dist, "actual_rgb": f"{r}, {g}, {b}"}


def ensure_region_in_filename(path: str, x: int, y: int, w: int, h: int) -> str:
    """Make sure a saved crop filename ends with ``_x_y_w_h.ext`` so Macro2k
    can parse the region back out of it later."""
    base, ext = os.path.splitext(path)
    if re.search(r"_\d+_\d+_\d+_\d+(?:\.\d+)?$", base):
        return path
    return f"{base}_{x}_{y}_{w}_{h}{ext}"


# ── Asset library ─────────────────────────────────────────────────────────────

def list_image_assets(out_dir: str, limit: int = 200) -> List[Dict[str, Any]]:
    """List image assets under *out_dir* (recursively), newest first."""
    if not os.path.isdir(out_dir):
        return []
    items: List[Dict[str, Any]] = []
    for root, _dirs, files in os.walk(out_dir):
        for fname in files:
            if not fname.lower().endswith(_IMAGE_EXTS):
                continue
            path = os.path.join(root, fname)
            try:
                st = os.stat(path)
            except OSError:
                continue
            rel = os.path.relpath(path, out_dir).replace("\\", "/")
            items.append({"name": rel, "path": path.replace("\\", "/"),
                          "size": st.st_size, "mtime": st.st_mtime})
    items.sort(key=lambda it: it["mtime"], reverse=True)
    for it in items:
        it.pop("mtime", None)
    return items[:limit]


def asset_thumbnail(out_dir: str, path: str, width: int = 96) -> str:
    """JPEG data-URL thumbnail for an image confined to *out_dir* (or "")."""
    try:
        safe_path = confined_path(out_dir, path, _IMAGE_EXTS)
        if not safe_path:
            return ""
        img = cv2.imread(safe_path)
        if img is None:
            return ""
        h, w = img.shape[:2]
        tw = max(1, int(width))
        th = max(1, int(h * tw / w))
        thumb = cv2.resize(img, (tw, th), interpolation=cv2.INTER_AREA)
        ok, buf = cv2.imencode(".jpg", thumb, [cv2.IMWRITE_JPEG_QUALITY, 80])
        if not ok:
            return ""
        return ("data:image/jpeg;base64,"
                + base64.b64encode(buf.tobytes()).decode("ascii"))
    except Exception:
        return ""


def delete_asset(out_dir: str, path: str) -> bool:
    """Delete an image strictly inside *out_dir*."""
    try:
        safe_path = confined_path(out_dir, path, _IMAGE_EXTS)
        if safe_path and os.path.isfile(safe_path):
            os.unlink(safe_path)
            return True
    except Exception:
        pass
    return False


# ── Template matching core ────────────────────────────────────────────────────

def run_template_match(matcher, screen: np.ndarray, template_path: str,
                       threshold: float, grayscale: bool, multiscale: bool,
                       all_matches: bool) -> Dict[str, Any]:
    """Run a template match against *screen*, returning either
    ``{"error": ...}`` or ``{"summary": ..., "rects": [[x, y, w, h, conf]]}``.
    Overlay push/logging stays at the call site."""
    path = (template_path or "").strip()
    if not path or not os.path.exists(path):
        return {"error": "Pick a valid template path"}
    grayscale = bool(grayscale)
    threshold = float(threshold)
    tpl = matcher.load(path, grayscale=grayscale)
    if tpl is None:
        log_warning(f"Could not load template: {path}")
        return {"error": "Could not load template"}
    th, tw = tpl.shape[:2]

    rects: List[List[float]] = []
    if all_matches:
        results = matcher.match_all(
            screen, tpl, threshold=threshold, use_grayscale=grayscale)
        for cx, cy, conf in results:
            rects.append([max(0, cx - tw // 2), max(0, cy - th // 2),
                          tw, th, float(conf)])
        summary = f"Found {len(results)} match(es)."
    else:
        scales = [0.8, 0.9, 1.0, 1.1, 1.2] if multiscale else None
        res = matcher.match(
            screen, tpl, threshold=threshold, use_grayscale=grayscale,
            multi_scale=multiscale, scales=scales)
        if res is None:
            return {"summary": f"No match >= {threshold:.2f}.", "rects": []}
        cx, cy, conf, scale = res
        sw, sh = int(tw * scale), int(th * scale)
        rects.append([max(0, cx - sw // 2), max(0, cy - sh // 2), sw, sh,
                      float(conf)])
        summary = (f"Match: center=({cx},{cy}) conf={conf:.3f} "
                   f"scale={scale:.2f}")
    return {"summary": summary, "rects": rects}
