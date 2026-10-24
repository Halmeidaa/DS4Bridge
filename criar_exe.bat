@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DS4 Bridge - Criar EXE Windows
set "PY=%~dp0.venv\Scripts\python.exe"
if not exist "%PY%" (
    echo ERRO: execute instalar.bat uma vez antes de criar o EXE.
    pause
    exit /b 1
)
if not exist "%~dp0DS4Bridge.pyw" (
    echo ERRO: DS4Bridge.pyw nao encontrado.
    pause
    exit /b 1
)
echo.
echo Instalando empacotador PyInstaller (somente para criar o EXE)...
"%PY%" -m pip install --upgrade "pyinstaller>=6.17,<8"
if errorlevel 1 goto falha
echo.
echo Gerando DS4Bridge.exe para este Windows...
"%PY%" -m PyInstaller --onefile --windowed --clean --noconfirm --name "DS4Bridge" --collect-all customtkinter --distpath "%~dp0" --workpath "%TEMP%\DS4Bridge_work" --specpath "%TEMP%\DS4Bridge_spec" "%~dp0DS4Bridge.pyw"
if errorlevel 1 goto falha
if not exist "%~dp0DS4Bridge.exe" goto falha
echo.
echo SUCESSO: DS4Bridge.exe criado nesta mesma pasta.
echo Agora voce pode abrir o EXE por duplo clique sem o Python.
echo O ViGEmBus ainda precisa estar instalado no Windows.
pause
exit /b 0
:falha
echo.
echo ERRO: falha ao criar o EXE. Confira as mensagens acima.
pause
exit /b 1
