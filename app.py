#!/usr/bin/env python3
"""
IG-SCRAPER-PRO - Servidor Web Flask
Rode: python app.py
Acesse: http://localhost:5000
"""

import os
import json
import time
import threading
import sqlite3
from datetime import datetime, timedelta

from flask import Flask, render_template, request, jsonify, send_from_directory, redirect, url_for
from instagrapi import Client
from instagrapi.exceptions import LoginRequired, PleaseWaitFewMinutes, ClientError

app = Flask(__name__)

DOWNLOADS_DIR = "downloads"
SESSIONS_DIR = "sessions"
DB_PATH = "scraper.db"
CONFIG_PATH = "config.json"
ACCOUNTS_PATH = "accounts.json"
TARGETS_PATH = "targets.json"

os.makedirs(DOWNLOADS_DIR, exist_ok=True)
os.makedirs(SESSIONS_DIR, exist_ok=True)

# ─── DB ──────────────────────────────────────────────────────────────────────
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

def reset_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("DROP TABLE IF EXISTS downloads")
    c.execute("DROP TABLE IF EXISTS accounts_stats")
    conn.commit()
    conn.close()
    init_db()

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
    r = db_query("SELECT id FROM downloads WHERE media_id=?", (media_id,))
    return len(r) > 0

def add_download(data):
    try:
        db_query("INSERT INTO downloads (media_id, username, file, type, date) VALUES (?,?,?,?,?)",
                 (data['media_id'], data['username'], data['file'], data['type'], data['date']), fetch=False)
        db_query("INSERT INTO accounts_stats (username, total_downloads, last_use) VALUES (?,1,?) ON CONFLICT(username) DO UPDATE SET total_downloads=total_downloads+1, last_use=?",
                 (data['username'], datetime.now().isoformat(), datetime.now().isoformat()), fetch=False)
    except sqlite3.IntegrityError:
        pass

# ─── HELPERS ─────────────────────────────────────────────────────────────────
def load_json(path, default=None):
    if os.path.exists(path):
        with open(path) as f:
            return json.load(f)
    return default if default is not None else {}

def save_json(path, data):
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)

def init_default_files():
    if not os.path.exists(ACCOUNTS_PATH): save_json(ACCOUNTS_PATH, {"accounts": []})
    if not os.path.exists(TARGETS_PATH): save_json(TARGETS_PATH, {"targets": []})
    if not os.path.exists(CONFIG_PATH):
        save_json(CONFIG_PATH, {
            "delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
            "max_retries": 3, "auto_mode": False, "auto_interval": 3600,
            "max_downloads_per_day": 500
        })

def get_config():
    return load_json(CONFIG_PATH, {
        "delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
        "max_retries": 3, "auto_mode": False, "auto_interval": 3600,
        "max_downloads_per_day": 500
    })

def get_stats():
    total = db_query("SELECT COUNT(*) FROM downloads")[0][0]
    profiles = db_query("SELECT COUNT(DISTINCT username) FROM downloads")[0][0]
    last = db_query("SELECT MAX(downloaded_at) FROM downloads")[0][0]
    try:
        import shutil
        du = shutil.disk_usage(DOWNLOADS_DIR)
        disk = f"{du.used/(1024**3):.1f} GB"
    except:
        disk = "N/A"
    return {"total": total, "profiles": profiles, "last_download": last, "disk_usage": disk}

# ─── SCRAPER ─────────────────────────────────────────────────────────────────
scraping_status = {"running": False, "message": "Parado", "progress": 0, "total": 0, "current": "", "results": []}

def scrape_thread(account_index=None):
    global scraping_status
    scraping_status = {"running": True, "message": "Iniciando...", "progress": 0, "total": 0, "current": "", "results": []}

    config = get_config()
    accounts = load_json(ACCOUNTS_PATH).get("accounts", [])
    targets = load_json(TARGETS_PATH).get("targets", [])

    if not accounts:
        scraping_status["message"] = "Nenhuma conta cadastrada"
        scraping_status["running"] = False
        return
    if not targets:
        scraping_status["message"] = "Nenhum perfil alvo cadastrado"
        scraping_status["running"] = False
        return

    accs = [accounts[account_index]] if account_index is not None else accounts
    active_targets = [t for t in targets if t.get("active", True)]

    for acc in accs:
        if not acc.get("active", True):
            continue

        scraping_status["message"] = f"Logando em @{acc['username']}..."
        cl = Client()
        cl.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")

        try:
            sf = f"{SESSIONS_DIR}/{acc['username']}.json"
            if os.path.exists(sf):
                try:
                    cl.load_settings(sf)
                    cl.login(acc['username'], acc['password'])
                except:
                    cl.login(acc['username'], acc['password'])
                    cl.dump_settings(sf)
            else:
                cl.login(acc['username'], acc['password'])
                cl.dump_settings(sf)
        except Exception as e:
            scraping_status["results"].append({"type": "error", "msg": f"Login falhou @{acc['username']}: {e}"})
            continue

        for t in active_targets:
            uname = t['username']
            try:
                uid = cl.user_id_from_username(uname)
            except:
                scraping_status["results"].append({"type": "error", "msg": f"@{uname} nao encontrado"})
                continue

            try:
                medias = cl.user_medias(uid, amount=config.get("posts_per_profile", 15))
            except:
                scraping_status["results"].append({"type": "error", "msg": f"Erro ao buscar @{uname}"})
                continue

            total = len(medias)
            scraping_status["message"] = f"Scrapando @{uname}"
            scraping_status["total"] = total

            folder = f"{DOWNLOADS_DIR}/{uname}"
            os.makedirs(folder, exist_ok=True)

            for i, m in enumerate(medias):
                scraping_status["progress"] = i + 1
                scraping_status["current"] = f"@{uname}"

                if is_downloaded(m.id):
                    continue

                date_str = m.taken_at.strftime("%Y%m%d_%H%M%S")
                try:
                    if m.media_type == 1:
                        path = cl.photo_download(m.id, folder=folder, filename=f"{uname}_{date_str}")
                        mtype = 'photo'
                    elif m.media_type == 2:
                        path = cl.video_download(m.id, folder=folder, filename=f"{uname}_{date_str}")
                        mtype = 'video'
                    elif m.media_type == 8:
                        resources = cl.media_resources(m.id)
                        for j, res in enumerate(resources):
                            try:
                                if res.media_type == 1:
                                    path = cl.photo_download(res.id, folder=folder, filename=f"{uname}_{date_str}_c{j}")
                                    mtype = 'photo'
                                else:
                                    path = cl.video_download(res.id, folder=folder, filename=f"{uname}_{date_str}_c{j}")
                                    mtype = 'video'
                                add_download({'media_id': res.id, 'username': uname, 'file': os.path.basename(path), 'type': mtype, 'date': m.taken_at.isoformat()})
                                scraping_status["results"].append({"type": "success", "msg": f"Download: {os.path.basename(path)}"})
                            except:
                                pass
                        continue

                    add_download({'media_id': m.id, 'username': uname, 'file': os.path.basename(path), 'type': mtype, 'date': m.taken_at.isoformat()})
                    scraping_status["results"].append({"type": "success", "msg": f"Download: {os.path.basename(path)}"})

                    if m.media_type == 2 and hasattr(m, 'video_duration'):
                        time.sleep(min(m.video_duration + 3, 60))
                    else:
                        time.sleep(3 + __import__('random').random() * 7)

                except PleaseWaitFewMinutes:
                    time.sleep(300)
                except ClientError as e:
                    if "429" in str(e):
                        time.sleep(120)
                    else:
                        scraping_status["results"].append({"type": "error", "msg": str(e)})
                except Exception as e:
                    scraping_status["results"].append({"type": "error", "msg": str(e)})

            scraping_status["message"] = f"✅ @{uname} concluido!"
            time.sleep(10)

    scraping_status["running"] = False
    scraping_status["message"] = "✅ Concluido!"

# ─── ROTAS API ───────────────────────────────────────────────────────────────
@app.route("/api/login", methods=["POST"])
def api_login():
    data = request.get_json()
    username = data.get("username", "").strip()
    password = data.get("password", "").strip()

    if not username or not password:
        return jsonify({"ok": False, "msg": "Preencha todos os campos"})

    cl = Client()
    cl.set_user_agent("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36")
    try:
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

        # Salva/atualiza nos JSON
        accs = load_json(ACCOUNTS_PATH)
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
        save_json(ACCOUNTS_PATH, accs)

        return jsonify({"ok": True, "msg": f"✅ Login OK! @{username}"})
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e)})

@app.route("/api/accounts", methods=["GET", "POST", "DELETE"])
def api_accounts():
    path = ACCOUNTS_PATH
    if request.method == "GET":
        return jsonify(load_json(path))

    data = request.get_json()
    if request.method == "POST":
        accs = load_json(path)
        accs.setdefault("accounts", []).append({
            "username": data["username"], "password": data["password"],
            "active": True, "created_at": datetime.now().isoformat(), "last_use": None
        })
        save_json(path, accs)
        return jsonify({"ok": True})

    if request.method == "DELETE":
        accs = load_json(path)
        idx = data.get("index")
        if idx is not None and 0 <= idx < len(accs.get("accounts", [])):
            del accs["accounts"][idx]
            save_json(path, accs)
        return jsonify({"ok": True})

@app.route("/api/targets", methods=["GET", "POST", "DELETE"])
def api_targets():
    path = TARGETS_PATH
    if request.method == "GET":
        return jsonify(load_json(path))

    data = request.get_json()
    if request.method == "POST":
        t = load_json(path)
        t.setdefault("targets", []).append({
            "username": data["username"], "priority": data.get("priority", 1),
            "active": True, "added_at": datetime.now().isoformat()
        })
        save_json(path, t)
        return jsonify({"ok": True})

    if request.method == "DELETE":
        t = load_json(path)
        idx = data.get("index")
        if idx is not None and 0 <= idx < len(t.get("targets", [])):
            del t["targets"][idx]
            save_json(path, t)
        return jsonify({"ok": True})

@app.route("/api/toggle-account", methods=["POST"])
def api_toggle_account():
    data = request.get_json()
    accs = load_json(ACCOUNTS_PATH)
    idx = data.get("index")
    if idx is not None and 0 <= idx < len(accs.get("accounts", [])):
        accs["accounts"][idx]["active"] = not accs["accounts"][idx].get("active", True)
        save_json(ACCOUNTS_PATH, accs)
    return jsonify({"ok": True})

@app.route("/api/toggle-target", methods=["POST"])
def api_toggle_target():
    data = request.get_json()
    t = load_json(TARGETS_PATH)
    idx = data.get("index")
    if idx is not None and 0 <= idx < len(t.get("targets", [])):
        t["targets"][idx]["active"] = not t["targets"][idx].get("active", True)
        save_json(TARGETS_PATH, t)
    return jsonify({"ok": True})

@app.route("/api/scrape", methods=["POST"])
def api_scrape():
    global scraping_status
    if scraping_status.get("running"):
        return jsonify({"ok": False, "msg": "Scraping ja esta rodando"})

    data = request.get_json() or {}
    idx = data.get("account_index")
    threading.Thread(target=scrape_thread, args=(idx,), daemon=True).start()
    return jsonify({"ok": True, "msg": "Scraping iniciado!"})

@app.route("/api/status")
def api_status():
    return jsonify(scraping_status)

@app.route("/api/stats")
def api_stats():
    stats = get_stats()
    # Top profiles
    rows = db_query("SELECT username, COUNT(*) as cnt FROM downloads GROUP BY username ORDER BY cnt DESC LIMIT 10")
    stats["top_profiles"] = [{"username": r[0], "count": r[1]} for r in rows]
    # Recent downloads
    rows = db_query("SELECT file, username, type, downloaded_at FROM downloads ORDER BY downloaded_at DESC LIMIT 20")
    stats["recent"] = [{"file": r[0], "profile": r[1], "type": r[2], "date": r[3]} for r in rows]
    # Daily chart (last 7 days)
    rows = db_query("SELECT DATE(downloaded_at) as day, COUNT(*) as cnt FROM downloads WHERE downloaded_at >= DATE('now', '-7 days') GROUP BY day ORDER BY day")
    stats["daily"] = {r[0]: r[1] for r in rows}
    return jsonify(stats)

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(get_config())

    data = request.get_json()
    cfg = get_config()
    cfg.update(data)
    save_json(CONFIG_PATH, cfg)
    return jsonify({"ok": True})

@app.route("/api/downloads")
def api_downloads():
    rows = db_query("SELECT file, username, type, date, downloaded_at FROM downloads ORDER BY downloaded_at DESC LIMIT 100")
    files = []
    for r in rows:
        uname = r[1]
        fname = r[0]
        fpath = f"{DOWNLOADS_DIR}/{uname}/{fname}"
        files.append({
            "username": uname, "file": fname, "type": r[2], "date": r[3],
            "exists": os.path.exists(fpath),
            "url": f"/downloads/{uname}/{fname}"
        })
    return jsonify(files)

@app.route("/api/reset")
def api_reset():
    reset_db()
    return jsonify({"ok": True})

@app.route("/downloads/<path:filename>")
def serve_download(filename):
    return send_from_directory(DOWNLOADS_DIR, filename)

@app.route("/api/clear-targets", methods=["POST"])
def api_clear_targets():
    save_json(TARGETS_PATH, {"targets": []})
    return jsonify({"ok": True})

@app.route("/api/clear-accounts", methods=["POST"])
def api_clear_accounts():
    save_json(ACCOUNTS_PATH, {"accounts": []})
    return jsonify({"ok": True})

# ─── PAGINAS ─────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html")

if __name__ == "__main__":
    init_db()
    init_default_files()
    print("\n" + "="*55)
    print("  📸  IG-SCRAPER-PRO v3.0  -  WEB DASHBOARD")
    print("="*55)
    print(f"  🌐  http://localhost:5000")
    print(f"  🌐  http://127.0.0.1:5000")
    print("="*55 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
