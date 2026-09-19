@echo off
rem Macro2k Hub — dashboard: list / run / edit / create workflows.
cd /d "%~dp0"
set "MACRO2K_PY=%~dp0.venv\Scripts\python.exe"
if not exist "%MACRO2K_PY%" set "MACRO2K_PY=python"
"%MACRO2K_PY%" apps\workflow_hub.py
