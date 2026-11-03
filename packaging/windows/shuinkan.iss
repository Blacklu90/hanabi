; Inno Setup script: builds dist\Shuinkan-Setup-<version>.exe from dist\Shuinkan (PyInstaller output).
; Per-user install (no admin rights needed). Your progress lives in %LOCALAPPDATA%\Shuinkan and is kept on uninstall.
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppId={{6B1F3C2A-8E4D-4F1B-9C7A-2D5E8F0A1B3C}
AppName=Shuinkan
AppVersion={#Version}
AppVerName=Shuinkan {#Version}
AppPublisher=Blacklu90
AppPublisherURL=https://github.com/Blacklu90/hanabi
AppSupportURL=https://github.com/Blacklu90/hanabi/issues
DefaultDirName={localappdata}\Programs\Shuinkan
DefaultGroupName=Shuinkan
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Shuinkan-Setup-{#Version}
SetupIconFile=shuinkan.ico
UninstallDisplayIcon={app}\Shuinkan.exe
UninstallDisplayName=Shuinkan
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=yes
LicenseFile=..\..\LICENSE

[Tasks]
Name: "desktopicon"; Description: "Create a &desktop shortcut"; GroupDescription: "Shortcuts:"

[Files]
Source: "..\..\dist\Shuinkan\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Shuinkan"; Filename: "{app}\Shuinkan.exe"; Comment: "Learn Japanese in short, focused bursts"
Name: "{autodesktop}\Shuinkan"; Filename: "{app}\Shuinkan.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Shuinkan.exe"; Description: "Start Shuinkan now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Shuinkan.exe"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopShuinkan"
