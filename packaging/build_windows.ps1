<#
Leventum - Windows-Build (PyInstaller + Inno Setup).
STATUS: UNGETESTET - unter Linux erstellt, nie unter Windows ausgefuehrt. Ein Linux-Lauf des PyInstaller-Specs ist belegt, dieses Skript nicht.
Voraussetzungen: Python 3.12/3.13 (64 Bit), Node.js 20+, Inno Setup 6 (ISCC.exe). Aufruf im Repo-Wurzelordner:
  powershell -ExecutionPolicy Bypass -File packaging\build_windows.ps1
Ergebnis: build\dist\Leventum\ (gebuendeltes Programm), build\installer\Leventum_Setup.exe, SHA-256 in build\installer\SHA256.txt
#>
[CmdletBinding()]
param([string]$PythonExe = 'python', [string]$Iscc = '')
Set-StrictMode -Version 2.0
$ErrorActionPreference = 'Stop'
$root = Split-Path -Parent $PSScriptRoot
Set-Location $root
function Run($exe, $arguments) { & $exe @arguments; if ($LASTEXITCODE -ne 0) { throw "Fehlgeschlagen ($LASTEXITCODE): $exe $arguments" } }

$version = (& $PythonExe -c "import re,pathlib;print(re.search(r'__version__ = .(.+?).', pathlib.Path('backend/leventum/__init__.py').read_text()).group(1))").Trim()
Write-Host "Version: $version"

Push-Location frontend; Run 'npm' @('ci'); Run 'npm' @('run', 'build'); Pop-Location

$venv = Join-Path $root 'build\venv'
if (Test-Path $venv) { Remove-Item -Recurse -Force $venv }
Run $PythonExe @('-m', 'venv', $venv)
$py = Join-Path $venv 'Scripts\python.exe'
Run $py @('-m', 'pip', 'install', '--upgrade', 'pip')
Run $py @('-m', 'pip', 'install', ".\backend[desktop]", 'pyinstaller')

$work = Join-Path $root 'build\work'; $dist = Join-Path $root 'build\dist'
Run $py @('-m', 'PyInstaller', 'packaging\leventum.spec', '--noconfirm', '--workpath', $work, '--distpath', $dist)

if (-not $Iscc) {
  $cand = @("$env:LOCALAPPDATA\Programs\Inno Setup 6\ISCC.exe", "${env:ProgramFiles(x86)}\Inno Setup 6\ISCC.exe", "$env:ProgramFiles\Inno Setup 6\ISCC.exe") | Where-Object { Test-Path $_ }
  if (-not $cand) { throw 'ISCC.exe (Inno Setup 6) nicht gefunden - mit -Iscc <Pfad> angeben.' }
  $Iscc = @($cand)[0]
}
Run $Iscc @("/DAppVersion=$version", 'packaging\leventum.iss')
$setup = Join-Path $root 'build\installer\Leventum_Setup.exe'
(Get-FileHash $setup -Algorithm SHA256).Hash + '  Leventum_Setup.exe' | Set-Content -Encoding ascii (Join-Path $root 'build\installer\SHA256.txt')
Write-Host "Fertig: $setup"
