@echo off
REM ============================================================
REM  IG-Scraper Pro - ATUALIZAR o aplicativo (1 clique)
REM
REM  Baixa a versao mais nova do codigo e gera um IGScraperPro.exe
REM  atualizado. Use este arquivo sempre que houver novidades.
REM
REM  Funciona de dois jeitos, automaticamente:
REM   - se a pasta veio de "git clone", usa git pull
REM   - se veio de um ZIP do GitHub (ou nao tem git instalado),
REM     baixa o ZIP novo sozinho, sem precisar de git
REM
REM  De 2 cliques neste arquivo. So isso.
REM ============================================================

REM O proprio ATUALIZAR.bat e trocado durante a atualizacao, e o Windows
REM se perde se o arquivo muda enquanto roda -- entao ele se copia pra
REM pasta temporaria e roda de la, deixando o original livre pra trocar.
if not "%IGS_COPIA_TEMP%"=="1" (
    set "IGS_COPIA_TEMP=1"
    set "IGS_PASTA_APP=%~dp0"
    copy /Y "%~f0" "%TEMP%\igscraper_atualizar.bat" >nul
    call "%TEMP%\igscraper_atualizar.bat"
    exit /b
)

setlocal enabledelayedexpansion
cd /d "%IGS_PASTA_APP%"
title Atualizando IG-Scraper Pro

set "BRANCH=claude/app-bugs-74wsl2"
set "REPOURL=https://github.com/anderson17quadri-cmd/Scraper.git"
set "ZIPURL=https://github.com/anderson17quadri-cmd/Scraper/archive/refs/heads/%BRANCH%.zip"
set "ZIPDIR=Scraper-claude-app-bugs-74wsl2"

echo.
echo  ============================================
echo    IG-Scraper Pro - Atualizacao
echo  ============================================
echo.

REM O PyInstaller nao consegue sobrescrever o .exe se ele estiver aberto.
echo [1/4] Fechando o app, se estiver aberto...
taskkill /IM IGScraperPro.exe /F >nul 2>&1

echo [2/4] Baixando a versao mais nova do codigo...
REM Usa sempre o endereco certo do repositorio (nao o "origin" da pasta,
REM que pode apontar pra outro lugar se ela veio de um clone antigo). Se
REM o git falhar por qualquer motivo (sem git, historico diferente,
REM arquivo mexido na mao...), cai pro download do ZIP, que sempre funciona.
set "BAIXOU="
if exist ".git" (
    git pull --no-edit "%REPOURL%" %BRANCH% && set "BAIXOU=1"
    if not defined BAIXOU echo       Git nao conseguiu atualizar, baixando pelo ZIP...
)
if not defined BAIXOU (
    call :baixar_zip
    if errorlevel 1 goto :erro_download
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
set "APPFINAL=%CD%\dist\IGScraperPro.exe"
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
goto :fim


REM ---------- baixa e aplica o ZIP do GitHub (sem precisar de git) ----------
:baixar_zip
set "TMPZIP=%TEMP%\igscraper_update.zip"
set "TMPDIR=%TEMP%\igscraper_update"

if exist "%TMPDIR%" rd /s /q "%TMPDIR%" >nul 2>&1
if exist "%TMPZIP%" del /q "%TMPZIP%" >nul 2>&1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; [Net.ServicePointManager]::SecurityProtocol=[Net.SecurityProtocolType]::Tls12; Invoke-WebRequest -Uri '%ZIPURL%' -OutFile '%TMPZIP%' -UseBasicParsing"
if errorlevel 1 exit /b 1

powershell -NoProfile -ExecutionPolicy Bypass -Command ^
  "$ErrorActionPreference='Stop'; Expand-Archive -Path '%TMPZIP%' -DestinationPath '%TMPDIR%' -Force"
if errorlevel 1 exit /b 1

if not exist "%TMPDIR%\%ZIPDIR%\app.py" (
    echo  ERRO: o conteudo baixado nao parece o esperado.
    exit /b 1
)

REM copia o codigo novo por cima. Nao mexe em .venv-build, dist\ nem
REM nos seus dados (que ficam em %LOCALAPPDATA%\IGScraperPro).
robocopy "%TMPDIR%\%ZIPDIR%" "%CD%" /E /IS /IT /NFL /NDL /NJH /NJS /NP >nul
if errorlevel 8 exit /b 1

rd /s /q "%TMPDIR%" >nul 2>&1
del /q "%TMPZIP%" >nul 2>&1
echo       Codigo atualizado com sucesso.
exit /b 0


:erro_download
echo.
echo  ERRO ao baixar a versao nova.
echo  Verifique sua conexao com a internet e tente de novo.
echo.
pause
exit /b 1

:fim
echo.
pause
