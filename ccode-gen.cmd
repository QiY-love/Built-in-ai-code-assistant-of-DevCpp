@echo off
rem ccode generate -- Dev-C++ Tools menu entry
setlocal
set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"
start "" "%PYW%" "%~dp0ccode.py" gen
endlocal
