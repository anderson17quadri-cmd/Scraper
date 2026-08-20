@echo off
REM ============================================================
REM  IG-Scraper Pro - ATUALIZAR o aplicativo (1 clique)
REM
REM  Baixa a versao mais nova do codigo e gera um IGScraperPro.exe
REM  atualizado. Use este arquivo sempre que houver novidades.
REM
REM  De 2 cliques neste arquivo. So isso.
REM ============================================================

setlocal
cd /d "%~dp0"
title Atualizando IG-Scraper Pro

echo.
echo  ============================================
echo    IG-Scraper Pro - Atualizacao
echo  ============================================
echo.

REM O PyInstaller nao consegue sobrescrever o .exe se ele estiver aberto.
echo [1/4] Fechando o app, se estiver aberto...
taskkill /IM IGScraperPro.exe /F >nul 2>&1

echo [2/4] Baixando a versao mais nova do codigo...
git pull origin claude/app-bugs-74wsl2
if errorlevel 1 (
    echo.
    echo  ERRO ao baixar o codigo novo.
    echo  Se aparecer algo sobre "local changes", rode este comando e tente de novo:
    echo      git checkout -- .
    echo.
    pause
    exit /b 1
)

echo.
echo [3/4] Instalando dependencias e empacotando...
echo       (a primeira vez demora alguns minutos, depois e mais rapido)
echo.
if not exist ".venv-build\Scripts\activate.bat" (
    python -m venv .venv-build
    if errorlevel 1 (
        echo  ERRO: Python nao encontrado. Instale em https://python.org
        echo  e marque "Add python.exe to PATH" durante a instalacao.
        pause
        exit /b 1
    )
)
call .venv-build\Scripts\activate.bat
python -m pip install --upgrade pip >nul 2>&1
pip install -q -r requirements.txt
pip install -q -r requirements-desktop.txt
pyinstaller packaging\windows\igscraper.spec --noconfirm --clean
if errorlevel 1 (
    echo.
    echo  ERRO ao gerar o aplicativo. Copie a mensagem acima e me mande.
    pause
    exit /b 1
)

REM Se o app foi instalado pelo instalador, o atalho da Area de Trabalho
REM aponta pra copia instalada -- sem atualizar ela tambem, o atalho
REM continuaria abrindo a versao antiga.
set "INSTALADO=%LOCALAPPDATA%\Programs\IGScraperPro\IGScraperPro.exe"
set "APPFINAL=dist\IGScraperPro.exe"
if exist "%INSTALADO%" (
    echo       Atualizando tambem a copia instalada...
    copy /Y "dist\IGScraperPro.exe" "%INSTALADO%" >nul
    if not errorlevel 1 set "APPFINAL=%INSTALADO%"
)

echo.
echo [4/4] Pronto! Aplicativo atualizado.
echo.
echo  App atualizado em:  %APPFINAL%
echo.
echo  Suas contas, sessoes e downloads NAO foram apagados --
echo  ficam guardados separado, em %LOCALAPPDATA%\IGScraperPro
echo.

choice /C SN /M "Abrir o aplicativo agora"
if errorlevel 2 goto :fim
start "" "%APPFINAL%"

:fim
echo.
pause
