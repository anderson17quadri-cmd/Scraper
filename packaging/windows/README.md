# IG-Scraper Pro — build desktop (Windows)

Transforma o app numa janela de verdade: sem terminal, sem abrir
navegador manualmente. So dar 2 cliques.

## Passo 1 — gerar o .exe (uma vez só)

Pré-requisito: Python 3.10+ instalado ([python.org](https://python.org),
marque **"Add python.exe to PATH"** na instalação).

Na pasta raiz do projeto (onde estão `app.py`, `desktop.py`), dê 2 cliques em:

```
packaging\windows\build_windows.bat
```

Isso vai:
1. Criar um ambiente virtual (`.venv-build`)
2. Instalar as dependências (instagrapi, flask, pywebview, etc.)
3. Empacotar tudo com o PyInstaller

Ao final, o app está pronto em `dist\IGScraperPro.exe` — já pode dar
2 cliques nele e abrir a janela do app.

Esse processo demora alguns minutos (principalmente a instalação das
dependências). Só precisa fazer de novo se você mudar o código.

## Passo 2 — instalador de verdade (opcional, recomendado)

Se você quiser um instalador com ícone na Área de Trabalho, entrada no
Menu Iniciar e desinstalador (em vez de só copiar o .exe manualmente):

1. Instale o [Inno Setup](https://jrsoftware.org/isdl.php) (gratuito)
2. Abra `packaging\windows\installer.iss` no Inno Setup Compiler
3. Clique em **Compile**
4. O instalador final fica em `packaging\windows\output\IGScraperPro-Setup.exe`

Rode esse instalador — ele copia o app pra
`%LOCALAPPDATA%\IGScraperPro`, cria os atalhos e não precisa de admin.

## Onde ficam os dados

Contas, alvos, sessões e os downloads ficam salvos em:

```
%LOCALAPPDATA%\IGScraperPro\
```

(normalmente algo como `C:\Users\SeuNome\AppData\Local\IGScraperPro`).
Isso é intencional — a pasta de instalação (`Program Files`) não é
gravável sem admin, então os dados vivem separados, na pasta do usuário.

## Se o build falhar

O erro mais comum é algum `ModuleNotFoundError` na primeira vez que o
`.exe` roda (o PyInstaller não detectou automaticamente alguma
dependência interna do instagrapi/pydantic/Pillow). Copie a mensagem de
erro completa e me manda — eu adiciono o módulo que faltou em
`hiddenimports` no `igscraper.spec` e você reconstrói.

## Atualizando o app depois

Sempre que eu mandar código novo (`git pull`), repete o **Passo 1**
(rodar `build_windows.bat` de novo) pra gerar um `.exe` atualizado. Se
você já tem o instalador, repete o **Passo 2** também para gerar um
novo instalador.
