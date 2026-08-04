"""Cliente da API Meetime + deduplicação de leads.

Usado para NÃO prospectar quem já está na Meetime. Baixa os leads existentes
(CNPJ + nome da empresa/contato), e o `dedup()` remove candidatos que batem:
  - por CNPJ (igualdade exata dos 14 dígitos), OU
  - por SIMILARIDADE de nome (equivalente a LIKE %nome% do SQL): nome normalizado
    de um contido no outro, ou todos os tokens significativos presentes.

Config (.env):
- MEETIME_TOKEN        token da API (obrigatório para ativar)
- MEETIME_BASE_URL     default https://api.meetime.com.br
- MEETIME_LEADS_PATH   default /v2/leads
- MEETIME_AUTH_HEADER  default api-token   (nome do header de auth)
- MEETIME_PAGE_SIZE    default 200

Pegadinha da API v2 (ver memória): paginação SÓ com limit+start, ordem crescente;
rejeita sort/date. Por isso paginamos incrementando `start`.
"""
import asyncio
import os
import re
import time
import unicodedata
from typing import Any

import httpx

import config_store

# Config vem do store (admin define pela UI) com fallback pro ambiente.
def _cfg(key, env, default=""):
    v = config_store.get(key)
    if v:
        return str(v).strip()
    return os.environ.get(env, default).strip()


def _token() -> str:
    return _cfg("meetime_token", "MEETIME_TOKEN", "")


def _base_url() -> str:
    return _cfg("meetime_base_url", "MEETIME_BASE_URL", "https://api.meetime.com.br").rstrip("/")


def _leads_path() -> str:
    return _cfg("meetime_leads_path", "MEETIME_LEADS_PATH", "/v2/leads")


def _auth_header() -> str:
    return _cfg("meetime_auth_header", "MEETIME_AUTH_HEADER", "api-token")


PAGE_SIZE = int(os.environ.get("MEETIME_PAGE_SIZE", "50") or "50")
_TIMEOUT = httpx.Timeout(40.0)

# Sufixos societários irrelevantes para comparar nomes.
_SUFIXOS = re.compile(
    r"\b(ltda|epp|me|eireli|s\s?a|sa|s/a|sociedade|anonima|limitada|"
    r"comercio|comercial|industria|industrial|servicos|transportes|transporte|"
    r"do brasil|brasil|cia|companhia|grupo|holding|participacoes)\b")

# Cache em memória dos existentes (evita rebaixar a API a cada dedup).
_cache: dict[str, Any] = {"ts": 0, "cnpjs": set(), "nomes": []}
_CACHE_TTL = 1800  # 30 min


def enabled() -> bool:
    return bool(_token() and _base_url())


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))


def norm_nome(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _SUFIXOS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(nome_norm: str) -> set:
    return {t for t in nome_norm.split() if len(t) >= 3}


def _extrai_lead(rec: dict) -> tuple[str, list[str]]:
    """Extrai (cnpj_digits, [nomes]) de um registro de lead, de forma defensiva."""
    cnpj, nomes = "", []
    if not isinstance(rec, dict):
        return cnpj, nomes
    for k in ("cnpj", "document", "documento", "cpf_cnpj", "companyDocument"):
        if rec.get(k):
            d = only_digits(rec[k])
            if len(d) == 14:
                cnpj = d
                break
    for k in ("company", "companyName", "razaoSocial", "razao_social", "empresa",
              "name", "nome", "lead_company", "tradeName", "nomeFantasia"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            nomes.append(v.strip())
        elif isinstance(v, dict):  # às vezes company é objeto {name:...}
            for kk in ("name", "razaoSocial", "nome"):
                if v.get(kk):
                    nomes.append(str(v[kk]))
    return cnpj, nomes


async def fetch_existing(max_pages: int = 200, force: bool = False) -> dict:
    """Baixa (paginando) os leads da Meetime → {cnpjs:set, nomes:[(norm, tokens)]}."""
    if not enabled():
        return {"status": "unavailable", "message": "Meetime não configurada (MEETIME_TOKEN).",
                "cnpjs": set(), "nomes": []}
    now = time.time()
    if not force and _cache["ts"] and now - _cache["ts"] < _CACHE_TTL:
        return {"status": "ok", "cnpjs": _cache["cnpjs"], "nomes": _cache["nomes"],
                "total": len(_cache["cnpjs"]) + len(_cache["nomes"]), "cache": True}

    headers = {"Accept": "application/json", _auth_header(): _token()}
    cnpjs, nomes = set(), []
    url = _base_url() + _leads_path()
    start = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for _ in range(max_pages):
                resp = None
                for tentativa in range(4):
                    resp = await client.get(url, params={"limit": PAGE_SIZE, "start": start}, headers=headers)
                    if resp.status_code != 429:
                        break
                    await asyncio.sleep(2.5 * (tentativa + 1))
                if resp.status_code == 401:
                    return {"status": "no_access", "message": "Token Meetime inválido (401).",
                            "cnpjs": set(), "nomes": []}
                if resp.status_code >= 400:
                    return {"status": "error", "message": f"Meetime {resp.status_code}: {resp.text[:200]}",
                            "cnpjs": cnpjs, "nomes": nomes}
                j = resp.json()
                # a lista pode vir na raiz ou em data/results/leads
                lote = j if isinstance(j, list) else (
                    j.get("data") or j.get("results") or j.get("leads") or j.get("items") or [])
                if not lote:
                    break
                for rec in lote:
                    cnpj, nms = _extrai_lead(rec)
                    if cnpj:
                        cnpjs.add(cnpj)
                    for nm in nms:
                        nn = norm_nome(nm)
                        if nn:
                            nomes.append((nn, _tokens(nn)))
                if len(lote) < PAGE_SIZE:
                    break
                start += PAGE_SIZE
                await asyncio.sleep(1.2)
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexão Meetime: {str(exc)[:150]}",
                "cnpjs": cnpjs, "nomes": nomes}

    _cache.update(ts=now, cnpjs=cnpjs, nomes=nomes)
    return {"status": "ok", "cnpjs": cnpjs, "nomes": nomes,
            "total_cnpjs": len(cnpjs), "total_nomes": len(nomes), "cache": False}


def _nome_bate(cand_norm: str, cand_tokens: set, existentes: list) -> bool:
    """Similaridade tipo LIKE %: substring nos dois sentidos OU tokens contidos."""
    if not cand_norm:
        return False
    for nn, toks in existentes:
        if not nn:
            continue
        if cand_norm in nn or nn in cand_norm:      # LIKE %nome%
            return True
        # todos os tokens significativos do menor presentes no maior
        if cand_tokens and toks:
            menor, maior = (cand_tokens, toks) if len(cand_tokens) <= len(toks) else (toks, cand_tokens)
            if len(menor) >= 2 and menor.issubset(maior):
                return True
    return False


def dedup(candidatos: list[dict], existing: dict) -> dict:
    """Separa candidatos em novos vs já-na-meetime (por CNPJ ou nome).

    candidatos: [{cnpj, razao_social|razao|nome}]. Retorna {novos, removidos}.
    """
    cnpjs = existing.get("cnpjs") or set()
    nomes = existing.get("nomes") or []
    novos, removidos = [], []
    for c in candidatos:
        cnpj = only_digits(c.get("cnpj") or "")
        razao = c.get("razao_social") or c.get("razao") or c.get("nome") or ""
        motivo = None
        if len(cnpj) == 14 and cnpj in cnpjs:
            motivo = "cnpj"
        else:
            nn = norm_nome(razao)
            if _nome_bate(nn, _tokens(nn), nomes):
                motivo = "nome"
        if motivo:
            removidos.append({**c, "_dedup": motivo})
        else:
            novos.append(c)
    return {"novos": novos, "removidos": removidos,
            "n_novos": len(novos), "n_removidos": len(removidos)}
