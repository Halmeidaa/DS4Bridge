@echo off
setlocal EnableExtensions
set "BASE=%~dp0"
cd /d "%BASE%"
set "PYW=%BASE%.venv\Scripts\pythonw.exe"
if not exist "%BASE%DS4Bridge.pyw" (
    echo ERRO: DS4Bridge.pyw nao esta nesta pasta.
    pause
    exit /b 1
)
if not exist "%PYW%" (
    echo ERRO: primeira instalacao ainda nao realizada.
    echo Execute instalar.bat uma unica vez. Depois use Iniciar.bat.
    pause
    exit /b 1
)
start "" "%PYW%" "%BASE%DS4Bridge.pyw"
if errorlevel 1 (
    echo Falha ao abrir o Python do DS4 Bridge.
    pause
    exit /b 1
)
exit /b 0
