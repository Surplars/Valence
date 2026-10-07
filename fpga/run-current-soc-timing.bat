@echo off
setlocal
if "%~1"=="" goto usage
set "PART=%~1"
set "PERIOD=%~2"
if "%PERIOD%"=="" set "PERIOD=10"
set "TOP=%~3"
if "%TOP%"=="" set "TOP=CurrentSocTimingTop"
cd /d "%~dp0"
where vivado.bat >nul 2>&1
if errorlevel 1 (
    echo Vivado is not on PATH. Open the Vivado Tcl Shell and retry.
    exit /b 1
)
call vivado.bat -mode batch -source vivado-ooc.tcl -tclargs . "%PART%" "%PERIOD%" "%TOP%"
exit /b %ERRORLEVEL%

:usage
echo Usage: run-current-soc-timing.bat FULL_PART [PERIOD_NS] [CurrentSocTimingTop^|CompactSocTimingTop]
echo Find FULL_PART in Vivado Tcl Shell with: get_parts *xczu15eg*
exit /b 2
