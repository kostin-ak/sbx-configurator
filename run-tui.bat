@echo off
rem Run the sbx TUI from this checkout.
rem Prefers a Windows virtualenv, falls back to the WSL virtualenv.
setlocal EnableExtensions EnableDelayedExpansion

set "ROOT=%~dp0"
cd /d "%ROOT%"

if exist "%ROOT%.venv\Scripts\python.exe" (
    "%ROOT%.venv\Scripts\python.exe" -m sbx.tui %*
    exit /b %ERRORLEVEL%
)

where wsl >nul 2>&1
if errorlevel 1 goto :noenv
if not defined WSL_DISTRO set "WSL_DISTRO=archlinux"

rem Convert F:\Files\project\router-vpn\ to /mnt/f/Files/project/router-vpn
set "DRIVE=%ROOT:~0,1%"
for %%a in (a b c d e f g h i j k l m n o p q r s t u v w x y z) do if /i "%DRIVE%"=="%%a" set "DRIVE=%%a"
set "REST=%ROOT:~2%"
set "REST=%REST:\=/%"
set "WSLROOT=/mnt/%DRIVE%%REST%"
if "%WSLROOT:~-1%"=="/" set "WSLROOT=%WSLROOT:~0,-1%"

wsl -d %WSL_DISTRO% -- bash -lc "test -x '%WSLROOT%/.venv-wsl/bin/python'"
if errorlevel 1 goto :tryplain

wsl -d %WSL_DISTRO% -- bash -lc "cd '%WSLROOT%' && exec ./.venv-wsl/bin/python -m sbx.tui %*"
exit /b %ERRORLEVEL%

:tryplain
wsl -d %WSL_DISTRO% -- bash -lc "test -x '/usr/bin/python3'"
if errorlevel 1 goto :noenv
wsl -d %WSL_DISTRO% -- bash -lc "cd '%WSLROOT%' && exec python3 -m sbx.tui %*"
exit /b %ERRORLEVEL%

:noenv
echo.
echo [run-tui] No runnable environment found.
echo.
echo   Windows:  python -m venv .venv
echo             .venv\Scripts\pip install -e ".[tui,router]"
echo.
echo   WSL:      wsl -d archlinux -- bash -lc "cd %WSLROOT% && .venv-wsl/bin/pip install -e '.[tui,router]'"
echo.
if "%~1"=="" pause
exit /b 1