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

Limitacao atual: so posts (feed) sao suportados por esse motor. Stories e
destaques continuam exclusivos do motor instagrapi.
"""
import os
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


def _http_download(url: str, path: str):
    r = requests.get(url, stream=True, timeout=30)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(8192):
            f.write(chunk)


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


def save_caption_sidecar(folder: str, base_name: str, post):
    caption = (post.caption or "").strip() if post.caption else ""
    lines = [caption] if caption else []
    lines.append("")
    lines.append("---")
    lines.append(f"Data: {post.date_utc.strftime('%Y-%m-%d %H:%M')}")
    try:
        lines.append(f"Curtidas: {post.likes}")
        lines.append(f"Comentarios: {post.comments}")
    except Exception:
        pass
    try:
        if post.location and post.location.name:
            lines.append(f"Localizacao: {post.location.name}")
    except Exception:
        pass
    try:
        with open(os.path.join(folder, f"{base_name}.txt"), "w", encoding="utf-8") as f:
            f.write("\n".join(lines))
    except Exception:
        pass


def download_post(post, tu, folder, add_download_fn, log_fn):
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
                    _http_download(url, path)
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
            _http_download(url, path)
            add_download_fn({
                'media_id': str(post.mediaid), 'username': tu, 'file': fname,
                'type': 'video' if post.is_video else 'photo', 'date': post.date_utc.isoformat(),
            })
            log_fn(f"Download: {fname}", "success")
            saved.append(path)
            save_caption_sidecar(folder, f"{tu}_{date_str}", post)
    except Exception as e:
        log_fn(f"Erro: {str(e)[:80]}", "error")
    return saved
