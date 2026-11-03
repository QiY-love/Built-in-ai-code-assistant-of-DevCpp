@echo off
rem ccode launcher -- runs with pythonw so no console window pops up.
rem Dev-C++ Tools menu and the global hotkey both point at this file.
setlocal
set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"
start "" "%PYW%" "%~dp0ccode.py" %*
endlocal
