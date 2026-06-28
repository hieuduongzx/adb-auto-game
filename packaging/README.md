# Đóng gói tool ra .exe

Build hai tool (PyWebView, backend EdgeChromium) vào **chung một thư mục** với
**`vendor/` dùng chung** (chỉ một bản, không nhân đôi):

```
dist/Workflow2k/
    Workflow2k.exe      Workflow Designer (kiêm Runner qua --runner)
    DevScope.exe        Tool inspect màn hình / thiết bị
    _workflow2k/        file runtime riêng của Workflow2k
    _devscope/          file runtime riêng của DevScope
    vendor/             adb / frida / tesseract dùng chung
```

Hai exe có thư mục nội bộ tên khác nhau (`_workflow2k` / `_devscope`) nên gộp chung
một folder không đụng nhau; cả hai đều resolve thư mục ghi được (`vendor/`,
`data/`, `out/`) về chính folder chứa exe → một `vendor/` phục vụ cả hai.

## Build

Từ thư mục gốc project, dùng đúng interpreter Python đang chạy được app từ source:

```powershell
pwsh packaging/build.ps1
```

Script sẽ: cài `pyinstaller` nếu thiếu → chạy `packaging/tools_build.spec` → copy `vendor/`
(adb, frida, tesseract) vào cạnh từng `.exe`.

Rebuild nhanh khi chỉ sửa code (bỏ qua copy vendor):

```powershell
pwsh packaging/build.ps1 -SkipVendor
```

## Cách hoạt động (frozen-aware)

- **Tài nguyên ghi được** (`vendor/`, `data/`, `out/`) nằm **cạnh `.exe`** —
  `src.utils.app_dir()` trả về thư mục chứa exe khi frozen, hoặc project root khi chạy source.
- **Asset chỉ-đọc** (HTML `web/`) được nhúng trong bundle — `src.utils.bundle_dir()` → `_MEIPASS`.
- **Gọi chéo tool** dùng `src.utils.launch_tool()`: khi frozen chạy `*.exe` cạnh bên
  (Runner = `designer.exe --runner <flow>`); khi source chạy `python tools/<script>.py`.

## Lưu ý

- Chỉ bundle backend OCR **Tesseract**; `easyocr/paddle/torch` bị loại khỏi build cho nhẹ.
- `vendor/` chỉ có **một bản dùng chung** trong `dist/Workflow2k/vendor` (DevScope không
  dùng frida ~107MB, designer không dùng tesseract ~101MB — có thể tự xoá bớt nếu cần).
- Đổi `console=False` → `True` trong `tools_build.spec` nếu cần xem traceback khi debug.
- Để phân phối: nén/copy cả thư mục `dist/Workflow2k/` (giữ nguyên cấu trúc bên trong).
