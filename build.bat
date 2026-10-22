@echo off
REM ===== Build Waraq PDF as a Windows desktop app (folder + WaraqPDF.exe) =====
cd /d "%~dp0"
if not exist .venv (
  py -3 -m venv .venv || python -m venv .venv
)
call .venv\Scripts\activate.bat
python -m pip install --upgrade pip
pip install -r requirements.txt pyinstaller
pyinstaller --noconfirm --clean --windowed --name WaraqPDF ^
  --icon assets\icon.ico ^
  --add-data "assets;assets" ^
  --collect-all pymupdf ^
  --collect-submodules pyhanko --collect-data pyhanko ^
  --collect-submodules pdf2docx ^
  --hidden-import win32com.client ^
  --exclude-module scipy --exclude-module pandas --exclude-module matplotlib --exclude-module onnxruntime --exclude-module tkinter --exclude-module IPython ^
  main.py
echo.
echo Done:  dist\WaraqPDF\WaraqPDF.exe
echo To make an installer, open installer.iss with Inno Setup and press Compile.
pause
