"""Cliente da API Mk Buscas (consulta por CPF).

Usado para:
1. DESAMBIGUAR o CPF de um funcionario: para cada CPF candidato (vindo da base
   JBR por nome), consulta na Mk e verifica se `empregos`/`empresas` batem com a
   empresa-alvo (ex.: Petrobras).
2. Trazer telefones (a Mk ja retorna telefones na consulta por CPF).

Config por variaveis de ambiente (a Mk e um gateway; ajuste conforme seu acesso):
- MK_BASE_URL     ex.: https://SEU-GATEWAY/api           (obrigatorio para ativar)
- MK_CPF_PATH     ex.: /consulta/cpf/{cpf}  ou  /modulo/xyz?cpf={cpf}   (default abaixo)
- MK_AUTH_HEADER  ex.: Authorization   (nome do header de auth; default Authorization)
- MK_AUTH_VALUE   ex.: Bearer XXX  ou  a apiKey                          (valor do header)
- MK_METHOD       GET (default) | POST

Sem MK_BASE_URL, `enabled()` retorna False e o sistema ignora a Mk.
"""

import os
import re
import unicodedata
from typing import Any

import httpx

# Defaults ja apontam para a WorkAPI (gateway por tras da Mk Buscas).
BASE_URL = os.environ.get("MK_BASE_URL", "https://api.workapi.dev/v1/gateway").strip().rstrip("/")
CPF_PATH = os.environ.get("MK_CPF_PATH", "/work-cpf?cpf={cpf}").strip()
AUTH_HEADER = os.environ.get("MK_AUTH_HEADER", "x-api-key").strip()
# Aceita MK_AUTH_VALUE ou WORKAPI_KEY (mesma chave que seus scripts ja usam).
AUTH_VALUE = (os.environ.get("MK_AUTH_VALUE") or os.environ.get("WORKAPI_KEY") or "").strip()
METHOD = os.environ.get("MK_METHOD", "GET").strip().upper()

# Módulo de TELEFONE REVERSO (intelgrax-tel): phone -> CPFs/CNPJs atrelados.
# Tem chave PRÓPRIA (MK_TEL_KEY) porque o acesso é por módulo: a chave do CPF
# (intelgrax-cpfv2) não abre o tel, e vice-versa. Cai na WORKAPI_KEY se não houver.
TEL_PATH = os.environ.get("MK_TEL_PATH", "/intelgrax-tel").strip()
TEL_AUTH_VALUE = (os.environ.get("MK_TEL_KEY") or AUTH_VALUE or "").strip()

_TIMEOUT = httpx.Timeout(20.0)
_cache: dict[str, dict[str, Any]] = {}
_tel_cache: dict[str, dict[str, Any]] = {}


def enabled() -> bool:
    # Ativa quando a chave (WORKAPI_KEY / MK_AUTH_VALUE) esta presente.
    return bool(AUTH_VALUE and BASE_URL)


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


async def consulta_cpf(cpf: str) -> dict[str, Any]:
    """Consulta bruta por CPF. Retorna {status, data|message}."""
    if not enabled():
        return {"status": "unavailable", "message": "Mk nao configurada (defina MK_BASE_URL)."}
    doc = only_digits(cpf).zfill(11)[:11]
    if doc in _cache:
        return _cache[doc]

    url = BASE_URL + CPF_PATH.replace("{cpf}", doc)
    headers = {"Accept": "application/json"}
    if AUTH_VALUE:
        headers[AUTH_HEADER] = AUTH_VALUE

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            if METHOD == "POST":
                resp = await client.post(url, headers=headers, json={"cpf": doc})
            else:
                resp = await client.get(url, headers=headers)
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexao Mk: {str(exc)[:120]}"}

    if resp.status_code >= 400:
        return {"status": "error", "message": f"Mk {resp.status_code}: {resp.text[:150]}"}
    try:
        data = resp.json()
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Mk."}

    result = {"status": "ok", "data": _unwrap(data)}
    _cache[doc] = result
    return result


_PERSON_KEYS = (
    "phones", "addresses", "telefones", "enderecos", "DadosBasicos",
    "empregos", "empresas", "cpf", "name", "nome",
)


def _unwrap(payload: Any) -> dict[str, Any]:
    """Extrai o objeto da PESSOA, cobrindo os 2 formatos de modulo:

    - work-cpf (ingles):  {data:{body:{data:[ <pessoa> ]}}}
    - modulo rico (pt):   {..., DadosBasicos, telefones, enderecos, empresas,...}
      (com ou sem envelope {data:{body:{...}}})
    """
    if not isinstance(payload, dict):
        return {}
    obj = payload
    for _ in range(4):
        if any(k in obj for k in _PERSON_KEYS) and not isinstance(obj.get("data"), list):
            return obj
        if isinstance(obj.get("data"), list):        # work-cpf: lista de pessoas
            return obj["data"][0] if obj["data"] else {}
        if isinstance(obj.get("body"), dict):
            obj = obj["body"]; continue
        if isinstance(obj.get("data"), dict):
            obj = obj["data"]; continue
        break
    return obj if isinstance(obj, dict) else {}


def _extract_companies(mk_data: dict[str, Any]) -> list[str]:
    """Empresas ligadas a pessoa. work-cpf nao tem; modulo rico usa empregos/empresas."""
    names: list[str] = []
    for key in ("empregos", "empresas", "companies", "jobs"):
        for item in mk_data.get(key) or []:
            if isinstance(item, dict):
                nome = (
                    item.get("razaoSocial") or item.get("nomeEmpresa")
                    or item.get("nome") or item.get("name")
                    or item.get("razao_social") or ""
                )
                if nome:
                    names.append(_norm(nome))
            elif isinstance(item, str):
                names.append(_norm(item))
    return names


def _extract_phones(mk_data: dict[str, Any]) -> list[dict[str, Any]]:
    """Dual-schema: work-cpf (phones[areaCode/number]) ou rico (telefones[telefone])."""
    out = []
    # Formato rico (pt): telefones[].telefone / tipo / operadora / whatsapp
    for t in mk_data.get("telefones") or []:
        if isinstance(t, dict) and (t.get("telefone") or t.get("numero")):
            num = str(t.get("telefone") or t.get("numero") or "")
            out.append({
                "telefone": num,
                "ddd": str(t.get("ddd") or ""),
                "number": num,
                "tipo": t.get("tipo") or "",
                "operadora": t.get("operadora") or "",
                "whatsapp": t.get("whatsapp"),
            })
    # Formato work-cpf (en): phones[].areaCode / number / typeId
    for t in mk_data.get("phones") or []:
        if not isinstance(t, dict):
            continue
        ddd = str(t.get("areaCode") or "").strip()
        num = str(t.get("number") or "").strip()
        if not num:
            continue
        out.append({
            "telefone": f"({ddd}) {num}",
            "ddd": ddd,
            "number": num,
            "type_id": t.get("typeId"),
            "mobile": num.startswith("9") and len(num) == 9,
        })
    return out


def classify_phone(p: dict[str, Any]) -> dict[str, Any]:
    """Classifica um telefone da Mk para priorizar/filtrar antes do DonoDoZap.

    Sem data na Mk, usamos o formato do número (o sinal mais forte de "antigo"):
    - celular atual: 11 dígitos (DDD + 9XXXXXXXX)  -> único que está no WhatsApp
    - 10 dígitos:    fixo (2-5) ou celular pré-2016 (7-9) -> tratados como ANTIGOS
    - 'NO'/status inválido ou tamanho fora de 10-11 -> LIXO (descartar)

    Retorna o dict original acrescido de: digits, categoria ('celular'|'fixo'|
    'celular_antigo'|'invalido'), antigo (bool), rank (menor = melhor).
    """
    ddd = re.sub(r"\D", "", str(p.get("ddd") or ""))
    number = re.sub(r"\D", "", str(p.get("number") or p.get("telefone") or ""))
    digits = number if (ddd and number.startswith(ddd)) else (ddd + number)
    digits = re.sub(r"\D", "", digits)

    status = str(p.get("status") or "").strip().upper()
    tipo = str(p.get("tipo") or "").strip().upper()

    cat, antigo, rank = "invalido", True, 99
    lixo = status in ("NO", "") and tipo == "NO"
    repetido = bool(digits) and len(set(digits)) <= 2  # ex.: 1334960000 quase-repetido
    if lixo or len(digits) not in (10, 11) or repetido:
        cat, antigo, rank = "invalido", True, 99
    elif len(digits) == 11 and digits[2] == "9":
        cat, antigo, rank = "celular", False, 0           # celular atual — melhor
    elif len(digits) == 10 and digits[2] in "6789":
        cat, antigo, rank = "celular_antigo", True, 3      # celular pré-nono-dígito
    else:
        cat, antigo, rank = "fixo", True, 2                # fixo/comercial

    return {**p, "digits": digits, "categoria": cat, "antigo": antigo, "rank": rank}


def refine_phones(phones: list[dict[str, Any]], modo: str = "celular",
                  max_n: int = 3) -> list[dict[str, Any]]:
    """Filtra/prioriza os telefones da Mk antes de validar no DonoDoZap.

    modo:
      'celular'       -> só celulares atuais (11 díg.) — padrão, corta antigos e fixos
      'celular_fixo'  -> celulares + fixos válidos (celulares primeiro)
      'todos'         -> tudo, menos lixo (inválidos), celulares primeiro
    max_n: máximo de telefones por pessoa (0 = sem limite).
    """
    classified = [classify_phone(p) for p in (phones or [])]
    classified = [c for c in classified if c["categoria"] != "invalido"]

    if modo == "celular":
        classified = [c for c in classified if c["categoria"] == "celular"]
    elif modo == "celular_fixo":
        classified = [c for c in classified if c["categoria"] in ("celular", "fixo")]
    # 'todos' mantém celular/fixo/celular_antigo

    # Ordenação "maior chance de estar correto primeiro":
    #  1) categoria (celular atual < fixo < celular antigo) — nosso rank de formato
    #  2) WhatsApp presente (sinal forte de número ativo)
    #  3) priority do provedor (Assertiva: 1 = melhor)
    #  4) classification do provedor (1 = melhor)
    def _sort_key(c):
        wa = 0 if c.get("whatsapp") else 1
        try:
            prio = int(c.get("priority")) if c.get("priority") is not None else 98
        except (TypeError, ValueError):
            prio = 98
        try:
            clf = int(c.get("classification")) if c.get("classification") is not None else 98
        except (TypeError, ValueError):
            clf = 98
        return (c["rank"], wa, prio, clf)

    # dedupe por dígitos, mantendo o de melhor ordenação
    seen, dedup = set(), []
    for c in sorted(classified, key=_sort_key):
        if c["digits"] in seen:
            continue
        seen.add(c["digits"])
        dedup.append(c)

    return dedup[:max_n] if max_n and max_n > 0 else dedup


def _extract_cities(mk_data: dict[str, Any]) -> list[dict[str, str]]:
    """Dual-schema: work-cpf (addresses[city/state]) ou rico (enderecos[cidade/uf])."""
    out = []
    for e in mk_data.get("enderecos") or []:      # rico (pt)
        if isinstance(e, dict) and e.get("cidade"):
            out.append({
                "cidade": _norm(e.get("cidade")),
                "uf": _norm(e.get("uf") or ""),
                "bairro": _norm(e.get("bairro") or ""),
            })
    for e in mk_data.get("addresses") or []:      # work-cpf (en)
        if isinstance(e, dict) and e.get("city"):
            out.append({
                "cidade": _norm(e.get("city")),
                "uf": _norm(e.get("state") or ""),
                "bairro": _norm(e.get("district") or ""),
            })
    return out


def city_matches(mk_data: dict[str, Any], target_city: str, target_uf: str = "") -> bool:
    """True se a cidade-alvo (do LinkedIn) aparece nos enderecos da pessoa."""
    tc = _norm(target_city)
    tu = _norm(target_uf)
    if not tc:
        return False
    for e in _extract_cities(mk_data):
        if e["cidade"] == tc and (not tu or not e["uf"] or e["uf"] == tu):
            return True
    return False


async def disambiguate_by_city(
    candidates: list[dict[str, Any]], target_city: str, target_uf: str = ""
) -> dict[str, Any]:
    """Dado candidatos {cpf,nome,...} e a cidade-alvo (LinkedIn), acha o CPF certo.

    Retorna {status: resolved|ambiguous|not_found, cpf?, pessoa?, checked[]}.
    """
    checked = []
    matches = []
    for c in candidates:
        r = await consulta_cpf(c["cpf"])
        if r.get("status") != "ok":
            checked.append({"cpf": c["cpf"], "mk": r.get("status"), "match": None})
            continue
        m = city_matches(r["data"], target_city, target_uf)
        checked.append({
            "cpf": c["cpf"],
            "cidades": [f"{e['cidade']}/{e['uf']}" for e in _extract_cities(r["data"])],
            "match": m,
        })
        if m:
            matches.append({**c, "phones_mk": _extract_phones(r["data"])})

    if len(matches) == 1:
        return {"status": "resolved", "cpf": matches[0]["cpf"], "pessoa": matches[0], "checked": checked}
    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": matches, "checked": checked}
    return {"status": "not_found", "checked": checked}


def _extract_roles(mk_data: dict[str, Any]) -> list[str]:
    """Cargos/ocupacao da pessoa (CBO + cargos em empregos), normalizados."""
    roles = []
    prof = mk_data.get("profissao")
    if isinstance(prof, dict):
        d = prof.get("cboDescricao") or ""
        if d and "sem descri" not in d.lower():
            roles.append(_norm(d))
    for item in mk_data.get("empregos") or []:
        if isinstance(item, dict):
            cargo = item.get("cargo") or item.get("funcao") or ""
            if cargo:
                roles.append(_norm(cargo))
    return roles


def _tokens(s: str, minlen: int = 4) -> set:
    return {t for t in _norm(s).split() if len(t) >= minlen}


def _loose_match(a: str, b: str) -> bool:
    """Match frouxo por sobreposicao de tokens (>=4 letras)."""
    ta, tb = _tokens(a), _tokens(b)
    return bool(ta and tb and (ta & tb))


async def disambiguate_multi(
    candidates: list[dict[str, Any]],
    company: str = "",
    role: str = "",
    city: str = "",
    uf: str = "",
    min_score: int = 2,
) -> dict[str, Any]:
    """Desambiguacao estilo Datastone: soma sinais empresa + cargo + localizacao.

    Pesos: empresa=3, cidade=2, cargo=1 (CBO/cargo e o sinal mais fraco).
    Resolve se houver um UNICO maior score >= min_score.
    Retorna {status, cpf?, pessoa?, checked[]}.
    """
    checked = []
    for c in candidates:
        r = await consulta_cpf(c["cpf"])
        if r.get("status") != "ok":
            checked.append({"cpf": c["cpf"], "mk": r.get("status"), "score": -1})
            continue
        data = r["data"]
        score = 0
        hits = []
        if company and company_matches(data, company):
            score += 3; hits.append("empresa")
        if city and city_matches(data, city, uf):
            score += 2; hits.append("cidade")
        if role and any(_loose_match(role, rr) for rr in _extract_roles(data)):
            score += 1; hits.append("cargo")
        checked.append({
            "cpf": c["cpf"],
            "score": score,
            "hits": hits,
            "cidades": [f"{e['cidade']}/{e['uf']}" for e in _extract_cities(data)],
            "empresas": _extract_companies(data),
            "cargos": _extract_roles(data),
            "phones_mk": _extract_phones(data),
        })

    ranked = sorted([c for c in checked if c["score"] >= 0], key=lambda x: x["score"], reverse=True)
    if not ranked or ranked[0]["score"] < min_score:
        return {"status": "not_found", "checked": checked}
    top = ranked[0]["score"]
    winners = [c for c in ranked if c["score"] == top]
    if len(winners) == 1:
        w = winners[0]
        return {"status": "resolved", "cpf": w["cpf"], "pessoa": w, "checked": checked}
    return {"status": "ambiguous", "candidates": winners, "checked": checked}


def company_matches(mk_data: dict[str, Any], target_company: str) -> bool:
    """True se a empresa-alvo aparece nos vinculos da pessoa (match por token)."""
    target = set(t for t in _norm(target_company).split() if len(t) >= 4)
    if not target:
        return False
    for name in _extract_companies(mk_data):
        toks = set(t for t in name.split() if len(t) >= 4)
        if target & toks:
            return True
    return False


async def disambiguate_by_company(
    candidates: list[dict[str, Any]], target_company: str
) -> dict[str, Any]:
    """Dado candidatos {cpf,nome,...} e a empresa-alvo, acha o CPF certo via Mk.

    Retorna {status: resolved|ambiguous|not_found, cpf?, pessoa?, checked[]}.
    """
    checked = []
    matches = []
    for c in candidates:
        r = await consulta_cpf(c["cpf"])
        if r.get("status") != "ok":
            checked.append({"cpf": c["cpf"], "mk": r.get("status"), "match": None})
            continue
        m = company_matches(r["data"], target_company)
        checked.append({
            "cpf": c["cpf"],
            "empresas": _extract_companies(r["data"]),
            "match": m,
        })
        if m:
            matches.append({**c, "phones_mk": _extract_phones(r["data"])})

    if len(matches) == 1:
        return {"status": "resolved", "cpf": matches[0]["cpf"], "pessoa": matches[0], "checked": checked}
    if len(matches) > 1:
        return {"status": "ambiguous", "candidates": matches, "checked": checked}
    return {"status": "not_found", "checked": checked}


# --------------------------------------------------------------------------
# Telefone reverso (intelgrax-tel): phone -> CPFs/CNPJs atrelados
# --------------------------------------------------------------------------

def cpf_matches_mask(doc: str, value: str) -> bool:
    """Confere se um CPF/CNPJ bate com o valor retornado pela API.

    A API pode devolver o documento MASCARADO ('689*****121') ou COMPLETO
    ('10495902870', às vezes com zeros à esquerda ou truncado). Cobre os dois.
    """
    d = only_digits(doc)
    if not d or not value:
        return False
    v = (value or "").strip()
    m = re.match(r"^(\d+)\D+(\d+)$", v)   # mascarado: prefixo + sufixo
    if m:
        pre, suf = m.group(1), m.group(2)
        return d.startswith(pre) and d.endswith(suf)
    # completo: compara por dígitos, tolerando zeros à esquerda / truncamento
    vd = only_digits(v)
    if not vd:
        return False
    dz, vz = d.lstrip("0"), vd.lstrip("0")
    return d == vd or dz == vz or d.endswith(vd) or vd.endswith(d)


async def consulta_telefone(phone: str) -> dict[str, Any]:
    """Telefone reverso via WorkAPI intelgrax-tel. Retorna {status, total, registros}.

    status: ok | no_access (módulo não habilitado) | unavailable | error.
    """
    if not (TEL_AUTH_VALUE and BASE_URL):
        return {"status": "unavailable", "message": "Telefone reverso não configurado (MK_TEL_KEY)."}
    digits = only_digits(phone)
    if len(digits) < 10:
        return {"status": "error", "message": "Telefone inválido."}
    if digits in _tel_cache:
        return _tel_cache[digits]

    url = BASE_URL + TEL_PATH
    headers = {"Accept": "application/json", AUTH_HEADER: TEL_AUTH_VALUE}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(url, params={"phone": digits}, headers=headers)
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexão: {str(exc)[:120]}"}

    if resp.status_code == 403:
        return {"status": "no_access",
                "message": ("Chave WorkAPI sem acesso ao módulo 'intelgrax-tel'. "
                            "Peça à Mk para habilitar (igual ao intelgrax-cpfv2).")}
    if resp.status_code >= 400:
        return {"status": "error", "message": f"WorkAPI {resp.status_code}: {resp.text[:150]}"}
    try:
        j = resp.json()
    except Exception:
        return {"status": "error", "message": "Resposta inválida da WorkAPI."}

    # O gateway pode responder HTTP 200 mas com ERRO no módulo interno
    # (ex.: {"data":{"body":{"status":403,"reason":"Token vencido/... sem acesso ..."}}}).
    # Sem checar isso, um 403 interno era lido como "0 vínculos" (falso negativo).
    data = j.get("data") or {}
    body = data.get("body") or j.get("body") or j
    inner_status = None
    if isinstance(body, dict):
        inner_status = body.get("status")
    if inner_status is None:
        inner_status = data.get("status")
    try:
        inner_status = int(inner_status) if inner_status is not None else None
    except (TypeError, ValueError):
        inner_status = None
    if inner_status is not None and inner_status >= 400:
        reason = ""
        if isinstance(body, dict):
            reason = body.get("reason") or body.get("statusMsg") or ""
        if inner_status in (401, 403):
            return {"status": "no_access",
                    "message": f"integralX (intelgrax-tel) rejeitou a chave: {reason or 'sem acesso/token inválido'}. "
                               "Verifique MK_TEL_KEY (vencida/sem acesso ao módulo)."}
        return {"status": "error", "message": f"integralX {inner_status}: {reason or 'erro no módulo'}"}

    registros = body.get("msg") or [] if isinstance(body, dict) else []
    result = {
        "status": "ok",
        "phone": digits,
        "total": body.get("total", len(registros)),
        "registros": [{
            "cpf_cnpj": r.get("cpf_cnpj", ""),
            "nome": r.get("nome", ""),
            "endereco": r.get("endereco") or {},
        } for r in registros],
        "remaining_daily": j.get("remainingDaily"),
    }
    _tel_cache[digits] = result
    return result


async def telefone_pertence(phone: str, doc: str) -> dict[str, Any]:
    """Verifica se um CPF/CNPJ está atrelado a um telefone (validação de contato).

    Retorna {status, atrelado, total, nome, alerta_compartilhado}.
    """
    r = await consulta_telefone(phone)
    if r.get("status") != "ok":
        return {"status": r.get("status"), "message": r.get("message"), "atrelado": None}
    match = next((x for x in r["registros"] if cpf_matches_mask(doc, x.get("cpf_cnpj", ""))), None)
    total = r.get("total") or 0
    return {
        "status": "ok",
        "phone": r["phone"],
        "atrelado": match is not None,
        "nome": (match or {}).get("nome", ""),
        "total": total,
        # nº muito alto de entes no mesmo telefone => número compartilhado/lixo
        "alerta_compartilhado": total >= 50,
    }
