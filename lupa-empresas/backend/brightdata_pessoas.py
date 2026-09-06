# -*- coding: utf-8 -*-
"""Busca funcionarios de uma empresa no dataset de perfis do LinkedIn (Bright Data).

NAO baixa a base inteira. Manda o criterio (empresa + pais + cargo) para a API de
filtro do Marketplace, que devolve so quem casa. O dataset e o mesmo de onde sai o
snapshot completo — a diferenca e perguntar em vez de baixar 669 MB de perfis
aleatorios do mundo todo.

ATENCAO AOS CAMINHOS. Os que estavam no `linkedin_scraper.py` sao de uma versao
antiga da API e respondem 404:
    /datasets/v3/filter         -> "Cannot POST"        | certo: /datasets/filter
    /datasets/v3/snapshot/{id}  -> "does not exist"     | certo: /datasets/snapshots/{id}/download

O JOB E ASSINCRONO e leva de ~1 a 4 minutos (empresa especifica e rapido; filtro
largo, tipo "todo o Brasil", demora bem mais). Por isso a busca e em duas partes:
`disparar()` devolve um protocolo, `consultar()` diz se ficou pronto. Segurar a
requisicao HTTP esperando o job daria timeout no proxy do Render.

CUSTA DINHEIRO POR REGISTRO ENTREGUE, nao por consulta. Por isso `limite` e
sempre explicito e o padrao e baixo.
"""
import os
import re
from typing import Any

import httpx

import linkedin_cache

CHAVE = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
DATASET = os.environ.get("BRIGHTDATA_PEOPLE_DATASET_ID", "gd_l1viktl72bvl7bjuj0").strip()
FILTER_URL = "https://api.brightdata.com/datasets/filter"
SNAP_URL = "https://api.brightdata.com/datasets/snapshots"

LIMITE_PADRAO = int(os.environ.get("BRIGHTDATA_DATASET_LIMIT", "50"))
LIMITE_MAX = int(os.environ.get("BRIGHTDATA_LIMITE_MAX", "500"))
_TIMEOUT = httpx.Timeout(90.0)


# O /datasets/v3/scrape CONTINUA valido (so o /v3/filter e o /v3/snapshot mudaram).
# Raspar a pagina da empresa e rapido (segundos) e devolve o nome EXATO como o
# LinkedIn escreve — que e o que faz o filtro de pessoas acertar depois.
SCRAPE_URL = "https://api.brightdata.com/datasets/v3/scrape"
DATASET_EMPRESA = os.environ.get(
    "BRIGHTDATA_COMPANY_DATASET_ID", "gd_l1vikfnt1wgvvqz95w").strip()


def enabled() -> bool:
    return bool(CHAVE and DATASET)


def _headers() -> dict[str, str]:
    return {"Authorization": "Bearer " + CHAVE, "Content-Type": "application/json"}


def _norm(s: str) -> str:
    return re.sub(r"\s+", " ", (s or "").strip())


_RE_COMPANY = re.compile(r"linkedin\.com/company/([^/?#\s]+)", re.I)


async def empresa_por_url(url: str) -> dict[str, Any]:
    """Raspa a pagina da empresa. Serve para dois problemas de uma vez:

    1. Da o nome EXATO como o LinkedIn escreve (o filtro de pessoas casa por
       nome, e a razao social da Receita quase nunca bate).
    2. Diz o tamanho da empresa no LinkedIn — que e o que prevê se o filtro de
       pessoas vai voltar em 1 minuto ou estourar o tempo. Empresa de 300 mil
       funcionarios nao termina; de 5 mil, volta rapido.
    """
    if not enabled():
        return {"status": "unavailable",
                "message": "Bright Data nao configurada (BRIGHTDATA_API_KEY)."}
    url = _norm(url)
    m = _RE_COMPANY.search(url)
    if not m:
        return {"status": "error",
                "message": "Cole o link da PAGINA DA EMPRESA "
                           "(linkedin.com/company/...), nao o de uma pessoa."}
    limpo = "https://www.linkedin.com/company/" + m.group(1)

    # Raspagem de empresa tambem e cobrada — se ja conferimos esse link, reusa.
    try:
        antes = linkedin_cache.empresa_cacheada(limpo)
    except Exception:
        antes = None
    if antes:
        return {"status": "ok", "fonte": "cache",
                "nome": antes["nome"], "company_id": antes["company_id"],
                "funcionarios_linkedin": antes["funcionarios"],
                "setor": antes["setor"], "sede": antes["sede"],
                "site": antes["site"], "pais": antes["pais"],
                "url": limpo, "destaque": [], "aviso_tamanho": ""}

    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(180.0)) as cli:
            r = await cli.post(
                "%s?dataset_id=%s&format=json" % (SCRAPE_URL, DATASET_EMPRESA),
                headers=_headers(), json=[{"url": limpo}])
    except Exception as exc:
        return {"status": "error", "message": "Falha ao falar com a Bright Data: %s"
                                              % str(exc)[:140]}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "Bright Data %s: %s" % (r.status_code, r.text[:200])}
    import json as _json
    try:
        d = _json.loads(r.content)          # bytes: a resposta e UTF-8 sem charset
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Bright Data."}
    if isinstance(d, list):
        d = d[0] if d else {}
    if not isinstance(d, dict) or not d.get("name"):
        return {"status": "not_found",
                "message": "Nao achei essa empresa no LinkedIn. Confira o link."}

    destaque = []
    for chave in ("employees", "alumni"):
        for e in d.get(chave) or []:
            if isinstance(e, dict):
                nome = _norm(e.get("title") or e.get("name") or "")
                lnk = (e.get("link") or e.get("url") or "").split("?")[0]
                if nome and lnk:
                    destaque.append({"nome": nome, "url": lnk})
    total = d.get("employees_in_linkedin")
    saida = {
        "status": "ok",
        "nome": d.get("name") or "",
        "company_id": str(d.get("company_id") or ""),
        "funcionarios_linkedin": total,
        "setor": d.get("industries") or "",
        "sede": d.get("headquarters") or "",
        "site": d.get("website") or "",
        "pais": d.get("country_code") or "",
        "url": limpo,
        "destaque": destaque[:12],
        # Aviso honesto na tela em vez de deixar a pessoa esperar 7 minutos por nada.
        "aviso_tamanho": (
            "Empresa grande (%s pessoas no LinkedIn). O filtro pode demorar muito "
            "ou nao terminar — vale restringir por cargo." % f"{total:,}".replace(",", ".")
            if isinstance(total, int) and total > 50000 else ""),
    }
    try:
        linkedin_cache.salvar_empresa(saida)
        # Os perfis em destaque vem de graca junto com a pagina: guarda tambem.
        if destaque:
            linkedin_cache.salvar_perfis(
                [{"url": p["url"], "nome": p["nome"], "empresa": saida["nome"],
                  "pais": saida.get("pais")} for p in destaque], origem="api")
    except Exception:
        pass
    return saida


def _candidatas(nome: str) -> list[str]:
    """URLs plausíveis da empresa no LinkedIn, a partir do nome.

    Não existe "buscar empresa por nome" na API da Bright Data — só acerto de
    URL. Então geramos variações e conferimos quais existem. Da mais provável
    para a menos, porque cada raspagem é cobrada.
    """
    base = _norm(nome).lower()
    if not base:
        return []
    tabela = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    base = base.translate(tabela)
    base = re.sub(r"[^a-z0-9 ]+", " ", base).strip()
    palavras = [p for p in base.split() if p]
    if not palavras:
        return []

    # Sufixos societários não entram no slug do LinkedIn.
    ruido = {"sa", "s", "a", "ltda", "me", "eireli", "epp", "do", "da", "de",
             "dos", "das", "e"}
    limpas = [p for p in palavras if p not in ruido] or palavras

    vistos, saida = set(), []
    for cand in ("-".join(limpas), "-".join(palavras), limpas[0],
                 "-".join(limpas[:2]), "".join(limpas)):
        if cand and cand not in vistos:
            vistos.add(cand)
            saida.append("https://www.linkedin.com/company/" + cand)
    return saida


async def sugerir_empresas(q: str, conferir: int = 0) -> dict[str, Any]:
    """Ajuda a achar a empresa certa quando o nome não bate de primeira.

    Duas camadas, de propósito nessa ordem:
      1. O que já temos no cache — grátis, instantâneo, com a grafia real.
      2. Só se pedido (`conferir` > 0), raspa N URLs candidatas no LinkedIn.
         Isso CUSTA, então nunca acontece sozinho.
    """
    q = _norm(q)
    if not q:
        return {"status": "error", "message": "Escreva um pedaço do nome."}

    try:
        conhecidas = linkedin_cache.empresas_parecidas(q)
    except Exception:
        conhecidas = []

    candidatas = _candidatas(q)
    confirmadas = []
    for url in candidatas[:max(0, int(conferir))]:
        r = await empresa_por_url(url)
        if r.get("status") == "ok":
            confirmadas.append({
                "nome": r.get("nome"), "url": r.get("url"),
                "funcionarios": r.get("funcionarios_linkedin"),
                "setor": r.get("setor"), "sede": r.get("sede"),
                "fonte": r.get("fonte") or "linkedin",
            })

    return {
        "status": "ok",
        "termo": q,
        "conhecidas": conhecidas,          # do cache: {empresa, quantos, visto_em}
        "confirmadas": confirmadas,        # raspadas agora
        "candidatas": candidatas,          # ainda não conferidas (cada uma custa)
        "message": "" if (conhecidas or confirmadas) else
                   "Não temos ninguém dessa empresa ainda. Confira as URLs "
                   "candidatas ou cole o link da página no LinkedIn.",
    }


async def disparar(empresa: str, pais: str = "BR", cargo: str = "",
                   limite: int = 0, forcar: bool = False) -> dict[str, Any]:
    """Dispara o filtro. Retorna {status, protocolo} — NAO espera o resultado."""
    if not enabled():
        return {"status": "unavailable",
                "message": "Bright Data nao configurada (BRIGHTDATA_API_KEY)."}
    empresa = _norm(empresa)
    if not empresa:
        return {"status": "error", "message": "Informe o nome da empresa."}

    limite = max(1, min(int(limite or LIMITE_PADRAO), LIMITE_MAX))

    # CACHE PRIMEIRO. Cobra-se por perfil entregue, então repetir a mesma busca
    # paga de novo pela mesma gente. Só vai à Bright Data com forcar=True.
    if not forcar:
        try:
            guardados = linkedin_cache.por_empresa(empresa, pais=pais, cargo=cargo,
                                                   limite=limite)
        except Exception:
            guardados = []
        if guardados:
            return {
                "status": "cache",
                "empresa": empresa,
                "total": len(guardados),
                "pessoas": guardados,
                "message": "Do que já foi comprado antes — não gastou nada agora.",
            }

    condicoes = [{"name": "current_company_name", "operator": "includes", "value": empresa}]
    if pais:
        condicoes.append({"name": "country_code", "operator": "=", "value": pais.upper()[:2]})
    if _norm(cargo):
        condicoes.append({"name": "position", "operator": "includes", "value": _norm(cargo)})

    corpo = {
        "dataset_id": DATASET,
        "records_limit": limite,
        # A API aceita filtro simples OU composto; com uma condicao so, o formato
        # composto tambem vale, entao nao ha caminho especial aqui.
        "filter": {"operator": "and", "filters": condicoes},
    }

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(FILTER_URL + "?format=json", headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "message": "Falha ao falar com a Bright Data: %s"
                                              % str(exc)[:140]}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "Bright Data %s: %s" % (r.status_code, r.text[:200])}
    try:
        d = r.json()
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Bright Data."}

    protocolo = d.get("snapshot_id") or d.get("id")
    if not protocolo:
        return {"status": "error", "message": "A Bright Data nao devolveu protocolo."}
    try:
        linkedin_cache.registrar_busca(empresa, pais, cargo, limite, protocolo)
    except Exception:
        pass          # cache e conveniencia: nunca derruba a busca

    return {
        "status": "ok",
        "protocolo": protocolo,
        "empresa": empresa,
        "pais": pais.upper()[:2] if pais else "",
        "cargo": _norm(cargo),
        "limite": limite,
        "message": "Busca enviada. Costuma levar de 1 a 4 minutos.",
    }


def _pessoa(rec: dict[str, Any]) -> dict[str, Any]:
    emp = rec.get("current_company") or {}
    if not isinstance(emp, dict):
        emp = {}
    # `default_avatar` marca a foto generica do LinkedIn (aquele boneco cinza).
    # Sem essa distincao a tabela enche de bonecos iguais e parece defeito.
    generica = bool(rec.get("default_avatar"))
    return {
        "nome": rec.get("name") or "",
        "cargo": rec.get("position") or "",
        "empresa": rec.get("current_company_name") or emp.get("name") or "",
        "cidade": rec.get("city") or "",
        "pais": rec.get("country_code") or "",
        "url": rec.get("url") or rec.get("input_url") or "",
        "foto": "" if generica else (rec.get("avatar") or ""),
        "foto_generica": generica,
        "seguidores": rec.get("followers"),
        "formacao": rec.get("educations_details") or "",
        "sobre": (rec.get("about") or "")[:400],
    }


def _casa_empresa(pessoa: dict[str, Any], alvo: str) -> bool:
    """O operador `includes` da Bright Data casa por substring: buscar 'Movida'
    traz tambem 'Movidata Contabilidade'. Marcamos para o front separar."""
    emp = (pessoa.get("empresa") or "").lower()
    alvo = (alvo or "").lower().strip()
    if not alvo or not emp:
        return False
    # Casa se o alvo aparece como palavra inteira (evita Movida -> Movidata).
    return re.search(r"(^|\W)" + re.escape(alvo) + r"(\W|$)", emp) is not None


async def consultar(protocolo: str, empresa: str = "") -> dict[str, Any]:
    """Diz se o job terminou. status: building | ok | error."""
    if not enabled():
        return {"status": "unavailable", "pessoas": []}
    protocolo = (protocolo or "").strip()
    if not protocolo:
        return {"status": "error", "message": "Protocolo ausente.", "pessoas": []}

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.get("%s/%s/download?format=json" % (SNAP_URL, protocolo),
                              headers=_headers())
            if r.status_code in (202, 404) or (
                    r.status_code == 400 and "not ready" in r.text.lower()):
                # Ainda montando. Buscamos o estado so para mostrar algo util na tela.
                meta = await cli.get("%s/%s" % (SNAP_URL, protocolo), headers=_headers())
                estado = ""
                if meta.status_code < 400:
                    try:
                        estado = meta.json().get("status", "")
                    except Exception:
                        pass
                return {"status": "building", "estado": estado or "building",
                        "pessoas": [],
                        "message": "Ainda processando na Bright Data."}
            if r.status_code >= 400:
                return {"status": "error",
                        "message": "Bright Data %s: %s" % (r.status_code, r.text[:200]),
                        "pessoas": []}
            # LER OS BYTES, NAO O `.text`. A resposta vem em UTF-8 mas SEM charset
            # no Content-Type; o httpx entao adivinha Latin-1 e "São Paulo" chega
            # como "SÃ£o Paulo". `json.loads` sobre bytes assume UTF-8 e acerta.
            import json as _json
            try:
                bruto = _json.loads(r.content)
            except Exception:
                # Pode vir NDJSON (um objeto por linha).
                linhas = r.content.decode("utf-8", "replace").splitlines()
                bruto = [_json.loads(l) for l in linhas if l.strip()]
    except Exception as exc:
        return {"status": "error", "message": "Falha de conexao: %s" % str(exc)[:140],
                "pessoas": []}

    regs = bruto if isinstance(bruto, list) else (bruto or {}).get("data") or []
    pessoas = [_pessoa(x) for x in regs if isinstance(x, dict)]

    # GUARDA TUDO que chegou: ja foi pago, nao se paga de novo.
    novos = 0
    try:
        novos = linkedin_cache.salvar_perfis(pessoas, origem="api")
    except Exception:
        pass

    exatos, parecidos = [], []
    for p in pessoas:
        (exatos if _casa_empresa(p, empresa) else parecidos).append(p)

    return {
        "status": "ok",
        "total": len(pessoas),
        "pessoas": exatos + parecidos,
        "exatos": len(exatos),
        "parecidos": len(parecidos),
        "novos_no_cache": novos,
        "message": "" if pessoas else
                   "Nenhum perfil no dataset para esse filtro. Tente outra grafia "
                   "do nome da empresa (o dataset guarda o nome como esta no LinkedIn).",
    }
