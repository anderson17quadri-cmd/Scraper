#!/usr/bin/env python3
"""Login helpers shared by the Flask app, the CLI and the scraping engine.

Centralizes two things that used to be duplicated (and buggy) in app.py,
scraper.py and dashboard.py:
  - turning instagrapi exceptions into short, actionable messages in pt-BR
  - logging in either with username/password or with a saved browser
    session id ("login por sessao"), reusing a cached session file when
    it is still valid.
"""
import os
from instagrapi import Client
from instagrapi.exceptions import (
    AccountSuspended,
    BadCredentials,
    BadPassword,
    ChallengeRequired,
    ClientError,
    ClientThrottledError,
    FeedbackRequired,
    LoginRequired,
    PleaseWaitFewMinutes,
    ProxyAddressIsBlocked,
    RateLimitError,
    TwoFactorRequired,
)

# Ordered most-specific-first: isinstance() stops at the first match.
_FRIENDLY_ERRORS = [
    (TwoFactorRequired,
        "Essa conta tem verificacao em duas etapas (2FA) ativada. Desative o 2FA "
        "temporariamente ou faca login por sessao (cookie) em vez de usuario/senha."),
    (ChallengeRequired,
        "O Instagram pediu uma verificacao de seguranca (checkpoint). Abra o app "
        "oficial do Instagram nesse mesmo aparelho/rede, resolva a verificacao e tente de novo."),
    (AccountSuspended,
        "Essa conta foi suspensa/banida pelo Instagram."),
    (PleaseWaitFewMinutes,
        "O Instagram pediu para esperar alguns minutos antes de tentar de novo."),
    (RateLimitError,
        "Limite de requisicoes do Instagram atingido. Espere um pouco e tente de novo."),
    (ClientThrottledError,
        "Muitas tentativas em pouco tempo. Espere alguns minutos e tente de novo."),
    (ProxyAddressIsBlocked,
        "O IP/rede usada foi bloqueado pelo Instagram."),
    (FeedbackRequired,
        "O Instagram bloqueou essa acao por comportamento suspeito nessa conta."),
    (BadPassword,
        "Senha incorreta OU o Instagram desconfiou desse login (comum em contas novas/"
        "descartaveis). Confira a senha; se estiver certa, 'esquente' a conta no app oficial "
        "antes ou faca login por sessao (cookie)."),
    (BadCredentials,
        "Usuario ou senha nao informados corretamente."),
    (LoginRequired,
        "A sessao expirou, sera necessario logar novamente."),
]


def translate_ig_error(e: Exception) -> str:
    """Maps an instagrapi exception to a short, actionable pt-BR message."""
    if isinstance(e, ValueError):
        # mensagens que a gente mesmo criou (ex: "Nenhuma conta cadastrada"),
        # ja estao prontas pra exibir, sem precisar de tradução
        return str(e)
    for exc_type, msg in _FRIENDLY_ERRORS:
        if isinstance(e, exc_type):
            return msg
    if isinstance(e, ClientError):
        return f"O Instagram recusou o login: {e}"
    return f"Erro inesperado: {e}"


def login_account(account: dict, session_file: str) -> Client:
    """
    Ensures `account` (a dict with 'username' and either 'password' or
    'sessionid') is logged in, reusing a saved session file when it is
    still valid. Returns an authenticated Client, or raises the underlying
    instagrapi exception (pass it to translate_ig_error() for a friendly
    message).
    """
    cl = Client()
    username = account.get("username")
    password = account.get("password")
    sessionid = account.get("sessionid")

    if os.path.exists(session_file):
        try:
            cl.load_settings(session_file)
            if cl.user_id:
                # ter os dados salvos no arquivo nao quer dizer que a sessao
                # ainda esta viva no Instagram (o cookie pode ter expirado
                # ou sido revogado) -- confirma com uma chamada leve antes
                # de confiar nela, senao isso so aparece como erro depois,
                # numa busca, em vez de relogar sozinho aqui
                cl.account_info()
                return cl
        except Exception:
            cl = Client()

    if sessionid:
        cl.login_by_sessionid(sessionid)
    elif username and password:
        cl.login(username, password)
    else:
        raise BadCredentials("Conta sem senha ou sessao salva")

    os.makedirs(os.path.dirname(session_file) or ".", exist_ok=True)
    cl.dump_settings(session_file)
    return cl


def login_by_sessionid(sessionid: str) -> Client:
    """Fresh login using a sessionid cookie copied from a real browser.

    The caller doesn't know the username until after this call succeeds
    (it's read off `client.username`), so saving the session file to its
    final `sessions/<username>.json` path is left to the caller.
    """
    cl = Client()
    cl.login_by_sessionid(sessionid)
    return cl
