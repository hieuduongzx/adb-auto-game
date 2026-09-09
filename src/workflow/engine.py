"""Execute JSON workflows against a connected device.

The engine wraps an :class:`~src.core.adb.auto.ADBGameAutomation` instance and
runs the **node graph** of each activity. It is shared by two front-ends:

* the **Run test** button in Macro2k Designer (design-time preview), and
* the standalone **runner GUI** (``apps/workflow_runner.py``).

Both feed it the exact same JSON, so a flow that runs in the designer runs
unchanged in the runner.

Each activity holds a directed **node graph** (``nodes`` + ``edges``). Execution
starts at the ``start`` node and follows output ports edge-by-edge:

* an **action** node (tap, swipe, …) runs, then follows its ``out`` port;
* an **if_image** node follows ``true`` or ``false`` depending on the match;
* a **loop** node follows ``body`` ``count`` times (wire the body back to the
  loop node to iterate), then ``done``;
* reaching an ``end`` node — or a port with no edge — ends the activity.

There are two activity modes:

* ``sequence``   — run the graph once (with ``maxRetries``), in order;
* ``background`` — run the graph in its own thread every ``pollInterval`` s.

JSON shape::

    {
      "name": "My Flow", "version": 2, "templatesDir": "out",
      "activities": [
        {
          "id": "daily", "name": "Daily", "type": "sequence",
          "enabled": true, "maxRetries": 1,
          "graph": {
            "nodes": [
              {"id": "n1", "type": "start", "x": 40,  "y": 40,  "params": {}},
              {"id": "n2", "type": "tap",   "x": 240, "y": 40,  "params": {"x": 100, "y": 200}},
              {"id": "n3", "type": "end",   "x": 440, "y": 40,  "params": {}}
            ],
            "edges": [
              {"from": "n1", "fromPort": "out", "to": "n2"},
              {"from": "n2", "fromPort": "out", "to": "n3"}
            ]
          }
        }
      ]
    }
"""
from __future__ import annotations

import json
import os
import random
import re
import threading
import time
from typing import Any, Callable, Dict, List, Optional

from src.core import ADBGameAutomation
from src.core.frida_speedhack import FridaSpeedhackManager
from src.utils import log_error, log_info, log_success, log_warning


# ── Node catalog ─────────────────────────────────────────────────────────────
#
# Single source of truth for the node types the engine understands. ``kind``
# drives traversal; ``outs`` lists the output port ids each node exposes. The
# designer UI keeps a richer mirror (icons + field widgets) keyed by the same
# names. Safety cap on total steps guards against runaway cycles.
MAX_STEPS = 100_000
MAX_CALL_DEPTH = 50  # guards against functions that (in)directly call themselves

NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "start":      {"label": "Bắt đầu",       "kind": "start",     "ins": 0, "outs": ["out"]},
    "end":        {"label": "Kết thúc",      "kind": "end",       "ins": 1, "outs": []},
    "stop":       {"label": "Dừng tất cả",   "kind": "stop",      "ins": 1, "outs": []},
    # A call returns a boolean: "true" when the function's walk reached an End
    # node, "false" when it dead-ended (e.g. a node inside timed out).
    "call":       {"label": "Gọi function",  "kind": "call",      "ins": 1, "outs": ["true", "false"]},
    "note":       {"label": "Ghi chú",       "kind": "note",      "ins": 0, "outs": []},
    "tap":        {"label": "Chạm",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "multi_tap":  {"label": "Chạm nhiều điểm", "kind": "action",    "ins": 1, "outs": ["out"]},
    "double_tap": {"label": "Chạm đúp",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_random": {"label": "Chạm ngẫu nhiên","kind": "action",   "ins": 1, "outs": ["out"]},
    "long_press": {"label": "Giữ",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe":      {"label": "Vuốt",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe_dir":  {"label": "Vuốt hướng",    "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait":       {"label": "Chờ",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait_random":{"label": "Chờ ngẫu nhiên","kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_image":  {"label": "Chạm ảnh",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_image": {"label": "Chờ ảnh",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # "…_any" variants take a *list* of templates and match ANY one of them — the
    # node-graph way to express "see image A or B" (an OR over several images).
    "tap_image_any":  {"label": "Chạm 1 trong ảnh", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_image_any": {"label": "Chờ 1 trong ảnh",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_text":  {"label": "Chờ chữ",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # ── Color (pixel) nodes — match a pixel/region against a #RRGGBB colour
    # with a per-channel tolerance (same semantics as DevScope's Inspect color:
    # match when max(ΔR,ΔG,ΔB) <= tolerance).
    "tap_color":  {"label": "Chạm màu",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_color": {"label": "Chờ màu",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_color":   {"label": "Nếu thấy màu",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "read_color": {"label": "Đọc màu → biến","kind": "action",    "ins": 1, "outs": ["out"]},
    "send_text":  {"label": "Nhập văn bản",  "kind": "action",    "ins": 1, "outs": ["out"]},
    "key":        {"label": "Phím",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "back":       {"label": "Back",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "home":       {"label": "Home",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "launch_app": {"label": "Mở ứng dụng",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "screenshot": {"label": "Chụp màn hình", "kind": "action",    "ins": 1, "outs": ["out"]},
    "log":        {"label": "Ghi nhật ký",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "set_var":    {"label": "Đặt biến",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "calc_var":   {"label": "Tính biến",     "kind": "action",    "ins": 1, "outs": ["out"]},
    "read_var":   {"label": "Đọc chữ → biến","kind": "action", "ins": 1, "outs": ["out"]},
    "parse_var":  {"label": "Tách chữ → biến","kind": "action", "ins": 1, "outs": ["out"]},
    "break":      {"label": "Thoát vòng lặp","kind": "action",    "ins": 1, "outs": ["out"]},
    "if_image":   {"label": "Nếu thấy ảnh",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_image_any":{"label": "Nếu thấy 1 trong ảnh","kind": "condition","ins": 1, "outs": ["true", "false"]},
    "if_text":    {"label": "Nếu thấy chữ",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_var":     {"label": "Nếu biến",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "loop":       {"label": "Lặp lại",       "kind": "loop",      "ins": 1, "outs": ["body", "done"]},
    "parallel":   {"label": "Chạy song song","kind": "parallel",  "ins": 1, "outs": []},
    # Sequential fallback: run branch 1; if that branch fails (a block returns
    # false), stop that branch and try branch 2, then 3... If every wired branch
    # fails, continue from the "fail" port.
    "try_chain":  {"label": "Thử lần lượt",  "kind": "try_chain", "ins": 1, "outs": []},
    # Explicit "give up this try_chain branch, try the next one" — like break for
    # loops. Wire it inside a try_chain arm when you want to abandon the branch
    # without an actual action failure (e.g. after an if_image true path).
    "try_next":   {"label": "Thử nhánh kế",  "kind": "try_next",  "ins": 1, "outs": []},
    # Output ports are dynamic (count param) so outs is left empty here; the
    # engine reads params["count"] at runtime and the designer renders them live.
    "join":       {"label": "Gộp",           "kind": "join",      "ins": 1, "outs": ["out"]},
    "and":        {"label": "And",            "kind": "and",       "ins": 1, "outs": ["out"]},
    # Multi-way branch: each case is its own condition; the first true case routes
    # to its port "c{i}", else "default". Output ports are dynamic (per the node's
    # ``cases`` list) so ``outs`` here is only the static fallback hint.
    "switch":      {"label": "Rẽ nhánh",       "kind": "switch",    "ins": 1, "outs": ["default"]},
    "scroll_find": {"label": "Kéo đến ảnh",    "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Lặp thân ("body" quay về cổng "loop") đến khi template xuất hiện → "found".
    # maxLoops > 0 giới hạn số vòng; hết lượt mà chưa thấy → "fail". Gói gọn
    # pattern phổ biến nhất trong workflow thực tế: loop ∞ + if_image + break.
    "loop_until_image": {"label": "Lặp đến khi thấy ảnh", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    # Cùng cơ chế loop_until nhưng điều kiện thoát là màu / chữ / biến — bộ ba
    # còn thiếu so với bản ảnh (trước đây phải dựng loop ∞ + if_* + break).
    "loop_until_color": {"label": "Lặp đến khi thấy màu", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    "loop_until_text":  {"label": "Lặp đến khi thấy chữ", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    "loop_until_var":   {"label": "Lặp đến khi biến thoả", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    # Tìm ảnh và LƯU toạ độ tâm vào 2 biến (x/y) — để tính toán offset, so sánh
    # vị trí… thay vì chỉ dùng được qua "chạm ảnh vừa thấy".
    "find_image_pos": {"label": "Tìm ảnh → toạ độ", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chờ màn hình NGỪNG thay đổi (hết animation/loading) rồi mới đi tiếp.
    "wait_stable": {"label": "Chờ màn hình ổn định", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chạm MỌI vị trí khớp template trên màn hình hiện tại (match_all + NMS).
    # true khi chạm được ≥1 vị trí — quét thu thập vật phẩm/phần thưởng.
    "tap_all_images": {"label": "Chạm tất cả ảnh", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Quản lý app: dừng hẳn (am force-stop, tuỳ chọn pm clear) — cặp với
    # launch_app để làm flow "game treo → restart".
    "app_stop": {"label": "Dừng ứng dụng", "kind": "action", "ins": 1, "outs": ["out"]},
    # Điều kiện: app/tiêu đề cửa sổ hiện tại có chứa chuỗi? (ADB: package
    # foreground; Win32: tiêu đề cửa sổ) — phát hiện game crash.
    "if_app": {"label": "Nếu app đang mở", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Gỡ cài đặt app (pm uninstall, tuỳ chọn -k giữ dữ liệu). ADB-only.
    "app_uninstall": {"label": "Gỡ ứng dụng", "kind": "action", "ins": 1, "outs": ["out"]},
    # Cài APK từ file trên PC (pm install qua adb install) — cặp đối xứng với
    # app_uninstall. ADB-only.
    "app_install": {"label": "Cài ứng dụng (APK)", "kind": "action", "ins": 1, "outs": ["out"]},

    # Thoát app ĐANG mở (không cần package): ADB force-stop app foreground;
    # Win32 đóng cửa sổ mục tiêu.
    "app_exit": {"label": "Thoát app hiện tại", "kind": "action", "ins": 1, "outs": ["out"]},
    "random_branch":{"label":"Chọn ngẫu nhiên","kind": "random",    "ins": 1, "outs": []},
    "format_var":  {"label": "Định dạng chuỗi","kind": "action",    "ins": 1, "outs": ["out"]},
    "notify":      {"label": "Thông báo",       "kind": "action",    "ins": 1, "outs": ["out"]},
    # ── Device / time ────────────────────────────────────────────────────────
    # Read the wall clock, wait until a clock time, gate on a time window, and
    # read live device properties (battery, current app, resolution…) into a var.
    "get_time":    {"label": "Lấy giờ → biến",  "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait_until":  {"label": "Hẹn giờ",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "if_time":     {"label": "Nếu trong khung giờ","kind": "condition","ins": 1, "outs": ["true", "false"]},
    "device_info": {"label": "Thông tin thiết bị → biến","kind": "action","ins": 1, "outs": ["out"]},
    "screen_power":{"label": "Bật/tắt màn hình", "kind": "action",    "ins": 1, "outs": ["out"]},
    # Màn hình thiết bị đang bật? (cặp đọc cho screen_power). ADB-only.
    "if_screen_on":{"label": "Nếu màn hình đang bật", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chạy một câu adb shell tuỳ ý, lưu stdout vào biến — cửa thoát cho những
    # thứ chưa có node riêng. ADB-only.
    "adb_shell":   {"label": "ADB shell → biến", "kind": "action", "ins": 1, "outs": ["out"]},

    # Launch the *emulator process itself* (LDPlayer/MuMu/Nox/MEmu/BlueStacks) on
    # the PC — unlike ``launch_app`` which opens an app *inside* an already-running
    # device. Optional ``at`` (HH:MM) waits until that clock time first, so a flow
    # can, on its own, sit idle until 07:00 then boot the emulator (no Task
    # Scheduler / PC-wake needed — the PC is already on running this tool).
    "launch_emulator": {"label": "Mở giả lập", "kind": "action", "ins": 1, "outs": ["out"]},
    # Is an emulator instance booted & its ADB responding? "last" (default)
    # re-checks the instance saved by the last successful launch_emulator, so a
    # flow can skip the boot when "the one I set" is already up.
    "if_emulator": {"label": "If emulator ready", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Poll until the emulator finishes Android boot (adb connect +
    # sys.boot_completed == 1) or until timeout — true when ready, false on
    # timeout/unresolvable target.
    "wait_emulator": {"label": "Wait emulator ready", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Resize the emulator's own PC window (the player UI), not the game inside
    # it. width/height describe the CLIENT area (the Android screen) — the
    # title bar is compensated for, otherwise the emulator letterboxes the
    # device with black side bars. Pure Win32 on the player process' window —
    # no ADB, no controller, so it works in ADB flows too (e.g. snap MuMu's
    # screen to 1920×1080 right after Launch emulator). "last" reuses the
    # instance the last successful launch_emulator saved.
    "resize_emulator": {"label": "Đổi kích thước giả lập", "kind": "action", "ins": 1, "outs": ["out"]},
    # Kill the emulator instance: the family's console shutdown when it exists
    # (LDPlayer/MuMu/Nox/MEmu; BlueStacks has none), else taskkill the player
    # window. "last" reuses the instance the last successful launch_emulator
    # saved.
    "kill_emulator": {"label": "Tắt giả lập", "kind": "action", "ins": 1, "outs": ["out"]},
    # Reboot a wedged instance (frozen UI / ADB gone) — console reboot when the
    # family has one, else kill the player + relaunch. Optional wait polls
    # sys.boot_completed so the next node can drive the fresh boot.
    "restart_emulator": {"label": "Restart giả lập", "kind": "action", "ins": 1, "outs": ["out"]},
    # Set the *device* resolution (Android screen px + DPI) — the value the
    # templates were cropped against. resize_emulator only changes the PC
    # window, so a 1920×1080 window over a 1600×900 device still letterboxes.
    # MuMu-only (its console exposes the resolution_* setting keys).
    "emulator_resolution": {"label": "Resolution giả lập", "kind": "action", "ins": 1, "outs": ["out"]},
    # ── Win32 (điều khiển cửa sổ chương trình PC) ─────────────────────────────
    # Only meaningful when the flow's controller is "win32". Tap/swipe/image/
    # color/OCR nodes already work on Win32 via the shared capture pipeline;
    # these cover the window-lifecycle actions ADB nodes can't express.
    "win_send_text":{"label": "Nhập văn bản PC", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_key":      {"label": "Phím PC (VK)", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_hotkey":   {"label": "Tổ hợp phím PC", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_escape":   {"label": "Phím Escape", "kind": "action", "ins": 1, "outs": ["out"]},
    # Chuột phải / giữa + con lăn + di chuột (hover) — những thứ WM_LBUTTON*
    # không diễn tả được nhưng app/game PC dùng liên tục.
    "win_click":    {"label": "Click chuột PC", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_scroll":   {"label": "Cuộn con lăn", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_mouse_move": {"label": "Di chuột (hover)", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_launch":   {"label": "Mở chương trình", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_activate": {"label": "Đưa cửa sổ lên trước", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_close":    {"label": "Đóng cửa sổ", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_resize":   {"label": "Thay đổi kích thước", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_move":     {"label": "Di chuyển cửa sổ", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_minimize": {"label": "Thu nhỏ", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_maximize": {"label": "Phóng to", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_restore":  {"label": "Khôi phục", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_always_on_top": {"label": "Luôn trên cùng", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_set_title": {"label": "Đổi tiêu đề", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_style":    {"label": "Đổi kiểu cửa sổ", "kind": "action", "ins": 1, "outs": ["out"]},
    # Điều kiện Win32 (trước đây mode Win32 KHÔNG có condition nào): cửa sổ mục
    # tiêu còn sống / đang foreground / đang thu nhỏ, và bản chờ có timeout.
    "win_if_window":  {"label": "Nếu cửa sổ …", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "win_wait_window":{"label": "Chờ cửa sổ …", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Đọc thuộc tính cửa sổ mục tiêu vào biến (đối xứng với device_info của ADB).
    "win_info":     {"label": "Thông tin cửa sổ → biến", "kind": "action", "ins": 1, "outs": ["out"]},
}


# ── Emulator launch specs ─────────────────────────────────────────────────────
#
# Per-family console executable + argv template for booting one instance, plus
# the default install dirs to auto-discover the console when the user leaves the
# path blank. ``{index}`` = instance number, ``{instance}`` = BlueStacks instance
# name. A ``custom`` command (with ``{index}``/``{path}`` placeholders) always
# overrides these — the escape hatch for non-standard installs. The per-family
# first-instance ADB port + step mirror src/core/adb/constants.py so a launch can
# poll the right ``127.0.0.1:PORT`` until the emulator's ADB comes up.
EMULATOR_CONSOLES: Dict[str, Dict[str, Any]] = {
    "ldplayer": {
        "exes": ["ldconsole.exe", "dnconsole.exe"],
        "args": ["launch", "--index", "{index}"],
        "quit_args": ["quit", "--index", "{index}"],
        "restart_args": ["reboot", "--index", "{index}"],
        "dirs": [r"C:\LDPlayer\LDPlayer9", r"C:\LDPlayer\LDPlayer64",
                 r"C:\ChangZhi\LDPlayer9", r"D:\LDPlayer\LDPlayer9"],
        "port0": 5555, "step": 2,
    },
    "mumu": {
        "exes": ["MuMuManager.exe"],
        "args": ["control", "-v", "{index}", "launch"],
        "quit_args": ["control", "-v", "{index}", "shutdown"],
        "restart_args": ["control", "-v", "{index}", "restart"],
        # ``info`` reports the instance's REAL adb_port — MuMu Global's ports do
        # not always follow 16384+32*index (index 2 answers on 16449, not
        # 16448), so asking beats deriving whenever the console is reachable.
        "info_args": ["info", "-v", "{index}"],
        # MuMu's console also drives the *device* resolution (settings keys),
        # which plain Win32 window sizing can't reach.
        "res_keys": {"width": "resolution_width.custom",
                     "height": "resolution_height.custom",
                     "dpi": "resolution_dpi.custom",
                     "mode": "resolution_mode"},
        # MuMu 12 keeps the console in <install>\shell; the newer 5.x/6.x
        # (incl. Global) builds moved it to <install>\nx_main — "subdirs" lets
        # a bare install dir resolve either layout.
        "subdirs": ["shell", "nx_main"],
        "dirs": [r"C:\Program Files\Netease\MuMuPlayer-12.0",
                 r"C:\Program Files\Netease\MuMuPlayerGlobal-12.0",
                 r"C:\Program Files\Netease\MuMuPlayer",
                 r"C:\Program Files\Netease\MuMuPlayerGlobal"],
        "port0": 16384, "step": 32,
    },
    "nox": {
        "exes": ["NoxConsole.exe"],
        "args": ["launch", "-index:{index}"],
        "quit_args": ["quit", "-index:{index}"],
        "restart_args": ["reboot", "-index:{index}"],
        "dirs": [r"C:\Program Files (x86)\Nox\bin", r"C:\Program Files\Nox\bin"],
        "port0": 62001, "step": 1,
    },
    "memu": {
        "exes": ["memuc.exe"],
        "args": ["start", "-i", "{index}"],
        "quit_args": ["stop", "-i", "{index}"],
        "restart_args": ["reboot", "-i", "{index}"],
        "dirs": [r"C:\Program Files\Microvirt\MEmu", r"C:\Program Files (x86)\Microvirt\MEmu"],
        "port0": 21503, "step": 1,
    },
    "bluestacks": {
        # HD-Player has no shutdown/restart verb — kill/restart fall back to
        # taskkill + relaunch of the player window's process tree.
        "exes": ["HD-Player.exe"],
        "args": ["--instance", "{instance}"],
        "dirs": [r"C:\Program Files\BlueStacks_nxt", r"C:\Program Files\BlueStacks"],
        "port0": 5555, "step": 10,
    },
}

# Last successful launch_emulator payload ({emulator, index, port, serial, …}).
# if_emulator's "last" option reads this back so a flow can check "is the
# emulator I used before still the one running?" across runs. Resolved via
# data_root() so frozen builds write to the writable user-data folder (next to
# the app, or %LOCALAPPDATA% for a read-only install), never inside _MEIPASS.
def _emulator_state_path() -> str:
    from src.utils import data_root
    return os.path.join(data_root(), "data", "emulator_state.json")

# Lowercased exe-basename prefixes of each family's *player* UI process — the
# console exes in EMULATOR_CONSOLES (ldconsole / MuMuManager / …) run headless,
# so resizing the window means finding the player process instead. Matched via
# basename prefix: MuMuPlayer.exe → "mumuplayer", HD-Player.exe → "hd-player".
EMU_PLAYER_EXES: Dict[str, List[str]] = {
    "ldplayer": ["dnplayer", "ldplayer"],
    "mumu": ["mumuplayer", "nemuplayer", "mumunxdevice"],
    "nox": ["nox"],
    "memu": ["memu"],
    "bluestacks": ["hd-player", "bluestacks"],
}


def _process_image_path(pid: int) -> str:
    """Full exe path of *pid* ("" for elevated/protected or non-Windows)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.restype = ctypes.c_void_p
        handle = kernel32.OpenProcess(0x1000, False, int(pid))  # PROCESS_QUERY_LIMITED_INFORMATION
        if not handle:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(32768)
            size = ctypes.c_ulong(len(buf))
            if not kernel32.QueryFullProcessImageNameW(ctypes.c_void_p(handle), 0, buf, ctypes.byref(size)):
                return ""
            return buf.value
        finally:
            kernel32.CloseHandle(ctypes.c_void_p(handle))
    except Exception:
        return ""


def _emulator_render_child(hwnd: int) -> Optional[tuple]:
    """Largest child window of an emulator player = its Android render surface.

    MuMu (and the other Qt-based players) put a toolbar strip inside the same
    client area — MuMu's is 40px tall — so the client rect is NOT the device
    view: a client of 1920×1080 leaves the render child at 1920×1040, which is
    no longer 16:9, and the player letterboxes the device inside it → black
    bars down both sides. Returns ``(hwnd, width, height)`` of that child, or
    None when the player draws straight into its own client area.
    """
    try:
        import win32gui
    except ImportError:
        return None
    kids: List[int] = []
    try:
        win32gui.EnumChildWindows(hwnd, lambda c, _: kids.append(c), None)
    except Exception:
        return None
    best: Optional[tuple] = None
    for c in kids:
        try:
            l, t, r, b = win32gui.GetWindowRect(c)
        except Exception:
            continue
        w, h = r - l, b - t
        if w <= 0 or h <= 0:
            continue
        if best is None or w * h > best[1] * best[2]:
            best = (c, w, h)
    return best


def _find_emulator_window(kind: str, install_dir: str = "") -> Optional[int]:
    """Locate an emulator family's visible main window; largest one wins.

    A top-level window qualifies when its process exe basename starts with one
    of the family's :data:`EMU_PLAYER_EXES` prefixes. When ``install_dir`` is
    known (node param / saved launch_emulator state), windows whose process
    lives under it are preferred — several emulator versions installed side by
    side all match the same family prefixes. Falls back to the window title
    (which usually carries the brand) when the process path is unreadable.
    """
    try:
        import win32gui
        import win32process
    except ImportError:
        return None
    prefixes = EMU_PLAYER_EXES.get(kind, [])
    base = os.path.normcase(os.path.normpath(install_dir)) if install_dir else ""
    best: Optional[tuple] = None  # (under_install_dir, area, hwnd)

    def _cb(hwnd, _):
        nonlocal best
        if not win32gui.IsWindowVisible(hwnd):
            return
        title = (win32gui.GetWindowText(hwnd) or "").strip()
        if not title:
            return  # skip invisible-named helper windows
        try:
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
        except Exception:
            return
        exe_path = _process_image_path(pid)
        name = os.path.basename(exe_path or "").lower()
        under = False
        if name:
            if not any(name.startswith(pre) for pre in prefixes):
                return
            if base and exe_path:
                exe_dir = os.path.normcase(os.path.normpath(os.path.dirname(exe_path)))
                under = exe_dir.startswith(base) or exe_dir.startswith(
                    os.path.normcase(os.path.normpath(os.path.dirname(base)))
                )
        else:
            # Can't read the exe (elevated) — trust the window title instead.
            if not any(pre in title.lower() for pre in prefixes + [kind]):
                return
        try:
            l, t, r, b = win32gui.GetWindowRect(hwnd)
        except Exception:
            return
        key = (under, abs((r - l) * (b - t)), hwnd)
        if best is None or key > best:
            best = key

    try:
        win32gui.EnumWindows(_cb, None)
    except Exception:
        return None
    return best[2] if best else None

# Condition node types a switch case may use — only the *instant* ones (no
# wait_* timeout blocking, no tap_* side-effect), so evaluating one case never
# stalls the others. Kept in sync with the designer's case-type dropdown.
SWITCH_CASE_TYPES = ("if_image", "if_image_any", "if_text", "if_var", "if_time",
                     "if_color", "if_app", "if_screen_on", "win_if_window")


class WorkflowEngine:
    """Run a JSON workflow, honouring pause/stop and the sequence/background split."""

    def __init__(
        self,
        automation: Optional[ADBGameAutomation] = None,
        ocr_backend: Optional[str] = None,
    ) -> None:
        self.auto = automation or ADBGameAutomation(ocr_backend=ocr_backend)
        # Match images exactly like the Dev Helper tester: single scale (1.0) at the
        # given threshold. Templates are QuickCropped on the same device at native
        # resolution, so the auto-orientation scale-sweep (0.8–1.2) + portrait
        # threshold-loosening only produces shifted / false matches here — the very
        # reason a tap that's correct in the tester lands wrong in a run.
        self.auto.auto_orientation_detection = False

        self.flow: Dict[str, Any] = {}
        self.flow_path: Optional[str] = None
        self.templates_base: str = ""
        # Global workflow variables — declared once at the flow top level
        # (``globals``) and seeded into EVERY activity/thread before its own
        # activity-local vars. Lets a counter or flag set in one place be seen
        # by every block in the workflow. Runtime writes to a global name keep
        # the shared dict in sync so other threads read the latest value.
        self._globals: Dict[str, Any] = {}
        # Target Android package for this flow (top-level ``package`` key).
        # Independent of speedhack; used as the default inject target and a
        # project-level app id. Legacy files may still nest it under speedhack.
        self.package: str = ""
        # Speedhack: a Frida clock_gettime time-scale, configured per-flow under
        # the top-level ``speedhack`` key ({enabled, speed}). The engine owns the
        # manager so both the designer's "Run test" and the runner GUI get it for
        # free. Package comes from ``self.package``. See frida_speedhack.py.
        self.speedhack_cfg: Dict[str, Any] = {}
        self._speedhack: Optional[FridaSpeedhackManager] = None
        self._speedhack_stop: Optional[threading.Event] = None
        self._speed_scale: float = 1.0
        # Reusable subroutines, keyed by id. Each value is a function dict with
        # its own ``graph`` (nodes + edges); a ``call`` node runs one inline.
        self._functions: Dict[str, Dict[str, Any]] = {}
        # Per-thread execution context. The sequence thread, every parallel branch
        # and every background activity each run a graph CONCURRENTLY; if they
        # shared one vars dict / last-found-position they would clobber each other
        # (a background popup-watcher resetting the main farm's variables, etc.).
        # Backing _vars/_last_pos/_break_loop with thread-local storage isolates
        # them automatically — see the properties below. A ``call`` runs on the
        # caller's thread, so a function correctly shares its caller's context.
        self._ctx = threading.local()
        self._debug_step = False
        self._debug_gate = threading.Event()
        self._debug_gate.set()
        self.failure_screenshot_dir: Optional[str] = None
        # When True (the designer's test runs), a failure screenshot is captured
        # for EVERY final action failure — not just nodes that opted in via
        # screenshotOnFail — so the designer can show "what the screen looked
        # like when this block failed" without per-node setup.
        self.capture_failures_always = False
        # When True (designer only), image/color/OCR matches emit ``on_match``
        # with rects + confidence so the Preview tab can draw a live overlay.
        # Off in the standalone runner — no UI to paint and no need for the
        # best-score-below-threshold extra match work on every miss.
        self.report_matches = False

        self.running = False
        self._stop = threading.Event()
        self._pause = threading.Event()
        self._pause.set()  # not paused

        self._seq_thread: Optional[threading.Thread] = None
        self._bg_threads: Dict[str, threading.Thread] = {}
        self._bg_stop: Dict[str, threading.Event] = {}

        # GUI hooks; all optional.
        self.callbacks: Dict[str, List[Callable]] = {
            "on_start": [], "on_stop": [],
            "on_activity_start": [], "on_activity_complete": [],
            "on_node": [],  # fired with the node id about to execute (None = idle)
            # fired after a node runs: (node_id, status, port). status is "ok" or
            # "fail" (an action whose handler returned False); port is the output
            # actually taken (a condition's "true"/"false", a loop's "body"/"done",
            # else "out"). Lets the designer paint the executed path + branch taken.
            "on_node_done": [],
            # fired when a per-node delayBefore/delayAfter wait starts or ends:
            # (node_id, phase, seconds). phase is "before" | "after" while waiting,
            # or None when the wait finishes / is cancelled. seconds is the full
            # wait length on start (0 on end). Designer shows a live countdown.
            "on_node_delay": [],
            # fired whenever a variable changes: (name, value). Lets the designer
            # show a live "current variables" panel during a test run.
            "on_var": [],
            # fired after a failure screenshot is written: (node_id, path). The
            # designer shows it in the inspector when the failed node is selected.
            "on_fail_shot": [],
            # fired after a template/color/OCR probe: one dict with rects
            # [{x,y,w,h,conf,ok,label}, …], threshold, template name, optional
            # search region. Designer paints these on the Preview canvas.
            "on_match": [],
        }

        # Dispatch table for action nodes: type -> handler(node, params) -> bool.
        self._actions: Dict[str, Callable[[Dict, Dict], bool]] = {
            "tap": self._a_tap,
            "multi_tap": self._a_multi_tap,
            "double_tap": self._a_double_tap,
            "tap_random": self._a_tap_random,
            "long_press": self._a_long_press,
            "swipe": self._a_swipe,
            "swipe_dir": self._a_swipe_dir,
            "wait": self._a_wait,
            "wait_random": self._a_wait_random,
            "send_text": self._a_send_text,
            "key": self._a_key,
            "back": self._a_back,
            "home": self._a_home,
            "launch_app": self._a_launch_app,
            "screenshot": self._a_screenshot,
            "log": self._a_log,
            "set_var": self._a_set_var,
            "calc_var": self._a_calc_var,
            "read_var": self._a_read_var,
            "parse_var": self._a_parse_var,
            "break":      self._a_break,
            "format_var": self._a_format_var,
            "notify":     self._a_notify,
            "get_time":     self._a_get_time,
            "wait_until":   self._a_wait_until,
            "device_info":  self._a_device_info,
            "screen_power": self._a_screen_power,
            "adb_shell":    self._a_adb_shell,
            "read_color":   self._a_read_color,
            "launch_emulator": self._a_launch_emulator,
            "resize_emulator": self._a_resize_emulator,
            "kill_emulator":   self._a_kill_emulator,
            "restart_emulator": self._a_restart_emulator,
            "emulator_resolution": self._a_emulator_resolution,
            "win_send_text":self._a_send_text,
            "win_key":      self._a_key,
            "win_hotkey":   self._a_win_hotkey,
            "win_escape":   self._a_back,
            "win_click":    self._a_win_click,
            "win_scroll":   self._a_win_scroll,
            "win_mouse_move": self._a_win_mouse_move,
            "win_launch":   self._a_win_launch,
            "win_activate": self._a_win_activate,
            "win_close":    self._a_win_close,
            "win_resize":   self._a_win_resize,
            "win_move":     self._a_win_move,
            "win_minimize": self._a_win_minimize,
            "win_maximize": self._a_win_maximize,
            "win_restore":  self._a_win_restore,
            "win_always_on_top": self._a_win_always_on_top,
            "win_set_title": self._a_win_set_title,
            "win_style":    self._a_win_style,
            "win_info":     self._a_win_info,
            "app_stop":     self._a_app_stop,
            "app_uninstall": self._a_app_uninstall,
            "app_install":  self._a_app_install,
            "app_exit":     self._a_app_exit,
        }

    # ── Per-thread execution context ─────────────────────────────────────────
    # These read/write the *current thread's* slot, so the existing
    # ``self._vars[...]`` / ``self._last_pos`` accesses scattered through the
    # handlers stay unchanged but become thread-isolated.

    def _set_var(self, name: str, value: Any) -> None:
        """Write a variable and notify ``on_var`` subscribers (live var panel).

        If ``name`` is a declared global, the shared ``_globals`` dict is kept
        in sync so other threads/activities see the latest value too.
        """
        if not name:
            return
        self._vars[name] = value
        if name in self._globals:
            self._globals[name] = value
        self._emit("on_var", name, value)

    @property
    def _vars(self) -> Dict[str, Any]:
        v = getattr(self._ctx, "vars", None)
        if v is None:
            v = {}
            self._ctx.vars = v
        return v

    @_vars.setter
    def _vars(self, value: Dict[str, Any]) -> None:
        self._ctx.vars = value if value is not None else {}

    @property
    def _last_pos(self) -> Optional[tuple]:
        return getattr(self._ctx, "last_pos", None)

    @_last_pos.setter
    def _last_pos(self, value: Optional[tuple]) -> None:
        self._ctx.last_pos = value

    @property
    def _break_loop(self) -> bool:
        return getattr(self._ctx, "break_loop", False)

    @_break_loop.setter
    def _break_loop(self, value: bool) -> None:
        self._ctx.break_loop = value

    # Set True when the current try_chain branch reaches an unhandled failure.
    # A condition returning false is only unhandled when its false/out path is not
    # wired; if the graph handles that path, the branch may still succeed.
    @property
    def _branch_failed(self) -> bool:
        return getattr(self._ctx, "branch_failed", False)

    @_branch_failed.setter
    def _branch_failed(self, value: bool) -> None:
        self._ctx.branch_failed = value

    # Set True when the current walk reaches an ``end`` node. A ``call`` resets
    # it before running its function graph and reads it after: reached End →
    # the call's "true" port, dead-ended (timeout etc.) → "false".
    @property
    def _reached_end(self) -> bool:
        return getattr(self._ctx, "reached_end", False)

    @_reached_end.setter
    def _reached_end(self, value: bool) -> None:
        self._ctx.reached_end = value

    @property
    def _try_chain_mode(self) -> bool:
        return getattr(self._ctx, "try_chain_mode", False)

    @_try_chain_mode.setter
    def _try_chain_mode(self, value: bool) -> None:
        self._ctx.try_chain_mode = value

    # ── Callbacks ────────────────────────────────────────────────────────────

    def on(self, event: str, fn: Callable) -> None:
        if event in self.callbacks:
            self.callbacks[event].append(fn)

    def _emit(self, event: str, *args) -> None:
        for fn in self.callbacks.get(event, []):
            try:
                fn(*args)
            except Exception as e:  # pragma: no cover - UI callback safety
                log_error(f"[workflow] callback {event} failed: {e}")

    # ── Flow loading ─────────────────────────────────────────────────────────

    def load(self, flow: Dict[str, Any], flow_path: Optional[str] = None) -> None:
        """Install a parsed flow dict. ``flow_path`` anchors relative templates."""
        self.flow = flow or {}
        self.flow_path = flow_path
        # Which backend drives the flow: "adb" (Android device/emulator) or
        # "win32" (a native Windows program window). Selected in the designer's
        # project settings and honoured by _ensure_ready().
        self._controller = str(self.flow.get("controller") or "adb").strip().lower()
        self._win32_cfg = dict(self.flow.get("win32") or {})
        self.speedhack_cfg = dict(self.flow.get("speedhack") or {})
        # Workflow package: prefer top-level key; migrate legacy speedhack.package.
        pkg = str(self.flow.get("package") or "").strip()
        if not pkg:
            pkg = str((self.speedhack_cfg or {}).get("package") or "").strip()
        self.package = pkg
        # OCR engine của flow ("tesseract" / "easyocr" / "paddleocr"…; rỗng = auto):
        # chọn trong Project settings của designer, áp dụng ở _ensure_ready().
        self._ocr_backend = str(self.flow.get("ocr") or "").strip().lower()
        # ADB frame source for this flow: "scrcpy" | "adb". Key "capture" (also
        # accept legacy captureBackend / capture_backend). Applied on load so
        # designer preview + runner + test runs share the same source.
        cap_raw = (
            self.flow.get("capture")
            if self.flow.get("capture") not in (None, "")
            else self.flow.get("captureBackend")
            if self.flow.get("captureBackend") not in (None, "")
            else self.flow.get("capture_backend")
        )
        self._capture_backend = str(cap_raw or "").strip().lower()
        self._apply_capture_backend()
        self._functions = {f.get("id"): f for f in (self.flow.get("functions") or []) if f.get("id")}
        # Global vars: declared at flow top level (``globals``), seeded into every
        # thread below. Reset the shared runtime dict on (re)load.
        self._globals = self._seed_vars({"vars": self.flow.get("globals") or []})

        base = (self.flow.get("templatesDir") or "").strip()
        anchors: List[str] = []
        if flow_path:
            anchors.append(os.path.dirname(os.path.abspath(flow_path)))
        anchors.append(os.getcwd())
        if base and os.path.isabs(base) and os.path.isdir(base):
            self.templates_base = base
        else:
            self.templates_base = ""
            for anchor in anchors:
                cand = os.path.join(anchor, base) if base else anchor
                if os.path.isdir(cand):
                    self.templates_base = cand
                    break
            if not self.templates_base:
                self.templates_base = anchors[0]
        log_info(
            f"[workflow] Loaded '{self.flow.get('name', 'flow')}' "
            f"({len(self.activities())} activities), templates@ {self.templates_base}"
        )

    def globals_snapshot(self) -> Dict[str, Any]:
        """Public copy of the shared global-vars dict (for GUI var panels)."""
        return dict(self._globals or {})

    @staticmethod
    def load_file(path: str) -> Dict[str, Any]:
        """Read + JSON-decode a flow file (raises on bad JSON/IO)."""
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)

    def activities(self) -> List[Dict[str, Any]]:
        return list(self.flow.get("activities", []) or [])

    def _resolve_template(self, raw: str) -> str:
        """Make a template path absolute, preferring the flow's templates dir."""
        raw = (raw or "").strip().replace("\\", "/")
        if not raw:
            return raw
        if os.path.isabs(raw) and os.path.exists(raw):
            return raw
        candidates = [os.path.join(self.templates_base, raw)]
        if self.flow_path:
            candidates.append(os.path.join(os.path.dirname(self.flow_path), raw))
        candidates.append(raw)
        for c in candidates:
            if os.path.exists(c):
                return c
        return candidates[0]

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def _apply_ocr_backend(self) -> None:
        """Đổi OCR engine của automation theo cấu hình flow (rỗng = giữ mặc định).

        Gọi sau khi backend (ADB/Win32) sẵn sàng — cả hai đều có ``self.auto.ocr``
        (OCRReader). Backend không khả dụng chỉ cảnh báo, không chặn run.
        """
        name = getattr(self, "_ocr_backend", "")
        if not name:
            return
        try:
            ocr = getattr(self.auto, "ocr", None)
            if ocr is None or getattr(ocr, "backend_name", None) == name:
                return
            if hasattr(self.auto, "set_ocr_backend"):
                ok = bool(self.auto.set_ocr_backend(name))
            else:
                ok = bool(ocr.set_backend(name))
            if ok:
                log_info(f"[workflow] OCR engine: {name}")
            else:
                log_warning(f"[workflow] OCR '{name}' không khả dụng — dùng engine mặc định")
        except Exception as e:
            log_warning(f"[workflow] Không đổi được OCR engine '{name}': {e}")

    def _apply_capture_backend(self) -> None:
        """Apply the flow's ADB capture source (scrcpy / adb screencap).

        Empty / missing key leaves the process-wide default alone (scrcpy).
        Only meaningful for ADB flows; Win32 captures windows, not this path.
        """
        name = getattr(self, "_capture_backend", "") or ""
        if name not in ("scrcpy", "adb"):
            return
        try:
            from src.core.adb.auto.scrcpy_capture import (
                get_capture_backend,
                set_capture_backend,
            )
            if get_capture_backend() == name:
                return
            set_capture_backend(name)
            log_info(f"[workflow] Capture backend: {name}")
        except Exception as e:
            log_warning(f"[workflow] Không đổi được capture backend '{name}': {e}")

    def _flow_has_node_type(self, *ntypes: str) -> bool:
        """True if any activity/function graph in the loaded flow contains a
        node of one of the given types."""
        graphs = [(a.get("graph") or {}) for a in (self.flow.get("activities") or [])]
        graphs += [(f.get("graph") or {}) for f in (self.flow.get("functions") or [])]
        return any(
            str(n.get("type")) in ntypes
            for g in graphs for n in (g.get("nodes") or [])
        )

    def _ensure_ready(self) -> bool:
        """Connect the selected backend + start continuous capture if needed."""
        if getattr(self, "_controller", "adb") == "win32":
            return self._ensure_ready_win32()
        try:
            if not self.auto.adb.device:
                self.auto.adb.check_adb_connection()
            if not self.auto.adb.device:
                # A flow with a launch_emulator / if_emulator / wait_emulator
                # node may legitimately start with no device — those nodes
                # boot/find the emulator and attach to its ADB
                # (_attach_adb_after_boot).
                if self._flow_has_node_type("launch_emulator", "if_emulator", "wait_emulator"):
                    log_info("[workflow] No device yet — an emulator node will boot/attach one")
                    self._apply_ocr_backend()
                    return True
                log_error("[workflow] No ADB device connected")
                return False
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
            self._apply_ocr_backend()
            return True
        except Exception as e:
            log_error(f"[workflow] Not ready: {e}")
            return False

    def _ensure_ready_win32(self) -> bool:
        """Attach to the target window + start window capture (Win32 backend).

        Swaps ``self.auto`` to a :class:`Win32GameAutomation` on first use (the
        engine builds an ADB backend by default in __init__), then attaches to
        the configured window."""
        try:
            from src.core.win32 import Win32GameAutomation
            if not isinstance(self.auto, Win32GameAutomation):
                try:
                    self.auto.stop_continuous_capture()
                except Exception:
                    pass
                self.auto = Win32GameAutomation(cfg=self._win32_cfg)
            else:
                self.auto.configure(self._win32_cfg)
            target = str(self._win32_cfg.get("window", "") or "").strip()
            has_launcher = self._flow_has_node_type("win_launch")
            if not self.auto.adb.device and target:
                self.auto.adb.check_adb_connection()  # attach an already-open window
            if not self.auto.adb.device:
                # A workflow may intentionally start the Windows program itself.
                # Do not require a Project-settings target before its Launch
                # program node has had a chance to create and attach the window.
                if has_launcher:
                    log_info("[workflow] No Win32 target yet — Launch program will start/attach it")
                    self._apply_ocr_backend()
                    return True
                log_error(
                    f"[workflow] Win32: không tìm thấy cửa sổ "
                    f"'{target}' — kiểm tra Project settings"
                )
                return False
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
            self._apply_ocr_backend()
            return True
        except Exception as e:
            log_error(f"[workflow] Win32 not ready: {e}")
            return False

    def start(self, background: bool = True, with_speedhack: bool = True) -> bool:
        """Run all enabled sequence activities once, then start backgrounds.

        ``with_speedhack`` lets a caller run the flow *without* auto-applying its
        speedhack config — the designer's "Run test" passes ``False`` so testing a
        flow never injects Frida; speedhack there is a separate, manual action.
        """
        if self.running:
            log_warning("[workflow] Already running")
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        self.running = True
        self._emit("on_start")

        if with_speedhack:
            self._start_speedhack()

        if background:
            self.start_all_background()

        self._seq_thread = threading.Thread(target=self._run_sequence, daemon=True)
        self._seq_thread.start()
        return True

    def start_graph(self, graph: Dict[str, Any], start_id: str, seed_act: Optional[Dict[str, Any]] = None, step: bool = False) -> bool:
        """Run one graph from an arbitrary node, used by designer debug tools."""
        if self.running:
            log_warning("[workflow] Already running")
            return False
        if not self._ensure_ready():
            return False
        self._stop.clear()
        self.auto._stop_event.clear()
        self._pause.set()
        self._debug_step = bool(step)
        if step:
            self._debug_gate.clear()
        else:
            self._debug_gate.set()
        self.running = True
        self._emit("on_start")
        self._seq_thread = threading.Thread(
            target=self._run_graph_from_node,
            args=(graph or {}, start_id, seed_act or {"vars": []}),
            daemon=True,
        )
        self._seq_thread.start()
        return True

    def _run_graph_from_node(self, graph: Dict[str, Any], start_id: str, seed_act: Dict[str, Any]) -> None:
        try:
            self._vars = self._seed_vars(seed_act)
            self._last_pos = None
            self._break_loop = False
            self._branch_failed = False
            self._try_chain_mode = False
            for k, v in self._vars.items():
                self._emit("on_var", k, v)
            self._run_graph(graph, start_id=start_id)
        except Exception as e:
            log_error(f"[workflow] Debug run error: {e}")
        finally:
            self._debug_step = False
            self._debug_gate.set()
            self.running = False
            self._emit("on_node", None)
            self._emit("on_stop")

    def _run_sequence(self) -> None:
        try:
            for act in self.activities():
                if self._stop.is_set():
                    break
                if act.get("type") == "background":
                    continue
                if not act.get("enabled", True):
                    continue
                self._run_activity(act)
                if self._stop.is_set():
                    break
                time.sleep(0.3)
            log_success("[workflow] Sequence finished")
        except Exception as e:
            log_error(f"[workflow] Sequence error: {e}")
        finally:
            if not self._bg_threads:
                self.running = False
                self._emit("on_stop")

    def _run_activity(self, act: Dict[str, Any]) -> bool:
        name = act.get("name") or act.get("id") or "activity"
        retries = max(1, int(act.get("maxRetries", 1) or 1))
        self._vars = self._seed_vars(act)
        self._last_pos = None
        self._break_loop = False
        self._branch_failed = False
        self._try_chain_mode = False
        self._emit("on_activity_start", act)
        for k, v in self._vars.items():
            self._emit("on_var", k, v)
        ok = False
        t0 = time.time()
        for attempt in range(1, retries + 1):
            if self._stop.is_set():
                break
            if attempt > 1:
                log_info(f"[workflow] Retry {name} ({attempt}/{retries})")
            log_info(f"[workflow] ▶ {name}")
            self._reached_end = False
            ok = self._run_graph(act.get("graph", {}) or {})
            # Same success rule as a function call: the walk must reach an End
            # node — a dead-end (e.g. a timed-out image wait with no false path)
            # is a failure. A stop (user or Stop node) is not painted as one.
            if ok and not self._stop.is_set():
                ok = self._reached_end
            if ok:
                break
        elapsed = time.time() - t0
        if ok:
            log_success(f"[workflow] ✔ {name} ({elapsed:.1f}s)")
        else:
            log_warning(f"[workflow] ✖ {name} ({elapsed:.1f}s)")
        self._emit("on_node", None)  # clear highlight between activities
        self._emit("on_activity_complete", act, ok)
        return ok

    # ── Graph traversal ──────────────────────────────────────────────────────

    @staticmethod
    def _build_adjacency(edges: List[Dict]) -> Dict[tuple, List[str]]:
        """Map ``(fromNodeId, fromPort) -> [targetNodeId, …]``."""
        adj: Dict[tuple, List[str]] = {}
        for e in edges or []:
            key = (e.get("from"), e.get("fromPort", "out"))
            adj.setdefault(key, []).append(e.get("to"))
        return adj

    @staticmethod
    def _next(adj: Dict[tuple, List[str]], node_id: str, port: str) -> Optional[str]:
        """First node wired to ``(node_id, port)`` (graphs use one wire/port)."""
        targets = adj.get((node_id, port))
        return targets[0] if targets else None

    def _run_graph(self, graph: Dict[str, Any], depth: int = 0, start_id: Optional[str] = None) -> bool:
        nodes = {n.get("id"): n for n in graph.get("nodes", []) or []}
        adj = self._build_adjacency(graph.get("edges", []) or [])
        if start_id:
            cur = start_id if start_id in nodes else None
            if cur is None:
                log_warning(f"[workflow] Start node id not found: {start_id}")
                return False
        else:
            start = next((n for n in nodes.values() if n.get("type") == "start"), None)
            if start is None:
                log_warning("[workflow] Graph has no start node")
                return False
            cur = self._next(adj, start.get("id"), "out")
        self._walk(nodes, adj, cur, {}, depth)
        return not self._branch_failed

    def _walk(self, nodes, adj, cur, counters, depth):
        """Follow edges from ``cur`` until a dead-end / end node / stop.

        ``counters`` is this walk's loop state (parallel branches get their own).
        """
        steps = 0
        while cur and not self._stop.is_set():
            self._pause.wait()
            if self._debug_step:
                self._debug_gate.wait()
                self._debug_gate.clear()
            steps += 1
            if steps > MAX_STEPS:
                log_warning("[workflow] Step cap reached — stopping graph (cycle?)")
                break
            node = nodes.get(cur)
            if node is None:
                break
            self._emit("on_node", cur)  # let the designer highlight the active node
            nid = cur                    # stable id for the post-run result event
            ntype = node.get("type")
            if ntype == "end":
                self._reached_end = True
                self._emit("on_node_done", nid, "ok", None)
                break
            # Per-node log line (designer's "Log khi chạy" field): auto-emit it
            # every time the block runs, filling {var} placeholders from vars.
            custom_log = node.get("log")
            if custom_log:
                log_info(f"[workflow] {self._format_msg(custom_log)}")
            spec = NODE_TYPES.get(ntype)
            kind = spec.get("kind") if spec else None
            params = node.get("params", {}) or {}

            # Universal pre-block pause ("Chờ trước"): wait, THEN run the block
            # (e.g. let the screen settle before searching for an image). The
            # legacy single `delay` param is read here as delayBefore.
            db = self._delay_val(node, "delayBefore", params)
            if db > 0:
                self._emit("on_node_delay", nid, "before", db)
                self._sleep(db)
                self._emit("on_node_delay", nid, None, 0)

            if kind == "stop":
                log_info("[workflow] Dừng theo node Stop")
                self._emit("on_node_done", nid, "ok", None)
                self.stop()
                break
            elif kind == "try_next":
                # Abandon the current try_chain arm and let the outer try_chain
                # advance to the next numbered port (or "fail" if none left).
                if self._try_chain_mode:
                    log_info("[workflow] ↩ thử nhánh kế — bỏ nhánh hiện tại")
                    self._branch_failed = True
                else:
                    log_warning("[workflow] 'Thử nhánh kế' ngoài Try in order — không có hiệu lực")
                self._emit("on_node_done", nid, "ok", None)
                break
            elif kind == "condition":
                try:
                    res = self._eval_condition(ntype, params)
                except Exception as e:
                    # A crash inside a condition counts as "false".
                    res = False
                    log_error(f"[workflow] Node '{ntype}' error: {e}")
                port = "true" if res else "false"
                self._emit("on_node_done", nid, "ok", port)  # branch taken
                nxt = self._next(adj, cur, port)
                if nxt is None:
                    nxt = self._next(adj, cur, "out")
                if self._try_chain_mode and not res and nxt is None:
                    self._branch_failed = True
                    break
                cur = nxt
            elif kind == "loop":
                if self._break_loop:
                    self._break_loop = False
                    log_info(f"[workflow] ↺ thoát vòng lặp sau {counters.get(cur, 0)} lần (break)")
                    counters[cur] = 0
                    loop_port = "done"
                elif self._truthy(params.get("infinite", False)):
                    steps = 0  # don't let the safety cap kill an intentional ∞ loop
                    loop_port = "body"
                else:
                    done = counters.get(cur, 0)
                    count = self._resolve_count(params.get("count", 1), default=1)
                    if done < count:
                        counters[cur] = done + 1
                        loop_port = "body"
                    else:
                        log_info(f"[workflow] ↺ vòng lặp xong {done} lần")
                        counters[cur] = 0
                        loop_port = "done"
                self._emit("on_node_done", nid, "ok", loop_port)
                cur = self._next(adj, cur, loop_port)
            elif kind == "loop_until":
                # Lặp đến khi <điều kiện>: mỗi lần (re-)enter node, kiểm tra một
                # lần. Thoả → "found"; break trong thân → "found" (thoát); hết
                # maxLoops → "fail"; còn lượt → "body" (thân quay về cổng
                # "loop"). delayBefore của node đóng vai trò poll interval.
                # Điều kiện tuỳ ntype: ảnh / màu / chữ / biến.
                what = self._loop_until_label(ntype, params)
                lu_port = None
                if self._break_loop:
                    self._break_loop = False
                    log_info(f"[workflow] ↺ thoát 'lặp đến khi {what}' sau {counters.get(cur, 0)} vòng (break)")
                    counters[cur] = 0
                    lu_port = "found"
                else:
                    if self._loop_until_hit(ntype, params):
                        log_info(f"[workflow] ↺ {what} sau {counters.get(cur, 0)} vòng")
                        counters[cur] = 0
                        lu_port = "found"
                    else:
                        done = counters.get(cur, 0)
                        max_loops = self._resolve_count(params.get("maxLoops", 0), default=0)
                        if max_loops > 0 and done >= max_loops:
                            log_warning(f"[workflow] ↺ chưa {what} sau {done} vòng — nhánh fail")
                            counters[cur] = 0
                            lu_port = "fail"
                        else:
                            counters[cur] = done + 1
                            steps = 0  # vòng lặp chủ ý — đừng để step cap cắt ngang
                            lu_port = "body"
                self._emit("on_node_done", nid, "ok" if lu_port != "fail" else "fail", lu_port)
                nxt = self._next(adj, cur, lu_port)
                if lu_port == "fail" and nxt is None:
                    # fail không đi dây → nhánh này coi như thất bại (đỏ), giống
                    # một condition false cụt trong try_chain.
                    self._branch_failed = True
                    break
                cur = nxt
            elif kind == "parallel":
                self._run_parallel(nodes, adj, cur, depth)
                # Execution after all branches is handled inside _run_parallel
                # (the last branch to hit a join node continues from join.out).
                # The parent walk ends here — no "done" port anymore.
                break
            elif kind == "join":
                # Barrier for parallel branches. The last branch to arrive
                # continues walking; all earlier arrivals stop here.
                ctx = getattr(self._ctx, "join_ctx", None)
                if ctx is not None:
                    with ctx["lock"]:
                        ctx["remaining"] -= 1
                        ctx["join_node"] = cur
                        is_last = ctx["remaining"] == 0
                    if not is_last:
                        # Not the last branch — stop this thread here.
                        self._emit("on_node_done", nid, "ok", None)
                        break
                    # Last branch: fall through and continue from "out".
                self._emit("on_node_done", nid, "ok", "out")
                cur = self._next(adj, cur, "out")
            elif kind == "and":
                expected = max(1, int(params.get("count", 2) or 2))
                ctx = getattr(self._ctx, "join_ctx", None)
                if ctx is None:
                    if expected <= 1:
                        self._emit("on_node_done", nid, "ok", "out")
                        cur = self._next(adj, cur, "out")
                    else:
                        log_warning(f"[workflow] And cần {expected} nhánh song song")
                        self._branch_failed = True
                        self._emit("on_node_done", nid, "fail", "out")
                        break
                else:
                    is_last, ok = self._and_arrive(ctx, cur, expected, self._branch_failed)
                    if not is_last:
                        self._emit("on_node_done", nid, "ok", None)
                        break
                    if not ok:
                        log_warning(f"[workflow] And fail: có nhánh lỗi trước khi gộp {expected} nhánh")
                        self._branch_failed = True
                        self._emit("on_node_done", nid, "fail", "out")
                        break
                    self._emit("on_node_done", nid, "ok", "out")
                    cur = self._next(adj, cur, "out")
            elif kind == "random":
                # Pick one of count numbered ports at random (uniform distribution).
                count = max(1, int(params.get("count", 2)))
                chosen = str(random.randint(1, count))
                log_info(f"[workflow] 🎲 ngẫu nhiên → nhánh {chosen}/{count}")
                self._emit("on_node_done", nid, "ok", chosen)
                cur = self._next(adj, cur, chosen)
            elif kind == "try_chain":
                count = max(1, int(params.get("count", 3)))
                ports = [str(i + 1) for i in range(count)]
                vars0 = dict(self._vars)
                pos0 = self._last_pos
                break0 = self._break_loop
                failed0 = self._branch_failed
                try0 = self._try_chain_mode

                success = False
                attempted = 0
                for port in ports:
                    if self._stop.is_set():
                        break
                    tgt = self._next(adj, cur, port)
                    if not tgt:
                        continue
                    attempted += 1
                    log_info(f"[workflow] thử nhánh {port}/{count}")
                    self._emit("on_node_done", nid, "ok", port)
                    self._vars = dict(vars0)
                    self._last_pos = pos0
                    self._break_loop = False
                    self._branch_failed = False
                    self._try_chain_mode = True
                    self._walk(nodes, adj, tgt, {}, depth)
                    if not self._branch_failed:
                        log_success(f"[workflow] nhánh {port} thành công")
                        success = True
                        break
                    log_warning(f"[workflow] nhánh {port} fail → thử nhánh kế")

                self._try_chain_mode = try0
                self._break_loop = break0
                if success:
                    # The successful branch already walked to its own end.
                    self._branch_failed = failed0
                    break
                self._vars = dict(vars0)
                self._last_pos = pos0
                self._branch_failed = failed0
                self._emit("on_node_done", nid, "fail", "fail")
                if attempted:
                    log_warning("[workflow] tất cả nhánh thử lần lượt đều fail")
                cur = self._next(adj, cur, "fail")
            elif kind == "switch":
                # Evaluate each case top-to-bottom; first true wins its port "c{i}".
                taken = "default"
                for i, case in enumerate(params.get("cases", []) or []):
                    ctype = case.get("type")
                    if ctype not in SWITCH_CASE_TYPES:
                        continue
                    try:
                        if self._eval_condition(ctype, case.get("params", {}) or {}):
                            taken = f"c{i}"
                            break
                    except Exception as e:
                        log_warning(f"[workflow] switch case {i} ({ctype}) lỗi: {e}")
                self._emit("on_node_done", nid, "ok", taken)
                nxt = self._next(adj, cur, taken)
                cur = nxt if nxt is not None else self._next(adj, cur, "default")
            elif kind == "call":
                self._emit("on_node", cur)  # highlight the call block while its function runs
                fid = params.get("fn")
                fn = self._functions.get(fid)
                ok_call = False
                if fn is None:
                    log_warning(f"[workflow] call -> unknown function '{fid}'")
                elif depth >= MAX_CALL_DEPTH:
                    log_warning("[workflow] Max function call depth reached (recursion?)")
                else:
                    log_info(f"[workflow] ƒ {fn.get('name', fid)}")
                    outer_end = self._reached_end
                    self._reached_end = False
                    self._run_graph(fn.get("graph", {}) or {}, depth + 1)
                    ok_call = self._reached_end
                    self._reached_end = outer_end
                    if not ok_call:
                        log_warning(f"[workflow] ƒ {fn.get('name', fid)} → false (dead-end, không tới node End)")
                # Result port: "true" khi function tới node End, "false" khi dead-end.
                port = "true" if ok_call else "false"
                self._emit("on_node_done", nid, "ok" if ok_call else "fail", port)
                nxt = self._next(adj, cur, port)
                if nxt is None:
                    # Legacy flows wired the call's single "out" port — follow it
                    # regardless of the result so old workflows behave as before.
                    nxt = self._next(adj, cur, "out")
                if self._try_chain_mode and (self._branch_failed or (not ok_call and nxt is None)):
                    self._branch_failed = True
                    break
                cur = nxt
            else:  # action (or unknown -> just follow out)
                ok_act = True
                handler = self._actions.get(ntype)
                if ntype == "note":
                    # Ghi chú không phải block thực thi — nếu lỡ bị đấu dây vào
                    # đường chạy thì bỏ qua êm (đi tiếp cổng out, thường không có)
                    # thay vì rơi xuống "Unknown node" và fail cả nhánh.
                    pass
                elif handler is not None:
                    ok_act = self._run_action_with_retry(node, params, handler)
                else:
                    log_warning(f"[workflow] Unknown node: {ntype}")
                    ok_act = False
                    self._branch_failed = True
                self._emit("on_node_done", nid, "ok" if ok_act else "fail", "out")
                if self._try_chain_mode and not ok_act:
                    break
                cur = self._next(adj, cur, "out")

            # Universal post-block pause ("Chờ sau"): block done → wait → then on
            # to the next block. Skipped on branches that `break` above (end /
            # stop / parallel / join / try_chain), which already terminate here.
            da = self._delay_val(node, "delayAfter", params)
            if da > 0 and cur and not self._stop.is_set():
                self._emit("on_node_delay", nid, "after", da)
                self._sleep(da)
                self._emit("on_node_delay", nid, None, 0)
        return True

    def _run_parallel(self, nodes, adj, node_id, depth):
        """Run every wired branch port of a parallel node at once, then join.

        Branch count is read from the node's ``count`` param (default 3). Each
        branch runs on its own thread with its OWN copy of the current vars /
        last-position (snapshotted at the fork) so branches can't stomp each other.

        If any branch reaches a ``join`` node, a shared join_ctx coordinates the
        barrier: the last branch to arrive continues execution from the join's
        ``out`` port. Branches that arrive earlier stop at the join.
        """
        params = (nodes.get(node_id) or {}).get("params", {})
        count = max(1, int(params.get("count", 3)))
        ports = [str(i + 1) for i in range(count)]

        vars0 = dict(self._vars)
        pos0 = self._last_pos

        active = [(p, self._next(adj, node_id, p)) for p in ports]
        active = [(p, tgt) for p, tgt in active if tgt]
        if not active:
            return

        # Shared barrier for join-node coordination (see _walk "join" handler).
        join_ctx: Dict[str, Any] = {
            "lock": threading.Lock(),
            "remaining": len(active),
            "join_node": None,   # id of the join node all branches converge to
            "barriers": {},      # per-And-node arrival / failure state
            "failed": False,     # any branch failed while running under this fork
            "reached_end": False,  # any branch hit an End node (function result)
        }

        threads = []
        for _p, tgt in active:
            t = threading.Thread(
                target=self._walk_branch,
                args=(nodes, adj, tgt, depth, vars0, pos0, join_ctx),
                daemon=True)
            threads.append(t)
            t.start()

        log_info(f"[workflow] ⇉ chạy song song {len(threads)} nhánh")
        for t in threads:
            t.join()

        for bid, state in join_ctx.get("barriers", {}).items():
            if state.get("arrived", 0) < state.get("expected", 0):
                join_ctx["failed"] = True
                self._emit("on_node_done", bid, "fail", "out")
                log_warning(
                    f"[workflow] And '{bid}' chỉ nhận {state.get('arrived', 0)}/"
                    f"{state.get('expected', 0)} nhánh"
                )

        # All branches done. If they converged at a join node, the last-arriving
        # branch already continued from join.out — nothing more to do here.
        # (The parent _walk call proceeds from wherever _run_parallel returns.)
        if join_ctx.get("failed"):
            self._branch_failed = True
        # An End node hit on a branch thread counts for the enclosing function's
        # true/false result — hoist it back onto the forking (caller) thread.
        if join_ctx.get("reached_end"):
            self._reached_end = True

    def _and_arrive(self, ctx: Dict[str, Any], node_id: str, expected: int, branch_failed: bool):
        """Record one parallel branch arriving at an And barrier."""
        with ctx["lock"]:
            barriers = ctx.setdefault("barriers", {})
            state = barriers.setdefault(node_id, {"arrived": 0, "failed": False, "expected": expected, "released": False})
            state["expected"] = expected
            state["arrived"] += 1
            state["failed"] = bool(state["failed"] or branch_failed)
            ctx["failed"] = bool(ctx.get("failed") or branch_failed)
            is_last = state["arrived"] >= expected and not state["released"]
            if is_last:
                state["released"] = True
            ok = not state["failed"]
        return is_last, ok

    def _walk_branch(self, nodes, adj, tgt, depth, vars0, pos0, join_ctx=None):
        """Entry point for a parallel branch thread: seed this thread's context
        from the fork snapshot, then walk. Isolated from siblings + the parent."""
        self._vars = dict(vars0)
        self._last_pos = pos0
        self._break_loop = False
        self._ctx.join_ctx = join_ctx   # thread-local; cleared when thread exits
        self._branch_failed = False
        self._reached_end = False
        try:
            self._walk(nodes, adj, tgt, {}, depth)
        finally:
            if join_ctx is not None:
                with join_ctx["lock"]:
                    if self._branch_failed:
                        join_ctx["failed"] = True
                    if self._reached_end:
                        join_ctx["reached_end"] = True
            self._ctx.join_ctx = None

    @staticmethod
    def _coerce(value: Any) -> Any:
        """Best-effort number coercion (keeps non-numeric strings as-is)."""
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value
        try:
            s = str(value).strip()
            return float(s) if ("." in s or "e" in s.lower()) else int(s)
        except (TypeError, ValueError):
            return value

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        return str(value).strip().lower() in ("true", "1", "yes", "on")

    def _format_msg(self, text: Any) -> str:
        """Fill ``{var}`` placeholders in a log message from the current vars.

        An unknown ``{name}`` is left untouched so the literal braces still show.
        """
        s = str(text)
        if "{" not in s:
            return s
        return re.sub(r"\{([^{}]+)\}",
                      lambda m: str(self._vars.get(m.group(1).strip(), m.group(0))),
                      s)

    def _seed_vars(self, act: Dict) -> Dict[str, Any]:
        """Initial variable values for a thread: globals first, then the
        activity's own declared ``vars`` (which may override a same-named
        global for this run). Nested children are flattened with dotted keys."""
        out: Dict[str, Any] = {}
        for v in (self._globals or {}).items():
            out[v[0]] = v[1]
        for v in (act.get("vars") or []):
            self._seed_var(v, out)
        return out

    def _seed_var(self, v: Dict, out: Dict[str, Any], prefix: str = "") -> None:
        nm = str(v.get("name", "")).strip()
        if not nm:
            return
        full = f"{prefix}.{nm}" if prefix else nm
        t = v.get("type", "text")
        val = v.get("value")
        if t == "bool":
            out[full] = self._truthy(val)
        elif t == "number":
            c = self._coerce(val)
            out[full] = c if isinstance(c, (int, float)) and not isinstance(c, bool) else 0
        else:
            out[full] = "" if val is None else str(val)
        for child in (v.get("children") or []):
            self._seed_var(child, out, full)

    @staticmethod
    def _region(params: Dict) -> tuple:
        return (int(params.get("x", 0)), int(params.get("y", 0)),
                int(params.get("w", 200)), int(params.get("h", 80)))

    @staticmethod
    def _search_region(params: Dict) -> Optional[tuple]:
        """Optional (x, y, w, h) crop to restrict a template search to.

        Reads ``regionX/Y/W/H`` (set by the designer's optional "Vùng tìm" group
        on image nodes). Returns ``None`` when the crop is empty or covers the
        whole screen — i.e. when there's effectively no restriction.
        """
        x = int(params.get("regionX", 0) or 0)
        y = int(params.get("regionY", 0) or 0)
        w = int(params.get("regionW", 0) or 0)
        h = int(params.get("regionH", 0) or 0)
        if w <= 0 or h <= 0:
            return None
        return (x, y, w, h)

    def _templates_list(self, params: Dict) -> List[str]:
        """Resolved template paths for an "…_any" node.

        Reads the ``templates`` list param (tolerating a single ``template``
        string for robustness), drops empties, and resolves each to an absolute
        path. Order is preserved so "first match wins" is predictable.
        """
        raw = params.get("templates")
        items: List[str] = []
        if isinstance(raw, (list, tuple)):
            items = [str(x) for x in raw if str(x).strip()]
        elif raw:
            items = [str(raw)]
        if not items and params.get("template"):
            items = [str(params.get("template"))]
        return [self._resolve_template(it) for it in items if it.strip()]

    # ── Match overlay helpers (designer Preview) ─────────────────────────────
    # When report_matches is on, every final template/color/OCR probe emits
    # on_match so the UI can draw the hit box + confidence. Misses still emit
    # the *best* below-threshold location (dashed red) so "why didn't it match?"
    # is visible without re-running in DevScope.

    def _tpl_wh(self, path: str) -> tuple:
        try:
            tpl = self.auto.matcher.load(path)
            if tpl is not None:
                return int(tpl.shape[1]), int(tpl.shape[0])
        except Exception:
            pass
        return 0, 0

    def _rect_from_center(
        self,
        cx: int,
        cy: int,
        conf: float,
        tw: int,
        th: int,
        scale: float = 1.0,
        ok: bool = True,
        label: str = "",
    ) -> Dict[str, Any]:
        sw = max(1, int(tw * scale)) if tw else 24
        sh = max(1, int(th * scale)) if th else 24
        return {
            "x": max(0, int(cx) - sw // 2),
            "y": max(0, int(cy) - sh // 2),
            "w": sw,
            "h": sh,
            "conf": float(conf),
            "ok": bool(ok),
            "label": label or "",
        }

    def _best_match_raw(self, tpl: str, region=None):
        """Best match at any confidence (for fail overlay). Returns matcher tuple
        ``(cx, cy, conf, scale)`` or ``None``."""
        try:
            screen = self.auto.get_latest_screen()
            if screen is None:
                screen = self.auto.capture_screen()
            if screen is None:
                return None
            template = self.auto.matcher.load(tpl)
            if template is None:
                return None
            # threshold just above 0 so a total miss (no valid scale) stays None
            # without requiring a real match.
            return self.auto.matcher.match(
                screen, template, threshold=0.01, multi_scale=False,
                scales=[1.0], region=region,
            )
        except Exception:
            return None

    def _report_template_match(
        self,
        tpl: str,
        res,
        threshold: float,
        region=None,
        label: str = "",
    ) -> None:
        """Emit on_match for one template probe. ``res`` is find_template's
        ``(cx, cy, conf)`` or ``None``."""
        if not self.report_matches:
            return
        name = os.path.basename(tpl or "") or "?"
        tw, th = self._tpl_wh(tpl)
        rects: List[Dict[str, Any]] = []
        ok = False
        conf = 0.0
        if res:
            cx, cy, conf = int(res[0]), int(res[1]), float(res[2])
            ok = conf >= float(threshold)
            rects.append(self._rect_from_center(
                cx, cy, conf, tw, th, 1.0, ok, label or name))
        else:
            best = self._best_match_raw(tpl, region)
            if best:
                cx, cy, conf, scale = best
                rects.append(self._rect_from_center(
                    int(cx), int(cy), float(conf), tw, th, float(scale),
                    False, label or name))
        self._emit("on_match", {
            "rects": rects,
            "ok": ok,
            "threshold": float(threshold),
            "template": name,
            "label": label or name,
            "region": list(region) if region else None,
            "conf": float(conf) if rects else 0.0,
        })

    def _report_match_rects(
        self,
        rects: List[Dict[str, Any]],
        *,
        ok: bool,
        threshold: float = 0.0,
        label: str = "",
        region=None,
        conf: float = 0.0,
    ) -> None:
        if not self.report_matches:
            return
        self._emit("on_match", {
            "rects": rects,
            "ok": ok,
            "threshold": float(threshold),
            "template": label,
            "label": label,
            "region": list(region) if region else None,
            "conf": float(conf),
        })

    def _report_ocr_region(self, region, ok: bool, needle: str = "") -> None:
        """Highlight the OCR search box after a text probe (no char boxes)."""
        if not self.report_matches:
            return
        rects: List[Dict[str, Any]] = []
        if region and len(region) >= 4:
            x, y, w, h = (int(region[0]), int(region[1]),
                          int(region[2]), int(region[3]))
            if w > 0 and h > 0:
                rects.append({
                    "x": x, "y": y, "w": w, "h": h,
                    "conf": 1.0 if ok else 0.0,
                    "ok": bool(ok),
                    "label": (needle or "OCR")[:24],
                })
        self._report_match_rects(
            rects, ok=bool(ok), label=needle or "OCR",
            region=region, conf=1.0 if ok else 0.0,
        )

    def _find_template(self, tpl: str, threshold: float = 0.85, region=None,
                       report: bool = True):
        """find_template + optional match overlay report."""
        res = self.auto.find_template(tpl, threshold=threshold, region=region)
        if report:
            self._report_template_match(tpl, res, threshold, region)
        return res

    def _wait_for_template(
        self,
        tpl: str,
        timeout: float = 10.0,
        threshold: float = 0.85,
        region=None,
        report: bool = True,
    ):
        """wait_for_template + one overlay report when done (found or timeout)."""
        res = self.auto.wait_for_template(
            tpl, timeout=timeout, threshold=threshold, region=region)
        if report:
            self._report_template_match(tpl, res, threshold, region)
        return res

    def _find_any(self, templates: List[str], threshold: float, region=None):
        """(x, y) of the first listed template currently on screen, or ``None``.
        Sequential: stops at the first match (list order is the priority order)."""
        for tpl in templates:
            # report only the winner (or the first miss below)
            res = self.auto.find_template(tpl, threshold=threshold, region=region)
            if res:
                self._report_template_match(tpl, res, threshold, region)
                return (res[0], res[1])
        if templates:
            self._report_template_match(templates[0], None, threshold, region)
        return None

    def _find_any_parallel(self, templates: List[str], threshold: float, region=None):
        """Check all templates concurrently; return position of whichever matches first.
        Unlike the sequential variant, list order does NOT determine priority —
        the template actually visible on screen wins."""
        if not templates:
            return None
        results: List = []
        lock = threading.Lock()

        def check(tpl: str) -> None:
            try:
                res = self.auto.find_template(tpl, threshold=threshold, region=region)
                if res:
                    with lock:
                        results.append((tpl, res[0], res[1], res[2]))
            except Exception:
                pass

        threads = [threading.Thread(target=check, args=(tpl,), daemon=True)
                   for tpl in templates]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        if results:
            tpl, x, y, conf = results[0]
            self._report_template_match(tpl, (x, y, conf), threshold, region)
            return (x, y)
        self._report_template_match(templates[0], None, threshold, region)
        return None

    def _wait_any(self, templates: List[str], timeout: float, threshold: float,
                  parallel: bool = False, region=None):
        """Poll until ANY listed template appears, or ``timeout``. Pause/stop aware.

        ``wait_for_template`` waits on one specific image, so for an OR-over-images
        we poll ``find_template`` across the whole list each round instead.
        When ``parallel=True`` all templates are checked concurrently each round.
        """
        if not templates:
            return None
        finder = self._find_any_parallel if parallel else self._find_any
        end = time.time() + max(0.0, timeout)
        while not self._stop.is_set():
            self._pause.wait()
            hit = finder(templates, threshold, region=region)
            if hit:
                return hit
            if time.time() >= end:
                return None
            time.sleep(0.25)
        return None

    # ── Color (pixel) helpers ────────────────────────────────────────────────

    @staticmethod
    def _parse_hex_color(raw: Any) -> Optional[tuple]:
        """``#RRGGBB`` (hash optional) → an ``(b, g, r)`` tuple, or ``None``."""
        s = str(raw or "").strip().lstrip("#")
        if not re.fullmatch(r"[0-9a-fA-F]{6}", s):
            return None
        return (int(s[4:6], 16), int(s[2:4], 16), int(s[0:2], 16))

    @staticmethod
    def _bgr_to_hex(px) -> str:
        return "#{:02x}{:02x}{:02x}".format(int(px[2]), int(px[1]), int(px[0]))

    def _pixel_at(self, x: int, y: int) -> Optional[tuple]:
        """The screen's BGR pixel at (x, y), or ``None`` (no frame / off-screen)."""
        screen = self.auto.capture_screen()
        if screen is None:
            return None
        h, w = screen.shape[:2]
        if not (0 <= x < w and 0 <= y < h):
            log_warning(f"[workflow] điểm ({x}, {y}) nằm ngoài màn hình {w}×{h}")
            return None
        return tuple(int(c) for c in screen[y, x][:3])

    @staticmethod
    def _color_close(px: tuple, target: tuple, tol: int) -> bool:
        """True when every BGR channel differs by at most ``tol``."""
        return all(abs(int(a) - int(b)) <= tol for a, b in zip(px, target))

    def _find_color(self, target: tuple, tol: int, region=None) -> Optional[tuple]:
        """(x, y) of the first pixel matching ``target``±``tol``, or ``None``.

        Scans top-to-bottom / left-to-right (first match wins) over the whole
        frame or an optional ``(x, y, w, h)`` crop.
        """
        import numpy as np
        screen = self.auto.capture_screen()
        if screen is None:
            return None
        ox = oy = 0
        if region:
            rx, ry, rw, rh = region
            h, w = screen.shape[:2]
            rx, ry = max(0, rx), max(0, ry)
            screen = screen[ry:min(h, ry + rh), rx:min(w, rx + rw)]
            if screen.size == 0:
                return None
            ox, oy = rx, ry
        mask = np.all(np.abs(screen[:, :, :3].astype(np.int16) - np.int16(target)) <= tol, axis=2)
        hits = np.argwhere(mask)
        if not len(hits):
            return None
        y, x = hits[0]
        return (int(x) + ox, int(y) + oy)

    def _eval_color_condition(self, ntype: str, params: Dict) -> bool:
        target = self._parse_hex_color(params.get("color"))
        if target is None:
            log_warning(f"[workflow] '{ntype}': màu không hợp lệ ({params.get('color')!r}) — cần #RRGGBB")
            return False
        tol = max(0, int(params.get("tolerance", 10) or 0))
        if ntype == "if_color":
            negate = bool(params.get("negate", False))
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            px = self._pixel_at(x, y)
            ok = px is not None and self._color_close(px, target, tol)
            if ok:
                # Lưu vị trí "found" như các node ảnh — để "Tap → last found
                # image" sau một node màu chạm đúng điểm vừa kiểm tra.
                self._last_pos = (x, y)
            hex_lbl = self._bgr_to_hex(target)
            self._report_match_rects(
                [self._rect_from_center(x, y, 1.0 if ok else 0.0, 18, 18, 1.0, ok, hex_lbl)],
                ok=ok != negate, label=hex_lbl, conf=1.0 if ok else 0.0,
            )
            return ok != negate
        if ntype == "wait_color":
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            negate = bool(params.get("negate", False))
            end = time.time() + max(0.0, float(params.get("timeout", 10.0)))
            hex_lbl = self._bgr_to_hex(target)
            while not self._stop.is_set():
                self._pause.wait()
                px = self._pixel_at(x, y)
                ok = px is not None and self._color_close(px, target, tol)
                if ok and not negate:
                    self._last_pos = (x, y)
                    log_info(f"[workflow] 🎨 thấy màu {hex_lbl} tại ({x}, {y})")
                    self._report_match_rects(
                        [self._rect_from_center(x, y, 1.0, 18, 18, 1.0, True, hex_lbl)],
                        ok=True, label=hex_lbl, conf=1.0,
                    )
                    return True
                if negate and not ok:
                    # Đảo: chờ đến khi màu BIẾN MẤT (nút sáng → tối, loading xong…).
                    log_info(f"[workflow] 🎨 màu {hex_lbl} đã biến mất tại ({x}, {y})")
                    self._report_match_rects(
                        [self._rect_from_center(x, y, 0.0, 18, 18, 1.0, True, hex_lbl)],
                        ok=True, label=hex_lbl, conf=0.0,
                    )
                    return True
                if time.time() >= end:
                    self._report_match_rects(
                        [self._rect_from_center(x, y, 0.0, 18, 18, 1.0, False, hex_lbl)],
                        ok=False, label=hex_lbl, conf=0.0,
                    )
                    return False
                time.sleep(0.25)
            return False
        if ntype == "tap_color":
            region = self._search_region(params)
            end = time.time() + max(0.0, float(params.get("timeout", 10.0)))
            hex_lbl = self._bgr_to_hex(target)
            while not self._stop.is_set():
                self._pause.wait()
                hit = self._find_color(target, tol, region=region)
                if hit:
                    self._last_pos = hit
                    self._report_match_rects(
                        [self._rect_from_center(hit[0], hit[1], 1.0, 18, 18, 1.0, True, hex_lbl)],
                        ok=True, label=hex_lbl, region=region, conf=1.0,
                    )
                    return self._tap_at(hit[0], hit[1], params, label=f"màu {hex_lbl}")
                if time.time() >= end:
                    self._report_match_rects(
                        [], ok=False, label=hex_lbl, region=region, conf=0.0,
                    )
                    return False  # colour never appeared — false branch fires
                time.sleep(0.25)
            return False
        return False

    def _a_read_color(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        px = self._pixel_at(int(p.get("x", 0)), int(p.get("y", 0)))
        value = self._bgr_to_hex(px) if px is not None else ""
        if name:
            self._set_var(name, value)
            log_info(f"[workflow] 🎨 {name} = {value or '(không đọc được)'}")
        return True

    @staticmethod
    def _ocr_whitelist(params: Dict) -> Optional[str]:
        """The node's optional OCR character whitelist ('' → None)."""
        wl = str(params.get("whitelist", "") or "").strip()
        return wl or None

    # ── loop_until family ──────────────────────────────────────────────────────
    # loop_until_image/color/text/var share the walk logic in _walk; only the
    # per-iteration probe differs. Each probe returns True when the loop should
    # exit through "found".

    def _loop_until_label(self, ntype: str, params: Dict) -> str:
        """Short human label of what the loop is waiting for (log lines)."""
        if ntype == "loop_until_color":
            return f"thấy màu {params.get('color') or '?'}"
        if ntype == "loop_until_text":
            return f"thấy chữ \"{params.get('text') or ''}\""
        if ntype == "loop_until_var":
            return (f"biến {params.get('name') or '?'} "
                    f"{params.get('op') or '=='} {params.get('value')}")
        tpl = str(params.get("template") or "")
        return f"thấy ảnh {os.path.basename(tpl) if tpl else '?'}"

    def _loop_until_hit(self, ntype: str, params: Dict) -> bool:
        """One probe of a loop_until node's exit condition."""
        if ntype == "loop_until_color":
            target = self._parse_hex_color(params.get("color"))
            if target is None:
                log_warning(f"[workflow] loop_until_color: màu không hợp lệ "
                            f"({params.get('color')!r}) — cần #RRGGBB")
                return False
            tol = max(0, int(params.get("tolerance", 10) or 0))
            hex_lbl = self._bgr_to_hex(target)
            # "anywhere" quét cả vùng tìm; mặc định kiểm 1 điểm x/y như if_color.
            if str(params.get("where", "point")).strip().lower() == "anywhere":
                hit = self._find_color(target, tol, region=self._search_region(params))
                ok = hit is not None
                if ok:
                    self._last_pos = (int(hit[0]), int(hit[1]))
                self._report_match_rects(
                    [self._rect_from_center(int(hit[0]) if ok else 0, int(hit[1]) if ok else 0,
                                            1.0 if ok else 0.0, 18, 18, 1.0, ok, hex_lbl)],
                    ok=ok, label=hex_lbl, conf=1.0 if ok else 0.0,
                    region=self._search_region(params),
                )
                return ok
            x, y = int(params.get("x", 0)), int(params.get("y", 0))
            px = self._pixel_at(x, y)
            ok = px is not None and self._color_close(px, target, tol)
            if ok:
                self._last_pos = (x, y)
            self._report_match_rects(
                [self._rect_from_center(x, y, 1.0 if ok else 0.0, 18, 18, 1.0, ok, hex_lbl)],
                ok=ok, label=hex_lbl, conf=1.0 if ok else 0.0,
            )
            return ok
        if ntype == "loop_until_text":
            needle = str(self._resolve_value(params.get("text", "")))
            region = self._region(params)
            found, _read = self.auto.region_find_text(
                needle, region=region, whitelist=self._ocr_whitelist(params))
            self._report_ocr_region(region, bool(found), needle)
            return bool(found)
        if ntype == "loop_until_var":
            cur = self._vars.get(str(params.get("name", "")))
            rhs = self._resolve_value(params.get("value", ""))
            return self._compare(cur, str(params.get("op", "==")), rhs)
        # loop_until_image (default)
        tpl = self._resolve_template(params.get("template", ""))
        res = self._find_template(
            tpl, threshold=float(params.get("threshold", 0.85)),
            region=self._search_region(params),
            report=True,  # live overlay each probe on designer
        )
        if res:
            self._last_pos = (res[0], res[1])
            return True
        return False

    def _eval_condition(self, ntype: str, params: Dict) -> bool:
        if ntype in ("if_color", "wait_color", "tap_color"):
            return self._eval_color_condition(ntype, params)
        if ntype == "tap_all_images":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            self.auto.capture_screen()  # find_all_templates reads the latest frame
            hits = self.auto.find_all_templates(tpl, threshold=threshold) or []
            region = self._search_region(params)
            if region:
                rx, ry, rw, rh = region
                hits = [h for h in hits if rx <= h[0] <= rx + rw and ry <= h[1] <= ry + rh]
            max_taps = self._resolve_count(params.get("maxTaps", 0), default=0)
            if max_taps > 0:
                hits = hits[:max_taps]
            # Overlay every hit before tapping so Preview shows the full set.
            name = os.path.basename(tpl) if tpl else "?"
            tw, th = self._tpl_wh(tpl)
            self._report_match_rects(
                [self._rect_from_center(int(hx), int(hy), float(sc), tw, th, 1.0, True, name)
                 for hx, hy, sc in hits],
                ok=bool(hits), threshold=threshold, label=name, region=region,
                conf=float(hits[0][2]) if hits else 0.0,
            )
            delay = max(0.0, float(params.get("delayBetween", 0.15) or 0))
            tapped = 0
            for hx, hy, _score in hits:
                if self._stop.is_set():
                    break
                self._pause.wait()
                if self._tap_at(int(hx), int(hy), params, label="ảnh"):
                    tapped += 1
                if delay:
                    self._sleep(delay)
            if tapped:
                self._last_pos = (int(hits[0][0]), int(hits[0][1]))
                log_info(f"[workflow] 👆 chạm {tapped} vị trí khớp {os.path.basename(tpl)}")
            return tapped > 0
        if ntype == "if_emulator":
            return self._c_if_emulator(params)
        if ntype == "wait_emulator":
            return self._c_wait_emulator(params)
        if ntype in ("win_if_window", "win_wait_window"):
            return self._c_win_window(ntype, params)
        if ntype == "if_screen_on":
            return self._c_if_screen_on(params)
        if ntype == "find_image_pos":
            return self._c_find_image_pos(params)
        if ntype == "wait_stable":
            return self._c_wait_stable(params)
        if ntype == "if_app":
            negate = bool(params.get("negate", False))
            # Win32: hỏi CỬA SỔ MỤC TIÊU, không phải cửa sổ đang foreground —
            # ở input mode background (mặc định) cửa sổ game hầu như không bao
            # giờ được focus, nên get_current_app() sẽ luôn trả về sai.
            if getattr(self, "_controller", "adb") == "win32":
                # pkgSrc=project ở dự án Win32 = "cửa sổ trong Project settings",
                # tức chỉ cần hỏi nó còn sống; custom = so khớp chuỗi tiêu đề.
                needle = ""
                if str(params.get("pkgSrc") or "").strip().lower() != "project":
                    needle = str(self._resolve_value(params.get("package", "")) or "").strip().lower()
                ctrl = getattr(self.auto, "adb", None)
                title = ""
                alive = False
                if ctrl is not None and hasattr(ctrl, "target_title"):
                    title = ctrl.target_title() or ""
                    alive = bool(title) or bool(getattr(ctrl, "device", None))
                elif ctrl is not None:
                    alive = bool(getattr(ctrl, "device", None))
                ok = alive if not needle else (needle in title.lower())
                log_info(f"[workflow] 🪟 cửa sổ mục tiêu: {title or '(không thấy)'} → "
                         f"{'khớp' if ok else 'không khớp'}"
                         + (f" '{needle}'" if needle else ""))
                return ok != negate
            needle = self._node_package(params).lower()
            try:
                if hasattr(self.auto.adb, "clear_info_cache"):
                    self.auto.adb.clear_info_cache()
                cur_app = (self.auto.adb.get_current_app() or "").lower()
            except Exception:
                cur_app = ""
            ok = bool(needle) and needle in cur_app
            log_info(f"[workflow] 📱 app hiện tại: {cur_app or '(?)'} → "
                     f"{'khớp' if ok else 'không khớp'} '{needle}'")
            return ok != negate
        if ntype == "if_image":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            negate = bool(params.get("negate", False))
            res = self._find_template(tpl, threshold=threshold, region=self._search_region(params))
            if res:
                self._last_pos = (res[0], res[1])
            return (res is not None) != negate
        if ntype == "if_image_any":
            templates = self._templates_list(params)
            negate = bool(params.get("negate", False))
            parallel = params.get("mode", "sequential") == "parallel"
            finder = self._find_any_parallel if parallel else self._find_any
            hit = finder(templates, float(params.get("threshold", 0.85)), region=self._search_region(params))
            if hit:
                self._last_pos = hit
            return (hit is not None) != negate
        if ntype == "wait_image_any":
            templates = self._templates_list(params)
            parallel = params.get("mode", "sequential") == "parallel"
            hit = self._wait_any(templates, float(params.get("timeout", 10.0)),
                                 float(params.get("threshold", 0.85)),
                                 parallel=parallel, region=self._search_region(params))
            if hit:
                self._last_pos = hit
                log_info(f"[workflow] 🔍 thấy ảnh ({hit[0]}, {hit[1]})")
            return hit is not None
        if ntype == "tap_image_any":
            templates = self._templates_list(params)
            parallel = params.get("mode", "sequential") == "parallel"
            hit = self._wait_any(templates, float(params.get("timeout", 10.0)),
                                 float(params.get("threshold", 0.85)),
                                 parallel=parallel, region=self._search_region(params))
            if not hit:
                return False  # no match — false branch fires; no log (tap-miss is expected)
            self._last_pos = hit
            return self._tap_at(hit[0], hit[1], params, label="ảnh")
        if ntype == "tap_image":
            # Find (with timeout), remember position, optionally wait, then tap.
            tpl = self._resolve_template(params.get("template", ""))
            res = self._wait_for_template(
                tpl, timeout=float(params.get("timeout", 10.0)),
                threshold=float(params.get("threshold", 0.85)),
                region=self._search_region(params),
            )
            if not res:
                return False  # not found — false branch fires; no log (tap-miss is expected)
            self._last_pos = (res[0], res[1])
            return self._tap_at(res[0], res[1], params, label=os.path.basename(tpl))
        if ntype == "wait_image":
            tpl = self._resolve_template(params.get("template", ""))
            threshold = float(params.get("threshold", 0.85))
            timeout = float(params.get("timeout", 10.0))
            region = self._search_region(params)
            if bool(params.get("negate", False)):
                # Đảo: chờ đến khi ảnh BIẾN MẤT (màn hình loading, hộp thoại…)
                # — true ngay khi không còn thấy template; hết timeout → false.
                end = time.time() + max(0.0, timeout)
                while not self._stop.is_set():
                    self._pause.wait()
                    if self._find_template(tpl, threshold=threshold, region=region,
                                           report=False) is None:
                        log_info(f"[workflow] 🔍 ảnh {os.path.basename(tpl)} đã biến mất")
                        self._report_template_match(tpl, None, threshold, region)
                        return True
                    if time.time() >= end:
                        # still visible — report the hit as fail for negate path
                        res = self._find_template(tpl, threshold=threshold, region=region)
                        return False
                    time.sleep(0.25)
                return False
            res = self._wait_for_template(
                tpl, timeout=timeout, threshold=threshold, region=region,
            )
            if res:
                self._last_pos = (res[0], res[1])
                log_info(f"[workflow] 🔍 thấy ảnh {os.path.basename(tpl)} ({res[0]}, {res[1]})")
            return res is not None
        if ntype == "wait_text":
            needle = str(self._resolve_value(params.get("text", "")) or "")
            region = self._region(params)
            wl = self._ocr_whitelist(params)
            timeout = float(params.get("timeout", 10.0))
            if bool(params.get("negate", False)):
                # Đảo: chờ đến khi chữ BIẾN MẤT khỏi vùng OCR.
                end = time.time() + max(0.0, timeout)
                while not self._stop.is_set():
                    self._pause.wait()
                    found, _read = self.auto.region_find_text(needle, region=region, whitelist=wl)
                    if not found:
                        log_info(f"[workflow] 🔤 chữ '{needle}' đã biến mất")
                        self._report_ocr_region(region, True, needle)
                        return True
                    if time.time() >= end:
                        self._report_ocr_region(region, False, needle)
                        return False
                    time.sleep(0.5)   # OCR nặng hơn match ảnh — poll thưa hơn
                return False
            found = bool(self.auto.wait_for_text_in_region(
                needle, region=region, timeout=timeout, whitelist=wl,
            ))
            self._report_ocr_region(region, found, needle)
            return found
        if ntype == "if_text":
            negate = bool(params.get("negate", False))
            # needle nhận biến — đồng bộ với if_app.package.
            needle = str(self._resolve_value(params.get("text", "")) or "")
            region = self._region(params)
            found, read = self.auto.region_find_text(
                needle, region=region, whitelist=self._ocr_whitelist(params))
            log_info(
                f"[workflow] 🔤 if_text vùng {region}: đọc được {read!r} → "
                f"{'thấy' if found else 'không thấy'} '{needle}'"
            )
            ok = bool(found) != negate
            self._report_ocr_region(region, ok, needle)
            return ok
        if ntype == "if_var":
            cur = self._vars.get(str(params.get("name", "")))
            rhs = self._resolve_value(params.get("value", ""))
            return self._compare(cur, str(params.get("op", "==")), rhs)
        if ntype == "scroll_find":
            template  = self._resolve_template(params.get("template", ""))
            direction = str(params.get("direction", "up")).lower()
            max_sw    = max(1, int(params.get("max_swipes", 10)))
            distance  = int(params.get("swipe_distance", 400))
            duration  = int(params.get("swipe_duration", 300))
            threshold = float(params.get("threshold", 0.85))
            try:
                w, h = self.auto.adb.get_screen_size()
            except Exception:
                w, h = 0, 0
            cx, cy = (w // 2, h // 2) if (w and h) else (540, 960)
            delta  = {"up": (0, -distance), "down": (0, distance),
                      "left": (-distance, 0), "right": (distance, 0)}.get(direction, (0, -distance))
            region = self._search_region(params)
            for i in range(max_sw):
                if self._stop.is_set():
                    return False
                self._pause.wait()
                res = self.auto.find_template(template, threshold=threshold, region=region)
                if res:
                    self._report_template_match(template, res, threshold, region)
                    self._last_pos = (res[0], res[1])
                    log_info(f"[workflow] 🔍 thấy ảnh sau {i} lần vuốt ({res[0]}, {res[1]})")
                    return True
                if i == max_sw - 1:
                    self._report_template_match(template, None, threshold, region)
                self.auto.swipe(cx, cy, cx + delta[0], cy + delta[1], duration)
                self._sleep(0.4)
            return False
        if ntype == "if_time":
            negate = bool(params.get("negate", False))
            now = time.localtime()
            cur = now.tm_hour * 60 + now.tm_min
            a = self._parse_hhmm(params.get("from"), 0)
            b = self._parse_hhmm(params.get("to"), 24 * 60 - 1)
            # a <= b: a normal window in one day. a > b: the window wraps past
            # midnight (e.g. 22:00–06:00), so "inside" means before b OR after a.
            inside = (a <= cur <= b) if a <= b else (cur >= a or cur <= b)
            return inside != negate
        return False

    @staticmethod
    def _parse_hhmm(raw: Any, default: int) -> int:
        """Parse a ``HH:MM`` string to minutes-since-midnight; ``default`` if bad."""
        m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*$", str(raw or ""))
        if not m:
            return default
        return int(m.group(1)) * 60 + int(m.group(2))

    def _compare(self, cur: Any, op: str, rhs: Any) -> bool:
        # String-shaped operators first — OCR results almost always need soft
        # matching ("Stage 3/5" contains "3/5") rather than numeric equality.
        if op in ("contains", "!contains", "starts", "ends", "regex"):
            hay = str("" if cur is None else cur)
            needle = str("" if rhs is None else rhs)
            if op == "regex":
                try:
                    return re.search(needle, hay) is not None
                except re.error as exc:
                    log_warning(f"[workflow] regex không hợp lệ /{needle}/: {exc}")
                    return False
            h, n = hay.lower(), needle.lower()
            if op == "contains":
                return n in h
            if op == "!contains":
                return n not in h
            if op == "starts":
                return h.startswith(n)
            return h.endswith(n)
        # Boolean comparison when the right-hand side is true/false.
        if op in ("==", "!=") and str(rhs).strip().lower() in ("true", "false"):
            res = self._truthy(cur) == (str(rhs).strip().lower() == "true")
            return res if op == "==" else not res
        a, b = self._coerce(cur), self._coerce(rhs)
        # Fall back to string compare when types differ for ordering ops.
        try:
            if op == "==":
                return a == b or str(cur) == str(rhs)
            if op == "!=":
                return not (a == b or str(cur) == str(rhs))
            if op == ">":
                return a > b
            if op == "<":
                return a < b
            if op == ">=":
                return a >= b
            if op == "<=":
                return a <= b
        except TypeError:
            return False
        return False

    # ── Background workers ───────────────────────────────────────────────────

    def start_all_background(self) -> None:
        for act in self.activities():
            if act.get("type") == "background" and act.get("enabled", True):
                self.start_background(act)

    def start_background(self, act: Dict[str, Any]) -> None:
        aid = act.get("id") or act.get("name")
        if not aid or aid in self._bg_threads:
            return
        stop_ev = threading.Event()
        self._bg_stop[aid] = stop_ev
        t = threading.Thread(target=self._bg_loop, args=(act, stop_ev), daemon=True)
        self._bg_threads[aid] = t
        t.start()
        log_info(f"[workflow] [bg] started '{act.get('name', aid)}'")

    def stop_background(self, aid: str) -> None:
        ev = self._bg_stop.get(aid)
        if ev:
            ev.set()
        t = self._bg_threads.pop(aid, None)
        self._bg_stop.pop(aid, None)
        if t and t.is_alive() and t is not threading.current_thread():
            t.join(timeout=0.5)
        log_info(f"[workflow] [bg] stopped '{aid}'")

    def _bg_loop(self, act: Dict[str, Any], stop_ev: threading.Event) -> None:
        name = act.get("name") or act.get("id")
        while not stop_ev.is_set() and not self._stop.is_set():
            self._pause.wait()
            self._vars = self._seed_vars(act)
            self._last_pos = None
            self._break_loop = False
            self._emit("on_activity_start", act)
            try:
                ok = self._run_graph(act.get("graph", {}) or {})
            except Exception as e:
                ok = False
                log_error(f"[workflow] [bg] '{name}' error: {e}")
            self._emit("on_activity_complete", act, ok)
            interval = max(0.05, float(act.get("pollInterval", 1.0) or 1.0))
            end = time.time() + interval
            while time.time() < end and not stop_ev.is_set() and not self._stop.is_set():
                time.sleep(0.05)

    # ── Pause / stop ─────────────────────────────────────────────────────────

    def pause(self) -> None:
        self._pause.clear()
        log_info("[workflow] Paused")

    def resume(self) -> None:
        self._pause.set()
        log_info("[workflow] Resumed")

    def is_paused(self) -> bool:
        return not self._pause.is_set()

    def is_running(self) -> bool:
        return self.running

    def stop(self) -> None:
        log_info("[workflow] Stopping…")
        self._stop.set()
        self.auto._stop_event.set()
        self._pause.set()
        self._debug_gate.set()
        self._stop_speedhack()
        for aid in list(self._bg_threads.keys()):
            self.stop_background(aid)
        if (self._seq_thread and self._seq_thread.is_alive()
                and self._seq_thread is not threading.current_thread()):
            self._seq_thread.join(timeout=1.0)
        self.auto.stop_continuous_capture()
        self.running = False
        self._emit("on_stop")
        log_success("[workflow] Stopped")

    # Node types whose ``timeout`` param waits for a screen change. Single-node
    # test caps this so "Test block" returns in ~1s with an overlay instead of
    # hanging for the full configured wait (often 10s).
    _QUICK_TIMEOUT_TYPES = frozenset({
        "tap_image", "wait_image", "tap_image_any", "wait_image_any",
        "tap_color", "wait_color", "wait_text", "scroll_find",
        "win_wait_window", "wait_stable",
    })

    def run_single_node(self, node: Dict[str, Any]) -> Dict[str, Any]:
        """Execute one node in isolation (no graph walk), on the calling thread.

        Used by the designer's "Test block" action: fires the same on_node /
        on_node_done callbacks as a real run so the UI paints the block
        amber→green/red, streams log output, and (when report_matches is on)
        emits on_match rects for the Preview overlay. Conditions report the
        taken branch; actions report ok/fail.

        Image/color wait timeouts are capped at 1s so a miss returns quickly
        with a best-score overlay instead of blocking for the full timeout.

        Returns ``{status, port}`` so the caller can relay the outcome.
        """
        if self.running:
            log_warning("[workflow] Đang chạy — không thể chạy 1 block")
            return {"status": "busy", "port": None}
        if not self._ensure_ready():
            return {"status": "error", "port": None}
        nid = node.get("id")
        ntype = node.get("type")
        # Shallow-copy params so timeout cap doesn't mutate the designer's node.
        params = dict(node.get("params", {}) or {})
        if ntype in self._QUICK_TIMEOUT_TYPES:
            try:
                params["timeout"] = min(float(params.get("timeout", 10) or 10), 1.0)
            except (TypeError, ValueError):
                params["timeout"] = 1.0
        work = dict(node)
        work["params"] = params
        spec = NODE_TYPES.get(ntype)
        kind = spec.get("kind") if spec else None
        self._emit("on_node", nid)
        port: Optional[str] = None
        status = "ok"
        try:
            if kind == "condition":
                res = self._eval_condition(ntype, params)
                port = "true" if res else "false"
            elif kind in ("start", "end", "note", "stop", "try_next"):
                # Terminals/notes/control exits have no side-effects standalone.
                port = None
            elif kind in ("loop", "loop_until", "parallel", "and", "join",
                          "random", "switch", "try_chain", "call"):
                # Structural nodes don't make sense standalone; report no-op.
                log_info(f"[workflow] Block '{ntype}' là cấu trúc — chạy trong luồng")
                port = None
            else:
                handler = self._actions.get(ntype)
                if handler is not None:
                    ok_act = self._run_action_with_retry(work, params, handler)
                    status = "ok" if ok_act else "fail"
                    port = "out"
                else:
                    log_warning(f"[workflow] Unknown node: {ntype}")
                    status = "fail"
                    port = "out"
        except Exception as e:
            log_error(f"[workflow] Node '{ntype}' error: {e}")
            status = "fail"
            port = "out"
        self._emit("on_node_done", nid, status, port)
        self._emit("on_node", None)  # clear the amber highlight
        return {"status": status, "port": port}

    # ── Speedhack ────────────────────────────────────────────────────────────

    def _auto_package(self) -> str:
        """Best-effort target package: workflow field, else first ``launch_app`` node.

        Lets a flow that opens the game itself drive speedhack / app helpers
        without retyping the package everywhere.
        """
        pkg = str(getattr(self, "package", "") or "").strip()
        if pkg:
            return pkg
        # Legacy nested package (older workflow JSON).
        pkg = str((self.speedhack_cfg or {}).get("package") or "").strip()
        if pkg:
            return pkg
        graphs = [a.get("graph", {}) or {} for a in self.activities()]
        graphs += [f.get("graph", {}) or {} for f in self._functions.values()]
        for g in graphs:
            for n in g.get("nodes", []) or []:
                if n.get("type") == "launch_app":
                    found = str((n.get("params", {}) or {}).get("package", "")).strip()
                    if found:
                        return found
        return ""

    def _resolve_package(self) -> str:
        """Canonical package for speedhack / app tools."""
        return self._auto_package()

    def _node_package(self, params: Dict[str, Any]) -> str:
        """Resolve package for launch_app / app_stop / app_uninstall / if_app.

        ``pkgSrc``:
          - ``project`` — use the workflow-level package (Project settings)
          - ``custom``  — free text / variable from the node's ``package`` field
          - missing     — legacy: explicit package wins; else fall back to project
        """
        p = params or {}
        src = str(p.get("pkgSrc") or "").strip().lower()
        if src == "project":
            return self._resolve_package()
        if src == "custom":
            return str(self._resolve_value(p.get("package", "")) or "").strip()
        # Legacy nodes (no pkgSrc): keep previous behaviour, but if package is
        # empty borrow the project package so old "blank" blocks still work.
        pkg = str(self._resolve_value(p.get("package", "")) or "").strip()
        if pkg:
            return pkg
        return self._resolve_package()

    def speedhack_info(self) -> Dict[str, Any]:
        """Current speedhack config + runtime state (for the GUI)."""
        cfg = self.speedhack_cfg or {}
        try:
            speed = float(cfg.get("speed", 2.0) or 2.0)
        except (TypeError, ValueError):
            speed = 2.0
        return {
            "enabled": self._truthy(cfg.get("enabled", False)),
            "speed": speed,
            "native": self._truthy(cfg.get("native", False)),
            "package": self._resolve_package(),
            "active": bool(self._speedhack and self._speedhack.active),
        }

    def configure_speedhack(self, enabled=None, speed=None, package=None, native=None) -> None:
        """Update the speedhack config; applies live if a run is in progress.

        ``package`` updates the workflow-level package (not nested under speedhack).
        ``native`` picks the compiled-C clock hook (faster, detected by some
        protected titles) and only takes effect on the next injection.
        """
        cfg = dict(self.speedhack_cfg or {})
        if enabled is not None:
            cfg["enabled"] = bool(enabled)
        if native is not None:
            cfg["native"] = bool(native)
        if speed is not None:
            try:
                cfg["speed"] = float(speed)
            except (TypeError, ValueError):
                pass
        if package is not None:
            self.package = str(package).strip()
            if isinstance(self.flow, dict):
                self.flow["package"] = self.package
        # Keep speedhack_cfg free of package (top-level owns it).
        cfg.pop("package", None)
        self.speedhack_cfg = cfg
        if not self.running:
            return
        # Live: reflect the change into the running injection.
        if self._truthy(cfg.get("enabled", False)):
            if self._speedhack is None:
                self._start_speedhack()
            else:
                # Also covers re-enabling after a park, where only the toggle
                # changed and ``speed`` came in as None.
                self.set_speed_scale(cfg.get("speed", self._speed_scale))
        elif self._speedhack is not None:
            # Park rather than tear down: unloading a hook that every thread
            # calls millions of times a second is itself a crash risk, and the
            # run may well re-enable it. _stop_speedhack() at the end of the run
            # does the real teardown.
            try:
                self._speedhack.reset()
            except Exception as e:
                log_warning(f"[speedhack] error while parking: {e}")
            self._speed_scale = 1.0

    def set_speed_scale(self, scale: float) -> bool:
        """Change the live time scale of a running speedhack injection."""
        try:
            scale = float(scale)
        except (TypeError, ValueError):
            return False
        self._speed_scale = scale
        self.speedhack_cfg["speed"] = scale
        if self._speedhack is None:
            return False
        try:
            return self._speedhack.set_scale(scale)
        except Exception as e:
            log_error(f"[speedhack] set scale failed: {e}")
            return False

    def _start_speedhack(self) -> None:
        cfg = self.speedhack_cfg or {}
        if not self._truthy(cfg.get("enabled", False)):
            return
        # Win32 projects have no Frida/ADB and we no longer inject a cheat
        # DLL — speed hack is ADB-only. Silently no-op in Win32 mode.
        if getattr(self, "_controller", "adb") == "win32":
            return
        if self._speedhack is not None:
            return
        package = self._resolve_package()
        if not package:
            log_warning("[speedhack] enabled but no game package (set 'package' next "
                        "to the workflow name, or add a Launch app block)")
            return
        try:
            scale = float(cfg.get("speed", 2.0) or 2.0)
        except (TypeError, ValueError):
            scale = 2.0
        if scale == 1.0:
            return
        mgr = FridaSpeedhackManager(
            package=package,
            use_cmodule=self._truthy(cfg.get("native", False)),
            scale_boottime=self._truthy(cfg.get("boottime", True)),
        )
        mgr.adb_controller = self.auto.adb
        if not mgr.available:
            log_warning("[speedhack] frida-inject not found in vendor/frida/")
            return
        self._speedhack = mgr
        self._speed_scale = scale
        self._speedhack_stop = threading.Event()
        # The game may still be launching, so inject in the background and retry
        # until its process exists rather than failing once at start.
        threading.Thread(
            target=self._speedhack_loop, args=(scale,), daemon=True
        ).start()

    def _speedhack_loop(self, scale: float) -> None:
        """Arm the speedhack, then keep it armed for the whole run.

        The loop does not stop at the first success: a game restart gives the
        package a new PID and takes the hook with the old one, so we keep
        checking and re-inject when the agent is gone. Without that watchdog the
        run silently continues at normal speed while the UI still says "Live".
        """
        stop_ev = self._speedhack_stop
        mgr = self._speedhack
        log_info(f"[speedhack] will accelerate '{mgr.package}' x{scale} once the game runs…")
        armed = False
        while (mgr is not None and not self._stop.is_set()
               and stop_ev is not None and not stop_ev.is_set()):
            try:
                if not armed:
                    if mgr.set_scale(scale):
                        armed = True
                        log_success(f"[speedhack] enabled x{scale}")
                elif not mgr.ensure_alive():
                    armed = False       # game gone: fall back to waiting for it
            except Exception as e:
                log_warning(f"[speedhack] retrying: {e}")
            # Wait ~5s before the next check, but stay responsive to stop.
            for _ in range(50):
                if self._stop.is_set() or stop_ev.is_set():
                    return
                time.sleep(0.1)

    def _stop_speedhack(self) -> None:
        ev = self._speedhack_stop
        if ev is not None:
            ev.set()
        self._speedhack_stop = None
        mgr = self._speedhack
        self._speedhack = None
        self._speed_scale = 1.0
        if mgr is None:
            return
        try:
            mgr.detach()
        except Exception as e:
            log_warning(f"[speedhack] error while disabling: {e}")

    def _delay_val(self, node: Dict, key: str, params: Dict) -> float:
        """Per-node pause (seconds) for delayBefore / delayAfter. Falls back to
        the legacy single ``delay`` param (read as delayBefore) so workflows
        saved before the split keep working without a rewrite."""
        v = node.get(key)
        if v is None and key == "delayBefore":
            v = params.get("delay")
        try:
            return max(0.0, float(v or 0))
        except (TypeError, ValueError):
            return 0.0

    def _sleep(self, seconds: float) -> None:
        """Pause-aware, stop-aware sleep."""
        end = time.time() + max(0.0, seconds)
        while time.time() < end and not self._stop.is_set():
            self._pause.wait()
            time.sleep(0.05)

    def debug_next(self) -> None:
        """Release one node when running in step-debug mode."""
        self._debug_gate.set()

    def _run_action_with_retry(self, node: Dict, params: Dict, handler: Callable[[Dict, Dict], bool]) -> bool:
        attempts = max(1, int(node.get("retryCount", 0) or 0) + 1)
        delay = max(0.0, float(node.get("retryDelay", 0) or 0))
        label = (NODE_TYPES.get(node.get("type"), {}).get("label") or node.get("type"))
        ok_act = False
        last_error: Optional[Exception] = None
        for attempt in range(1, attempts + 1):
            try:
                ok_act = handler(node, params) is not False
                last_error = None
            except Exception as e:
                log_error(f"[workflow] Node '{node.get('type')}' error: {e}")
                ok_act = False
                last_error = e
            if ok_act:
                return True
            if attempt < attempts and not self._stop.is_set():
                log_warning(f"[workflow] ✖ '{label}' fail → retry {attempt}/{attempts - 1}")
                if delay:
                    self._sleep(delay)
        self._branch_failed = True
        if last_error is None:
            log_warning(f"[workflow] ✖ '{label}' không thực hiện được")
        self._save_failure_screenshot(node)
        return False

    def _save_failure_screenshot(self, node: Dict) -> None:
        # Per-node opt-in, or the designer's "always capture" test-run mode.
        if not (node.get("screenshotOnFail") or self.capture_failures_always):
            return
        try:
            img = self.auto.capture_screen()
            if img is None:
                return
            import cv2
            out_dir = self.failure_screenshot_dir or os.path.join(os.getcwd(), "out", "workflow_failures")
            os.makedirs(out_dir, exist_ok=True)
            safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", str(node.get("id") or node.get("type") or "node"))
            path = os.path.join(out_dir, f"fail_{safe}_{time.strftime('%Y%m%d_%H%M%S')}.png")
            # Unicode-safe write (cv2.imwrite chokes on non-ASCII Windows paths).
            ok, buf = cv2.imencode(".png", img)
            if ok:
                buf.tofile(path)
                log_warning(f"[workflow] saved failure screenshot: {path}")
                self._emit("on_fail_shot", str(node.get("id") or ""), path)
        except Exception as e:
            log_warning(f"[workflow] save failure screenshot failed: {e}")

    # ── Action handlers ──────────────────────────────────────────────────────

    def _pos(self, p) -> tuple:
        """(x, y) for a tap-like node: the found image, or fixed coords."""
        if str(p.get("target", "pos")) == "found" and self._last_pos:
            return self._last_pos
        return (int(p.get("x", 0)), int(p.get("y", 0)))

    def _tap_at(self, x: int, y: int, params: Dict, label: str = "ảnh") -> bool:
        """Tap a found image's center, applying the node's optional offsetX/offsetY
        (handy when the thing to tap sits beside the matched icon). Honours the
        ``taps`` field (1 / 2-double) and logs the actual tapped point."""
        ox = int(params.get("offsetX", 0) or 0)
        oy = int(params.get("offsetY", 0) or 0)
        tx, ty = int(x) + ox, int(y) + oy
        tc = 2 if str(params.get("taps", "1")) in ("2", "double") else 1
        ok = bool(self.auto.tap(tx, ty, tap_count=tc))
        if ok:
            suffix = f" (+{ox},{oy})" if (ox or oy) else ""
            log_info(f"[workflow] 👆 chạm {label} ({tx}, {ty}){suffix}")
        return ok

    def _a_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        # taps=2 → chạm đúp: gộp công dụng của node double_tap (đã ẩn khỏi palette).
        taps = 2 if str(p.get("taps", "1")) == "2" else 1
        ok = self.auto.tap(x, y, tap_count=taps)
        if ok:
            log_info(f"[workflow] 👆 chạm ({x}, {y})" + (" ×2" if taps == 2 else ""))
        return ok

    def _a_multi_tap(self, node, p) -> bool:
        """Start two or more fixed touch points in one concurrent batch."""
        points = []
        for raw in p.get("points", []) if isinstance(p.get("points"), list) else []:
            try:
                if isinstance(raw, dict):
                    x, y = int(raw.get("x", 0)), int(raw.get("y", 0))
                elif isinstance(raw, (list, tuple)) and len(raw) >= 2:
                    x, y = int(raw[0]), int(raw[1])
                else:
                    continue
                points.append((x, y))
            except (TypeError, ValueError):
                continue
        if len(points) < 2:
            log_warning("[workflow] multi-point tap cần ít nhất 2 điểm")
            return False
        # Most Android devices expose at most ten touch slots. Limiting here also
        # prevents malformed workflow JSON from spawning an unbounded batch.
        points = points[:10]
        try:
            duration_ms = int(p.get("duration", 80) or 80)
        except (TypeError, ValueError):
            duration_ms = 80
        duration_ms = max(20, min(10_000, duration_ms))
        ok = bool(self.auto.multi_tap(points, duration_ms=duration_ms))
        if ok:
            coords = ", ".join(f"({x}, {y})" for x, y in points)
            log_info(f"[workflow] 👆 chạm đồng thời {len(points)} điểm: {coords} · {duration_ms}ms")
        return ok

    def _a_double_tap(self, node, p) -> bool:
        x, y = self._pos(p)
        ok = self.auto.tap(x, y, tap_count=2)
        if ok:
            log_info(f"[workflow] 👆 chạm đúp ({x}, {y})")
        return ok

    def _a_swipe_dir(self, node, p) -> bool:
        direction = str(p.get("direction", "up")).lower()
        dist = int(p.get("distance", 400))
        dur = int(p.get("duration", 300))
        try:
            w, h = self.auto.adb.get_screen_size()
        except Exception:
            w, h = 0, 0
        cx, cy = (w // 2, h // 2) if (w and h) else (540, 960)
        dx = dy = 0
        if direction == "up":
            dy = -dist
        elif direction == "down":
            dy = dist
        elif direction == "left":
            dx = -dist
        elif direction == "right":
            dx = dist
        return self.auto.swipe(cx, cy, cx + dx, cy + dy, dur)

    def _a_tap_random(self, node, p) -> bool:
        # New shape uses two explicit corners, which is easier to reason about
        # than x/y + width/height. Keep legacy params runnable for old JSON files.
        if any(k in p for k in ("x1", "y1", "x2", "y2")):
            x1, y1 = int(p.get("x1", 0)), int(p.get("y1", 0))
            x2, y2 = int(p.get("x2", 100)), int(p.get("y2", 100))
        else:
            x1, y1 = int(p.get("x", 0)), int(p.get("y", 0))
            x2 = x1 + max(0, int(p.get("w", 100)))
            y2 = y1 + max(0, int(p.get("h", 100)))
        lo_x, hi_x = sorted((x1, x2))
        lo_y, hi_y = sorted((y1, y2))
        rx = random.randint(lo_x, hi_x)
        ry = random.randint(lo_y, hi_y)
        ok = self.auto.tap(rx, ry)
        if ok:
            log_info(f"[workflow] 👆 chạm ngẫu nhiên ({rx}, {ry})")
        return ok

    def _a_wait_random(self, node, p) -> bool:
        lo = float(p.get("min", 0.5))
        hi = float(p.get("max", 2.0))
        if hi < lo:
            lo, hi = hi, lo
        dur = random.uniform(lo, hi)
        log_info(f"[workflow] ⏳ Đợi {dur:.1f}s (ngẫu nhiên {lo:g}–{hi:g}s)")
        self._sleep(dur)
        return True

    def _resolve_operand(self, raw: Any) -> float:
        """A calc operand: a number literal, or the value of a variable name."""
        s = str(raw).strip()
        if s in self._vars:
            v = self._coerce(self._vars[s])
            return float(v) if isinstance(v, (int, float)) else 0.0
        v = self._coerce(s)
        return float(v) if isinstance(v, (int, float)) else 0.0

    def _resolve_value(self, raw: Any) -> Any:
        """Resolve a param that may reference variables.

        Precedence: a bare variable name (the whole value equals a known var) →
        that variable's live value; a string containing ``{name}`` placeholders →
        filled from the current vars (like the Log field); otherwise the literal,
        best-effort number-coerced. Lets value fields (Set variable, If variable,
        loop count…) point at another variable instead of a fixed literal.
        """
        if isinstance(raw, (int, float, bool)):
            return raw
        s = str(raw)
        stripped = s.strip()
        if not stripped:
            return ""
        if stripped in self._vars:
            return self._vars[stripped]
        if "{" in s and "}" in s:
            return self._coerce(self._format_msg(s))
        return self._coerce(s)

    def _resolve_count(self, raw: Any, default: int = 0) -> int:
        """A loop/branch count that may be a number literal or a variable name."""
        val = self._resolve_value(raw)
        try:
            return max(0, int(float(val)))
        except (TypeError, ValueError):
            return default

    def _a_set_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if name:
            self._set_var(name, self._resolve_value(p.get("value", "")))
            log_info(f"[workflow] set {name} = {self._vars[name]!r}")
        return True

    def _a_calc_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        if not name:
            return True
        op = str(p.get("op", "+"))
        cur = self._resolve_operand(self._vars.get(name, 0))
        rhs = self._resolve_operand(p.get("value", 0))
        if op == "+":
            res = cur + rhs
        elif op == "-":
            res = cur - rhs
        elif op == "*":
            res = cur * rhs
        elif op == "/":
            res = cur / rhs if rhs else 0.0
        elif op == "%":
            # Modulo — cần cho counter vòng lặp ("mỗi 5 vòng thì …").
            res = (cur % rhs) if rhs else 0.0
        elif op == "min":
            res = min(cur, rhs)
        elif op == "max":
            res = max(cur, rhs)
        elif op == "round":
            # rhs = số chữ số thập phân.
            res = round(cur, int(rhs))
        elif op == "abs":
            res = abs(cur)
        else:  # "=" assign
            res = rhs
        # Keep ints clean (3.0 -> 3) for nicer comparisons/logs.
        if isinstance(res, float) and res.is_integer():
            res = int(res)
        self._set_var(name, res)
        log_info(f"[workflow] {name} {op}= {rhs} -> {res}")
        return True

    def _a_read_var(self, node, p) -> bool:
        name = str(p.get("name", "")).strip()
        region = self._region(p)
        text = self.auto.read_text(region=region, whitelist=self._ocr_whitelist(p)) or ""
        if name:
            self._set_var(name, self._coerce(text.strip()))
            log_info(
                f"[workflow] 🔤 read {name} = {self._vars[name]!r} "
                f"(OCR vùng {region}: {text!r})"
            )
        return True

    def _a_parse_var(self, node, p) -> bool:
        """Tách một đoạn text theo regex và lưu nhóm capture vào biến.

        Nguồn text: vùng OCR (mặc định, dùng x/y/w/h), hoặc giá trị của một
        biến có sẵn khi ``source`` = "var" (đọc từ ``fromVar``). Regex ``pattern``
        được áp dụng (re.search); nhóm capture thứ ``group`` (mặc định 1) được
        gán vào biến ``name``. Nếu không khớp, biến được đặt về "" và node vẫn
        trả về True (không phải lỗi—chỉ là không thấy).

        Ví dụ: text "5/5", pattern "(\\d+)/(\\d+)", group 1 -> name = "5".
        """
        name = str(p.get("name", "")).strip()
        src = str(p.get("source", "region")).strip().lower()
        if src == "var":
            text = str(self._vars.get(str(p.get("fromVar", "")).strip(), ""))
        else:
            region = self._region(p)
            try:
                text = self.auto.read_text(region=region, whitelist=self._ocr_whitelist(p)) or ""
                log_info(f"[workflow] 🔤 parse_var OCR vùng {region}: {text!r}")
            except Exception as exc:
                log_warning(f"[workflow] parse_var OCR lỗi: {exc}")
                text = ""
        pattern = str(p.get("pattern", "")).strip()
        if not pattern:
            if name:
                self._set_var(name, self._coerce(text.strip()))
                log_info(f"[workflow] parse {name} = {self._vars[name]!r} (không pattern)")
            return True
        try:
            m = re.search(pattern, text, re.MULTILINE)
        except re.error as exc:
            log_error(f"[workflow] parse_var regex lỗi: {exc}")
            if name:
                self._set_var(name, "")
            return False
        value = ""
        if m:
            try:
                grp = int(p.get("group", 1) or 1)
            except (TypeError, ValueError):
                grp = 1
            if 0 <= grp <= len(m.groups()):
                value = m.group(grp) or ""
            else:
                value = m.group(0) or ""
        if name:
            self._set_var(name, self._coerce(value.strip()))
            log_info(f"[workflow] parse {name} = {self._vars[name]!r} (từ {text!r})")
        return True

    def _a_break(self, node, p) -> bool:
        self._break_loop = True
        log_info("[workflow] break — sẽ thoát vòng lặp kế tiếp")
        return True

    def _a_long_press(self, node, p) -> bool:
        x, y = self._pos(p)
        return self.auto.adb.swipe(x, y, x, y, int(p.get("duration", 800)))

    def _a_swipe(self, node, p) -> bool:
        return self.auto.swipe(
            int(p.get("x1", 0)), int(p.get("y1", 0)),
            int(p.get("x2", 0)), int(p.get("y2", 0)),
            int(p.get("duration", 300)),
        )

    def _a_wait(self, node, p) -> bool:
        secs = float(p.get("seconds", 1.0))
        log_info(f"[workflow] ⏱ Đợi {secs:g}s")
        self._sleep(secs)
        return True

    def _a_send_text(self, node, p) -> bool:
        # Điền {var} vào text (giống Log) — gõ giá trị biến ra ô nhập của game.
        return self.auto.send_text(self._format_msg(str(p.get("text", ""))))

    def _a_key(self, node, p) -> bool:
        code = p.get("keycode", "")
        try:
            return self.auto.press_key(int(code))
        except (TypeError, ValueError):
            try:
                self.auto.adb.device.shell(f"input keyevent {code}")
                return True
            except Exception:
                return False

    def _a_back(self, node, p) -> bool:
        return self.auto.go_back()

    def _a_home(self, node, p) -> bool:
        return self.auto.go_home()

    def _a_app_stop(self, node, p) -> bool:
        """Force-stop một app (tuỳ chọn xóa dữ liệu) — cặp với launch_app cho
        flow 'game treo → dừng hẳn → mở lại'. Chỉ áp dụng cho dự án ADB."""
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] ⛔ Dừng ứng dụng chỉ áp dụng cho dự án ADB — dùng 'Đóng cửa sổ' cho Win32")
            return True
        pkg = self._node_package(p)
        if not pkg:
            log_warning("[workflow] ⛔ app_stop: chưa có package (Project settings hoặc Custom)")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            dev.shell(f"am force-stop {pkg}")
            if self._truthy(p.get("clearData", False)):
                dev.shell(f"pm clear {pkg}")
                log_info(f"[workflow] ⛔ đã dừng + xóa dữ liệu '{pkg}'")
            else:
                log_info(f"[workflow] ⛔ đã dừng '{pkg}'")
            return True
        except Exception as exc:
            log_warning(f"[workflow] app_stop lỗi: {exc}")
            return False

    def _a_app_uninstall(self, node, p) -> bool:
        """pm uninstall một app (tuỳ chọn -k giữ dữ liệu/cache). ADB-only."""
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] 🗑 Gỡ ứng dụng chỉ áp dụng cho dự án ADB — bỏ qua")
            return True
        pkg = self._node_package(p)
        if not pkg:
            log_warning("[workflow] 🗑 app_uninstall: chưa có package (Project settings hoặc Custom)")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            keep = "-k " if self._truthy(p.get("keepData", False)) else ""
            out = (dev.shell(f"pm uninstall {keep}{pkg}") or "").strip()
            ok = "success" in out.lower()
            if ok:
                log_info(f"[workflow] 🗑 đã gỡ '{pkg}'{' (giữ dữ liệu)' if keep else ''}")
            else:
                log_warning(f"[workflow] 🗑 gỡ '{pkg}' thất bại: {out or '(không có phản hồi)'}")
            return ok
        except Exception as exc:
            log_warning(f"[workflow] app_uninstall lỗi: {exc}")
            return False

    def _a_app_install(self, node, p) -> bool:
        """Cài một file .apk trên PC vào thiết bị (``adb -s <serial> install``).

        Dùng CLI adb (không phải shell) vì APK nằm trên PC và cần được push.
        ``reinstall`` (-r) giữ dữ liệu, ``grantPerms`` (-g) cấp sẵn quyền.
        """
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] 📦 Cài ứng dụng chỉ áp dụng cho dự án ADB — bỏ qua")
            return True
        apk = str(self._resolve_value(p.get("apk", ""))).strip().strip('"')
        if not apk:
            log_warning("[workflow] 📦 app_install: chưa chọn file APK")
            return False
        if not os.path.isfile(apk):
            log_warning(f"[workflow] 📦 app_install: không thấy file '{apk}'")
            return False
        serial = str(getattr(self.auto.adb, "device_id", "") or "").strip()
        if not serial:
            log_warning("[workflow] 📦 app_install: chưa có thiết bị")
            return False
        import subprocess

        from src.core.adb.constants import get_adb_path
        adb = get_adb_path()
        if not adb:
            log_warning("[workflow] 📦 app_install: không tìm thấy adb.exe")
            return False
        cmd = [adb, "-s", serial, "install"]
        if self._truthy(p.get("reinstall", True)):
            cmd.append("-r")
        if self._truthy(p.get("grantPerms", False)):
            cmd.append("-g")
        cmd.append(apk)
        try:
            timeout = max(10.0, float(p.get("timeout", 180) or 180))
            res = subprocess.run(
                cmd, capture_output=True, text=True, timeout=timeout, check=False,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
            out = ((res.stdout or "") + (res.stderr or "")).strip()
            ok = "success" in out.lower()
            if ok:
                log_success(f"[workflow] 📦 đã cài '{os.path.basename(apk)}'")
            else:
                log_warning(f"[workflow] 📦 cài '{os.path.basename(apk)}' thất bại: "
                            f"{out or '(không có phản hồi)'}")
            return ok
        except Exception as exc:
            log_warning(f"[workflow] app_install lỗi: {exc}")
            return False

    def _a_adb_shell(self, node, p) -> bool:
        """Chạy một câu ``adb shell`` tuỳ ý; lưu stdout vào biến (nếu có tên).

        Cửa thoát cho những gì chưa có node riêng. ``failIfEmpty`` cho phép coi
        "không có output" là thất bại để rẽ nhánh trong Try in order.
        """
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] 💻 ADB shell chỉ áp dụng cho dự án ADB — bỏ qua")
            return True
        cmd = str(self._resolve_value(p.get("command", ""))).strip()
        if not cmd:
            log_warning("[workflow] 💻 adb_shell: chưa có câu lệnh")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            log_warning("[workflow] 💻 adb_shell: chưa có thiết bị")
            return False
        try:
            out = (dev.shell(cmd) or "").strip()
        except Exception as exc:
            log_warning(f"[workflow] 💻 adb_shell '{cmd}' lỗi: {exc}")
            return False
        name = str(p.get("name", "") or "").strip()
        if name:
            self._set_var(name, self._coerce(out))
        log_info(f"[workflow] 💻 {cmd} → {out[:160]!r}"
                 + (f" (→ {name})" if name else ""))
        return not (self._truthy(p.get("failIfEmpty", False)) and not out)

    def _a_app_exit(self, node, p) -> bool:
        """Thoát app ĐANG mở: ADB force-stop app foreground (không cần biết
        package); Win32 đóng cửa sổ mục tiêu."""
        if getattr(self, "_controller", "adb") == "win32":
            ctrl = getattr(self.auto, "adb", None)
            if ctrl is None or not hasattr(ctrl, "close_window"):
                return False
            log_info("[workflow] 🚪 đóng cửa sổ mục tiêu")
            return bool(ctrl.close_window())
        try:
            if hasattr(self.auto.adb, "clear_info_cache"):
                self.auto.adb.clear_info_cache()
            cur = (self.auto.adb.get_current_app() or "").strip()
        except Exception:
            cur = ""
        if not cur:
            log_warning("[workflow] 🚪 không xác định được app đang mở")
            return False
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        try:
            dev.shell(f"am force-stop {cur}")
            log_info(f"[workflow] 🚪 đã thoát '{cur}'")
            return True
        except Exception as exc:
            log_warning(f"[workflow] app_exit lỗi: {exc}")
            return False

    def _a_launch_app(self, node, p) -> bool:
        # package: Project settings (pkgSrc=project) hoặc custom/var (pkgSrc=custom).
        pkg = self._node_package(p)
        if not pkg:
            log_warning("[workflow] 🚀 launch_app: chưa có package (Project settings hoặc Custom)")
            return False
        if not self.auto.adb.launch_app(pkg):
            return False
        # Optional: block until the app is actually in the foreground (0 = don't
        # wait). Lets "open game → tap image" work without a manual fixed delay.
        wait = float(p.get("wait", 0) or 0)
        if wait > 0:
            end = time.time() + wait
            while time.time() < end and not self._stop.is_set():
                self._pause.wait()
                try:
                    self.auto.adb.clear_info_cache()
                    cur = self.auto.adb.get_current_app() or ""
                except Exception:
                    cur = ""
                if cur and pkg in cur:
                    log_success(f"[workflow] '{pkg}' đã lên foreground")
                    return True
                time.sleep(0.5)
            log_warning(f"[workflow] '{pkg}' chưa lên foreground sau {wait:.0f}s")
        return True

    def _a_screenshot(self, node, p) -> bool:
        """Chụp màn hình và LƯU thành PNG (trước đây chỉ refresh frame trong RAM).

        ``save`` = false → chỉ làm mới frame (hành vi cũ, dùng khi chỉ cần ép
        capture lại trước một node ảnh). ``name`` nhận cả {var}; thư mục mặc
        định là ``out/screenshots`` cạnh workflow (hoặc cwd nếu chưa lưu file).
        """
        img = self.auto.capture_screen()
        if img is None:
            log_warning("[workflow] 📷 không lấy được frame")
            return False
        if not self._truthy(p.get("save", True)):
            return True
        raw = self._format_msg(str(p.get("name", "") or "")).strip()
        stem = re.sub(r"[^\w.\-]+", "_", raw).strip("._") or "shot"
        folder = str(self._resolve_value(p.get("folder", ""))).strip()
        if not folder:
            anchor = (os.path.dirname(self.flow_path) if self.flow_path
                      else (self.templates_base or os.getcwd()))
            folder = os.path.join(anchor, "out", "screenshots")
        try:
            import cv2
            os.makedirs(folder, exist_ok=True)
            path = os.path.join(folder, f"{stem}_{time.strftime('%Y%m%d_%H%M%S')}.png")
            # Unicode-safe write (cv2.imwrite chokes on non-ASCII Windows paths).
            ok, buf = cv2.imencode(".png", img)
            if not ok:
                log_warning("[workflow] 📷 mã hoá PNG thất bại")
                return False
            buf.tofile(path)
            log_info(f"[workflow] 📷 đã lưu {path}")
            name = str(p.get("pathVar", "") or "").strip()
            if name:
                self._set_var(name, path)
            return True
        except Exception as exc:
            log_warning(f"[workflow] 📷 lưu ảnh lỗi: {exc}")
            return False

    def _a_log(self, node, p) -> bool:
        log_info(f"[workflow] {self._format_msg(p.get('message', ''))}")
        return True

    def _a_format_var(self, node, p) -> bool:
        name     = str(p.get("name", "")).strip()
        template = str(p.get("template", ""))
        result   = template
        for k, v in list(self._vars.items()):
            result = result.replace(f"{{{k}}}", str(v))
        if name:
            self._set_var(name, result)
            log_info(f"[workflow] 📝 {name} = \"{result}\"")
        return True

    def _a_notify(self, node, p) -> bool:
        # Title cũng điền {var} như message (designer đánh dấu insertVar cả hai).
        title   = self._format_msg(str(p.get("title", "Workflow"))).strip() or "Workflow"
        message = self._format_msg(str(p.get("message", "Đã hoàn thành!")))
        sound   = bool(p.get("sound", True))
        log_info(f"[workflow] 🔔 [{title}] {message}")
        if sound:
            try:
                import winsound
                winsound.MessageBeep(winsound.MB_ICONASTERISK)
            except Exception:
                pass
        try:
            import subprocess
            safe_t = title.replace('"', '\\"')
            safe_m = message.replace('"', '\\"')
            ps = (
                "Add-Type -AssemblyName System.Windows.Forms;"
                "$n=New-Object System.Windows.Forms.NotifyIcon;"
                "$n.Icon=[System.Drawing.SystemIcons]::Information;"
                "$n.Visible=$true;"
                f'$n.ShowBalloonTip(6000,"{safe_t}","{safe_m}",'
                "[System.Windows.Forms.ToolTipIcon]::Info);"
                "Start-Sleep 7;$n.Dispose()"
            )
            subprocess.Popen(
                ["powershell", "-WindowStyle", "Hidden", "-NonInteractive", "-Command", ps],
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        except Exception:
            pass
        return True

    # ── Device / time handlers ────────────────────────────────────────────────

    def _a_get_time(self, node, p) -> bool:
        """Read the current local time into a variable, in the chosen shape."""
        name = str(p.get("name", "")).strip()
        part = str(p.get("part", "hm")).strip().lower()
        now = time.localtime()
        if part == "timestamp":
            val: Any = int(time.time())
        elif part == "hour":
            val = now.tm_hour
        elif part == "minute":
            val = now.tm_min
        elif part == "second":
            val = now.tm_sec
        elif part == "hms":
            val = time.strftime("%H:%M:%S", now)
        elif part == "date":
            val = time.strftime("%Y-%m-%d", now)
        elif part == "datetime":
            val = time.strftime("%Y-%m-%d %H:%M:%S", now)
        elif part == "weekday":
            val = now.tm_wday + 1  # 1 = Monday … 7 = Sunday
        elif part == "custom":
            val = time.strftime(str(p.get("format", "%H:%M")), now)
        else:  # "hm"
            val = time.strftime("%H:%M", now)
        if name:
            self._set_var(name, val)
            log_info(f"[workflow] 🕒 {name} = {self._vars[name]!r}")
        return True

    def _wait_until_clock(self, target: str, next_day: bool = True) -> bool:
        """Block until a wall-clock ``HH:MM`` (or ``HH:MM:SS``). If the time is
        already past today, wait until the same time tomorrow (unless disabled).
        Returns False only on a malformed time string. Shared by the ``wait_until``
        node and ``launch_emulator``'s optional ``at`` schedule."""
        m = re.match(r"^\s*(\d{1,2}):(\d{2})(?::(\d{2}))?\s*$", target)
        if not m:
            log_warning(f"[workflow] ⏰ Hẹn giờ: định dạng không hợp lệ '{target}' (cần HH:MM)")
            return False
        hh, mm, ss = int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)
        now = time.localtime()
        now_secs = now.tm_hour * 3600 + now.tm_min * 60 + now.tm_sec
        delay = (hh * 3600 + mm * 60 + ss) - now_secs
        if delay <= 0:
            if next_day:
                delay += 86400
            else:
                log_info(f"[workflow] ⏰ {hh:02d}:{mm:02d} đã qua — bỏ qua chờ")
                return True
        log_info(f"[workflow] ⏰ Hẹn giờ đến {hh:02d}:{mm:02d}:{ss:02d} — chờ {delay}s")
        self._sleep(delay)
        return True

    def _a_wait_until(self, node, p) -> bool:
        return self._wait_until_clock(str(p.get("time", "")).strip(), bool(p.get("nextDay", True)))

    def _a_device_info(self, node, p) -> bool:
        """Read a live device property into a variable (battery, app, size…)."""
        name = str(p.get("name", "")).strip()
        prop = str(p.get("prop", "battery")).strip().lower()
        val = self._read_device_prop(prop)
        if name:
            self._set_var(name, val)
            log_info(f"[workflow] 📱 {name} = {self._vars[name]!r} ({prop})")
        return True

    def _read_device_prop(self, prop: str) -> Any:
        dev = getattr(self.auto.adb, "device", None)

        def _sh(cmd: str) -> str:
            return (dev.shell(cmd) if dev else "") or ""

        try:
            if prop == "battery":
                m = re.search(r"level:\s*(\d+)", _sh("dumpsys battery"))
                return int(m.group(1)) if m else 0
            if prop == "current_app":
                return self.auto.adb.get_current_app() or ""
            if prop in ("width", "height"):
                w, h = self.auto.adb.get_screen_size()
                return int(w if prop == "width" else h)
            if prop == "model":
                return _sh("getprop ro.product.model").strip()
            if prop == "brand":
                return _sh("getprop ro.product.brand").strip()
            if prop == "android":
                return _sh("getprop ro.build.version.release").strip()
            if prop == "sdk":
                v = _sh("getprop ro.build.version.sdk").strip()
                return int(v) if v.isdigit() else v
            if prop == "serial":
                return str(getattr(self.auto.adb, "device_id", "") or "")
            if prop == "ip":
                m = re.search(r"src\s+(\d+\.\d+\.\d+\.\d+)", _sh("ip route"))
                return m.group(1) if m else ""
        except Exception as exc:
            log_warning(f"[workflow] device_info '{prop}' lỗi: {exc}")
        return ""

    def _a_screen_power(self, node, p) -> bool:
        """Wake, sleep, or toggle the device screen via key events."""
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] 🖥 Bật/tắt màn hình không áp dụng cho dự án Win32 — bỏ qua")
            return True
        action = str(p.get("action", "on")).strip().lower()
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False
        # KEYCODE_POWER 26 · KEYCODE_SLEEP 223 · KEYCODE_WAKEUP 224
        try:
            if action == "toggle":
                dev.shell("input keyevent 26")
            else:
                out = dev.shell("dumpsys power") or ""
                is_on = ("mWakefulness=Awake" in out) or ("Display Power: state=ON" in out)
                if action == "on" and not is_on:
                    dev.shell("input keyevent 224")
                elif action == "off" and is_on:
                    dev.shell("input keyevent 223")
            log_info(f"[workflow] 🖥 màn hình: {action}")
            return True
        except Exception as exc:
            log_warning(f"[workflow] screen_power '{action}' lỗi: {exc}")
            return False

    # ── Emulator launch ───────────────────────────────────────────────────────

    def _a_launch_emulator(self, node, p) -> bool:
        """Boot the emulator *process* on the PC (LDPlayer/MuMu/Nox/MEmu/
        BlueStacks). Optional ``at`` (HH:MM) waits until that clock time first;
        optional ``wait`` seconds then polls the instance's ADB port until it is
        connectable (so the very next node can drive the freshly-booted device).
        """
        at = str(p.get("at", "")).strip()
        if at and not self._wait_until_clock(at, bool(p.get("nextDay", True))):
            return False  # malformed schedule time

        kind = str(p.get("emulator", "ldplayer")).strip().lower()
        try:
            index = int(float(p.get("index", 0) or 0))
        except (TypeError, ValueError):
            index = 0

        argv = self._emulator_launch_argv(p, kind, index)
        if not argv:
            log_error(
                f"[workflow] ▶ Không dựng được lệnh mở '{kind}' — đặt 'Đường dẫn' "
                f"tới thư mục cài / console .exe, hoặc dùng 'Lệnh tùy chỉnh'"
            )
            return False

        import subprocess
        try:
            log_info(f"[workflow] ▶ Mở giả lập: {' '.join(argv)}")
            subprocess.Popen(
                argv,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000),
            )
        except Exception as exc:
            log_error(f"[workflow] ▶ Mở giả lập lỗi: {exc}")
            return False

        wait = float(p.get("wait", 0) or 0)
        port = self._emulator_adb_port(p, kind, index)
        host: Optional[str] = None
        if wait > 0:
            # The console only publishes the real port once the instance is up,
            # so keep re-asking it while polling instead of trusting the
            # pre-boot guess.
            host = self._wait_emulator_adb(
                port, wait,
                resolver=lambda: self._emulator_adb_port(p, kind, index))
            if host:
                try:
                    port = int(host.rsplit(":", 1)[1])
                except (IndexError, ValueError):
                    pass
        # Remember which instance this flow booted so if_emulator's "last used"
        # option can re-check the same one on future runs.
        self._save_emulator_state({
            "emulator": kind,
            "index": index,
            "instance": str(p.get("instance", "") or ""),
            "path": str(p.get("path", "") or ""),
            "port": port,
            "serial": host or (f"127.0.0.1:{port}" if port else None),
            "launched_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        })
        # Flows started with no device (deferred readiness in _ensure_ready)
        # attach to the freshly booted emulator here so the next node can run.
        if getattr(self, "_controller", "adb") != "win32" and not self.auto.adb.device:
            self._attach_adb_after_boot(host)
        return True

    @staticmethod
    def _save_emulator_state(state: Dict[str, Any]) -> None:
        path = _emulator_state_path()
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
            with open(path, "w", encoding="utf-8") as fh:
                json.dump(state, fh, ensure_ascii=False, indent=2)
        except Exception as exc:
            log_warning(f"[workflow] Couldn't save the emulator state: {exc}")

    @staticmethod
    def _load_emulator_state() -> Optional[Dict[str, Any]]:
        try:
            with open(_emulator_state_path(), "r", encoding="utf-8") as fh:
                return json.load(fh) or None
        except Exception:
            return None

    def _resolve_emulator_target(self, p: Dict) -> Optional[tuple]:
        """Resolve ``(kind, index, host)`` for if_emulator / wait_emulator.

        ``emulator`` = "last" re-checks the instance the last successful
        launch_emulator saved. The port comes from the explicit override, then
        the family console's own report, then the state file, then the
        port0+index*step formula — the console is asked before the saved value
        because MuMu Global's real port can differ from the derived one, and a
        stale saved port would make a healthy emulator look unready. Returns
        None when the target can't be resolved.
        """
        kind = str(p.get("emulator", "last")).strip().lower() or "last"
        try:
            index = int(float(p.get("index", 0) or 0))
        except (TypeError, ValueError):
            index = 0
        # Blank/0 port = "auto" (the designer serializes an empty num field as 0).
        port: Optional[int] = None
        override = str(p.get("port", "") or "").strip()
        if override:
            try:
                val = int(float(override))
                port = val if val > 0 else None
            except (TypeError, ValueError):
                port = None
        saved_port: Optional[int] = None
        path = str(self._resolve_value(p.get("path", "")) or "").strip()
        if kind == "last":
            saved = self._load_emulator_state()
            if not saved:
                log_warning("[workflow] 🖥 No saved emulator yet — run a Launch emulator node once first")
                return None
            kind = str(saved.get("emulator") or "?").lower()
            try:
                index = int(saved.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            if not path:
                path = str(saved.get("path") or "").strip()
            try:
                val = int(saved.get("port") or 0)
                saved_port = val if val > 0 else None
            except (TypeError, ValueError):
                saved_port = None
        if port is None:
            port = self._emulator_adb_port({"path": path}, kind, index)
        if port is None:
            port = saved_port
        if port is None:
            log_warning(f"[workflow] 🖥 Can't derive the ADB port for '{kind}' — set 'ADB port override'")
            return None
        return kind, index, f"127.0.0.1:{port}"

    def _maybe_attach_emulator(self, p: Dict, host: str) -> None:
        """Attach ADB to ``host`` when ``attach`` is on and no device is bound yet."""
        if (bool(p.get("attach", True))
                and getattr(self, "_controller", "adb") != "win32"
                and not self.auto.adb.device):
            self._attach_adb_after_boot(host)

    def _emulator_pc_target(self, p: Dict, verb: str) -> Optional[tuple]:
        """Resolve ``(kind, index, install_dir, instance)`` for the PC-side
        emulator nodes (resize / kill / restart / device resolution).

        ``emulator`` = "last" reuses the instance the last successful
        launch_emulator saved (family + index + install path + BlueStacks
        instance name). Returns None when the family can't be determined; the
        reason is logged here.
        """
        kind = str(p.get("emulator", "last")).strip().lower() or "last"
        try:
            index = int(float(p.get("index", 0) or 0))
        except (TypeError, ValueError):
            index = 0
        path = str(self._resolve_value(p.get("path", "")) or "").strip()
        instance = str(p.get("instance", "") or "").strip()
        if kind == "last":
            saved = self._load_emulator_state()
            if not saved:
                log_warning(f"[workflow] 🖥 {verb}: chưa có giả lập nào được lưu — "
                            f"chạy node 'Mở giả lập' trước, hoặc chọn hãng giả lập cụ thể")
                return None
            kind = str(saved.get("emulator") or "").lower()
            try:
                index = int(saved.get("index") or 0)
            except (TypeError, ValueError):
                index = 0
            if not path:
                path = str(saved.get("path") or "").strip()
            if not instance:
                instance = str(saved.get("instance") or "").strip()
        if kind not in EMU_PLAYER_EXES:
            log_warning(f"[workflow] 🖥 {verb}: không nhận diện được hãng giả lập '{kind}' — chọn hãng cụ thể trong node")
            return None
        return kind, index, path, instance

    def _run_emulator_console(self, kind: str, path: str, args_key: str,
                              index: int, extra: Optional[Dict[str, Any]] = None,
                              timeout: float = 30.0) -> Optional[str]:
        """Run one console verb (``args_key`` in EMULATOR_CONSOLES) for *index*.

        Returns the command's stdout on success; None when the family has no
        such verb, the console exe can't be found, or the call raised — the
        caller then decides whether a Win32 fallback applies.
        """
        import subprocess
        spec = EMULATOR_CONSOLES.get(kind) or {}
        template = spec.get(args_key)
        if not template:
            return None
        exe = self._resolve_console_exe(
            path, spec.get("exes", []), spec.get("dirs", []), spec.get("subdirs"))
        if not exe:
            return None
        subs = {"index": str(index), **{k: str(v) for k, v in (extra or {}).items()}}
        argv = [exe]
        for a in template:
            for k, v in subs.items():
                a = a.replace("{" + k + "}", v)
            argv.append(a)
        try:
            log_info(f"[workflow] 🖥 {' '.join(argv)}")
            r = subprocess.run(
                argv, capture_output=True, text=True, timeout=timeout,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            return r.stdout or ""
        except Exception as exc:
            log_warning(f"[workflow] 🖥 Console '{args_key}' lỗi: {exc}")
            return None

    def _taskkill_emulator_window(self, kind: str, path: str) -> Optional[bool]:
        """Force-kill the process tree owning the family's player window.

        True = killed, None = no window found (already closed), False = error.
        """
        import subprocess
        hwnd = _find_emulator_window(kind, path)
        if not hwnd:
            return None
        try:
            import win32process
            pid = win32process.GetWindowThreadProcessId(hwnd)[1]
            subprocess.run(["taskkill", "/PID", str(pid), "/T", "/F"],
                           capture_output=True, text=True, timeout=15,
                           creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            return True
        except Exception as exc:
            log_warning(f"[workflow] 🖥 Taskkill giả lập lỗi: {exc}")
            return False

    def _a_resize_emulator(self, node, p) -> bool:
        """Resize the emulator's PC window so the ANDROID RENDER AREA becomes
        width×height — the thing that decides whether the device is letterboxed.

        Two layers of chrome sit between the outer frame and the device view:
        the title bar/borders, and (on MuMu) a ~40px toolbar strip inside the
        client area. Sizing either the frame or the client to 1920×1080 leaves
        the render surface short of 16:9, so the player pillarboxes the device →
        black bars down both sides. Both deltas are therefore measured live
        (GetWindowRect vs the largest child window) and added on top. Unlike
        ``win_resize`` — which resizes the flow's Win32 target window — this
        needs no controller, so it works in ADB flows; the player window is
        found via the family's process names ("last" = the instance the last
        successful launch_emulator saved). Keeps the restore-if-maximized +
        WM_SIZE nudge, because the Qt/DX player windows otherwise ignore plain
        SetWindowPos.
        """
        target = self._emulator_pc_target(p, "Resize")
        if not target:
            return False
        kind, index, install_dir, _ = target
        try:
            w = max(200, int(float(p.get("width", 1920) or 1920)))
            h = max(200, int(float(p.get("height", 1080) or 1080)))
        except (TypeError, ValueError):
            w, h = 1920, 1080
        hwnd = _find_emulator_window(kind, install_dir)
        if not hwnd:
            log_warning(f"[workflow] 🖥 Không thấy cửa sổ giả lập '{kind}' #{index} — giả lập chưa mở?")
            return False
        try:
            import win32api
            import win32con
            import win32gui
            placement = win32gui.GetWindowPlacement(hwnd)
            if placement[1] == win32con.SW_SHOWMAXIMIZED:
                win32gui.ShowWindow(hwnd, win32con.SW_RESTORE)
                time.sleep(0.05)
            l, t, r, b = win32gui.GetWindowRect(hwnd)
            # Chrome = outer frame minus the render surface. Fall back to the
            # client rect for players that draw into their own client area.
            child = _emulator_render_child(hwnd)
            if child:
                _, rw, rh = child
            else:
                cl, ct, cr, cb = win32gui.GetClientRect(hwnd)
                rw, rh = cr - cl, cb - ct
            dx = max(0, (r - l) - rw)
            dy = max(0, (b - t) - rh)
            # Optional reposition — blank X/Y keeps the window where it is, so a
            # flow can also park several instances side by side.
            for key in ("x", "y"):
                val = str(p.get(key, "")).strip()
                if val in ("", "None"):
                    continue
                try:
                    if key == "x":
                        l = int(float(val))
                    else:
                        t = int(float(val))
                except (TypeError, ValueError):
                    pass
            SWP_NOZORDER, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0004, 0x0010, 0x0020
            win32gui.SetWindowPos(hwnd, 0, l, t, w + dx, h + dy,
                                  SWP_NOZORDER | SWP_NOACTIVATE | SWP_FRAMECHANGED)
            # WM_SIZE carries the new *client* size (render + toolbar strip).
            win32api.SendMessage(hwnd, 0x0005, 0, ((h + dy - 4) << 16) | ((w + dx) & 0xFFFF))
            time.sleep(0.3)  # Qt relayouts the render child asynchronously
            after = _emulator_render_child(hwnd)
            got = (after[1], after[2]) if after else None
            if got and got != (w, h):
                log_warning(f"[workflow] 🖥 Vùng hiển thị sau resize là {got[0]}×{got[1]} "
                            f"(yêu cầu {w}×{h}) — window có thể bị kẹp kích thước tối thiểu")
            log_success(f"[workflow] 🖥 Resize giả lập {kind} #{index} → hiển thị {w}×{h} tại ({l}, {t})")
            return True
        except Exception as exc:
            log_warning(f"[workflow] 🖥 Resize giả lập lỗi: {exc}")
            return False

    def _a_kill_emulator(self, node, p) -> bool:
        """Kill the emulator instance — closing the app inside ≠ closing the
        emulator; the instance keeps running and holds its RAM/CPU + ADB port.

        Preferred path is the family's console shutdown (LDPlayer/MuMu/Nox/
        MEmu; BlueStacks has none). When the console can't be resolved — or the
        family has no console shutdown — fall back to taskkilling the process
        tree that owns the player window (the same window resize_emulator
        finds). Returns True when the kill command was issued or there was
        nothing to kill; False only when the target couldn't even be resolved.
        """
        target = self._emulator_pc_target(p, "Tắt giả lập")
        if not target:
            return False
        kind, index, path, _ = target

        # 1) console shutdown — leaves no zombie VM process behind.
        if self._run_emulator_console(kind, path, "quit_args", index) is not None:
            log_success(f"[workflow] 🖥 Đã tắt giả lập {kind} #{index}")
            return True
        # 2) fallback: taskkill the player window's process tree (BlueStacks has
        #    no console verb; or the console exe couldn't be resolved).
        killed = self._taskkill_emulator_window(kind, path)
        if killed is None:
            log_info(f"[workflow] 🖥 Không thấy cửa sổ giả lập '{kind}' #{index} (đã tắt sẵn? — bỏ qua)")
            return True
        if not killed:
            return False
        log_success(f"[workflow] 🖥 Đã tắt giả lập {kind} #{index}")
        return True

    def _a_restart_emulator(self, node, p) -> bool:
        """Reboot the emulator instance — the fix for a wedged Android session
        (frozen UI, ADB gone, app stuck) that ``app_stop`` can't clear.

        Console ``reboot``/``restart`` when the family has one, else kill the
        player and relaunch it via the same argv launch_emulator builds. With
        ``wait`` > 0 the node then polls the instance's ADB until Android
        reports ``sys.boot_completed`` so the next node can drive the device.
        """
        target = self._emulator_pc_target(p, "Restart giả lập")
        if not target:
            return False
        kind, index, path, instance = target
        try:
            wait = max(0.0, float(p.get("wait", 120) or 0))
        except (TypeError, ValueError):
            wait = 120.0

        if self._run_emulator_console(kind, path, "restart_args", index) is None:
            # No console restart verb (BlueStacks) → kill, then relaunch.
            log_info(f"[workflow] 🖥 '{kind}' không có lệnh restart — tắt rồi mở lại")
            killed = self._taskkill_emulator_window(kind, path)
            if killed is False:
                return False
            if killed:
                time.sleep(3.0)  # let the VM processes actually exit
            argv = self._emulator_launch_argv(
                {**p, "path": path, "instance": instance, "command": ""}, kind, index)
            if not argv:
                log_error(f"[workflow] 🖥 Không dựng được lệnh mở lại '{kind}' — đặt 'Đường dẫn' tới thư mục cài")
                return False
            import subprocess
            try:
                log_info(f"[workflow] 🖥 Mở lại giả lập: {' '.join(argv)}")
                subprocess.Popen(argv, creationflags=getattr(
                    subprocess, "CREATE_NO_WINDOW", 0x08000000))
            except Exception as exc:
                log_error(f"[workflow] 🖥 Mở lại giả lập lỗi: {exc}")
                return False

        if wait <= 0:
            log_success(f"[workflow] 🖥 Đã gửi lệnh restart giả lập {kind} #{index}")
            return True
        # An instance that is still shutting down would answer the *old* ADB
        # session; give it a moment before polling for the fresh boot.
        time.sleep(3.0)
        port = self._emulator_adb_port(p, kind, index)
        host = f"127.0.0.1:{port}" if port else None
        if not host:
            log_warning(f"[workflow] 🖥 Không suy ra được cổng ADB của '{kind}' #{index} — bỏ qua bước chờ")
            return True
        end = time.time() + wait
        while not self._stop.is_set():
            self._pause.wait()
            if self._emulator_adb_ready(host):
                log_success(f"[workflow] 🖥 Giả lập {kind} #{index} đã restart & boot xong ({host})")
                self._maybe_attach_emulator(p, host)
                return True
            if time.time() >= end:
                break
            time.sleep(1.0)
        log_warning(f"[workflow] 🖥 Giả lập {kind} #{index} chưa boot xong sau {wait:.0f}s")
        return False

    def _a_emulator_resolution(self, node, p) -> bool:
        """Set the emulator's *device* resolution (Android screen px + DPI).

        This is the setting that actually decides what the templates were
        cropped against — ``resize_emulator`` only changes the PC window, so a
        window at 1920×1080 over a 1600×900 device still letterboxes. Only MuMu
        exposes it on the console (``setting --key resolution_*``); the change
        needs a restart of the instance to take effect, which ``restart`` does
        here when asked.
        """
        target = self._emulator_pc_target(p, "Đổi resolution")
        if not target:
            return False
        kind, index, path, _ = target
        spec = EMULATOR_CONSOLES.get(kind) or {}
        keys = spec.get("res_keys")
        if not keys:
            log_warning(f"[workflow] 🖥 '{kind}' không hỗ trợ đổi resolution qua console — "
                        f"đổi tay trong Settings của giả lập (chỉ MuMu hỗ trợ)")
            return False
        try:
            w = max(200, int(float(p.get("width", 1920) or 1920)))
            h = max(200, int(float(p.get("height", 1080) or 1080)))
            dpi = max(80, int(float(p.get("dpi", 280) or 280)))
        except (TypeError, ValueError):
            w, h, dpi = 1920, 1080, 280
        exe = self._resolve_console_exe(
            path, spec.get("exes", []), spec.get("dirs", []), spec.get("subdirs"))
        if not exe:
            log_warning(f"[workflow] 🖥 Không thấy console của '{kind}' — đặt 'Đường dẫn' tới thư mục cài")
            return False
        # A custom w/h/dpi only applies when the mode is switched off the presets.
        argv = [exe, "setting", "-v", str(index),
                "-k", keys["mode"], "-val", "custom",
                "-k", keys["width"], "-val", str(w),
                "-k", keys["height"], "-val", str(h),
                "-k", keys["dpi"], "-val", str(dpi)]
        import subprocess
        try:
            log_info(f"[workflow] 🖥 {' '.join(argv)}")
            r = subprocess.run(argv, capture_output=True, text=True, timeout=30,
                               creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000))
            out = (r.stdout or "") + (r.stderr or "")
        except Exception as exc:
            log_warning(f"[workflow] 🖥 Đổi resolution lỗi: {exc}")
            return False
        if "errcode" in out.lower() and '"errcode": 0' not in out:
            log_warning(f"[workflow] 🖥 Console từ chối đổi resolution: {out.strip()[:200]}")
            return False
        log_success(f"[workflow] 🖥 Resolution giả lập {kind} #{index} → {w}×{h} @ {dpi}dpi")
        if bool(p.get("restart", True)):
            # The instance reads resolution at boot, so it must cycle to apply.
            return self._a_restart_emulator(node, {**p, "wait": p.get("wait", 120)})
        log_info("[workflow] 🖥 Cần restart giả lập để resolution mới có hiệu lực")
        return True

    def _c_if_emulator(self, p: Dict) -> bool:
        """True when the target emulator instance is booted and its ADB answers
        (``adb connect`` + ``sys.boot_completed`` == 1).

        ``emulator`` = "last" (default) re-checks the instance the last
        successful launch_emulator saved — "is the one I set still running?".
        With ``attach`` on (default), a flow that started with no device binds
        to the ready instance so the following nodes can drive it.
        """
        target = self._resolve_emulator_target(p)
        if not target:
            return False
        kind, index, host = target
        ready = self._emulator_adb_ready(host)
        log_info(f"[workflow] 🖥 Emulator {kind} #{index} ({host}) → {'ready' if ready else 'not ready'}")
        if ready:
            self._maybe_attach_emulator(p, host)
        return ready

    def _c_wait_emulator(self, p: Dict) -> bool:
        """Poll until the target emulator finishes booting (ADB +
        ``sys.boot_completed``) or ``timeout`` seconds elapse.

        true  → ready (and optionally attached as the active device)
        false → timeout / unresolvable target / stopped mid-wait
        """
        target = self._resolve_emulator_target(p)
        if not target:
            return False
        kind, index, host = target
        try:
            timeout = float(p.get("timeout", 120) or 120)
        except (TypeError, ValueError):
            timeout = 120.0
        timeout = max(0.0, timeout)
        log_info(
            f"[workflow] ⏳ Waiting for emulator {kind} #{index} ({host}) "
            f"up to {timeout:.0f}s…"
        )
        end = time.time() + timeout
        # Immediate probe first so an already-booted instance returns instantly.
        while not self._stop.is_set():
            self._pause.wait()
            if self._emulator_adb_ready(host):
                log_success(
                    f"[workflow] ⏳ Emulator {kind} #{index} ({host}) ready"
                )
                self._maybe_attach_emulator(p, host)
                return True
            if time.time() >= end:
                break
            # Short sleep so stop/pause stay responsive; boot often takes tens of s.
            time.sleep(1.0)
        if self._stop.is_set():
            log_warning(f"[workflow] ⏳ Wait emulator cancelled ({host})")
        else:
            log_warning(
                f"[workflow] ⏳ Emulator {kind} #{index} ({host}) not ready "
                f"after {timeout:.0f}s"
            )
        return False

    @staticmethod
    def _emulator_adb_ready(host: str) -> bool:
        """One-shot readiness probe: ``adb connect`` succeeds AND the instance
        reports ``sys.boot_completed`` == 1 (Android finished booting)."""
        from src.core.adb.constants import get_adb_path
        import subprocess
        adb = get_adb_path()
        flags = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)
        try:
            r = subprocess.run(
                [adb, "connect", host],
                capture_output=True, text=True, timeout=5, creationflags=flags,
            )
            if "connected" not in (r.stdout or "").lower():
                return False
            r = subprocess.run(
                [adb, "-s", host, "shell", "getprop", "sys.boot_completed"],
                capture_output=True, text=True, timeout=5, creationflags=flags,
            )
            return (r.stdout or "").strip() == "1"
        except Exception:
            return False

    def _attach_adb_after_boot(self, serial: Optional[str]) -> None:
        """Bind the engine to the emulator that launch_emulator just booted:
        select its ADB serial (if known), then start capture — the steps
        _ensure_ready() skipped when the flow started with no device."""
        try:
            adb = self.auto.adb
            if serial:
                adb.device_id = serial
            adb.check_adb_connection()
            if not adb.device:
                log_warning(
                    "[workflow] No ADB device after the emulator launch — "
                    "set 'Wait' on the Launch emulator node so it can finish booting"
                )
                return
            self.auto._update_screen_size()
            if not getattr(self.auto, "capture_running", False):
                self.auto.start_continuous_capture()
        except Exception as exc:
            log_warning(f"[workflow] Couldn't attach to the booted emulator: {exc}")

    def _emulator_launch_argv(self, p: Dict, kind: str, index: int) -> Optional[List[str]]:
        """Build the console argv for booting one instance, or None if it can't be
        resolved. A custom command always wins; otherwise the per-family console
        exe is discovered under the given path or the default install dirs."""
        path = str(self._resolve_value(p.get("path", ""))).strip()
        custom = str(p.get("command", "")).strip()
        if kind == "custom" or custom:
            if not custom:
                return None
            cmd = custom.replace("{index}", str(index)).replace("{path}", path)
            try:
                import shlex
                return shlex.split(cmd, posix=False)
            except Exception:
                return [cmd]

        spec = EMULATOR_CONSOLES.get(kind)
        if not spec:
            return None
        exe = self._resolve_console_exe(path, spec["exes"], spec["dirs"], spec.get("subdirs"))
        if not exe:
            return None
        instance = str(p.get("instance", "") or index)
        args = [a.replace("{index}", str(index)).replace("{instance}", instance)
                for a in spec["args"]]
        return [exe] + args

    @staticmethod
    def _resolve_console_exe(path: str, exes: List[str], dirs: List[str],
                             subdirs: Optional[List[str]] = None) -> Optional[str]:
        """Find the console .exe: an explicit file, else inside an explicit dir,
        else inside each known default install dir. ``subdirs`` are well-known
        per-family subfolders also searched under each dir (e.g. MuMu's
        ``shell``/``nx_main``)."""
        def find_in(d: str) -> Optional[str]:
            for sub in [""] + list(subdirs or []):
                for name in exes:
                    cand = os.path.join(d, sub, name)
                    if os.path.exists(cand):
                        return cand
            return None

        if path:
            if os.path.isfile(path):
                return path
            if os.path.isdir(path):
                hit = find_in(path)
                if hit:
                    return hit
        for d in dirs:
            hit = find_in(d)
            if hit:
                return hit
        return None

    def _emulator_adb_port(self, p: Dict, kind: str, index: int) -> Optional[int]:
        """The instance's ADB port: an explicit ``port`` override, else what the
        family's console reports for that instance, else derived from the
        family's first-instance port + index*step (mirrors constants.py).

        Asking the console matters because MuMu Global does not always follow
        16384+32*index (instance 2 answers on 16449), so a derived port would
        make the boot-wait time out on a perfectly healthy emulator.
        """
        # The designer serializes a blank num field as 0 — treat <= 0 as "auto".
        override = str(p.get("port", "")).strip()
        if override:
            try:
                val = int(float(override))
                if val > 0:
                    return val
            except ValueError:
                pass
        spec = EMULATOR_CONSOLES.get(kind)
        if not spec:
            return None
        if spec.get("info_args"):
            out = self._run_emulator_console(
                kind, str(self._resolve_value(p.get("path", "")) or "").strip(),
                "info_args", index, timeout=15.0)
            if out:
                m = re.search(r'"adb_port"\s*:\s*(\d+)', out)
                if m:
                    port = int(m.group(1))
                    if port > 0:
                        return port
        if "port0" not in spec:
            return None
        return spec["port0"] + index * spec["step"]

    def _wait_emulator_adb(self, port: Optional[int], wait: float,
                           resolver: Optional[Callable[[], Optional[int]]] = None
                           ) -> Optional[str]:
        """Poll until an instance's ADB is connectable *and* Android reports
        ``sys.boot_completed`` == 1, or ``wait`` s elapse.

        ``resolver`` is re-asked while polling: a family whose console only
        publishes the real ADB port once the instance is up (MuMu Global —
        instance 2 lands on 16449, not the derived 16448) cannot be resolved
        before the boot, so every candidate port found along the way is probed.
        Returns the connected ``host:port`` serial, or None. With no port at all
        it degrades to sleeping ``wait`` s to let the emulator boot.
        """
        hosts: List[str] = [f"127.0.0.1:{port}"] if port else []
        if not hosts and resolver is None:
            log_info(f"[workflow] ▶ Chờ giả lập khởi động {wait:.0f}s (không rõ cổng ADB)")
            self._sleep(wait)
            return None
        end = time.time() + wait
        next_resolve = 0.0
        while time.time() < end and not self._stop.is_set():
            self._pause.wait()
            if resolver is not None and time.time() >= next_resolve:
                next_resolve = time.time() + 5.0
                try:
                    fresh = resolver()
                except Exception:
                    fresh = None
                if fresh:
                    host = f"127.0.0.1:{fresh}"
                    if host not in hosts:
                        hosts.append(host)
            for host in hosts:
                if self._emulator_adb_ready(host):
                    log_success(f"[workflow] ▶ Giả lập sẵn sàng — ADB {host}")
                    return host
            time.sleep(1.0)
        label = ", ".join(hosts) or "?"
        log_warning(f"[workflow] ▶ Chưa thấy ADB {label} sau {wait:.0f}s")
        return None

    # ── Win32 handlers ─────────────────────────────────────────────────────────

    def _win32_ctrl(self):
        """Return the Win32 controller if this is a Win32 flow, else None."""
        if getattr(self, "_controller", "adb") != "win32":
            log_warning("[workflow] Node Win32 chỉ chạy trong dự án Win32 (đổi Controller ở Project settings)")
            return None
        return getattr(self.auto, "adb", None)

    def _a_win_launch(self, node, p) -> bool:
        """Start a program (exe path + optional args) or focus its window; then
        optionally wait until a matching window title appears and attach to it."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        path = str(self._resolve_value(p.get("path", ""))).strip()
        args = str(self._resolve_value(p.get("args", ""))).strip()
        cmd = f'"{path}" {args}'.strip() if args else path
        if not ctrl.launch_app(cmd):
            return False
        window = str(self._resolve_value(p.get("window", ""))).strip()
        wait = float(p.get("wait", 0) or 0)
        # Prefer the explicit title; when it is blank, attach the top-level
        # window created by the process we just launched. This makes an initial
        # Launch program node work without a pre-existing Project target.
        if wait > 0 and (window or getattr(ctrl, "last_launch_pid", None)):
            end = time.time() + wait
            while time.time() < end and not self._stop.is_set():
                self._pause.wait()
                hwnd = (ctrl._find_hwnd(window, "title") if window
                        else ctrl.find_window_by_pid(ctrl.last_launch_pid))
                if hwnd:
                    ctrl.hwnd = hwnd
                    title = ctrl._w[1].GetWindowText(hwnd) or window
                    log_success(f"[workflow] 🪟 Cửa sổ '{title}' đã mở và được gắn")
                    try:
                        self.auto._update_screen_size()
                        if not getattr(self.auto, "capture_running", False):
                            self.auto.start_continuous_capture()
                    except Exception as exc:
                        log_warning(f"[workflow] Win32 capture chưa sẵn sàng: {exc}")
                    return True
                time.sleep(0.5)
            label = window or f"PID {ctrl.last_launch_pid}"
            log_warning(f"[workflow] 🪟 Chưa thấy cửa sổ '{label}' sau {wait:.0f}s")
        return True

    def _a_win_activate(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not ctrl.device:
            ctrl.attach()
        return bool(ctrl.activate())

    def _a_win_close(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.close_window())

    def _a_win_resize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        w = int(p.get("width", 1280))
        h = int(p.get("height", 720))
        ok = bool(ctrl.resize_window(w, h))
        log_info(f"[workflow] 🪟 resize → {w}×{h}")
        return ok

    def _a_win_move(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        x = int(p.get("x", 0))
        y = int(p.get("y", 0))
        ok = bool(ctrl.move_window(x, y))
        log_info(f"[workflow] 🪟 move → ({x}, {y})")
        return ok

    def _a_win_minimize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.minimize_window())

    def _a_win_maximize(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.maximize_window())

    def _a_win_restore(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        return bool(ctrl.restore_window())

    def _a_win_always_on_top(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        on = bool(p.get("enabled", True))
        ok = bool(ctrl.set_always_on_top(on))
        log_info(f"[workflow] 🪟 always on top → {on}")
        return ok

    def _a_win_set_title(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        title = str(p.get("title", "")).strip()
        if not title:
            return True
        ok = bool(ctrl.set_window_title(title))
        log_info(f"[workflow] 🪟 title → '{title}'")
        return ok

    def _a_win_style(self, node, p) -> bool:
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        style = str(p.get("style", "windowed")).strip()
        ok = bool(ctrl.set_window_style(style))
        log_info(f"[workflow] 🪟 style → {style}")
        return ok

    # ── Win32: extended mouse / keyboard ───────────────────────────────────────

    def _a_win_click(self, node, p) -> bool:
        """Left/right/middle click at coords (or the last found image position)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "click"):
            log_warning("[workflow] 🖱 Backend Win32 không hỗ trợ click nhiều nút")
            return False
        x, y = self._pos(p)
        x += int(p.get("offsetX", 0) or 0)
        y += int(p.get("offsetY", 0) or 0)
        button = str(p.get("button", "right")).strip().lower() or "right"
        clicks = 2 if str(p.get("clicks", "1")) == "2" else 1
        ok = bool(ctrl.click(x, y, button=button, click_count=clicks))
        if ok:
            log_info(f"[workflow] 🖱 click {button} ({x}, {y})" + (" ×2" if clicks == 2 else ""))
        return ok

    def _a_win_scroll(self, node, p) -> bool:
        """Mouse wheel at coords. ``direction`` up/down/left/right, ``notches`` count."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "scroll"):
            log_warning("[workflow] 🖱 Backend Win32 không hỗ trợ con lăn")
            return False
        x, y = self._pos(p)
        direction = str(p.get("direction", "down")).strip().lower()
        try:
            notches = max(1, int(p.get("notches", 3) or 3))
        except (TypeError, ValueError):
            notches = 3
        horizontal = direction in ("left", "right")
        signed = notches if direction in ("up", "right") else -notches
        ok = bool(ctrl.scroll(x, y, notches=signed, horizontal=horizontal))
        if ok:
            log_info(f"[workflow] 🖱 cuộn {direction} ×{notches} tại ({x}, {y})")
        return ok

    def _a_win_mouse_move(self, node, p) -> bool:
        """Move the pointer without clicking (hover-activated menus)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "move_mouse"):
            log_warning("[workflow] 🖱 Backend Win32 không hỗ trợ di chuột")
            return False
        x, y = self._pos(p)
        ok = bool(ctrl.move_mouse(x, y))
        if ok:
            log_info(f"[workflow] 🖱 di chuột → ({x}, {y})")
        return ok

    def _a_win_hotkey(self, node, p) -> bool:
        """Press a key with Ctrl/Shift/Alt/Win modifiers (Ctrl+C, Alt+Enter…)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        if not hasattr(ctrl, "press_hotkey"):
            log_warning("[workflow] ⌨ Backend Win32 không hỗ trợ tổ hợp phím")
            return False
        try:
            vk = int(p.get("keycode", 13))
        except (TypeError, ValueError):
            log_warning(f"[workflow] ⌨ win_hotkey: mã phím không hợp lệ ({p.get('keycode')!r})")
            return False
        mods = {k: self._truthy(p.get(k, False)) for k in ("ctrl", "shift", "alt", "win")}
        ok = bool(ctrl.press_hotkey(vk, **mods))
        if ok:
            combo = "+".join([k.capitalize() for k, on in mods.items() if on] + [f"VK{vk}"])
            log_info(f"[workflow] ⌨ {combo}")
        return ok

    def _a_win_info(self, node, p) -> bool:
        """Read a target-window property into a variable (Win32's device_info)."""
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        name = str(p.get("name", "")).strip()
        prop = str(p.get("prop", "width")).strip().lower()
        info = ctrl.window_info() if hasattr(ctrl, "window_info") else {}
        val: Any = info.get(prop, "")
        if isinstance(val, bool):
            val = "true" if val else "false"
        if name:
            self._set_var(name, val)
            log_info(f"[workflow] 🪟 {name} = {self._vars[name]!r} ({prop})")
        return True

    # ── Win32 / ADB conditions added alongside the action handlers ─────────────

    def _c_win_window(self, ntype: str, params: Dict) -> bool:
        """win_if_window / win_wait_window: state of the TARGET window.

        ``state``: ``exists`` (still alive — crash detection) · ``foreground``
        (is the active window) · ``minimized``. ``win_wait_window`` polls until
        the state holds or ``timeout`` runs out.
        """
        ctrl = self._win32_ctrl()
        if ctrl is None:
            return False
        state = str(params.get("state", "exists")).strip().lower()
        negate = self._truthy(params.get("negate", False))

        def probe() -> bool:
            try:
                if state == "foreground":
                    return bool(ctrl.window_exists()) and bool(ctrl.is_foreground())
                if state == "minimized":
                    return bool(ctrl.window_exists()) and bool(ctrl.is_minimized())
                return bool(ctrl.window_exists())
            except Exception as exc:
                log_warning(f"[workflow] 🪟 kiểm tra cửa sổ lỗi: {exc}")
                return False

        if ntype == "win_if_window":
            ok = probe()
            log_info(f"[workflow] 🪟 cửa sổ {state} → {'có' if ok else 'không'}")
            return ok != negate
        end = time.time() + max(0.0, float(params.get("timeout", 30) or 0))
        while not self._stop.is_set():
            self._pause.wait()
            if probe() != negate:
                log_info(f"[workflow] 🪟 cửa sổ {state}{' (đảo)' if negate else ''} — sẵn sàng")
                return True
            if time.time() >= end:
                log_warning(f"[workflow] 🪟 hết thời gian chờ cửa sổ {state}")
                return False
            time.sleep(0.25)
        return False

    def _c_if_screen_on(self, params: Dict) -> bool:
        """ADB: is the device display awake? (the read side of screen_power)."""
        if getattr(self, "_controller", "adb") == "win32":
            log_warning("[workflow] 🖥 'Nếu màn hình đang bật' chỉ áp dụng cho dự án ADB — coi như bật")
            return not self._truthy(params.get("negate", False))
        negate = self._truthy(params.get("negate", False))
        dev = getattr(self.auto.adb, "device", None)
        if not dev:
            return False != negate
        on = False
        try:
            out = dev.shell("dumpsys power") or ""
            m = re.search(r"mWakefulness=(\w+)", out)
            if m:
                on = m.group(1).strip().lower() == "awake"
            else:
                # Older/AOSP builds: fall back to the display-power state line.
                on = "mScreenOn=true" in out or "Display Power: state=ON" in out
        except Exception as exc:
            log_warning(f"[workflow] if_screen_on lỗi: {exc}")
            return False != negate
        log_info(f"[workflow] 🖥 màn hình {'đang bật' if on else 'đang tắt'}")
        return on != negate

    def _c_find_image_pos(self, params: Dict) -> bool:
        """Find a template and store its centre in two variables (x / y).

        True when found (and the variables are written); false on a miss, leaving
        the variables untouched so a previous value isn't silently clobbered.
        """
        tpl = self._resolve_template(params.get("template", ""))
        res = self._find_template(
            tpl, threshold=float(params.get("threshold", 0.85)),
            region=self._search_region(params),
        )
        if not res:
            log_info(f"[workflow] 🔍 không thấy {os.path.basename(tpl) if tpl else '?'} — không ghi biến")
            return False
        x, y = int(res[0]), int(res[1])
        self._last_pos = (x, y)
        nx = str(params.get("nameX", "") or "").strip()
        ny = str(params.get("nameY", "") or "").strip()
        if nx:
            self._set_var(nx, x)
        if ny:
            self._set_var(ny, y)
        log_info(f"[workflow] 🔍 {os.path.basename(tpl) if tpl else '?'} tại ({x}, {y})"
                 + (f" → {nx}/{ny}" if (nx or ny) else ""))
        return True

    def _c_wait_stable(self, params: Dict) -> bool:
        """Wait until the screen stops changing (loading/animation settled).

        Compares consecutive frames (optionally only inside the search region);
        the screen counts as stable once the mean absolute pixel difference stays
        under ``tolerance`` for ``settle`` seconds. True when stable, false on
        timeout — so a flow can branch instead of pushing on into an animation.
        """
        import numpy as np
        settle = max(0.1, float(params.get("settle", 1.0) or 1.0))
        timeout = max(settle, float(params.get("timeout", 15.0) or 15.0))
        tol = max(0.0, float(params.get("tolerance", 2.0) or 0))
        region = self._search_region(params)

        def frame():
            img = self.auto.capture_screen()
            if img is None:
                return None
            if region:
                rx, ry, rw, rh = region
                h, w = img.shape[:2]
                img = img[max(0, ry):min(h, ry + rh), max(0, rx):min(w, rx + rw)]
                if img.size == 0:
                    return None
            return img.astype(np.float32)

        end = time.time() + timeout
        prev = frame()
        stable_since: Optional[float] = None
        while not self._stop.is_set():
            self._pause.wait()
            time.sleep(0.2)
            cur = frame()
            if cur is None or prev is None or cur.shape != prev.shape:
                # No frame yet, or the window resized — restart the settle timer.
                prev = cur
                stable_since = None
            else:
                diff = float(np.mean(np.abs(cur - prev)))
                prev = cur
                if diff <= tol:
                    if stable_since is None:
                        stable_since = time.time()
                    elif time.time() - stable_since >= settle:
                        log_info(f"[workflow] 🧊 màn hình ổn định (Δ={diff:.2f} ≤ {tol:g})")
                        return True
                else:
                    stable_since = None
            if time.time() >= end:
                log_warning(f"[workflow] 🧊 màn hình chưa ổn định sau {timeout:g}s")
                return False
        return False

