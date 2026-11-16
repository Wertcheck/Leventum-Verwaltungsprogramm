<#
=====================================================================================================
UNGETESTET – nie auf Windows ausgeführt, Syntax nicht geprüft
=====================================================================================================
Leventum - manueller Windows-Smoke-Test (Vorbereitung der Windows-Testphase, siehe docs/WINDOWS_TESTPLAN.md)

STATUS: Erstellt in einer Linux-Umgebung ohne Windows, ohne PowerShell, ohne Wine. Dieses Skript wurde
NIE ausgeführt und seine Syntax wurde NICHT geprüft. Jede Aussage über Windows-Verhalten in den Kommentaren
ist eine ANNAHME / ZU PRÜFEN. Ein erfolgreicher Lauf ersetzt NICHT die manuellen Fälle im Testplan
(Fenster/WebView2, DPI, Dialoge, Download-Verhalten im Fenster, Restore bei geöffneter DB, ...).
Erst nach einem echten Lauf (mit Ergebnisdatei) darf etwas als "unter Windows getestet" gelten.

Zweck: Server-/API-Ebene unter Windows prüfen (--browser-Modus, KEIN pywebview-Fenster):
  Python-Version, pip-Installation, Frontend-dist, Serverstart mit eigenem Datenordner, Health, 127.0.0.1-Bindung,
  CSRF-Header, Admin-Einrichtung/Login, Backup (unverschlüsselt + verschlüsselt), Verify, Upload/Download mit SHA-256,
  Serverende (hart), Neustart, Datenerhalt. Ergebnis als JSON (pass/fail/not-run je Prüfung) + Exit-Code.

Verwendung (PowerShell 5.1 oder 7, im Repo-Wurzelordner; Beispiel):
  powershell -ExecutionPolicy Bypass -File .\scripts\windows_smoke_test.ps1
  .\scripts\windows_smoke_test.ps1 -Port 8799 -SkipInstall -PythonExe "C:\Python311\python.exe"

Exit-Code: 0 = keine Prüfung fehlgeschlagen (not-run zählt NICHT als bestanden - Ergebnisdatei lesen!),
           1 = mindestens eine Prüfung fehlgeschlagen, 2 = Skript-Abbruch (unerwarteter Fehler).

Sicherheits-/Datenschutzrahmen:
  * Keine echten Daten, keine Secrets: Passwort/Passphrase sind erfundene Testwerte (siehe unten).
  * Datenordner (LEVENTUM_DATA_DIR) liegt in einem NEUEN Unterordner von $env:TEMP; es wird nichts außerhalb davon gelöscht.
    Der Ordner wird nur mit -Cleanup gelöscht (nur wenn er unter $env:TEMP liegt und den Präfix 'leventum-smoke-' trägt).
  * Der Server bindet laut Code nur an 127.0.0.1; das Skript spricht nur 127.0.0.1 an.
  * AUSNAHME ausgehende Verbindung: 'pip install' lädt Pakete (PyPI). Mit -SkipInstall entfällt das (Umgebung dann selbst vorbereiten).
  * AUSNAHME Schreibzugriff außerhalb Temp: 'pip install -e' legt Build-Metadaten (leventum.egg-info) in backend\ an (Neuanlage, kein Löschen).
    Grund für editierbare Installation: main.py sucht alembic.ini/alembic relativ zum Quellordner (BACKEND_DIR) und
    pyproject.toml packt diese Ordner nicht ins Paket -> eine normale (nicht editierbare) Installation ist laut Quellcodelektüre
    wahrscheinlich NICHT lauffähig (zu prüfen, siehe docs/WINDOWS_BUILD_PLAN.md).
  * Die ergebnisrelevante JSON-Datei wird (außer mit -ResultFile) nach $env:TEMP geschrieben.

Annahmen/TODO (nicht verifiziert):
  * TODO: Der venv-python.exe-Starter spawnt unter Windows evtl. einen Kindprozess -> deshalb 'taskkill /T /F' statt Stop-Process.
  * TODO: WebView2-Registry-Pfad (nur Info im Umgebungsblock) ist eine Annahme.
  * TODO: UTF-8-Dateiname im Multipart-Header (Umlaute) wird vom Server evtl. anders dekodiert -> Prüfung S15 zeigt es.
  * TODO: netstat-Ausgabeformat (Prüfung S07) ist angenommen; bei Abweichung 'fail' bitte manuell mit 'netstat -ano' gegenprüfen.
  * Ausführbarer Code ist ASCII (Umlaute per [char]-Code); Nicht-ASCII steht nur in diesem Kommentarkopf. Falls PS 5.1 die
    Datei (ohne BOM) falsch liest, betrifft das nur Kommentare (Annahme, zu prüfen).
=====================================================================================================
#>
[CmdletBinding()]
param(
    [string]$PythonExe = 'python',
    [int]$Port = 8799,
    [string]$ResultFile = '',
    [switch]$SkipInstall,
    [switch]$Cleanup
)

Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'

# --- erfundene Testwerte (KEINE echten Zugangsdaten) --------------------------------------------------------------
$TestUser       = 'smoketest'
$TestPassword   = 'Smoke-Test-Passwort-0815'      # >= 12 Zeichen (Server-Mindestlaenge laut config.py: 12)
$TestPassphrase = 'Smoke-Test-Passphrase-4711'    # >= 12 Zeichen (backup_crypto.MIN_PASSPHRASE)
$WrongPassphrase = 'Falsche-Passphrase-0000'

$RepoRoot   = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$BackendDir = Join-Path $RepoRoot 'backend'
$DistDir    = Join-Path (Join-Path $RepoRoot 'frontend') 'dist'
$Stamp      = Get-Date -Format 'yyyyMMdd-HHmmss'
$TempRoot   = [System.IO.Path]::GetTempPath().TrimEnd('\')
$RunDir     = Join-Path $TempRoot ("leventum-smoke-" + $Stamp)
$DataDir    = Join-Path $RunDir 'data'
$WorkDir    = Join-Path $RunDir 'work'
$VenvDir    = Join-Path $RunDir 'venv'
if (-not $ResultFile) { $ResultFile = Join-Path $TempRoot ("leventum-smoke-result-" + $Stamp + ".json") }
$BaseUrl    = "http://127.0.0.1:$Port"
$Api        = "$BaseUrl/api/v1"

$script:Results   = New-Object System.Collections.ArrayList
$script:Sess      = $null
$script:ServerPid = $null
$script:Py        = $PythonExe
$script:Fatal     = $false     # nach einem fatalen Fehler werden Folgepruefungen als not-run markiert
$script:Ctx       = @{}        # gemeinsame Werte zwischen Pruefungen (IDs, Hashes)
$script:SavedEnv  = @{}

# --- Ergebnis-Helfer -------------------------------------------------------------------------------------------------
function Add-Result([string]$Id, [string]$Name, [string]$Status, [string]$Message, [double]$Seconds) {
    [void]$script:Results.Add([ordered]@{
        id = $Id; name = $Name; status = $Status; message = $Message
        seconds = [math]::Round($Seconds, 2); timestamp = (Get-Date).ToString('o')
    })
    Write-Host ("[{0}] {1} {2} - {3}" -f $Status.ToUpper(), $Id, $Name, $Message)
}

# $Body: Scriptblock; wirft bei Fehler; Rueckgabe = Meldung. 'NOTRUN: grund' als Ausnahmetext => not-run.
function Invoke-Check([string]$Id, [string]$Name, [scriptblock]$Body, [switch]$FatalOnFail) {
    if ($script:Fatal) {
        Add-Result $Id $Name 'not-run' 'Uebersprungen: vorherige fatale Pruefung fehlgeschlagen.' 0
        return
    }
    $sw = [System.Diagnostics.Stopwatch]::StartNew()
    try {
        $msg = & $Body
        $sw.Stop()
        Add-Result $Id $Name 'pass' ([string]$msg) $sw.Elapsed.TotalSeconds
    } catch {
        $sw.Stop()
        $text = $_.Exception.Message
        if ($text -like 'NOTRUN:*') {
            Add-Result $Id $Name 'not-run' $text.Substring(7).Trim() $sw.Elapsed.TotalSeconds
        } else {
            Add-Result $Id $Name 'fail' $text $sw.Elapsed.TotalSeconds
            if ($FatalOnFail) { $script:Fatal = $true }
        }
    }
}

function Skip-Check([string]$Id, [string]$Name, [string]$Reason) {
    Add-Result $Id $Name 'not-run' $Reason 0
}

# --- HTTP-Helfer (Invoke-RestMethod, Header X-Leventum-Client: 1) --------------------------------------------------
# Liefert [pscustomobject] Ok/Status/Data/Error; wirft NICHT bei HTTP-Fehlern (Statuscode-Auslesen: TODO unter PS 5.1 pruefen).
function Invoke-Api([string]$Method, [string]$Path, $Body = $null, [switch]$NoHeader, [switch]$NoSession,
                    [byte[]]$RawBody = $null, [string]$ContentType = 'application/json; charset=utf-8') {
    $headers = @{}
    if (-not $NoHeader) { $headers['X-Leventum-Client'] = '1' }
    $p = @{ Method = $Method; Uri = ($Api + $Path); Headers = $headers; UseBasicParsing = $true; TimeoutSec = 60 }
    if (-not $NoSession) {
        if ($null -eq $script:Sess) { $script:Sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession }
        $p['WebSession'] = $script:Sess
    }
    if ($null -ne $RawBody) {
        $p['Body'] = $RawBody; $p['ContentType'] = $ContentType
    } elseif ($null -ne $Body) {
        $json = ConvertTo-Json -InputObject $Body -Compress -Depth 6
        $p['Body'] = [System.Text.Encoding]::UTF8.GetBytes($json); $p['ContentType'] = $ContentType
    }
    # -UseBasicParsing ist bei Invoke-RestMethod nicht definiert (nur Invoke-WebRequest) -> entfernen
    $p.Remove('UseBasicParsing')
    try {
        $data = Invoke-RestMethod @p
        return [pscustomobject]@{ Ok = $true; Status = 200; Data = $data; Error = $null }
    } catch {
        $status = 0
        try { $status = [int]$_.Exception.Response.StatusCode } catch { $status = 0 }
        return [pscustomobject]@{ Ok = $false; Status = $status; Data = $null; Error = $_.Exception.Message }
    }
}

function Assert-Ok($r, [string]$What) {
    if (-not $r.Ok) { throw ("{0}: HTTP {1} - {2}" -f $What, $r.Status, $r.Error) }
}

function Test-PortOpen([int]$P) {
    $c = New-Object System.Net.Sockets.TcpClient
    try {
        $iar = $c.BeginConnect('127.0.0.1', $P, $null, $null)
        if ($iar.AsyncWaitHandle.WaitOne(500)) { try { $c.EndConnect($iar); return $true } catch { return $false } }
        return $false
    } finally { $c.Close() }
}

function Wait-Health([int]$TimeoutSec = 60) {
    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while ((Get-Date) -lt $deadline) {
        $r = Invoke-Api 'GET' '/health' -NoSession
        if ($r.Ok -and $r.Data.status -eq 'ok') { return $true }
        if ($script:ServerPid -and -not (Get-Process -Id $script:ServerPid -ErrorAction SilentlyContinue)) { return $false }
        Start-Sleep -Milliseconds 500
    }
    return $false
}

function Start-Server([string]$LogSuffix) {
    $out = Join-Path $RunDir ("server-" + $LogSuffix + ".out.log")
    $err = Join-Path $RunDir ("server-" + $LogSuffix + ".err.log")
    # Umgebungsvariablen werden vom Kindprozess geerbt (Annahme); Originalwerte werden in finally wiederhergestellt.
    $env:LEVENTUM_DATA_DIR = $DataDir
    $env:LEVENTUM_FRONTEND_DIST = $DistDir
    $proc = Start-Process -FilePath $script:Py -ArgumentList @('-m', 'leventum.desktop', '--browser', '--port', "$Port") `
        -WorkingDirectory $WorkDir -PassThru -WindowStyle Hidden -RedirectStandardOutput $out -RedirectStandardError $err
    $script:ServerPid = $proc.Id
    return $proc
}

function Stop-Server {
    $ErrorActionPreference = 'Continue'
    if ($script:ServerPid) {
        # /T beendet den Prozessbaum (venv-Starter + Interpreter, Annahme), /F erzwingt. Hartes Ende = Absturz-Simulation, KEIN sauberes Herunterfahren.
        & taskkill.exe /PID $script:ServerPid /T /F 2>&1 | Out-Null
        Start-Sleep -Seconds 2
        $script:ServerPid = $null
    }
}

function New-TestPdfBytes {
    # Deterministisch (Seed 42), ~300 KB, beginnt mit dem PDF-Magic-Header (Allowlist/Magic-Bytes-Pruefung in storage/local.py).
    $rnd = New-Object System.Random 42
    $body = New-Object byte[] 300000
    $rnd.NextBytes($body)
    $head = [System.Text.Encoding]::ASCII.GetBytes("%PDF-1.4`n% Leventum Smoke-Test, erfundener Inhalt`n")
    $all = New-Object byte[] ($head.Length + $body.Length)
    [Array]::Copy($head, 0, $all, 0, $head.Length)
    [Array]::Copy($body, 0, $all, $head.Length, $body.Length)
    return , $all
}

function New-MultipartBody([string]$Boundary, [hashtable]$Fields, [string]$FileField, [string]$FileName, [byte[]]$FileBytes, [string]$FileMime) {
    $enc = New-Object System.Text.UTF8Encoding $false
    $ms = New-Object System.IO.MemoryStream
    $w = { param([string]$s) $b = $enc.GetBytes($s); $ms.Write($b, 0, $b.Length) }
    foreach ($k in $Fields.Keys) {
        & $w ("--$Boundary`r`nContent-Disposition: form-data; name=`"$k`"`r`n`r`n$($Fields[$k])`r`n")
    }
    # Dateiname als rohes UTF-8 im Header (TODO: Serverseitige Dekodierung unter Windows pruefen)
    & $w ("--$Boundary`r`nContent-Disposition: form-data; name=`"$FileField`"; filename=`"$FileName`"`r`nContent-Type: $FileMime`r`n`r`n")
    $ms.Write($FileBytes, 0, $FileBytes.Length)
    & $w ("`r`n--$Boundary--`r`n")
    return , $ms.ToArray()
}

function Get-FileSha256([string]$Path) { return (Get-FileHash -Algorithm SHA256 -LiteralPath $Path).Hash.ToLower() }

function Get-EnvInfo {
    $ErrorActionPreference = 'Continue'
    $info = [ordered]@{}
    $info['powershell_version'] = $PSVersionTable.PSVersion.ToString()
    $info['powershell_edition'] = if ($PSVersionTable.ContainsKey('PSEdition')) { [string]$PSVersionTable.PSEdition } else { 'Desktop' }
    try { $os = Get-CimInstance Win32_OperatingSystem; $info['os'] = $os.Caption; $info['os_build'] = $os.BuildNumber; $info['os_version'] = $os.Version } catch { $info['os'] = 'unbekannt: ' + $_.Exception.Message }
    $info['machine'] = $env:COMPUTERNAME   # Hinweis: Rechnername kann personenbezogen sein -> vor Weitergabe der Datei pruefen/schwaerzen
    try { $info['python'] = (& $script:Py --version 2>&1 | Out-String).Trim() } catch { $info['python'] = 'nicht ermittelbar' }
    try { $info['python_path'] = (& $script:Py -c "import sys; print(sys.executable)" 2>&1 | Out-String).Trim() } catch { }
    try {
        $wv = Get-ItemProperty -Path 'HKLM:\SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}' -ErrorAction Stop
        $info['webview2_runtime'] = [string]$wv.pv   # TODO: Registry-Pfad ist eine Annahme
    } catch { $info['webview2_runtime'] = 'nicht ermittelt (Registry-Pfad ungeprueft)' }
    try { $c = (& git -C $RepoRoot rev-parse --short HEAD 2>$null | Out-String).Trim(); $info['git_commit'] = $c } catch { $info['git_commit'] = 'unbekannt' }
    $info['data_dir'] = $DataDir
    $info['port'] = $Port
    return $info
}

function Write-ResultFile($Env) {
    $summary = [ordered]@{ pass = 0; fail = 0; 'not-run' = 0 }
    foreach ($r in $script:Results) { $summary[$r.status] = $summary[$r.status] + 1 }
    $doc = [ordered]@{
        status_note = 'UNGETESTET-Skript: Ergebnisse gelten nur fuer diesen einen Lauf; not-run ist NICHT bestanden.'
        started = $script:StartedAt; finished = (Get-Date).ToString('o')
        environment = $Env; summary = $summary; checks = $script:Results
    }
    $json = ConvertTo-Json -InputObject $doc -Depth 8
    [System.IO.File]::WriteAllText($ResultFile, $json, (New-Object System.Text.UTF8Encoding $false))
    Write-Host "Ergebnisdatei: $ResultFile"
}

# =====================================================================================================================
$script:StartedAt = (Get-Date).ToString('o')
$exitCode = 0
$envInfo = $null
try {
    Write-Host 'UNGETESTET - nie auf Windows ausgefuehrt, Syntax nicht geprueft'
    New-Item -ItemType Directory -Force -Path $RunDir, $DataDir, $WorkDir | Out-Null
    foreach ($n in 'LEVENTUM_DATA_DIR', 'LEVENTUM_FRONTEND_DIST') { $script:SavedEnv[$n] = [Environment]::GetEnvironmentVariable($n) }

    # S01 Python-Version (pyproject: requires-python >=3.11)
    Invoke-Check 'S01' 'Python >= 3.11 vorhanden' {
        $ErrorActionPreference = 'Continue'   # PS 5.1: stderr nativer Programme darf nicht abbrechen (Annahme)
        $v = (& $script:Py -c "import sys; print('%d.%d.%d' % sys.version_info[:3]); sys.exit(0 if sys.version_info >= (3, 11) else 3)" 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0) { throw "Python-Version zu alt oder nicht aufrufbar: $v" }
        "Python $v"
    } -FatalOnFail

    # S02 pip-Installation in eigener venv unter dem Temp-Ordner
    Invoke-Check 'S02' 'pip install -e backend[desktop] (venv im Temp-Ordner)' {
        $ErrorActionPreference = 'Continue'
        if ($SkipInstall) { throw 'NOTRUN: -SkipInstall gesetzt; Umgebung wird unveraendert verwendet (Installation nicht geprueft).' }
        & $script:Py -m venv $VenvDir
        if ($LASTEXITCODE -ne 0) { throw 'venv-Erzeugung fehlgeschlagen.' }
        $vpy = Join-Path (Join-Path $VenvDir 'Scripts') 'python.exe'
        if (-not (Test-Path -LiteralPath $vpy)) { throw "venv-Python nicht gefunden: $vpy" }
        $script:Py = $vpy
        & $script:Py -m pip install --disable-pip-version-check -e ($BackendDir + '[desktop]') 2>&1 | Tee-Object -FilePath (Join-Path $RunDir 'pip-install.log') | Out-Null
        if ($LASTEXITCODE -ne 0) { throw "pip install fehlgeschlagen (siehe $RunDir\pip-install.log)." }
        $wv = (& $script:Py -m pip show pywebview 2>&1 | Out-String)
        if ($wv -notmatch 'Version:\s*(\S+)') { throw 'pywebview nach Installation nicht gefunden.' }
        $script:Ctx['pywebview'] = $Matches[1]
        "installiert; pywebview $($Matches[1])"
    } -FatalOnFail

    # S03 Importtest (zeigt u.a. fehlende Abhaengigkeiten frueh)
    Invoke-Check 'S03' 'import leventum.desktop (ohne Fenster)' {
        $ErrorActionPreference = 'Continue'
        $o = (& $script:Py -c "import leventum.desktop; print('ok')" 2>&1 | Out-String).Trim()
        if ($LASTEXITCODE -ne 0 -or $o -notlike '*ok*') { throw "Import fehlgeschlagen: $o" }
        'Import ok'
    } -FatalOnFail

    # S04 Frontend-dist vorhanden
    Invoke-Check 'S04' 'frontend\dist\index.html vorhanden' {
        $idx = Join-Path $DistDir 'index.html'
        if (-not (Test-Path -LiteralPath $idx)) { throw "Fehlt: $idx (vorher im Ordner frontend: npm ci; npm run build)" }
        if (-not (Test-Path -LiteralPath (Join-Path $DistDir 'assets'))) { throw "Fehlt: $DistDir\assets (main.py mountet /assets)" }
        'dist vorhanden'
    } -FatalOnFail

    $envInfo = Get-EnvInfo
    $envInfo['pywebview_version'] = if ($script:Ctx.ContainsKey('pywebview')) { $script:Ctx['pywebview'] } else { 'nicht ermittelt' }

    # S05 Port frei
    Invoke-Check 'S05' "Port $Port frei" {
        if (Test-PortOpen $Port) { throw "Port $Port ist bereits belegt - anderen -Port waehlen." }
        'frei'
    } -FatalOnFail

    # S06 Serverstart + Health
    Invoke-Check 'S06' 'Server startet (--browser) und /api/v1/health = ok' {
        [void](Start-Server 'run1')
        if (-not (Wait-Health 90)) { throw "Health nicht erreichbar. Logs: $RunDir\server-run1.*.log" }
        'health ok'
    } -FatalOnFail

    # S07 Bindung nur 127.0.0.1 (netstat-Format angenommen)
    Invoke-Check 'S07' 'Listener nur auf 127.0.0.1' {
        $ErrorActionPreference = 'Continue'
        $lines = & netstat.exe -ano -p TCP 2>&1 | Where-Object { $_ -match "LISTENING" -and $_ -match ":$Port\s" }
        if (-not $lines) { throw 'Kein LISTENING-Eintrag fuer den Port gefunden (netstat-Format ungeprueft).' }
        foreach ($l in $lines) {
            if ($l -notmatch '^\s*TCP\s+127\.0\.0\.1:') { throw "Listener nicht auf 127.0.0.1: $l" }
        }
        "nur 127.0.0.1: $(@($lines).Count) Eintrag/Eintraege"
    }

    # S08 CSRF-Pflichtheader (Negativtest: ohne X-Leventum-Client muss 403 kommen)
    Invoke-Check 'S08' 'POST ohne X-Leventum-Client wird abgelehnt (403)' {
        $r = Invoke-Api 'POST' '/auth/login' @{ username = 'x'; password = 'y' } -NoHeader -NoSession
        if ($r.Ok -or $r.Status -ne 403) { throw "Erwartet HTTP 403, erhalten: Ok=$($r.Ok) Status=$($r.Status)" }
        'HTTP 403'
    }

    # S09 Ersteinrichtung Admin (POST /auth/setup: username, password, display_name; Setzt Sitzungs-Cookie)
    Invoke-Check 'S09' 'Admin einrichten (auth/setup)' {
        $s = Invoke-Api 'GET' '/auth/status'
        Assert-Ok $s 'auth/status'
        if (-not $s.Data.setup_required) { throw 'setup_required ist false - Datenordner nicht leer?' }
        $r = Invoke-Api 'POST' '/auth/setup' @{ username = $TestUser; password = $TestPassword; display_name = 'Smoke Test' }
        Assert-Ok $r 'auth/setup'
        $me = Invoke-Api 'GET' '/auth/me'
        Assert-Ok $me 'auth/me (Cookie-Sitzung)'
        "Rolle: $($me.Data.role)"
    } -FatalOnFail

    # S10 Logout + Login
    Invoke-Check 'S10' 'Logout und erneut anmelden (auth/login)' {
        Assert-Ok (Invoke-Api 'POST' '/auth/logout') 'auth/logout'
        $script:Sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        $r = Invoke-Api 'POST' '/auth/login' @{ username = $TestUser; password = $TestPassword }
        Assert-Ok $r 'auth/login'
        'Login ok'
    } -FatalOnFail

    # S11 Objekt anlegen (Dokumentziel; entity_type=property)
    Invoke-Check 'S11' 'Testobjekt anlegen (POST /properties)' {
        $r = Invoke-Api 'POST' '/properties' @{ name = 'Smoke-Testobjekt'; property_type = 'wohnung' }
        Assert-Ok $r 'properties'
        $script:Ctx['property_id'] = [int]$r.Data.id
        "property_id=$($script:Ctx['property_id'])"
    } -FatalOnFail

    # S12 Backup unverschluesselt (POST /system/backups; Antwort: id, encrypted, verified, problems)
    Invoke-Check 'S12' 'Backup unverschluesselt erstellen + verified' {
        $r = Invoke-Api 'POST' '/system/backups' @{}
        Assert-Ok $r 'backup create'
        if ($r.Data.encrypted) { throw 'Backup unerwartet als verschluesselt gemeldet.' }
        if (-not $r.Data.verified) { throw "verified=false: $($r.Data.problems -join '; ')" }
        $script:Ctx['backup_plain'] = [string]$r.Data.id
        $f = Join-Path (Join-Path $DataDir 'backups') $r.Data.id
        if (-not (Test-Path -LiteralPath $f)) { throw "Backup-Datei fehlt: $f" }
        $v = Invoke-Api 'POST' ("/system/backups/" + $r.Data.id + "/verify") @{}
        Assert-Ok $v 'backup verify'
        if (-not $v.Data.ok) { throw "Verify ok=false: $($v.Data.problems -join '; ')" }
        "$($r.Data.id) ($((Get-Item -LiteralPath $f).Length) Bytes)"
    }

    # S13 Backup verschluesselt
    Invoke-Check 'S13' 'Backup verschluesselt erstellen (.enc, Magic LEVBKP01) + verified' {
        $r = Invoke-Api 'POST' '/system/backups' @{ passphrase = $TestPassphrase }
        Assert-Ok $r 'backup create (enc)'
        if (-not $r.Data.encrypted -or -not ([string]$r.Data.id).EndsWith('.enc')) { throw "Nicht als .enc gemeldet: id=$($r.Data.id)" }
        if (-not $r.Data.verified) { throw "verified=false: $($r.Data.problems -join '; ')" }
        $script:Ctx['backup_enc'] = [string]$r.Data.id
        $f = Join-Path (Join-Path $DataDir 'backups') $r.Data.id
        $head = New-Object byte[] 8
        $fs = [System.IO.File]::OpenRead($f)
        try { [void]$fs.Read($head, 0, 8) } finally { $fs.Close() }
        if ([System.Text.Encoding]::ASCII.GetString($head) -ne 'LEVBKP01') { throw 'Magic LEVBKP01 fehlt am Dateianfang.' }
        $v = Invoke-Api 'POST' ("/system/backups/" + $r.Data.id + "/verify") @{ passphrase = $TestPassphrase }
        Assert-Ok $v 'backup verify (enc)'
        if (-not $v.Data.ok) { throw "Verify ok=false: $($v.Data.problems -join '; ')" }
        $r.Data.id
    }

    # S14 falsche Passphrase muss scheitern (Antwort 200 mit ok=false laut routers.py)
    Invoke-Check 'S14' 'Verify mit falscher Passphrase schlaegt fehl' {
        $v = Invoke-Api 'POST' ("/system/backups/" + $script:Ctx['backup_enc'] + "/verify") @{ passphrase = $WrongPassphrase }
        Assert-Ok $v 'verify wrong passphrase'
        if ($v.Data.ok) { throw 'Falsche Passphrase wurde akzeptiert!' }
        "abgelehnt: $($v.Data.problems -join '; ')"
    }

    # S15 Upload (multipart: file, entity_type, entity_id, doc_type); Dateiname mit Umlauten + Leerzeichen
    $ue = [string][char]0x00FC; $oe = [string][char]0x00F6
    $docName = "Pr${ue}fdokument K${oe}nig.pdf"
    $upBytes = New-TestPdfBytes
    $upHash = ([System.BitConverter]::ToString([System.Security.Cryptography.SHA256]::Create().ComputeHash($upBytes)) -replace '-', '').ToLower()
    Invoke-Check 'S15' 'Dokument hochladen (Umlaute im Dateinamen)' {
        $boundary = '----LeventumSmoke' + [guid]::NewGuid().ToString('N')
        $mp = New-MultipartBody $boundary @{ entity_type = 'property'; entity_id = "$($script:Ctx['property_id'])"; doc_type = 'sonstige' } 'file' $docName $upBytes 'application/pdf'
        $r = Invoke-Api 'POST' '/documents' -RawBody $mp -ContentType ("multipart/form-data; boundary=" + $boundary)
        Assert-Ok $r 'documents upload'
        $script:Ctx['doc_id'] = [int]$r.Data.id
        $script:Ctx['doc_name_returned'] = [string]$r.Data.original_name
        if ($r.Data.original_name -ne $docName) { throw "Dateiname veraendert: erwartet '$docName', erhalten '$($r.Data.original_name)' (Kodierung pruefen)." }
        "doc_id=$($r.Data.id), size=$($r.Data.size)"
    }

    # S16 Download + SHA-256-Vergleich
    function Test-DocDownload([string]$OutName) {
        $out = Join-Path $RunDir $OutName
        if (Test-Path -LiteralPath $out) { Remove-Item -LiteralPath $out -Force }   # nur Datei im eigenen RunDir
        Invoke-WebRequest -Uri ("$Api/documents/$($script:Ctx['doc_id'])/download") -Headers @{ 'X-Leventum-Client' = '1' } `
            -WebSession $script:Sess -OutFile $out -UseBasicParsing -TimeoutSec 60 | Out-Null
        $h = Get-FileSha256 $out
        if ($h -ne $upHash) { throw "SHA-256 stimmt nicht: erwartet $upHash, erhalten $h" }
        return $h
    }
    Invoke-Check 'S16' 'Dokument herunterladen, SHA-256 identisch' {
        if (-not $script:Ctx.ContainsKey('doc_id')) { throw 'NOTRUN: kein Upload vorhanden (S15 fehlgeschlagen).' }
        $h = Test-DocDownload 'download-run1.pdf'
        "sha256=$h"
    }

    # S17 Server hart beenden
    Invoke-Check 'S17' 'Server beenden (taskkill /T /F; Absturz-aehnlich)' {
        Stop-Server
        if (Test-PortOpen $Port) { throw "Port $Port antwortet nach Beenden weiterhin (Kindprozess uebrig?)." }
        'Port geschlossen'
    } -FatalOnFail

    # S18 DB-Datei vorhanden (WAL/SHM-Hinweis: Dateien bleiben evtl. liegen; nur Information)
    Invoke-Check 'S18' 'Datenbankdatei im Datenordner vorhanden' {
        $db = Join-Path (Join-Path $DataDir 'db') 'leventum.sqlite3'
        if (-not (Test-Path -LiteralPath $db)) { throw "Fehlt: $db" }
        $extra = @(Get-ChildItem -LiteralPath (Join-Path $DataDir 'db') | Select-Object -ExpandProperty Name) -join ', '
        "Dateien: $extra"
    }

    # S19 Neustart + Health
    Invoke-Check 'S19' 'Server neu starten, health = ok' {
        [void](Start-Server 'run2')
        if (-not (Wait-Health 90)) { throw "Health nach Neustart nicht erreichbar. Logs: $RunDir\server-run2.*.log" }
        'health ok'
    } -FatalOnFail

    # S20 Daten nach Neustart erhalten
    Invoke-Check 'S20' 'Nach Neustart: Login, Objekt, Dokument, Backups vorhanden' {
        $s = Invoke-Api 'GET' '/auth/status' -NoSession
        Assert-Ok $s 'auth/status'
        if ($s.Data.setup_required) { throw 'setup_required=true: Admin nach Neustart nicht mehr vorhanden!' }
        $script:Sess = New-Object Microsoft.PowerShell.Commands.WebRequestSession
        Assert-Ok (Invoke-Api 'POST' '/auth/login' @{ username = $TestUser; password = $TestPassword }) 'login nach Neustart'
        $props = Invoke-Api 'GET' '/properties'
        Assert-Ok $props 'properties'
        if (-not (@($props.Data.items) | Where-Object { $_.id -eq $script:Ctx['property_id'] -and $_.name -eq 'Smoke-Testobjekt' })) { throw 'Testobjekt fehlt nach Neustart.' }
        $docs = Invoke-Api 'GET' ("/documents?entity_type=property&entity_id=" + $script:Ctx['property_id'])
        Assert-Ok $docs 'documents list'
        if (-not (@($docs.Data.items) | Where-Object { $_.id -eq $script:Ctx['doc_id'] })) { throw 'Dokument fehlt nach Neustart.' }
        $bk = Invoke-Api 'GET' '/system/backups'
        Assert-Ok $bk 'backups list'
        $ids = @($bk.Data.items | ForEach-Object { $_.id })
        foreach ($need in @($script:Ctx['backup_plain'], $script:Ctx['backup_enc'])) { if ($ids -notcontains $need) { throw "Backup fehlt nach Neustart: $need" } }
        'Admin, Objekt, Dokument, 2 Backups vorhanden'
    }

    # S21 Dokument nach Neustart unveraendert
    Invoke-Check 'S21' 'Nach Neustart: Dokument-Download SHA-256 identisch' {
        if (-not $script:Ctx.ContainsKey('doc_id')) { throw 'NOTRUN: kein Upload vorhanden.' }
        $h = Test-DocDownload 'download-run2.pdf'
        "sha256=$h"
    }

    # S22/S23 bewusst NICHT automatisiert
    Skip-Check 'S22' 'Restore (inkl. Neustart, Dateisperren bei offener DB)' 'Nicht automatisiert: Restore ersetzt die laufende DB-Datei; Dateisperren unter Windows sind Kernrisiko -> manuell nach docs/WINDOWS_TESTPLAN.md (WIN-BR-*).'
    Skip-Check 'S23' 'pywebview-Fenster, DPI, Dialoge, Download im Fenster' 'Nicht automatisierbar in diesem Skript (--browser-Modus) -> manuell nach docs/WINDOWS_TESTPLAN.md.'
}
catch {
    $exitCode = 2
    Add-Result 'SCRIPT' 'Skriptabbruch' 'fail' $_.Exception.Message 0
}
finally {
    try { Stop-Server } catch { Write-Host "Warnung: Server konnte nicht beendet werden: $($_.Exception.Message)" }
    foreach ($n in $script:SavedEnv.Keys) { [Environment]::SetEnvironmentVariable($n, $script:SavedEnv[$n]) }
    if ($null -eq $envInfo) { try { $envInfo = Get-EnvInfo } catch { $envInfo = @{ note = 'Umgebungsinfo nicht ermittelbar' } } }
    try { Write-ResultFile $envInfo } catch { Write-Host "FEHLER beim Schreiben der Ergebnisdatei: $($_.Exception.Message)"; $exitCode = 2 }
    if ($Cleanup) {
        # nur der eigene Laufordner, nur unter TEMP, nur mit passendem Praefix
        $leaf = Split-Path -Leaf $RunDir
        if ($RunDir.StartsWith($TempRoot, [System.StringComparison]::OrdinalIgnoreCase) -and $leaf -like 'leventum-smoke-*') {
            Remove-Item -LiteralPath $RunDir -Recurse -Force -ErrorAction SilentlyContinue
        }
    } else {
        Write-Host "Laufordner (Daten, Logs) bleibt bestehen: $RunDir  (-Cleanup loescht ihn)"
    }
}

$failed = @($script:Results | Where-Object { $_.status -eq 'fail' }).Count
$notrun = @($script:Results | Where-Object { $_.status -eq 'not-run' }).Count
Write-Host ("Zusammenfassung: fail={0}, not-run={1} (not-run ist NICHT bestanden)" -f $failed, $notrun)
if ($exitCode -eq 0 -and $failed -gt 0) { $exitCode = 1 }
exit $exitCode
