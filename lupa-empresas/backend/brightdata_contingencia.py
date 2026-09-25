# -*- coding: utf-8 -*-
"""Contingência da Bright Data: leitura ao vivo (Web Scraper) -> busca nas bases (Search).

POR QUE EXISTE
--------------
Entre 17 e 25/set/2026 a conta da Bright Data ficou suspensa. O Web Scraper
(`/datasets/v3/scrape`) respondia `Customer is not active`, e com ele pararam
"dados da empresa pela URL" e "funcionários pelo nome da empresa". A Search
nos MESMOS datasets seguia respondendo com a mesma chave -- é cobrada à parte.

O QUE É DIFERENTE NA SUBSTITUTA (medido em 25/set/2026)
-------------------------------------------------------
- O registro é o do snapshot da base, não o da página agora: pode ter semanas.
- Filtrar por `url` funciona mas é LENTO: ~29 s por busca (o scrape leva 6 s).
  Filtrar por `id` nem termina -- o campo não é indexado (timeout em 60 s).
  Por isso quem chama junta tudo numa busca só (`in`) em vez de uma por URL:
  o limite da Cloudflare é 100 s por requisição.
- Mesmo formato de registro que o scrape (é o mesmo dataset), então quem lê
  a resposta não precisa mudar.
"""
import asyncio
import time
from typing import Any

import httpx

import contingencias

SEARCH_URL = "https://api.brightdata.com/datasets/search/"


def ativo() -> bool:
    return contingencias.ativo("brightdata")


def _url_padrao(u: str) -> str:
    """O dataset guarda `https://www.linkedin.com/...` sem barra final nem query."""
    u = (u or "").strip().split("?")[0].rstrip("/")
    for pre in ("https://br.linkedin.com/", "http://br.linkedin.com/",
                "http://www.linkedin.com/", "https://linkedin.com/", "http://linkedin.com/"):
        if u.startswith(pre):
            u = "https://www.linkedin.com/" + u[len(pre):]
    return u


async def por_url(dataset_id: str, urls: list[str], chave: str,
                  detalhe: str = "") -> tuple[int, Any]:
    """No lugar do POST /v3/scrape. Devolve (status_code, lista_de_registros).

    Cobra por registro entregue, como toda Search -- lança no livro da Bright
    Data (`gastos_bd`) com tipo próprio, para a fatura bater com o painel.
    """
    # No máximo 4 URLs por busca, como no `or` do brightdata_pessoas (5+
    # termos dá 500). As candidatas vêm em ordem de probabilidade.
    alvos = [u for u in dict.fromkeys(_url_padrao(u) for u in urls) if u][:4]
    if not alvos:
        return 200, []
    filtro = ({"name": "url", "operator": "=", "value": alvos[0]} if len(alvos) == 1
              else {"name": "url", "operator": "in", "value": alvos})
    cab = {"Authorization": "Bearer " + chave, "Content-Type": "application/json"}

    async def _pede(cli, corpo):
        # A SEARCH FALHA A ESMO. Medido em 25/set/2026: ~1 em 3 chamadas volta
        # 500 "Response Error" em 0,4 s, com 1, 2, 3 ou 4 URLs, e a MESMA
        # chamada repetida responde 200. Esse 500 instantâneo não entrega
        # registro (não cobra), então repetir é de graça; um 500 lento seria
        # outra coisa e não se repete.
        for n in range(4):
            t0 = time.monotonic()
            r = await cli.post(SEARCH_URL + dataset_id, headers=cab, json=corpo)
            if not (r.status_code >= 500 and time.monotonic() - t0 < 3):
                return r
            await asyncio.sleep(1.5)
        return r

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(90.0)) as cli:
            r = await _pede(cli, {"size": min(len(alvos), 100), "filter": filtro})
            if r.status_code == 400 and len(alvos) > 1:
                # Plano B se o `in` for recusado: `or` de igualdades.
                r = await _pede(cli, {
                    "size": len(alvos),
                    "filter": {"operator": "or", "filters": [
                        {"name": "url", "operator": "=", "value": u} for u in alvos]}})
    except Exception as exc:
        return 599, "Bright Data Search (contingência) sem resposta: %s" % type(exc).__name__
    if r.status_code >= 400:
        return r.status_code, r.text[:300]
    import json as _json
    try:
        hits = (_json.loads(r.content) or {}).get("hits") or []
    except Exception:
        return 502, "resposta ilegível da Bright Data Search"
    try:
        import linkedin_cache
        linkedin_cache.registrar_gasto(
            "search-contingencia", detalhe=(detalhe or alvos[0])[:200],
            registros=len(hits), custo_usd=len(hits) * linkedin_cache.USD_POR_REGISTRO,
            usuario="")
    except Exception:
        pass
    # Mesma ordem dos pedidos: quem chama escolhe o primeiro candidato que casa.
    ordem = {u: i for i, u in enumerate(alvos)}
    hits.sort(key=lambda h: ordem.get(_url_padrao(str(h.get("url") or "")), 999))
    return 200, hits
