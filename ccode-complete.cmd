@echo off
rem ccode complete -- Dev-C++ Tools menu entry
setlocal
set "PYW=pythonw"
where pythonw >nul 2>nul || set "PYW=python"
start "" "%PYW%" "%~dp0ccode.py" complete
endlocal
