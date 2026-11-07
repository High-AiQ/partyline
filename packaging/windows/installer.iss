; Inno Setup script: a per-user installer for the frozen helper (no administrator rights, no UAC prompt).
; Build: iscc /DAppVersion=2.89.0 packaging\windows\installer.iss   (after PyInstaller made dist\PartylineHelper)
; Output: build\installer\PartylineHelper-Setup.exe  (a fixed name, so releases/latest/download/... is stable)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#define AppName "Partyline Helper"
#define AppExe "PartylineHelper.exe"

[Setup]
AppId={{B6F1D2A4-5C1E-4E0B-9C57-3A7E2D0F4A61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Partyline
DefaultDirName={localappdata}\Programs\Partyline Helper
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\installer
OutputBaseFilename=PartylineHelper-Setup
SetupIconFile=..\..\build\PartylineHelper.ico
UninstallDisplayIcon={app}\{#AppExe}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
; We stop the helper ourselves (instance lock + pid), not through the Restart Manager.
CloseApplications=no
RestartApplications=no
; Signing: when the SIGN define is passed (iscc /DSIGN=1 "/Ssigntool=<command> $f"), installer and uninstaller
; are signed. The unsigned prototype leaves it out. See docs/screen-helper.md and the workflow's sign steps.
#ifdef SIGN
SignTool=signtool
SignedUninstaller=yes
#endif

[Files]
Source: "..\..\dist\PartylineHelper\*"; DestDir: "{app}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{app}\{#AppExe}"

[Run]
; Order matters: end any helper still running (also an older uvx/pythonw copy: same lock files), register
; partyline:// and start-at-login with the install logic the helper already has, then start it.
Filename: "{app}\{#AppExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; StatusMsg: "Stopping the running helper..."
Filename: "{app}\{#AppExe}"; Parameters: "install"; Flags: runhidden waituntilterminated; StatusMsg: "Registering partyline:// links..."
Filename: "{app}\{#AppExe}"; Parameters: "start"; Flags: runhidden nowait; Check: ShouldStartHelper

[UninstallRun]
Filename: "{app}\{#AppExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopHelper"
Filename: "{app}\{#AppExe}"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Partyline Helper is installed (once paired it shows a round icon in the system tray).%n%nNext, in Partyline open "Computers / Share screen", choose "Pair a computer", then click "Pair with installed helper".

[Code]
// The helper's own `stop` command (exit 0 = nothing runs any more). Replacing or deleting files under a helper
// that would not stop leaves a broken install, so a failure is reported and the caller aborts.
function HelperStopped: Boolean;
var
  Exe: String;
  Code: Integer;
begin
  Exe := ExpandConstant('{app}\{#AppExe}');
  Result := True;
  if FileExists(Exe) then
    Result := Exec(Exe, 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// An upgrade replaces files that a running helper holds open: stop it first, or do not install.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not HelperStopped then
    Result := 'Partyline Helper is still running and could not be stopped. Quit it from its tray icon (or end ' +
              'PartylineHelper.exe in Task Manager), then run this installer again.';
end;

function InitializeUninstall: Boolean;
begin
  Result := HelperStopped;
  if not Result then
    MsgBox('Partyline Helper is still running and could not be stopped. Quit it from its tray icon (or end ' +
           'PartylineHelper.exe in Task Manager), then uninstall again.', mbError, MB_OK);
end;

// A silent install (CI, scripted upgrade) does not open dialogs unless asked with /START=1.
function ShouldStartHelper: Boolean;
begin
  Result := (not WizardSilent) or (ExpandConstant('{param:START|0}') = '1');
end;
