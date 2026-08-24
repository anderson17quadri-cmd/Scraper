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

document.addEventListener("DOMContentLoaded", () => {
  loadSettings();
  $("btn-conectar").addEventListener("click", conectar);
});
