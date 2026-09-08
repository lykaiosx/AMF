; Build: ISCC /DRuntimeDir="absolute path to verified private runtime" AMF.iss
#ifndef RuntimeDir
  #error RuntimeDir must point to the verified Python runtime including site-packages
#endif
#define AppVersion "4.18"
[Setup]
AppId=AMF
AppName=AMF
AppVersion={#AppVersion}
AppPublisher=AMF
DefaultDirName={localappdata}\Programs\AMF
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
MinVersion=10.0.17763
OutputDir=dist
OutputBaseFilename=AMF-4.18-Setup
SetupIconFile=payload\AMF.ico
UninstallDisplayIcon={app}\AMF.ico
Compression=lzma2/normal
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
RestartApplications=no
AppMutex={code:GetAppMutex}
Uninstallable=not IsTestInstall
CreateUninstallRegKey=not IsTestInstall

[Tasks]
Name: desktopicon; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "payload\*.py"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\AMF.ico"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\*.svg"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\AMF.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\logo-*.png"; DestDir: "{app}"; Flags: ignoreversion
Source: "payload\requirements.txt"; DestDir: "{app}"; Flags: ignoreversion
Source: "{#RuntimeDir}\*"; DestDir: "{app}\runtime"; Excludes: "__pycache__\*,*.pyc,*.log,python.zip,*.lib,*.prl,*.obj,*.cpp,*.h"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{userprograms}\AMF"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\start_amf.py"""; WorkingDir: "{app}"; IconFilename: "{app}\AMF.ico"; Check: not IsTestInstall
Name: "{userdesktop}\AMF"; Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\start_amf.py"""; WorkingDir: "{app}"; IconFilename: "{app}\AMF.ico"; Tasks: desktopicon; Check: not IsTestInstall

[Run]
Filename: "{app}\runtime\pythonw.exe"; Parameters: """{app}\start_amf.py"""; WorkingDir: "{app}"; Description: "Open AMF"; Flags: postinstall nowait skipifsilent

[Code]
function IsTestInstall: Boolean;
begin
  Result := ExpandConstant('{param:TESTINSTALL|0}') = '1';
end;

function GetAppMutex(Param: String): String;
begin
  if IsTestInstall then Result := ''
  else Result := 'AMF.Desktop.Running';
end;

procedure CurStepChanged(CurStep: TSetupStep);
var ResultCode: Integer; OldLocation: String;
begin
  if CurStep = ssPostInstall then begin
    WizardForm.StatusLabel.Caption := 'Verifying AMF and its included libraries...';
    if not Exec(ExpandConstant('{app}\runtime\python.exe'),
      ExpandConstant('"{app}\verify_install.py" {#AppVersion} --log "{app}\install-check.log"'),
      ExpandConstant('{app}'), SW_HIDE, ewWaitUntilTerminated, ResultCode) then
      RaiseException('Could not run the included AMF runtime.');
    if ResultCode <> 0 then
      RaiseException(ExpandConstant('AMF verification failed. Full details: {app}\install-check.log'));
    if not IsTestInstall then
      if RegQueryStringValue(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AMF', 'InstallLocation', OldLocation) then
        if CompareText(OldLocation, ExpandConstant('{app}')) = 0 then
          RegDeleteKeyIncludingSubkeys(HKCU, 'Software\Microsoft\Windows\CurrentVersion\Uninstall\AMF');
  end;
end;

