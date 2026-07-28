"""Cliente da Serasa Experian - Infomais 2.0 (enriquecimento PF e PJ).

Fluxo:
1. Gera token JWT via Basic Auth (Client Id / Secret) e cacheia ate expirar.
2. Enriquece por CPF (people) ou CNPJ (organizations), pedindo APENAS os
   atributos necessarios (minimizacao de dados / LGPD): telefone, email, nome.

Credenciais e ambiente vem de variaveis de ambiente:
- SERASA_CLIENT_ID, SERASA_CLIENT_SECRET   (obrigatorios para ativar)
- SERASA_ENV = "prod" (default) | "uat"
- SERASA_PACKAGE_TOKEN                      (opcional, se o contrato usa pacote)

Sem credenciais, `enabled()` retorna False e o resto do sistema ignora a Serasa.
"""

import base64
import os
import re
import time
from typing import Any

import httpx

CLIENT_ID = os.environ.get("SERASA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("SERASA_CLIENT_SECRET", "").strip()
ENV = os.environ.get("SERASA_ENV", "prod").strip().lower()
PACKAGE_TOKEN = os.environ.get("SERASA_PACKAGE_TOKEN", "").strip()

_BASE = (
    "https://api.serasaexperian.com.br"
    if ENV != "uat"
    else "https://uat-api.serasaexperian.com.br"
)
_LOGIN_URL = f"{_BASE}/security/iam/v1/client-identities/login"
_PEOPLE_URL = f"{_BASE}/ms-da/enrichment/v1/enrichments/people"
_ORG_URL = f"{_BASE}/ms-da/enrichment/v1/enrichments/organizations"

_TIMEOUT = httpx.Timeout(50.0)

# Atributos minimos (so o necessario para prospeccao).
PF_ATTRIBUTES = ["DOCUMENT", "NAME", "PHONES", "EMAIL"]
PJ_ATTRIBUTES = ["DOCUMENT", "BUSINESSNAME", "PHONES", "EMAIL"]

# Cache de token: {"token":..., "exp": epoch_seconds}
_token_cache: dict[str, Any] = {}
# Cache de resultados por documento (evita reconsulta/custo).
_result_cache: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    return bool(CLIENT_ID and CLIENT_SECRET)


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


async def _get_token(client: httpx.AsyncClient) -> str | None:
    now = time.time()
    if _token_cache.get("token") and _token_cache.get("exp", 0) > now + 30:
        return _token_cache["token"]

    basic = base64.b64encode(f"{CLIENT_ID}:{CLIENT_SECRET}".encode()).decode()
    resp = await client.post(
        _LOGIN_URL,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"},
    )
    if resp.status_code >= 400:
        return None
    data = resp.json()
    token = data.get("accessToken")
    try:
        expires_in = int(data.get("expiresIn", 300))
    except (TypeError, ValueError):
        expires_in = 300
    _token_cache["token"] = token
    _token_cache["exp"] = now + expires_in
    return token


def _fmt_phones(raw: Any) -> list[dict[str, Any]]:
    out = []
    for p in raw or []:
        if not isinstance(p, dict):
            continue
        ddd = str(p.get("areaCode") or "").strip()
        num = str(p.get("number") or "").strip()
        if not num:
            continue
        out.append({
            "ddd": ddd,
            "number": num,
            "mobile": bool(p.get("mobile")),
            "type": p.get("type") or "",
            "fonte": p.get("fontePesquisada") or "",
        })
    return out


def _fmt_emails(raw: Any) -> list[str]:
    out = []
    for e in raw or []:
        if isinstance(e, dict) and e.get("address"):
            out.append(e["address"])
        elif isinstance(e, str) and e:
            out.append(e)
    return out


async def _enrich(url: str, document: str, attributes: list[str]) -> dict[str, Any]:
    if not enabled():
        return {"status": "unavailable", "message": "Serasa nao configurada."}
    if document in _result_cache:
        return _result_cache[document]

    body: dict[str, Any] = {"document": document, "attributes": attributes}
    if PACKAGE_TOKEN:
        body["packageToken"] = PACKAGE_TOKEN

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            token = await _get_token(client)
            if not token:
                return {"status": "error", "message": "Falha ao autenticar na Serasa."}
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=body,
            )
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexao Serasa: {str(exc)[:120]}"}

    if resp.status_code == 404:
        result = {"status": "not_found", "message": "Documento nao encontrado."}
        _result_cache[document] = result
        return result
    if resp.status_code >= 400:
        return {"status": "error", "message": f"Serasa {resp.status_code}: {resp.text[:150]}"}

    try:
        data = resp.json()
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Serasa."}

    result = {
        "status": "ok",
        "document": data.get("document") or document,
        "phones": _fmt_phones(data.get("phones")),
        "emails": _fmt_emails(data.get("email")) or data.get("emailValidado") or [],
        "raw_name": data.get("name") or data.get("businessName"),
    }
    _result_cache[document] = result
    return result


async def enrich_person(cpf: str) -> dict[str, Any]:
    """Telefones/emails de uma PF por CPF (11 digitos)."""
    doc = only_digits(cpf).zfill(11)[:11]
    return await _enrich(_PEOPLE_URL, doc, PF_ATTRIBUTES)


async def enrich_company(cnpj: str) -> dict[str, Any]:
    """Telefones/emails de uma PJ por CNPJ (14 digitos)."""
    doc = only_digits(cnpj).zfill(14)[:14]
    return await _enrich(_ORG_URL, doc, PJ_ATTRIBUTES)
