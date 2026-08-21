"""Ponte com o serviço de dados do CapiBLU.

O app do CapiBLU (`lupa-empresas/backend/main.py`) é montado dentro do Bluutime,
então as chamadas acontecem em processo — sem túnel, sem rede. Os headers de
identidade são os mesmos que o `app_online` injeta no proxy de produção, porque
o serviço de dados decide permissão de admin lendo `X-User-Role`.
"""
import os

import httpx

from .config import capiblu_on_path
from .deps import session_user

_app = None
_import_error: str | None = None


def capiblu_app():
    """Importa o app do CapiBLU sob demanda — a subida do Bluutime não pode
    depender de a base de 31 GB ou as chaves de API estarem presentes."""
    global _app, _import_error
    if _app is None and _import_error is None:
        capiblu_on_path()
        try:
            from main import app as data_app  # backend/main.py
            _app = data_app
        except Exception as exc:  # noqa: BLE001 — qualquer falha vira modo degradado
            _import_error = f"{type(exc).__name__}: {exc}"
    return _app


def capiblu_error() -> str | None:
    capiblu_app()
    return _import_error


def _headers() -> dict:
    user = session_user() or {}
    headers = {"X-User-Email": user.get("email", ""),
               "X-User-Role": user.get("role", ""),
               "X-User-Grupo": user.get("grupo_id") or ""}
    secret = os.environ.get("PROXY_SECRET", "").strip()
    if secret:
        headers["X-Proxy-Secret"] = secret
    return headers


async def call(method: str, path: str, *, params=None, json=None, timeout: float = 120.0):
    """Chama uma rota do CapiBLU e devolve (status, payload)."""
    app = capiblu_app()
    if app is None:
        return 503, {"detail": f"Serviço de dados do CapiBLU indisponível. {_import_error}"}
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://capiblu",
                                 timeout=timeout) as client:
        r = await client.request(method, path, params=params, json=json, headers=_headers())
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"detail": r.text[:400]}


async def get(path: str, **kw):
    return await call("GET", path, **kw)


async def post(path: str, **kw):
    return await call("POST", path, **kw)
