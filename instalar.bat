@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DS4 Bridge - Instalacao inicial

echo ===========================================
echo   DS4 BRIDGE 2.2.6 - INSTALACAO (1 VEZ)
echo ===========================================
echo.

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" (
    echo [1/3] Criando ambiente Python exclusivo do DS4 Bridge...
    py -3 --version >nul 2>&1
    if not errorlevel 1 (
        py -3 -m venv "%VENV%"
    ) else (
        python --version >nul 2>&1
        if errorlevel 1 (
            echo ERRO: Python nao encontrado. Instale Python 3.11 ou superior.
            pause
            exit /b 1
        )
        python -m venv "%VENV%"
    )
    if errorlevel 1 (
        echo ERRO: Nao foi possivel criar o ambiente Python.
        pause
        exit /b 1
    )
)
if not exist "%PY%" (
    echo ERRO: Python nao localizado dentro de .venv\Scripts.
    pause
    exit /b 1
)
echo [2/3] Conferindo bibliotecas do projeto...
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo FALHA: a instalacao nao terminou. Verifique a conexao e o antivirus.
    pause
    exit /b 1
)
echo.
echo [3/3] Conferindo drivers (ViGEmBus e HidHide)...
echo.
where powershell.exe >nul 2>&1
if errorlevel 1 (
    echo AVISO: PowerShell nao encontrado. Drivers devem ser instalados manualmente.
) else (
    powershell.exe -NoProfile -ExecutionPolicy Bypass -File "%~dp0instalar_drivers.ps1"
    if errorlevel 1 echo AVISO: confira a instalacao dos drivers.
)
echo.
echo Instalacao concluida. Nas proximas vezes, abra Iniciar.bat.
echo Para gerar DS4Bridge.exe, execute criar_exe.bat.
echo.
pause
exit /b 0
