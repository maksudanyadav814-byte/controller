; STREAMING_CHUNK:Inno Setup Directives for single app
[Setup]
AppName=Voice to Control
AppVersion=1.0
DefaultDirName={autopf}\Voice to Control
DefaultGroupName=Voice to Control
OutputBaseFilename=Voice_to_Control_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest
SetupIconFile=logo.ico
UninstallDisplayIcon={app}\logo.ico

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Voice to Control.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "logo.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Voice to Control"; Filename: "{app}\Voice to Control.exe"; IconFilename: "{app}\logo.ico"
Name: "{group}\Uninstall Voice to Control"; Filename: "{uninstallexe}"; IconFilename: "{app}\logo.ico"
Name: "{autodesktop}\Voice to Control"; Filename: "{app}\Voice to Control.exe"; IconFilename: "{app}\logo.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VoiceToControl"; ValueData: """{app}\Voice to Control.exe"""; Flags: uninsdeletevalue

[Run]
Filename: "{app}\Voice to Control.exe"; Description: "Launch Voice to Control"; Flags: nowait postinstall skipifsilent