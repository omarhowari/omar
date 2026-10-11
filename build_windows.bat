@echo off
REM ==== Build TDA (portable folder + TDA-Setup.exe) on Windows ====
REM Needs: Python 3.10+, Visual Studio with "Desktop development with C++" (or MinGW), NSIS 3.
cd /d "%~dp0"
powershell -NoProfile -ExecutionPolicy Bypass -File packaging\windows\build_windows.ps1 -Out dist
if errorlevel 1 (echo BUILD FAILED & pause & exit /b 1)
echo.
echo Done: dist\TDA-Setup.exe
pause
