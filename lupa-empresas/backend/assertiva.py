"""Cliente da API Assertiva Localize (V3).

Fornece o modo "Busca Assertiva": consultas por CPF, Nome/Endereço, Telefone,
E-mail e CNPJ, usando a base de dados cadastral da Assertiva Soluções.

Fluxo OAuth2 (client_credentials):
  POST {BASE}/oauth2/v3/token  (Basic base64(client_id:client_secret), grant_type=client_credentials)
  -> {access_token, token_type: bearer, expires_in, scope}
As demais chamadas usam Authorization: Bearer <access_token>.

Config por variáveis de ambiente (todas ficam no .env, nunca no código):
- ASSERTIVA_CLIENT_ID       client_id da aplicação
- ASSERTIVA_CLIENT_SECRET   client_secret da aplicação
- ASSERTIVA_BASIC           (alternativa) base64 pronto de "id:secret"
- ASSERTIVA_BASE_URL        default https://api.assertivasolucoes.com.br
- ASSERTIVA_TOKEN_PATH      default /oauth2/v3/token
- ASSERTIVA_FINALIDADE      idFinalidade padrão (LGPD). Default 5 (legítimo interesse).

Sem client_id/secret (ou ASSERTIVA_BASIC), `enabled()` retorna False.
"""

import base64
import os
import re
import time
from typing import Any

import httpx

import custos

BASE_URL = os.environ.get(
    "ASSERTIVA_BASE_URL", "https://api.assertivasolucoes.com.br"
).strip().rstrip("/")
TOKEN_PATH = os.environ.get("ASSERTIVA_TOKEN_PATH", "/oauth2/v3/token").strip()
CLIENT_ID = os.environ.get("ASSERTIVA_CLIENT_ID", "").strip()
CLIENT_SECRET = os.environ.get("ASSERTIVA_CLIENT_SECRET", "").strip()
_BASIC_ENV = os.environ.get("ASSERTIVA_BASIC", "").strip()
DEFAULT_FINALIDADE = int(os.environ.get("ASSERTIVA_FINALIDADE", "5") or "5")

_TIMEOUT = httpx.Timeout(35.0)

# Cache do token em memória: (access_token, expira_em_epoch).
_token: str = ""
_token_exp: float = 0.0
# Cache simples de consultas (evita gastar cota em repetição na mesma sessão).
_cache: dict[str, dict[str, Any]] = {}
# Relatório de uso: paginado e lento (30 dias = ~75 páginas, mais de 2 min).
# Não é billable, mas precisa de cache próprio, com validade, pra não travar o
# painel administrativo a cada abertura.
_cache_relatorio: dict[str, tuple[float, dict]] = {}
_TTL_RELATORIO = 15 * 60


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _basic_header() -> str:
    if _BASIC_ENV:
        return _BASIC_ENV
    raw = f"{CLIENT_ID}:{CLIENT_SECRET}".encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def enabled() -> bool:
    return bool((_BASIC_ENV or (CLIENT_ID and CLIENT_SECRET)) and BASE_URL)


async def _get_token(force: bool = False) -> str:
    """Retorna um access_token válido, renovando quando necessário."""
    global _token, _token_exp
    now = time.time()
    if not force and _token and now < _token_exp - 10:
        return _token
    url = BASE_URL + TOKEN_PATH
    headers = {
        "Authorization": "Basic " + _basic_header(),
        "Content-Type": "application/x-www-form-urlencoded",
        "Accept": "application/json",
    }
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        resp = await client.post(url, headers=headers,
                                 data={"grant_type": "client_credentials"})
    if resp.status_code >= 400:
        raise RuntimeError(f"token {resp.status_code}: {resp.text[:160]}")
    j = resp.json()
    _token = j.get("access_token") or ""
    _token_exp = now + float(j.get("expires_in") or 60)
    if not _token:
        raise RuntimeError("token vazio na resposta da Assertiva")
    return _token


async def _get(path: str, params: dict) -> dict[str, Any]:
    """GET autenticado. Renova o token 1x em caso de 401."""
    if not enabled():
        return {"status": "unavailable",
                "message": "Assertiva não configurada (ASSERTIVA_CLIENT_ID/SECRET no .env)."}
    url = BASE_URL + path
    try:
        token = await _get_token()
    except Exception as exc:
        return {"status": "auth_error", "message": f"Falha ao autenticar: {str(exc)[:160]}"}

    async def _do(tok: str):
        headers = {"Authorization": f"Bearer {tok}", "Accept": "application/json"}
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            return await client.get(url, params=params, headers=headers)

    try:
        resp = await _do(token)
        if resp.status_code == 401:
            token = await _get_token(force=True)
            resp = await _do(token)
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexão: {str(exc)[:160]}"}

    # Chamada real chegou à Assertiva (independente do resultado) → é billable.
    custos.log_chamada_assertiva(endpoint=path)

    if resp.status_code == 403:
        return {"status": "no_access",
                "message": "Sem permissão para este recurso na Assertiva (403)."}
    if resp.status_code == 422:
        return {"status": "invalid", "message": f"Dados inválidos (422): {resp.text[:200]}"}
    if resp.status_code == 404:
        # A Assertiva usa 404 pra "não encontrei nada" (não é erro de sistema) —
        # o corpo traz {"resposta": "Não localizamos..."} com o motivo real.
        try:
            corpo = resp.json()
            motivo = corpo.get("resposta") or corpo.get("mensagem") or "Nenhum resultado encontrado."
        except Exception:
            motivo = "Nenhum resultado encontrado."
        return {"status": "not_found", "message": str(motivo)}
    if resp.status_code >= 400:
        return {"status": "error", "message": f"Assertiva {resp.status_code}: {resp.text[:200]}"}
    try:
        return {"status": "ok", "data": resp.json()}
    except Exception:
        return {"status": "error", "message": "Resposta inválida da Assertiva."}


# --------------------------------------------------------------------------
# Consultas principais (Localize V3)
# --------------------------------------------------------------------------

async def consulta_cpf(cpf: str, finalidade: int | None = None) -> dict[str, Any]:
    d = only_digits(cpf)
    if len(d) < 3 or len(d) > 11:
        return {"status": "invalid", "message": "CPF inválido."}
    key = f"cpf:{d}:{finalidade}"
    if key in _cache:
        return _cache[key]
    r = await _get("/localize/v3/cpf",
                   {"cpf": d, "idFinalidade": finalidade or DEFAULT_FINALIDADE})
    if r.get("status") == "ok":
        _cache[key] = r
    return r


async def consulta_cnpj(cnpj: str, finalidade: int | None = None) -> dict[str, Any]:
    d = only_digits(cnpj)
    if len(d) > 14 or len(d) < 8:
        return {"status": "invalid", "message": "CNPJ inválido."}
    key = f"cnpj:{d}:{finalidade}"
    if key in _cache:
        return _cache[key]
    r = await _get("/localize/v3/cnpj",
                   {"cnpj": d, "idFinalidade": finalidade or DEFAULT_FINALIDADE})
    if r.get("status") == "ok":
        _cache[key] = r
    return r


async def possiveis_decisores(cnpj: str, finalidade: int | None = None) -> dict[str, Any]:
    """Possíveis decisores de um CNPJ: nome, CPF, cargo e data de nascimento.

    São GESTORES (gerente, diretor, coordenador), não sócios — no CNPJ da
    Google Brasil vieram 602 pessoas, sendo 419 na folha da RAIS e nenhuma no
    quadro societário da Receita.

    O endpoint exige o `protocolo` de uma consulta de CNPJ anterior, então isso
    custa DUAS chamadas na primeira vez (a de CNPJ fica em cache). Se a
    Assertiva recusar um protocolo velho do cache, refaz a consulta de CNPJ uma
    vez e tenta de novo.
    """
    d = only_digits(cnpj)
    if len(d) != 14:
        return {"status": "invalid", "message": "CNPJ inválido."}

    key = f"decisores:{d}:{finalidade}"
    if key in _cache:
        return _cache[key]

    async def _tentar(usar_cache: bool) -> tuple[dict, str]:
        if not usar_cache:
            _cache.pop(f"cnpj:{d}:{finalidade}", None)
        base = await consulta_cnpj(d, finalidade)
        if base.get("status") != "ok":
            return base, ""
        proto = ((base.get("data") or {}).get("cabecalho") or {}).get("protocolo") or ""
        if not proto:
            return {"status": "error",
                    "message": "A consulta de CNPJ não devolveu protocolo."}, ""
        return await _get("/localize/v3/possiveis-decisores",
                          {"cnpj": d, "protocolo": proto}), proto

    r, _ = await _tentar(usar_cache=True)
    # Só vale repetir quando o PROTOCOLO foi recusado (protocolo velho do cache).
    # "not_found" é resposta legítima — micro empresa quase nunca tem decisor —
    # e repetir nesse caso DOBRAVA o custo: 2 consultas de CNPJ + 2 de decisores
    # em toda empresa sem decisor, que é a maioria.
    if r.get("status") in ("invalid", "error"):
        r, _ = await _tentar(usar_cache=False)

    # Cacheia inclusive o "não tem decisor": sem isso, cada nova montagem de
    # lista consulta de novo a mesma empresa vazia.
    if r.get("status") in ("ok", "not_found"):
        _cache[key] = r
    return r


async def relatorio_uso(desde: str = "", ate: str = "", max_paginas: int = 120,
                        por_pagina: int = 100) -> dict[str, Any]:
    """Consultas que a Assertiva REGISTROU no período — a contagem que ela fatura.

    Diferente do nosso log interno, que conta chamada HTTP: aqui reconsulta do
    mesmo documento não aparece de novo, e complementos como "possíveis
    decisores" vêm como `subItems` da consulta que os originou.

    Percorre a paginação (a resposta traz totalPages) e devolve
    {status, itens:[...], paginas, truncado}.
    """
    # 30 dias dão ~75 páginas e mais de 2 minutos de leitura. O relatório não é
    # billable, mas é lento demais pra recarregar a cada abertura do painel.
    chave = f"{desde}|{ate}|{por_pagina}"
    em_cache = _cache_relatorio.get(chave)
    if em_cache and (time.time() - em_cache[0]) < _TTL_RELATORIO:
        return {**em_cache[1], "_from_cache": True}

    itens: list[dict] = []
    pagina, total_paginas = 0, 1
    while pagina < min(total_paginas, max_paginas):
        params = {"numPage": pagina, "numPageSize": por_pagina}
        if desde:
            params["startDate"] = desde
        if ate:
            params["endDate"] = ate
        r = await _get("/localize/v3/report/usage", params)
        if r.get("status") != "ok":
            if itens:
                break
            return r
        corpo = (r.get("data") or {}).get("resposta") or {}
        try:
            total_paginas = int(corpo.get("totalPages") or 1)
        except Exception:
            total_paginas = 1
        itens.extend([x for x in (corpo.get("list") or []) if isinstance(x, dict)])
        pagina += 1

    resultado = {"status": "ok", "itens": itens, "paginas": pagina,
                 "truncado": pagina < total_paginas}
    _cache_relatorio[chave] = (time.time(), resultado)
    return resultado


async def pessoas_de_referencia(cpf: str, retornar_mae: bool = True,
                                finalidade: int | None = None) -> dict[str, Any]:
    """Parentes e sócios ligados a um CPF (mãe, pai, filhos, irmãos, cônjuge).

    O `protocolo` é opcional aqui: se a consulta de CPF já estiver em cache,
    mandamos o protocolo dela — a Assertiva trata como continuação da mesma
    consulta em vez de uma nova.
    """
    d = only_digits(cpf)
    if len(d) != 11:
        return {"status": "invalid", "message": "CPF inválido."}

    key = f"referencia:{d}:{retornar_mae}:{finalidade}"
    if key in _cache:
        return _cache[key]

    params = {"cpf": d, "retornarMae": "true" if retornar_mae else "false",
              "idFinalidade": finalidade or DEFAULT_FINALIDADE}
    base = _cache.get(f"cpf:{d}:{finalidade}")
    if base:
        proto = ((base.get("data") or {}).get("cabecalho") or {}).get("protocolo")
        if proto:
            params["protocolo"] = proto

    r = await _get("/localize/v3/pessoas-de-referencia", params)
    if r.get("status") == "ok":
        _cache[key] = r
    return r


async def conexoes(documento: str, tipo: str = "CNPJ",
                   finalidade: int | None = None, telefones: bool = True) -> dict[str, Any]:
    """Conexões de um CPF/CNPJ. Para CNPJ: sócios, possíveis decisores e
    empresas com participação — cada um com o telefone principal, tipo de linha
    e as flags de WhatsApp e 'não perturbe'."""
    d = only_digits(documento)
    tipo = (tipo or "CNPJ").upper()
    if tipo not in ("CPF", "CNPJ"):
        return {"status": "invalid", "message": "tipo deve ser CPF ou CNPJ."}
    if (tipo == "CNPJ" and len(d) != 14) or (tipo == "CPF" and len(d) != 11):
        return {"status": "invalid", "message": f"{tipo} inválido."}

    key = f"conexoes:{tipo}:{d}:{finalidade}"
    if key in _cache:
        return _cache[key]
    params = {"documento": d, "tipo": tipo, "idFinalidade": finalidade or DEFAULT_FINALIDADE}
    if telefones:
        params["telefones"] = "true"
    r = await _get("/localize-api/v1/base-cadastral/conexoes", params)
    if r.get("status") == "ok":
        _cache[key] = r
    return r


async def consulta_telefone(telefone: str, finalidade: int | None = None) -> dict[str, Any]:
    d = only_digits(telefone)
    if len(d) < 10 or len(d) > 11:
        return {"status": "invalid", "message": "Telefone deve ter 10 ou 11 dígitos."}
    r = await _get("/localize/v3/telefone",
                   {"telefone": d, "idFinalidade": finalidade or DEFAULT_FINALIDADE})
    return r


async def consulta_email(email: str, finalidade: int | None = None) -> dict[str, Any]:
    email = (email or "").strip()
    if "@" not in email:
        return {"status": "invalid", "message": "E-mail inválido."}
    r = await _get("/localize/v3/email",
                   {"email": email, "idFinalidade": finalidade or DEFAULT_FINALIDADE})
    return r


def _norm_tel(t: Any) -> dict[str, Any] | None:
    """Normaliza um telefone da Assertiva para o formato do mkbuscas.refine_phones
    ({ddd, number, telefone, tipo, whatsapp}), aceitando string ou dict variado."""
    if isinstance(t, str):
        d = only_digits(t)
        return {"ddd": "", "number": d, "telefone": d, "tipo": "", "whatsapp": None} if d else None
    if not isinstance(t, dict):
        return None
    ddd = only_digits(str(t.get("ddd") or t.get("codigoArea") or ""))
    num = only_digits(str(t.get("numero") or t.get("telefone") or t.get("numeroTelefone") or ""))
    full = num if (ddd and num.startswith(ddd)) else (ddd + num)
    full = only_digits(full)
    if not full:
        return None
    whats = t.get("whatsApp")
    if whats is None and isinstance(t.get("aplicativos"), dict):
        whats = t["aplicativos"].get("whatsApp")
    # No schema real do Localize (reverso de CPF), ter data de WhatsApp = tem WhatsApp.
    if whats is None and t.get("whatsapp_datetime"):
        whats = True
    # priority (1 = mais provável de estar correto na Assertiva); classification (1 melhor).
    try:
        prio = int(t.get("priority")) if t.get("priority") is not None else None
    except (TypeError, ValueError):
        prio = None
    return {
        "ddd": ddd,
        "number": full,
        "telefone": full,
        "tipo": str(t.get("tipoTelefone") or t.get("tipo") or ""),
        "whatsapp": bool(whats) if whats is not None else None,
        "priority": prio,
        "classification": t.get("classification"),
        "ranking": t.get("ranking") or t.get("classificacao") or "",
    }


def _flatten_tel(src: Any) -> list[dict[str, Any]]:
    """Achata `telefones` (pode ser lista, ou dict com listas por tipo) em telefones normalizados."""
    out: list[dict[str, Any]] = []
    if not src:
        return out
    if isinstance(src, list):
        for x in src:
            n = _norm_tel(x)
            if n:
                out.append(n)
    elif isinstance(src, dict):
        for v in src.values():
            if isinstance(v, list):
                for x in v:
                    n = _norm_tel(x)
                    if n:
                        out.append(n)
            elif isinstance(v, dict):
                n = _norm_tel(v)
                if n:
                    out.append(n)
    return out


async def telefones_documento(doc: str, tipo: str = "CPF",
                              finalidade: int | None = None) -> dict[str, Any]:
    """Telefones de um CPF/CNPJ via consulta principal do Localize.

    Retorna {status, telefones:[{ddd,number,telefone,tipo,whatsapp}], protocolo}.
    A lista sai crua (sem filtro) — quem chama aplica mkbuscas.refine_phones.
    """
    tipo = (tipo or "CPF").upper()
    r = await (consulta_cnpj(doc, finalidade) if tipo == "CNPJ"
               else consulta_cpf(doc, finalidade))
    if r.get("status") != "ok":
        return {"status": r.get("status"), "message": r.get("message", ""), "telefones": []}
    data = r.get("data") or {}
    resp = data.get("resposta") or {}
    tels = _flatten_tel(resp.get("telefones")) + _flatten_tel(resp.get("telefonesAdicionados"))
    return {
        "status": "ok",
        "telefones": tels,
        "protocolo": (data.get("cabecalho") or {}).get("protocolo", ""),
    }


async def contato_cpf(cpf: str, finalidade: int | None = None) -> dict[str, Any]:
    """Telefones + e-mails de um CPF (para enriquecer contato de sócio/decisor).

    Retorna {status, telefones:[{ddd,number,telefone,tipo,whatsapp}], emails:[str]}.
    """
    r = await consulta_cpf(cpf, finalidade)
    if r.get("status") != "ok":
        return {"status": r.get("status"), "message": r.get("message", ""),
                "telefones": [], "emails": []}
    resp = ((r.get("data") or {}).get("resposta")) or {}
    tels = _flatten_tel(resp.get("telefones")) + _flatten_tel(resp.get("telefonesAdicionados"))
    emails = []
    for e in (resp.get("emails") or []) + (resp.get("emailsAdicionados") or []):
        if isinstance(e, dict):
            val = e.get("email") or e.get("enderecoEmail") or ""
        else:
            val = str(e)
        if val:
            emails.append(val)
    return {"status": "ok", "telefones": tels, "emails": emails}


async def busca_nome_endereco(filtros: dict, finalidade: int | None = None) -> dict[str, Any]:
    """Busca por nome/razão social e/ou endereço.

    filtros aceita: buscarPor (pessoas|empresas|ambas), nomeOuRazaoSocial,
    nomeOuRazaoSocialExata (bool), sexo, dataNascimentoOuAbertura (dd/MM/yyyy),
    uf, cidade, bairro, cepOuNomeRua, numeroInicial, numeroFinal, complemento.
    """
    filtros = filtros or {}
    buscar_por = (filtros.get("buscarPor") or "ambas").strip()
    nome = (filtros.get("nomeOuRazaoSocial") or "").strip()
    cep_rua = (filtros.get("cepOuNomeRua") or "").strip()
    if not nome and not cep_rua:
        return {"status": "invalid",
                "message": "Informe ao menos o nome/razão social ou CEP/rua."}
    params: dict[str, Any] = {
        "buscarPor": buscar_por,
        "idFinalidade": finalidade or DEFAULT_FINALIDADE,
    }
    passa = ["nomeOuRazaoSocial", "nomeOuRazaoSocialExata", "sexo",
             "dataNascimentoOuAbertura", "uf", "cidade", "bairro",
             "cepOuNomeRua", "numeroInicial", "numeroFinal", "complemento"]
    for k in passa:
        v = filtros.get(k)
        if v not in (None, "", []):
            params[k] = v
    return await _get("/localize/v3/nome-endereco", params)
