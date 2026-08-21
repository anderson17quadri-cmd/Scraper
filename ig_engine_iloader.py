#!/usr/bin/env python3
"""Motor alternativo de download usando a biblioteca Instaloader.

Complementa o motor principal (instagrapi, em ig_auth.py). Usa a API
publica/web do Instagram em vez da API privada do app mobile -- caminho
de acesso diferente, entao serve como redundancia: se um motor levar
bloqueio/rate-limit, o outro pode continuar funcionando.

Cada conta cadastrada escolhe seu motor (campo "engine" em accounts.json).
As funcoes aqui devolvem os MESMOS formatos de dict que o app.py ja usa
pros posts do instagrapi (_media_preview_item etc), pra reaproveitar toda
a grade de selecao/preview do front-end sem mudar nada la.

Suporta posts (feed), stories e destaques -- as mesmas coisas que o motor
instagrapi baixa.
"""
import os
import time
from datetime import datetime
import requests
import instaloader
from instaloader.exceptions import (
    BadCredentialsException,
    ConnectionException,
    LoginException,
    LoginRequiredException,
    PrivateProfileNotFollowedException,
    ProfileNotExistsException,
    QueryReturnedForbiddenException,
    TooManyRequestsException,
    TwoFactorAuthRequiredException,
)

_FRIENDLY_ERRORS = [
    (TwoFactorAuthRequiredException,
        "Essa conta tem verificacao em duas etapas (2FA) ativada. O motor Instaloader "
        "ainda nao suporta inserir o codigo por aqui -- desative o 2FA ou use essa conta "
        "no motor Instagrapi (login por sessao)."),
    (BadCredentialsException,
        "Usuario ou senha incorretos (Instaloader)."),
    # LoginException generico cobre "checkpoint required" -- verificado a parte
    # abaixo (mensagem especifica) antes de cair nesse fallback mais vago
    (LoginException,
        "O Instagram pediu uma verificacao de seguranca extra pra essa conta (checkpoint). "
        "Abra o app oficial do Instagram nesse mesmo aparelho/rede, resolva a verificacao "
        "e tente de novo."),
    (TooManyRequestsException,
        "O Instagram pediu pra esperar -- muitas requisicoes em pouco tempo. Tente de novo em alguns minutos."),
    (QueryReturnedForbiddenException,
        "O Instagram recusou essa requisicao (perfil bloqueado ou acao suspeita)."),
    (PrivateProfileNotFollowedException,
        "Esse perfil e privado e a conta usada nao o segue."),
    (ProfileNotExistsException,
        "Perfil nao encontrado."),
    (LoginRequiredException,
        "A sessao expirou, sera necessario logar novamente."),
    (ConnectionException,
        "Erro de conexao com o Instagram. Tente de novo em instantes."),
]


def translate_iloader_error(e: Exception) -> str:
    for exc_type, msg in _FRIENDLY_ERRORS:
        if isinstance(e, exc_type):
            return msg
    return f"Erro inesperado (Instaloader): {e}"


def login_iloader_account(account: dict, session_file: str) -> instaloader.Instaloader:
    """Mesma ideia do login_account() do motor instagrapi: reaproveita
    sessao salva quando possivel, senao loga com usuario/senha e salva."""
    L = instaloader.Instaloader(
        download_pictures=False, download_videos=False, download_video_thumbnails=False,
        download_geotags=False, download_comments=False, save_metadata=False,
        compress_json=False, quiet=True,
    )
    username = account.get("username")
    password = account.get("password")

    if os.path.exists(session_file):
        try:
            L.load_session_from_file(username, session_file)
            if L.context.is_logged_in:
                return L
        except Exception:
            pass

    if not username or not password:
        raise BadCredentialsException("Conta sem usuario/senha salva pro motor Instaloader")

    L.login(username, password)
    os.makedirs(os.path.dirname(session_file) or ".", exist_ok=True)
    L.save_session_to_file(session_file)
    return L


def _http_download(url: str, path: str, speed_fn=None):
    t0 = time.perf_counter()
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    size = 0
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)
            size += len(chunk)
    if speed_fn:
        speed_fn(size, time.perf_counter() - t0)


def post_preview_item(post, is_downloaded_fn) -> dict:
    is_carousel = post.typename == "GraphSidecar"
    thumb = post.url
    if is_carousel:
        try:
            first = next(iter(post.get_sidecar_nodes()))
            thumb = first.display_url
        except StopIteration:
            pass
    return {
        "id": str(post.mediaid),
        "type": "carousel" if is_carousel else ("video" if post.is_video else "photo"),
        "thumbnail": str(thumb) if thumb else None,
        "date": post.date_utc.isoformat(),
        "already": is_downloaded_fn(str(post.mediaid)),
    }


def download_post(post, tu, folder, add_download_fn, log_fn, speed_fn=None):
    """Baixa um post (foto/video/carrossel) via Instaloader, na maior
    resolucao disponivel. Retorna a lista de caminhos salvos."""
    date_str = post.date_utc.strftime("%Y%m%d_%H%M%S")
    saved = []
    try:
        if post.typename == "GraphSidecar":
            for j, node in enumerate(post.get_sidecar_nodes()):
                try:
                    url = node.video_url if node.is_video else node.display_url
                    ext = "mp4" if node.is_video else "jpg"
                    fname = f"{tu}_{date_str}_c{j}.{ext}"
                    path = os.path.join(folder, fname)
                    _http_download(url, path, speed_fn)
                    add_download_fn({
                        'media_id': f"{post.mediaid}_{j}", 'username': tu, 'file': fname,
                        'type': 'video' if node.is_video else 'photo', 'date': post.date_utc.isoformat(),
                    })
                    log_fn(f"Download: {fname}", "success")
                    saved.append(path)
                except Exception:
                    pass
        else:
            url = post.video_url if post.is_video else post.url
            ext = "mp4" if post.is_video else "jpg"
            fname = f"{tu}_{date_str}.{ext}"
            path = os.path.join(folder, fname)
            _http_download(url, path, speed_fn)
            add_download_fn({
                'media_id': str(post.mediaid), 'username': tu, 'file': fname,
                'type': 'video' if post.is_video else 'photo', 'date': post.date_utc.isoformat(),
            })
            log_fn(f"Download: {fname}", "success")
            saved.append(path)
    except Exception as e:
        log_fn(f"Erro: {str(e)[:80]}", "error")
    return saved


# ─── STORIES E DESTAQUES ─────────────────────────────────────────────────────
# Story/Highlight do Instaloader expoem StoryItem, que tem uma "forma"
# diferente de Post (url/video_url/date_utc/mediaid, sem carrossel). As
# funcoes abaixo convertem pros mesmos dicts que o app.py ja usa.

def story_preview_item(item, is_downloaded_fn) -> dict:
    return {
        "id": str(item.mediaid),
        "type": "video" if item.is_video else "photo",
        "thumbnail": str(item.url) if item.url else None,
        "date": item.date_utc.isoformat() if item.date_utc else None,
        "already": is_downloaded_fn(str(item.mediaid)),
    }


def fetch_stories(L, username: str) -> list:
    """Stories ativos (24h) de um perfil. Precisa estar logado."""
    profile = instaloader.Profile.from_username(L.context, username)
    items = []
    for story in L.get_stories(userids=[profile.userid]):
        items.extend(story.get_items())
    return items


def fetch_highlights(L, username: str) -> list:
    """Lista os destaques do perfil (objetos Highlight, ainda sem baixar
    os itens de dentro)."""
    profile = instaloader.Profile.from_username(L.context, username)
    return list(L.get_highlights(profile))


def highlight_summary(h) -> dict:
    """Mesmo formato usado pelos destaques do motor instagrapi, pro
    front-end renderizar a lista sem saber qual motor gerou."""
    return {
        "id": str(h.unique_id),
        "title": h.title or "Destaque",
        "cover": str(h.cover_url) if h.cover_url else None,
        "count": h.itemcount,
    }


def download_story_item(item, tu, folder, add_download_fn, log_fn, speed_fn=None):
    """Baixa um item de story/destaque. Retorna lista de caminhos salvos."""
    date_str = (item.date_utc or datetime.utcnow()).strftime("%Y%m%d_%H%M%S")
    saved = []
    try:
        url = item.video_url if item.is_video else item.url
        ext = "mp4" if item.is_video else "jpg"
        fname = f"{tu}_story_{date_str}.{ext}"
        path = os.path.join(folder, fname)
        _http_download(url, path, speed_fn)
        add_download_fn({
            'media_id': str(item.mediaid), 'username': tu, 'file': fname,
            'type': 'video' if item.is_video else 'photo',
            'date': item.date_utc.isoformat() if item.date_utc else datetime.utcnow().isoformat(),
        })
        log_fn(f"Download: {fname}", "success")
        saved.append(path)
    except Exception as e:
        log_fn(f"Erro: {str(e)[:80]}", "error")
    return saved
