"""Cliente da API Meetime + deduplicação de leads.

Usado para NÃO prospectar quem já está na Meetime. Baixa os leads existentes
(CNPJ + nome da empresa/contato), e o `dedup()` remove candidatos que batem:
  - por CNPJ (igualdade exata dos 14 dígitos), OU
  - por SIMILARIDADE de nome (equivalente a LIKE %nome% do SQL): nome normalizado
    de um contido no outro, ou todos os tokens significativos presentes.

Config (.env):
- MEETIME_TOKEN        token da API (obrigatório para ativar)
- MEETIME_BASE_URL     default https://api.meetime.com.br
- MEETIME_LEADS_PATH   default /v2/leads
- MEETIME_AUTH_HEADER  default api-token   (nome do header de auth)
- MEETIME_PAGE_SIZE    default 200

Pegadinha da API v2 (ver memória): paginação SÓ com limit+start, ordem crescente;
rejeita sort/date. Por isso paginamos incrementando `start`.
"""
import asyncio
import os
import re
import hashlib
import time
import unicodedata
from typing import Any

import httpx

import meetime_base

import config_store

# Config vem do store (admin define pela UI) com fallback pro ambiente.
def _cfg(key, env, default=""):
    v = config_store.get(key)
    if v:
        return str(v).strip()
    return os.environ.get(env, default).strip()


def _grupos_tokens() -> dict:
    """{grupo_id: {"token":..., "nome":...}} — um token Meetime por grupo de usuários."""
    v = config_store.get("meetime_grupos") or {}
    return v if isinstance(v, dict) else {}


def set_token_grupo(grupo_id: str, token: str) -> None:
    grupos = _grupos_tokens()
    grupos[grupo_id] = {**grupos.get(grupo_id, {}), "token": token}
    config_store.set_many({"meetime_grupos": grupos})
    _cache.pop(grupo_id or "__default__", None)


def status_grupos() -> dict:
    """Resumo (sem expor o token) de quais grupos têm token Meetime configurado."""
    return {gid: {"configurado": bool((v or {}).get("token"))} for gid, v in _grupos_tokens().items()}


# ---------------------------------------------------------------------
# TOKEN POR USUARIO
#
# Ate aqui havia dois lugares: o token do GRUPO, que so o admin configura, e
# um campo avulso no painel de filtros que valia para uma busca so e nao era
# guardado.
#
# Isso servia para quem usa a conta do grupo e nao muda nunca. Nao serve para
# quem TROCA de conta com frequencia -- e e o caso: cada troca exigiria pedir
# ao admin, ou recolar o token em cada busca.
#
# Recolar em cada busca parece mais seguro e nao e: o segredo atravessa o
# navegador toda vez, em vez de uma vez so. Guardar no servidor, indexado
# pelo usuario, e devolver so um resumo mascarado expoe MENOS.
#
# O valor nunca volta para a tela. `status_usuario` devolve os quatro
# ultimos digitos e a contagem de leads -- o suficiente para a pessoa
# reconhecer qual conta esta ativa sem que a credencial trafegue de novo.
def _tokens_usuarios() -> dict:
    v = config_store.get("meetime_usuarios") or {}
    return v if isinstance(v, dict) else {}


def _chave_usuario(email: str) -> str:
    return (email or "").strip().lower()


def set_token_usuario(email: str, token: str) -> dict:
    """Grava (ou apaga, com token vazio) o token de UM usuario."""
    chave = _chave_usuario(email)
    if not chave:
        return {"status": "error", "message": "Sem usuário identificado."}
    usuarios = _tokens_usuarios()
    token = (token or "").strip()
    if token:
        usuarios[chave] = {"token": token}
    else:
        usuarios.pop(chave, None)
    config_store.set_many({"meetime_usuarios": usuarios})
    # O cache de memoria e por conta: trocar de token tem que descartar o
    # indice da conta anterior, senao a dedup seguiria comparando contra a
    # base errada -- e silenciosamente, que e o pior jeito de errar aqui.
    _cache.clear()
    return {"status": "ok", "configurado": bool(token)}


def token_do_usuario(email: str) -> str:
    return str((_tokens_usuarios().get(_chave_usuario(email)) or {})
               .get("token") or "").strip()


def status_usuario(email: str, grupo_id: str = "") -> dict:
    """O que a tela precisa saber, sem o segredo."""
    meu = token_do_usuario(email)
    return {
        "tem_proprio": bool(meu),
        # Quatro digitos bastam para reconhecer qual conta esta ativa e nao
        # bastam para usar o token.
        "final": meu[-4:] if len(meu) > 4 else "",
        "tem_grupo": bool(_token(grupo_id)),
        "em_uso": "proprio" if meu else ("grupo" if _token(grupo_id) else "nenhum"),
    }


def _token(grupo_id: str = "", usuario: str = "") -> str:
    """Ordem: token do proprio usuario > token do grupo > token global.

    O do usuario vem primeiro porque e o mais especifico e o mais recente --
    quem acabou de trocar espera que a troca valha.
    """
    if usuario:
        meu = token_do_usuario(usuario)
        if meu:
            return meu
    if grupo_id:
        tok = (_grupos_tokens().get(grupo_id) or {}).get("token")
        if tok:
            return str(tok).strip()
    return _cfg("meetime_token", "MEETIME_TOKEN", "")


def _base_url() -> str:
    return _cfg("meetime_base_url", "MEETIME_BASE_URL",
                "https://api.meetime.com.br").rstrip("/")


def _leads_path() -> str:
    return _cfg("meetime_leads_path", "MEETIME_LEADS_PATH", "/v2/leads")


def url_leads() -> str:
    """Base + caminho SEM repetir a versão.

    Isto existe porque aconteceu: a configuração guardada tinha base
    `https://api.meetime.com.br/v2` e caminho `/v2/leads`, e a concatenação
    dava `/v2/v2/leads` -> HTTP 404 em toda chamada. A dedup contra a Meetime
    nunca funcionou nesse ambiente, e o sintoma era um aviso genérico de
    falha que ninguém associou a uma barra a mais.

    Os padrões do código sempre estiveram certos; quem quebrou foi um valor
    digitado no painel do admin. Por isso a proteção fica AQUI, no ponto que
    monta a URL, e não numa correção do valor guardado -- o painel continua
    aberto e o mesmo erro pode voltar amanhã.
    """
    base = _base_url()
    caminho = _leads_path()
    if not caminho.startswith("/"):
        caminho = "/" + caminho
    primeiro = caminho.strip("/").split("/")[0]
    if primeiro and base.rstrip("/").endswith("/" + primeiro):
        base = base.rstrip("/")[: -(len(primeiro) + 1)]
    return base.rstrip("/") + caminho


def _auth_header() -> str:
    # MEDIDO em 10/set/2026: `Authorization: <token>` devolve 200 e 12.440
    # leads; `api-token` devolve 401. O padrão antigo era `api-token`, e a
    # configuração guardada repetia o erro -- duas fontes concordando na
    # coisa errada.
    return _cfg("meetime_auth_header", "MEETIME_AUTH_HEADER", "Authorization")


# 100 e o TETO da API: medido, 500 e 1000 devolvem HTTP 400. Estava em 50,
# o que dobrava o numero de requisicoes -- e cada uma tem 1,2s de espera
# entre elas, entao 12.440 leads levavam 249 chamadas em vez de 125.
PAGE_SIZE = int(os.environ.get("MEETIME_PAGE_SIZE", "100") or "100")
_TIMEOUT = httpx.Timeout(40.0)

# Sufixos societários irrelevantes para comparar nomes.
_SUFIXOS = re.compile(
    r"\b(ltda|epp|me|eireli|s\s?a|sa|s/a|sociedade|anonima|limitada|"
    r"comercio|comercial|industria|industrial|servicos|transportes|transporte|"
    r"do brasil|brasil|cia|companhia|grupo|holding|participacoes)\b")

# Cache em memória dos existentes, por grupo (cada grupo é uma conta Meetime
# diferente — não dá pra compartilhar cache entre grupos). Evita rebaixar a
# API a cada dedup.
_cache: dict[str, dict[str, Any]] = {}
_CACHE_TTL = 1800  # 30 min


def enabled(grupo_id: str = "", token_avulso: str = "",
            usuario: str = "") -> bool:
    """Dá para consultar a Meetime? Token do grupo OU o que o operador digitou.

    O `token_avulso` conta aqui: sem isso, quem digita um token para filtrar
    contra outra conta levaria "Meetime não configurada" mesmo tendo acabado
    de fornecer a credencial.
    """
    return bool((token_avulso.strip() or _token(grupo_id, usuario)) and _base_url())


def only_digits(s: str) -> str:
    return re.sub(r"\D", "", str(s or ""))


def norm_nome(s: str) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    s = _SUFIXOS.sub(" ", s)
    return re.sub(r"\s+", " ", s).strip()


def _tokens(nome_norm: str) -> set:
    return {t for t in nome_norm.split() if len(t) >= 3}


def _extrai_lead(rec: dict) -> tuple[str, list[str]]:
    """Extrai (cnpj_digits, [nomes]) de um registro de lead, de forma defensiva."""
    cnpj, nomes = "", []
    if not isinstance(rec, dict):
        return cnpj, nomes
    for k in ("cnpj", "document", "documento", "cpf_cnpj", "companyDocument"):
        if rec.get(k):
            d = only_digits(rec[k])
            if len(d) == 14:
                cnpj = d
                break
    for k in ("company", "companyName", "razaoSocial", "razao_social", "empresa",
              "name", "nome", "lead_company", "tradeName", "nomeFantasia"):
        v = rec.get(k)
        if isinstance(v, str) and v.strip():
            nomes.append(v.strip())
        elif isinstance(v, dict):  # às vezes company é objeto {name:...}
            for kk in ("name", "razaoSocial", "nome"):
                if v.get(kk):
                    nomes.append(str(v[kk]))
    return cnpj, nomes


async def fetch_existing(max_pages: int = 200, force: bool = False,
                         grupo_id: str = "", token_avulso: str = "",
                         usuario: str = "") -> dict:
    """Baixa (paginando) os leads da Meetime → {cnpjs:set, nomes:[(norm, tokens)]}.

    Cada grupo tem sua própria conta/token, então o cache também é por grupo.

    `token_avulso` é o token que o OPERADOR digitou na tela, para filtrar contra
    uma conta que não é a do grupo dele. Ele vale só para esta chamada e
    NUNCA É GRAVADO — nem em `config_store`, nem em log, nem na resposta.

    Isso é deliberado. O token do grupo é credencial de máquina: fica no
    serviço de dados e nem o navegador o vê. Um token digitado na tela já
    passou pelo navegador, então guardá-lo depois disso só aumentaria a
    exposição sem devolver nada. O operador redigita quando precisar de novo.

    A chave de cache dele é o HASH do token, não o token: assim duas buscas
    seguidas na mesma conta reaproveitam a lista sem que o segredo apareça em
    nenhuma estrutura de memória indexada por ele.
    """
    if token_avulso:
        cache_key = "avulso:" + hashlib.sha256(
            token_avulso.strip().encode()).hexdigest()[:16]
    else:
        cache_key = grupo_id or "__default__"
    if not enabled(grupo_id, token_avulso, usuario):
        return {"status": "unavailable", "message": "Meetime não configurada para este grupo (token ausente).",
                "cnpjs": set(), "nomes": []}
    now = time.time()
    cached = _cache.get(cache_key)
    if not force and cached and cached["ts"] and now - cached["ts"] < _CACHE_TTL:
        return {"status": "ok", "cnpjs": cached["cnpjs"], "nomes": cached["nomes"],
                "total": len(cached["cnpjs"]) + len(cached["nomes"]), "cache": True}

    headers = {"Accept": "application/json",
               _auth_header(): (token_avulso.strip() if token_avulso
                                else _token(grupo_id, usuario))}

    # ---- RETOMA DE ONDE PAROU ----------------------------------------
    # A API nao aceita filtro por data (`start_date` -> HTTP 400) nem
    # ordenacao: a ordem e crescente e fixa. Entao "so o que e novo" se
    # obtem pelo OFFSET -- se da ultima vez a conta tinha 12.158 leads,
    # comeca em 12.158. O novo esta no fim.
    #
    # Sem isso, cada sincronizacao refaz a base inteira: medido, 20.689
    # leads dao 207 requisicoes e 118 segundos.
    # A conta segue o token QUE VAI SER USADO, e nao so o avulso: com token
    # proprio do usuario, o indice tem que ser o dele -- senao a dedup
    # compararia contra a base do grupo enquanto le a base dele.
    conta = meetime_base.id_da_conta(
        token_avulso or token_do_usuario(usuario), grupo_id)
    ja = meetime_base.estado(conta)
    guardado = meetime_base.carregar(conta) if ja["conhecida"] else None
    cnpjs = set(guardado["cnpjs"]) if guardado else set()
    nomes = [(n, _tokens(n)) for n in (guardado["nomes"] if guardado else [])]
    url = url_leads()
    start = 0 if (force or not ja["conhecida"]) else int(ja["offset"])
    if start:
        # Recua uma pagina de proposito. Custa uma requisicao e cobre o caso
        # do lote anterior ter sido cortado no meio por erro de rede.
        start = max(0, start - PAGE_SIZE)
    base_inicial = start
    novos_cnpjs, novos_nomes = set(), []
    total_relatado = 0
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            for _ in range(max_pages):
                resp = None
                for tentativa in range(4):
                    resp = await client.get(url, params={"limit": PAGE_SIZE, "start": start}, headers=headers)
                    if resp.status_code != 429:
                        break
                    await asyncio.sleep(2.5 * (tentativa + 1))
                if resp.status_code == 401:
                    return {"status": "no_access", "message": "Token Meetime inválido (401).",
                            "cnpjs": set(), "nomes": []}
                if resp.status_code >= 400:
                    return {"status": "error", "message": f"Meetime {resp.status_code}: {resp.text[:200]}",
                            "cnpjs": cnpjs, "nomes": nomes}
                j = resp.json()
                # a lista pode vir na raiz ou em data/results/leads
                lote = j if isinstance(j, list) else (
                    j.get("data") or j.get("results") or j.get("leads") or j.get("items") or [])
                if not lote:
                    break
                if isinstance(j, dict) and j.get("totalItems"):
                    try:
                        total_relatado = int(j["totalItems"])
                    except (TypeError, ValueError):
                        pass
                for rec in lote:
                    cnpj, nms = _extrai_lead(rec)
                    if cnpj:
                        cnpjs.add(cnpj)
                        novos_cnpjs.add(cnpj)
                    for nm in nms:
                        nn = norm_nome(nm)
                        if nn:
                            nomes.append((nn, _tokens(nn)))
                            novos_nomes.append(nn)
                start += len(lote)
                if len(lote) < PAGE_SIZE:
                    break
                await asyncio.sleep(1.2)
    except Exception as exc:
        return {"status": "error", "message": f"Erro de conexão Meetime: {str(exc)[:150]}",
                "cnpjs": cnpjs, "nomes": nomes}

    # LEAD APAGADO DESALINHA OS OFFSETS. Se a conta encolheu, o ponto de
    # retomada nao vale mais e a base e refeita -- preferir refazer a
    # arrastar um indice furado que ninguem percebe.
    encolheu = bool(total_relatado and ja["conhecida"]
                    and total_relatado < ja["total_visto"])
    if encolheu:
        meetime_base.esquecer(conta)
    else:
        meetime_base.guardar(conta, novos_cnpjs, novos_nomes,
                             offset_fim=start,
                             total_visto=total_relatado or start,
                             zerar_antes=(base_inicial == 0 and force))

    _cache[cache_key] = {"ts": now, "cnpjs": cnpjs, "nomes": nomes}
    return {"status": "ok", "cnpjs": cnpjs, "nomes": nomes,
            "total_cnpjs": len(cnpjs), "total_nomes": len(nomes),
            "cache": False,
            "conta": conta,
            "incremental": base_inicial > 0,
            "novos_nesta_sync": len(novos_cnpjs),
            "refez_do_zero": encolheu}


def _nome_bate(cand_norm: str, cand_tokens: set, existentes: list) -> bool:
    """Similaridade tipo LIKE %: substring nos dois sentidos OU tokens contidos."""
    if not cand_norm:
        return False
    for nn, toks in existentes:
        if not nn:
            continue
        if cand_norm in nn or nn in cand_norm:      # LIKE %nome%
            return True
        # todos os tokens significativos do menor presentes no maior
        if cand_tokens and toks:
            menor, maior = (cand_tokens, toks) if len(cand_tokens) <= len(toks) else (toks, cand_tokens)
            if len(menor) >= 2 and menor.issubset(maior):
                return True
    return False


def dedup(candidatos: list[dict], existing: dict) -> dict:
    """Separa candidatos em novos vs já-na-meetime (por CNPJ ou nome).

    candidatos: [{cnpj, razao_social|razao|nome}]. Retorna {novos, removidos}.
    """
    cnpjs = existing.get("cnpjs") or set()
    nomes = existing.get("nomes") or []
    novos, removidos = [], []
    for c in candidatos:
        cnpj = only_digits(c.get("cnpj") or "")
        razao = c.get("razao_social") or c.get("razao") or c.get("nome") or ""
        motivo = None
        if len(cnpj) == 14 and cnpj in cnpjs:
            motivo = "cnpj"
        else:
            nn = norm_nome(razao)
            if _nome_bate(nn, _tokens(nn), nomes):
                motivo = "nome"
        if motivo:
            removidos.append({**c, "_dedup": motivo})
        else:
            novos.append(c)
    return {"novos": novos, "removidos": removidos,
            "n_novos": len(novos), "n_removidos": len(removidos)}


async def testar_token(token: str = "", grupo_id: str = "",
                       usuario: str = "") -> dict:
    """Diz, em UMA requisicao, se o token serve e o que ele enxerga.

    Existe porque hoje a unica forma de descobrir que o token esta errado e
    rodar a dedup inteira e ver dar errado no fim -- depois de esperar. Um
    teste de 1 requisicao responde na hora.

    Devolve o TAMANHO DA BASE junto, e isso nao e enfeite: existem duas
    contas Meetime na casa, uma que ve 20.689 leads e outra que ve 12.158.
    Saber qual delas o token abriu e a diferenca entre deduplicar contra a
    base certa e contra a errada -- o Banco do Brasil existe numa e nao
    existe na outra, o que ja pareceu bug de casamento e nao era.
    """
    alvo = (token or "").strip()
    if not alvo and not enabled(grupo_id, "", usuario):
        return {"status": "unavailable",
                "message": "Nenhum token configurado para o seu grupo."}
    headers = {"Accept": "application/json",
               _auth_header(): (alvo or _token(grupo_id, usuario))}
    url = url_leads()
    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            # `limit=1` de proposito: e um teste, nao uma leitura.
            r = await client.get(url, params={"limit": 1, "start": 0},
                                 headers=headers)
    except Exception as exc:
        return {"status": "error",
                "message": "Não consegui falar com a Meetime: %s" % str(exc)[:120]}
    if r.status_code == 401:
        return {"status": "invalido",
                "message": "A Meetime recusou este token (401). Confira se "
                           "copiou inteiro e sem espaços."}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "Meetime devolveu %s: %s" % (r.status_code, r.text[:120])}
    try:
        j = r.json()
    except Exception:
        return {"status": "error", "message": "Resposta ilegível da Meetime."}

    total = 0
    if isinstance(j, dict):
        try:
            total = int(j.get("totalItems") or 0)
        except (TypeError, ValueError):
            total = 0

    conta = meetime_base.id_da_conta(alvo or token_do_usuario(usuario), grupo_id)
    st = meetime_base.estado(conta)
    return {
        "status": "ok",
        "message": "Token válido.",
        "leads_na_conta": total,
        "ms": int((time.time() - t0) * 1000),
        # O que ja temos guardado desta conta -- e o que diz se a proxima
        # dedup vai levar 2 segundos ou 2 minutos.
        "conta": conta,
        "ja_conhecida": st["conhecida"],
        "leads_guardados": st["leads"],
        "sincronizado_em": st["sincronizado"],
        "faltam_sincronizar": max(0, total - int(st["total_visto"] or 0)),
    }
