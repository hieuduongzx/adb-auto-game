"""Node catalog shared by the engine, Designer checks and the Runner."""
from __future__ import annotations

from typing import Any, Dict


# ── Node catalog ─────────────────────────────────────────────────────────────
#
# Single source of truth for the node types the engine understands. ``kind``
# drives traversal; ``outs`` lists the output port ids each node exposes. The
# Designer keeps a richer mirror (icons + field widgets) keyed by the same
# names in apps/web/wf/js/workflow.js; labels and kinds must agree with it
# (tests/test_catalog_parity.py). Safety cap on total steps guards against
# runaway cycles.
MAX_STEPS = 100_000
MAX_CALL_DEPTH = 50  # guards against functions that (in)directly call themselves

NODE_TYPES: Dict[str, Dict[str, Any]] = {
    "start":      {"label": "Start",       "kind": "start",     "ins": 0, "outs": ["out"]},
    "end":        {"label": "End",      "kind": "end",       "ins": 1, "outs": []},
    "stop":       {"label": "Stop workflow",   "kind": "stop",      "ins": 1, "outs": []},
    # A call returns a boolean: "true" when the function's walk reached an End
    # node, "false" when it dead-ended (e.g. a node inside timed out).
    "call":       {"label": "Call function",  "kind": "call",      "ins": 1, "outs": ["true", "false"]},
    "note":       {"label": "Note",       "kind": "note",      "ins": 0, "outs": []},
    "tap":        {"label": "Tap",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "multi_tap":  {"label": "Multi-point tap", "kind": "action",    "ins": 1, "outs": ["out"]},
    "sequence_tap": {"label": "Sequence tap", "kind": "action", "ins": 1, "outs": ["out"]},
    "sequence_tap_image": {"label": "Sequence tap image", "kind": "action", "ins": 1, "outs": ["out"]},
    "stop_sequence": {"label": "Stop sequence", "kind": "action", "ins": 1, "outs": ["out"]},
    "double_tap": {"label": "Double tap",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_random": {"label": "Random tap","kind": "action",   "ins": 1, "outs": ["out"]},
    "long_press": {"label": "Long press",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe":      {"label": "Swipe",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "swipe_dir":  {"label": "Swipe direction",    "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait":       {"label": "Wait",           "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait_random":{"label": "Random wait","kind": "action",    "ins": 1, "outs": ["out"]},
    "tap_image":  {"label": "Tap image",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_image": {"label": "Wait image",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # "…_any" variants take a *list* of templates and match ANY one of them — the
    # node-graph way to express "see image A or B" (an OR over several images).
    "tap_image_any":  {"label": "Tap any image", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_image_any": {"label": "Wait any image",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "tap_text":   {"label": "Tap text",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_text":  {"label": "Wait text",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # ── Color (pixel) nodes — match a pixel/region against a #RRGGBB colour
    # with a per-channel tolerance (same semantics as DevScope's Inspect color:
    # match when max(ΔR,ΔG,ΔB) <= tolerance).
    "tap_color":  {"label": "Tap color",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "wait_color": {"label": "Wait color",       "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_color":   {"label": "If color",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "read_color": {"label": "Read color to variable","kind": "action",    "ins": 1, "outs": ["out"]},
    "send_text":  {"label": "Type text",  "kind": "action",    "ins": 1, "outs": ["out"]},
    "key":        {"label": "Press key",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "back":       {"label": "Back",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "home":       {"label": "Home",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "launch_app": {"label": "Launch app",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "screenshot": {"label": "Screenshot", "kind": "action",    "ins": 1, "outs": ["out"]},
    "log":        {"label": "Log",   "kind": "action",    "ins": 1, "outs": ["out"]},
    "set_var":    {"label": "Set variable",      "kind": "action",    "ins": 1, "outs": ["out"]},
    "calc_var":   {"label": "Calculate variable",     "kind": "action",    "ins": 1, "outs": ["out"]},
    "read_var":   {"label": "Read text to variable","kind": "action", "ins": 1, "outs": ["out"]},
    "parse_var":  {"label": "Parse text to variable","kind": "action", "ins": 1, "outs": ["out"]},
    "break":      {"label": "Break loop","kind": "action",    "ins": 1, "outs": ["out"]},
    "if_image":   {"label": "If image",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_image_any":{"label": "If any image","kind": "condition","ins": 1, "outs": ["true", "false"]},
    "if_text":    {"label": "If text",  "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_var":     {"label": "If variable",      "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "loop":       {"label": "Loop",       "kind": "loop",      "ins": 1, "outs": ["body", "done"]},
    "parallel":   {"label": "Parallel","kind": "parallel",  "ins": 1, "outs": []},
    # Sequential fan-out: run branches 1..N one after another. Unlike try_chain a
    # branch is NOT skipped when an earlier one fails or succeeds — every wired
    # branch ALWAYS runs. No shared output port: each branch is its own path.
    "sequence":   {"label": "Sequence","kind": "sequence",  "ins": 1, "outs": []},
    # Sequential fallback: run branch 1; if that branch fails (a block returns
    # false), stop that branch and try branch 2, then 3... If every wired branch
    # fails, continue from the "fail" port.
    "try_chain":  {"label": "Try in order",  "kind": "try_chain", "ins": 1, "outs": []},
    # Explicit "give up this try_chain branch, try the next one" — like break for
    # loops. Wire it inside a try_chain arm when you want to abandon the branch
    # without an actual action failure (e.g. after an if_image true path).
    "try_next":   {"label": "Next branch",  "kind": "try_next",  "ins": 1, "outs": []},
    # Output ports are dynamic (count param) so outs is left empty here; the
    # engine reads params["count"] at runtime and the designer renders them live.
    "join":       {"label": "Join",           "kind": "join",      "ins": 1, "outs": ["out"]},
    "and":        {"label": "And",            "kind": "and",       "ins": 1, "outs": ["out"]},
    # Multi-way branch: each case is its own condition; the first true case routes
    # to its port "c{i}", else "default". Output ports are dynamic (per the node's
    # ``cases`` list) so ``outs`` here is only the static fallback hint.
    "switch":      {"label": "Switch",       "kind": "switch",    "ins": 1, "outs": ["default"]},
    "scroll_find": {"label": "Scroll until image",    "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Lặp thân ("body" quay về cổng "loop") đến khi template xuất hiện → "found".
    # maxLoops > 0 giới hạn số vòng; hết lượt mà chưa thấy → "fail". Gói gọn
    # pattern phổ biến nhất trong workflow thực tế: loop ∞ + if_image + break.
    "loop_until_image": {"label": "Loop until image", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    # Cùng cơ chế loop_until nhưng điều kiện thoát là màu / chữ / biến — bộ ba
    # còn thiếu so với bản ảnh (trước đây phải dựng loop ∞ + if_* + break).
    "loop_until_color": {"label": "Loop until color", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    "loop_until_text":  {"label": "Loop until text", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    "loop_until_var":   {"label": "Loop until variable", "kind": "loop_until", "ins": 2, "outs": ["body", "found", "fail"]},
    # Tìm ảnh và LƯU toạ độ tâm vào 2 biến (x/y) — để tính toán offset, so sánh
    # vị trí… thay vì chỉ dùng được qua "chạm ảnh vừa thấy".
    "find_image_pos": {"label": "Find image position", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chờ màn hình NGỪNG thay đổi (hết animation/loading) rồi mới đi tiếp.
    "wait_stable": {"label": "Wait until still", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chạm MỌI vị trí khớp template trên màn hình hiện tại (match_all + NMS).
    # true khi chạm được ≥1 vị trí — quét thu thập vật phẩm/phần thưởng.
    "tap_all_images": {"label": "Tap all images", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Quản lý app: dừng hẳn (am force-stop, tuỳ chọn pm clear) — cặp với
    # launch_app để làm flow "game treo → restart".
    "app_stop": {"label": "Stop app", "kind": "action", "ins": 1, "outs": ["out"]},
    # Điều kiện: app/tiêu đề cửa sổ hiện tại có chứa chuỗi? (ADB: package
    # foreground; Win32: tiêu đề cửa sổ) — phát hiện game crash.
    "if_app": {"label": "If app is running", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chờ app/cửa sổ xuất hiện (hoặc BIẾN MẤT khi negate) — cặp chờ của if_app,
    # dùng cho cả hai backend. true khi đạt điều kiện, false khi hết timeout.
    "wait_app": {"label": "Wait until app", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Gỡ cài đặt app (pm uninstall, tuỳ chọn -k giữ dữ liệu). ADB-only.
    "app_uninstall": {"label": "Uninstall app", "kind": "action", "ins": 1, "outs": ["out"]},
    # Cài APK từ file trên PC (pm install qua adb install) — cặp đối xứng với
    # app_uninstall. ADB-only.
    "app_install": {"label": "Install app", "kind": "action", "ins": 1, "outs": ["out"]},

    # Thoát app ĐANG mở (không cần package): ADB force-stop app foreground;
    # Win32 đóng cửa sổ mục tiêu.
    "app_exit": {"label": "Exit app", "kind": "action", "ins": 1, "outs": ["out"]},
    "random_branch":{"label":"Random branch","kind": "random",    "ins": 1, "outs": []},
    "format_var":  {"label": "Format text to variable","kind": "action",    "ins": 1, "outs": ["out"]},
    "notify":      {"label": "Notify",       "kind": "action",    "ins": 1, "outs": ["out"]},
    # ── Device / time ────────────────────────────────────────────────────────
    # Read the wall clock, wait until a clock time, gate on a time window, and
    # read live device properties (battery, current app, resolution…) into a var.
    "get_time":    {"label": "Read time to variable",  "kind": "action",    "ins": 1, "outs": ["out"]},
    "wait_until":  {"label": "Wait until time",          "kind": "action",    "ins": 1, "outs": ["out"]},
    "if_time":     {"label": "If time is between","kind": "condition","ins": 1, "outs": ["true", "false"]},
    "device_info": {"label": "Read device to variable","kind": "action","ins": 1, "outs": ["out"]},
    "screen_power":{"label": "Screen power", "kind": "action",    "ins": 1, "outs": ["out"]},
    # Màn hình thiết bị đang bật? (cặp đọc cho screen_power). ADB-only.
    "if_screen_on":{"label": "If screen on", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "if_device_size":{"label": "If screen size", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Chạy một câu adb shell tuỳ ý, lưu stdout vào biến — cửa thoát cho những
    # thứ chưa có node riêng. ADB-only.
    "adb_shell":   {"label": "Run shell to variable", "kind": "action", "ins": 1, "outs": ["out"]},

    # Launch the *emulator process itself* (LDPlayer/MuMu/Nox/MEmu/BlueStacks) on
    # the PC — unlike ``launch_app`` which opens an app *inside* an already-running
    # device. Optional ``at`` (HH:MM) waits until that clock time first, so a flow
    # can, on its own, sit idle until 07:00 then boot the emulator (no Task
    # Scheduler / PC-wake needed — the PC is already on running this tool).
    "launch_emulator": {"label": "Launch emulator", "kind": "action", "ins": 1, "outs": ["out"]},
    # Is an emulator instance booted & its ADB responding? "last" (default)
    # re-checks the instance saved by the last successful launch_emulator, so a
    # flow can skip the boot when "the one I set" is already up.
    "if_emulator": {"label": "If emulator is ready", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Poll until the emulator finishes Android boot (adb connect +
    # sys.boot_completed == 1) or until timeout — true when ready, false on
    # timeout/unresolvable target.
    "wait_emulator": {"label": "Wait until emulator ready", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Resize the emulator's own PC window (the player UI), not the game inside
    # it. width/height describe the CLIENT area (the Android screen) — the
    # title bar is compensated for, otherwise the emulator letterboxes the
    # device with black side bars. Pure Win32 on the player process' window —
    # no ADB, no controller, so it works in ADB flows too (e.g. snap MuMu's
    # screen to 1920×1080 right after Launch emulator). "last" reuses the
    # instance the last successful launch_emulator saved.
    "resize_emulator": {"label": "Resize emulator", "kind": "action", "ins": 1, "outs": ["out"]},
    # Kill the emulator instance: the family's console shutdown when it exists
    # (LDPlayer/MuMu/Nox/MEmu; BlueStacks has none), else taskkill the player
    # window. "last" reuses the instance the last successful launch_emulator
    # saved.
    "kill_emulator": {"label": "Kill emulator", "kind": "action", "ins": 1, "outs": ["out"]},
    # Reboot a wedged instance (frozen UI / ADB gone) — console reboot when the
    # family has one, else kill the player + relaunch. Optional wait polls
    # sys.boot_completed so the next node can drive the fresh boot.
    "restart_emulator": {"label": "Restart emulator", "kind": "action", "ins": 1, "outs": ["out"]},
    # Set the *device* resolution (Android screen px + DPI) — the value the
    # templates were cropped against. resize_emulator only changes the PC
    # window, so a 1920×1080 window over a 1600×900 device still letterboxes.
    # MuMu-only (its console exposes the resolution_* setting keys).
    "emulator_resolution": {"label": "Set emulator resolution", "kind": "action", "ins": 1, "outs": ["out"]},
    # ── Win32 (điều khiển cửa sổ chương trình PC) ─────────────────────────────
    # Only meaningful when the flow's controller is "win32". Tap/swipe/image/
    # color/OCR nodes already work on Win32 via the shared capture pipeline;
    # these cover the window-lifecycle actions ADB nodes can't express.
    "win_send_text":{"label": "Type text", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_key":      {"label": "Press key", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_hotkey":   {"label": "Hotkey (combo)", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_escape":   {"label": "Escape key", "kind": "action", "ins": 1, "outs": ["out"]},
    # Chuột phải / giữa + con lăn + di chuột (hover) — những thứ WM_LBUTTON*
    # không diễn tả được nhưng app/game PC dùng liên tục.
    "win_click":    {"label": "Mouse click", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_scroll":   {"label": "Mouse wheel", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_mouse_move": {"label": "Move mouse (hover)", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_launch":   {"label": "Launch program", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_activate": {"label": "Activate window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_close":    {"label": "Close window", "kind": "action", "ins": 1, "outs": ["out"]},
    # Tắt CỨNG tiến trình sở hữu cửa sổ mục tiêu (taskkill /F) — win_close chỉ gửi
    # WM_CLOSE nên game treo / hiện hộp thoại "Lưu?" thì không đóng được.
    "win_kill":     {"label": "Kill process", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_resize":   {"label": "Resize window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_move":     {"label": "Move window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_minimize": {"label": "Minimize window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_maximize": {"label": "Maximize window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_restore":  {"label": "Restore window", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_always_on_top": {"label": "Always on top", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_set_title": {"label": "Set window title", "kind": "action", "ins": 1, "outs": ["out"]},
    "win_style":    {"label": "Set window style", "kind": "action", "ins": 1, "outs": ["out"]},
    # Điều kiện Win32 (trước đây mode Win32 KHÔNG có condition nào): cửa sổ mục
    # tiêu còn sống / đang foreground / đang thu nhỏ, và bản chờ có timeout.
    "win_if_window":  {"label": "If window", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    "win_wait_window":{"label": "Wait until window", "kind": "condition", "ins": 1, "outs": ["true", "false"]},
    # Đọc thuộc tính cửa sổ mục tiêu vào biến (đối xứng với device_info của ADB).
    "win_info":     {"label": "Read window to variable", "kind": "action", "ins": 1, "outs": ["out"]},
}


# Condition node types a switch case may use — only the *instant* ones (no
# wait_* timeout blocking, no tap_* side-effect), so evaluating one case never
# stalls the others. Kept in sync with the designer's case-type dropdown.
SWITCH_CASE_TYPES = ("if_image", "if_image_any", "if_text", "if_var", "if_time",
                     "if_color", "if_app", "if_screen_on", "if_device_size",
                     "win_if_window")
