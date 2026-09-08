# -*- coding: utf-8 -*-
"""O funil que liga um perfil do LinkedIn a um CPF, na ordem definitiva.

Até agora este fluxo só existia em scripts de teste no /tmp, cada um com uma
ordem ligeiramente diferente — foi assim que uma rodada acabou medindo 18,2%
enquanto outra media 54,8%, sem que nada no código dissesse qual era a certa.
Este módulo é a versão única.

A ORDEM, e o princípio que a define
-----------------------------------
Não é "grátis antes de pago". É POR EMPRESA ANTES DE POR PESSOA. Duas consultas
resolvidas no CNPJ cobrem a empresa inteira; a mesma resposta obtida nome a
nome custaria trinta vezes mais. Numa empresa com 12 perfis:

    decisores + RAIS, por CNPJ ......  2 consultas  R$ 0,24  cobre os 12
    busca por nome, um a um ......... 60 consultas  R$ 7,14  um por vez

  02  porte da empresa      local   escolhe a filial e o teto de gasto
  03  possíveis decisores   POR EMPRESA, R$ 0,24 na 1ª vez, depois cache
  04  RAIS / CAGED          POR EMPRESA, gateway FDX
  ---------------------------------------------------------------------
  05  JBR                   local   homônimos no país + data de nascimento
  06  WorkAPI nome          grátis  CPF inteiro + endereço + nascimento
  07  MK integrax-cpf       grátis  confirma cidade, telefone, profissão
  08  Assertiva nome+cidade PAGO    só para quem sobrou
  09  Assertiva consulta_cpf PAGO   a prova: CNPJ do empregador e CBO
  10  decidir()                     escolhe, ou devolve para o operador

O QUE NÃO ESTÁ AQUI, de propósito
---------------------------------
A porta de cargo (`funcoes.eh_cargo`). Ela foi ligada com base numa projeção
minha de +8,2 pp e, medida nos 166 perfis, entregou +1,7 pp de razão CUSTANDO
14 CPFs — o grupo que ela barra resolve a 46,2%, não a 30%. Decisão da Rebeca
em 08/09/2026: fica fora. O detalhe está no docstring de `funcoes.eh_cargo`.
"""
from __future__ import annotations

import asyncio
import re
import time
from typing import Any

import assertiva
import funcoes
import identidade as I
import linkedin_cache
import mkbuscas
import rais
import workapi

PRECO_ASSERTIVA = 0.119

# Um perfil não vale gasto ilimitado. O teto por pessoa sai da estratégia de
# porte; este é o teto do LOTE inteiro, para uma tela nunca torrar o orçamento
# num clique.
TETO_LOTE_PADRAO = 25.0


class Gasto:
    """Contador de consultas pagas, com teto. Passa junto por todo o funil.

    Existe como objeto e não como variável global porque duas buscas podem
    rodar ao mesmo tempo, e um contador global faria uma ver o gasto da outra
    e parar cedo.
    """

    def __init__(self, teto_brl: float = TETO_LOTE_PADRAO):
        self.teto = float(teto_brl)
        self.assertiva = 0
        self.mk = 0
        self.workapi = 0
        self.rais = 0

    @property
    def brl(self) -> float:
        return round(self.assertiva * PRECO_ASSERTIVA, 2)

    def estourou(self, margem: int = 1) -> bool:
        """True quando mais `margem` consultas passariam do teto."""
        return (self.assertiva + margem) * PRECO_ASSERTIVA > self.teto

    def resumo(self) -> dict[str, Any]:
        return {"assertiva": self.assertiva, "mk": self.mk,
                "workapi": self.workapi, "rais": self.rais,
                "brl": self.brl, "teto_brl": self.teto}


def _cpf(v: Any) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d if len(d) == 11 else ""


def _nome_contido(procurado: str, achado: str) -> bool:
    """Todo token do nome do LinkedIn aparece no nome do cadastro.

    Não é igualdade: o LinkedIn esconde nome do meio em 53% dos perfis, então
    "Ana Silva" tem que casar com "Ana Beatriz Silva". Mas é contenção nos DOIS
    sentidos do que importa — "Ana Silva" NÃO pode casar com "Ana Silvana",
    que é o que um `startswith` faria.
    """
    a = [t for t in I._norm(procurado).split() if len(t) > 1]
    b = set(I._norm(achado).split())
    return bool(a) and all(t in b for t in a)


# ===========================================================================
# ETAPAS POR EMPRESA — rodam UMA VEZ e cobrem todo mundo daquele CNPJ
# ===========================================================================
class Empresa:
    """O contexto de uma empresa: CNPJ, estratégia e as listas por CNPJ.

    Guardar isto num objeto é o que impede o erro caro: chamar `decisores` uma
    vez por pessoa em vez de uma vez por empresa. A resposta é idêntica para
    todo mundo do mesmo CNPJ.
    """

    def __init__(self, nome: str, cidade: str = "", uf: str = ""):
        self.nome = nome
        self.cidade = cidade
        self.uf = uf
        self.cnpj = ""
        self.razao = ""
        self.aviso = ""
        self.estrategia: dict[str, Any] = {}
        self.decisores: list[dict] = []
        self.vinculos: list[dict] = []
        self.preparada = False

    async def preparar(self, gasto: Gasto, usar_pagas: bool = True) -> None:
        r = I.cnpj_com_aviso(self.nome, self.uf)
        self.cnpj, self.razao, self.aviso = r["cnpj"], r["razao"], r["aviso"]
        self.estrategia = I.estrategia(self.cnpj, self.cidade, self.uf,
                                       nome_empresa=self.nome)
        if not self.cnpj or not usar_pagas:
            self.preparada = True
            return

        # ETAPA 03 — possíveis decisores. Duas consultas na primeira vez.
        if not gasto.estourou(margem=2):
            d = await assertiva.possiveis_decisores(self.cnpj)
            gasto.assertiva += 2
            # O caminho é data.resposta.possiveisDecisores. Verificado contra a
            # resposta real; chutar `decisores`/`pessoas` devolvia lista vazia
            # em silêncio, o que faria a etapa mais barata do funil parecer
            # inútil sem dar um único erro.
            self.decisores = [
                {"nome": x.get("nome") or "", "cpf": _cpf(x.get("cpf")),
                 "cargo": x.get("cargo") or "",
                 "nascimento": x.get("dataNascimento") or ""}
                for x in ((((d.get("data") or {}).get("resposta") or {})
                           .get("possiveisDecisores")) or [])
                if _cpf(x.get("cpf"))]

        # ETAPA 04 — RAIS. Gateway irregular, mas aqui isso quase não custa:
        # o que ele achar é lucro, o que ele errar cai nas etapas seguintes.
        try:
            v = await rais.vinculos_cnpj(self.cnpj)
            gasto.rais += 1
            self.vinculos = [
                {"nome": x.get("nome") or "", "cpf": _cpf(x.get("cpf"))}
                for x in (v.get("vinculos") or []) if _cpf(x.get("cpf"))]
        except Exception:
            self.vinculos = []
        self.preparada = True

    def por_lista(self, nome: str) -> tuple[str, str]:
        """Procura o nome nas duas listas por CNPJ. Grátis, já estão em memória."""
        for etapa, lista in (("decisores", self.decisores),
                             ("rais", self.vinculos)):
            achados = [x for x in lista if _nome_contido(nome, x["nome"])]
            if len(achados) == 1:
                return etapa, achados[0]["cpf"]
        return "", ""


# ===========================================================================
# ETAPAS POR PESSOA
# ===========================================================================
async def _pela_workapi(nome: str, cidade: str, uf: str,
                        gasto: Gasto) -> list[dict[str, Any]]:
    """Candidatos com CPF e endereço, de graça. Recorta por cidade, senão UF."""
    r = await workapi.nome_search(nome, limit=60)
    gasto.workapi += 1
    if r.get("status") != "ok":
        return []
    ps = [p for p in (r.get("pessoas") or [])
          if _cpf(p.get("cpf")) and _nome_contido(nome, p.get("nome"))]
    if not ps:
        return []
    na_cidade = [p for p in ps
                 if I._norm(p["endereco"]["cidade"]) == I._norm(cidade)]
    na_uf = [p for p in ps
             if (p["endereco"]["uf"] or "").upper() == (uf or "").upper()]
    return na_cidade or na_uf or []


async def _pela_assertiva(nome: str, cidade: str, uf: str,
                          gasto: Gasto) -> tuple[list[dict], bool, bool]:
    """Busca paga por nome. Devolve (candidatos, foi_por_uf, truncou)."""
    async def busca(params):
        r = await assertiva._get("/localize/v3/nome-endereco", params)
        gasto.assertiva += 1
        if r.get("status") != "ok":
            return []
        return ((r.get("data") or {}).get("resposta") or {}).get("pessoaFisica") or []

    if gasto.estourou():
        return [], False, False
    pf = await busca({"buscarPor": "pessoas", "nomeOuRazaoSocial": nome,
                      "uf": uf, "cidade": (cidade or "").title(),
                      "idFinalidade": 5, "limite": 50})
    por_uf = False
    if not pf and uf and not gasto.estourou():
        pf = await busca({"buscarPor": "pessoas", "nomeOuRazaoSocial": nome,
                          "uf": uf, "idFinalidade": 5, "limite": 50})
        por_uf = bool(pf)
    # Exatamente 50 = truncado E enviesado pelo alfabeto: a pessoa pode estar
    # depois do corte, então não se escolhe ninguém.
    return pf, por_uf, len(pf) >= I.TETO_ASSERTIVA


async def resolver_pessoa(perfil: dict[str, Any], emp: Empresa,
                          gasto: Gasto) -> dict[str, Any]:
    """Um perfil do LinkedIn -> um CPF, ou o motivo de não ter dado."""
    t0 = time.time()
    nome = (perfil.get("nome") or "").strip()
    cargo = perfil.get("cargo") or ""
    cid = I.cidade_do_linkedin(perfil.get("cidade"))
    uf = linkedin_cache.uf_de(perfil.get("cidade") or "") or emp.uf

    def saida(situacao, cpf="", confianca=0, **extra):
        return {"nome": nome, "empresa": emp.nome, "cargo": cargo,
                "cidade": cid, "uf": uf, "cpf": cpf, "situacao": situacao,
                "confianca": confianca, "ms": int((time.time() - t0) * 1000),
                **extra}

    if len([t for t in I._norm(nome).split() if len(t) > 1]) < 2:
        return saida("nome_incompleto")

    # ETAPAS 03/04 — as listas por CNPJ, já em memória. Grátis.
    etapa, cpf = emp.por_lista(nome)
    if cpf:
        return saida("resolvido_por_" + etapa, cpf, 90,
                     porque="nome único na lista de %s do CNPJ" % etapa)

    # ETAPA 05 — faixa de nascimento, para filtrar candidatos depois
    de, ate = linkedin_cache.faixa_nascimento(
        int(perfil.get("formatura_ano") or 0),
        int(perfil.get("carreira_desde") or 0))

    # ETAPA 06 — WorkAPI, grátis
    livres = await _pela_workapi(nome, cid, uf, gasto)
    if de:
        f = [p for p in livres
             if linkedin_cache.dentro_da_faixa(p.get("data_nascimento"), de, ate)]
        if f:
            livres = f
    if len(livres) == 1:
        d = I.decidir([{"cpf": _cpf(livres[0]["cpf"]), "nome": livres[0]["nome"],
                        "forca": 0, "elimina": False}], concorrentes=1)
        return saida("resolvido_workapi", d["cpf"], d["confianca"],
                     porque=d.get("porque", ""), custo_brl=0.0)

    if not emp.estrategia.get("pode_buscar", True):
        return saida("precisa_escolher_filial", confianca=0,
                     porque=emp.estrategia.get("porque", ""),
                     escolher_entre=emp.estrategia.get("escolher_entre") or [])

    # ETAPA 08 — busca paga
    pf, por_uf, truncou = await _pela_assertiva(nome, cid, uf, gasto)
    if truncou:
        return saida("truncado_em_50", porque=(
            "a Assertiva devolve no máximo 50, em ordem alfabética e sem "
            "paginação — a pessoa pode estar depois do corte"))
    if not pf:
        return saida("nao_achado")
    if de:
        f = [x for x in pf
             if linkedin_cache.dentro_da_faixa(x.get("dataNascimento"), de, ate)]
        if f:
            pf = f
    if len(pf) > I.MAX_CANDIDATOS:
        return saida("candidatos_demais", porque=(
            "%d candidatos — acima de %d o custo cresce linear e a chance de "
            "acerto não" % (len(pf), I.MAX_CANDIDATOS)))

    # ETAPA 09 — a prova, candidato a candidato
    alvo = {"cnpj_empresa": emp.cnpj, "empresa": emp.nome, "cargo": cargo,
            "cidade": cid, "ddd": I.ddd_da_cidade(cid, uf)}
    teto = int(emp.estrategia.get("teto_pago") or I.MAX_PAGO)
    avaliados = []
    for c in pf[:teto]:
        if gasto.estourou():
            break
        d = _cpf(c.get("cpf"))
        if not d:
            continue
        a = await assertiva.consulta_cpf(d)
        gasto.assertiva += 1
        if a.get("status") != "ok":
            continue
        av = I.avaliar(I.sinais_do_cpf(a), alvo, cidade_ja_filtrada=not por_uf)
        avaliados.append({"cpf": d, "nome": c.get("nome") or "", **av})

    if not avaliados:
        return saida("sem_resposta_paga")

    # ETAPA 10 — a decisão. O limiar só vale contra concorrente.
    d = I.decidir(avaliados, concorrentes=len(pf))
    return saida(d["situacao"], d.get("cpf", ""), d.get("confianca", 0),
                 porque=d.get("porque", ""), motivos=d.get("motivos") or [],
                 candidatos=len(pf))


# ===========================================================================
# ORQUESTRAÇÃO
# ===========================================================================
async def resolver_lote(perfis: list[dict[str, Any]], cidade: str = "",
                        uf: str = "", teto_brl: float = TETO_LOTE_PADRAO,
                        usar_pagas: bool = True) -> dict[str, Any]:
    """Roda o funil num lote, agrupando por empresa para não repetir o CNPJ."""
    gasto = Gasto(teto_brl)
    t0 = time.time()

    porempresa: dict[str, list] = {}
    for p in perfis:
        porempresa.setdefault((p.get("empresa") or "").strip(), []).append(p)

    saidas, empresas = [], {}
    for nome_emp, lista in porempresa.items():
        emp = Empresa(nome_emp, cidade, uf)
        await emp.preparar(gasto, usar_pagas=usar_pagas)
        empresas[nome_emp] = {
            "cnpj": emp.cnpj, "razao": emp.razao, "aviso": emp.aviso,
            "faixa": emp.estrategia.get("faixa"),
            "modo": emp.estrategia.get("modo"),
            "pode_buscar": emp.estrategia.get("pode_buscar", True),
            "porque": emp.estrategia.get("porque", ""),
            "decisores": len(emp.decisores), "rais": len(emp.vinculos),
        }
        for p in lista:
            if gasto.estourou():
                saidas.append({"nome": p.get("nome"), "empresa": nome_emp,
                               "situacao": "teto_de_gasto", "cpf": "",
                               "confianca": 0})
                continue
            saidas.append(await resolver_pessoa(p, emp, gasto))

    com_cpf = sum(1 for s in saidas if s.get("cpf"))
    return {
        "pessoas": saidas, "empresas": empresas,
        "total": len(saidas), "com_cpf": com_cpf,
        "taxa": round(100.0 * com_cpf / max(len(saidas), 1), 1),
        "custo": gasto.resumo(),
        "custo_por_cpf": round(gasto.brl / com_cpf, 2) if com_cpf else None,
        "segundos": round(time.time() - t0, 1),
    }


# ===========================================================================
# DOSSIÊ — o que a tela mostra depois que o CPF saiu
# ===========================================================================
# Ordem dos telefones. O objetivo do funil inteiro é ALGUÉM ATENDER, então o
# critério não é "o dado mais completo", é "o número com maior chance de tocar
# na mão da pessoa certa hoje". Nesta ordem:
#
#   1. não perturbe    -> vai para o fim, sempre. É risco jurídico, não ruído.
#   2. relação Direto  -> o número é do titular; "terceiro" é a mãe, o vizinho
#   3. WhatsApp        -> canal que o SDR usa de verdade
#   4. celular         -> 11 dígitos; fixo raramente atende em prospecção B2B
#   5. contato recente -> `ultimoContato` da Assertiva, em meses
#   6. priority        -> o palpite deles, como último desempate
def _ordem_telefone(t: dict[str, Any]) -> tuple:
    digitos = re.sub(r"\D", "", str(t.get("telefone") or ""))
    celular = len(digitos) == 11 and digitos[2:3] == "9"
    meses = t.get("meses_sem_contato")
    return (
        1 if t.get("nao_perturbe") else 0,
        0 if str(t.get("relacao") or "").upper().startswith("DIRET") else 1,
        0 if t.get("whatsapp") else 1,
        0 if celular else 1,
        999 if meses is None else meses,
        t.get("priority") if isinstance(t.get("priority"), int) else 99,
    )


def _rotulo_telefone(t: dict[str, Any]) -> str:
    """Uma frase curta dizendo por que este número está nesta posição."""
    p = []
    if t.get("nao_perturbe"):
        p.append("NÃO PERTURBE")
    if t.get("whatsapp"):
        p.append("WhatsApp")
    rel = str(t.get("relacao") or "")
    if rel:
        p.append("do titular" if rel.upper().startswith("DIRET") else rel.lower())
    m = t.get("meses_sem_contato")
    if m == 0:
        p.append("contato nos últimos dias")
    elif isinstance(m, int):
        p.append("contato há %d %s" % (m, "mês" if m == 1 else "meses"))
    if t.get("hotphone"):
        p.append("linha ativa")
    return " · ".join(p)


async def dossie_pessoa(cpf: str, gasto: Gasto | None = None) -> dict[str, Any]:
    """Os dados da pessoa, com o telefone na frente. UMA consulta paga.

    Se a consulta desse CPF já rolou nesta execução, a Assertiva devolve do
    cache em memória do módulo `assertiva` e não cobra de novo.
    """
    d = _cpf(cpf)
    if not d:
        return {"status": "error", "message": "CPF inválido."}
    g = gasto or Gasto()
    if g.estourou():
        return {"status": "teto_de_gasto", "cpf": d}
    r = await assertiva.consulta_cpf(d)
    g.assertiva += 1
    if r.get("status") != "ok":
        return {"status": r.get("status") or "error", "cpf": d,
                "message": r.get("message") or "A Assertiva não devolveu dados."}

    resp = (r.get("data") or {}).get("resposta") or {}
    s = I.sinais_do_cpf(r)
    tels = sorted(s["telefones"], key=_ordem_telefone)
    for t in tels:
        t["porque"] = _rotulo_telefone(t)

    vinculos = sorted(s["vinculos"], key=lambda v: str(v.get("desde") or ""),
                      reverse=True)
    for v in vinculos:
        v["areas"] = sorted(funcoes.areas(v["cargo"]) | funcoes.areas(v["setor"]))

    # Nome, nascimento e situação NÃO ficam no topo da resposta — moram em
    # `dadosCadastrais`. Lê-los do topo devolvia string vazia em silêncio, e o
    # painel aparecia sem o nome da pessoa que ele acabou de identificar.
    dc = resp.get("dadosCadastrais") or {}

    def sim(v) -> bool:
        return str(v).strip().lower() in ("true", "1", "sim")

    return {
        "status": "ok", "cpf": d,
        "nome": dc.get("nome") or "",
        "nascimento": dc.get("dataNascimento") or "",
        "idade": dc.get("idade") or "",
        "sexo": dc.get("sexo") or "",
        "mae": dc.get("maeNome") or "",
        "situacao_cpf": dc.get("situacaoCadastral") or "",
        # Dois marcadores que mudam se vale a pena ligar, e que ficariam
        # escondidos se o painel só mostrasse contato.
        "obito_provavel": sim(dc.get("obitoProvavel")),
        "ppe": sim(dc.get("ppe")),
        "telefones": tels,
        "emails": s["emails"],
        "enderecos": [
            {"logradouro": " ".join(x for x in [e.get("tipoLogradouro"),
                                                e.get("logradouro")] if x),
             "numero": e.get("numero") or "",
             "complemento": e.get("complemento") or "",
             "bairro": e.get("bairro") or "", "cidade": e.get("cidade") or "",
             "uf": e.get("uf") or "", "cep": e.get("cep") or ""}
            for e in ((resp.get("enderecos") or [])
                      + (resp.get("enderecosAdicionados") or []))
            if isinstance(e, dict)],
        "redes": [x for x in (resp.get("redesSociais") or []) if x],
        "vinculos": vinculos,
        "custo": g.resumo(),
    }


async def resolver_e_detalhar(perfil: dict[str, Any], cidade: str = "",
                              uf: str = "",
                              teto_brl: float = 3.0) -> dict[str, Any]:
    """O "ver mais" de uma pessoa: acha o CPF e já traz os dados dela.

    Teto baixo de propósito — isto nasce de um clique numa linha da tabela, e
    um clique não deve conseguir gastar o orçamento do dia.
    """
    gasto = Gasto(teto_brl)
    emp = Empresa((perfil.get("empresa") or "").strip(), cidade, uf)
    await emp.preparar(gasto)
    r = await resolver_pessoa(perfil, emp, gasto)
    saida = {"identificacao": r, "empresa": {
        "cnpj": emp.cnpj, "razao": emp.razao,
        "faixa": emp.estrategia.get("faixa"),
        "porque": emp.estrategia.get("porque", "")}}
    if r.get("cpf"):
        saida["dossie"] = await dossie_pessoa(r["cpf"], gasto)
    saida["custo"] = gasto.resumo()
    return saida


def contexto_empresa(nome: str, cidade: str = "", uf: str = "") -> dict[str, Any]:
    """Tudo que a TELA precisa saber sobre a empresa, sem gastar um centavo.

    É o que o filtro B2B chama enquanto a pessoa digita: diz o porte, se falta
    escolher a cidade, e quais unidades existem para escolher.
    """
    r = I.cnpj_com_aviso(nome, uf)
    est = I.estrategia(r["cnpj"], cidade, uf, nome_empresa=nome)
    filiais = est.get("filiais_no_estado")
    if filiais is None:
        filiais = I.filiais_da_empresa(r["cnpj"], nome, 20, uf=uf) if r["cnpj"] else []
    return {
        "empresa": nome, "cnpj": r["cnpj"], "razao": r["razao"],
        "aviso": r["aviso"] or est.get("aviso", ""),
        "faixa": est.get("faixa", "desconhecida"),
        "modo": est.get("modo", ""),
        "unidades": est.get("filiais", 0), "ufs": est.get("ufs", 0),
        "exige_cidade": bool(est.get("exige_cidade")),
        "pode_buscar": bool(est.get("pode_buscar", True)),
        "porque": est.get("porque", ""),
        "teto_pago": est.get("teto_pago"),
        "custo_max_brl": est.get("custo_max_brl"),
        "raiz_trocada": est.get("raiz_trocada", ""),
        "cidade_resolvida": est.get("cidade_resolvida", ""),
        "unidade_padrao": est.get("unidade_padrao") or {},
        "filiais": [
            {"cidade": f["cidade"].title(), "uf": f["uf"],
             "unidades": f["unidades"], "matriz": f["matriz"],
             "perfis": f.get("perfis_no_cache", 0)}
            for f in filiais],
    }
