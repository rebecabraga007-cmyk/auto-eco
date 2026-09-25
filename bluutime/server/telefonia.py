"""Telefonia pela Zenvia Voice (a antiga TotalVoice).

Como a ligação acontece — o "click-to-call" da Zenvia:

1. O Bluutime pede `POST /chamada` com `numero_origem` = o **ramal** do SDR (ou
   o celular dele) e `numero_destino` = o lead.
2. A Zenvia toca primeiro na origem. Com ramal, quem toca é o **webphone** aberto
   no navegador (a mesma ideia da "Bina inteligente" do Meetime); com celular, o
   telefone do SDR.
3. Atendida a origem, a Zenvia disca para o lead e junta as duas pontas. A
   bina que o lead vê é o DID da conta.

O estado da chamada volta por consulta (`GET /chamada/{id}`) e pelo webhook
`chamada`, e é traduzido para o vocabulário do Bluutime (`Call.status`).

Custa dinheiro de verdade a cada ligação, então nada aqui disca sozinho: toda
chamada nasce de um clique no discador.

A conta da BLU é **pós-paga** (pay as you go): a Zenvia cobra depois, e o
"saldo" que a API devolve não é crédito — com R$ 0,01 ela liga normalmente. Por
isso o saldo não decide nada, a não ser que a conta seja configurada como
pré-paga (`ZENVIA_PREPAGO=1`). O que decide é ter número (DID) e a conta ativa.
"""
import os

import httpx

BASE = "https://voice-api.zenvia.com"
SALDO_MINIMO = 1.0   # só vale para conta pré-paga (ZENVIA_PREPAGO=1)


def pre_paga() -> bool:
    return (os.environ.get("ZENVIA_PREPAGO") or "").strip() == "1"


def token() -> str:
    return (os.environ.get("ZENVIA_VOICE_TOKEN") or "").strip()


def configurado() -> bool:
    return bool(token())


def _cliente() -> httpx.AsyncClient:
    return httpx.AsyncClient(base_url=BASE, timeout=15.0,
                             headers={"Access-Token": token(), "Content-Type": "application/json"})


async def _chamar(metodo: str, caminho: str, **kw) -> tuple[int, dict]:
    """(status HTTP, `dados`) — ou levanta RuntimeError com a mensagem da Zenvia."""
    if not configurado():
        raise RuntimeError("Falta ZENVIA_VOICE_TOKEN no .env.")
    try:
        async with _cliente() as c:
            r = await c.request(metodo, caminho, **kw)
    except httpx.HTTPError as exc:
        raise RuntimeError(f"Não consegui falar com a Zenvia ({type(exc).__name__}).") from exc
    try:
        corpo = r.json()
    except ValueError:
        corpo = {}
    if r.status_code >= 400 or corpo.get("sucesso") is False:
        raise RuntimeError(corpo.get("mensagem") or f"A Zenvia respondeu HTTP {r.status_code}.")
    return r.status_code, corpo.get("dados") or {}


def so_digitos(tel: str) -> str:
    return "".join(ch for ch in str(tel or "") if ch.isdigit())


def numero_destino(tel: str) -> str:
    """Número brasileiro no formato que a Zenvia aceita: DDD + número, sem DDI.
    Com DDI 55 colado, ele sai; com menos de 10 dígitos, volta vazio (não disca)."""
    d = so_digitos(tel)
    if len(d) in (12, 13) and d.startswith("55"):
        d = d[2:]
    return d if len(d) in (10, 11) else ""


async def estado() -> dict:
    """Pode ligar agora? Conta ativa, números (DID) e ramais, lidos na hora."""
    if not configurado():
        return {"configurado": False, "podeLigar": False, "motivo": "Falta ZENVIA_VOICE_TOKEN no .env."}
    try:
        _, s = await _chamar("GET", "/saldo")
        _, conta = await _chamar("GET", "/conta")
        _, d = await _chamar("GET", "/did")
        _, r = await _chamar("GET", "/ramal/relatorio")
    except RuntimeError as exc:
        return {"configurado": True, "podeLigar": False, "motivo": str(exc)}
    saldo = float(s.get("saldo") or 0)
    dids = [{"id": x.get("id"), "numero": x.get("numero"), "cidade": x.get("cidade"),
             "estado": x.get("estado")} for x in (d.get("dids") or [])]
    ramais = [{"id": x.get("id"), "ramal": str(x.get("ramal") or ""), "bina": x.get("bina"),
               "webphone": bool(x.get("webphone")), "ativo": bool(x.get("ativo")),
               "login": x.get("login")} for x in (r.get("relatorio") or [])]
    faltas = []
    if not dids:
        faltas.append("comprar um número (DID)")
    if str(conta.get("conta_ativa", 1)) in ("0", "False", "false"):
        faltas.append("reativar a conta na Zenvia")
    if pre_paga() and saldo < SALDO_MINIMO:
        faltas.append(f"colocar saldo (hoje R$ {saldo:.2f})".replace(".", ","))
    return {"configurado": True, "saldo": saldo, "prePaga": pre_paga(),
            "saldoMinimo": SALDO_MINIMO if pre_paga() else None, "dids": dids,
            "ramais": ramais, "podeLigar": not faltas,
            "motivo": ("Falta " + " e ".join(faltas) + ".") if faltas else ""}


async def webphone_url(ramal: str) -> str:
    """URL assinada do webphone do ramal — abre dentro do Bluutime, com o
    microfone do navegador. Expira; peça de novo a cada sessão de ligações."""
    _, d = await _chamar("GET", "/webphone", params={"ramal": ramal})
    return d.get("url") or ""


async def criar_chamada(origem: str, destino: str, *, gravar: bool = True, tags: str = "") -> str:
    """Dispara a chamada. Devolve o id da Zenvia."""
    corpo = {"numero_origem": origem, "numero_destino": destino, "gravar_audio": bool(gravar),
             "tags": tags[:100]}
    _, d = await _chamar("POST", "/chamada", json=corpo)
    cid = d.get("id")
    if not cid:
        raise RuntimeError("A Zenvia não devolveu o id da chamada.")
    return str(cid)


async def consultar(chamada_id: str) -> dict:
    _, d = await _chamar("GET", f"/chamada/{chamada_id}")
    return d


async def encerrar(chamada_id: str) -> None:
    await _chamar("DELETE", f"/chamada/{chamada_id}")


async def gravacao(chamada_id: str) -> str:
    """URL da gravação, quando existe."""
    d = await consultar(chamada_id)
    return d.get("url_gravacao") or ""


# ── tradução do estado da Zenvia para o do Bluutime ───────────────────────
_ATENDIDA = {"atendida", "atendido", "answered", "em andamento", "conversando"}
_OCUPADO = {"ocupado", "busy"}
_SEM_RESPOSTA = {"sem resposta", "nao atendida", "não atendida", "no answer", "caixa postal",
                 "cancelada", "falha", "congestionado", "invalido", "inválido", "rejeitada"}


def traduzir(dados: dict) -> dict:
    """Do payload de `GET /chamada/{id}` (ou do webhook) para o que o Call guarda.

    `fase` diz em que pé está a tela: origem tocando (o SDR ainda não atendeu),
    destino tocando, em conversa ou encerrada."""
    origem = dados.get("origem") or {}
    destino = dados.get("destino") or {}
    st_d = str(destino.get("status") or "").strip().lower()
    st_o = str(origem.get("status") or "").strip().lower()
    ativa = bool(dados.get("ativa"))
    duracao = int(destino.get("duracao_segundos") or destino.get("duracao_falada_segundos") or 0)
    if ativa:
        fase = "conversando" if st_d in _ATENDIDA else "chamando-destino" if st_o in _ATENDIDA else "chamando-origem"
    else:
        fase = "encerrada"
    if st_d in _ATENDIDA or duracao > 0:
        status = "CONNECTED"
    elif st_d in _OCUPADO:
        status = "BUSY"
    elif ativa:
        status = "DIALING"
    else:
        status = "NOT_PERFORMED"
    preco = float(dados.get("preco") or origem.get("preco") or 0) + float(destino.get("preco") or 0)
    return {"fase": fase, "status": status, "duracao": duracao, "preco": round(preco, 4),
            "gravacao": dados.get("url_gravacao") or "",
            "motivo": destino.get("motivo_desligamento") or origem.get("motivo_desligamento") or "",
            "statusOrigem": st_o, "statusDestino": st_d}
