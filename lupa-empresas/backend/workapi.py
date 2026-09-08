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


async def nome_search(q: str, limit: int = 40, tentativas: int = 2) -> dict:
    """Busca pessoas por nome na WorkAPI (intelgrax-nomev2).

    Retorna {status, pessoas:[{nome, cpf, dataNascimento, sexo, nomeMae,
    situacaoCadastral, endereco:{logradouro, bairro, municipio, uf, cep}}]}.

    O GATEWAY É INTERMITENTE. Medido: os mesmos três nomes voltaram "Sem
    resultados" numa chamada e completos na seguinte, segundos depois. Por isso
    `tentativas`: um zero da WorkAPI não prova que a pessoa não existe, e tratar
    esse zero como resposta final derruba etapa gratuita do funil e empurra o
    caso para consulta paga sem necessidade. A cota é 2000/dia — repetir uma
    vez custa cota, não dinheiro, e cada repetição só acontece no zero.
    """
    if not WORKAPI_KEY:
        return {"status": "unavailable", "pessoas": []}
    if not q or not q.strip():
        return {"status": "error", "message": "q obrigatório", "pessoas": []}

    data, erro = None, ""
    for tentativa in range(max(1, tentativas)):
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                # WorkAPI não expõe parâmetros de limit/offset — a resposta traz o que acha
                r = await client.get(
                    f"{WORKAPI_BASE}/intelgrax-nomev2",
                    headers={"x-api-key": WORKAPI_KEY},
                    params={"name": q.strip()},
                )
                r.raise_for_status()
                data = r.json()
        except Exception as exc:
            data, erro = None, f"WorkAPI erro: {str(exc)[:100]}"
        # `data` pode vir null no envelope — .get("data", {}) devolve None nesse
        # caso (a chave EXISTE), e o .get encadeado estourava AttributeError.
        corpo = ((data or {}).get("data") or {}).get("body") or {}
        if corpo.get("success") is True and (corpo.get("data") or []):
            break
        if tentativa + 1 < max(1, tentativas):
            await asyncio.sleep(0.6)

    if data is None:
        return {"status": "error", "message": erro or "WorkAPI sem resposta",
                "pessoas": []}
    corpo = ((data or {}).get("data") or {}).get("body") or {}
    if corpo.get("success") is not True:
        return {"status": "ok", "pessoas": [],
                "message": corpo.get("statusMsg") or "Sem resultados"}

    brutos = corpo.get("data") or []
    pessoas = []
    for p in brutos[:limit]:
        if not isinstance(p, dict):
            continue
        cpf = p.get("cpf") or ""
        # ERA FALSO que este módulo mascara o CPF: o intelgrax-nomev2 devolve os
        # 11 dígitos inteiros ("22284156851"). O comentário antigo dizia
        # "347*****821" e fazia parecer que a etapa gratuita não dava CPF
        # utilizável — dá, e é o que torna o funil barato. `cpf_mascarado` fica
        # só para não quebrar o front, marcando de fato se veio máscara.
        endereco = p.get("endereco") or {}
        pessoas.append({
            "nome": p.get("nome") or "",
            "cpf": cpf,
            "cpf_mascarado": "*" in cpf,
            "data_nascimento": p.get("dataNascimento") or "",
            "sexo": p.get("sexo") or "",
            "nome_mae": p.get("nomeMae") or "",
            "situacao_cadastral": p.get("situacaoCadastral") or "",
            # A API manda `cidade` e `numero`; ler só `municipio`/`logradouroNumero`
            # devolvia cidade SEMPRE vazia — o que arruinava qualquer
            # desambiguação por cidade sem dar erro nenhum. Aceita os dois nomes.
            "endereco": {
                "logradouro": endereco.get("logradouro") or "",
                "numero": (endereco.get("numero")
                           or endereco.get("logradouroNumero") or ""),
                "complemento": endereco.get("complemento") or "",
                "bairro": endereco.get("bairro") or "",
                "municipio": (endereco.get("cidade")
                              or endereco.get("municipio") or ""),
                "cidade": (endereco.get("cidade")
                           or endereco.get("municipio") or ""),
                # "SEM INFORMACAO" é ausência de dado, não uma UF: deixar passar
                # como se fosse faria o filtro tratar 25% da base como estado errado.
                "uf": ("" if str(endereco.get("uf") or "").strip().upper()
                       in ("SEM INFORMACAO", "NAO INFORMADO", "N/A")
                       else (endereco.get("uf") or "")),
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
