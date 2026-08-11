; Inno Setup script for Found It.
; Compile with: ISCC.exe FoundItSetup.iss
; Produces dist311-onefile\..\installer\FoundIt-Setup.exe

#define MyAppName "Found It"
#define MyAppVersion "1.0.0"
#define MyAppPublisher "Found It"
#define MyAppExeName "FoundIt.exe"

[Setup]
AppId={{8F2E1C5A-6B3D-4E7A-9C1F-2D4B8A0E5F31}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
; Per-user install: no admin rights required, and guarantees the app can
; write its data folder (db/snapshots/faces) next to the exe at runtime.
DefaultDirName={localappdata}\Programs\FoundIt
PrivilegesRequired=lowest
DisableProgramGroupPage=yes
OutputDir=installer
OutputBaseFilename=FoundIt-Setup
Compression=lzma2/fast
SolidCompression=yes
WizardStyle=modern
ArchitecturesInstallIn64BitMode=x64compatible
UninstallDisplayIcon={app}\{#MyAppExeName}

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Additional shortcuts:"

[Files]
Source: "dist311-onefile\FoundIt.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "yolov8n.pt"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{autoprograms}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Launch {#MyAppName}"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; Remove app-generated data (db/snapshots/faces/settings) on uninstall.
Type: filesandordirs; Name: "{app}\data"
