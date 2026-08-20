; Script do Inno Setup para o instalador do IG-Scraper Pro.
;
; Pre-requisito: ja ter rodado build_windows.bat (precisa existir
; dist\IGScraperPro.exe).
;
; Como gerar o instalador:
;   1. Baixe e instale o Inno Setup (gratis): https://jrsoftware.org/isdl.php
;   2. Abra este arquivo (installer.iss) no Inno Setup Compiler
;   3. Clique em "Compile" (ou Build > Compile)
;   4. O instalador fica em packaging\windows\output\IGScraperPro-Setup.exe
;
; Da pra abrir o Inno Setup Compiler e mandar compilar direto por linha
; de comando tambem:
;   "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" packaging\windows\installer.iss

#define MyAppName "IG-Scraper Pro"
#define MyAppVersion "4.0"
#define MyAppExeName "IGScraperPro.exe"

[Setup]
AppId={{8F3C2B4E-9A1D-4E7F-B6C0-5D2A1F9E7C33}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
DefaultDirName={autopf}\IGScraperPro
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
OutputDir=output
OutputBaseFilename=IGScraperPro-Setup
Compression=lzma2
SolidCompression=yes
SetupIconFile=icon.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
ArchitecturesInstallIn64BitMode=x64
PrivilegesRequired=lowest

[Languages]
Name: "brazilianportuguese"; MessagesFile: "compiler:Languages\BrazilianPortuguese.isl"

[Tasks]
Name: "desktopicon"; Description: "Criar atalho na Area de Trabalho"; GroupDescription: "Atalhos adicionais:"

[Files]
Source: "..\..\dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"
Name: "{group}\Desinstalar {#MyAppName}"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "Abrir {#MyAppName} agora"; Flags: nowait postinstall skipifsilent
