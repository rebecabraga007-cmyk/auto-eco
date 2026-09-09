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
import time
from typing import Any

import httpx

import cargos
import cidades
import funcoes
import linkedin_cache

CHAVE = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
# DATASET ENRIQUECIDO (gd_me5ppx...), nao o padrao (gd_l1vikt...).
#
# Mesmo universo -- 43.213.633 brasileiros nos dois -- mas este traz o campo
# `email`, que o padrao nao tem. Medido em 08/set/2026: 2.181.331 brasileiros
# com e-mail (5,0%), e por empresa chega a 31% (Banrisul).
#
# Ele responde pelo SEARCH, que e o endpoint que usamos. NAO responde pelo
# Filter (404) -- o entitlement e por endpoint, e eu quase conclui que nao
# tinhamos acesso por ter testado so o Filter.
#
# O preco: 35 campos contra 46. Perde certifications, groups, organizations,
# patents, posts, projects, publications, recommendations e fsd_profile_id.
# MANTEM education e experience, que e de onde sai a faixa de nascimento --
# entao o desambiguador do funil continua inteiro.
DATASET = os.environ.get("BRIGHTDATA_PEOPLE_DATASET_ID",
                         "gd_me5ppxjr2ge6icjuh0").strip()
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
                # O CNPJ deduzido fica guardado junto: reconferir a cada
                # leitura seria refazer a mesma consulta pelo mesmo resultado.
                "cnpj": (antes["cnpj"] if "cnpj" in antes.keys() else "") or "",
                "cnpj_confianca": (antes["cnpj_confianca"]
                                   if "cnpj_confianca" in antes.keys() else "") or "nenhuma",
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

    # A Bright Data nao manda CNPJ (26 campos, nenhum fiscal). Deduz aqui pelo
    # dominio do site contra a Receita -- local, instantaneo e de graca. Quando
    # nao da para decidir, `cnpj` volta vazio de proposito: ver empresa_cnpj.
    try:
        import empresa_cnpj
        p = empresa_cnpj.resolver(registro=d)
        saida.update(cnpj=p["cnpj"], cnpj_confianca=p["confianca"],
                     cnpj_motivo=p["motivo"])
    except Exception:
        pass

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
                "cnpj": r.get("cnpj") or "",
                "cnpj_confianca": r.get("cnpj_confianca") or "nenhuma",
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


SEARCH_URL = "https://api.brightdata.com/datasets/search/"
SEARCH_TETO = 100          # medido: `size` acima de 100 devolve 400 (a doc diz 1.000)

# Termos que trazem quem decide. SÃO QUATRO PORQUE QUATRO É O TETO: medido que
# um grupo `or` com 5 condições devolve "HTTP 500 Filter validation failed".
# A escolha destes quatro veio de medir a cobertura na Magalu:
#   2 termos (diretor, head) -> 19 decisores  |  3 -> 21  |  4 -> 22
# "presidente" pega vice-presidente por ser `includes`; "diretor" pega diretora.
TERMOS_DECISOR = ["diretor", "head", "presidente", "ceo"]


def _grupo_decisores() -> dict[str, Any]:
    return {"operator": "or",
            "filters": [{"name": "position", "operator": "includes", "value": t}
                        for t in TERMOS_DECISOR]}


async def buscar_agora(empresa: str, pais: str = "BR", cargo: str = "",
                       limite: int = 0, cursor: Any = None,
                       decisores: bool = True) -> dict[str, Any]:
    """Busca SÍNCRONA pelo endpoint Search. Substitui o par disparar/consultar.

    Por que trocar: o Filter é um job de 40s a 4min com polling; o Search devolve
    inline em 2-3s. O PREÇO É O MESMO ($2,50 por 1.000 registros nos dois), então
    a troca não economiza dinheiro — economiza tempo e destrava paginação, que o
    Filter simplesmente não tem.

    A resposta traz `total_hits`, que é quantos existem no dataset inteiro (não
    quantos vieram). É o número que a tela mostra como "de N encontrados".

    Paginação: mande `cursor` com o `timestamp` do último resultado da página
    anterior. Ordenamos por timestamp justamente para o cursor ser estável.
    """
    if not enabled():
        return {"status": "unavailable",
                "message": "Bright Data nao configurada (BRIGHTDATA_API_KEY)."}
    empresa = _norm(empresa)
    limite = max(1, min(int(limite or LIMITE_PADRAO), SEARCH_TETO))

    condicoes = []
    if pais:
        condicoes.append({"name": "country_code", "operator": "=", "value": pais.upper()[:2]})
    if empresa:
        condicoes.append({"name": "current_company_name", "operator": "includes",
                          "value": empresa})
    if _norm(cargo):
        condicoes.append({"name": "position", "operator": "includes", "value": _norm(cargo)})
    elif decisores:
        # Só entra se NÃO houver cargo digitado: os dois juntos viriam como AND e
        # "gerente" + decisores devolveria vazio, que pareceria falha de busca.
        condicoes.append(_grupo_decisores())
    if not condicoes:
        return {"status": "error", "message": "Informe ao menos empresa ou cargo."}

    corpo: dict[str, Any] = {
        "size": limite,
        "filter": (condicoes[0] if len(condicoes) == 1
                   else {"operator": "and", "filters": condicoes}),
        "sort": [{"timestamp": "asc"}],
    }
    if cursor:
        corpo["search_after"] = cursor if isinstance(cursor, list) else [cursor]

    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(SEARCH_URL + DATASET, headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "message": "Falha na Bright Data: %s" % str(exc)[:140]}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "Bright Data %s: %s" % (r.status_code, r.text[:200])}

    import json as _json
    try:
        d = _json.loads(r.content)     # bytes: UTF-8 sem charset no cabeçalho
    except Exception:
        return {"status": "error", "message": "Resposta invalida da Bright Data."}

    brutos = d.get("hits") or []       # é `hits`, NÃO `data` como no Filter
    pessoas = [_pessoa(x) for x in brutos if isinstance(x, dict)]

    novos = 0
    try:
        novos = linkedin_cache.salvar_perfis(pessoas, origem="api")
    except Exception:
        pass

    exatos, parecidos = [], []
    for p in pessoas:
        (exatos if _casa_empresa(p, empresa) else parecidos).append(p)

    proximo = None
    if brutos and len(brutos) >= limite:
        proximo = brutos[-1].get("timestamp")

    return {
        "status": "ok",
        "fonte": "search",
        "so_decisores": bool(decisores and not _norm(cargo)),
        "total": len(pessoas),
        "total_no_dataset": d.get("total_hits"),
        "pessoas": exatos + parecidos,
        "exatos": len(exatos),
        "parecidos": len(parecidos),
        "novos_no_cache": novos,
        "cursor": proximo,
        "ms": d.get("took"),
        "message": "" if pessoas else
                   "Nenhum perfil com esse filtro. Tente outra grafia do nome da "
                   "empresa (o dataset guarda como está no LinkedIn).",
    }



# Na Bright Data o `or` aceita no maximo 4 condicoes (medido: 5 -> HTTP 500).
# Entao "varias empresas de uma vez" cabe em grupos de 4 por chamada.
EMPRESAS_POR_CHAMADA = 4


async def buscar_varias(empresas: list[str], pais: str = "BR", cargo: str = "",
                        limite_por_lote: int = 50,
                        decisores: bool = True) -> dict[str, Any]:
    """Funcionarios de VARIAS empresas. Cache primeiro, Bright Data para o resto.

    A Datastone resolve isso com uma query so, porque a base deles ja tem pessoa
    ligada a empresa por id (visto no `prospect.js`: `selected_companies` e uma
    LISTA). Aqui o cache faz o mesmo de graca; o que falta vai a Bright Data em
    grupos de 4, que e o teto do `or` de la.
    """
    empresas = [_norm(e) for e in (empresas or []) if _norm(e)]
    if not empresas:
        return {"status": "error", "message": "Informe ao menos uma empresa."}

    try:
        cobertura = linkedin_cache.cobertura_empresas(empresas, pais=pais)
    except Exception:
        cobertura = [{"empresa": e, "perfis": 0, "decisores": 0} for e in empresas]

    # So vai a API o que o cache nao cobre — decidido por DECISOR, nao por perfil:
    # ter 30 estagiarios de uma empresa nao ajuda quem procura quem decide.
    faltando = [c["empresa"] for c in cobertura
                if (c["decisores"] if decisores else c["perfis"]) < 3]

    buscadas, custo_registros = [], 0
    for i in range(0, len(faltando), EMPRESAS_POR_CHAMADA):
        lote = faltando[i:i + EMPRESAS_POR_CHAMADA]
        grupo_emp = {"operator": "or", "filters": [
            {"name": "current_company_name", "operator": "includes", "value": e}
            for e in lote]}
        condicoes = [grupo_emp]
        if pais:
            condicoes.append({"name": "country_code", "operator": "=",
                              "value": pais.upper()[:2]})
        # Empresas (or) + decisores (or) dentro de um and = 2 niveis, dentro do
        # limite de 3 da doc. Cargo digitado substitui o grupo de decisores.
        if _norm(cargo):
            condicoes.append({"name": "position", "operator": "includes",
                              "value": _norm(cargo)})
        elif decisores:
            condicoes.append(_grupo_decisores())

        corpo = {"size": max(1, min(limite_por_lote, SEARCH_TETO)),
                 "filter": {"operator": "and", "filters": condicoes},
                 "sort": [{"timestamp": "asc"}]}
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
                r = await cli.post(SEARCH_URL + DATASET, headers=_headers(), json=corpo)
        except Exception:
            continue
        if r.status_code >= 400:
            continue
        import json as _json
        try:
            d = _json.loads(r.content)
        except Exception:
            continue
        achados = [_pessoa(x) for x in (d.get("hits") or []) if isinstance(x, dict)]
        custo_registros += len(achados)
        # Cobrado e cobrado: guarda tudo, inclusive o parecido. Quem separa e a
        # leitura no fim -- descartar aqui seria pagar e jogar fora.
        try:
            linkedin_cache.salvar_perfis(achados, origem="api")
        except Exception:
            pass
        buscadas.extend(lote)

    # RECALCULA a cobertura: a de cima foi medida ANTES de buscar e diria
    # "0 decisores" mesmo depois de trazer 20 deles — numero que mente na tela.
    try:
        cobertura = linkedin_cache.cobertura_empresas(empresas, pais=pais)
    except Exception:
        pass

    # Le tudo do cache no fim: o que ja tinha + o que acabou de entrar, na mesma
    # ordem (decisor primeiro) e sem duplicata.
    try:
        pessoas = linkedin_cache.por_empresas(empresas, pais=pais, limite=500,
                                              senioridade="Decisores" if decisores else "")
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:150], "pessoas": []}

    exatas = sum(1 for p in pessoas if p.get("exata"))
    return {
        "status": "ok",
        "empresas_pedidas": len(empresas),
        "exatas": exatas,
        "parecidas": len(pessoas) - exatas,
        "empresas_buscadas_na_api": buscadas,
        "chamadas_api": (len(faltando) + EMPRESAS_POR_CHAMADA - 1) // EMPRESAS_POR_CHAMADA,
        "registros_cobrados": custo_registros,
        "custo_estimado_usd": round(custo_registros * 0.0025, 2),
        "cobertura": cobertura,
        "total": len(pessoas),
        "pessoas": pessoas,
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
    cargo = rec.get("position") or ""
    return {
        # Classifica aqui tambem (nao so na gravacao do cache): a tela precisa
        # saber quem e decisor no MESMO retorno da busca, nao na proxima.
        "departamento": cargos.departamento(cargo),
        "senioridade": cargos.senioridade(cargo),
        "nome": rec.get("name") or "",
        "cargo": rec.get("position") or "",
        "empresa": rec.get("current_company_name") or emp.get("name") or "",
        "cidade": rec.get("city") or "",
        "pais": rec.get("country_code") or "",
        "url": rec.get("url") or rec.get("input_url") or "",
        "foto": "" if generica else (rec.get("avatar") or ""),
        "foto_generica": generica,
        "seguidores": rec.get("followers"),
        # So existe no dataset enriquecido. E o unico identificador UNICO que
        # um perfil do LinkedIn carrega: nome tem homonimo, e-mail nao.
        "email": (rec.get("email") or "").strip().lower(),
        "formacao": rec.get("educations_details") or "",
        "sobre": (rec.get("about") or "")[:400],
        # Campos que o dataset já entregava e a gente descartava. Medido em 300
        # registros: first_name 99,7%, last_name 99,0%, experience 80,3%,
        # current_company_company_id 40,7%, languages 11,7%, certifications 8,0%.
        # Sem eles nao havia como oferecer os filtros de nome/sobrenome, tempo
        # na empresa e especialidades que a Datastone tem.
        "primeiro_nome": rec.get("first_name") or "",
        "sobrenome": rec.get("last_name") or "",
        "empresa_id": (rec.get("current_company_company_id")
                       or emp.get("company_id") or ""),
        "conexoes": rec.get("connections"),
        "idiomas": _titulos(rec.get("languages")),
        "certificacoes": _titulos(rec.get("certifications")),
        "desde_na_empresa": _desde_atual(rec, emp),
        # Os dois estimadores de IDADE. Nao existe data de nascimento no
        # LinkedIn, mas formatura e primeiro emprego cercam a faixa -- e faixa de
        # nascimento e o filtro gratuito que mais corta homonimo.
        "formatura_ano": _formatura(rec),
        "carreira_desde": _carreira_desde(rec),
    }


def _anos(txt: Any) -> list[int]:
    """Anos plausiveis de vida adulta num texto. Descarta 1899 e 2100."""
    return [int(a) for a in re.findall(r"\b(19[3-9]\d|20[0-4]\d)\b", str(txt or ""))]


def _formatura(rec: dict[str, Any]) -> int:
    """Ano da ULTIMA formacao concluida. 0 quando nao da pra afirmar.

    Usa `end_year` do array `education` (43% preenchido). Pega o maior: a
    formacao mais recente e a que melhor situa a idade. Curso em andamento
    (sem end_year) nao entra -- serviria para chutar, nao para afirmar.
    """
    edu = rec.get("education")
    if not isinstance(edu, list):
        return 0
    anos = []
    for e in edu:
        if not isinstance(e, dict):
            continue
        for campo in ("end_year", "endYear", "end_date"):
            anos += _anos(e.get(campo))
    return max(anos) if anos else 0


def _carreira_desde(rec: dict[str, Any]) -> int:
    """Ano da PRIMEIRA experiencia da carreira. 0 quando nao da.

    E o melhor estimador de idade do registro: primeiro emprego costuma ser
    entre 18 e 28 anos. `experience` vem 80% preenchido.
    """
    exp = rec.get("experience")
    if not isinstance(exp, list):
        return 0
    anos = []
    for x in exp:
        if not isinstance(x, dict):
            continue
        for campo in ("start_date", "startDate", "duration", "duration_short"):
            anos += _anos(x.get(campo))
        for pos in (x.get("positions") or []):
            if isinstance(pos, dict):
                for campo in ("start_date", "duration"):
                    anos += _anos(pos.get(campo))
    return min(anos) if anos else 0


def _titulos(v: Any) -> str:
    """Achata [{title: 'Inglês'}, ...] num texto buscável. Guardar o JSON cru
    obrigaria a tela a entender o formato deles; texto basta pro filtro."""
    if not isinstance(v, list):
        return ""
    saida = []
    for x in v[:12]:
        if isinstance(x, dict):
            t = x.get("title") or x.get("name") or ""
            if t:
                saida.append(str(t))
        elif x:
            saida.append(str(x))
    return " | ".join(saida)[:300]


_MESES = {"jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6, "jul": 7,
          "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12}


def _desde_atual(rec: dict[str, Any], emp: dict[str, Any]) -> str:
    """Quando a pessoa entrou na empresa ATUAL, como AAAAMM.

    O LinkedIn nao tem campo de data de entrada: esta dentro de `experience`,
    em texto ("Jan 2018 - Present"). Extraimos so da experiencia marcada como
    atual; se nenhuma estiver, devolvemos vazio em vez de chutar a primeira --
    "tempo na empresa" errado manda o vendedor abrir a conversa com data falsa.
    """
    for fonte in (emp.get("start_date"), rec.get("current_company_join_date")):
        m = re.search(r"(\d{4})[-/](\d{1,2})", str(fonte or ""))
        if m:
            return "%04d%02d" % (int(m.group(1)), int(m.group(2)))

    exp = rec.get("experience")
    if not isinstance(exp, list):
        return ""
    for x in exp:
        if not isinstance(x, dict):
            continue
        periodo = str(x.get("duration") or x.get("duration_short") or "")
        atual = ("present" in periodo.lower() or "atual" in periodo.lower()
                 or x.get("end_date") in (None, "", "Present"))
        if not atual:
            continue
        bruto = str(x.get("start_date") or periodo)
        m = re.search(r"(\d{4})[-/](\d{1,2})", bruto)
        if m:
            return "%04d%02d" % (int(m.group(1)), int(m.group(2)))
        m = re.search(r"([A-Za-z]{3})[a-z]*\.?\s+(\d{4})", bruto)
        if m and m.group(1).lower() in _MESES:
            return "%04d%02d" % (int(m.group(2)), _MESES[m.group(1).lower()])
        m = re.search(r"\b(19|20)(\d{2})\b", bruto)
        if m:
            return "%s%s01" % (m.group(1), m.group(2))
        return ""
    return ""


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


# --------------------------------------------------------------------------
# Busca por FILTRO na Bright Data (o "traz o que nao esta na base")
# --------------------------------------------------------------------------
# Ate aqui a unica forma de gastar era "traz os decisores da empresa X". Se a
# pessoa filtrava por cargo + UF + palavra-chave e o cache nao tinha, nao havia
# saida: a tela dizia "0 perfis" e ficava nisso. Isto traduz os filtros da tela
# para o DSL deles e busca de verdade.
#
# O QUE A API DELES ACEITA FILTRAR (sondado em 06/set, size=1 por sonda):
#   first_name =            OK   |  last_name = e includes   OK
#   city includes           OK   |  about includes           OK
#   educations_details inc. OK   |  languages includes       OK
#   followers >             OK   |  default_avatar =         OK
#   current_company_company_id =  OK  (25.091 para magazine-luiza)
#   position includes       OK   |  current_company_name includes  OK
# O QUE NAO ACEITA:
#   connections >  -> devolve 0 sempre (campo nao indexado)
#   experience     -> HTTP 500 ETIMEDOUT (array aninhado)
# Consequencia: "tempo na empresa" e "UF" NAO existem como filtro na origem.
# Tempo vem de `experience` e UF nao existe (so `city` em texto livre), entao
# esses dois so funcionam sobre o que ja esta no cache. A tela avisa.

# `city` do dataset guarda o nome COM acento ("Sao Paulo" devolveu 1 hit,
# "Sao" sem acento nao casa). Entao o filtro de cidade vai como o usuario
# digitou, sem passar pelo _norm que tira acento.
CIDADE_SEM_NORM = True

OR_TETO = 4                # medido: `or` com mais de 4 termos e rejeitado


def _grupo_or(campo: str, termos: list[str], operador: str = "includes"):
    """Grupo `or` de um campo. Corta em OR_TETO: acima disso a API rejeita a
    chamada inteira, e perder a busca e pior que perder o 5o termo."""
    termos = [t for t in termos if t][:OR_TETO]
    if not termos:
        return None
    if len(termos) == 1:
        return {"name": campo, "operator": operador, "value": termos[0]}
    return {"operator": "or",
            "filters": [{"name": campo, "operator": operador, "value": t}
                        for t in termos]}


async def buscar_por_filtro(pais: str = "BR", empresas: Any = None,
                            empresa_ids: Any = None, cargos_termos: Any = None,
                            nome: str = "", sobrenome: str = "",
                            cidade: str = "", palavras: Any = None,
                            min_seguidores: int = 0, so_com_foto: bool = False,
                            decisores: bool = False, limite: int = 50,
                            usuario: str = "", departamentos: Any = None,
                            so_com_email: bool = False) -> dict[str, Any]:
    """Busca no dataset inteiro da Bright Data com os filtros da tela.

    Cobra por registro entregue. Devolve `custo_usd` para a tela poder mostrar
    o valor DEPOIS da chamada, alem da estimativa que ela mostra antes.
    """
    if not enabled():
        return {"status": "unavailable", "pessoas": [],
                "message": "BRIGHTDATA_API_KEY nao configurada."}

    def _l(v):
        if v is None:
            return []
        if isinstance(v, str):
            v = re.split(r"[;,]", v)
        return [str(x).strip() for x in v if str(x).strip()]

    condicoes: list[dict[str, Any]] = []
    if pais:
        condicoes.append({"name": "country_code", "operator": "=",
                          "value": pais.upper()[:2]})

    # company_id e melhor que nome: e chave, nao texto. Quando a empresa foi
    # conferida pelo link, temos o id e a busca deixa de trazer homonimo.
    g = _grupo_or("current_company_company_id", _l(empresa_ids), "=")
    if g:
        condicoes.append(g)
    else:
        g = _grupo_or("current_company_name", _l(empresas))
        if g:
            condicoes.append(g)

    termos_cargo = _l(cargos_termos)

    # DEPARTAMENTO vira termo de `position` na PRÓPRIA consulta, não filtro
    # nosso depois. Decisão da Rebeca: mais barato e menos preciso.
    #
    # Mais barato porque a Bright Data cobra por registro ENTREGUE — filtrando
    # lá, não se paga por quem não interessa. Menos preciso porque o `or` deles
    # trava em 4 termos e uma área tem dezenas de radicais: "Comercial/Vendas"
    # vira `vend, comerci, represent, revend` e perde "closer", "account
    # executive", "BDR". Quem quiser a cauda longa usa o campo de cargo livre.
    #
    # `seniority` e `department` NÃO existem como filtro deles (testado: os
    # dois dão `unsupported filters`). São classificação nossa sobre `position`,
    # que tem 96% de cobertura — por isso o caminho é por `position`.
    for dep in _l(departamentos):
        termos_cargo += funcoes.termos_para_busca(dep)
    termos_cargo = list(dict.fromkeys(termos_cargo))
    if termos_cargo:
        condicoes.append(_grupo_or("position", [_norm(t) for t in termos_cargo]))
    elif decisores:
        condicoes.append(_grupo_decisores())

    if _norm(nome):
        condicoes.append({"name": "first_name", "operator": "includes",
                          "value": _norm(nome)})
    if _norm(sobrenome):
        condicoes.append({"name": "last_name", "operator": "includes",
                          "value": _norm(sobrenome)})
    if (cidade or "").strip():
        condicoes.append({"name": "city", "operator": "includes",
                          "value": cidade.strip()})
    g = _grupo_or("about", _l(palavras))
    if g:
        condicoes.append(g)
    if int(min_seguidores or 0) > 0:
        condicoes.append({"name": "followers", "operator": ">",
                          "value": int(min_seguidores)})
    if so_com_foto:
        condicoes.append({"name": "default_avatar", "operator": "=", "value": False})
    if so_com_email:
        # NASCE DESLIGADO. A Rebeca chegou a pedir ligado e voltou atrás, e o
        # motivo está no tamanho da conta: o universo cai de 43.213.633 para
        # 2.181.331 brasileiros — 5,05%. Ligar por padrão esconderia 95% da
        # base de quem nem sabe que o filtro existe.
        #
        # Por empresa a fatia é melhor,
        # porque quem tem e-mail é mais senior: Banrisul 31%, Nibo 13%,
        # Gerdau 12%, Magazine Luiza 7%. Entre decisores a média é ~10% e em
        # "head" chega a 29%, contra 2% em auxiliar.
        #
        # A troca é essa: menos gente, e cada uma acionável hoje sem depender
        # de identificar CPF nem de achar telefone.
        condicoes.append({"name": "email", "operator": "is_not_null"})

    # Sem nenhuma condicao alem do pais, a busca traria 21 milhoes de perfis
    # aleatorios e cobraria por todos. Melhor recusar.
    if len(condicoes) <= 1:
        return {"status": "error", "pessoas": [],
                "message": "Escolha ao menos um filtro (empresa, cargo, nome, "
                           "cidade ou palavra-chave) antes de buscar na Bright "
                           "Data - sem filtro ela cobraria por perfil aleatorio."}

    corpo = {"size": max(1, min(int(limite or 50), SEARCH_TETO)),
             "filter": {"operator": "and", "filters": condicoes},
             "sort": [{"timestamp": "asc"}]}

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(SEARCH_URL + DATASET, headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "pessoas": [],
                "message": "Bright Data nao respondeu: %s" % str(exc)[:120]}
    if r.status_code >= 400:
        return {"status": "error", "pessoas": [],
                "message": "Bright Data recusou o filtro (HTTP %s): %s"
                           % (r.status_code, r.text[:180])}
    import json as _json
    try:
        d = _json.loads(r.content)      # UTF-8 sem charset: r.text erra o acento
    except Exception:
        return {"status": "error", "pessoas": [], "message": "Resposta ilegivel."}

    pessoas = [_pessoa(x) for x in (d.get("hits") or []) if isinstance(x, dict)]
    custo = round(len(pessoas) * linkedin_cache.USD_POR_REGISTRO, 4)
    novos = 0
    try:
        novos = linkedin_cache.salvar_perfis(pessoas, origem="api")
    except Exception:
        pass
    linkedin_cache.registrar_gasto(
        "search", detalhe=(", ".join(_l(empresas) or _l(cargos_termos)
                                     or [nome or cidade or "filtro"]))[:200],
        registros=len(pessoas), custo_usd=custo, usuario=usuario)

    return {
        "status": "ok",
        "pessoas": pessoas,
        "total": len(pessoas),
        "total_no_dataset": d.get("total_hits"),
        "novos_no_cache": novos,
        "registros_cobrados": len(pessoas),
        "custo_usd": custo,
        "cursor": d.get("search_after"),
        "ms": int((time.time() - t0) * 1000),
    }


# =====================================================================
# EMPRESAS pelo dataset de empresas (gd_l1vikfnt1wgvvqz95w)
# =====================================================================
#
# Ate aqui empresa so chegava de dois jeitos, os dois de uma em uma: raspando
# a URL do LinkedIn (`empresa_por_url`) ou pelo autocomplete. A busca em massa
# de EMPRESA ia na Receita, que e gratis e instantanea mas nao sabe nada do
# LinkedIn -- nao sabe quantas pessoas a empresa tem la, nem o tipo de
# organizacao, nem quando ela diz que foi fundada.
#
# Sao exatamente os filtros que o B2B da Datastone tem e o nosso nao. Todos
# testados contra a API antes de virar codigo (8/set/2026):
#
#     website_simplified    =         funciona, e EXATO
#     employees_in_linkedin >         funciona, 100% de cobertura
#     organization_type     =         funciona
#     founded               >         funciona
#     industries            includes  funciona
#
# O que ficou de fora, e por que: `company_size` tem 56% de cobertura contra
# 100% de `employees_in_linkedin`; e `current_company_company_id` no dataset
# de PESSOAS nao casa com o `company_id` daqui -- medido em 5 empresas, todas
# devolveram 0 pessoas enquanto a busca por nome devolvia milhares. Sao
# espacos de id diferentes, apesar do nome igual.

# Faixas medidas no dataset em 8/set/2026 (universo BR: 1.356.875).
# Sao estas porque foram contadas uma a uma: faixa sem empresa dentro so
# ocupa espaco na tela.
FAIXAS_PORTE = [
    ("1 a 10", 0, 10, 808423),
    ("11 a 50", 10, 50, 218955),
    ("51 a 200", 50, 200, 51075),
    ("201 a 500", 200, 500, 11197),
    ("501 a 1.000", 500, 1000, 3620),
    ("1.001 a 5.000", 1000, 5000, 2732),
    ("5.001 a 10.000", 5000, 10000, 302),
    ("mais de 10.000", 10000, 0, 170),
]

# `Sole Proprietorship` ficou de fora de proposito: medido, tem ZERO empresas
# brasileiras. Filtro que nunca devolve nada e pior que filtro nenhum.
TIPOS_ORGANIZACAO = [
    ("Privately Held", "Capital fechado", 412081),
    ("Partnership", "Sociedade", 81315),
    ("Self-Employed", "Autonomo", 42382),
    ("Educational", "Educacional", 20091),
    ("Nonprofit", "Sem fins lucrativos", 18470),
    ("Public Company", "Capital aberto", 8406),
    ("Government Agency", "Orgao publico", 3800),
]


def catalogo_empresas() -> dict[str, Any]:
    """Opcoes de filtro de empresa, com quantas empresas ha em cada uma.

    A contagem vai junto porque muda a decisao de quem filtra: escolher
    "5.001 a 10.000" sabendo que sao 302 empresas no Brasil inteiro e uma
    escolha; escolher sem saber e uma surpresa depois.
    """
    return {
        "status": "ok",
        "portes": [{"id": i, "rotulo": r, "min": a, "max": b, "quantas": q}
                   for i, (r, a, b, q) in enumerate(FAIXAS_PORTE)],
        "tipos": [{"valor": v, "rotulo": r, "quantas": q}
                  for v, r, q in TIPOS_ORGANIZACAO],
        "universo_br": 1356875,
    }


def _empresa(rec: dict[str, Any]) -> dict[str, Any]:
    d = {
        "nome": rec.get("name") or "",
        "url": rec.get("url") or "",
        "company_id": str(rec.get("company_id") or ""),
        "funcionarios_linkedin": rec.get("employees_in_linkedin"),
        "setor": rec.get("industries") or "",
        "sede": rec.get("headquarters") or "",
        "site": rec.get("website_simplified") or rec.get("website") or "",
        "tipo": rec.get("organization_type") or "",
        "fundada": rec.get("founded") or "",
        "seguidores": rec.get("followers"),
        "pais": rec.get("country_code") or "",
    }
    # O CNPJ nao vem da Bright Data. E deduzido aqui, de graca, contra a
    # Receita; quando nao da para decidir entre empresas diferentes volta
    # vazio de proposito. Ver empresa_cnpj.
    try:
        import empresa_cnpj
        p = empresa_cnpj.resolver(registro=rec)
        d["cnpj"] = p["cnpj"]
        d["cnpj_confianca"] = p["confianca"]
        d["cnpj_motivo"] = p["motivo"]
    except Exception:
        d["cnpj"], d["cnpj_confianca"], d["cnpj_motivo"] = "", "nenhuma", ""
    return d


def _nome_do_estado(uf: str) -> str:
    """"SC" -> "Santa Catarina", que e como o LinkedIn escreve.

    O filtro de local do dataset e `headquarters includes`, e la o estado vem
    por extenso. Mandar a sigla nao casa quase nada: medido, "Santa Catarina"
    devolve 42.809 empresas.

    O mapa e o de `cidades.UF_POR_NOME`, invertido -- reaproveitado em vez de
    redigitado para as duas telas nao divergirem com o tempo.
    """
    u = (uf or "").strip().upper()[:2]
    if not u:
        return ""
    for nome, sigla in cidades.UF_POR_NOME.items():
        # so as entradas em portugues; as em ingles ("STATE OF ...") existem
        # para LER o que o LinkedIn escreve, nao para escrever a consulta
        if sigla == u and not nome.startswith("STATE OF") and " DISTRICT" not in nome:
            return nome.title()
    return ""


async def buscar_empresas_por_filtro(
        pais: str = "BR", nomes: Any = None, sites: Any = None,
        porte_min: int = 0, tipos: Any = None, fundada_apos: int = 0,
        setores: Any = None, so_com_cnpj: bool = False,
        ufs: Any = None, cidade: str = "",
        limite: int = 25, usuario: str = "") -> dict[str, Any]:
    """Busca de EMPRESAS no dataset da Bright Data.

    `limite` vira `size` e e sempre enviado. Isso nao e detalhe de estilo:
    MEDIDO em 8/set/2026, chamada SEM `size` devolve tudo que casa e cobra
    por tudo (16 de 16 e 13 de 13 nos dois testes). Nao existe teto padrao do
    lado deles -- o teto tem que ser nosso.

    `so_com_cnpj` filtra DEPOIS de receber, e nao ha como ser diferente: o
    CNPJ e deduzido aqui e a Bright Data nao sabe o que e isso. Ou seja, ele
    reduz o que aparece na tela e NAO o que foi cobrado. A resposta separa
    `registros_cobrados` de `total` justamente para a tela poder dizer isso.
    """
    if not enabled():
        return {"status": "unavailable", "empresas": [],
                "message": "BRIGHTDATA_API_KEY nao configurada."}

    def _l(v):
        if v is None:
            return []
        if isinstance(v, str):
            v = re.split(r"[;,]", v)
        return [str(x).strip() for x in v if str(x).strip()]

    cond: list[dict[str, Any]] = []
    if pais:
        cond.append({"name": "country_code", "operator": "=",
                     "value": pais.upper()[:2]})

    # Site e a melhor entrada daqui: `=` exato, sem homonimo. E o caminho de
    # volta do CNPJ para o LinkedIn, porque o dominio sai do e-mail da Receita.
    g = _grupo_or("website_simplified", [s.lower() for s in _l(sites)], "=")
    if g:
        cond.append(g)
    g = _grupo_or("name", _l(nomes))
    if g:
        cond.append(g)
    g = _grupo_or("industries", _l(setores))
    if g:
        cond.append(g)
    g = _grupo_or("organization_type", _l(tipos), "=")
    if g:
        cond.append(g)
    if int(porte_min or 0) > 0:
        cond.append({"name": "employees_in_linkedin", "operator": ">",
                     "value": int(porte_min)})
    if int(fundada_apos or 0) > 0:
        cond.append({"name": "founded", "operator": ">",
                     "value": int(fundada_apos)})

    # LOCAL. Sem isto a busca do LinkedIn ignora a UF que a pessoa escolheu e
    # a lista mistura empresa de SC com empresa de qualquer lugar -- foi o que
    # aconteceu no primeiro teste da lista unificada, e o pior e que parecia
    # certo na tela. `headquarters` e a SEDE; `locations` traria filial de
    # empresa sediada longe, que nao e o que "empresa de SC" significa.
    estados = [n for n in (_nome_do_estado(u) for u in _l(ufs)) if n]
    g = _grupo_or("headquarters", estados)
    if g:
        cond.append(g)
    if (cidade or "").strip():
        cond.append({"name": "headquarters", "operator": "includes",
                     "value": cidade.strip()})

    if len(cond) <= 1:
        return {"status": "error", "empresas": [],
                "message": "Escolha ao menos um filtro (site, nome, setor, "
                           "porte, tipo ou fundacao). Sem filtro a busca "
                           "traria 1,3 milhao de empresas e cobraria todas."}

    corpo = {"size": max(1, min(int(limite or 25), SEARCH_TETO)),
             "filter": {"operator": "and", "filters": cond},
             "sort": [{"timestamp": "asc"}]}

    t0 = time.time()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(SEARCH_URL + DATASET_EMPRESA,
                               headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "empresas": [],
                "message": "Bright Data nao respondeu: %s" % str(exc)[:120]}
    if r.status_code >= 400:
        return {"status": "error", "empresas": [],
                "message": "Bright Data recusou o filtro (HTTP %s): %s"
                           % (r.status_code, r.text[:180])}
    import json as _json
    try:
        d = _json.loads(r.content)
    except Exception:
        return {"status": "error", "empresas": [],
                "message": "Resposta ilegivel."}

    brutas = [_empresa(x) for x in (d.get("hits") or []) if isinstance(x, dict)]
    cobrados = len(brutas)
    custo = round(cobrados * linkedin_cache.USD_POR_REGISTRO, 4)
    empresas = [e for e in brutas if e.get("cnpj")] if so_com_cnpj else brutas

    for e in brutas:
        try:
            linkedin_cache.salvar_empresa(
                {"url": e["url"], "nome": e["nome"],
                 "company_id": e["company_id"],
                 "funcionarios_linkedin": e["funcionarios_linkedin"],
                 "setor": e["setor"], "sede": e["sede"], "site": e["site"],
                 "pais": e["pais"], "cnpj": e.get("cnpj"),
                 "cnpj_confianca": e.get("cnpj_confianca")})
        except Exception:
            pass
    linkedin_cache.registrar_gasto(
        "search-empresas",
        detalhe=(", ".join(_l(nomes) or _l(sites) or ["filtro"]))[:200],
        registros=cobrados, custo_usd=custo, usuario=usuario)

    com_cnpj = sum(1 for e in brutas if e.get("cnpj"))
    return {
        "status": "ok",
        "empresas": empresas,
        "total": len(empresas),
        "total_no_dataset": d.get("total_hits"),
        "com_cnpj": com_cnpj,
        "sem_cnpj": cobrados - com_cnpj,
        "registros_cobrados": cobrados,
        "custo_usd": custo,
        "cursor": d.get("search_after"),
        "ms": int((time.time() - t0) * 1000),
    }


async def nome_no_linkedin(cnpj: str = "", site: str = "") -> dict[str, Any]:
    """Como a empresa se chama NO LINKEDIN, partindo do CNPJ.

    Existe por causa de um erro concreto: a busca de decisores procurava pela
    RAZAO SOCIAL, e razao social quase nunca e o nome do LinkedIn. O CNPJ
    17.688.085/0001-45 e "L3 SOLUCOES EM TECNOLOGIA LTDA" na Receita e "Even3"
    no LinkedIn -- procurar por "L3" devolvia zero decisores numa empresa com
    45 pessoas la dentro.

    O caminho e o mesmo da ponte, invertido:

        CNPJ -> dominio do e-mail (Receita, local, gratis)
             -> empresa por `website_simplified` = dominio (EXATO)
             -> nome como o LinkedIn escreve

    Custa 1 registro (US$ 0,0025). Vale: sem ele, a busca de pessoas seguinte
    -- que custa ate 100 registros -- procura pelo nome errado e traz zero,
    ou pior, traz gente de outra empresa com nome parecido.
    """
    if not enabled():
        return {"status": "unavailable"}
    dom = ""
    if site:
        try:
            import empresa_cnpj
            dom = empresa_cnpj.dominio(site)
        except Exception:
            dom = ""
    if not dom and cnpj:
        try:
            import empresa_cnpj
            dom = empresa_cnpj.dominio_do_cnpj(cnpj)
        except Exception:
            dom = ""
    if not dom:
        return {"status": "not_found", "motivo": "empresa sem dominio proprio"}

    # ORDENADO POR TAMANHO, e isso nao e detalhe. Um dominio corporativo
    # costuma ter varias paginas no LinkedIn -- selbetti.com.br tem 5 --  e
    # sem ordenacao a API devolve uma qualquer. Medido: vinha "Selbetti Retail
    # Experience" com 30 pessoas no lugar de "Selbetti Tecnologia" com 1.977.
    # A maior e a empresa; as outras sao braco, marca ou unidade.
    # Custa o mesmo 1 registro.
    corpo = {"size": 1,
             "filter": {"operator": "and", "filters": [
                 {"name": "country_code", "operator": "=", "value": "BR"},
                 {"name": "website_simplified", "operator": "=", "value": dom}]},
             "sort": [{"employees_in_linkedin": "desc"}]}
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as cli:
            r = await cli.post(SEARCH_URL + DATASET_EMPRESA,
                               headers=_headers(), json=corpo)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:120]}
    if r.status_code >= 400:
        return {"status": "error",
                "message": "HTTP %s %s" % (r.status_code, r.text[:120])}
    import json as _json
    try:
        d = _json.loads(r.content)
    except Exception:
        return {"status": "error", "message": "resposta ilegivel"}
    hits = d.get("hits") or []
    if not hits:
        return {"status": "not_found", "dominio": dom,
                "motivo": "dominio %s nao tem pagina no LinkedIn" % dom}
    h = hits[0]
    try:
        linkedin_cache.registrar_gasto(
            "empresa-por-site", detalhe=dom, registros=1,
            custo_usd=linkedin_cache.USD_POR_REGISTRO, usuario="")
    except Exception:
        pass
    return {"status": "ok", "dominio": dom,
            "nome": h.get("name") or "",
            "company_id": str(h.get("company_id") or ""),
            "funcionarios_linkedin": h.get("employees_in_linkedin"),
            "url": h.get("url") or "",
            "custo_usd": linkedin_cache.USD_POR_REGISTRO}
