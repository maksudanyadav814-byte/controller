; Inno Setup Script for Voice to Control
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

[Tasks]
Name: "desktopicon"; Description: "{cm:CreateDesktopIcon}"; GroupDescription: "{cm:AdditionalIcons}"; Flags: unchecked

[Files]
Source: "dist\Voice to Control.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Voice to Control Dashboard"; Filename: "{app}\dashboard.exe"
Name: "{group}\Voice to Control"; Filename: "{app}\Voice to Control.exe"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Voice to Control"; Filename: "{app}\Voice to Control.exe"; Tasks: desktopicon

[Registry]
; Auto-start on Windows boot / restart for current user
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "VoiceToControl"; ValueData: """{app}\Voice to Control.exe"""; Flags: uninsdeletevalue

[Run]
; Launch controller immediately after installation finishes
Filename: "{app}\Voice to Control.exe"; Description: "Launch Voice to Control"; Flags: nowait postinstall skipifsilent

[Code]
var
NamePage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
{ Custom step during install to ask user name }
NamePage := CreateInputQueryPage(wpWelcome,
'User Profile Configuration',
'Please enter the Owner/User name:',
'This name will be spoken by Voice to Control during startup welcome message.');
NamePage.Add('Owner Name:', False);
NamePage.Values[0] := 'User';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var
ConfigPath: String;
UserName: String;
JsonContent: String;
begin
if CurStep = ssPostInstall then
begin
UserName := Trim(NamePage.Values[0]);
if UserName = '' then
UserName := 'User';
ConfigPath := ExpandConstant('{app}\user_config.json');
JsonContent := '{"name": "' + UserName + '"}';
SaveStringToFile(ConfigPath, JsonContent, False);
end;
end;