@echo off
setlocal DisableDelayedExpansion
rem GUI on double-click; any arguments are forwarded to the command-line updater.
set "WBEX_UPDATER_MODE=gui"
if not "%~1"=="" set "WBEX_UPDATER_MODE=cli"
set "WBEX_UPDATER_PYTHON="

rem An explicit interpreter must work even if PowerShell probing is unavailable.
if not defined WBEX_PYTHON goto discover
set "WBEX_UPDATER_PYTHON=%WBEX_PYTHON:"=%"
:trim_python_left
if not "%WBEX_UPDATER_PYTHON:~0,1%"==" " goto trim_python_right
set "WBEX_UPDATER_PYTHON=%WBEX_UPDATER_PYTHON:~1%"
goto trim_python_left
:trim_python_right
if not "%WBEX_UPDATER_PYTHON:~-1%"==" " goto probe_configured
set "WBEX_UPDATER_PYTHON=%WBEX_UPDATER_PYTHON:~0,-1%"
goto trim_python_right
:probe_configured
echo Checking configured Python: "%WBEX_UPDATER_PYTHON%"
"%WBEX_UPDATER_PYTHON%" -c "import sys; print(sys.version); sys.exit(0 if sys.version_info >= (3, 9) else 1)"
if errorlevel 1 (
  echo The configured WBEX_PYTHON could not run Python 3.9+.
  echo Check the path and the error above. No automatic interpreter was substituted.
  pause
  exit /b 1
)
if "%WBEX_UPDATER_MODE%"=="cli" goto launch
"%WBEX_UPDATER_PYTHON%" -c "import tkinter"
if errorlevel 1 (
  echo The configured Python runs, but tkinter could not be imported.
  echo Repair Python with the tcl/tk and IDLE component, or use command-line mode.
  pause
  exit /b 1
)
goto launch

:discover
rem Probe candidates instead of trusting the Windows Store Python alias.
rem User input is never inserted into this PowerShell program.
for /f "usebackq delims=" %%P in (`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue'; $candidates=@(); if($env:WBEX_PYTHON){$candidates+=@{Path=$env:WBEX_PYTHON;Prefix=@()}}; foreach($name in @('py.exe','python.exe')){$cmd=Get-Command $name -ErrorAction SilentlyContinue; if($cmd -and $cmd.Source -notlike '*\WindowsApps\*'){$prefix=@(); if($name -eq 'py.exe'){$prefix=@('-3')}; $candidates+=@{Path=$cmd.Source;Prefix=$prefix}}}; foreach($item in (Get-ChildItem Env:AWP_ROOT*)){Get-ChildItem -LiteralPath (Join-Path $item.Value 'commonfiles\CPython') -Filter python.exe -Recurse -ErrorAction SilentlyContinue | ForEach-Object {$candidates+=@{Path=$_.FullName;Prefix=@()}}}; foreach($base in @($env:ProgramFiles,$env:ProgramW6432) | Select-Object -Unique){if($base){Get-ChildItem -Path (Join-Path $base 'ANSYS Inc\v*\commonfiles\CPython\*\winx64\Release\python\python.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object {$candidates+=@{Path=$_.FullName;Prefix=@()}}}}; $probe='import sys;assert sys.version_info>=(3,9);print(sys.executable)'; if($env:WBEX_UPDATER_MODE -eq 'gui'){$probe='import tkinter;'+$probe}; foreach($item in $candidates){if(Test-Path -LiteralPath $item.Path){$prefix=$item.Prefix; $answer=@(& $item.Path @prefix -c $probe 2>$null); if($LASTEXITCODE -eq 0 -and $answer.Count -gt 0){Write-Output $answer[-1];exit 0}}}; exit 1"`) do set "WBEX_UPDATER_PYTHON=%%P"

if not defined WBEX_UPDATER_PYTHON (
  echo No suitable Python 3.9+ was found.
  echo GUI mode also requires tkinter. Install Python from python.org,
  echo or set WBEX_PYTHON to a working python.exe path and try again.
  pause
  exit /b 1
)

:launch
if "%WBEX_UPDATER_MODE%"=="cli" goto cli

for %%D in ("%WBEX_UPDATER_PYTHON%") do set "WBEX_UPDATER_PYTHONW=%%~dpDpythonw.exe"
if exist "%WBEX_UPDATER_PYTHONW%" (
  start "" "%WBEX_UPDATER_PYTHONW%" "%~dp0tools\wbex_updater_gui.py"
  exit /b 0
)
"%WBEX_UPDATER_PYTHON%" "%~dp0tools\wbex_updater_gui.py"
if errorlevel 1 pause
exit /b %errorlevel%

:cli
"%WBEX_UPDATER_PYTHON%" -u "%~dp0tools\update_wbex.py" %*
exit /b %errorlevel%
