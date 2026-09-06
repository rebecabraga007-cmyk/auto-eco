# -*- coding: utf-8 -*-
"""Busca funcionarios de uma empresa no dataset de perfis do LinkedIn (Bright Data).

NAO baixa a base inteira. Manda o criterio (empresa + pais + cargo) para a API de
filtro do Marketplace, que devolve so quem casa. O dataset e o mesmo de onde sai o
snapshot completo — a diferenca e perguntar em vez de baixar 669 MB de perfis
aleatorios do mundo todo.

ATENCAO AOS CAMINHOS. Os que estavam no `linkedin_scraper.py` sao de uma versao
antiga da API e respondem 404:
    /datasets/v3/filter         -> "Cannot POST"        | certo: /datasets/filter
    /datasets/v3/snapshot/{id}  -> "does not exist"     | certo: /datasets/snapshots/{id}/download

O JOB E ASSINCRONO e leva de ~1 a 4 minutos (empresa especifica e rapido; filtro
largo, tipo "todo o Brasil", demora bem mais). Por isso a busca e em duas partes:
`disparar()` devolve um protocolo, `consultar()` diz se ficou pronto. Segurar a
requisicao HTTP esperando o job daria timeout no proxy do Render.

CUSTA DINHEIRO POR REGISTRO ENTREGUE, nao por consulta. Por isso `limite` e
sempre explicito e o padrao e baixo.
"""
import os
import re
from typing import Any

import httpx

CHAVE = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
DATASET = os.environ.get("BRIGHTDATA_PEOPLE_DATASET_ID", "gd_l1viktl72bvl7bjuj0").strip()
FILTER_URL = "https://api.brightdata.com/datasets/filter"
SNAP_URL = "https://api.brightdata.com/datasets/snapshots"

LIMITE_PADRAO = int(os.environ.get("BRIGHTDATA_DATASET_LIMIT", "50"))
LIMITE_MAX = int(os.environ.get("BRIGHTDATA_LIMITE_MAX", "500"))
_TIMEOUT = httpx.Timeout(90.0)


def enabled() -> bool:
    return bool(CHAVE and DATASET)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + CHAVE, "Content-Type": "application/json"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


async def disparar(empresa: str, pais: str = "BR", cargo: str = "",
                   limite: int = 0) -> dict[str, Any]:
    """Dispara o filtro. Retorna {status, protocolo} — NAO espera o resultado."""
    if not enabled():
        return {"status": "unavailable",
                "message": "Bright Data nao configurada (BRIGHTDATA_API_KEY)."}
    empresa = _norm(empresa)
    if not empresa:
        return {"status": "error", "message": "Informe o nome da empresa."}

    limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAX))

    condicoes = [{"name": "current_company_name", "operator": "includes", "value": empresa}]
    if pais:
        condicoes.append({"name": "country_code", "operator": "=", "value": pais.upper()[:2]})
    if _norm(cargo):
        condicoes.append({"name": "position", "operator": "includes", "value": _norm(cargo)})

    corpo = {
        "dataset_id": DATASET,
        "records_limit": limite,
        # A API aceita filtro simples OU composto; com uma condicao so, o formato
        # composto tambem vale, entao nao ha caminho especial aqui.
        "filter": {"operator": "and", "filters": condicoes},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(FILTER_URL + "?format=json", headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "message": "Falha ao falar com a Bright Data: %s"
                                              % str(exc)[:140]}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "Bright Data %s: %s" % (r.status_code, r.text[:200])}
    try:
        d = r.json()
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Bright Data."}

    protocolo = d.get("snapshot_id") or d.get("id")
    if not protocolo:
        return {"status": "error", "message": "A Bright Data nao devolveu protocolo."}
    return {
        "status": "ok",
        "protocolo": protocolo,
        "empresa": empresa,
        "pais": pais.upper()[:2] if pais else "",
        "cargo": _norm(cargo),
        "limite": limite,
        "message": "Busca enviada. Costuma levar de 1 a 4 minutos.",
    }


def _pessoa(rec: dict[str, Any]) -> dict[str, Any]:
    emp = rec.get("current_company") or {}
    if not isinstance(emp, dict):
        emp = {}
    return {
        "nome": rec.get("name") or "",
        "cargo": rec.get("position") or "",
        "empresa": rec.get("current_company_name") or emp.get("name") or "",
        "cidade": rec.get("city") or "",
        "pais": rec.get("country_code") or "",
        "url": rec.get("url") or rec.get("input_url") or "",
        "seguidores": rec.get("followers"),
        "formacao": rec.get("educations_details") or "",
        "sobre": (rec.get("about") or "")[:400],
    }


def _casa_empresa(pessoa: dict[str, Any], alvo: str) -> bool:
    """O operador `includes` da Bright Data casa por substring: buscar 'Movida'
    traz tambem 'Movidata Contabilidade'. Marcamos para o front separar."""
    emp = (pessoa.get("empresa") or "").lower()
    alvo = (alvo or "").lower().strip()
    if not alvo or not emp:
        return False
    # Casa se o alvo aparece como palavra inteira (evita Movida -> Movidata).
    return re.search(r"(^|\W)" + re.escape(alvo) + r"(\W|$)", emp) is not None


async def consultar(protocolo: str, empresa: str = "") -> dict[str, Any]:
    """Diz se o job terminou. status: building | ok | error."""
    if not enabled():
        return {"status": "unavailable", "pessoas": []}
    protocolo = (protocolo or "").strip()
    if not protocolo:
        return {"status": "error", "message": "Protocolo ausente.", "pessoas": []}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.get("%s/%s/download?format=json" % (SNAP_URL, protocolo),
                              headers=_headers())
            if r.status_code in (202, 404) or (
                    r.status_code == 400 and "not ready" in r.text.lower()):
                # Ainda montando. Buscamos o estado so para mostrar algo util na tela.
                meta = await cli.get("%s/%s" % (SNAP_URL, protocolo), headers=_headers())
                estado = ""
                if meta.status_code < 400:
                    try:
                        estado = meta.json().get("status", "")
                    except Exception:
                        pass
                return {"status": "building", "estado": estado or "building",
                        "pessoas": [],
                        "message": "Ainda processando na Bright Data."}
            if r.status_code >= 400:
                return {"status": "error",
                        "message": "Bright Data %s: %s" % (r.status_code, r.text[:200]),
                        "pessoas": []}
            # LER OS BYTES, NAO O `.text`. A resposta vem em UTF-8 mas SEM charset
            # no Content-Type; o httpx entao adivinha Latin-1 e "São Paulo" chega
            # como "SÃ£o Paulo". `json.loads` sobre bytes assume UTF-8 e acerta.
            import json as _json
            try:
                bruto = _json.loads(r.content)
            except Exception:
                # Pode vir NDJSON (um objeto por linha).
                linhas = r.content.decode("utf-8", "replace").splitlines()
                bruto = [_json.loads(l) for l in linhas if l.strip()]
    except Exception as exc:
        return {"status": "error", "message": "Falha de conexao: %s" % str(exc)[:140],
                "pessoas": []}

    regs = bruto if isinstance(bruto, list) else (bruto or {}).get("data") or []
    pessoas = [_pessoa(x) for x in regs if isinstance(x, dict)]

    exatos, parecidos = [], []
    for p in pessoas:
        (exatos if _casa_empresa(p, empresa) else parecidos).append(p)

    return {
        "status": "ok",
        "total": len(pessoas),
        "pessoas": exatos + parecidos,
        "exatos": len(exatos),
        "parecidos": len(parecidos),
        "message": "" if pessoas else
                   "Nenhum perfil no dataset para esse filtro. Tente outra grafia "
                   "do nome da empresa (o dataset guarda o nome como esta no LinkedIn).",
    }
