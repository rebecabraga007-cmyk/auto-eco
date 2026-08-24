"""Cliente da API v2 do Meetime — usado para migrar a operação real para o Bluutime.

Descoberto sondando a API com o token da conta BLU (a documentação oficial
descreve `Authorization: Bearer <token>`, mas o servidor só aceita o token
**cru**, sem esquema; com "Bearer" ele devolve 401/429).

Envelope de listagem:
    {"data": [...], "limit", "start", "size", "totalItems", "next"}

Paginação: só `limit` + `start`, ordem crescente — a API rejeita `sort`/`date`.
Por isso paginamos incrementando `start` e paramos quando `size < limit`.
"""
import asyncio
import os

import httpx

BASE_URL = os.environ.get("MEETIME_BASE_URL", "https://api.meetime.com.br/v2").rstrip("/")
# Teto da API: "Limit must be less than or equal to 100".
PAGE_SIZE = min(int(os.environ.get("MEETIME_PAGE_SIZE", "100") or 100), 100)

# /v2/calls é pesado (103 mil registros na conta BLU) e estoura o timeout padrão.
_TIMEOUT = httpx.Timeout(120.0, connect=20.0)

RESOURCES = ["users", "cadences", "leads", "prospections", "calls", "webhooks", "feedbacks"]


def token() -> str:
    return (os.environ.get("MEETIME_TOKEN") or "").strip()


def enabled() -> bool:
    return bool(token())


def _headers() -> dict:
    return {"Authorization": token(), "Accept": "application/json"}


async def _get(client: httpx.AsyncClient, path: str, params: dict) -> httpx.Response:
    """GET com repique. 429 é limite de taxa ('Rate exceeded.'); 503 acontece nos
    recursos grandes — /v2/calls tem 103 mil registros na conta BLU e cede sob
    pressão. Nos dois casos o caminho é esperar e tentar de novo."""
    delay = 3.0
    for attempt in range(6):
        try:
            r = await client.get(f"{BASE_URL}/{path.lstrip('/')}",
                                 headers=_headers(), params=params)
        except httpx.RequestError:
            if attempt == 5:
                raise
            await asyncio.sleep(delay)
            delay *= 1.7
            continue
        if r.status_code not in (429, 502, 503, 504):
            return r
        await asyncio.sleep(delay)
        delay *= 1.7
    return r


async def page(resource: str, start: int = 0, limit: int = 50) -> dict:
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _get(client, resource, {"limit": limit, "start": start})
    if r.status_code == 401:
        raise PermissionError("Token do Meetime inválido ou sem acesso (401).")
    if r.status_code >= 400:
        raise RuntimeError(f"Meetime {r.status_code}: {r.text[:200]}")
    return r.json()


async def total_items(resource: str, params: dict | None = None) -> int | None:
    """Total do conjunto — precisa levar os mesmos filtros, senão o `start`
    calculado para a cauda cai fora do recorte e a página volta vazia."""
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        r = await _get(client, resource, {**(params or {}), "limit": 1})
    if r.status_code >= 400:
        return None
    return r.json().get("totalItems")


async def fetch_all(resource: str, max_records: int = 2000,
                    params: dict | None = None, newest: bool = True) -> list[dict]:
    """Pagina até `max_records`. O teto existe de propósito: a conta tem 103 mil
    ligações, e puxar tudo levaria horas de rate limit.

    A API só ordena crescente e rejeita `sort` — então paginar do zero traz os
    registros **mais antigos**, que para uma operação viva são inúteis (leads de
    2024 sem prospecção correspondente). Com `newest`, pulamos direto para a
    cauda usando o `totalItems` que a própria API informa.
    """
    out: list[dict] = []
    start = 0
    if newest:
        total = await total_items(resource, params)
        if total:
            start = max(0, total - max_records)
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        while len(out) < max_records:
            limit = min(PAGE_SIZE, max_records - len(out))
            r = await _get(client, resource, {**(params or {}), "limit": limit, "start": start})
            if r.status_code == 401:
                raise PermissionError("Token do Meetime inválido ou sem acesso (401).")
            if r.status_code >= 400:
                raise RuntimeError(f"Meetime {r.status_code} em {resource}: {r.text[:200]}")
            payload = r.json()
            batch = payload.get("data") or []
            out.extend(batch)
            if len(batch) < limit or not payload.get("next"):
                break
            start += limit
            await asyncio.sleep(0.7)
    return out


async def prospections_for_leads(lead_ids: list[str], concurrency: int = 4,
                                 progress=None) -> dict[str, dict]:
    """A prospecção atual de cada lead, buscada por `?lead_id=`.

    Paginar /v2/prospections não serve para juntar com os leads: o `totalItems`
    do recurso (18.645) não corresponde ao conjunto real — a cauda paginável
    para em prospecções de id ~27M, enquanto os leads vivos apontam para ~37M —
    e em consultas filtradas o `totalItems` volta nulo. A consulta por lead é a
    única junção exata que a API oferece.
    """
    out: dict[str, dict] = {}
    sem = asyncio.Semaphore(concurrency)

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        async def one(lead_id: str):
            async with sem:
                r = await _get(client, "prospections", {"lead_id": lead_id, "limit": 5})
                if r.status_code >= 400:
                    return
                rows = r.json().get("data") or []
                if not rows:
                    return
                # A API devolve em ordem crescente; a última é a prospecção atual.
                out[str(lead_id)] = rows[-1]
                await asyncio.sleep(0.05)

        step = 200
        for i in range(0, len(lead_ids), step):
            await asyncio.gather(*(one(x) for x in lead_ids[i:i + step]))
            if progress:
                progress(min(i + step, len(lead_ids)), len(lead_ids))
    return out


async def counts(prazo: float = 20.0) -> dict:
    """Quantos registros existem de cada recurso, sem baixá-los.

    Antes isto percorria os 7 recursos em série, com `sleep(0.6)` entre cada e
    repique de até 6 tentativas em 429 — o pior caso passava de dois minutos e a
    rota simplesmente não voltava.

    Agora vão de três em três (a API limita taxa; paralelismo maior só provoca
    429) e o conjunto tem prazo: o que não responder a tempo volta como
    `"tempo esgotado"` em vez de segurar a resposta inteira.
    """
    result: dict[str, object] = {}
    sem = asyncio.Semaphore(3)

    async def um(client: httpx.AsyncClient, resource: str) -> None:
        async with sem:
            try:
                r = await _get(client, resource, {"limit": 1})
                result[resource] = (r.json().get("totalItems")
                                    if r.status_code < 300 else f"erro {r.status_code}")
            except Exception as exc:
                result[resource] = f"falha: {type(exc).__name__}"

    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        tarefas = [asyncio.create_task(um(client, r)) for r in RESOURCES]
        _, pendentes = await asyncio.wait(tarefas, timeout=prazo)
        for t in pendentes:
            t.cancel()
    for resource in RESOURCES:
        result.setdefault(resource, "tempo esgotado")
    return result
