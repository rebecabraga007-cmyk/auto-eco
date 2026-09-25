"""WorkAPI — busca de pessoas por nome, telefone reverso, e CPF."""

import os
import asyncio
import time

import httpx

import workapi_suspensa

WORKAPI_KEY = os.environ.get("WORKAPI_KEY", "").strip()
WORKAPI_BASE = "https://api.workapi.dev/v1/gateway"
_TIMEOUT = httpx.Timeout(30.0)

# UM cliente para o módulo inteiro, com pool de conexões, em vez de abrir e
# fechar um AsyncClient (e um handshake TLS) por consulta.
#
# Isto sozinho NÃO resolveu a varredura de 166 perfis — eu achei que resolveria
# e estava errado. Com o cliente compartilhado as falhas continuaram, só que
# agora legíveis: HTTP 403 do gateway, não erro de conexão. A causa é rajada, e
# o conserto é o intervalo abaixo. O cliente compartilhado fica porque é certo
# de qualquer forma, não porque tenha consertado alguma coisa.
_cliente: httpx.AsyncClient | None = None
_lock = asyncio.Lock()

# O gateway limita por RAJADA, e recusa com 403 — não com 429. Medido: numa
# varredura de 166 perfis, 38 das 60 chamadas (63%) voltaram 403; os MESMOS
# nomes, chamados com 1,2 s de intervalo, voltaram 200 com dados. Como o 403
# parece "sem permissão", é fácil concluir que a chave perdeu acesso ao módulo
# quando na verdade só foi rápido demais.
_INTERVALO = float(os.environ.get("WORKAPI_INTERVALO", "1.2"))
_ultima = 0.0
_vez = asyncio.Lock()


async def _espera_a_vez() -> None:
    """Garante `_INTERVALO` segundos entre duas chamadas, seja quem chamar."""
    global _ultima
    async with _vez:
        agora = time.monotonic()
        atraso = _INTERVALO - (agora - _ultima)
        if atraso > 0:
            await asyncio.sleep(atraso)
        _ultima = time.monotonic()


async def _http() -> httpx.AsyncClient:
    global _cliente
    if _cliente is None or _cliente.is_closed:
        async with _lock:
            if _cliente is None or _cliente.is_closed:
                _cliente = httpx.AsyncClient(
                    timeout=_TIMEOUT,
                    limits=httpx.Limits(max_connections=8,
                                        max_keepalive_connections=4),
                )
    return _cliente


async def fechar() -> None:
    """Fecha o cliente compartilhado. Chamar no shutdown do serviço."""
    global _cliente
    if _cliente is not None and not _cliente.is_closed:
        await _cliente.aclose()
    _cliente = None


def enabled() -> bool:
    """WorkAPI está configurada (WORKAPI_KEY no .env) -- ou a contingência
    "Work API Suspenso" está respondendo por ela?"""
    return bool(WORKAPI_KEY) or workapi_suspensa.ativo()


async def nome_search(q: str, limit: int = 40, tentativas: int = 2, uf: str = "") -> dict:
    """Busca pessoas por nome na WorkAPI (intelgrax-nomev2).

    Retorna {status, pessoas:[{nome, cpf, dataNascimento, sexo, nomeMae,
    situacaoCadastral, endereco:{logradouro, bairro, municipio, uf, cep}}]}.

    O GATEWAY É INTERMITENTE. Medido: os mesmos três nomes voltaram "Sem
    resultados" numa chamada e completos na seguinte, segundos depois. Por isso
    `tentativas`: um zero da WorkAPI não prova que a pessoa não existe, e tratar
    esse zero como resposta final derruba etapa gratuita do funil e empurra o
    caso para consulta paga sem necessidade. A cota é 2000/dia — repetir uma
    vez custa cota, não dinheiro, e cada repetição só acontece no zero.

    `uf` só é usado pela contingência (a Assertiva filtra por estado na origem,
    o que importa porque ela corta em 50 resultados em ordem alfabética).
    """
    if workapi_suspensa.ativo():
        return await workapi_suspensa.nome(q, limit=limit, uf=uf)
    if not WORKAPI_KEY:
        return {"status": "unavailable", "pessoas": []}
    if not q or not q.strip():
        return {"status": "error", "message": "q obrigatório", "pessoas": []}

    data, erro = None, ""
    for tentativa in range(max(1, tentativas)):
        try:
            await _espera_a_vez()
            client = await _http()
            # WorkAPI não expõe parâmetros de limit/offset — a resposta traz o que acha
            r = await client.get(
                f"{WORKAPI_BASE}/intelgrax-nomev2",
                headers={"x-api-key": WORKAPI_KEY},
                params={"name": q.strip()},
            )
            r.raise_for_status()
            data = r.json()
        except Exception as exc:
            data = None
            erro = "%s: %s" % (type(exc).__name__, str(exc)[:120])
        # `data` pode vir null no envelope — .get("data", {}) devolve None nesse
        # caso (a chave EXISTE), e o .get encadeado estourava AttributeError.
        corpo = ((data or {}).get("data") or {}).get("body") or {}
        if corpo.get("success") is True and (corpo.get("data") or []):
            break
        if tentativa + 1 < max(1, tentativas):
            await asyncio.sleep(0.6 * (tentativa + 1))   # espera crescente

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
