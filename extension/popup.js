const $ = (id) => document.getElementById(id);

async function loadSettings() {
  const { port, engine } = await chrome.storage.local.get(["port", "engine"]);
  if (port) $("port").value = port;
  if (engine) $("engine").value = engine;
}

async function saveSettings() {
  await chrome.storage.local.set({ port: $("port").value, engine: $("engine").value });
}

function setStatus(msg, cls) {
  const el = $("status");
  el.textContent = msg;
  el.className = cls || "";
}

async function conectar() {
  const btn = $("btn-conectar");
  btn.disabled = true;
  setStatus("Lendo cookies do Instagram nesse navegador...");

  try {
    const cookies = await chrome.cookies.getAll({ domain: "instagram.com" });
    const sessionCookie = cookies.find((c) => c.name === "sessionid");
    if (!sessionCookie) {
      throw new Error(
        "Você não está logado no Instagram nesse navegador. Faça login em instagram.com primeiro e tente de novo."
      );
    }

    const cookieString = cookies.map((c) => `${c.name}=${c.value}`).join("; ");
    const port = $("port").value || 5000;
    const engine = $("engine").value;

    setStatus("Conectando no IG-Scraper Pro...");
    let resp;
    try {
      resp = await fetch(`http://localhost:${port}/api/login-session`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ sessionid: cookieString, engine }),
      });
    } catch (netErr) {
      throw new Error(
        `Não consegui conectar no IG-Scraper Pro na porta ${port}. Confira se o app está aberto e se a porta está certa.`
      );
    }

    const data = await resp.json();
    if (!data.ok) throw new Error(data.msg || "Erro desconhecido");

    setStatus(`✓ ${data.msg}`, "ok");
    await saveSettings();
  } catch (e) {
    setStatus(`✗ ${e.message || e}`, "err");
  } finally {
    btn.disabled = false;
  }
}

// ─── PERFIL ATUAL (adicionar aos alvos / baixar tudo) ─────────────────────
const RESERVED_PATHS = [
  "p", "reel", "reels", "explore", "accounts", "direct", "stories", "tv",
  "tags", "locations", "about", "legal", "developer", "web", "graphql",
];

async function getCurrentInstagramProfile() {
  const [tab] = await chrome.tabs.query({ active: true, currentWindow: true });
  if (!tab || !tab.url) return null;
  const m = tab.url.match(/^https?:\/\/(?:www\.)?instagram\.com\/([A-Za-z0-9_.]+)\/?(?:[/?#].*)?$/);
  if (!m) return null;
  const username = m[1];
  if (RESERVED_PATHS.includes(username.toLowerCase())) return null;
  return username;
}

function setProfileStatus(msg, cls) {
  const el = $("profile-status");
  el.textContent = msg;
  el.className = cls || "";
}

async function apiCall(path, body) {
  const port = $("port").value || 5000;
  const resp = await fetch(`http://localhost:${port}${path}`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  });
  return resp.json();
}

async function adicionarAosAlvos(username) {
  const btn = $("btn-add-target");
  btn.disabled = true;
  setProfileStatus(`Adicionando @${username} aos alvos...`);
  try {
    const data = await apiCall("/api/targets", { username, priority: 1 });
    if (!data.ok) throw new Error(data.msg || "Erro desconhecido");
    setProfileStatus(`✓ @${username} adicionado aos alvos`, "ok");
  } catch (e) {
    setProfileStatus(`✗ Não consegui conectar no IG-Scraper Pro. O app está aberto?`, "err");
  } finally {
    btn.disabled = false;
  }
}

async function baixarTudoDoPerfil(username) {
  if (!confirm(`Baixar TUDO (posts, reels, stories e destaques) de @${username}? Pode demorar dependendo do tamanho do perfil.`)) {
    return;
  }
  const btn = $("btn-baixar-tudo");
  btn.disabled = true;
  setProfileStatus(`Pedindo pro app baixar tudo de @${username}...`);
  try {
    const data = await apiCall("/api/download-all", { target_username: username });
    if (!data.ok) throw new Error(data.msg || "Erro desconhecido");
    setProfileStatus(`✓ ${data.msg} -- acompanhe pelo app`, "ok");
  } catch (e) {
    setProfileStatus(`✗ Não consegui conectar no IG-Scraper Pro. O app está aberto?`, "err");
  } finally {
    btn.disabled = false;
  }
}

async function initProfileSection() {
  const username = await getCurrentInstagramProfile();
  if (!username) {
    $("profile-empty").hidden = false;
    $("profile-card").hidden = true;
    $("profile-actions").hidden = true;
    return;
  }
  $("profile-empty").hidden = true;
  $("profile-card").hidden = false;
  $("profile-actions").hidden = false;
  $("profile-name").textContent = `@${username}`;
  $("btn-add-target").onclick = () => adicionarAosAlvos(username);
  $("btn-baixar-tudo").onclick = () => baixarTudoDoPerfil(username);
}

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  $("btn-conectar").addEventListener("click", conectar);
  initProfileSection();
});
