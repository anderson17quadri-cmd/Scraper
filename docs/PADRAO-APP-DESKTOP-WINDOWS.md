# Padrão: transformar um app Flask em instalável de Windows

Referência de como este projeto (IG-Scraper Pro) virou um app desktop
clicável no Windows, pra reaproveitar em outros programas. Quando for
aplicar em outro repositório, é só pedir pra recriar essas mesmas peças
lá (adaptando nomes/paths).

## As duas partes do modelo

### 1. App instalável (sem terminal, um clique)

Peças, todas neste repositório:

- **`desktop.py`** — em vez do usuário rodar `python app.py` e abrir o
  navegador manualmente, esse script:
  - acha uma porta livre, sobe o Flask (`app.py`) numa thread em
    background;
  - espera o servidor responder (`_wait_server_ready`);
  - abre uma janela nativa com **pywebview** apontando pro
    `http://localhost:<porta>` — parece um app de verdade, não uma aba
    de navegador;
  - ícone na bandeja do sistema com **pystray** (Abrir/Sair, oculta em
    vez de fechar ao clicar no X, notificação nativa quando um
    download/tarefa termina);
  - detecta se está rodando "congelado" (`sys.frozen`, seteado pelo
    PyInstaller) pra achar os arquivos certos dentro do `.exe`.

- **`packaging/windows/igscraper.spec`** — spec do PyInstaller.
  Pontos que dão trabalho e valem lembrar:
  - `datas=[...]` precisa incluir pastas de template/assets E qualquer
    ícone usado em runtime (ex: ícone da bandeja) — fácil esquecer e o
    ícone sumir só no `.exe` empacotado, não em dev.
  - `hiddenimports=[...]` precisa listar bibliotecas que o PyInstaller
    não detecta sozinho (no nosso caso: `instagrapi`, `pydantic`,
    `pydantic_core`, `PIL._imaging`, `engineio.async_drivers.threading`,
    `instaloader`, `instaloader.exceptions`, `pystray`, `pystray._win32`).
  - `console=False` pra não abrir janela de terminal preta atrás do app.

- **`packaging/windows/build_windows.bat`** — automatiza: cria/ativa um
  venv de build (`.venv-build`), instala `requirements.txt` +
  `requirements-desktop.txt`, roda o PyInstaller com o `.spec`, e (se
  configurado) empacota com Inno Setup pra gerar um instalador de
  verdade com atalho na Área de Trabalho.

- **`requirements-desktop.txt`** — dependências só do empacotamento
  (`pywebview`, `pyinstaller`, `pystray`), separado do
  `requirements.txt` principal pra não pesar o ambiente web/Termux.

- **Dado do usuário fora da pasta do programa**: usa
  `IGSCRAPER_DATA_DIR` (variável de ambiente) pra decidir onde salvam
  contas/sessões/config — no desktop empacotado aponta pra
  `%LOCALAPPDATA%\IGScraperPro`, assim atualizar o `.exe` nunca apaga
  dados do usuário. Sem a variável, cai no comportamento antigo (pasta
  atual), preservando o modo Termux/dev.

### 2. Botão de atualizar (clica no arquivo, atualiza sozinho)

- **`ATUALIZAR.bat`** (raiz do repo) — o usuário só clica duas vezes.
  O que ele faz, nessa ordem:
  1. Fecha o `.exe` se estiver rodando (`taskkill`) — senão o Windows
     trava a substituição do arquivo por estar em uso.
  2. Detecta se a instalação tem `.git` (clone) ou não:
     - se tem `.git`: `git pull` na branch certa;
     - se não tem (a maioria dos usuários baixa o ZIP do GitHub em vez
       de clonar): baixa o ZIP da branch via PowerShell
       (`Invoke-WebRequest`), extrai, e usa `robocopy` pra sobrepor os
       arquivos do projeto — **excluindo** pastas de dados do usuário
       e de build (`.venv-build`, `dist`, etc), que nem ficam no repo
       mesmo.
  3. Roda o `build_windows.bat` de novo pra gerar um `.exe` atualizado.
  4. Se foi instalado via instalador Inno Setup, copia o `.exe` novo
     por cima do que está em
     `%LOCALAPPDATA%\Programs\<NomeDoApp>\<NomeDoApp>.exe` também —
     assim o atalho da Área de Trabalho já abre a versão nova sem
     precisar reinstalar.

## Coisas que já erramos e não precisa errar de novo

- **Cache de template do Flask**: com `debug=False` (produção), o
  Flask cacheia o Jinja template compilado na primeira renderização —
  editar `templates/index.html` e testar sem reiniciar o servidor
  mostra a versão antiga. Sempre reiniciar o processo depois de mexer
  no HTML/CSS/JS ao testar localmente.
- **Ícone sumindo só no build empacotado**: se o ícone (bandeja, `.exe`)
  não estiver no `datas` do `.spec`, funciona em dev (lê do disco) mas
  quebra silenciosamente no `.exe` (não encontra o arquivo dentro do
  bundle).
- **Fechar o app antes de sobrescrever o `.exe`**: sem o `taskkill` no
  updater, o Windows recusa sobrescrever um `.exe` em uso e a
  atualização falha pela metade.

## Quando for aplicar em outro programa

Só falar qual é o repositório (ex: "aplica esse padrão no Jarvis-novo")
que a gente recria essas peças lá, adaptando os nomes de pasta/app e o
que precisa rodar em background (pode não ser um Flask, mas a ideia de
pywebview + PyInstaller + updater.bat é a mesma).
