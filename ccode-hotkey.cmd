@echo off
rem ccode-hotkey launcher -- window-scoped hotkey guard for Dev-C++
rem Ctrl+I works only when Dev-C++ is the foreground window.
setlocal
set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"
start "" "%PYW%" "%~dp0ccode-hotkey.py"
endlocal
