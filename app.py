#!/usr/bin/env python3
"""
IG-SCRAPER-PRO v4.0 - Web Dashboard
python app.py  ->  http://localhost:5000
"""

import os, json, time, threading, sqlite3, random
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory

app = Flask(__name__)

DOWNLOADS_DIR = "downloads"
SESSIONS_DIR = "sessions"
DB_PATH = "scraper.db"
ACCOUNTS_PATH = "accounts.json"
TARGETS_PATH = "targets.json"
CONFIG_PATH = "config.json"

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

# ─── SCRAPING ENGINE ──────────────────────────────────────────────────────────
scrape_state = {"running": False, "connected": False, "current_account": "",
                "message": "Pronto", "progress": 0, "total": 0, "current": "", "logs": []}

def _add_log(msg, typ="info"):
    scrape_state["logs"].append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": typ})
    if len(scrape_state["logs"]) > 100:
        scrape_state["logs"] = scrape_state["logs"][-50:]

def _do_scrape(account_index=None):
    global scrape_state
    scrape_state.update(running=True, connected=False, current_account="",
                        message="Ligando motor...", progress=0, total=0, current="", logs=[])

    cfg = get_cfg()
    accounts = jload(ACCOUNTS_PATH).get("accounts", [])
    targets = jload(TARGETS_PATH).get("targets", [])

    if not accounts:
        scrape_state["message"] = "Erro: Nenhuma conta cadastrada"
        scrape_state["running"] = False
        _add_log("Nenhuma conta cadastrada", "error")
        return
    if not targets:
        scrape_state["message"] = "Erro: Nenhum perfil alvo cadastrado"
        scrape_state["running"] = False
        _add_log("Nenhum perfil alvo cadastrado", "error")
        return

    accs = [accounts[account_index]] if account_index is not None else accounts
    active_targets = [t for t in targets if t.get("active", True)]

    if not active_targets:
        scrape_state["message"] = "Erro: Nenhum alvo ativo"
        scrape_state["running"] = False
        _add_log("Nenhum alvo ativo", "error")
        return

    for acc in accs:
        if not acc.get("active", True):
            continue

        un = acc['username']
        pw = acc['password']
        scrape_state["current_account"] = un
        scrape_state["message"] = f"Conectando @{un}..."
        _add_log(f"Tentando login em @{un}...")

        cl_global = None
        # Tentar importar instagrapi
        try:
            from instagrapi import Client as IGClient
            from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, ClientError
            cl = IGClient()
            cl.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
            sf = f"{SESSIONS_DIR}/{un}.json"
            if os.path.exists(sf):
                try:
                    cl.load_settings(sf)
                    cl.login(un, pw)
                except:
                    cl.login(un, pw)
                    cl.dump_settings(sf)
            else:
                cl.login(un, pw)
                cl.dump_settings(sf)

            scrape_state["connected"] = True
            _add_log(f"Login OK @{un}")
        except Exception as e:
            _add_log(f"Falha login @{un}: {e}", "error")
            scrape_state["message"] = f"Falha login @{un}"
            continue

        for tgt in active_targets:
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
                scrape_state["progress"] = i + 1

                if is_downloaded(m.id):
                    continue

                date_str = m.taken_at.strftime("%Y%m%d_%H%M%S")
                path = None

                try:
                    if m.media_type == 1:
                        path = cl.photo_download(m.id, folder=folder, filename=f"{tu}_{date_str}")
                        mtype = 'photo'
                    elif m.media_type == 2:
                        path = cl.video_download(m.id, folder=folder, filename=f"{tu}_{date_str}")
                        mtype = 'video'
                    elif m.media_type == 8:  # carousel
                        resources = cl.media_resources(m.id)
                        for j, res in enumerate(resources):
                            try:
                                if res.media_type == 1:
                                    path = cl.photo_download(res.id, folder=folder, filename=f"{tu}_{date_str}_c{j}")
                                    mtype = 'photo'
                                else:
                                    path = cl.video_download(res.id, folder=folder, filename=f"{tu}_{date_str}_c{j}")
                                    mtype = 'video'
                                add_download({'media_id': res.id, 'username': tu, 'file': os.path.basename(path), 'type': mtype, 'date': m.taken_at.isoformat()})
                                downloaded_count += 1
                                _add_log(f"Download: {os.path.basename(path)}", "success")
                            except:
                                pass
                        continue

                    add_download({'media_id': m.id, 'username': tu, 'file': os.path.basename(path), 'type': mtype, 'date': m.taken_at.isoformat()})
                    downloaded_count += 1
                    _add_log(f"Download: {os.path.basename(path)}", "success")

                    if m.media_type == 2 and hasattr(m, 'video_duration'):
                        time.sleep(min(m.video_duration + 3, 60))
                    else:
                        time.sleep(3 + random.random() * 7)

                except Exception as e:
                    es = str(e)
                    _add_log(f"Erro: {es[:80]}", "error")
                    if "429" in es:
                        time.sleep(120)
                    elif "PleaseWaitFewMinutes" in es:
                        time.sleep(300)
                    continue

            _add_log(f"@{tu}: {downloaded_count} baixados", "success")
            time.sleep(10 + random.random() * 10)

    total_logs = sum(1 for l in scrape_state["logs"] if l["type"] == "success")
    scrape_state["running"] = False
    scrape_state["connected"] = False
    scrape_state["current"] = ""
    scrape_state["message"] = f"Finalizado: {total_logs} downloads"
    _add_log("Scraping concluido", "success")

# ─── API ROUTES ───────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()
    if not username or not password:
        return jsonify({"ok": False, "msg": "Preencha todos os campos"})

    try:
        from instagrapi import Client as IGClient
        cl = IGClient()
        cl.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
        sf = f"{SESSIONS_DIR}/{username}.json"
        if os.path.exists(sf):
            try:
                cl.load_settings(sf)
                cl.login(username, password)
            except:
                cl.login(username, password)
                cl.dump_settings(sf)
        else:
            cl.login(username, password)
            cl.dump_settings(sf)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Falha no login: {e}"})

    accs = jload(ACCOUNTS_PATH)
    found = False
    for a in accs.get("accounts", []):
        if a["username"] == username:
            a["last_use"] = datetime.now().isoformat()
            a["active"] = True
            found = True
            break
    if not found:
        accs.setdefault("accounts", []).append({
            "username": username, "password": password, "active": True,
            "created_at": datetime.now().isoformat(), "last_use": datetime.now().isoformat()
        })
    jsave(ACCOUNTS_PATH, accs)

    global scrape_state
    scrape_state["connected"] = True
    scrape_state["current_account"] = username
    return jsonify({"ok": True, "msg": f"Conectado como @{username}", "username": username})

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
    idx = data.get("account_index")
    threading.Thread(target=_do_scrape, args=(idx,), daemon=True).start()
    return jsonify({"ok": True, "msg": "Scraping iniciado!"})

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
