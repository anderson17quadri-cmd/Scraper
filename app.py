#!/usr/bin/env python3
"""
IG-SCRAPER-PRO v4.0 - Web Dashboard
python app.py  ->  http://localhost:5000
"""

import os, sys, json, time, threading, sqlite3, random, zipfile, re, itertools
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from flask import Flask, render_template, request, jsonify, send_from_directory, Response
from ig_auth import login_account, login_by_sessionid, translate_ig_error
from ig_engine_iloader import (login_iloader_account, login_iloader_sessionid, translate_iloader_error,
                               _parse_cookies as _parse_cookie_string,
                               post_preview_item as _iloader_preview_item,
                               download_post as _iloader_download_post,
                               story_preview_item as _iloader_story_item,
                               download_story_item as _iloader_download_story,
                               fetch_stories as _iloader_fetch_stories,
                               fetch_highlights as _iloader_fetch_highlights,
                               highlight_summary as _iloader_highlight_summary)
import instaloader

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
    c.execute("""CREATE TABLE IF NOT EXISTS error_log (
        id INTEGER PRIMARY KEY AUTOINCREMENT, message TEXT, occurred_at TEXT DEFAULT CURRENT_TIMESTAMP)""")
    c.execute("CREATE INDEX IF NOT EXISTS idx_username ON downloads(username)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_downloaded_at ON downloads(downloaded_at)")
    c.execute("CREATE INDEX IF NOT EXISTS idx_error_occurred_at ON error_log(occurred_at)")
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
                            "auto_interval": 3600, "max_downloads_per_day": 500,
                            "auto_mode": False, "quality": "max"})

def get_cfg():
    return jload(CONFIG_PATH, {"delay_min": 3, "delay_max": 10, "posts_per_profile": 15,
                                "auto_interval": 3600, "max_downloads_per_day": 500,
                                "auto_mode": False, "quality": "max"})

def upsert_account(username, password=None, sessionid=None, engine=None):
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
    if engine in ("instagrapi", "instaloader"):
        acc["engine"] = engine
    acc["active"] = True
    acc["last_use"] = datetime.now().isoformat()
    jsave(ACCOUNTS_PATH, accs)

# ─── SCRAPING ENGINE ──────────────────────────────────────────────────────────
scrape_state = {"running": False, "connected": False, "current_account": "",
                "message": "Pronto", "progress": 0, "total": 0, "current": "", "logs": [],
                "stop_requested": False, "zip_url": None, "speed": "", "speed_avg": "",
                "failed_count": 0, "started_at": None}

# midias que falharam na ultima leva de downloads, agrupadas por
# conta/alvo/pasta, pra dar pra tentar de novo so essas (ver /api/retry-failed)
last_failed_groups = []

# cache em memoria: cache_key -> {"cl":.., "medias":[...], "kind": "post"|"story",
# "target":.., "label":.., "folder":.., "uid":.. , "end_cursor":..}
# preenchido por /api/preview*, /api/stories e /api/highlight-items;
# consumido por /api/download-selected
preview_cache = {}
PREVIEW_PAGE_SIZE = 30

# (username-alvo, id do client) -> {unique_id: objeto Highlight do Instaloader}
# Guardado porque o Instaloader so entrega os itens de um destaque a partir
# do proprio objeto Highlight -- nao da pra buscar so por id depois.
iloader_highlights = {}

# (conta-nossa, motor) -> Client/Instaloader ja autenticado, reaproveitado
# entre chamadas de preview/stories/destaques pra nao relogar toda hora
active_clients = {}

def _get_client(acc_idx):
    """Retorna (engine, client) da conta escolhida (ou a primeira ativa se
    nenhum indice for passado). engine e 'instagrapi' ou 'instaloader'."""
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
    engine = acc.get("engine", "instagrapi")
    key = (un, engine)
    cl = active_clients.get(key)
    if cl is None:
        if engine == "instaloader":
            cl = login_iloader_account(acc, f"{SESSIONS_DIR}/{un}.iloader")
        else:
            cl = login_account(acc, f"{SESSIONS_DIR}/{un}.json")
        active_clients[key] = cl
    return engine, cl

def _translate_any_error(e):
    """translate_ig_error() so conhece excecoes do instagrapi -- se for
    uma excecao do Instaloader, usa o tradutor dele em vez disso."""
    import instaloader.exceptions as _iloader_exc
    if isinstance(e, _iloader_exc.InstaloaderException):
        return translate_iloader_error(e)
    return translate_ig_error(e)

def _safe_name(s):
    return re.sub(r'[^\w\-. ]', '_', str(s)).strip()[:60] or "destaque"

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

def _make_zip(target, items):
    """items: lista de caminhos (ficam soltos na raiz do zip) OU de
    tuplas (caminho, subpasta) pra organizar em pastas dentro do zip
    (ex: "posts", "reels", "stories", "destaques/Viagens") -- usado pelo
    "Baixar tudo", que junta varias categorias num zip so."""
    pairs = []
    for it in items:
        path, subfolder = it if isinstance(it, tuple) else (it, None)
        if path and os.path.exists(path):
            pairs.append((path, subfolder))
    if not pairs:
        return None
    os.makedirs(ZIPS_DIR, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    zip_path = f"{ZIPS_DIR}/{target}_{ts}.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for path, subfolder in pairs:
            arcname = f"{subfolder}/{os.path.basename(path)}" if subfolder else os.path.basename(path)
            zf.write(path, arcname=arcname)
    return f"/downloads/_zips/{os.path.basename(zip_path)}"

def _add_log(msg, typ="info"):
    scrape_state["logs"].append({"time": datetime.now().strftime("%H:%M:%S"), "msg": msg, "type": typ})
    if len(scrape_state["logs"]) > 100:
        scrape_state["logs"] = scrape_state["logs"][-50:]
    if typ == "error":
        # o log da tela some quando a sessao acaba -- grava os erros no
        # banco tambem, pra ter um historico que sobrevive a isso
        try:
            db_query("INSERT INTO error_log (message) VALUES (?)", (msg,), fetch=False)
        except Exception:
            pass

@app.after_request
def _log_error_responses(response):
    """Grava no historico QUALQUER resposta de erro da API (nao so as do
    fluxo de scraping, que ja passam por _add_log) -- pega tambem os erros
    das rotas de busca/preview/login, que respondem {"ok": false, "msg":...}
    direto sem passar pelo log. Um unico lugar cobre o app inteiro."""
    try:
        if response.is_json:
            data = response.get_json(silent=True)
            if isinstance(data, dict) and data.get("ok") is False and data.get("msg"):
                db_query("INSERT INTO error_log (message) VALUES (?)", (str(data["msg"])[:500],), fetch=False)
    except Exception:
        pass
    return response

def _stopped():
    if scrape_state.get("stop_requested"):
        _add_log("Scraping interrompido pelo usuario", "error")
        scrape_state["message"] = "Interrompido pelo usuario"
        return True
    return False

def _pick_lower_res_url(candidates, target_width=720):
    """candidates: lista de objetos/dicts com largura+url (candidatos de
    resolucao que o Instagram oferece pra mesma midia). Escolhe o mais
    proximo de target_width sem cortar demais -- pega a primeira igual
    ou maior que o alvo, senao a maior disponivel mesmo."""
    def w(c):
        return (c.get("width") if isinstance(c, dict) else getattr(c, "width", 0)) or 0
    def u(c):
        return c.get("url") if isinstance(c, dict) else getattr(c, "url", None)
    usable = [c for c in candidates if u(c)]
    if not usable:
        return None
    usable.sort(key=w)
    for c in usable:
        if w(c) >= target_width:
            return str(u(c))
    return str(u(usable[-1]))

def _eco_photo_url(m):
    """Resolucao menor de uma foto, quando disponivel (modo "Economizar
    espaco" de Ajustes) -- os candidatos ja vem junto com a midia, sem
    precisar de requisicao extra."""
    cands = getattr(getattr(m, "image_versions2", None), "candidates", None)
    if cands:
        url = _pick_lower_res_url(cands)
        if url:
            return url
    return m.thumbnail_url

def _eco_video_url(cl, m):
    """Resolucao menor de um video, quando disponivel. O objeto Media ja
    processado pelo instagrapi so guarda a URL da melhor qualidade -- os
    candidatos menores so vem numa chamada extra (so faz essa chamada a
    mais quando "Economizar espaco" esta ativo, e cai pra qualidade
    maxima de qualquer jeito se a chamada falhar por algum motivo)."""
    try:
        cl.private_request(f"media/{m.pk}/info/")
        raw = (cl.last_json or {}).get("items", [{}])[0]
        url = _pick_lower_res_url(raw.get("video_versions") or [])
        if url:
            return url
    except Exception:
        pass
    return m.video_url

def _download_one(cl, tu, m, folder):
    """Baixa uma midia (foto/video/carrossel) na resolucao configurada
    em Ajustes (maxima por padrao). Retorna a lista de caminhos salvos."""
    date_str = m.taken_at.strftime("%Y%m%d_%H%M%S")
    eco = get_cfg().get("quality") == "eco"
    saved_paths = []
    try:
        if m.media_type == 1:
            url = _eco_photo_url(m) if eco else m.thumbnail_url
            path = _timed_download(cl.photo_download_by_url, url, filename=f"{tu}_{date_str}", folder=folder)
            add_download({'media_id': m.id, 'username': tu, 'file': os.path.basename(path), 'type': 'photo', 'date': m.taken_at.isoformat()})
            _add_log(f"Download: {os.path.basename(path)}", "success")
            saved_paths.append(str(path))
        elif m.media_type == 2:
            url = _eco_video_url(cl, m) if eco else m.video_url
            path = _timed_download(cl.video_download_by_url, url, filename=f"{tu}_{date_str}", folder=folder)
            add_download({'media_id': m.id, 'username': tu, 'file': os.path.basename(path), 'type': 'video', 'date': m.taken_at.isoformat()})
            _add_log(f"Download: {os.path.basename(path)}", "success")
            saved_paths.append(str(path))
        elif m.media_type == 8:  # carousel
            for j, res in enumerate(m.resources):
                try:
                    if res.media_type == 1:
                        path = _timed_download(cl.photo_download_by_url, res.thumbnail_url, filename=f"{tu}_{date_str}_c{j}", folder=folder)
                        rtype = 'photo'
                    else:
                        path = _timed_download(cl.video_download_by_url, res.video_url, filename=f"{tu}_{date_str}_c{j}", folder=folder)
                        rtype = 'video'
                    add_download({'media_id': res.pk, 'username': tu, 'file': os.path.basename(path), 'type': rtype, 'date': m.taken_at.isoformat()})
                    _add_log(f"Download: {os.path.basename(path)}", "success")
                    saved_paths.append(str(path))
                except Exception:
                    pass
            # legenda e uma so pro carrossel inteiro, nao por item
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
        path = _timed_download(cl.story_download_by_url, url, filename=f"{tu}_story_{date_str}", folder=folder)
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
    """Pausa entre downloads, usando os valores configurados pelo usuario
    (antes era fixo em 3-10s e o config.json era ignorado).

    Antes essa pausa somava a duracao do video (ate 60s extras por video),
    simulando alguem "assistindo" antes de baixar -- isso deixava o download
    de varios reels extremamente lento. Agora usa so a pausa configurada,
    igual pras fotos; quem quiser mais cautela ajusta a pausa em Ajustes."""
    cfg = get_cfg()
    lo = max(0, float(cfg.get("delay_min", 3)))
    hi = max(lo, float(cfg.get("delay_max", 10)))
    time.sleep(random.uniform(lo, hi))

_speed_stats = {"bytes": 0, "seconds": 0.0}

def _fmt_speed(bytes_per_sec):
    mbps = bytes_per_sec / (1024 * 1024)
    if mbps >= 1:
        return f"{mbps:.1f} MB/s"
    return f"{bytes_per_sec / 1024:.0f} KB/s"

def _record_speed(size_bytes, elapsed_seconds):
    """Atualiza a velocidade (atual e media) mostrada no painel de Progresso."""
    if size_bytes <= 0 or elapsed_seconds <= 0:
        return
    _speed_stats["bytes"] += size_bytes
    _speed_stats["seconds"] += elapsed_seconds
    scrape_state["speed"] = _fmt_speed(size_bytes / elapsed_seconds)
    scrape_state["speed_avg"] = _fmt_speed(_speed_stats["bytes"] / _speed_stats["seconds"])

def _timed_download(fn, *args, **kwargs):
    """Roda uma funcao de download do instagrapi (que retorna o caminho do
    arquivo salvo) medindo o tempo, pra alimentar o indicador de velocidade."""
    t0 = time.perf_counter()
    path = fn(*args, **kwargs)
    elapsed = time.perf_counter() - t0
    try:
        _record_speed(os.path.getsize(path), elapsed)
    except OSError:
        pass
    return path

def downloads_today():
    row = db_query("SELECT COUNT(*) FROM downloads WHERE DATE(downloaded_at) = DATE('now')")
    return row[0][0] if row else 0

def daily_limit_reached():
    """Trava de seguranca: para de baixar ao atingir o limite diario
    configurado (0 = sem limite). Reduz risco de bloqueio da conta."""
    limite = int(get_cfg().get("max_downloads_per_day", 0) or 0)
    if limite <= 0:
        return False
    if downloads_today() >= limite:
        _add_log(f"Limite diario de {limite} downloads atingido -- parando por hoje", "error")
        scrape_state["message"] = f"Limite diario ({limite}) atingido"
        return True
    return False

PARALLEL_WORKERS = 3

def _run_downloads(medias, downloader, cl, tu, folder, get_id, progress_offset=0):
    """Baixa uma lista de midias (posts/stories) pra uma conta+alvo.

    No preset de velocidade "Maxima" (pausa configurada em 0-1s) baixa
    varias midias ao mesmo tempo em vez de uma por uma -- usa bem mais
    da velocidade da internet, mas parece mais "robo" pro Instagram, daí
    so entra nesse modo mais arriscado (quem quiser cautela usa Segura
    ou Rapida, que continuam sequenciais com pausa entre downloads).

    Midias que nao estavam baixadas mas o download falhou (excecao ou
    lista vazia devolvida) entram em 'failed', pra dar pra tentar de novo
    so essas depois (botao "Tentar novamente" no painel de Progresso).

    Retorna (caminhos_salvos, quantidade_baixada, midias_com_erro)."""
    cfg = get_cfg()
    parallel = cfg.get("delay_min", 3) == 0 and cfg.get("delay_max", 10) <= 1
    all_saved = []
    downloaded_count = 0
    failed = []

    if parallel:
        pendentes = [m for m in medias if not is_downloaded(get_id(m))]
        scrape_state["progress"] = progress_offset + (len(medias) - len(pendentes))
        lock = threading.Lock()
        with ThreadPoolExecutor(max_workers=PARALLEL_WORKERS) as ex:
            futures = {ex.submit(downloader, cl, tu, m, folder): m for m in pendentes}
            for fut in as_completed(futures):
                m = futures[fut]
                try:
                    saved = fut.result()
                except Exception:
                    saved = []
                with lock:
                    scrape_state["progress"] += 1
                    all_saved.extend(saved)
                    downloaded_count += len(saved)
                    if not saved:
                        failed.append(m)
                if _stopped() or daily_limit_reached():
                    for f in futures:
                        f.cancel()
                    break
    else:
        for i, m in enumerate(medias):
            if _stopped() or daily_limit_reached():
                break
            scrape_state["progress"] = progress_offset + i + 1
            if is_downloaded(get_id(m)):
                continue
            saved = downloader(cl, tu, m, folder)
            all_saved.extend(saved)
            downloaded_count += len(saved)
            if saved:
                _human_delay_after(m)
            else:
                failed.append(m)

    return all_saved, downloaded_count, failed

def _register_failed(cl, tu, folder, downloader, failed, get_id):
    if failed:
        last_failed_groups.append({
            "cl": cl, "tu": tu, "folder": folder, "downloader": downloader,
            "medias": failed, "get_id": get_id,
        })
        scrape_state["failed_count"] = scrape_state.get("failed_count", 0) + len(failed)

def _item_id(m):
    """Id unico de uma midia, seja ela um objeto do instagrapi (.id) ou
    um Post do Instaloader (.mediaid)."""
    v = getattr(m, 'id', None)
    if v is None:
        v = getattr(m, 'mediaid', None)
    return str(v)

def _media_date(m):
    """Data de publicacao de uma midia, seja ela um objeto do instagrapi
    (.taken_at) ou um Post/StoryItem do Instaloader (.date_utc). Sempre
    devolve datetime "naive" (sem timezone) pra poder comparar os dois
    engines com a mesma logica."""
    dt = getattr(m, 'taken_at', None) or getattr(m, 'date_utc', None)
    if dt and dt.tzinfo:
        dt = dt.replace(tzinfo=None)
    return dt

def _parse_date_param(s):
    """Converte "YYYY-MM-DD" (vindo do <input type=date> do front) num
    datetime. None se vazio/invalido."""
    if not s:
        return None
    try:
        return datetime.fromisoformat(s)
    except ValueError:
        return None

def _in_date_range(dt, date_from, date_to):
    if dt is None:
        return True
    if date_from and dt < date_from:
        return False
    if date_to and dt > date_to.replace(hour=23, minute=59, second=59):
        return False
    return True

def _fetch_filtered_page(fetch_batch, date_from, date_to, page_size, max_batches=6):
    """Busca paginas de midias ate juntar 'page_size' itens dentro do
    intervalo de data pedido (ou esgotar o perfil / tentar demais).

    fetch_batch() deve devolver uma lista de ate page_size midias por
    chamada (lista vazia = acabou). Como o feed do Instagram vem sempre
    do mais novo pro mais velho, assim que aparece uma midia mais velha
    que 'date_from' da pra parar de vez -- o resto so vai ficar mais
    velho ainda. Devolve (midias_filtradas, tem_mais)."""
    collected = []
    has_more = True
    for _ in range(max_batches):
        if len(collected) >= page_size or not has_more:
            break
        raw = fetch_batch()
        has_more = len(raw) == page_size
        for m in raw:
            dt = _media_date(m)
            if date_from and dt and dt < date_from:
                has_more = False
                break
            if _in_date_range(dt, date_from, date_to):
                collected.append(m)
    # nao trunca em page_size: um lote cheio processado por inteiro pode
    # render um pouco mais que page_size itens validos, e cortar aqui
    # descartaria midias de verdade (o cursor/iterator ja passou por elas,
    # entao "Carregar mais" nunca as veria de novo)
    return collected, has_more

def _do_scrape(account_index=None, target_index=None):
    global scrape_state
    _speed_stats["bytes"] = 0
    _speed_stats["seconds"] = 0.0
    last_failed_groups.clear()
    scrape_state.update(running=True, connected=False, current_account="",
                        message="Ligando motor...", progress=0, total=0, current="", logs=[],
                        stop_requested=False, zip_url=None, speed="", speed_avg="", failed_count=0,
                        started_at=time.time())

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
            engine = acc.get('engine', 'instagrapi')
            scrape_state["current_account"] = un
            scrape_state["message"] = f"Conectando @{un} ({engine})..."
            _add_log(f"Tentando login em @{un} ({engine})...")

            try:
                if engine == 'instaloader':
                    cl = login_iloader_account(acc, f"{SESSIONS_DIR}/{un}.iloader")
                else:
                    cl = login_account(acc, f"{SESSIONS_DIR}/{un}.json")
                scrape_state["connected"] = True
                _add_log(f"Login OK @{un}")
            except Exception as e:
                msg = _translate_any_error(e)
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
                folder = f"{DOWNLOADS_DIR}/{tu}"
                os.makedirs(folder, exist_ok=True)
                downloaded_count = 0

                if engine == 'instaloader':
                    try:
                        profile = instaloader.Profile.from_username(cl.context, tu)
                        medias = list(itertools.islice(profile.get_posts(), cfg.get("posts_per_profile", 15)))
                    except Exception as e:
                        _add_log(f"Erro buscar @{tu}: {_translate_any_error(e)}", "error")
                        continue

                    scrape_state["total"] = len(medias)
                    _add_log(f"@{tu}: {len(medias)} midias encontradas")

                    _eco = cfg.get("quality") == "eco"
                    iloader_downloader = lambda cl, tu, m, folder: _iloader_download_post(
                        m, tu, folder, add_download, _add_log, _record_speed, eco=_eco)
                    _saved, downloaded_count, failed = _run_downloads(medias, iloader_downloader, cl, tu, folder, _item_id)
                    _register_failed(cl, tu, folder, iloader_downloader, failed, _item_id)
                else:
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

                    _saved, downloaded_count, failed = _run_downloads(medias, _download_one, cl, tu, folder, _item_id)
                    _register_failed(cl, tu, folder, _download_one, failed, _item_id)

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
    engine = data.get("engine") if data.get("engine") in ("instagrapi", "instaloader") else "instagrapi"
    if not username or not password:
        return jsonify({"ok": False, "msg": "Preencha todos os campos"})

    try:
        if engine == "instaloader":
            login_iloader_account({"username": username, "password": password}, f"{SESSIONS_DIR}/{username}.iloader")
        else:
            login_account({"username": username, "password": password}, f"{SESSIONS_DIR}/{username}.json")
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    upsert_account(username, password=password, engine=engine)

    global scrape_state
    scrape_state["connected"] = True
    scrape_state["current_account"] = username
    return jsonify({"ok": True, "msg": f"Conectado como @{username}", "username": username})

def _do_session_login(raw_session, engine):
    """Loga por sessao -- aceita tanto so o sessionid quanto a string de
    cookies inteira (formato "nome=valor; nome2=valor2") em qualquer um
    dos dois motores. Compartilhado entre login manual, importacao do
    navegador local e a extensao do Chrome.

    O motor Instagrapi so aceita o VALOR PURO do sessionid (a lib faz
    um assert que quebra se receber a string de cookies inteira) -- por
    isso sempre extrai so o sessionid antes de passar pra ele, mesmo
    que o chamador tenha mandado a string toda. O Instaloader aceita os
    dois formatos direto (quanto mais cookies, mais confiavel)."""
    if engine == "instaloader":
        L = login_iloader_sessionid(raw_session)
        username = L.context.username
        L.save_session_to_file(f"{SESSIONS_DIR}/{username}.iloader")
        sessionid = _parse_cookie_string(raw_session).get("sessionid", raw_session)
    else:
        sessionid = _parse_cookie_string(raw_session).get("sessionid")
        if not sessionid:
            raise ValueError("Nao encontrei o sessionid no valor colado")
        cl = login_by_sessionid(sessionid)
        username = cl.username
        cl.dump_settings(f"{SESSIONS_DIR}/{username}.json")

    upsert_account(username, sessionid=sessionid, engine=engine)

    global scrape_state
    scrape_state["connected"] = True
    scrape_state["current_account"] = username
    return username

@app.route("/api/login-session", methods=["POST"])
def api_login_session():
    data = request.get_json() or {}
    sessionid = (data.get("sessionid") or "").strip()
    engine = data.get("engine") if data.get("engine") in ("instagrapi", "instaloader") else "instagrapi"
    if not sessionid:
        return jsonify({"ok": False, "msg": "Cole o sessionid copiado do navegador"})

    try:
        username = _do_session_login(sessionid, engine)
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    return jsonify({"ok": True, "msg": f"Conectado como @{username} (via sessao)", "username": username})

# navegadores suportados pelo browser_cookie3 que fazem sentido num PC
# Windows comum -- a lib suporta mais (Safari, LibreWolf...) mas esses
# cobrem quase todo mundo
_BROWSERS = {
    "chrome": "Chrome", "edge": "Edge", "firefox": "Firefox",
    "brave": "Brave", "opera": "Opera", "vivaldi": "Vivaldi",
}

def _cookies_from_browser(browser: str) -> dict:
    """Le os cookies do instagram.com direto de um navegador instalado
    na propria maquina (mesma ideia do Cookie-Editor, sem copiar e colar
    nada) usando browser_cookie3 -- a mesma biblioteca que o projeto
    Instaloader usa no --load-cookies do CLI oficial dele."""
    try:
        import browser_cookie3
    except ImportError:
        raise RuntimeError(
            "Esse recurso precisa da biblioteca browser_cookie3 (so vem no app "
            "desktop empacotado, nao no modo web/Termux)."
        )
    getter = getattr(browser_cookie3, browser, None)
    if getter is None:
        raise ValueError(f"Navegador nao suportado: {browser}")
    nome = _BROWSERS.get(browser, browser)
    try:
        jar = getter(domain_name="instagram.com")
    except Exception as e:
        es = str(e)
        if "requires admin" in es.lower() or "administrator" in es.lower():
            # o Chrome (e navegadores baseados nele, tipo Edge) protegem os
            # cookies com uma camada extra desde meados de 2024 (App-Bound
            # Encryption) que so o proprio processo do Chrome consegue
            # descriptografar -- de proposito, pra travar justamente esse
            # tipo de leitura automatica. Nao existe "rodar como admin" que
            # resolva isso (nao e sobre permissao, e sobre so o Chrome poder
            # abrir essa chave); o navegador precisa ser trocado por um sem
            # essa protecao, ou usar a colagem manual do sessionid.
            raise RuntimeError(
                f"O {nome} protege os cookies com uma criptografia extra que só o "
                f"próprio navegador consegue abrir (proteção de segurança do "
                f"Chrome/Edge desde 2024) -- não tem como contornar isso por fora, "
                f"nem rodando como administrador. Tenta importar do Firefox, se "
                f"tiver instalado, ou cola o sessionid manualmente (aba 'ou cole "
                f"manualmente' logo abaixo)."
            )
        raise RuntimeError(
            f"Nao consegui ler os cookies do {nome}. "
            f"Feche o navegador e tente de novo (alguns navegadores travam o "
            f"arquivo de cookies enquanto estao abertos). Detalhe: {e}"
        )
    cookies = {c.name: c.value for c in jar}
    if not cookies.get("sessionid"):
        raise RuntimeError(
            f"Nao achei um login do Instagram no {_BROWSERS.get(browser, browser)}. "
            "Faca login em instagram.com nesse navegador primeiro."
        )
    return cookies

@app.route("/api/login-browser", methods=["POST"])
def api_login_browser():
    data = request.get_json() or {}
    browser = (data.get("browser") or "").strip().lower()
    engine = data.get("engine") if data.get("engine") in ("instagrapi", "instaloader") else "instagrapi"
    if browser not in _BROWSERS:
        return jsonify({"ok": False, "msg": "Navegador invalido"})

    try:
        cookies = _cookies_from_browser(browser)
        raw = "; ".join(f"{k}={v}" for k, v in cookies.items())
        username = _do_session_login(raw, engine)
    except Exception as e:
        return jsonify({"ok": False, "msg": str(e) if isinstance(e, (RuntimeError, ValueError)) else _translate_any_error(e)})

    return jsonify({"ok": True,
                    "msg": f"Conectado como @{username} (importado do {_BROWSERS[browser]})",
                    "username": username})

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
        username = (data.get("username") or "").strip()
        password = (data.get("password") or "").strip()
        sessionid = (data.get("sessionid") or "").strip()
        if not username or not (password or sessionid):
            return jsonify({"ok": False, "msg": "Informe usuario e senha (ou sessionid)"}), 400
        accs = jload(ACCOUNTS_PATH)
        engine = data.get("engine") if data.get("engine") in ("instagrapi", "instaloader") else "instagrapi"
        acc = {
            "username": username, "engine": engine,
            "active": True, "created_at": datetime.now().isoformat(), "last_use": None
        }
        if sessionid:
            acc["sessionid"] = sessionid
        if password:
            acc["password"] = password
        accs.setdefault("accounts", []).append(acc)
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

# ─── TESTAR CONTAS ──────────────────────────────────────────────────────────
# Checagem rapida de login em todas as contas salvas, pra saber ANTES de
# buscar um perfil quais contas estao funcionando -- sem isso o usuario so
# descobre que uma conta esta bloqueada/com senha errada depois de esperar
# a busca inteira falhar.
account_test_state = {"running": False, "results": []}

def _test_one_account(acc):
    engine = acc.get("engine", "instagrapi")
    un = acc.get("username", "")
    try:
        if engine == "instaloader":
            cl = login_iloader_account(acc, f"{SESSIONS_DIR}/{un}.iloader")
        else:
            cl = login_account(acc, f"{SESSIONS_DIR}/{un}.json")
        active_clients[(un, engine)] = cl
        return True, "Login OK"
    except Exception as e:
        return False, _translate_any_error(e)

def _do_test_accounts():
    global account_test_state
    accounts = jload(ACCOUNTS_PATH).get("accounts", [])
    account_test_state = {"running": True, "results": []}
    for i, acc in enumerate(accounts):
        if i > 0:
            # pausa entre uma conta e outra -- testar todas em sequencia
            # rapida parece ataque automatizado pro Instagram e pode
            # derrubar varias contas de uma vez (ja aconteceu)
            time.sleep(random.uniform(4, 9))
        ok, msg = _test_one_account(acc)
        account_test_state["results"].append({
            "index": i, "username": acc.get("username"), "engine": acc.get("engine", "instagrapi"),
            "ok": ok, "msg": msg,
        })
    account_test_state["running"] = False

@app.route("/api/test-accounts", methods=["POST"])
def api_test_accounts():
    if account_test_state["running"]:
        return jsonify({"ok": False, "msg": "Ja tem um teste rodando"})
    if scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Espera o download atual terminar antes de testar"})
    threading.Thread(target=_do_test_accounts, daemon=True).start()
    return jsonify({"ok": True, "msg": "Testando contas..."})

@app.route("/api/test-accounts-status")
def api_test_accounts_status():
    return jsonify(account_test_state)

@app.route("/api/toggle-target", methods=["POST"])
def api_toggle_target():
    data = request.get_json()
    t = jload(TARGETS_PATH)
    idx = data.get("index")
    if idx is not None and 0 <= idx < len(t.get("targets", [])):
        t["targets"][idx]["active"] = not t["targets"][idx].get("active", True)
        jsave(TARGETS_PATH, t)
    return jsonify({"ok": True})

# ─── AGENDAMENTO AUTOMATICO ──────────────────────────────────────────────────
# O config.json ja tinha "auto_interval" desde o inicio, mas nada no codigo
# usava esse valor -- o agendamento simplesmente nao existia. Agora existe.
auto_state = {"thread": None, "next_run": None}

def _auto_loop():
    while True:
        cfg = get_cfg()
        if not cfg.get("auto_mode"):
            auto_state["next_run"] = None
            return  # desligado: encerra a thread
        intervalo = max(300, int(cfg.get("auto_interval", 3600) or 3600))
        auto_state["next_run"] = (datetime.now() + timedelta(seconds=intervalo)).isoformat()

        # dorme em fatias pra reagir rapido se o usuario desligar o modo auto
        dormiu = 0
        while dormiu < intervalo:
            time.sleep(5)
            dormiu += 5
            if not get_cfg().get("auto_mode"):
                auto_state["next_run"] = None
                return

        if not scrape_state["running"]:
            _do_scrape()

def _sync_auto_mode():
    """Liga/desliga a thread do agendamento conforme a config."""
    ligado = bool(get_cfg().get("auto_mode"))
    viva = auto_state["thread"] is not None and auto_state["thread"].is_alive()
    if ligado and not viva:
        t = threading.Thread(target=_auto_loop, daemon=True)
        auto_state["thread"] = t
        t.start()

@app.route("/api/auto-status")
def api_auto_status():
    return jsonify({
        "auto_mode": bool(get_cfg().get("auto_mode")),
        "next_run": auto_state["next_run"],
        "downloads_today": downloads_today(),
        "daily_limit": int(get_cfg().get("max_downloads_per_day", 0) or 0),
    })

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
    date_from = _parse_date_param(data.get("date_from"))
    date_to = _parse_date_param(data.get("date_to"))

    try:
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    cache_key = target_username

    if engine == "instaloader":
        try:
            profile = instaloader.Profile.from_username(cl.context, target_username)
            posts_iter = profile.get_posts()
            if date_from or date_to:
                batch, has_more = _fetch_filtered_page(
                    lambda: list(itertools.islice(posts_iter, PREVIEW_PAGE_SIZE)),
                    date_from, date_to, PREVIEW_PAGE_SIZE)
            else:
                batch = list(itertools.islice(posts_iter, PREVIEW_PAGE_SIZE))
                has_more = len(batch) == PREVIEW_PAGE_SIZE
        except Exception as e:
            return jsonify({"ok": False, "msg": f"Erro ao buscar @{target_username}: {_translate_any_error(e)}"})

        preview_cache[cache_key] = {
            "cl": cl, "engine": "instaloader", "posts_iter": posts_iter, "medias": batch,
            "kind": "post", "target": target_username, "label": f"@{target_username}",
            "folder": f"{DOWNLOADS_DIR}/{target_username}",
            "date_from": date_from, "date_to": date_to,
        }
        return jsonify({
            "ok": True,
            "items": [_iloader_preview_item(p, is_downloaded) for p in batch],
            "cache_key": cache_key,
            "has_more": has_more,
        })

    try:
        uid = cl.user_id_from_username(target_username)
        cursor_state = {"cursor": ""}
        def fetch_batch():
            batch, ec = cl.user_medias_paginated(uid, amount=PREVIEW_PAGE_SIZE, end_cursor=cursor_state["cursor"])
            cursor_state["cursor"] = ec
            return batch
        if date_from or date_to:
            medias, has_more = _fetch_filtered_page(fetch_batch, date_from, date_to, PREVIEW_PAGE_SIZE)
        else:
            medias = fetch_batch()
            has_more = bool(cursor_state["cursor"])
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar @{target_username}: {_translate_any_error(e)}"})

    preview_cache[cache_key] = {
        "cl": cl, "engine": "instagrapi", "uid": uid, "medias": list(medias), "end_cursor": cursor_state["cursor"],
        "kind": "post", "target": target_username, "label": f"@{target_username}",
        "folder": f"{DOWNLOADS_DIR}/{target_username}",
        "date_from": date_from, "date_to": date_to,
    }

    return jsonify({
        "ok": True,
        "items": [_media_preview_item(m) for m in medias],
        "cache_key": cache_key,
        "has_more": has_more,
    })

@app.route("/api/preview-more", methods=["POST"])
def api_preview_more():
    data = request.get_json() or {}
    cache_key = (data.get("cache_key") or data.get("target_username") or "").strip()
    cache = preview_cache.get(cache_key)
    if not cache:
        return jsonify({"ok": False, "msg": "Preview expirado, busque de novo."})
    date_from = cache.get("date_from")
    date_to = cache.get("date_to")

    if cache.get("engine") == "instaloader":
        it = cache.get("posts_iter")
        if it is None:
            return jsonify({"ok": True, "items": [], "has_more": False})
        try:
            if date_from or date_to:
                batch, has_more = _fetch_filtered_page(
                    lambda: list(itertools.islice(it, PREVIEW_PAGE_SIZE)),
                    date_from, date_to, PREVIEW_PAGE_SIZE)
            else:
                batch = list(itertools.islice(it, PREVIEW_PAGE_SIZE))
                has_more = len(batch) == PREVIEW_PAGE_SIZE
        except Exception as e:
            return jsonify({"ok": False, "msg": f"Erro ao buscar mais midias: {_translate_any_error(e)}"})
        cache["medias"].extend(batch)
        return jsonify({
            "ok": True,
            "items": [_iloader_preview_item(p, is_downloaded) for p in batch],
            "has_more": has_more,
        })

    if not cache.get("end_cursor"):
        return jsonify({"ok": True, "items": [], "has_more": False})

    try:
        cursor_state = {"cursor": cache["end_cursor"]}
        def fetch_batch():
            batch, ec = cache["cl"].user_medias_paginated(
                cache["uid"], amount=PREVIEW_PAGE_SIZE, end_cursor=cursor_state["cursor"])
            cursor_state["cursor"] = ec
            return batch
        if date_from or date_to:
            medias, has_more = _fetch_filtered_page(fetch_batch, date_from, date_to, PREVIEW_PAGE_SIZE)
        else:
            medias = fetch_batch()
            has_more = bool(cursor_state["cursor"])
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar mais midias: {_translate_any_error(e)}"})

    cache["medias"].extend(medias)
    cache["end_cursor"] = cursor_state["cursor"]

    return jsonify({
        "ok": True,
        "items": [_media_preview_item(m) for m in medias],
        "has_more": has_more,
    })

@app.route("/api/preview-url", methods=["POST"])
def api_preview_url():
    """Preview de um post especifico a partir do link colado, em vez de
    buscar o perfil inteiro. Aceita links de post, reel e tv."""
    data = request.get_json() or {}
    url = (data.get("url") or "").strip()
    if not url:
        return jsonify({"ok": False, "msg": "Cole o link do post"})
    if "instagram.com" not in url:
        return jsonify({"ok": False, "msg": "Isso nao parece um link do Instagram"})

    try:
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    try:
        if engine == "instaloader":
            m = re.search(r"instagram\.com/(?:p|reel|reels|tv)/([A-Za-z0-9_-]+)", url)
            if not m:
                return jsonify({"ok": False, "msg": "Nao consegui ler o codigo do post nesse link"})
            post = instaloader.Post.from_shortcode(cl.context, m.group(1))
            alvo = post.owner_username
            itens, item_dict = [post], _iloader_preview_item(post, is_downloaded)
        else:
            pk = cl.media_pk_from_url(url)
            media = cl.media_info(pk)
            alvo = media.user.username
            itens, item_dict = [media], _media_preview_item(media)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao abrir o link: {_translate_any_error(e)}"})

    cache_key = f"url:{url}"
    preview_cache[cache_key] = {
        "cl": cl, "engine": engine, "medias": itens, "kind": "post",
        "target": alvo, "label": f"@{alvo} (link)",
        "folder": f"{DOWNLOADS_DIR}/{alvo}",
    }
    return jsonify({"ok": True, "items": [item_dict], "cache_key": cache_key,
                    "target": alvo, "has_more": False})

@app.route("/api/reels", methods=["POST"])
def api_reels():
    """Reels de um perfil. O feed normal ja traz alguns, mas o Instagram
    tem um endpoint dedicado que costuma trazer mais/melhor."""
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    cache_key = f"{target_username}:reels"
    base = {"cl": cl, "engine": engine, "kind": "post", "target": target_username,
            "label": f"@{target_username} (reels)",
            "folder": f"{DOWNLOADS_DIR}/{target_username}/reels"}

    try:
        if engine == "instaloader":
            perfil = instaloader.Profile.from_username(cl.context, target_username)
            # o Instaloader nao tem endpoint so de reels: filtra os videos do feed
            itens = [x for x in itertools.islice(perfil.get_posts(), 60) if x.is_video]
            preview_cache[cache_key] = {**base, "medias": itens}
            preview_items = [_iloader_preview_item(x, is_downloaded) for x in itens]
        else:
            uid = cl.user_id_from_username(target_username)
            itens = cl.user_clips(uid, amount=PREVIEW_PAGE_SIZE)
            preview_cache[cache_key] = {**base, "medias": list(itens)}
            preview_items = [_media_preview_item(x) for x in itens]
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar reels de @{target_username}: {_translate_any_error(e)}"})

    msg = None if preview_items else "Nenhum reel encontrado nesse perfil"
    return jsonify({"ok": True, "items": preview_items, "cache_key": cache_key, "msg": msg})

@app.route("/api/stories", methods=["POST"])
def api_stories():
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    cache_key = f"{target_username}:stories"
    cache_base = {
        "cl": cl, "engine": engine, "kind": "story", "target": target_username,
        "label": f"@{target_username} (stories)",
        "folder": f"{DOWNLOADS_DIR}/{target_username}/stories",
    }

    if engine == "instaloader":
        try:
            stories = _iloader_fetch_stories(cl, target_username)
        except Exception as e:
            return jsonify({"ok": False, "msg": f"Erro ao buscar stories de @{target_username}: {_translate_any_error(e)}"})
        preview_cache[cache_key] = {**cache_base, "medias": stories}
        msg = None if stories else "Sem stories ativos agora (expiram em 24h)"
        return jsonify({"ok": True, "items": [_iloader_story_item(s, is_downloaded) for s in stories],
                        "cache_key": cache_key, "msg": msg})

    try:
        uid = cl.user_id_from_username(target_username)
        stories = cl.user_stories(uid)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar stories de @{target_username}: {_translate_any_error(e)}"})

    preview_cache[cache_key] = {**cache_base, "medias": list(stories)}

    msg = None if stories else "Sem stories ativos agora (expiram em 24h)"
    return jsonify({"ok": True, "items": [_story_preview_item(s) for s in stories], "cache_key": cache_key, "msg": msg})

@app.route("/api/highlights", methods=["POST"])
def api_highlights():
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    try:
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    if engine == "instaloader":
        try:
            highlights = _iloader_fetch_highlights(cl, target_username)
        except Exception as e:
            return jsonify({"ok": False, "msg": f"Erro ao buscar destaques de @{target_username}: {_translate_any_error(e)}"})
        # guarda os objetos Highlight pra /api/highlight-items abrir depois
        # sem precisar buscar a lista inteira de novo
        iloader_highlights[(target_username, id(cl))] = {str(h.unique_id): h for h in highlights}
        return jsonify({"ok": True, "items": [_iloader_highlight_summary(h) for h in highlights],
                        "target": target_username})

    try:
        uid = cl.user_id_from_username(target_username)
        highlights = cl.user_highlights(uid)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao buscar destaques de @{target_username}: {_translate_any_error(e)}"})

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
        engine, cl = _get_client(data.get("account_index"))
    except Exception as e:
        return jsonify({"ok": False, "msg": _translate_any_error(e)})

    if engine == "instaloader":
        h = (iloader_highlights.get((target_username, id(cl))) or {}).get(highlight_id)
        if h is None:
            return jsonify({"ok": False, "msg": "Destaque expirou da memoria, abra a lista de destaques de novo."})
        try:
            items = list(h.get_items())
        except Exception as e:
            return jsonify({"ok": False, "msg": f"Erro ao abrir destaque: {_translate_any_error(e)}"})
        display_title = title or h.title or "Destaque"
        cache_key = f"highlight:{highlight_id}"
        preview_cache[cache_key] = {
            "cl": cl, "engine": "instaloader", "medias": items, "kind": "story",
            "target": target_username, "label": f"@{target_username} › {display_title}",
            "folder": f"{DOWNLOADS_DIR}/{target_username}/highlights/{_safe_name(display_title)}",
        }
        return jsonify({"ok": True, "items": [_iloader_story_item(s, is_downloaded) for s in items],
                        "cache_key": cache_key})

    try:
        fetched_title, items = _fetch_highlight_items_raw(cl, highlight_id)
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Erro ao abrir destaque: {_translate_any_error(e)}"})

    display_title = title or fetched_title
    cache_key = f"highlight:{highlight_id}"
    preview_cache[cache_key] = {
        "cl": cl, "engine": "instagrapi", "medias": items, "kind": "story",
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

    selected = [m for m in cache["medias"] if _item_id(m) in ids]
    if not selected:
        return jsonify({"ok": False, "msg": "Selecao invalida, busque de novo."})

    threading.Thread(target=_do_selected_download, args=(cache, selected), daemon=True).start()
    return jsonify({"ok": True, "msg": f"Baixando {len(selected)} selecionados..."})

def _do_selected_download(cache, medias):
    global scrape_state
    cl = cache["cl"]
    folder = cache["folder"]
    kind = cache.get("kind", "post")
    engine = cache.get("engine", "instagrapi")
    label = cache.get("label", "selecionados")
    tu = cache.get("target", "midia").lstrip("@") or "midia"

    if engine == "instaloader":
        iloader_fn = _iloader_download_post if kind == "post" else _iloader_download_story
        _eco = get_cfg().get("quality") == "eco"
        downloader = lambda cl, tu, m, folder: iloader_fn(m, tu, folder, add_download, _add_log, _record_speed, eco=_eco)
        account_label = getattr(cl.context, "username", "") or ""
    else:
        downloader = _download_one if kind == "post" else _download_story_item
        account_label = getattr(cl, "username", "") or ""

    _speed_stats["bytes"] = 0
    _speed_stats["seconds"] = 0.0
    last_failed_groups.clear()
    scrape_state.update(running=True, connected=True, current_account=account_label,
                        message=f"Baixando selecionados de {label}...", progress=0,
                        total=len(medias), current=label, logs=[], stop_requested=False,
                        zip_url=None, speed="", speed_avg="", failed_count=0,
                        started_at=time.time())
    os.makedirs(folder, exist_ok=True)
    try:
        all_saved, _count, failed = _run_downloads(medias, downloader, cl, tu, folder, _item_id)
        _register_failed(cl, tu, folder, downloader, failed, _item_id)

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

@app.route("/api/download-all", methods=["POST"])
def api_download_all():
    """"Baixar tudo": posts, reels, stories e destaques de um perfil,
    tudo numa tacada so, terminando num unico zip organizado em pastas
    por categoria -- sem precisar repetir "buscar > selecionar > baixar"
    quatro vezes, uma por aba."""
    global scrape_state
    if scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Scraping ja esta rodando"})
    data = request.get_json() or {}
    target_username = (data.get("target_username") or "").strip().lstrip("@")
    if not target_username:
        return jsonify({"ok": False, "msg": "Informe o perfil alvo"})

    threading.Thread(target=_do_download_all, args=(target_username, data.get("account_index")), daemon=True).start()
    return jsonify({"ok": True, "msg": f"Baixando tudo de @{target_username}..."})

def _do_download_all(target_username, account_index):
    global scrape_state
    tu = target_username
    _speed_stats["bytes"] = 0
    _speed_stats["seconds"] = 0.0
    last_failed_groups.clear()
    scrape_state.update(running=True, connected=False, current_account="",
                        message=f"Conectando pra baixar tudo de @{tu}...", progress=0, total=0,
                        current=f"@{tu}", logs=[], stop_requested=False, zip_url=None,
                        speed="", speed_avg="", failed_count=0, started_at=time.time())
    all_saved = []  # lista de (caminho, subpasta) pro zip final
    try:
        try:
            engine, cl = _get_client(account_index)
        except Exception as e:
            msg = _translate_any_error(e)
            _add_log(f"Erro ao conectar: {msg}", "error")
            scrape_state["message"] = f"Erro: {msg}"
            return
        account_label = (getattr(cl.context, "username", "") if engine == "instaloader"
                          else getattr(cl, "username", "")) or ""
        scrape_state["connected"] = True
        scrape_state["current_account"] = account_label
        cfg = get_cfg()

        def _baixa_categoria(nome, medias, folder, downloader, subfolder):
            if _stopped():
                return
            scrape_state["message"] = f"Baixando {nome} de @{tu}..."
            scrape_state["total"] = len(medias)
            _add_log(f"@{tu}: {len(medias)} {nome} encontrados")
            os.makedirs(folder, exist_ok=True)
            saved, _cnt, failed = _run_downloads(medias, downloader, cl, tu, folder, _item_id)
            _register_failed(cl, tu, folder, downloader, failed, _item_id)
            all_saved.extend((p, subfolder) for p in saved)

        # 1. POSTS
        scrape_state["message"] = f"Buscando posts de @{tu}..."
        _add_log(f"Buscando posts de @{tu}...")
        try:
            _eco = cfg.get("quality") == "eco"
            if engine == "instaloader":
                profile = instaloader.Profile.from_username(cl.context, tu)
                posts = list(itertools.islice(profile.get_posts(), cfg.get("posts_per_profile", 15)))
                downloader = lambda cl, tu, m, folder: _iloader_download_post(m, tu, folder, add_download, _add_log, _record_speed, eco=_eco)
            else:
                uid = cl.user_id_from_username(tu)
                posts = cl.user_medias(uid, amount=cfg.get("posts_per_profile", 15))
                downloader = _download_one
            _baixa_categoria("posts", posts, f"{DOWNLOADS_DIR}/{tu}", downloader, "posts")
        except Exception as e:
            _add_log(f"Erro ao buscar posts: {_translate_any_error(e)}", "error")

        # 2. REELS
        if not _stopped():
            scrape_state["message"] = f"Buscando reels de @{tu}..."
            _add_log(f"Buscando reels de @{tu}...")
            try:
                _eco = cfg.get("quality") == "eco"
                if engine == "instaloader":
                    profile = instaloader.Profile.from_username(cl.context, tu)
                    reels = [x for x in itertools.islice(profile.get_posts(), 60) if x.is_video]
                    downloader = lambda cl, tu, m, folder: _iloader_download_post(m, tu, folder, add_download, _add_log, _record_speed, eco=_eco)
                else:
                    uid = cl.user_id_from_username(tu)
                    reels = list(cl.user_clips(uid, amount=PREVIEW_PAGE_SIZE))
                    downloader = _download_one
                _baixa_categoria("reels", reels, f"{DOWNLOADS_DIR}/{tu}/reels", downloader, "reels")
            except Exception as e:
                _add_log(f"Erro ao buscar reels: {_translate_any_error(e)}", "error")

        # 3. STORIES (ativos, expiram em 24h -- pode nao ter nenhum)
        if not _stopped():
            scrape_state["message"] = f"Buscando stories de @{tu}..."
            _add_log(f"Buscando stories de @{tu}...")
            try:
                if engine == "instaloader":
                    stories = _iloader_fetch_stories(cl, tu)
                    downloader = lambda cl, tu, m, folder: _iloader_download_story(m, tu, folder, add_download, _add_log, _record_speed)
                else:
                    uid = cl.user_id_from_username(tu)
                    stories = list(cl.user_stories(uid))
                    downloader = _download_story_item
                _baixa_categoria("stories", stories, f"{DOWNLOADS_DIR}/{tu}/stories", downloader, "stories")
            except Exception as e:
                _add_log(f"Erro ao buscar stories: {_translate_any_error(e)}", "error")

        # 4. DESTAQUES (cada um numa subpasta com o proprio titulo)
        if not _stopped():
            scrape_state["message"] = f"Buscando destaques de @{tu}..."
            _add_log(f"Buscando destaques de @{tu}...")
            try:
                if engine == "instaloader":
                    highlights = _iloader_fetch_highlights(cl, tu)
                    downloader = lambda cl, tu, m, folder: _iloader_download_story(m, tu, folder, add_download, _add_log, _record_speed)
                    for h in highlights:
                        if _stopped():
                            break
                        title = _safe_name(h.title or "Destaque")
                        try:
                            items = list(h.get_items())
                        except Exception as e:
                            _add_log(f"Erro no destaque {title}: {_translate_any_error(e)}", "error")
                            continue
                        _baixa_categoria(f"itens de '{title}'", items,
                                        f"{DOWNLOADS_DIR}/{tu}/highlights/{title}", downloader, f"destaques/{title}")
                else:
                    uid = cl.user_id_from_username(tu)
                    highlights = cl.user_highlights(uid)
                    for h in highlights:
                        if _stopped():
                            break
                        try:
                            fetched_title, items = _fetch_highlight_items_raw(cl, h.pk)
                        except Exception as e:
                            _add_log(f"Erro no destaque {h.title or h.pk}: {_translate_any_error(e)}", "error")
                            continue
                        title = _safe_name(h.title or fetched_title)
                        _baixa_categoria(f"itens de '{title}'", items,
                                        f"{DOWNLOADS_DIR}/{tu}/highlights/{title}", _download_story_item, f"destaques/{title}")
            except Exception as e:
                _add_log(f"Erro ao buscar destaques: {_translate_any_error(e)}", "error")

        if not scrape_state.get("stop_requested"):
            zip_url = _make_zip(tu, all_saved)
            scrape_state["zip_url"] = zip_url
            done_msg = f"Finalizado: {len(all_saved)} arquivos baixados (tudo de @{tu})"
            scrape_state["message"] = done_msg + (" (zip pronto)" if zip_url else "")
            _add_log("Download completo (tudo) concluido", "success")
    except Exception as e:
        _add_log(f"Erro fatal: {e}", "error")
        scrape_state["message"] = f"Erro fatal: {e}"
    finally:
        scrape_state["running"] = False
        scrape_state["connected"] = False
        scrape_state["current"] = ""
        scrape_state["stop_requested"] = False

@app.route("/api/retry-failed", methods=["POST"])
def api_retry_failed():
    global scrape_state
    if scrape_state["running"]:
        return jsonify({"ok": False, "msg": "Scraping ja esta rodando"})
    if not last_failed_groups:
        return jsonify({"ok": False, "msg": "Nada pra tentar de novo"})
    threading.Thread(target=_do_retry_failed, daemon=True).start()
    return jsonify({"ok": True, "msg": "Tentando de novo os itens com erro..."})

def _do_retry_failed():
    """Refaz so os downloads que falharam na ultima leva (scrape automatico
    ou selecionados), sem precisar buscar tudo de novo."""
    global scrape_state
    groups = list(last_failed_groups)
    last_failed_groups.clear()
    total = sum(len(g["medias"]) for g in groups)

    _speed_stats["bytes"] = 0
    _speed_stats["seconds"] = 0.0
    scrape_state.update(running=True, connected=True, current_account="",
                        message="Tentando de novo os itens com erro...", progress=0,
                        total=total, current="", logs=[], stop_requested=False,
                        zip_url=None, speed="", speed_avg="", failed_count=0,
                        started_at=time.time())
    all_saved = []
    try:
        offset = 0
        for g in groups:
            if _stopped():
                break
            saved, _count, still_failed = _run_downloads(
                g["medias"], g["downloader"], g["cl"], g["tu"], g["folder"], g["get_id"],
                progress_offset=offset)
            offset += len(g["medias"])
            all_saved.extend(saved)
            _register_failed(g["cl"], g["tu"], g["folder"], g["downloader"], still_failed, g["get_id"])

        if not scrape_state.get("stop_requested"):
            recuperados = total - scrape_state.get("failed_count", 0)
            scrape_state["message"] = f"Finalizado: {recuperados} recuperados de {total}"
            _add_log("Nova tentativa concluida", "success")
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

def _eta_string():
    """Tempo restante estimado, com base no ritmo real desde o inicio da
    operacao atual (inclui as pausas entre downloads, nao so o tempo de
    transferencia -- por isso e mais fiel do que so olhar a velocidade)."""
    progress = scrape_state.get("progress", 0)
    total = scrape_state.get("total", 0)
    started_at = scrape_state.get("started_at")
    if not started_at or progress <= 0 or total <= 0 or progress >= total:
        return ""
    elapsed = time.time() - started_at
    remaining = (elapsed / progress) * (total - progress)
    if remaining < 60:
        return f"~{int(remaining)}s restantes"
    if remaining < 3600:
        return f"~{round(remaining / 60)} min restantes"
    h, m = int(remaining // 3600), int((remaining % 3600) // 60)
    return f"~{h}h{m:02d}min restantes"

@app.route("/api/status")
def api_status():
    s = dict(scrape_state)
    s["eta"] = _eta_string() if s.get("running") else ""
    return jsonify(s)

@app.route("/api/stats")
def api_stats():
    return jsonify(get_stats())

@app.route("/api/errors")
def api_errors():
    q = (request.args.get("q") or "").strip()
    limit = min(int(request.args.get("limit", 200) or 200), 1000)
    if q:
        rows = db_query(
            "SELECT id, message, occurred_at FROM error_log WHERE message LIKE ? "
            "ORDER BY id DESC LIMIT ?", (f"%{q}%", limit))
    else:
        rows = db_query("SELECT id, message, occurred_at FROM error_log ORDER BY id DESC LIMIT ?", (limit,))
    total = db_query("SELECT COUNT(*) FROM error_log")[0][0]
    return jsonify({"ok": True, "total": total,
                    "errors": [{"id": r[0], "message": r[1], "occurred_at": r[2]} for r in rows]})

@app.route("/api/errors/export")
def api_errors_export():
    rows = db_query("SELECT occurred_at, message FROM error_log ORDER BY id DESC")
    linhas = ["data_hora,mensagem"]
    for occurred_at, message in rows:
        msg_csv = '"' + (message or "").replace('"', '""') + '"'
        linhas.append(f"{occurred_at},{msg_csv}")
    csv_text = "\n".join(linhas)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    return Response(csv_text, mimetype="text/csv", headers={
        "Content-Disposition": f"attachment; filename=erros_igscraper_{ts}.csv"
    })

@app.route("/api/errors/clear", methods=["POST"])
def api_errors_clear():
    db_query("DELETE FROM error_log", fetch=False)
    return jsonify({"ok": True})

@app.route("/api/config", methods=["GET", "POST"])
def api_config():
    if request.method == "GET":
        return jsonify(get_cfg())
    data = request.get_json() or {}
    cfg = get_cfg()

    # valida os numeros antes de salvar, pra nao gravar lixo que quebraria
    # o download depois (ex: delay negativo, texto no lugar de numero)
    limites = {"delay_min": (0, 300), "delay_max": (0, 600),
               "posts_per_profile": (1, 500), "auto_interval": (300, 86400),
               "max_downloads_per_day": (0, 100000)}
    for chave, (lo, hi) in limites.items():
        if chave in data:
            try:
                cfg[chave] = max(lo, min(hi, int(float(data[chave]))))
            except (TypeError, ValueError):
                return jsonify({"ok": False, "msg": f"Valor invalido em {chave}"})
    if "auto_mode" in data:
        cfg["auto_mode"] = bool(data["auto_mode"])
    if "quality" in data and data["quality"] in ("max", "eco"):
        cfg["quality"] = data["quality"]
    if cfg.get("delay_max", 10) < cfg.get("delay_min", 3):
        cfg["delay_max"] = cfg["delay_min"]

    jsave(CONFIG_PATH, cfg)
    _sync_auto_mode()
    return jsonify({"ok": True, "config": cfg})

# ─── INTEGRACAO COM O WINDOWS ────────────────────────────────────────────────
_STARTUP_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_STARTUP_NAME = "IGScraperPro"

def _startup_supported():
    """So faz sentido no Windows e rodando como aplicativo empacotado --
    apontar o registro pro python.exe do desenvolvimento nao ajudaria."""
    return sys.platform == "win32" and getattr(sys, "frozen", False)

def startup_enabled():
    if sys.platform != "win32":
        return False
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY) as k:
            winreg.QueryValueEx(k, _STARTUP_NAME)
            return True
    except Exception:
        return False

@app.route("/api/startup", methods=["GET", "POST"])
def api_startup():
    if request.method == "GET":
        return jsonify({"supported": _startup_supported(), "enabled": startup_enabled()})

    if not _startup_supported():
        return jsonify({"ok": False, "msg": "So funciona no aplicativo instalado no Windows"})

    ligar = bool((request.get_json() or {}).get("enabled"))
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _STARTUP_KEY, 0, winreg.KEY_ALL_ACCESS) as k:
            if ligar:
                winreg.SetValueEx(k, _STARTUP_NAME, 0, winreg.REG_SZ, f'"{sys.executable}"')
            else:
                try:
                    winreg.DeleteValue(k, _STARTUP_NAME)
                except FileNotFoundError:
                    pass
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Nao consegui alterar: {e}"})

    return jsonify({"ok": True, "enabled": ligar,
                    "msg": "Vai abrir junto com o Windows" if ligar else "Nao abre mais sozinho"})

@app.route("/api/open-folder", methods=["POST"])
def api_open_folder():
    """Abre a pasta de downloads no gerenciador de arquivos do sistema.
    So faz sentido quando o app roda na propria maquina (build desktop);
    no Termux/servidor remoto nao ha o que abrir."""
    pasta = os.path.abspath(DOWNLOADS_DIR)
    os.makedirs(pasta, exist_ok=True)
    try:
        if sys.platform == "win32":
            os.startfile(pasta)
        elif sys.platform == "darwin":
            import subprocess; subprocess.Popen(["open", pasta])
        else:
            import subprocess; subprocess.Popen(["xdg-open", pasta])
    except Exception as e:
        return jsonify({"ok": False, "msg": f"Nao consegui abrir a pasta ({e}). Ela fica em: {pasta}"})
    return jsonify({"ok": True, "msg": "Pasta aberta", "path": pasta})

@app.route("/api/downloads")
def api_downloads():
    # busca feita no banco, nao no navegador: a lista e limitada a 100
    # itens, entao filtrar so no front-end deixaria de fora arquivos
    # antigos que casam com o termo procurado
    termo = (request.args.get("q") or "").strip()
    tipo = (request.args.get("type") or "").strip()
    where, params = [], []
    if termo:
        where.append("(file LIKE ? OR username LIKE ?)")
        params += [f"%{termo}%", f"%{termo}%"]
    if tipo in ("photo", "video"):
        where.append("type = ?")
        params.append(tipo)
    filtro = ("WHERE " + " AND ".join(where)) if where else ""
    rows = db_query(
        f"SELECT file, username, type, date, downloaded_at FROM downloads {filtro} "
        "ORDER BY downloaded_at DESC LIMIT 100", tuple(params))
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
    _sync_auto_mode()  # religa o agendamento se estava ligado
    print("\n" + "=" * 55)
    print("  IG-SCRAPER-PRO v4.0  |  WEB DASHBOARD")
    print("=" * 55)
    print("  http://localhost:5000")
    print("=" * 55 + "\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
