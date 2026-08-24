"""WorkAPI — busca de pessoas por nome, telefone reverso, e CPF."""

import os
import asyncio
import httpx

WORKAPI_KEY = os.environ.get("WORKAPI_KEY", "").strip()
WORKAPI_BASE = "https://api.workapi.dev/v1/gateway"
_TIMEOUT = httpx.Timeout(30.0)


def enabled() -> bool:
    """WorkAPI está configurada (WORKAPI_KEY no .env)?"""
    return bool(WORKAPI_KEY)


async def nome_search(q: str, limit: int = 40) -> dict:
    """Busca pessoas por nome na WorkAPI (database-nome).

    Retorna {status, pessoas:[{nome, cpf, dataNascimento, sexo, nomeMae,
    situacaoCadastral, endereco:{logradouro, bairro, municipio, uf, cep}}]}.
    """
    if not WORKAPI_KEY:
        return {"status": "unavailable", "pessoas": []}
    if not q or not q.strip():
        return {"status": "error", "message": "q obrigatório", "pessoas": []}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # WorkAPI não expõe parâmetros de limit/offset — a resposta traz o que acha
            r = await client.get(
                f"{WORKAPI_BASE}/database-nome",
                headers={"x-api-key": WORKAPI_KEY},
                params={"nome": q.strip()},
            )
            r.raise_for_status()
            data = r.json()
    except Exception as exc:
        return {"status": "error", "message": f"WorkAPI erro: {str(exc)[:100]}", "pessoas": []}

    # Resposta padrão WorkAPI: {apiId, remainingDaily, dailyLimit, data:{module, status, body:{status, statusMsg, success, data:[...]}}}
    if data.get("data", {}).get("body", {}).get("success") is not True:
        msg = data.get("data", {}).get("body", {}).get("statusMsg", "Sem resultados")
        return {"status": "ok", "pessoas": [], "message": msg}

    brutos = data.get("data", {}).get("body", {}).get("data") or []
    pessoas = []
    for p in brutos[:limit]:
        if not isinstance(p, dict):
            continue
        cpf = p.get("cpf") or ""
        # WorkAPI retorna CPF parcialmente mascarado: "347*****821"
        # Guardamos como está; o front vai tratar o mascaramento
        endereco = p.get("endereco") or {}
        pessoas.append({
            "nome": p.get("nome") or "",
            "cpf": cpf,
            "cpf_mascarado": cpf,  # marca que veio mascarado
            "data_nascimento": p.get("dataNascimento") or "",
            "sexo": p.get("sexo") or "",
            "nome_mae": p.get("nomeMae") or "",
            "situacao_cadastral": p.get("situacaoCadastral") or "",
            "endereco": {
                "logradouro": endereco.get("logradouro") or "",
                "numero": endereco.get("logradouroNumero") or "",
                "bairro": endereco.get("bairro") or "",
                "municipio": endereco.get("municipio") or "",
                "uf": endereco.get("uf") or "",
                "cep": endereco.get("cep") or "",
            },
            "fonte": "WorkAPI",
        })

    return {
        "status": "ok",
        "pessoas": pessoas,
        "remaining_daily": data.get("remainingDaily"),
        "daily_limit": data.get("dailyLimit"),
    }
