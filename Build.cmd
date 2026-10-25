@echo off
setlocal DisableDelayedExpansion
rem Developer build entry point. Default: distribute the complete folder/ZIP.
rem Pass --mode onefile to build the optional single EXE instead.
rem The generated EXE uses the bundled v241-first policy, then latest fallback.
if not defined WBEX_PYTHON goto discover
set "WBEX_UPDATER_BUILD_PYTHON=%WBEX_PYTHON:"=%"
:trim_python_left
if not "%WBEX_UPDATER_BUILD_PYTHON:~0,1%"==" " goto trim_python_right
set "WBEX_UPDATER_BUILD_PYTHON=%WBEX_UPDATER_BUILD_PYTHON:~1%"
goto trim_python_left
:trim_python_right
if not "%WBEX_UPDATER_BUILD_PYTHON:~-1%"==" " goto launch
set "WBEX_UPDATER_BUILD_PYTHON=%WBEX_UPDATER_BUILD_PYTHON:~0,-1%"
goto trim_python_right

:discover
rem Select an installed Python that already has PyInstaller and Tcl/Tk.
for /f "usebackq delims=" %%P in (`powershell.exe -NoLogo -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='SilentlyContinue'; $candidates=@(); foreach($name in @('py.exe','python.exe','pyinstaller.exe')){$cmd=Get-Command $name -ErrorAction SilentlyContinue; if($cmd -and $cmd.Source -notlike '*\WindowsApps\*'){if($name -eq 'pyinstaller.exe'){$candidates+=@{Path=(Join-Path (Split-Path (Split-Path $cmd.Source)) 'python.exe');Prefix=@()}}else{$prefix=@();if($name -eq 'py.exe'){$prefix=@('-3')};$candidates+=@{Path=$cmd.Source;Prefix=$prefix}}}}; Get-ChildItem -Path (Join-Path $env:LOCALAPPDATA 'Programs\Python\Python*\python.exe') -ErrorAction SilentlyContinue | Sort-Object FullName -Descending | ForEach-Object {$candidates+=@{Path=$_.FullName;Prefix=@()}}; foreach($item in $candidates){if(Test-Path -LiteralPath $item.Path){$prefix=$item.Prefix;$answer=@(& $item.Path @prefix -c 'import sys, tkinter, PyInstaller; assert sys.version_info >= (3,9); print(sys.executable)' 2>$null);if($LASTEXITCODE -eq 0 -and $answer.Count -gt 0){Write-Output $answer[-1];exit 0}}};exit 1"`) do set "WBEX_UPDATER_BUILD_PYTHON=%%P"
if defined WBEX_UPDATER_BUILD_PYTHON goto launch
echo No build interpreter with Python 3.9+, PyInstaller and Tcl/Tk was found.
echo Developer setup: python -m pip install "pyinstaller>=6.16,<7"
echo Then set WBEX_PYTHON to that python.exe and try again.
echo End users do not need Python; give them the resulting EXE.
if "%~1"=="" pause
exit /b 1

:launch
echo Generated updater default: Ansys v241 if installed, otherwise newest installed version.
"%WBEX_UPDATER_BUILD_PYTHON%" "%~dp0tools\build_wbex_updater.py" %*
set "WBEX_UPDATER_BUILD_STATUS=%errorlevel%"
if "%~1"=="" pause
exit /b %WBEX_UPDATER_BUILD_STATUS%
