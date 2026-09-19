@echo off
rem Chạy Workflow Designer KHÔNG cần quyền Administrator.
rem Dùng khi không cần điều khiển cửa sổ game chạy quyền Admin.
cd /d "%~dp0"
set "MACRO2K_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%MACRO2K_PY%" set "MACRO2K_PY=python"
"%MACRO2K_PY%" apps\workflow_designer.py
