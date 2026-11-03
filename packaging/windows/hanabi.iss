; Inno Setup script: builds dist\Hanabi-Setup-<version>.exe from dist\Hanabi (PyInstaller output).
; Per-user install (no admin rights needed). Your progress lives in %LOCALAPPDATA%\Hanabi and is kept on uninstall.
#ifndef Version
  #define Version "1.0.0"
#endif

[Setup]
AppId={{6B1F3C2A-8E4D-4F1B-9C7A-2D5E8F0A1B3C}
AppName=Hanabi
AppVersion={#Version}
AppVerName=Hanabi {#Version}
AppPublisher=Blacklu90
AppPublisherURL=https://github.com/Blacklu90/hanabi
AppSupportURL=https://github.com/Blacklu90/hanabi/issues
DefaultDirName={localappdata}\Programs\Hanabi
DefaultGroupName=Hanabi
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\..\dist
OutputBaseFilename=Hanabi-Setup-{#Version}
SetupIconFile=hanabi.ico
UninstallDisplayIcon={app}\Hanabi.exe
UninstallDisplayName=Hanabi
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
Source: "..\..\dist\Hanabi\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{autoprograms}\Hanabi"; Filename: "{app}\Hanabi.exe"; Comment: "Learn Japanese in short, focused bursts"
Name: "{autodesktop}\Hanabi"; Filename: "{app}\Hanabi.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Hanabi.exe"; Description: "Start Hanabi now"; Flags: nowait postinstall skipifsilent

[UninstallRun]
Filename: "{app}\Hanabi.exe"; Parameters: "--stop"; Flags: runhidden; RunOnceId: "StopHanabi"
