; Inno Setup 6 – Leventum Installer.  STATUS: NICHT kompiliert, NICHT unter Windows getestet (Erstellt unter Linux ohne Inno Setup).
; Aufruf: ISCC.exe /DAppVersion=0.1.0 packaging\leventum.iss   (nach packaging\build_windows.ps1, das build\dist\Leventum erzeugt)
; Grundsätze: Installation pro Benutzer (kein Administrator), Programmdateien getrennt von den Benutzerdaten (%LOCALAPPDATA%\Leventum),
; Deinstallation löscht Benutzerdaten NIE. Keine Zugangsdaten im Installer; die Demo erzeugt ihr Passwort zur Laufzeit.
#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif

[Setup]
AppId={{AE95247B-DE09-4BE3-BF1A-769828DC3D25}
AppName=Leventum Verwaltung
AppVersion={#AppVersion}
AppPublisher=Leventum Real Estate GmbH
DefaultDirName={localappdata}\Programs\Leventum
DefaultGroupName=Leventum
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
OutputDir=..\build\installer
OutputBaseFilename=Leventum_Setup
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
CloseApplications=yes
UninstallDisplayName=Leventum Verwaltung
UninstallDisplayIcon={app}\Leventum.exe

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknüpfung erstellen"; GroupDescription: "Zusätzliche Verknüpfungen:"

[Files]
Source: "..\build\dist\Leventum\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{group}\Leventum"; Filename: "{app}\Leventum.exe"
Name: "{group}\Leventum Demo (erfundene Daten)"; Filename: "{app}\Leventum.exe"; Parameters: "--demo"
Name: "{group}\Leventum Browser-Modus (Diagnose)"; Filename: "{app}\LeventumServer.exe"
Name: "{group}\Leventum deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\Leventum"; Filename: "{app}\Leventum.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\Leventum.exe"; Description: "Leventum jetzt starten"; Flags: nowait postinstall skipifsilent

; Es gibt bewusst KEINEN [UninstallDelete]-Eintrag für %LOCALAPPDATA%\Leventum (Benutzerdaten) und \leventum-demo.

[Code]
function WebView2Installed(): Boolean;
var v: String;
begin
  Result := RegQueryStringValue(HKLM, 'SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v)
         or RegQueryStringValue(HKCU, 'Software\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v)
         or RegQueryStringValue(HKLM, 'SOFTWARE\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}', 'pv', v);
  if Result then Result := (v <> '') and (v <> '0.0.0.0');
end;

procedure CurStepChanged(CurStep: TSetupStep);
begin
  if (CurStep = ssPostInstall) and (not WebView2Installed()) and (not WizardSilent) then
    MsgBox('Hinweis: Die Microsoft-WebView2-Runtime wurde nicht gefunden. Leventum benötigt sie für das Programmfenster ' +
           '(Windows 11 und aktuelle Windows-10-Versionen bringen sie meist mit). Bitte installieren Sie die "Evergreen WebView2 Runtime" von Microsoft ' +
           'oder nutzen Sie solange die Verknüpfung "Leventum Browser-Modus (Diagnose)".', mbInformation, MB_OK);
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  if (CurUninstallStep = usPostUninstall) and (not UninstallSilent) then
    MsgBox('Leventum wurde entfernt. Ihre Daten (Datenbank, Dokumente, Backups) wurden NICHT gelöscht und liegen weiterhin unter:' + #13#10 +
           ExpandConstant('{localappdata}\Leventum') + #13#10 + 'Löschen Sie diesen Ordner nur, wenn Sie die Daten nicht mehr benötigen (vorher ein Backup anlegen).', mbInformation, MB_OK);
end;
