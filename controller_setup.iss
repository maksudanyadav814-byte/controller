; Inno Setup Script for Hackworld Controller
[Setup]
AppName=Hackworld Controller
AppVersion=1.0
DefaultDirName={autopf}\HackworldController
DefaultGroupName=Hackworld Controller
OutputBaseFilename=HackworldController_Setup
Compression=lzma2
SolidCompression=yes
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Files]
Source: "dist\controller.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "dist\dashboard.exe"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\Hackworld Dashboard"; Filename: "{app}\dashboard.exe"
Name: "{group}\Hackworld Controller"; Filename: "{app}\controller.exe"
Name: "{group}\Uninstall"; Filename: "{uninstallexe}"

[Registry]
; Auto-start on Windows boot / restart for current user
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "HackworldController"; ValueData: """{app}\controller.exe"""; Flags: uninsdeletevalue

[Run]
; Launch controller immediately after installation finishes
Filename: "{app}\controller.exe"; Description: "Launch Hackworld Controller"; Flags: nowait postinstall skipifsilent

[Code]
var
NamePage: TInputQueryWizardPage;

procedure InitializeWizard;
begin
{ Custom step during install to ask user name }
NamePage := CreateInputQueryPage(wpWelcome,
'User Profile Configuration',
'Please enter the Owner/User name:',
'This name will be spoken by Hackworld Controller during startup welcome message.');
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