; Inno Setup script for Macro2k.
;
; Compiled by packaging/build.ps1 -Installer, which passes the version + paths:
;   ISCC /DMyAppVersion=1.0.0 /DMySourceDir=..\dist\Macro2k /DMyOutputDir=..\dist\installer installer.iss
; Defaults below let it also be opened directly in the Inno Setup IDE.
;
; Produces dist\installer\Macro2k-Setup-<ver>.exe — a normal wizard with a
; "Browse…" folder picker (per-user or, elevated, all-users / Program Files).
; Auto-update (src/updater.py) downloads this Setup.exe for the new version and
; re-runs it silently into the same folder.
;
; Writable user data lives next to the app when the install folder is writable
; (per-user / custom dir), else under %LOCALAPPDATA%\Macro2k for a read-only
; Program Files install — see src/utils.data_root().

#ifndef MyAppVersion
  #define MyAppVersion "1.0.0"
#endif
#ifndef MySourceDir
  #define MySourceDir "..\dist\Macro2k"
#endif
#ifndef MyOutputDir
  #define MyOutputDir "..\dist\installer"
#endif
#define MyAppName "Macro2k"
#define MyAppExe "Macro2k.exe"
#define MyAppPublisher "hieuduongzx"
#define MyAppUrl "https://github.com/hieuduongzx/adb-auto-game"

[Setup]
; A stable AppId ties upgrades + uninstall together across versions — never change it.
AppId={{8F4B2C1A-2E7D-4F3A-9B6C-1D5E8A0F7C42}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
AppPublisherURL={#MyAppUrl}
AppSupportURL={#MyAppUrl}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExe}
; Let the user choose per-user or (elevated) all-users at install time, and
; keep the Browse folder page so they can pick any directory.
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog commandline
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; Silent auto-updates must be able to close the running app to replace files.
CloseApplications=yes
RestartApplications=no
WizardStyle=modern
Compression=lzma2/max
SolidCompression=yes
OutputDir={#MyOutputDir}
OutputBaseFilename={#MyAppName}-Setup-{#MyAppVersion}
#if FileExists(AddBackslash(SourcePath) + "app.ico")
SetupIconFile=app.ico
#endif

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "{#MySourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"
Name: "{group}\{cm:UninstallProgram,{#MyAppName}}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExe}"; Tasks: desktopicon

[Run]
; Launch after an interactive install (skipped during silent auto-updates —
; the updater's wrapper relaunches the app itself in that case).
Filename: "{app}\{#MyAppExe}"; Description: "{cm:LaunchProgram,{#MyAppName}}"; Flags: nowait postinstall skipifsilent
