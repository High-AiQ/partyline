; Inno Setup script: a per-user installer for the frozen helper (no administrator rights, no UAC prompt).
; Build: iscc /DAppVersion=2.89.0 packaging\windows\installer.iss   (after PyInstaller made dist\PartylineHelper)
; Output: build\installer\PartylineHelper-Setup-<version>.exe  (the version is in the file name and in the file's Details)
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
; Windows version resources want four numbers: 1.2.0 -> 1.2.0.0
#define VersionNumbers AppVersion + ".0"
#define AppName "Partyline Helper"
#define AppExe "PartylineHelper.exe"
#define BinaryDir "{app}\versions\" + AppVersion

[Setup]
AppId={{B6F1D2A4-5C1E-4E0B-9C57-3A7E2D0F4A61}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher=Partyline
VersionInfoVersion={#VersionNumbers}
VersionInfoProductVersion={#AppVersion}
VersionInfoProductName={#AppName}
VersionInfoDescription={#AppName} Setup
VersionInfoCompany=Partyline
DefaultDirName={localappdata}\Programs\Partyline Helper
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\..\build\installer
OutputBaseFilename=PartylineHelper-Setup-{#AppVersion}
SetupIconFile=..\..\build\PartylineHelper.ico
UninstallDisplayIcon={#BinaryDir}\{#AppExe}
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
Source: "..\..\dist\PartylineHelper\*"; DestDir: "{#BinaryDir}"; Flags: recursesubdirs ignoreversion

[Icons]
Name: "{autoprograms}\{#AppName}"; Filename: "{#BinaryDir}\{#AppExe}"

[Run]
; Order matters: end any helper still running (also an older uvx/pythonw copy: same lock files), register
; partyline:// and start-at-login with the install logic the helper already has, then start it.
Filename: "{#BinaryDir}\{#AppExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; StatusMsg: "Stopping the running helper..."
Filename: "{#BinaryDir}\{#AppExe}"; Parameters: "install"; Flags: runhidden waituntilterminated; StatusMsg: "Registering partyline:// links..."
Filename: "{#BinaryDir}\{#AppExe}"; Parameters: "start"; Flags: runhidden nowait; Check: ShouldStartHelper

[UninstallRun]
Filename: "{#BinaryDir}\{#AppExe}"; Parameters: "stop"; Flags: runhidden waituntilterminated; RunOnceId: "StopHelper"
Filename: "{#BinaryDir}\{#AppExe}"; Parameters: "uninstall"; Flags: runhidden waituntilterminated; RunOnceId: "Unregister"

[UninstallDelete]
Type: filesandordirs; Name: "{app}"

[Messages]
FinishedLabel=Partyline Helper is installed (once paired it shows a round icon in the system tray).%n%nNext, in Partyline open "Computers / Share screen", choose "Pair a computer", then click "Pair with installed helper".

[Code]
// The helper's own executable: the registered one wins, so a rollback restores the right registration even when
// Setup's previous-data entry names a failed version.
function HelperExe: String;
var
  RegisteredExe: String;
begin
  Result := GetPreviousData('HelperExe', ExpandConstant('{app}\{#AppExe}'));
  if RegQueryStringValue(HKCU, 'Software\Partyline\Helper', 'Executable', RegisteredExe) then
    if FileExists(RegisteredExe) then
      Result := RegisteredExe;
end;

// The helper's own `stop` command (exit 0 = nothing runs any more). Replacing or deleting files under a helper
// that would not stop leaves a broken install, so a failure is reported and the caller aborts.
function HelperStopped: Boolean;
var
  Exe: String;
  Code: Integer;
begin
  Exe := HelperExe;
  Result := True;
  if FileExists(Exe) then
    Result := Exec(Exe, 'stop', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// Ask Chrome's native host to release its files. The extension reconnects by itself about a minute after this
// (60 s), so it must be asked only when the files are about to be replaced or deleted, never before a dialog
// the person may leave open. Only a helper that registered the Chrome host (1.5.0 or later) has one to pause;
// an older helper does not know `suspend-chrome`, and its refusal must not block anything. An automatic
// update never asks: it installs into a new version folder and the host keeps its old one.
function ChromeHostReleased: Boolean;
var
  Exe: String;
  Code: Integer;
begin
  Exe := HelperExe;
  Result := True;
  if (ExpandConstant('{param:AUTOUPDATE|0}') <> '1') and FileExists(Exe)
     and RegKeyExists(HKCU, 'Software\Google\Chrome\NativeMessagingHosts\io.partyline.chrome') then
    Result := Exec(Exe, 'suspend-chrome', '', SW_HIDE, ewWaitUntilTerminated, Code) and (Code = 0);
end;

// An upgrade replaces files that a running helper holds open: stop it first, or do not install.
function PrepareToInstall(var NeedsRestart: Boolean): String;
begin
  Result := '';
  if not (HelperStopped and ChromeHostReleased) then
    Result := 'Partyline Helper is still running and could not be stopped. Quit it from its tray icon (or end ' +
              'PartylineHelper.exe in Task Manager), disable Partyline Chrome at chrome://extensions, then run this installer again.';
end;

function InitializeUninstall: Boolean;
begin
  Result := HelperStopped;
  if not Result then
    MsgBox('Partyline Helper is still running and could not be stopped. Quit it from its tray icon (or end ' +
           'PartylineHelper.exe in Task Manager), disable Partyline Chrome at chrome://extensions, then uninstall again.', mbError, MB_OK);
end;

// The uninstall confirmation may stay open for minutes: release the Chrome host only once removal starts.
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if CurUninstallStep = usUninstall then
    if not ChromeHostReleased then
      MsgBox('Partyline Chrome''s native host could not be released. If some files remain, close Chrome and ' +
             'delete the Partyline Helper folder.', mbInformation, MB_OK);
end;

// A silent install (CI, scripted upgrade) does not open dialogs unless asked with /START=1.
function ShouldStartHelper: Boolean;
begin
  Result := (not WizardSilent) or (ExpandConstant('{param:START|0}') = '1');
end;

procedure RegisterPreviousData(PreviousDataKey: Integer);
begin
  SetPreviousData(PreviousDataKey, 'HelperExe', ExpandConstant('{#BinaryDir}\{#AppExe}'));
end;
