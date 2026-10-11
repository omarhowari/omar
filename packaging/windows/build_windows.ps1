# Build TDA on Windows (Visual Studio / Developer PowerShell):  portable folder + TDA-Setup.exe
#   needs: Python 3.10+ (any, only used to download/unpack), Visual Studio "Desktop development with C++"
#          (or MinGW gcc in PATH), NSIS 3 (https://nsis.sourceforge.io)
#   usage: powershell -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1 [-Out dist]
param([string]$Out = "")
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path "$PSScriptRoot\..\..").Path
if (-not $Out) { $Out = Join-Path $Root "dist" }
New-Item -ItemType Directory -Force $Out | Out-Null
$Out = (Resolve-Path $Out).Path
$App = Join-Path $Out "TDA"

if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 "$Root\packaging\windows\assemble.py" $Out }
else { & python "$Root\packaging\windows\assemble.py" $Out }
if ($LASTEXITCODE) { throw "assemble failed" }

# --- launcher TDA.exe
$B = Join-Path $Out "build"; New-Item -ItemType Directory -Force $B | Out-Null
Copy-Item "$Root\packaging\windows\launcher.c","$Root\packaging\windows\launcher.rc","$Root\packaging\windows\app.manifest","$Root\assets\tda.ico" $B -Force
Push-Location $B
try {
  $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
  if (-not $cl) {
    # find Visual Studio and load its x64 compiler environment
    $vswhere = "${env:ProgramFiles(x86)}\Microsoft Visual Studio\Installer\vswhere.exe"
    if (Test-Path $vswhere) {
      $vs = & $vswhere -latest -products * -requires Microsoft.VisualStudio.Component.VC.Tools.x86.x64 -property installationPath
      if ($vs) {
        $bat = Join-Path $vs "VC\Auxiliary\Build\vcvars64.bat"
        cmd /c "`"$bat`" >nul && set" | ForEach-Object { if ($_ -match "^(.*?)=(.*)$") { Set-Item "env:$($matches[1])" $matches[2] } }
        $cl = Get-Command cl.exe -ErrorAction SilentlyContinue
      }
    }
  }
  if ($cl) {
    rc.exe /nologo /fo res.res launcher.rc
    cl.exe /nologo /O2 /MT /DUNICODE /D_UNICODE launcher.c res.res /Fe:"$App\TDA.exe" /link /SUBSYSTEM:WINDOWS shell32.lib user32.lib
  } elseif (Get-Command gcc -ErrorAction SilentlyContinue) {
    windres launcher.rc -O coff -o res.o
    gcc -O2 -municode -mwindows -static -o "$App\TDA.exe" launcher.c res.o -lshell32
  } else { throw "No C compiler: install Visual Studio 'Desktop development with C++' or MinGW." }
  if (-not (Test-Path "$App\TDA.exe")) { throw "launcher build failed" }
} finally { Pop-Location }

# --- portable zip + installer
$zip = Join-Path $Out "TDA-portable.zip"
if (Test-Path $zip) { Remove-Item $zip }
Compress-Archive -Path $App -DestinationPath $zip
$nsis = @("${env:ProgramFiles(x86)}\NSIS\makensis.exe", "$env:ProgramFiles\NSIS\makensis.exe") | Where-Object { Test-Path $_ } | Select-Object -First 1
if (-not $nsis) { $c = Get-Command makensis -ErrorAction SilentlyContinue; if ($c) { $nsis = $c.Source } }
if ($nsis) {
  & $nsis -V2 "-DSRC=$App" "-DOUTFILE=$Out\TDA-Setup.exe" "-DICON=$Root\assets\tda.ico" "-DLICENSE=$Root\LICENSE" "$Root\packaging\windows\installer.nsi"
  if ($LASTEXITCODE) { throw "NSIS failed" }
  Write-Host "`nInstaller: $Out\TDA-Setup.exe" -ForegroundColor Green
} else {
  Write-Host "NSIS not found - portable folder only ($App). Get NSIS from https://nsis.sourceforge.io" -ForegroundColor Yellow
}
