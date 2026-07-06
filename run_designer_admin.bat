@echo off
rem Chạy Workflow Designer với quyền Administrator.
rem Cần khi điều khiển cửa sổ game chạy quyền Admin (NIKKE...) — UIPI chặn
rem input từ process quyền thấp. Double-click file này, bấm Yes ở hộp UAC.
cd /d "%~dp0"
net session >nul 2>&1
if %errorlevel%==0 (
    rem Đã có quyền admin (mở từ terminal admin) — chạy thẳng.
    python tools\workflow_designer.py
) else (
    rem Chưa có quyền — bật UAC rồi chạy lại chính lệnh này với quyền admin.
    powershell -NoProfile -Command "Start-Process -FilePath 'python' -ArgumentList 'tools\workflow_designer.py' -WorkingDirectory '%~dp0' -Verb RunAs"
)
