@echo off
setlocal EnableExtensions
cd /d "%~dp0"
title DS4 Bridge - Gerar executavel
set "PY=%~dp0.venv\Scripts\python.exe"

if not exist "%PY%" (
    echo ERRO: execute instalar.bat uma vez antes de criar o EXE.
    pause
    exit /b 1
)
if not exist "%~dp0instalar_drivers.ps1" (
    echo ERRO: instalar_drivers.ps1 nao foi encontrado na pasta do projeto.
    pause
    exit /b 1
)
if not exist "DS4Bridge.pyw" (
    echo ERRO: o arquivo DS4Bridge.pyw nao foi encontrado nesta pasta.
    pause
    exit /b 1
)

rem Inclui as duas DLLs nativas para o vgamepad no Windows.
set "DLL64=%~dp0.venv\Lib\site-packages\vgamepad\win\vigem\client\x64\ViGEmClient.dll"
set "DLL86=%~dp0.venv\Lib\site-packages\vgamepad\win\vigem\client\x86\ViGEmClient.dll"
if not exist "%DLL64%" goto sem_dll
if not exist "%DLL86%" goto sem_dll

echo.
echo Instalando ou atualizando PyInstaller...
"%PY%" -m pip install --upgrade "pyinstaller>=6.17,<8"
if errorlevel 1 goto falha

echo.
echo Criando EXE com ViGEmClient.dll (x64 e x86)...
echo Os arquivos do aplicativo serao empacotados sem alterar o driver instalado.
"%PY%" -m PyInstaller ^
    --onefile ^
    --windowed ^
    --clean ^
    --noconfirm ^
    --name DS4Bridge ^
    --collect-all customtkinter ^
    --collect-all vgamepad ^
    --add-data "%~dp0instalar_drivers.ps1;." ^
    --hidden-import vgamepad ^
    --hidden-import hid ^
    --add-binary "%DLL64%;vgamepad/win/vigem/client/x64" ^
    --add-binary "%DLL86%;vgamepad/win/vigem/client/x86" ^
    --distpath "%CD%" ^
    --workpath "%TEMP%\DS4Bridge_build" ^
    --specpath "%TEMP%\DS4Bridge_spec" ^
    "DS4Bridge.pyw"
if errorlevel 1 goto falha
if not exist "DS4Bridge.exe" goto falha

echo.
echo SUCESSO: DS4Bridge.exe atualizado nesta pasta.
echo Abra o EXE e teste a conversao Xbox.
echo O driver ViGEmBus precisa continuar instalado no Windows.
pause
exit /b 0

:sem_dll
echo.
echo ERRO: a biblioteca ViGEmClient.dll nao foi encontrada no vgamepad.
echo Execute instalar.bat para conferir as dependencias.
pause
exit /b 1

:falha
echo.
echo ERRO: o EXE nao foi gerado. Confira a mensagem acima.
pause
exit /b 1
