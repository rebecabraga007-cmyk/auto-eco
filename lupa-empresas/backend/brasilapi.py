"""Wrapper para BrasilAPI (dados de CNPJ) + busca por nome via Casa dos Dados.

A BrasilAPI (https://brasilapi.com.br/api/cnpj/v1/{cnpj}) SO aceita CNPJ exato
(14 digitos). Para busca por nome usamos a API da Casa dos Dados via cloudscraper
(necessario para bypassar Cloudflare): GET /v4/public/pesquisa/nome?q=...
"""

import re
from typing import Any

import httpx

try:
    import cloudscraper as _cs_mod
    _scraper = _cs_mod.create_scraper()
except Exception:
    _scraper = None

BRASILAPI_CNPJ = "https://brasilapi.com.br/api/cnpj/v1/{cnpj}"
CASADOSDADOS_NOME = "https://api.casadosdados.com.br/v4/public/pesquisa/nome"
CASADOSDADOS_HEADERS = {
    "Accept": "application/json",
    "Origin": "https://casadosdados.com.br",
    "Referer": "https://casadosdados.com.br/",
}

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
}

_TIMEOUT = httpx.Timeout(20.0)


def only_digits(value: str) -> str:
    return re.sub(r"\D", "", value or "")


def is_cnpj(value: str) -> bool:
    return len(only_digits(value)) == 14


def format_cnpj(digits: str) -> str:
    d = only_digits(digits)
    if len(d) != 14:
        return digits
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


async def fetch_company(cnpj: str) -> dict[str, Any]:
    """Retorna os dados completos da empresa via BrasilAPI."""
    digits = only_digits(cnpj)
    if len(digits) != 14:
        raise ValueError("CNPJ invalido (precisa de 14 digitos).")

    url = BRASILAPI_CNPJ.format(cnpj=digits)
    async with httpx.AsyncClient(timeout=_TIMEOUT, headers=DEFAULT_HEADERS) as client:
        resp = await client.get(url)
    if resp.status_code == 404:
        raise LookupError("CNPJ nao encontrado na BrasilAPI.")
    resp.raise_for_status()
    return resp.json()


def _simplify_brasilapi(data: dict[str, Any]) -> dict[str, Any]:
    return {
        "cnpj": format_cnpj(str(data.get("cnpj", ""))),
        "razao_social": data.get("razao_social") or "",
        "nome_fantasia": data.get("nome_fantasia") or "",
        "municipio": data.get("municipio") or "",
        "uf": data.get("uf") or "",
        "situacao": data.get("descricao_situacao_cadastral") or "",
    }


def _simplify_casadosdados(item: dict[str, Any]) -> dict[str, Any]:
    sit = item.get("situacao_cadastral") or {}
    sit_str = sit.get("situacao_atual") if isinstance(sit, dict) else (sit or "")
    return {
        "cnpj": format_cnpj(str(item.get("cnpj", ""))),
        "razao_social": item.get("razao_social") or "",
        "nome_fantasia": item.get("nome_fantasia") or "",
        "municipio": item.get("municipio") or "",
        "uf": item.get("uf") or "",
        "descricao_situacao_cadastral": sit_str or "",
    }


async def search_companies(q: str) -> dict[str, Any]:
    """Busca empresas por CNPJ (exato) ou por nome (Casa dos Dados).

    Retorna dict com chaves: status, results, message.
    """
    q = (q or "").strip()
    if not q:
        return {"status": "ok", "results": [], "message": "Digite um CNPJ ou nome."}

    # CNPJ exato -> BrasilAPI
    if is_cnpj(q):
        try:
            data = await fetch_company(q)
            return {"status": "ok", "results": [_simplify_brasilapi(data)], "message": ""}
        except LookupError:
            return {"status": "ok", "results": [], "message": "CNPJ nao encontrado."}
        except Exception:
            return {
                "status": "error",
                "results": [],
                "message": "Falha ao consultar a BrasilAPI. Tente novamente.",
            }

    # Nome -> Casa dos Dados (GET /v4/public/pesquisa/nome via cloudscraper)
    try:
        import asyncio

        def _sync_search(term: str):
            if not _scraper:
                raise RuntimeError("cloudscraper indisponivel")
            resp = _scraper.get(
                CASADOSDADOS_NOME,
                params={"q": term, "pagina": 1},
                headers=CASADOSDADOS_HEADERS,
                timeout=20,
            )
            resp.raise_for_status()
            return resp.json()

        body = await asyncio.get_event_loop().run_in_executor(None, _sync_search, q)
        raw = body.get("cnpjs") or []

        # Se nao encontrou, tenta com as duas primeiras palavras (nomes compostos)
        if not raw and len(q.split()) > 2:
            short = " ".join(q.split()[:2])
            body2 = await asyncio.get_event_loop().run_in_executor(None, _sync_search, short)
            raw = body2.get("cnpjs") or []

        results = [_simplify_casadosdados(item) for item in raw]
        if not results:
            return {
                "status": "ok",
                "results": [],
                "message": "Nenhuma empresa encontrada para esse nome.",
            }
        return {"status": "ok", "results": results, "message": ""}
    except Exception:
        return {
            "status": "error",
            "results": [],
            "message": (
                "A busca por nome esta indisponivel no momento. "
                "Tente buscar pelo CNPJ (14 digitos)."
            ),
        }
