"""Vínculos empregatícios de um CNPJ (base RAIS, via gateway FDX APIs).

A RAIS (Relação Anual de Informações Sociais) é a declaração que toda empresa
entrega ao Ministério do Trabalho com o quadro de empregados do ano. Este
módulo consulta o gateway e devolve, para um CNPJ, QUEM TRABALHA (ou trabalhou)
lá: nome, CPF, data de admissão e data de desligamento.

Config por variáveis de ambiente:
- FDX_TOKEN      token do gateway (obrigatório — sem ele `enabled()` é False)
- FDX_BASE_URL   default https://api.fdxapis.us/api.php

Formato da resposta do gateway:
    {"status": true,  "response": [ {CPF, NOME, CNPJ, RAZAO_SOCIAL, SITUACAO,
                                     DATA_ENTREGA, DATA_ADMISSAO,
                                     DATA_DESLIGAMENTO, DATA_CADASTRO,
                                     FAIXA_RENDA}, ... ]}
    {"status": false, "response": "Not exist"}       # CNPJ sem RAIS na base
    {"status": false, "response": "Token inválido"}

Duas armadilhas do gateway, tratadas aqui:

1. CADA VÍNCULO VEM DUPLICADO — uma cópia com datas em ISO
   ("2020-01-01 00:00:00") e outra com datas em BR ("01/01/2020"). Sem dedup, a
   contagem de funcionários sai pelo dobro (4.778 registros = 2.388 pessoas no
   CNPJ da Globo, por exemplo).
2. O DESLIGAMENTO SÓ VEM NA CÓPIA BR, E SEM O ANO — a cópia ISO traz None e a
   cópia BR traz "09/03" (dia/mês; o ano se perde na conversão do gateway).
   Descartar isso marcaria como "ainda trabalha lá" gente que já saiu (328 de
   2.389 pessoas no CNPJ da Globo), então guardamos o dia/mês em
   `desligamento_parcial` e deixamos explícito que o ano não foi informado.

A base é um retrato do último ano entregue (o campo DATA_ENTREGA diz quando),
não um espelho da folha de hoje: quem entrou depois da entrega não aparece, e
"sem data de desligamento" significa "estava lá na data da entrega".
"""

import os
import re
import time
from typing import Any

import httpx

BASE_URL = os.environ.get("FDX_BASE_URL", "https://api.fdxapis.us/api.php").strip()
TOKEN = (os.environ.get("FDX_TOKEN") or "").strip()

_TIMEOUT = httpx.Timeout(90.0)   # 1,5 MB de resposta em ~2s; folga pra empresa grande
_CACHE_TTL = 6 * 3600            # a RAIS é anual — cache longo não perde nada
_cache: dict[str, tuple[float, dict]] = {}


def enabled() -> bool:
    return bool(TOKEN and BASE_URL)


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _parse_data(valor: Any) -> str | None:
    """Normaliza data pra 'AAAA-MM-DD'. Aceita ISO e BR; o resto vira None."""
    s = str(valor or "").strip()
    if not s or s.lower() in ("none", "null", "0000-00-00"):
        return None
    m = re.match(r"^(\d{4})-(\d{2})-(\d{2})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{m.group(3)}"
    m = re.match(r"^(\d{2})/(\d{2})/(\d{4})$", s)
    if m:
        return f"{m.group(3)}-{m.group(2)}-{m.group(1)}"
    return None  # ex.: "04/06" — dia/mês sem ano, inútil e enganoso


def _parse_dia_mes(valor: Any) -> str | None:
    """Reconhece 'DD/MM' (desligamento sem ano, do jeito que o gateway manda)."""
    s = str(valor or "").strip()
    m = re.match(r"^(\d{2})/(\d{2})$", s)
    if not m:
        return None
    dia, mes = int(m.group(1)), int(m.group(2))
    return s if 1 <= dia <= 31 and 1 <= mes <= 12 else None


def _br(iso: str | None) -> str:
    if not iso:
        return ""
    a, m, d = iso.split("-")
    return f"{d}/{m}/{a}"


def _meses_entre(inicio: str, fim: str | None) -> int | None:
    """Meses cheios entre duas datas ISO (fim=None → hoje)."""
    if not inicio:
        return None
    try:
        ai, mi, di = (int(x) for x in inicio.split("-"))
        if fim:
            af, mf, df = (int(x) for x in fim.split("-"))
        else:
            t = time.localtime()
            af, mf, df = t.tm_year, t.tm_mon, t.tm_mday
    except Exception:
        return None
    meses = (af - ai) * 12 + (mf - mi) - (1 if df < di else 0)
    return max(0, meses)


def _tempo_casa(meses: int | None) -> str:
    if meses is None:
        return ""
    anos, resto = divmod(meses, 12)
    if anos and resto:
        return f"{anos} ano{'s' if anos > 1 else ''} e {resto} m{'eses' if resto > 1 else 'ês'}"
    if anos:
        return f"{anos} ano{'s' if anos > 1 else ''}"
    return f"{resto} m{'eses' if resto != 1 else 'ês'}"


def _normalizar(registros: list[dict], referencia: str | None) -> list[dict]:
    """Deduplica as cópias ISO/BR e devolve um vínculo por (CPF, admissão)."""
    por_chave: dict[tuple[str, str], dict] = {}

    for reg in registros:
        if not isinstance(reg, dict):
            continue
        cpf = only_digits(reg.get("CPF"))
        admissao = _parse_data(reg.get("DATA_ADMISSAO"))
        if not cpf or not admissao:
            continue
        chave = (cpf, admissao)
        bruto_desl = reg.get("DATA_DESLIGAMENTO")
        desligamento = _parse_data(bruto_desl)
        parcial = None if desligamento else _parse_dia_mes(bruto_desl)

        atual = por_chave.get(chave)
        if atual is None:
            por_chave[chave] = {
                "cpf": cpf,
                "nome": (reg.get("NOME") or "").strip(),
                "admissao": admissao,
                "desligamento": desligamento,
                "desligamento_parcial": parcial,
                "faixa_renda": reg.get("FAIXA_RENDA") or "",
                "situacao": (reg.get("SITUACAO") or "").strip(),
            }
            continue
        # A cópia gêmea só acrescenta o que faltava na primeira.
        if desligamento and not atual["desligamento"]:
            atual["desligamento"] = desligamento
        if parcial and not atual["desligamento_parcial"]:
            atual["desligamento_parcial"] = parcial
        if not atual["nome"]:
            atual["nome"] = (reg.get("NOME") or "").strip()
        if not atual["faixa_renda"]:
            atual["faixa_renda"] = reg.get("FAIXA_RENDA") or ""

    vinculos = []
    for v in por_chave.values():
        # "Ativo" = nenhum sinal de desligamento até a data de entrega da RAIS.
        # O tempo de casa de quem continua é medido até a referência, não até
        # hoje, senão inventaríamos anos de vínculo que a base não afirma.
        v["ativo"] = not (v["desligamento"] or v["desligamento_parcial"])
        if v["desligamento_parcial"]:
            # Sem o ano da saída não dá pra medir tempo de casa sem chutar.
            v["meses"] = None
            v["tempo_casa"] = ""
        else:
            meses = _meses_entre(v["admissao"], v["desligamento"] or referencia)
            v["meses"] = meses
            v["tempo_casa"] = _tempo_casa(meses)
        v["admissao_br"] = _br(v["admissao"])
        v["desligamento_br"] = _br(v["desligamento"]) or (
            f"{v['desligamento_parcial']} (ano não informado)" if v["desligamento_parcial"] else "")
        vinculos.append(v)

    # Quem está lá primeiro; dentro de cada grupo, a admissão mais recente no topo.
    vinculos.sort(key=lambda v: (not v["ativo"], _data_desc(v["admissao"]), v["nome"]))
    return vinculos


def _data_desc(iso: str) -> tuple:
    """Chave de ordenação decrescente por data ISO."""
    try:
        return tuple(-int(x) for x in iso.split("-"))
    except Exception:
        return (0, 0, 0)


def _por_ano(vinculos: list[dict]) -> list[dict]:
    """Admissões e desligamentos por ano — sinal de crescimento/encolhimento."""
    anos: dict[str, dict] = {}
    for v in vinculos:
        a = v["admissao"][:4]
        anos.setdefault(a, {"ano": a, "admissoes": 0, "desligamentos": 0})["admissoes"] += 1
        if v["desligamento"]:
            d = v["desligamento"][:4]
            anos.setdefault(d, {"ano": d, "admissoes": 0, "desligamentos": 0})["desligamentos"] += 1
    return sorted(anos.values(), key=lambda x: x["ano"])


async def vinculos_cnpj(cnpj: str, refresh: bool = False) -> dict[str, Any]:
    """Vínculos empregatícios declarados na RAIS para um CNPJ.

    Retorna {status, cnpj, razao_social, referencia, total, ativos,
             desligados, registros_brutos, por_ano, vinculos:[...]}.
    status: ok | not_found | unavailable | error
    """
    doc = only_digits(cnpj)
    if len(doc) != 14:
        return {"status": "error", "message": "CNPJ inválido — precisa ter 14 dígitos.",
                "cnpj": cnpj, "vinculos": []}
    if not enabled():
        return {"status": "unavailable",
                "message": "Vínculos não configurados (defina FDX_TOKEN no .env).",
                "cnpj": doc, "vinculos": []}

    if not refresh:
        em_cache = _cache.get(doc)
        if em_cache and (time.time() - em_cache[0]) < _CACHE_TTL:
            resultado = dict(em_cache[1])
            resultado["_from_cache"] = True
            return resultado

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(BASE_URL, params={"token": TOKEN, "raispj": doc})
    except httpx.HTTPError as exc:
        # str(exc) do httpx inclui a URL chamada — e a URL leva o token. Nunca
        # devolver isso pra tela: só o tipo do erro.
        return {"status": "error",
                "message": f"Não consegui falar com a base RAIS ({type(exc).__name__}).",
                "cnpj": doc, "vinculos": []}

    if resp.status_code in (401, 403):
        # O gateway responde 401 tanto pra token errado quanto pra token vencido.
        motivo = ""
        try:
            motivo = str((resp.json() or {}).get("response") or "")
        except Exception:
            pass
        return {"status": "unavailable",
                "message": ("Acesso à base RAIS recusado"
                            + (f" ({motivo})" if motivo else "")
                            + ". Renove o FDX_TOKEN no .env do serviço de dados."),
                "cnpj": doc, "vinculos": []}
    if resp.status_code >= 400:
        return {"status": "error",
                "message": f"A base RAIS respondeu {resp.status_code}.",
                "cnpj": doc, "vinculos": []}

    try:
        payload = resp.json()
    except ValueError:
        return {"status": "error", "message": "A base RAIS respondeu em formato inesperado.",
                "cnpj": doc, "vinculos": []}

    corpo = payload.get("response") if isinstance(payload, dict) else None

    if not (isinstance(payload, dict) and payload.get("status")) or not isinstance(corpo, list):
        motivo = str(corpo or "").strip()
        if motivo.lower().startswith("not exist"):
            return {"status": "not_found",
                    "message": "Nenhum vínculo declarado na RAIS para este CNPJ.",
                    "cnpj": doc, "vinculos": [], "total": 0, "ativos": 0, "desligados": 0}
        if "token" in motivo.lower():
            return {"status": "unavailable",
                    "message": "Token da base RAIS recusado (verifique FDX_TOKEN).",
                    "cnpj": doc, "vinculos": []}
        return {"status": "error", "message": motivo or "A base RAIS não retornou dados.",
                "cnpj": doc, "vinculos": []}

    razao = ""
    referencia = None
    for reg in corpo:
        if isinstance(reg, dict):
            razao = razao or (reg.get("RAZAO_SOCIAL") or "").strip()
            entrega = _parse_data(reg.get("DATA_ENTREGA"))
            if entrega and (referencia is None or entrega > referencia):
                referencia = entrega

    vinculos = _normalizar(corpo, referencia)
    ativos = sum(1 for v in vinculos if v["ativo"])
    por_ano = _por_ano(vinculos)

    # A RAIS é entregue no ano SEGUINTE ao que declara (entrega em abr/2022 =
    # ano-base 2021), então "contratações do ano" é o ano-base, não o da entrega
    # — no ano da entrega o número é sempre 0 e não diria nada.
    ano_base = ""
    if referencia:
        ano_base = str(int(referencia[:4]) - 1)
    linha_base = next((a for a in por_ano if a["ano"] == ano_base), None)

    resultado = {
        "status": "ok" if vinculos else "not_found",
        "cnpj": doc,
        "razao_social": razao,
        "referencia": referencia or "",
        "referencia_br": _br(referencia),
        "total": len(vinculos),
        "ativos": ativos,
        "desligados": len(vinculos) - ativos,
        "registros_brutos": len(corpo),
        "ano_base": ano_base,
        "admissoes_ano_base": linha_base["admissoes"] if linha_base else 0,
        "por_ano": por_ano,
        "vinculos": vinculos,
    }
    if not vinculos:
        resultado["message"] = "A base respondeu, mas sem nenhum vínculo aproveitável."
    _cache[doc] = (time.time(), resultado)
    return resultado
