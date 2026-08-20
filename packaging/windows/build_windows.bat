@echo off
REM ============================================================
REM  IG-Scraper Pro - build do .exe desktop (rodar no Windows)
REM
REM  Uso: da RAIZ do repositorio (a pasta com app.py, desktop.py),
REM  de dois cliques neste arquivo ou rode pelo terminal:
REM      packaging\windows\build_windows.bat
REM
REM  Precisa de Python 3.10+ instalado (python.org, marque "Add to PATH"
REM  na instalacao). So precisa fazer isso UMA VEZ por maquina -- depois
REM  o IGScraperPro.exe gerado funciona sozinho, sem precisar de Python.
REM ============================================================

setlocal
cd /d "%~dp0..\.."

echo.
echo [1/4] Criando ambiente virtual (venv)...
python -m venv .venv-build
if errorlevel 1 (
    echo ERRO: nao achei o Python. Instale em https://python.org e marque "Add python.exe to PATH".
    pause
    exit /b 1
)
call .venv-build\Scripts\activate.bat

echo.
echo [2/4] Instalando dependencias (isso pode demorar alguns minutos)...
python -m pip install --upgrade pip >nul
pip install -r requirements.txt
pip install -r requirements-desktop.txt

echo.
echo [3/4] Empacotando com PyInstaller...
pyinstaller packaging\windows\igscraper.spec --noconfirm --clean

echo.
echo [4/4] Pronto!
echo O aplicativo esta em: dist\IGScraperPro.exe
echo.
echo Voce ja pode dar 2 cliques nele para abrir o app.
echo Para criar um instalador de verdade (icone na area de trabalho,
echo desinstalador, etc), veja packaging\windows\README.md
echo.
pause
