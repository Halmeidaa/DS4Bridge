@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DS4 Bridge - Instalacao inicial

echo ===========================================
echo   DS4 BRIDGE 2.2.1 - INSTALACAO (1 VEZ)
echo ===========================================
echo.

set "VENV=%~dp0.venv"
set "PY=%VENV%\Scripts\python.exe"
if not exist "%PY%" (
    echo [1/2] Criando ambiente Python exclusivo do DS4 Bridge...
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
echo [2/2] Conferindo bibliotecas do projeto...
"%PY%" -m pip install -r "%~dp0requirements.txt"
if errorlevel 1 (
    echo.
    echo FALHA: a instalacao nao terminou. Verifique a conexao e o antivirus.
    pause
    exit /b 1
)
echo.
echo Instalacao concluida. Nas proximas vezes, abra INICIAR.bat
 echo ou INICIAR.vbs. Nao precisa reinstalar os pacotes.
echo.
pause
exit /b 0
