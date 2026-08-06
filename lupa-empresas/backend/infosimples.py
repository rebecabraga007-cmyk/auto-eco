"""Cliente da Infosimples para certidoes de antecedentes criminais da PF.

Config por variaveis de ambiente:
- INFOSIMPLES_TOKEN      token da API Infosimples
- INFOSIMPLES_BASE_URL   default https://api.infosimples.com
"""
from __future__ import annotations

import os
import re
from datetime import datetime
from typing import Any

import httpx

BASE_URL = os.environ.get("INFOSIMPLES_BASE_URL", "https://api.infosimples.com").strip().rstrip("/")
TOKEN = os.environ.get("INFOSIMPLES_TOKEN", "").strip()
TIMEOUT = httpx.Timeout(45.0)

_cache: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    return bool(TOKEN and BASE_URL)


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _birthdate(value: str) -> str:
    value = (value or "").strip()
    if re.match(r"^\d{2}/\d{2}/\d{4}$", value):
        return value
    for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%d-%m-%Y"):
        try:
            return datetime.strptime(value[:19], fmt).strftime("%d/%m/%Y")
        except ValueError:
            pass
    return value


def _first_data(payload: dict[str, Any]) -> dict[str, Any]:
    data = payload.get("data")
    if isinstance(data, list):
        return data[0] if data and isinstance(data[0], dict) else {}
    if isinstance(data, dict):
        return data
    return {}


async def antecedentes_pf_emitir(
    *,
    cpf: str,
    nome: str,
    nascimento: str,
    nome_mae: str,
    nome_pai: str = "",
    uf_nascimento: str = "",
) -> dict[str, Any]:
    if not enabled():
        return {
            "status": "unavailable",
            "message": "Infosimples nao configurada (defina INFOSIMPLES_TOKEN).",
            "certidao": {},
        }

    doc = only_digits(cpf).zfill(11)[:11]
    birthdate = _birthdate(nascimento)
    missing = []
    if len(doc) != 11:
        missing.append("cpf")
    if not nome:
        missing.append("nome")
    if not birthdate:
        missing.append("birthdate")
    if not nome_mae:
        missing.append("nome_mae")
    if missing:
        return {
            "status": "missing_fields",
            "message": "Campos insuficientes para emitir antecedentes PF: " + ", ".join(missing),
            "certidao": {},
        }

    cache_key = "|".join([doc, nome, birthdate, nome_mae, nome_pai, uf_nascimento])
    if cache_key in _cache:
        return _cache[cache_key]

    url = BASE_URL + "/api/v2/consultas/antecedentes-criminais/pf-emit"
    body = {
        "token": TOKEN,
        "cpf": doc,
        "nome": nome,
        "birthdate": birthdate,
        "nome_mae": nome_mae,
        "nome_pai": nome_pai or "",
        "uf_nascimento": (uf_nascimento or "").upper(),
    }
    if not body["uf_nascimento"]:
        body.pop("uf_nascimento")

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT) as client:
            resp = await client.post(url, json=body, headers={"Accept": "application/json"})
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexao Infosimples: {str(exc)[:160]}", "certidao": {}}

    try:
        payload = resp.json()
    except Exception:
        payload = {"raw_text": resp.text[:500]}

    if resp.status_code >= 400:
        return {
            "status": "error",
            "message": f"Infosimples {resp.status_code}: {str(payload)[:240]}",
            "certidao": {},
            "raw": payload,
        }

    code = payload.get("code") if isinstance(payload, dict) else None
    status = "ok" if code in (200, None) else "error"
    result = {
        "status": status,
        "message": payload.get("code_message", "") if isinstance(payload, dict) else "",
        "certidao": _first_data(payload) if isinstance(payload, dict) else {},
        "raw": payload,
    }
    if status == "ok":
        _cache[cache_key] = result
    return result
