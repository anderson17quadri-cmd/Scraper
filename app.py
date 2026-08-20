#!/usr/bin/env python3
"""
IG-SCRAPER-PRO v4.0 - Web Dashboard
python app.py  ->  http://localhost:5000
"""

import os, sys, json, time, threading, sqlite3, random, zipfile, re
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory
from ig_auth import login_account, login_by_sessionid, translate_ig_error

# Quando empacotado com PyInstaller (build desktop), os templates ficam
# dentro do bundle (_MEIPASS) em vez de ao lado do app.py -- sem isso o
# Flask nao encontra index.html e da TemplateNotFound no .exe.
if getattr(sys, "frozen", False):
    app = Flask(__name__, template_folder=os.path.join(sys._MEIPASS, "templates"))
else:
    app = Flask(__name__)

# No build desktop, desktop.py define IGSCRAPER_DATA_DIR (pasta gravavel
# do usuario, tipo %LOCALAPPDATA%) antes de importar este modulo. No
# Termux/uso normal essa variavel nao existe e tudo continua relativo ao
# diretorio atual, como sempre foi.
_DATA_DIR = os.environ.get("IGSCRAPER_DATA_DIR") or "."
DOWNLOADS_DIR = os.path.join(_DATA_DIR, "downloads")
ZIPS_DIR = f"{DOWNLOADS_DIR}/_zips"
SESSIONS_DIR = os.path.join(_DATA_DIR, "sessions")
DB_PATH = os.path.join(_DATA_DIR, "scraper.db")
ACCOUNTS_PATH = os.path.join(_DATA_DIR, "accounts.json")
TARGETS_PATH = os.path.join(_DATA_DIR, "targets.json")
CONFIG_PATH = os.path.join(_DATA_DIR, "config.json")

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

# ─── DATABASE ─────────────────────────────────────────────────────────────────
def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""CREATE TABLE IF NOT EXISTS downloads (
        id INTEGER PRIMARY KEY AUTOINCREMENT, media_id TEXT UNIQUE,
        username TEXT, file TEXT, type TEXT, date TEXT, downloaded_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("""CREATE TABLE IF NOT EXISTS accounts_stats (
        username TEXT PRIMARY KEY, total_downloads INTEGER DEFAULT 0, last_use TEXT)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_username ON downloads(username)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_at ON downloads(downloaded_at)")
    conn.commit()
    conn.close()

def db_query(sql, params=(), fetch=True):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute(sql, params)
    if fetch:
        rows = c.fetchall()
    else:
        conn.commit()
        rows = None
    conn.close()
    return rows

def is_downloaded(media_id):
    return len(db_query("SELECT id FROM downloads WHERE media_id=?", (media_id,))) > 0

def add_download(data):
    try:
        db_query("INSERT INTO downloads (media_id, username, file, type, date) VALUES (?,?,?,?,?)",
                 (data['media_id'], data['username'], data['file'], data['type'], data['date']), fetch=False)
        db_query("INSERT INTO accounts_stats (username, total_downloads, last_use) VALUES (?,1,?) "
                 "ON CONFLICT(username) DO UPDATE SET total_downloads=total_downloads+1, last_use=?",
                 (data['username'], datetime.now().isoformat(), datetime.now().isoformat()), fetch=False)
    except sqlite3.IntegrityError:
        pass

def get_stats():
    t = db_query("SELECT COUNT(*) FROM downloads")[0][0]
    p = db_query("SELECT COUNT(DISTINCT username) FROM downloads")[0][0]
    l = db_query("SELECT MAX(downloaded_at) FROM downloads")[0][0]
    rows = db_query("SELECT username, COUNT(*) as cnt FROM downloads GROUP BY username ORDER BY cnt DESC LIMIT 10")
    top = [{"username": r[0], "count": r[1]} for r in rows]
    rows = db_query("SELECT file, username, type, downloaded_at FROM downloads ORDER BY downloaded_at DESC LIMIT 20")
    recent = [{"file": r[0], "profile": r[1], "type": r[2], "date": r[3]} for r in rows]
    rows = db_query("SELECT DATE(downloaded_at) as day, COUNT(*) as cnt FROM downloads "
                     "WHERE downloaded_at >= DATE('now','-7 days') GROUP BY day ORDER BY day")
    daily = {r[0]: r[1] for r in rows}
    try:
        import shutil; du = shutil.disk_usage(DOWNLOADS_DIR)
        disk = f"{du.used/(1024**3):.1f} GB"
    except:
        disk = "0 GB"
    return {"total": t, "profiles": p, "last_download": l, "disk_usage": disk,
            "top_profiles": top, "recent": recent, "daily": daily}

# ─── JSON HELPERS ─────────────────────────────────────────────────────────────
def jload(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def jsave(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def init_files():
    if not os.path.exists(ACCOUNTS_PATH): jsave(ACCOUNTS_PATH, {"accounts": []})
    if not os.path.exists(TARGETS_PATH): jsave(TARGETS_PATH, {"targets": []})
    if not os.path.exists(CONFIG_PATH):
        jsave(CONFIG_PATH, {"delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
                            "auto_interval": 3600, "max_downloads_per_day": 500})

def get_cfg():
    return jload(CONFIG_PATH, {"delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
                                "auto_interval": 3600, "max_downloads_per_day": 500})

def upsert_account(username, password=None, sessionid=None):
    accs = jload(ACCOUNTS_PATH)
    accounts = accs.setdefault("accounts", [])
    acc = next((a for a in accounts if a["username"] == username), None)
    if acc is None:
        acc = {"username": username, "active": True, "created_at": datetime.now().isoformat()}
        accounts.append(acc)
    if password:
        acc["password"] = password
        acc.pop("sessionid", None)
    if sessionid:
        acc["sessionid"] = sessionid
        acc.pop("password", None)
    acc["active"] = True
    acc["last_use"] = datetime.now().isoformat()
    jsave(ACCOUNTS_PATH, accs)

# ─── SCRAPING ENGINE ──────────────────────────────────────────────────────────
scrape_state = {"running": False, "connected": False, "current_account": "",
                "message": "Pronto", "progress": 0, "total": 0, "current": "", "logs": [],
                "stop_requested": False, "zip_url": None}

# cache em memoria: cache_key -> {"cl":.., "medias":[...], "kind": "post"|"story",
# "target":.., "label":.., "folder":.., "uid":.. , "end_cursor":..}
# preenchido por /api/preview*, /api/stories e /api/highlight-items;
# consumido por /api/download-selected
preview_cache = {}
PREVIEW_PAGE_SIZE = 30

# conta-nossa (username) -> Client ja autenticado, reaproveitado entre
# chamadas de preview/stories/destaques pra nao relogar toda hora
active_clients = {}

def _get_client(acc_idx):
    accounts = jload(ACCOUNTS_PATH).get("accounts", [])
    if not accounts:
        raise ValueError("Nenhuma conta cadastrada")
    if acc_idx in (None, ""):
        acc_idx = next((i for i, a in enumerate(accounts) if a.get("active", True)), None)
    else:
        acc_idx = int(acc_idx)
    if acc_idx is None or not (0 <= acc_idx < len(accounts)):
        raise ValueError("Nenhuma conta valida")
    acc = accounts[acc_idx]
    un = acc["username"]
    cl = active_clients.get(un)
    if cl is None:
        cl = login_account(acc, f"{SESSIONS_DIR}/{un}.json")
        active_clients[un] = cl
    return cl

def _safe_name(s):
    return re.sub(r'[^\w\-. ]', '_', str(s)).strip()[:60] or "destaque"

def _save_caption_sidecar(folder, base_name, m):
    """Salva a legenda + metadados do post num .txt do lado da midia
    (mesma ideia do Instaloader: legenda legivel + dados uteis embaixo).
    So faz sentido pra posts (Media) -- stories nao tem legenda."""
    caption = (getattr(m, "caption_text", None) or "").strip()
    likes = getattr(m, "like_count", None)
    comments = getattr(m, "comment_count", None)
    location = getattr(m, "location", None)
    tags = [f"@{u.user.username}" for u in (getattr(m, "usertags", None) or []) if getattr(u, "user", None)]

    lines = [caption] if caption else []
    lines.append("")
    lines.append("---")
    lines.append(f"Data: {m.taken_at.strftime('%Y-%m-%d %H:%M')}")
    if likes is not None:
        lines.append(f"Curtidas: {likes}")
    if comments is not None:
        lines.append(f"Comentarios: {comments}")
    if location is not None and getattr(location, "name", None):
        lines.append(f"Localizacao: {location.name}")
    if tags:
        lines.append(f"Marcados: {', '.join(tags)}")

    try:
        with open(os.path.join(folder, f"{base_name}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass

def _highlight_cover_url(cover):
    """cover_media do Highlight vem como dict cru da API do Instagram, nao
    como objeto Media -- tenta achar a url da imagem em algumas chaves
    conhecidas e desiste (None) sem quebrar se o formato mudar."""
    if not isinstance(cover, dict):
        return None
    for key in ("cropped_image_version", "full_image_version"):
        v = cover.get(key)
        if isinstance(v, dict) and v.get("url"):
            return str(v["url"])
    return None

def _media_preview_item(m):
    thumb = m.thumbnail_url or (m.resources[0].thumbnail_url if m.media_type == 8 and m.resources else None)
    return {
        "id": str(m.id),
        "type": "carousel" if m.media_type == 8 else ("video" if m.media_type == 2 else "photo"),
        "thumbnail": str(thumb) if thumb else None,
        "date": m.taken_at.isoformat(),
        "already": is_downloaded(m.id),
    }

def _story_preview_item(s):
    return {
        "id": str(s.id),
        "type": "video" if s.media_type == 2 else "photo",
        "thumbnail": str(s.thumbnail_url) if s.thumbnail_url else None,
        "date": s.taken_at.isoformat() if getattr(s, "taken_at", None) else None,
        "already": is_downloaded(s.id),
    }

class _RawStory:
    """Mesma 'forma' de um Story do instagrapi (id/pk/media_type/thumbnail_url/
    video_url/taken_at/video_duration), montada direto do JSON cru da API.

    Existe porque cl.highlight_info() valida a resposta inteira com pydantic
    (incluindo Highlight.user.friendship_status.user_id), e o Instagram as
    vezes nao manda esse campo -- af entao a lib inteira quebra so por causa
    de um campo que a gente nem usa pra baixar o destaque."""
    def __init__(self, item):
        self.id = str(item.get("pk") or item.get("id") or "")
        self.pk = self.id
        self.media_type = item.get("media_type", 1)
        self.thumbnail_url = self._best_url((item.get("image_versions2") or {}).get("candidates"))
        self.video_url = self._best_url(item.get("video_versions"))
        ts = item.get("taken_at")
        self.taken_at = datetime.fromtimestamp(ts) if ts else None
        self.video_duration = item.get("video_duration")

    @staticmethod
    def _best_url(candidates):
        if not candidates:
            return None
        best = max(candidates, key=lambda c: (c.get("width") or 0) * (c.get("height") or 0))
        return best.get("url")

def _fetch_highlight_items_raw(cl, highlight_pk):
    """Busca os itens de um destaque sem passar pela validacao pydantic
    (que quebra em contas/perfis onde o Instagram omite alguns campos).
    Retorna (titulo, [_RawStory,...])."""
    from instagrapi import config as ig_config
    highlight_id = f"highlight:{highlight_pk}"
    data = {
        "exclude_media_ids": "[]",
        "supported_capabilities_new": json.dumps(ig_config.SUPPORTED_CAPABILITIES),
        "source": "profile",
        "_uid": str(cl.user_id),
        "_uuid": cl.uuid,
        "user_ids": [highlight_id],
    }
    result = cl.private_request("feed/reels_media/", data)
    reels = result.get("reels", {})
    if highlight_id not in reels:
        raise ValueError("Destaque nao encontrado ou vazio")
    raw = reels[highlight_id]
    title = raw.get("title") or "Destaque"
    items = [_RawStory(it) for it in raw.get("items", [])]
    return title, items

def _make_zip(target, paths):
    paths = [p for p in paths if p and os.path.exists(p)]
    if not paths:
        return None
    os.makedirs(ZIPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = f"{ZIPS_DIR}/{target}_{ts}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for p in paths:
            zf.write(p, arcname=os.path.basename(p))
    return f"/downloads/_zips/{os.path.basename(zip_path)}"

def _add_log(msg, typ="info"):
    scrape_state["logs"].append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": typ})
    if len(scrape_state["logs"]) > 100:
        scrape_state["logs"] = scrape_state["logs"][-50:]

def _stopped():
    if scrape_state.get("stop_requested"):
        _add_log("Scraping interrompido pelo usuario", "error")
        scrape_state["message"] = "Interrompido pelo usuario"
        return True
    return False

def _download_one(cl, tu, m, folder):
    """Baixa uma midia (foto/video/carrossel) na maior resolucao que o
    instagrapi tiver disponivel. Retorna a lista de caminhos salvos."""
    date_str = m.taken_at.strftime("%Y%m%d_%H%M%S")
    saved_paths = []
    try:
        if m.media_type == 1:
            path = cl.photo_download_by_url(m.thumbnail_url, filename=f"{tu}_{date_str}", folder=folder)
            add_download({'media_id': m.id, 'username': tu, 'file': os.path.basename(path), 'type': 'photo', 'date': m.taken_at.isoformat()})
            _add_log(f"Download: {os.path.basename(path)}", "success")
            saved_paths.append(str(path))
            _save_caption_sidecar(folder, f"{tu}_{date_str}", m)
        elif m.media_type == 2:
            path = cl.video_download_by_url(m.video_url, filename=f"{tu}_{date_str}", folder=folder)
            add_download({'media_id': m.id, 'username': tu, 'file': os.path.basename(path), 'type': 'video', 'date': m.taken_at.isoformat()})
            _add_log(f"Download: {os.path.basename(path)}", "success")
            saved_paths.append(str(path))
            _save_caption_sidecar(folder, f"{tu}_{date_str}", m)
        elif m.media_type == 8:  # carousel
            for j, res in enumerate(m.resources):
                try:
                    if res.media_type == 1:
                        path = cl.photo_download_by_url(res.thumbnail_url, filename=f"{tu}_{date_str}_c{j}", folder=folder)
                        rtype = 'photo'
                    else:
                        path = cl.video_download_by_url(res.video_url, filename=f"{tu}_{date_str}_c{j}", folder=folder)
                        rtype = 'video'
                    add_download({'media_id': res.pk, 'username': tu, 'file': os.path.basename(path), 'type': rtype, 'date': m.taken_at.isoformat()})
                    _add_log(f"Download: {os.path.basename(path)}", "success")
                    saved_paths.append(str(path))
                except Exception:
                    pass
            # legenda e uma so pro carrossel inteiro, nao por item
            _save_caption_sidecar(folder, f"{tu}_{date_str}", m)
    except Exception as e:
        es = str(e)
        _add_log(f"Erro: {es[:80]}", "error")
        if "429" in es:
            time.sleep(120)
        elif "PleaseWaitFewMinutes" in es:
            time.sleep(300)
    return saved_paths

def _download_story_item(cl, tu, s, folder):
    """Baixa um item de story/destaque (foto ou video), ja na maior
    resolucao disponivel. Retorna a lista de caminhos salvos."""
    date_str = (s.taken_at.strftime("%Y%m%d_%H%M%S") if getattr(s, "taken_at", None)
                else datetime.now().strftime("%Y%m%d_%H%M%S"))
    saved_paths = []
    try:
        url = s.thumbnail_url if s.media_type == 1 else s.video_url
        mtype = 'photo' if s.media_type == 1 else 'video'
        path = cl.story_download_by_url(url, filename=f"{tu}_story_{date_str}", folder=folder)
        add_download({'media_id': s.id, 'username': tu, 'file': os.path.basename(path), 'type': mtype, 'date': datetime.now().isoformat()})
        _add_log(f"Download: {os.path.basename(path)}", "success")
        saved_paths.append(str(path))
    except Exception as e:
        es = str(e)
        _add_log(f"Erro: {es[:80]}", "error")
        if "429" in es:
            time.sleep(120)
        elif "PleaseWaitFewMinutes" in es:
            time.sleep(300)
    return saved_paths

def _human_delay_after(m):
    if m.media_type == 2 and hasattr(m, 'video_duration') and m.video_duration:
        time.sleep(min(m.video_duration + 3, 60))
    else:
        time.sleep(3 + random.random() * 7)

def _do_scrape(account_index=None, target_index=None):
    global scrape_state
    scrape_state.update(running=True, connected=False, current_account="",
                        message="Ligando motor...", progress=0, total=0, current="", logs=[],
                        stop_requested=False, zip_url=None)

    try:
        cfg = get_cfg()
        accounts = jload(ACCOUNTS_PATH).get("accounts", [])
        targets = jload(TARGETS_PATH).get("targets", [])

        if not accounts:
            scrape_state["message"] = "Erro: Nenhuma conta cadastrada"
            _add_log("Nenhuma conta cadastrada", "error")
            return
        if not targets:
            scrape_state["message"] = "Erro: Nenhum perfil alvo cadastrado"
            _add_log("Nenhum perfil alvo cadastrado", "error")
            return

        if account_index is not None:
            if not (0 <= account_index < len(accounts)):
                scrape_state["message"] = "Erro: Conta invalida"
                _add_log("Indice de conta invalido", "error")
                return
            accs = [accounts[account_index]]
        else:
            accs = accounts

        if target_index is not None:
            if not (0 <= target_index < len(targets)):
                scrape_state["message"] = "Erro: Alvo invalido"
                _add_log("Indice de alvo invalido", "error")
                return
            active_targets = [targets[target_index]]
        else:
            active_targets = [t for t in targets if t.get("active", True)]

        if not active_targets:
            scrape_state["message"] = "Erro: Nenhum alvo ativo"
            _add_log("Nenhum alvo ativo", "error")
            return

        # distribui os alvos entre as contas ativas em rodizio (round-robin)
        # quando ha mais de uma conta disponivel e nenhuma foi escolhida
        # especificamente -- assim nenhuma conta sozinha faz requisicao pra
        # TODOS os alvos, reduzindo o risco de bloqueio por excesso de uso
        valid_accs = [a for a in accs if a.get("active", True)
                      and a.get('username') and (a.get('password') or a.get('sessionid'))]
        if not valid_accs:
            scrape_state["message"] = "Erro: Nenhuma conta ativa valida"
            _add_log("Nenhuma conta ativa valida (sem usuario/senha/sessao)", "error")
            return

        if account_index is None and len(valid_accs) > 1:
            assignment = [[] for _ in valid_accs]
            for i, tgt in enumerate(active_targets):
                assignment[i % len(valid_accs)].append(tgt)
            _add_log(f"Alvos distribuidos entre {len(valid_accs)} contas (rodizio)")
        else:
            assignment = [active_targets for _ in valid_accs]

        for acc, my_targets in zip(valid_accs, assignment):
            if _stopped():
                break
            if not my_targets:
                continue

            un = acc['username']
            scrape_state["current_account"] = un
            scrape_state["message"] = f"Conectando @{un}..."
            _add_log(f"Tentando login em @{un}...")

            try:
                sf = f"{SESSIONS_DIR}/{un}.json"
                cl = login_account(acc, sf)
                scrape_state["connected"] = True
                _add_log(f"Login OK @{un}")
            except Exception as e:
                msg = translate_ig_error(e)
                _add_log(f"Falha login @{un}: {msg}", "error")
                scrape_state["message"] = f"Falha login @{un}: {msg}"
                continue

            for tgt in my_targets:
                if _stopped():
                    break
                tu = tgt['username']
                scrape_state["message"] = f"Buscando @{tu}..."
                scrape_state["current"] = f"@{tu}"
                _add_log(f"Iniciando @{tu}...")

                try:
                    uid = cl.user_id_from_username(tu)
                except:
                    _add_log(f"@{tu} nao encontrado", "error")
                    continue

                try:
                    medias = cl.user_medias(uid, amount=cfg.get("posts_per_profile", 15))
                except Exception as e:
                    _add_log(f"Erro buscar @{tu}: {e}", "error")
                    continue

                scrape_state["total"] = len(medias)
                _add_log(f"@{tu}: {len(medias)} midias encontradas")

                folder = f"{DOWNLOADS_DIR}/{tu}"
                os.makedirs(folder, exist_ok=True)
                downloaded_count = 0

                for i, m in enumerate(medias):
                    if _stopped():
                        break
                    scrape_state["progress"] = i + 1

                    if is_downloaded(m.id):
                        continue

                    saved = _download_one(cl, tu, m, folder)
                    downloaded_count += len(saved)
                    if saved:
                        _human_delay_after(m)

                _add_log(f"@{tu}: {downloaded_count} baixados", "success")
                if _stopped():
                    break
                time.sleep(10 + random.random() * 10)

        if not scrape_state.get("stop_requested"):
            total_logs = sum(1 for l in scrape_state["logs"] if l["type"] == "success")
            scrape_state["message"] = f"Finalizado: {total_logs} downloads"
            _add_log("Scraping concluido", "success")
    except Exception as e:
        _add_log(f"Erro fatal no scraping: {e}", "error")
        scrape_state["message"] = f"Erro fatal: {e}"
    finally:
        scrape_state["running"] = False
        scrape_state["connected"] = False
        scrape_state["current"] = ""
        scrape_state["stop_requested"] = False

# ─── API ROUTES ───────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"ok": False, "msg": "Preencha todos os campos"})

    sf = f"{SESSIONS_DIR}/{username}.json"
    try:
        login_account({"username": username, "password": password}, sf)
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    upsert_account(username, password=password)

    global scrape_state
    scrape_state["connected"] = True
    scrape_state["current_account"] = username
    return jsonify({"ok": True, "msg": f"Conectado como @{username}", "username": username})

@app.route("/api/login-session", methods=["POST"])
def api_login_session():
    data = request.get_json() or {}
    sessionid = (data.get("sessionid") or "").strip()
    if not sessionid:
        return jsonify({"ok": False, "msg": "Cole o sessionid copiado do navegador"})

    try:
        cl = login_by_sessionid(sessionid)
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    username = cl.username
    cl.dump_settings(f"{SESSIONS_DIR}/{username}.json")
    upsert_account(username, sessionid=sessionid)

    global scrape_state
    scrape_state["connected"] = True
    scrape_state["current_account"] = username
    return jsonify({"ok": True, "msg": f"Conectado como @{username} (via sessao)", "username": username})

@app.route("/api/logout", methods=["POST"])
def api_logout():
    global scrape_state
    scrape_state["connected"] = False
    scrape_state["current_account"] = ""
    return jsonify({"ok": True})

@app.route("/api/session")
def api_session():
    return jsonify({"connected": scrape_state["connected"], "current_account": scrape_state["current_account"]})

@app.route("/api/accounts", methods=["GET", "POST", "DELETE"])
def api_accounts():
    if request.method == "GET":
        return jsonify(jload(ACCOUNTS_PATH))
    data = request.get_json()
    if request.method == "POST":
        accs = jload(ACCOUNTS_PATH)
        accs.setdefault("accounts", []).append({
            "username": data["username"], "password": data["password"],
            "active": True, "created_at": datetime.now().isoformat(), "last_use": None
        })
        jsave(ACCOUNTS_PATH, accs)
        return jsonify({"ok": True})
    if request.method == "DELETE":
        accs = jload(ACCOUNTS_PATH)
        idx = data.get("index")
        if idx is not None and 0 <= idx < len(accs.get("accounts", [])):
            del accs["accounts"][idx]
            jsave(ACCOUNTS_PATH, accs)
        return jsonify({"ok": True})

@app.route("/api/targets", methods=["GET", "POST", "DELETE"])
def api_targets():
    if request.method == "GET":
        return jsonify(jload(TARGETS_PATH))
    data = request.get_json()
    if request.method == "POST":
        t = jload(TARGETS_PATH)
        t.setdefault("targets", []).append({
            "username": data["username"], "priority": data.get("priority", 1),
            "active": True, "added_at": datetime.now().isoformat()
        })
        jsave(TARGETS_PATH, t)
        return jsonify({"ok": True})
    if request.method == "DELETE":
        t = jload(TARGETS_PATH)
        idx = data.get("index")
        if idx is not None and 0 <= idx < len(t.get("targets", [])):
            del t["targets"][idx]
            jsave(TARGETS_PATH, t)
        return jsonify({"ok": True})

@app.route("/api/toggle-account", methods=["POST"])
def api_toggle_account():
    data = request.get_json()
    accs = jload(ACCOUNTS_PATH)
    idx = data.get("index")
    if idx is not None and 0 <= idx < len(accs.get("accounts", [])):
        accs["accounts"][idx]["active"] = not accs["accounts"][idx].get("active", True)
        jsave(ACCOUNTS_PATH, accs)
    return jsonify({"ok": True})

@app.route("/api/toggle-target", methods=["POST"])
def api_toggle_target():
    data = request.get_json()
    t = jload(TARGETS_PATH)
    idx = data.get("index")
    if idx is not None and 0 <= idx < len(t.get("targets", [])):
        t["targets"][idx]["active"] = not t["targets"][idx].get("active", True)
        jsave(TARGETS_PATH, t)
    return jsonify({"ok": True})

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    global scrape_state
    if scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Scraping ja esta rodando"})
    data = request.get_json() or {}
    acc_idx = data.get("account_index")
    tgt_idx = data.get("target_index")
    acc_idx = int(acc_idx) if acc_idx not in (None, "") else None
    tgt_idx = int(tgt_idx) if tgt_idx not in (None, "") else None
    threading.Thread(target=_do_scrape, args=(acc_idx, tgt_idx), daemon=True).start()
    return jsonify({"ok": True, "msg": "Scraping iniciado!"})

@app.route("/api/preview", methods=["POST"])
def api_preview():
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    try:
        uid = cl.user_id_from_username(target_username)
        medias, end_cursor = cl.user_medias_paginated(uid, amount=PREVIEW_PAGE_SIZE)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar @{target_username}: {translate_ig_error(e)}"})

    cache_key = target_username
    preview_cache[cache_key] = {
        "cl": cl, "uid": uid, "medias": list(medias), "end_cursor": end_cursor,
        "kind": "post", "target": target_username, "label": f"@{target_username}",
        "folder": f"{DOWNLOADS_DIR}/{target_username}",
    }

    return jsonify({
        "ok": True,
        "items": [_media_preview_item(m) for m in medias],
        "cache_key": cache_key,
        "has_more": bool(end_cursor),
    })

@app.route("/api/preview-more", methods=["POST"])
def api_preview_more():
    data = request.get_json() or {}
    cache_key = (data.get("cache_key") or data.get("target_username") or "").strip()
    cache = preview_cache.get(cache_key)
    if not cache:
        return jsonify({"ok": False, "msg": "Preview expirado, busque de novo."})
    if not cache.get("end_cursor"):
        return jsonify({"ok": True, "items": [], "has_more": False})

    try:
        medias, end_cursor = cache["cl"].user_medias_paginated(
            cache["uid"], amount=PREVIEW_PAGE_SIZE, end_cursor=cache["end_cursor"])
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar mais midias: {translate_ig_error(e)}"})

    cache["medias"].extend(medias)
    cache["end_cursor"] = end_cursor

    return jsonify({
        "ok": True,
        "items": [_media_preview_item(m) for m in medias],
        "has_more": bool(end_cursor),
    })

@app.route("/api/stories", methods=["POST"])
def api_stories():
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    try:
        uid = cl.user_id_from_username(target_username)
        stories = cl.user_stories(uid)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar stories de @{target_username}: {translate_ig_error(e)}"})

    cache_key = f"{target_username}:stories"
    preview_cache[cache_key] = {
        "cl": cl, "medias": list(stories), "kind": "story",
        "target": target_username, "label": f"@{target_username} (stories)",
        "folder": f"{DOWNLOADS_DIR}/{target_username}/stories",
    }

    msg = None if stories else "Sem stories ativos agora (expiram em 24h)"
    return jsonify({"ok": True, "items": [_story_preview_item(s) for s in stories], "cache_key": cache_key, "msg": msg})

@app.route("/api/highlights", methods=["POST"])
def api_highlights():
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    try:
        uid = cl.user_id_from_username(target_username)
        highlights = cl.user_highlights(uid)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar destaques de @{target_username}: {translate_ig_error(e)}"})

    items = [{
        "id": str(h.pk),
        "title": h.title or "Destaque",
        "cover": _highlight_cover_url(h.cover_media),
        "count": h.media_count,
    } for h in highlights]
    return jsonify({"ok": True, "items": items, "target": target_username})

@app.route("/api/highlight-items", methods=["POST"])
def api_highlight_items():
    data = request.get_json() or {}
    highlight_id = str(data.get("highlight_id") or "").strip()
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    title = (data.get("title") or "").strip()
    if not highlight_id or not target_username:
        return jsonify({"ok": False, "msg": "Dados invalidos"})

    try:
        cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": translate_ig_error(e)})

    try:
        fetched_title, items = _fetch_highlight_items_raw(cl, highlight_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao abrir destaque: {translate_ig_error(e)}"})

    display_title = title or fetched_title
    cache_key = f"highlight:{highlight_id}"
    preview_cache[cache_key] = {
        "cl": cl, "medias": items, "kind": "story",
        "target": target_username, "label": f"@{target_username} › {display_title}",
        "folder": f"{DOWNLOADS_DIR}/{target_username}/highlights/{_safe_name(display_title)}",
    }

    return jsonify({"ok": True, "items": [_story_preview_item(s) for s in items], "cache_key": cache_key})

@app.route("/api/download-selected", methods=["POST"])
def api_download_selected():
    global scrape_state
    if scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Scraping ja esta rodando"})
    data = request.get_json() or {}
    cache_key = (data.get("cache_key") or data.get("target_username") or "").strip()
    ids = set(str(i) for i in data.get("media_ids", []))
    cache = preview_cache.get(cache_key)
    if not cache or not ids:
        return jsonify({"ok": False, "msg": "Nada selecionado ou preview expirado. Busque de novo."})

    selected = [m for m in cache["medias"] if str(m.id) in ids]
    if not selected:
        return jsonify({"ok": False, "msg": "Selecao invalida, busque de novo."})

    threading.Thread(target=_do_selected_download, args=(cache, selected), daemon=True).start()
    return jsonify({"ok": True, "msg": f"Baixando {len(selected)} selecionados..."})

def _do_selected_download(cache, medias):
    global scrape_state
    cl = cache["cl"]
    folder = cache["folder"]
    kind = cache.get("kind", "post")
    label = cache.get("label", "selecionados")
    tu = cache.get("target", "midia").lstrip("@") or "midia"
    downloader = _download_one if kind == "post" else _download_story_item

    scrape_state.update(running=True, connected=True, current_account=getattr(cl, "username", "") or "",
                        message=f"Baixando selecionados de {label}...", progress=0,
                        total=len(medias), current=label, logs=[], stop_requested=False,
                        zip_url=None)
    os.makedirs(folder, exist_ok=True)
    all_saved = []
    try:
        for i, m in enumerate(medias):
            if _stopped():
                break
            scrape_state["progress"] = i + 1
            if is_downloaded(m.id):
                continue
            saved = downloader(cl, tu, m, folder)
            all_saved.extend(saved)
            if saved:
                _human_delay_after(m)

        if not scrape_state.get("stop_requested"):
            zip_url = _make_zip(tu, all_saved)
            scrape_state["zip_url"] = zip_url
            done_msg = f"Finalizado: {len(all_saved)} arquivos baixados"
            scrape_state["message"] = done_msg + (" (zip pronto)" if zip_url else "")
            _add_log("Download dos selecionados concluido", "success")
    except Exception as e:
        _add_log(f"Erro fatal: {e}", "error")
        scrape_state["message"] = f"Erro fatal: {e}"
    finally:
        scrape_state["running"] = False
        scrape_state["connected"] = False
        scrape_state["current"] = ""
        scrape_state["stop_requested"] = False

@app.route("/api/stop", methods=["POST"])
def api_stop():
    global scrape_state
    if not scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Nenhum scraping em andamento"})
    scrape_state["stop_requested"] = True
    scrape_state["message"] = "Parando..."
    return jsonify({"ok": True, "msg": "Interrompendo scraping..."})

@app.route("/api/status")
def api_status():
    return jsonify(scrape_state)

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(get_cfg())
    data = request.get_json()
    cfg = get_cfg()
    cfg.update(data)
    jsave(CONFIG_PATH, cfg)
    return jsonify({"ok": True})

@app.route("/api/downloads")
def api_downloads():
    rows = db_query("SELECT file, username, type, date, downloaded_at FROM downloads ORDER BY downloaded_at DESC LIMIT 100")
    files = []
    for r in rows:
        uname, fname = r[1], r[0]
        fpath = f"{DOWNLOADS_DIR}/{uname}/{fname}"
        files.append({
            "username": uname, "file": fname, "type": r[2], "date": r[3],
            "exists": os.path.exists(fpath),
            "url": f"/downloads/{uname}/{fname}"
        })
    return jsonify(files)

@app.route("/api/reset")
def api_reset():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS downloads")
    c.execute("DROP TABLE IF EXISTS accounts_stats")
    conn.commit()
    conn.close()
    init_db()
    return jsonify({"ok": True})

@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory(DOWNLOADS_DIR, filename)

@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    init_db()
    init_files()
    print("\n" + "=" * 55)
    print("  IG-SCRAPER-PRO v4.0  |  WEB DASHBOARD")
    print("=" * 55)
    print("  http://localhost:5000")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
