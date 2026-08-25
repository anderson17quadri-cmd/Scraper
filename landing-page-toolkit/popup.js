const $ = (id) => document.getElementById(id);
let ultimoResultadoTexto = "";

// ─── NAVEGACAO (menu -> ferramenta -> voltar) ───────────────────────────────
document.querySelectorAll(".menu-item").forEach((btn) => {
  btn.addEventListener("click", () => {
    $("view-home").hidden = true;
    $("view-" + btn.dataset.tool).hidden = false;
    $("btn-copiar").hidden = true;
    setStatus("");
  });
});

document.querySelectorAll("[data-back]").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tool-view").forEach((v) => (v.hidden = true));
    $("view-home").hidden = false;
    $("btn-copiar").hidden = true;
    setStatus("");
  });
});

function setStatus(msg, cls) {
  const el = $("status");
  el.textContent = msg;
  el.className = "status " + (cls || "");
}

async function getActiveTab() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  return tab;
}

async function rodarNaPagina(func, args) {
  const tab = await getActiveTab();
  if (!tab || !tab.id) throw new Error("Não achei a aba atual.");
  const [{ result }] = await chrome.scripting.executeScript({
    target: { tabId: tab.id },
    func,
    args: args || [],
  });
  return result;
}

function prepararCopiar(texto) {
  ultimoResultadoTexto = texto;
  $("btn-copiar").hidden = false;
}

$("btn-copiar").addEventListener("click", async () => {
  try {
    await navigator.clipboard.writeText(ultimoResultadoTexto);
    setStatus("✓ Copiado! Cola numa conversa com o Claude e pergunta o que quiser sobre isso.", "ok");
  } catch (e) {
    setStatus("✗ Não consegui copiar. Tenta de novo.", "err");
  }
});

// ─── CLIQUE NOS BOTOES DE ACAO (delegado por data-action) ───────────────────
document.addEventListener("click", (ev) => {
  const btn = ev.target.closest("[data-action]");
  if (!btn) return;
  const acao = btn.dataset.action;
  const fn = ACOES[acao];
  if (fn) fn(btn);
});

async function executarAcao(btn, resultId, worker) {
  const original = btn.textContent;
  btn.disabled = true;
  setStatus("Analisando...");
  try {
    await worker();
    setStatus("");
  } catch (e) {
    setStatus("✗ " + (e.message || e), "err");
  } finally {
    btn.disabled = false;
    btn.textContent = original;
  }
}

const ACOES = {};

// ─── 1. CORES E FONTES ───────────────────────────────────────────────────
function _extrairCoresEFontes() {
  const contarCores = {};
  const contarFontes = {};
  document.querySelectorAll("body *").forEach((el) => {
    const style = getComputedStyle(el);
    [style.color, style.backgroundColor].forEach((c) => {
      if (c && c !== "rgba(0, 0, 0, 0)" && c !== "transparent") {
        contarCores[c] = (contarCores[c] || 0) + 1;
      }
    });
    if (style.fontFamily) contarFontes[style.fontFamily] = (contarFontes[style.fontFamily] || 0) + 1;
  });
  const topCores = Object.entries(contarCores).sort((a, b) => b[1] - a[1]).slice(0, 8).map(([c]) => c);
  const topFontes = Object.entries(contarFontes).sort((a, b) => b[1] - a[1]).slice(0, 5).map(([f]) => f);
  return { cores: topCores, fontes: topFontes, titulo: document.title, url: location.href };
}

function rgbParaHex(rgb) {
  const m = rgb.match(/\d+(\.\d+)?/g);
  if (!m || m.length < 3) return rgb;
  const [r, g, b] = m.map((n) => Math.round(parseFloat(n)));
  return "#" + [r, g, b].map((n) => n.toString(16).padStart(2, "0")).join("");
}

ACOES["cores"] = (btn) =>
  executarAcao(btn, "result-cores", async () => {
    const r = await rodarNaPagina(_extrairCoresEFontes);
    const hexCores = r.cores.map(rgbParaHex);
    $("result-cores").innerHTML = `<div class="result-box"><b>Cores mais usadas nessa página:</b>
      <div class="swatch-row">${hexCores.map((h) => `<div class="swatch" style="background:${h}" title="${h}"></div>`).join("")}</div>
      <div style="margin-top:6px;color:var(--dim);font-size:0.72rem;">${hexCores.join(" · ")}</div>
    </div>
    <div class="result-box"><b>Tipos de letra mais usados:</b><br>${r.fontes.map((f) => `• ${f.split(",")[0].replace(/["']/g, "")}`).join("<br>")}</div>`;
    prepararCopiar(
      `Análise de cores e fontes da página "${r.titulo}" (${r.url}):\n\n` +
        `Cores mais usadas: ${hexCores.join(", ")}\n\n` +
        `Tipos de letra mais usados: ${r.fontes.map((f) => f.split(",")[0].replace(/["']/g, "")).join(", ")}`
    );
  });

// ─── 2. TITULOS E BOTOES ─────────────────────────────────────────────────
function _extrairTextos() {
  const titulos = Array.from(document.querySelectorAll("h1, h2, h3"))
    .map((el) => el.textContent.trim()).filter(Boolean).slice(0, 20);
  const botoesBrutos = Array.from(document.querySelectorAll('button, a[class*="btn"], a[class*="button"], input[type="submit"]'))
    .map((el) => (el.textContent || el.value || "").trim()).filter(Boolean);
  const botoes = [...new Set(botoesBrutos)].slice(0, 20);
  return { titulos, botoes, titulo: document.title, url: location.href };
}

ACOES["textos"] = (btn) =>
  executarAcao(btn, "result-textos", async () => {
    const r = await rodarNaPagina(_extrairTextos);
    $("result-textos").innerHTML = `<div class="result-box"><b>Títulos da página:</b><br>${
      r.titulos.length ? r.titulos.map((t) => `• ${t}`).join("<br>") : "<span style='color:var(--dim)'>Nenhum encontrado</span>"
    }</div>
    <div class="result-box"><b>Textos dos botões:</b><br>${
      r.botoes.length ? r.botoes.map((t) => `• ${t}`).join("<br>") : "<span style='color:var(--dim)'>Nenhum encontrado</span>"
    }</div>`;
    prepararCopiar(
      `Títulos e botões da página "${r.titulo}" (${r.url}):\n\n` +
        `Títulos:\n${r.titulos.map((t) => "- " + t).join("\n")}\n\n` +
        `Botões:\n${r.botoes.map((t) => "- " + t).join("\n")}`
    );
  });

// ─── 3. RASTREADORES ─────────────────────────────────────────────────────
function _detectarRastreadores() {
  const html = document.documentElement.outerHTML;
  const checagens = [
    { nome: "Facebook / Instagram (Meta Pixel)", re: /connect\.facebook\.net|fbq\(/i },
    { nome: "Google (Ads / Analytics)", re: /googletagmanager\.com|gtag\(|google-analytics\.com/i },
    { nome: "TikTok", re: /analytics\.tiktok\.com|ttq\.load/i },
    { nome: "Pinterest", re: /pintrk\(|ct\.pinterest\.com/i },
    { nome: "Hotjar (grava a tela de quem visita)", re: /static\.hotjar\.com/i },
    { nome: "Microsoft / Bing Ads", re: /bat\.bing\.com|uetq/i },
  ];
  const encontrados = checagens.filter((c) => c.re.test(html)).map((c) => c.nome);
  return { encontrados, titulo: document.title, url: location.href };
}

ACOES["rastreadores"] = (btn) =>
  executarAcao(btn, "result-rastreadores", async () => {
    const r = await rodarNaPagina(_detectarRastreadores);
    $("result-rastreadores").innerHTML = `<div class="result-box"><b>Quem está de olho em quem visita essa página:</b><br>${
      r.encontrados.length
        ? r.encontrados.map((n) => `✓ ${n}`).join("<br>")
        : "<span style='color:var(--dim)'>Não encontrei nenhum rastreador conhecido</span>"
    }</div>`;
    prepararCopiar(
      `Rastreadores/pixels encontrados na página "${r.titulo}" (${r.url}):\n\n` +
        (r.encontrados.length ? r.encontrados.map((n) => "- " + n).join("\n") : "Nenhum encontrado")
    );
  });

// ─── 4. COLECAO DE INSPIRACAO ────────────────────────────────────────────
async function _obterFavicon() {
  const r = await rodarNaPagina(() => {
    const link = document.querySelector('link[rel*="icon"]');
    return { favicon: link ? link.href : null, titulo: document.title, url: location.href };
  });
  return r;
}

async function _colecaoCarregar() {
  const { colecao } = await chrome.storage.local.get({ colecao: [] });
  return colecao;
}

async function _colecaoRenderizar() {
  const lista = await _colecaoCarregar();
  const box = $("result-colecao");
  if (!lista.length) {
    box.innerHTML = `<p class="empty-note">Sua coleção está vazia. Abra uma página que te inspirou e clique em "Salvar essa página".</p>`;
    return;
  }
  box.innerHTML = lista
    .slice()
    .reverse()
    .map(
      (item, iRev) => {
        const i = lista.length - 1 - iRev;
        return `<div class="colecao-item">
          ${item.favicon ? `<img src="${item.favicon}">` : `<div style="width:36px;height:36px;border-radius:6px;background:#222;flex-shrink:0;"></div>`}
          <div class="info"><b>${item.titulo}</b>${item.url}</div>
          <button class="del" data-del="${i}" title="Remover">✕</button>
        </div>`;
      }
    )
    .join("");
  prepararCopiar(
    "Coleção de páginas de inspiração:\n\n" + lista.map((it) => `- ${it.titulo} — ${it.url}`).join("\n")
  );
}

ACOES["colecao-salvar"] = (btn) =>
  executarAcao(btn, "result-colecao", async () => {
    const info = await _obterFavicon();
    const { colecao } = await chrome.storage.local.get({ colecao: [] });
    if (colecao.some((it) => it.url === info.url)) {
      setStatus("Essa página já está na sua coleção.", "ok");
    } else {
      colecao.push(info);
      await chrome.storage.local.set({ colecao });
      setStatus("✓ Página salva na coleção.", "ok");
    }
    await _colecaoRenderizar();
  });

document.addEventListener("click", async (ev) => {
  const del = ev.target.closest("[data-del]");
  if (!del) return;
  const idx = parseInt(del.dataset.del, 10);
  const { colecao } = await chrome.storage.local.get({ colecao: [] });
  colecao.splice(idx, 1);
  await chrome.storage.local.set({ colecao });
  await _colecaoRenderizar();
});

document.querySelector('[data-tool="colecao"]').addEventListener("click", () => {
  _colecaoRenderizar();
});

// ─── 5. GATILHOS DE URGENCIA ──────────────────────────────────────────────
function _detectarUrgencia() {
  const texto = document.body.innerText;
  const padroes = [
    { nome: "Tempo limitado (hoje, agora, últimas horas...)", re: /(oferta|promo[çc][ãa]o|desconto)[^.\n]{0,25}(acaba|termina|expira)[^.\n]{0,20}(hoje|agora|em breve)|últim[ao]s?\s+horas/gi },
    { nome: "Poucas unidades / vagas restando", re: /restam?\s+(apenas|só|somente)?\s*\d+|últim[ao]s?\s+\d+\s+(unidades|vagas|peças)/gi },
    { nome: "Contagem regressiva", re: /contagem regressiva|countdown/gi },
    { nome: "\"Não perca\" / \"corre\"", re: /n[ãa]o perca|corre (que|e) (a[cç][aã]o|oferta)|garanta (o seu|a sua) agora/gi },
    { nome: "Prova de gente comprando agora (\"X pessoas viram isso\")", re: /\d+\s+pessoas?\s+(est[ãa]o vendo|compraram|viram isso)/gi },
  ];
  const achados = [];
  padroes.forEach((p) => {
    const m = texto.match(p.re);
    if (m) achados.push({ nome: p.nome, exemplos: [...new Set(m)].slice(0, 3) });
  });
  return { achados, titulo: document.title, url: location.href };
}

ACOES["urgencia"] = (btn) =>
  executarAcao(btn, "result-urgencia", async () => {
    const r = await rodarNaPagina(_detectarUrgencia);
    $("result-urgencia").innerHTML = r.achados.length
      ? r.achados.map((a) => `<div class="result-box"><b>${a.nome}</b><br>${a.exemplos.map((e) => `"${e.trim()}"`).join("<br>")}</div>`).join("")
      : `<p class="empty-note">Não encontrei frases de urgência nessa página.</p>`;
    prepararCopiar(
      `Gatilhos de urgência encontrados na página "${r.titulo}" (${r.url}):\n\n` +
        (r.achados.length
          ? r.achados.map((a) => `- ${a.nome}: ${a.exemplos.join(" / ")}`).join("\n")
          : "Nenhum encontrado")
    );
  });

// ─── 6. SEO ────────────────────────────────────────────────────────────────
function _checarSEO() {
  const titulo = document.title || "";
  const desc = document.querySelector('meta[name="description"]')?.getAttribute("content") || "";
  const h1s = document.querySelectorAll("h1");
  const canonical = document.querySelector('link[rel="canonical"]')?.href || "";
  const imgs = document.querySelectorAll("img");
  const imgsSemAlt = Array.from(imgs).filter((i) => !i.getAttribute("alt")).length;
  return {
    titulo, tituloLen: titulo.length,
    desc, descLen: desc.length,
    qtdH1: h1s.length,
    canonical,
    qtdImgs: imgs.length, imgsSemAlt,
    url: location.href,
  };
}

ACOES["seo"] = (btn) =>
  executarAcao(btn, "result-seo", async () => {
    const r = await rodarNaPagina(_checarSEO);
    const itens = [];
    itens.push({
      ok: r.titulo && r.tituloLen >= 10 && r.tituloLen <= 60,
      texto: `Título da página: "${r.titulo || "(vazio)"}" (${r.tituloLen} caracteres) — ${
        !r.titulo ? "está sem título, o Google não vai gostar" : r.tituloLen > 60 ? "meio comprido, o Google pode cortar" : r.tituloLen < 10 ? "meio curto" : "tamanho bom"
      }`,
    });
    itens.push({
      ok: r.desc && r.descLen >= 50 && r.descLen <= 160,
      texto: `Descrição: "${r.desc || "(vazia)"}" (${r.descLen} caracteres) — ${
        !r.desc
          ? "está sem descrição, o Google inventa uma sozinho"
          : r.descLen > 160
          ? "meio comprida, pode ser cortada"
          : r.descLen < 50
          ? "meio curta, dá pra caprichar mais"
          : "tamanho bom"
      }`,
    });
    itens.push({ ok: r.qtdH1 === 1, texto: `Título principal (H1) na página: ${r.qtdH1} encontrado(s) — o ideal é ter exatamente 1` });
    itens.push({ ok: !!r.canonical, texto: r.canonical ? `Link canônico configurado: ${r.canonical}` : "Sem link canônico configurado (não é obrigatório, mas ajuda a evitar conteúdo duplicado)" });
    itens.push({ ok: r.imgsSemAlt === 0, texto: `Imagens sem texto explicativo (alt): ${r.imgsSemAlt} de ${r.qtdImgs} — imagens sem esse texto não ajudam no Google nem em leitor de tela` });

    $("result-seo").innerHTML = itens
      .map((it) => `<div class="result-box ${it.ok ? "" : "warn"}">${it.ok ? "✓" : "⚠"} ${it.texto}</div>`)
      .join("");
    prepararCopiar(`Checagem de SEO da página "${r.url}":\n\n` + itens.map((it) => `${it.ok ? "OK" : "ATENÇÃO"} - ${it.texto}`).join("\n"));
  });

// ─── 7. ACESSIBILIDADE ──────────────────────────────────────────────────────
function _checarAcessibilidade() {
  const imgsSemAlt = Array.from(document.querySelectorAll("img")).filter((i) => !i.getAttribute("alt")).length;
  const linksVagos = Array.from(document.querySelectorAll("a"))
    .map((a) => a.textContent.trim().toLowerCase())
    .filter((t) => ["clique aqui", "saiba mais", "aqui", "leia mais", "veja mais", "click here"].includes(t)).length;
  const fontesPequenas = Array.from(document.querySelectorAll("p, span, li, a"))
    .filter((el) => parseFloat(getComputedStyle(el).fontSize) < 12).length;
  const semLangNoHtml = !document.documentElement.getAttribute("lang");
  const inputsSemLabel = Array.from(document.querySelectorAll("input:not([type=hidden]), textarea, select")).filter((el) => {
    const id = el.id;
    const temLabel = id && document.querySelector(`label[for="${id}"]`);
    return !temLabel && !el.getAttribute("aria-label");
  }).length;
  return { imgsSemAlt, linksVagos, fontesPequenas, semLangNoHtml, inputsSemLabel, url: location.href };
}

ACOES["acessibilidade"] = (btn) =>
  executarAcao(btn, "result-acessibilidade", async () => {
    const r = await rodarNaPagina(_checarAcessibilidade);
    const itens = [
      { ok: r.imgsSemAlt === 0, texto: `${r.imgsSemAlt} imagem(ns) sem texto explicativo, então quem usa leitor de tela não sabe o que é a imagem` },
      { ok: r.linksVagos === 0, texto: `${r.linksVagos} link(s) com texto vago tipo "clique aqui" — melhor dizer pra onde o link leva` },
      { ok: r.fontesPequenas === 0, texto: `${r.fontesPequenas} texto(s) com letra bem pequena (menor que 12px), difícil de ler` },
      { ok: !r.semLangNoHtml, texto: r.semLangNoHtml ? "A página não avisa em que idioma está escrita (isso confunde leitor de tela)" : "A página avisa certinho o idioma dela" },
      { ok: r.inputsSemLabel === 0, texto: `${r.inputsSemLabel} campo(s) de formulário sem rótulo (label) associado, dificultando pra quem usa leitor de tela` },
    ];
    $("result-acessibilidade").innerHTML = itens.map((it) => `<div class="result-box ${it.ok ? "" : "warn"}">${it.ok ? "✓" : "⚠"} ${it.texto}</div>`).join("");
    prepararCopiar(`Checagem de acessibilidade da página "${r.url}":\n\n` + itens.map((it) => `${it.ok ? "OK" : "ATENÇÃO"} - ${it.texto}`).join("\n"));
  });

// ─── 8. RESPONSIVO (ver em varios tamanhos) ────────────────────────────────
ACOES["responsivo"] = (btn) =>
  executarAcao(btn, "result-responsivo", async () => {
    const tab = await getActiveTab();
    const tamanhos = [
      { nome: "Celular", w: 390, h: 780 },
      { nome: "Tablet", w: 800, h: 900 },
      { nome: "Computador", w: 1400, h: 900 },
    ];
    for (const t of tamanhos) {
      await chrome.windows.create({ url: tab.url, type: "popup", width: t.w, height: t.h });
    }
    $("result-responsivo").innerHTML = `<div class="result-box">✓ Abri essa página em 3 janelas: celular, tablet e computador. Dá uma olhada em cada uma pra ver se tudo continua legível e clicável.</div>`;
    prepararCopiar(`Testei a página "${tab.url}" em 3 tamanhos de tela (celular, tablet, computador) em janelas separadas pra conferir se o site se adapta bem em cada um.`);
    setStatus("");
  });

// ─── 9. VELOCIDADE ──────────────────────────────────────────────────────────
function _medirVelocidade() {
  const nav = performance.getEntriesByType("navigation")[0];
  const recursos = performance.getEntriesByType("resource");
  const totalBytes = recursos.reduce((s, r) => s + (r.transferSize || 0), 0);
  return {
    tempoCarregarMs: nav ? Math.round(nav.loadEventEnd - nav.startTime) : null,
    tempoRespostaServidorMs: nav ? Math.round(nav.responseStart - nav.requestStart) : null,
    qtdArquivos: recursos.length,
    totalKB: Math.round(totalBytes / 1024),
    url: location.href,
  };
}

ACOES["velocidade"] = (btn) =>
  executarAcao(btn, "result-velocidade", async () => {
    const r = await rodarNaPagina(_medirVelocidade);
    const segs = r.tempoCarregarMs != null ? (r.tempoCarregarMs / 1000).toFixed(1) : "?";
    const lento = r.tempoCarregarMs != null && r.tempoCarregarMs > 3000;
    $("result-velocidade").innerHTML = `
      <div class="result-box ${lento ? "warn" : ""}"><b>Tempo pra carregar tudo:</b> ${segs}s ${lento ? "— um pouco lento, o ideal é até 3s" : "— bom"}</div>
      <div class="result-box"><b>Resposta do servidor:</b> ${r.tempoRespostaServidorMs != null ? r.tempoRespostaServidorMs + "ms" : "não medido"}</div>
      <div class="result-box"><b>Arquivos carregados:</b> ${r.qtdArquivos} (total de ${r.totalKB} KB)</div>`;
    prepararCopiar(
      `Velocidade da página "${r.url}":\n\n` +
        `Tempo pra carregar: ${segs}s\nResposta do servidor: ${r.tempoRespostaServidorMs != null ? r.tempoRespostaServidorMs + "ms" : "?"}\n` +
        `Arquivos carregados: ${r.qtdArquivos} (${r.totalKB} KB no total)`
    );
  });

// ─── 10. LINKS QUEBRADOS ────────────────────────────────────────────────────
function _listarLinksEImagens() {
  const links = [...new Set(Array.from(document.querySelectorAll("a[href]")).map((a) => a.href))]
    .filter((h) => h.startsWith("http")).slice(0, 40);
  const imgs = [...new Set(Array.from(document.querySelectorAll("img[src]")).map((i) => i.src))]
    .filter((h) => h.startsWith("http")).slice(0, 20);
  return { links, imgs, url: location.href };
}

async function _checarUrl(url) {
  try {
    const resp = await fetch(url, { method: "HEAD", mode: "no-cors" });
    return true;
  } catch (e) {
    try {
      const resp2 = await fetch(url, { method: "GET", mode: "no-cors" });
      return true;
    } catch (e2) {
      return false;
    }
  }
}

ACOES["links"] = (btn) =>
  executarAcao(btn, "result-links", async () => {
    const r = await rodarNaPagina(_listarLinksEImagens);
    const todos = [...r.links.map((u) => ({ url: u, tipo: "link" })), ...r.imgs.map((u) => ({ url: u, tipo: "imagem" }))];
    setStatus(`Checando ${todos.length} itens...`);
    const quebrados = [];
    for (const item of todos) {
      const ok = await _checarUrl(item.url);
      if (!ok) quebrados.push(item);
    }
    $("result-links").innerHTML = quebrados.length
      ? `<div class="result-box bad"><b>Possivelmente quebrados (${quebrados.length}):</b><br>${quebrados.map((q) => `• [${q.tipo}] ${q.url}`).join("<br>")}</div>
         <div class="empty-note">Como o navegador bloqueia alguns testes, vale conferir manualmente os apontados aqui antes de ter certeza.</div>`
      : `<div class="result-box">✓ Testei ${todos.length} links/imagens e nenhum pareceu quebrado.</div>`;
    prepararCopiar(
      `Checagem de links/imagens da página "${r.url}" (${todos.length} testados):\n\n` +
        (quebrados.length ? quebrados.map((q) => `- [${q.tipo}] ${q.url}`).join("\n") : "Nenhum problema encontrado")
    );
  });

// ─── 11. TESTAR FORMULARIO ──────────────────────────────────────────────────
function _preencherFormularioTeste() {
  const forms = document.querySelectorAll("form");
  if (!forms.length) return { qtdFormularios: 0, qtdCampos: 0 };
  let qtdCampos = 0;
  forms.forEach((form) => {
    form.querySelectorAll("input, textarea, select").forEach((el) => {
      const type = (el.type || "").toLowerCase();
      if (["submit", "button", "hidden", "checkbox", "radio", "file"].includes(type)) return;
      let valor = "Teste";
      if (type === "email") valor = "teste@exemplo.com";
      else if (type === "tel") valor = "(11) 99999-0000";
      else if (type === "number") valor = "10";
      else if (el.tagName === "TEXTAREA") valor = "Mensagem de teste gerada pelo Kit de Ferramentas.";
      else if (el.tagName === "SELECT") { if (el.options.length > 1) el.selectedIndex = 1; return; }
      else if (/nome|name/i.test(el.name || el.id || "")) valor = "João da Silva";
      el.value = valor;
      el.dispatchEvent(new Event("input", { bubbles: true }));
      el.dispatchEvent(new Event("change", { bubbles: true }));
      qtdCampos++;
    });
  });
  return { qtdFormularios: forms.length, qtdCampos };
}

ACOES["formulario"] = (btn) =>
  executarAcao(btn, "result-formulario", async () => {
    const r = await rodarNaPagina(_preencherFormularioTeste);
    $("result-formulario").innerHTML = r.qtdFormularios
      ? `<div class="result-box">✓ Preenchi ${r.qtdCampos} campo(s) em ${r.qtdFormularios} formulário(s) com dados de teste. Vá na página e confira se ficou tudo certinho (não enviei nada, só preenchi).</div>`
      : `<p class="empty-note">Não encontrei nenhum formulário nessa página.</p>`;
    prepararCopiar(`Teste de formulário na página: preenchi ${r.qtdCampos} campo(s) em ${r.qtdFormularios} formulário(s) com dados falsos pra teste visual.`);
  });

// ─── 12. TESTAR DISPARO DE PIXEL ────────────────────────────────────────────
function _testarPixels() {
  const resultados = [];
  if (typeof window.fbq === "function") {
    try { window.fbq("trackCustom", "TesteKitFerramentas"); resultados.push({ nome: "Facebook / Instagram (Meta Pixel)", ok: true }); }
    catch (e) { resultados.push({ nome: "Facebook / Instagram (Meta Pixel)", ok: false, erro: true }); }
  } else if (/connect\.facebook\.net|fbq\(/i.test(document.documentElement.outerHTML)) {
    resultados.push({ nome: "Facebook / Instagram (Meta Pixel)", ok: false, naoCarregou: true });
  }
  if (typeof window.gtag === "function") {
    try { window.gtag("event", "teste_kit_ferramentas"); resultados.push({ nome: "Google (Ads / Analytics)", ok: true }); }
    catch (e) { resultados.push({ nome: "Google (Ads / Analytics)", ok: false, erro: true }); }
  } else if (/googletagmanager\.com|gtag\(/i.test(document.documentElement.outerHTML)) {
    resultados.push({ nome: "Google (Ads / Analytics)", ok: false, naoCarregou: true });
  }
  if (typeof window.ttq === "object" && window.ttq && typeof window.ttq.track === "function") {
    try { window.ttq.track("TesteKitFerramentas"); resultados.push({ nome: "TikTok", ok: true }); }
    catch (e) { resultados.push({ nome: "TikTok", ok: false, erro: true }); }
  } else if (/analytics\.tiktok\.com|ttq\.load/i.test(document.documentElement.outerHTML)) {
    resultados.push({ nome: "TikTok", ok: false, naoCarregou: true });
  }
  return { resultados, url: location.href };
}

ACOES["pixelteste"] = (btn) =>
  executarAcao(btn, "result-pixelteste", async () => {
    const r = await rodarNaPagina(_testarPixels);
    $("result-pixelteste").innerHTML = r.resultados.length
      ? r.resultados
          .map(
            (res) =>
              `<div class="result-box ${res.ok ? "" : "bad"}">${res.ok ? "✓" : "✗"} ${res.nome} — ${
                res.ok ? "respondeu certinho ao teste" : res.naoCarregou ? "encontrei o código na página, mas ele não carregou/respondeu" : "deu erro ao tentar disparar"
              }</div>`
          )
          .join("")
      : `<p class="empty-note">Não encontrei nenhum rastreador de anúncio (Facebook, Google, TikTok) pra testar nessa página.</p>`;
    prepararCopiar(
      `Teste de disparo de pixel na página "${r.url}":\n\n` +
        (r.resultados.length
          ? r.resultados.map((res) => `- ${res.nome}: ${res.ok ? "respondeu certinho" : "não respondeu bem"}`).join("\n")
          : "Nenhum rastreador encontrado pra testar")
    );
  });

// ─── 13. AO COMPARTILHAR ────────────────────────────────────────────────────
function _extrairShare() {
  const get = (sel) => document.querySelector(sel)?.getAttribute("content") || null;
  return {
    titulo: get('meta[property="og:title"]') || document.title,
    descricao: get('meta[property="og:description"]') || get('meta[name="description"]'),
    imagem: get('meta[property="og:image"]'),
    url: location.href,
  };
}

ACOES["share"] = (btn) =>
  executarAcao(btn, "result-share", async () => {
    const r = await rodarNaPagina(_extrairShare);
    const semImagem = !r.imagem;
    const semDescricao = !r.descricao;
    let html = `<div class="result-box">
      ${r.imagem ? `<img src="${r.imagem}" style="width:100%;border-radius:6px;margin-bottom:8px;">` : ""}
      <b>Título que vai aparecer:</b><br>${r.titulo}<br><br>
      <b>Descrição que vai aparecer:</b><br>${r.descricao || "<span style='color:var(--red)'>Nenhuma -- o link vai aparecer sem descrição</span>"}<br><br>
      <b>Imagem que vai aparecer:</b><br>${r.imagem ? "Tem imagem configurada ✓" : "<span style='color:var(--red)'>Não tem imagem -- o link vai aparecer sem foto</span>"}
    </div>`;
    if (semImagem || semDescricao) {
      html += `<div class="result-box bad">⚠ Recomendo configurar ${semImagem ? "uma imagem" : ""}${semImagem && semDescricao ? " e " : ""}${semDescricao ? "uma descrição" : ""} pra essa página, senão o link fica menos atraente quando compartilhado.</div>`;
    }
    $("result-share").innerHTML = html;
    prepararCopiar(
      `Como a página "${r.url}" aparece quando compartilhada:\n\n` +
        `Título: ${r.titulo}\nDescrição: ${r.descricao || "(nenhuma configurada)"}\nImagem: ${r.imagem || "(nenhuma configurada)"}`
    );
  });

// ─── 14. ANTES E DEPOIS ─────────────────────────────────────────────────────
async function _antesDepoisRenderizar() {
  const { antesImg, depoisImg } = await chrome.storage.local.get({ antesImg: null, depoisImg: null });
  const box = $("result-antesdepois");
  if (!antesImg && !depoisImg) {
    box.innerHTML = `<p class="empty-note">Ainda não tem nenhum print salvo. Clique em "Print Antes" pra começar.</p>`;
    return;
  }
  if (antesImg && !depoisImg) {
    box.innerHTML = `<div class="result-box">✓ Print "Antes" salvo. Agora mude o que quiser na página e clique em "Print Depois".</div>`;
    return;
  }
  if (!antesImg && depoisImg) {
    box.innerHTML = `<div class="result-box">✓ Print "Depois" salvo. Falta o "Antes".</div>`;
    return;
  }
  box.innerHTML = `
    <div class="compare-wrap" id="compareWrap">
      <img src="${antesImg}">
      <div class="depois-layer" id="depoisLayer"><img src="${depoisImg}"></div>
    </div>
    <input type="range" id="sliderComparar" min="0" max="100" value="50">
    <div class="empty-note">Arraste pra comparar o antes (esquerda) com o depois (direita).</div>`;
  prepararCopiar("Comparei dois prints da mesma página (antes e depois de uma mudança). As imagens ficam salvas na extensão -- pra mandar pro Claude, salve os prints e anexe na conversa.");
  const wrap = $("compareWrap");
  const layer = $("depoisLayer");
  const slider = $("sliderComparar");
  const ajustar = () => {
    const w = wrap.clientWidth;
    wrap.style.setProperty("--wrap-w", w + "px");
    const pct = slider.value / 100;
    layer.style.width = w * (1 - pct) + "px";
    layer.style.left = w * pct + "px";
  };
  slider.addEventListener("input", ajustar);
  setTimeout(ajustar, 0);
}

ACOES["antes-print"] = (btn) =>
  executarAcao(btn, "result-antesdepois", async () => {
    const dataUrl = await chrome.tabs.captureVisibleTab({ format: "png" });
    await chrome.storage.local.set({ antesImg: dataUrl });
    setStatus("✓ Print \"Antes\" salvo.", "ok");
    await _antesDepoisRenderizar();
  });

ACOES["depois-print"] = (btn) =>
  executarAcao(btn, "result-antesdepois", async () => {
    const dataUrl = await chrome.tabs.captureVisibleTab({ format: "png" });
    await chrome.storage.local.set({ depoisImg: dataUrl });
    setStatus("✓ Print \"Depois\" salvo.", "ok");
    await _antesDepoisRenderizar();
  });

ACOES["antesdepois-limpar"] = (btn) =>
  executarAcao(btn, "result-antesdepois", async () => {
    await chrome.storage.local.set({ antesImg: null, depoisImg: null });
    await _antesDepoisRenderizar();
  });

document.querySelector('[data-tool="antesdepois"]').addEventListener("click", () => {
  _antesDepoisRenderizar();
});

// ─── 15. MOCKUP EM DISPOSITIVO ───────────────────────────────────────────────
function _montarMockup(dataUrl) {
  return new Promise((resolve) => {
    const img = new Image();
    img.onload = () => {
      const molduraW = 30;
      const topoH = 60;
      const baseH = 60;
      const canvas = document.createElement("canvas");
      canvas.width = img.width + molduraW * 2;
      canvas.height = img.height + topoH + baseH;
      const ctx = canvas.getContext("2d");
      ctx.fillStyle = "#111";
      const r = 40;
      ctx.beginPath();
      ctx.moveTo(r, 0);
      ctx.arcTo(canvas.width, 0, canvas.width, canvas.height, r);
      ctx.arcTo(canvas.width, canvas.height, 0, canvas.height, r);
      ctx.arcTo(0, canvas.height, 0, 0, r);
      ctx.arcTo(0, 0, canvas.width, 0, r);
      ctx.closePath();
      ctx.fill();
      ctx.drawImage(img, molduraW, topoH);
      ctx.fillStyle = "#333";
      ctx.beginPath();
      ctx.arc(canvas.width / 2, topoH / 2, 4, 0, Math.PI * 2);
      ctx.fill();
      resolve(canvas.toDataURL("image/png"));
    };
    img.src = dataUrl;
  });
}

ACOES["mockup"] = (btn) =>
  executarAcao(btn, "result-mockup", async () => {
    const dataUrl = await chrome.tabs.captureVisibleTab({ format: "png" });
    const mockupUrl = await _montarMockup(dataUrl);
    $("result-mockup").innerHTML = `<img src="${mockupUrl}" style="width:100%;border-radius:8px;">
      <div class="empty-note">Clique com o botão direito na imagem e escolha "Salvar imagem como..." pra guardar.</div>`;
    prepararCopiar("Criei um mockup dessa página dentro de uma moldura de celular. A imagem fica só aqui na extensão -- pra mandar pro Claude, salve a imagem e anexe na conversa.");
    setStatus("✓ Mockup criado.", "ok");
  });

// ─── 16. EXTRAIR PRODUTOS DA LOJA ───────────────────────────────────────────
function _extrairProdutos() {
  const produtos = [];
  const vistos = new Set();

  function addProduto(p) {
    const nome = (p.nome || "").trim();
    if (!nome) return;
    const preco = (p.preco || "").toString().trim().replace(/^r\$\s*/i, "");
    const linkReal = p.link && p.link !== location.href ? p.link : "";
    // a chave sempre leva o nome, e usa o link (ou a imagem) so como criterio extra --
    // assim dois produtos diferentes com o mesmo preco e sem link individual nao se misturam
    const chave = nome + "|" + preco + "|" + (linkReal || p.imagem || "");
    if (vistos.has(chave)) return;
    vistos.add(chave);
    produtos.push({
      nome,
      preco,
      descricao: (p.descricao || "").trim().slice(0, 300),
      imagem: p.imagem || "",
      link: p.link || location.href,
    });
  }

  // 1) dados estruturados (JSON-LD) -- a maioria das plataformas de loja usa isso pro Google
  document.querySelectorAll('script[type="application/ld+json"]').forEach((script) => {
    try {
      const data = JSON.parse(script.textContent);
      const itens = Array.isArray(data) ? data : data["@graph"] || [data];
      itens.forEach((item) => {
        if (!item) return;
        const tipo = item["@type"];
        const ehProduto = tipo === "Product" || (Array.isArray(tipo) && tipo.includes("Product"));
        if (!ehProduto) return;
        const oferta = Array.isArray(item.offers) ? item.offers[0] : item.offers;
        addProduto({
          nome: item.name,
          preco: oferta ? oferta.price || (oferta.priceSpecification && oferta.priceSpecification.price) : "",
          descricao: item.description,
          imagem: Array.isArray(item.image) ? item.image[0] : item.image,
          link: item.url || location.href,
        });
      });
    } catch (e) {}
  });

  // 2) microdados (itemtype Product) -- outra forma comum de marcar produto
  if (produtos.length === 0) {
    document.querySelectorAll('[itemtype*="Product"]').forEach((el) => {
      const prop = (name) => el.querySelector(`[itemprop="${name}"]`);
      const nomeEl = prop("name");
      const precoEl = el.querySelector('[itemprop="price"]');
      const imgEl = prop("image");
      const linkEl = el.closest("a") || el.querySelector("a");
      addProduto({
        nome: nomeEl ? nomeEl.getAttribute("content") || nomeEl.textContent : "",
        preco: precoEl ? precoEl.getAttribute("content") || precoEl.textContent : "",
        descricao: (prop("description") || {}).textContent,
        imagem: imgEl ? imgEl.getAttribute("content") || imgEl.src : "",
        link: linkEl ? linkEl.href : location.href,
      });
    });
  }

  // 3) grade de produtos (cartões com classe "product"/"produto") -- quando a loja nao tem os dados acima
  if (produtos.length === 0) {
    document.querySelectorAll('[class*="product" i], [class*="produto" i]').forEach((el) => {
      const sub = el.querySelectorAll('[class*="product" i], [class*="produto" i]').length;
      if (sub > 3) return; // e um container grande demais, nao um cartao individual
      const tituloEl = el.querySelector('h1,h2,h3,h4,[class*="title" i],[class*="nome" i],[class*="name" i]');
      const precoEl = el.querySelector('[class*="price" i],[class*="preco" i]');
      const imgEl = el.querySelector("img");
      const linkEl = el.tagName === "A" ? el : el.closest("a") || el.querySelector("a");
      if (!tituloEl) return;
      addProduto({
        nome: tituloEl.textContent,
        preco: precoEl ? precoEl.textContent : "",
        descricao: "",
        imagem: imgEl ? imgEl.src : "",
        link: linkEl ? linkEl.href : location.href,
      });
    });
  }

  // 4) pagina de produto unico, sem nenhuma marcacao especial -- usa as tags de compartilhamento
  if (produtos.length === 0) {
    const get = (sel) => document.querySelector(sel)?.getAttribute("content") || null;
    const nome = get('meta[property="og:title"]') || document.title;
    const preco = get('meta[property="product:price:amount"]') || get('meta[property="og:price:amount"]');
    const imagem = get('meta[property="og:image"]');
    const descricao = get('meta[property="og:description"]') || get('meta[name="description"]');
    if (nome) addProduto({ nome, preco, descricao, imagem, link: location.href });
  }

  return { produtos, url: location.href, titulo: document.title };
}

async function _produtosCarregar() {
  const { produtosLoja } = await chrome.storage.local.get({ produtosLoja: [] });
  return produtosLoja;
}

function _csvEscapar(v) {
  const s = (v == null ? "" : String(v)).replace(/"/g, '""');
  return `"${s}"`;
}

async function _produtosRenderizar() {
  const lista = await _produtosCarregar();
  $("produtos-contagem").textContent = lista.length;
  const box = $("lista-produtos");
  if (!lista.length) {
    box.innerHTML = `<p class="empty-note">Nenhum produto guardado ainda.</p>`;
    return;
  }
  box.innerHTML = lista
    .map(
      (p, i) => `<div class="colecao-item">
        ${p.imagem ? `<img src="${p.imagem}">` : `<div style="width:36px;height:36px;border-radius:6px;background:#222;flex-shrink:0;"></div>`}
        <div class="info"><b>${p.nome}</b>${p.preco ? "R$ " + p.preco : "(sem preço)"}</div>
        <button class="del" data-del-produto="${i}" title="Remover">✕</button>
      </div>`
    )
    .join("");
}

ACOES["produtos-extrair"] = (btn) =>
  executarAcao(btn, "result-produtos", async () => {
    const r = await rodarNaPagina(_extrairProdutos);
    const lista = await _produtosCarregar();
    const antes = lista.length;
    const chaveDe = (p) => p.nome + "|" + (p.preco || "") + "|" + (p.link || p.imagem || "");
    const chavesExistentes = new Set(lista.map(chaveDe));
    r.produtos.forEach((p) => {
      const chave = chaveDe(p);
      if (!chavesExistentes.has(chave)) {
        chavesExistentes.add(chave);
        lista.push(p);
      }
    });
    await chrome.storage.local.set({ produtosLoja: lista });
    const novos = lista.length - antes;
    $("result-produtos").innerHTML = novos
      ? `<div class="result-box">✓ Achei ${r.produtos.length} produto(s) nessa página, ${novos} novo(s) foram adicionados à lista.</div>`
      : r.produtos.length
      ? `<div class="result-box">Todos os ${r.produtos.length} produto(s) dessa página já estavam na lista.</div>`
      : `<div class="result-box warn">⚠ Não consegui reconhecer produtos automaticamente nessa página. Tenta abrir uma página de categoria ou de um produto específico.</div>`;
    await _produtosRenderizar();
  });

ACOES["produtos-csv"] = (btn) =>
  executarAcao(btn, "result-produtos", async () => {
    const lista = await _produtosCarregar();
    if (!lista.length) {
      setStatus("A lista está vazia -- extraia produtos antes de baixar.", "err");
      return;
    }
    const cabecalho = ["Nome", "Preco", "Descricao", "Imagem (URL)", "Link"];
    const linhas = lista.map((p) => [p.nome, p.preco, p.descricao, p.imagem, p.link].map(_csvEscapar).join(","));
    const csv = "﻿" + [cabecalho.map(_csvEscapar).join(","), ...linhas].join("\r\n");
    const blob = new Blob([csv], { type: "text/csv;charset=utf-8" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = "produtos-da-loja.csv";
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 5000);
    setStatus(`✓ Baixado com ${lista.length} produto(s).`, "ok");
    prepararCopiar(
      `Produtos extraídos pra migração de loja (${lista.length}):\n\n` +
        lista.map((p) => `- ${p.nome} — R$ ${p.preco || "?"} — ${p.link}`).join("\n")
    );
  });

ACOES["produtos-limpar"] = (btn) =>
  executarAcao(btn, "result-produtos", async () => {
    await chrome.storage.local.set({ produtosLoja: [] });
    $("result-produtos").innerHTML = "";
    await _produtosRenderizar();
  });

document.addEventListener("click", async (ev) => {
  const del = ev.target.closest("[data-del-produto]");
  if (!del) return;
  const idx = parseInt(del.dataset.delProduto, 10);
  const lista = await _produtosCarregar();
  lista.splice(idx, 1);
  await chrome.storage.local.set({ produtosLoja: lista });
  await _produtosRenderizar();
});

document.querySelector('[data-tool="produtos"]').addEventListener("click", () => {
  _produtosRenderizar();
});
