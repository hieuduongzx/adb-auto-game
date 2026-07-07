@echo off
rem Chạy Workflow Designer KHÔNG cần quyền Administrator.
rem Dùng khi không cần điều khiển cửa sổ game chạy quyền Admin.
cd /d "%~dp0"
python tools\workflow_designer.py
