@echo off
REM ==== Build TDA.exe and the installer on Windows ====
REM Requirements: Python 3.10+ (python.org), optional Inno Setup 6 for the installer.
cd /d "%~dp0"
python -m pip install --upgrade pip
python -m pip install -r requirements.txt pyinstaller || goto :err

python -m PyInstaller --noconfirm --clean --windowed --name TDA ^
  --icon assets\tda.ico --add-data "assets;assets" ^
  --exclude-module tkinter main.py || goto :err

echo.
echo Program built in: dist\TDA\TDA.exe

set ISCC="%ProgramFiles(x86)%\Inno Setup 6\ISCC.exe"
if exist %ISCC% (
  %ISCC% installer\TDA.iss || goto :err
  echo Installer built in: dist\
) else (
  echo Inno Setup 6 not found - skipping installer. Get it from https://jrsoftware.org/isdl.php
)
pause
exit /b 0
:err
echo BUILD FAILED
pause
exit /b 1
