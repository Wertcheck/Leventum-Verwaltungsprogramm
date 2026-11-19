<#
Leventum - Installer-Smoke-Test (stiller Installer, Serverebene, KEIN Fensterbetrieb).
STATUS: UNGETESTET - nie unter Windows ausgefuehrt. Ersetzt NICHT die manuellen Faelle (Fenster/WebView2, DPI, Demo-Fenster).
Prueft: Installation ohne Entwicklungsumgebung, Start, Health, Einrichtung+Anmeldung, Datenanlage, Neustart+Persistenz, Deinstallation, Daten bleiben.
Aufruf: powershell -File packaging\installer_smoke.ps1 -Setup build\installer\Leventum_Setup.exe
Alle Daten liegen in einem neuen Ordner unter $env:TEMP (LEVENTUM_DATA_DIR); der echte Datenordner wird nicht benutzt. Ergebnis: Exit 0 = alles bestanden.
#>
param([Parameter(Mandatory = $true)][string]$Setup, [int]$Port = 8799)
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$tmp = Join-Path $env:TEMP ('leventum-inst-' + [guid]::NewGuid().ToString('N').Substring(0, 8))
$app = Join-Path $tmp 'app'; $data = Join-Path $tmp 'data'
New-Item -ItemType Directory -Force $tmp | Out-Null
$results = @(); $failed = $false
function Check($name, [scriptblock]$fn) { try { $r = & $fn; $script:results += "OK      $name $r"; Write-Host "OK      $name $r" } catch { $script:failed = $true; $script:results += "FEHLER  $name | $($_.Exception.Message)"; Write-Host "FEHLER  $name | $($_.Exception.Message)" } }
$h = @{ 'X-Leventum-Client' = '1' }
$base = "http://127.0.0.1:$Port"
function StartServer { $env:LEVENTUM_DATA_DIR = $data; $p = Start-Process -FilePath (Join-Path $app 'LeventumServer.exe') -ArgumentList @('--port', $Port) -PassThru -WindowStyle Hidden
  for ($i = 0; $i -lt 90; $i++) { try { Invoke-RestMethod "$base/api/v1/health" -TimeoutSec 2 | Out-Null; return $p } catch { Start-Sleep 1 } }; throw 'Server startet nicht' }
function StopServer($p) { & taskkill /PID $p.Id /T /F | Out-Null; Start-Sleep 2 }

Check '01 stille Installation ohne Entwicklungsumgebung' { $pr = Start-Process $Setup -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES', '/NORESTART', "/DIR=`"$app`"", '/TASKS=desktopicon') -Wait -PassThru; if ($pr.ExitCode -ne 0) { throw "Setup-Exit $($pr.ExitCode)" }
  foreach ($f in 'Leventum.exe', 'LeventumServer.exe') { if (-not (Test-Path (Join-Path $app $f))) { throw "$f fehlt" } } }
$p = $null
Check '02 Erster Start und Health' { $script:p = StartServer; (Invoke-RestMethod "$base/api/v1/health").status }
$sess = $null
Check '03 Einrichtung und Anmeldung' { $b = '{"username":"admin","password":"Smoke-Test-Passwort-0815","display_name":"Admin"}'
  Invoke-RestMethod "$base/api/v1/auth/setup" -Method Post -Headers $h -ContentType 'application/json' -Body $b -SessionVariable s | Out-Null; $script:sess = $s; 'angemeldet' }
Check '04 Frontend wird ausgeliefert' { if ((Invoke-WebRequest "$base/" -UseBasicParsing).Content -notmatch '<html') { throw 'keine HTML-Seite' } }
Check '05 Stammdaten anlegen' { $b = '{"kind":"company","company_name":"Persistenztest GmbH","roles":["owner"]}'; (Invoke-RestMethod "$base/api/v1/parties" -Method Post -Headers $h -ContentType 'application/json' -Body $b -WebSession $sess).display_name }
Check '06 Neustart und Persistenz' { StopServer $p; $script:p = StartServer
  $b = '{"username":"admin","password":"Smoke-Test-Passwort-0815"}'; Invoke-RestMethod "$base/api/v1/auth/login" -Method Post -Headers $h -ContentType 'application/json' -Body $b -SessionVariable s2 | Out-Null; $script:s2 = $s2
  $l = Invoke-RestMethod "$base/api/v1/parties" -WebSession $s2; if (-not ($l.items | Where-Object { $_.display_name -eq 'Persistenztest GmbH' })) { throw 'Datensatz nach Neustart weg' } 'Datensatz vorhanden' }
Check '07 Verschluesseltes Backup' { $b = '{"passphrase":"geheim-1234-xyz-demo"}'; $r = Invoke-RestMethod "$base/api/v1/system/backups" -Method Post -Headers $h -ContentType 'application/json' -Body $b -WebSession $s2; if (-not ($r.encrypted -and $r.verified)) { throw 'Backup nicht verifiziert' } }
if ($p) { StopServer $p }
Check '08 Deinstallation' { $u = Join-Path $app 'unins000.exe'; $pr = Start-Process $u -ArgumentList @('/VERYSILENT', '/SUPPRESSMSGBOXES') -Wait -PassThru; if ($pr.ExitCode -ne 0) { throw "Uninstall-Exit $($pr.ExitCode)" }; Start-Sleep 2
  if (Test-Path (Join-Path $app 'Leventum.exe')) { throw 'Programmdateien noch vorhanden' } }
Check '09 Benutzerdaten nach Deinstallation erhalten' { if (-not (Test-Path (Join-Path $data 'db\leventum.sqlite3'))) { throw 'Datenbank wurde geloescht' }; 'Datenbank vorhanden' }
$results | Set-Content (Join-Path $tmp 'ergebnis.txt'); Write-Host "Ergebnis: $tmp\ergebnis.txt"
if ($failed) { exit 1 } else { exit 0 }
