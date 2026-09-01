# Đóng gói app ra .exe

Build **Macro2k** (Hub mặc định + Designer qua `--designer` + Runner qua
`--runner`) vào một thư mục kèm **`vendor/`** (adb / frida / tesseract):

```
dist/Macro2k/
    Macro2k.exe      Hub (mặc định); --designer / --runner
    _macro2k/        file runtime riêng
    vendor/             adb / frida / tesseract
```

Exe resolve thư mục ghi được (`vendor/`, `data/`, `out/`) về folder chứa exe.

> **DevScope** không còn được đóng gói trong build này. Chạy DevScope từ source:
> `python apps/devscope.py`.

## Build

Từ thư mục gốc project, dùng đúng interpreter Python đang chạy được app từ source:

```powershell
pwsh packaging/build.ps1
```

Script sẽ: cài `pyinstaller` nếu thiếu → chạy `packaging/apps_build.spec` → copy `vendor/`
vào cạnh `.exe`.

Rebuild nhanh khi chỉ sửa code (bỏ qua copy vendor):

```powershell
pwsh packaging/build.ps1 -SkipVendor
```

## Icon

`packaging/app.ico` là icon dùng cho `Macro2k.exe`, Runner exe build riêng, và
`Setup.exe`. `build.ps1` tự tạo lại khi file thiếu hoặc cũ hơn generator, nên
build bình thường không cần làm gì thêm.

Tạo lại thủ công sau khi sửa artwork (chỉ cần Pillow):

```powershell
python packaging/make_icon.py     # -> packaging/app.ico + app.png
```

`make_icon.py` vẽ đúng brand mark của Hub (ba ô vuông + dấu cộng accent) trên nền
tile tối, render riêng từng size 16 → 256 để frame nhỏ vẫn rõ.

## Cách hoạt động (frozen-aware)

- **Tài nguyên ghi được** (`vendor/`, `data/`, `out/`) nằm **cạnh `.exe`** —
  `src.utils.app_dir()` trả về thư mục chứa exe khi frozen, hoặc project root khi chạy source.
- **Asset chỉ-đọc** (HTML `web/hub`, `web/wf`, `web/runner`) được nhúng trong
  bundle — `src.utils.bundle_dir()` → `_MEIPASS`.
- **Cùng một exe, ba mode:**
  - `Macro2k.exe` → Hub (dashboard)
  - `Macro2k.exe --designer [flow.json]` → Designer
  - `Macro2k.exe --runner [flow.json]` → Runner
  (source: `python apps/workflow_hub.py` / `workflow_designer.py` / `workflow_runner.py`).

## Lưu ý

- Chỉ bundle backend OCR **Tesseract**; `easyocr/paddle/torch` bị loại khỏi build cho nhẹ.
- `vendor/` nằm trong `dist/Macro2k/vendor` — có thể tự xoá bớt tool không dùng nếu cần.
- Đổi `console=False` → `True` trong `apps_build.spec` nếu cần xem traceback khi debug.
- Để phân phối: nén/copy cả thư mục `dist/Macro2k/` (giữ nguyên cấu trúc bên trong).
