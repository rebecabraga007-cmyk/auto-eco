"""Contexto da sessão — quem está logado no request atual.

O login é o do CapiBLU (`auth.py`, JWT em cookie httpOnly). O middleware
guarda o usuário aqui para que os routers e a ponte com o serviço de dados
saibam por quem estão agindo.
"""
from contextvars import ContextVar

_current: ContextVar[dict | None] = ContextVar("bluutime_user", default=None)


def set_session_user(user: dict | None) -> None:
    _current.set(user)


def session_user() -> dict | None:
    return _current.get()


def session_email() -> str:
    return (session_user() or {}).get("email", "")


def session_role() -> str:
    return (session_user() or {}).get("role", "")
