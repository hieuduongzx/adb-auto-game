@echo off
rem Builds Macro2kBridge.Il2Cpp.dll (x64) with MSVC and copies it to vendor\unity_bridge\plugin_il2cpp.
setlocal
set "VCVARS="
for %%E in (Community Professional Enterprise BuildTools) do (
  for /d %%V in ("%ProgramFiles%\Microsoft Visual Studio\*") do (
    if exist "%%V\%%E\VC\Auxiliary\Build\vcvars64.bat" if not defined VCVARS set "VCVARS=%%V\%%E\VC\Auxiliary\Build\vcvars64.bat"
  )
)
if not defined VCVARS (
  echo Visual Studio with the C++ x64 tools was not found.
  exit /b 1
)
call "%VCVARS%" >nul || exit /b 1
set "OUT=%~dp0..\..\plugin_il2cpp"
if not exist "%OUT%" mkdir "%OUT%"
cl /nologo /LD /O2 /MT /EHsc /W3 /D_CRT_SECURE_NO_WARNINGS "%~dp0bridge.cpp" /Fo"%TEMP%\\" /Fe"%OUT%\Macro2kBridge.Il2Cpp.dll" /link /INCREMENTAL:NO ws2_32.lib user32.lib
exit /b %errorlevel%
