# IG-Scraper Pro - Conector (extensão do navegador)

Conecta a conta do Instagram já logada no seu Chrome/Edge direto no
IG-Scraper Pro, com um clique — sem copiar e colar sessionid, sem passar
pelo bloqueio de criptografia do Chrome (porque a extensão lê o cookie
de dentro do navegador, não por fora).

## Como instalar (uma vez só)

1. Abra o Chrome ou Edge e vá em `chrome://extensions` (ou `edge://extensions`).
2. Ative o **"Modo do desenvolvedor"** (canto superior direito).
3. Clique em **"Carregar sem compactação"** (ou "Load unpacked").
4. Selecione esta pasta (`extension`), dentro da pasta do IG-Scraper Pro.
5. Pronto — o ícone azul do IG-Scraper Pro aparece na barra de extensões.

## Como usar

1. Deixe o **IG-Scraper Pro aberto** no seu PC.
2. Faça login no **instagram.com** normalmente nesse mesmo navegador
   (Chrome ou Edge), com a conta que você quer usar.
3. Clique no ícone da extensão.
4. Escolha o motor (Instagrapi ou Instaloader) e confirme a porta
   (normalmente `5000` — só muda se o app avisar outra porta).
5. Clique em **"Conectar essa conta"**.

A conta aparece na aba Contas do app automaticamente, pronta pra usar.

## Por que isso funciona e o botão "Importar" de dentro do app não sempre funciona

O botão "Importar" que já existe dentro do IG-Scraper Pro tenta ler os
cookies do navegador **por fora** (um programa separado abrindo o
arquivo de cookies do Chrome). Desde 2024 o Chrome bloqueia esse tipo
de acesso de propósito, mesmo com o app rodando como administrador.

Essa extensão faz diferente: ela roda **dentro** do navegador e usa a
API oficial de cookies que o próprio Chrome disponibiliza pras
extensões (a mesma que extensões como o Cookie-Editor usam) —
por isso não esbarra nesse bloqueio.
