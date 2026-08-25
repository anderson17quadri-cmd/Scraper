# Kit de Ferramentas para Landing Page

Extensão com 16 ferramentas simples pra analisar, testar e apresentar
qualquer página, em linguagem direta — sem termo técnico difícil. Cada
ferramenta tem um botão pra copiar o resultado e colar numa conversa com
o Claude.

## As 16 ferramentas

### Estudar a concorrência
1. **Cores e Fontes** — mostra as cores e os tipos de letra que a
   página mais usa.
2. **Títulos e Botões** — lista todos os títulos e textos de botão da
   página.
3. **Rastreadores** — mostra quais empresas de anúncio (Facebook,
   Google, TikTok...) a página deixa acompanhar quem visita ela.
4. **Coleção de Inspiração** — guarda a página numa lista pessoal sua,
   pra não perder de vista quando encontrar algo que te inspirou.
5. **Gatilhos de Urgência** — procura frases de urgência ou escassez
   (tipo "restam só 3" ou "oferta acaba hoje") na página.

### Conferir qualidade
6. **Checagem de SEO** — confere se a página está configurada do jeito
   que o Google gosta (título, descrição, imagens com texto explicativo).
7. **Acessibilidade** — aponta coisas que dificultam a vida de quem tem
   dificuldade de visão ou usa leitor de tela.
8. **Ver em Vários Tamanhos** — abre a página em três janelas de
   tamanhos diferentes (celular, tablet, computador) de uma vez.
9. **Velocidade** — mede quanto tempo a página demorou pra carregar de
   verdade, e quantos arquivos ela precisou baixar.
10. **Links Quebrados** — testa os links e imagens da página e avisa
    quais parecem estar quebrados.
11. **Testar Formulário** — preenche os formulários da página com dados
    de teste, pra conferir rápido se está tudo certo.
12. **Testar Disparo de Pixel** — tenta acionar os rastreadores de
    anúncio da página pra ver se eles respondem.

### Compartilhar e apresentar
13. **Ao Compartilhar** — mostra como o link vai aparecer quando alguém
    colar no WhatsApp, Instagram ou Facebook.
14. **Antes e Depois** — tira dois prints da mesma página em momentos
    diferentes e mostra um controle deslizante pra comparar.
15. **Mockup em Dispositivo** — tira um print da página e coloca dentro
    de uma moldura de celular, pronta pra postar ou mandar pro cliente.

### Migrar loja antiga
16. **Extrair Produtos da Loja** — vai juntando os produtos (nome,
    preço, descrição, foto) de cada página que você visita. No final,
    baixa um CSV com os dados, ou um ZIP com o CSV **e os arquivos das
    fotos de verdade**, pronto pra importar numa loja nova. Use só em
    loja sua, ou de um cliente que te contratou pra fazer a migração.

## Como instalar

1. Abra `chrome://extensions` (ou `edge://extensions`) no navegador.
2. Ative o **"Modo do desenvolvedor"** (canto superior direito).
3. Clique em **"Carregar expandida"** (ou "Carregar sem compactação").
4. Selecione esta pasta (`landing-page-toolkit`).
5. Pronto — aparece o ícone na barra de extensões.

Se já tinha instalado antes, não precisa remover nada: só clique no
ícone de recarregar no card da extensão em `chrome://extensions`. A
partir dessa versão o Chrome vai pedir uma autorização nova ("Ler e
alterar todos os seus dados em todos os sites") — é porque a
ferramenta "Extrair Produtos da Loja" agora baixa as fotos de verdade
de qualquer loja, e pra isso precisa de acesso a qualquer site (não é
usado por nenhuma outra ferramenta).

## Como usar

1. Abra a página que você quer analisar (a sua ou de um concorrente).
2. Clique no ícone da extensão.
3. Escolha a ferramenta na lista do menu.
4. Clique no botão de ação da ferramenta (varia: "Analisar essa
   página", "Preencher com dados de teste", etc.).
5. Se quiser, clique em **"Copiar resultado pro Claude"** e cole numa
   conversa aqui pra perguntar o que quiser sobre o resultado.
6. Use "← Voltar" pra retornar ao menu e escolher outra ferramenta.

## Detalhes de algumas ferramentas

- **Coleção de Inspiração** e **Antes e Depois** guardam os dados
  dentro do próprio navegador (só nesse computador) — não vão pra
  nenhum servidor.
- **Links Quebrados** pode demorar alguns segundos, porque testa cada
  link um por um.
- **Testar Formulário** só preenche os campos, nunca envia nada
  sozinho — quem decide enviar é você.
- **Mockup em Dispositivo** e **Antes e Depois** geram imagens; pra
  levar pro Claude, salve a imagem (clique direito → "Salvar imagem
  como...") e anexe na conversa.
- **Extrair Produtos da Loja** também guarda os dados só nesse
  navegador até você clicar em algum botão de baixar. Ela tenta
  reconhecer produtos automaticamente (funciona melhor em lojas
  Shopify, WooCommerce e a maioria das plataformas brasileiras); se
  não achar nada numa página, tenta abrir uma página de categoria ou
  de produto específico. Se alguma foto não puder ser baixada (link
  expirado, loja bloqueando), ela avisa quantas falharam e mesmo assim
  entrega o CSV com o link de cada uma.
