const $ = (id) => document.getElementById(id);
let ultimoResultadoTexto = "";

// ─── TROCA DE ABAS ─────────────────────────────────────────────────────────
document.querySelectorAll(".tab-btn").forEach((btn) => {
  btn.addEventListener("click", () => {
    document.querySelectorAll(".tab-btn").forEach((b) => b.classList.toggle("active", b === btn));
    document.querySelectorAll(".panel").forEach((p) => p.classList.toggle("active", p.id === "panel-" + btn.dataset.tab));
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

async function rodarNaPagina(func) {
  const tab = await getActiveTab();
  if (!tab || !tab.id) throw new Error("Não achei a aba atual.");
  const [{ result }] = await chrome.scripting.executeScript({ target: { tabId: tab.id }, func });
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

$("btn-cores").addEventListener("click", async () => {
  const btn = $("btn-cores");
  btn.disabled = true;
  setStatus("Analisando...");
  try {
    const r = await rodarNaPagina(_extrairCoresEFontes);
    const hexCores = r.cores.map(rgbParaHex);
    let html = `<div class="result-box"><b>Cores mais usadas nessa página:</b>
      <div class="swatch-row">${hexCores.map((h) => `<div class="swatch" style="background:${h}" title="${h}"></div>`).join("")}</div>
      <div style="margin-top:6px;color:var(--dim);font-size:0.72rem;">${hexCores.join(" · ")}</div>
    </div>
    <div class="result-box"><b>Tipos de letra mais usados:</b><br>${r.fontes.map((f) => `• ${f.split(",")[0].replace(/["']/g, "")}`).join("<br>")}</div>`;
    $("result-cores").innerHTML = html;

    const texto = `Análise de cores e fontes da página "${r.titulo}" (${r.url}):\n\n` +
      `Cores mais usadas: ${hexCores.join(", ")}\n\n` +
      `Tipos de letra mais usados: ${r.fontes.map((f) => f.split(",")[0].replace(/["']/g, "")).join(", ")}`;
    prepararCopiar(texto);
    setStatus("");
  } catch (e) {
    setStatus("✗ " + (e.message || e), "err");
  } finally {
    btn.disabled = false;
  }
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

$("btn-textos").addEventListener("click", async () => {
  const btn = $("btn-textos");
  btn.disabled = true;
  setStatus("Analisando...");
  try {
    const r = await rodarNaPagina(_extrairTextos);
    let html = `<div class="result-box"><b>Títulos da página:</b><br>${
      r.titulos.length ? r.titulos.map((t) => `• ${t}`).join("<br>") : "<span style='color:var(--dim)'>Nenhum encontrado</span>"
    }</div>
    <div class="result-box"><b>Textos dos botões:</b><br>${
      r.botoes.length ? r.botoes.map((t) => `• ${t}`).join("<br>") : "<span style='color:var(--dim)'>Nenhum encontrado</span>"
    }</div>`;
    $("result-textos").innerHTML = html;

    const texto = `Títulos e botões da página "${r.titulo}" (${r.url}):\n\n` +
      `Títulos:\n${r.titulos.map((t) => "- " + t).join("\n")}\n\n` +
      `Botões:\n${r.botoes.map((t) => "- " + t).join("\n")}`;
    prepararCopiar(texto);
    setStatus("");
  } catch (e) {
    setStatus("✗ " + (e.message || e), "err");
  } finally {
    btn.disabled = false;
  }
});

// ─── 3. PREVIEW DE COMPARTILHAMENTO ─────────────────────────────────────
function _extrairShare() {
  const get = (sel) => document.querySelector(sel)?.getAttribute("content") || null;
  return {
    titulo: get('meta[property="og:title"]') || document.title,
    descricao: get('meta[property="og:description"]') || get('meta[name="description"]'),
    imagem: get('meta[property="og:image"]'),
    url: location.href,
  };
}

$("btn-share").addEventListener("click", async () => {
  const btn = $("btn-share");
  btn.disabled = true;
  setStatus("Analisando...");
  try {
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
      html += `<div class="result-box" style="border-color:var(--red)">⚠ Recomendo configurar ${semImagem ? "uma imagem" : ""}${semImagem && semDescricao ? " e " : ""}${semDescricao ? "uma descrição" : ""} pra essa página, senão o link fica menos atraente quando compartilhado.</div>`;
    }
    $("result-share").innerHTML = html;

    const texto = `Como a página "${r.url}" aparece quando compartilhada:\n\n` +
      `Título: ${r.titulo}\nDescrição: ${r.descricao || "(nenhuma configurada)"}\nImagem: ${r.imagem || "(nenhuma configurada)"}`;
    prepararCopiar(texto);
    setStatus("");
  } catch (e) {
    setStatus("✗ " + (e.message || e), "err");
  } finally {
    btn.disabled = false;
  }
});

// ─── 4. RASTREADORES ─────────────────────────────────────────────────────
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

$("btn-rastreadores").addEventListener("click", async () => {
  const btn = $("btn-rastreadores");
  btn.disabled = true;
  setStatus("Analisando...");
  try {
    const r = await rodarNaPagina(_detectarRastreadores);
    let html = `<div class="result-box"><b>Quem está de olho em quem visita essa página:</b><br>${
      r.encontrados.length
        ? r.encontrados.map((n) => `✓ ${n}`).join("<br>")
        : "<span style='color:var(--dim)'>Não encontrei nenhum rastreador conhecido</span>"
    }</div>`;
    $("result-rastreadores").innerHTML = html;

    const texto = `Rastreadores/pixels encontrados na página "${r.titulo}" (${r.url}):\n\n` +
      (r.encontrados.length ? r.encontrados.map((n) => "- " + n).join("\n") : "Nenhum encontrado");
    prepararCopiar(texto);
    setStatus("");
  } catch (e) {
    setStatus("✗ " + (e.message || e), "err");
  } finally {
    btn.disabled = false;
  }
});
