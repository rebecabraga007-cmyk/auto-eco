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

  00  Bright Data           PAGO    entra pronto: nome, cargo, empresa, cidade
  01  porta de cargo        local   rotula; NÃO barra (ver abaixo)
  02  porte da empresa      local   escolhe a filial e o teto de gasto
  03  possíveis decisores   POR EMPRESA, R$ 0,24 na 1ª vez, depois cache
  04  RAIS / CAGED          POR EMPRESA, gateway FDX
  ---------------------------------------------------------------------
  05  JBR                   local   ENUMERA os candidatos: 223,7M, sem teto
  06  WorkAPI nome          grátis  CPF inteiro + endereço, cruzado com a JBR
  07  MK integrax-cpf       grátis  confirma cidade e EMPRESA; fecha sem pagar
  08  Assertiva nome+cidade PAGO    só para quem sobrou
  09  Assertiva consulta_cpf PAGO   a prova: CNPJ do empregador e CBO
      decidir()                     escolhe, ou devolve para o operador

O ERRO QUE ESTE ARQUIVO JÁ TEVE, para não voltar
------------------------------------------------
A primeira versão listava estas dez etapas no docstring e implementava CINCO.
A JBR e o MK apareciam aqui em cima e não no código — `mkbuscas` ficava
importado sem nunca ser chamado, e o fluxo pulava da WorkAPI direto para a
busca PAGA. Quando a pessoa não estava no índice de nome da Assertiva naquela
cidade, a resposta voltava vazia e cobrada, enquanto a JBR — que é a base
inteira e é local — teria respondido de graça. Foi assim que funcionários da
BLU que a rodada manual tinha achado passaram a dar "não consegui identificar".

Documentação que descreve mais do que o código faz é pior que documentação
nenhuma: ela impede a pergunta certa.

SOBRE A ETAPA 01
----------------
Ela roda e rotula, mas não barra: `barrar_sem_cargo` nasce False. Medida nos
166 perfis, a porta dava +1,7 pp de razão CUSTANDO 14 CPFs — o grupo que ela
barra resolve a 46,2%, não a 30% que eu projetei. Decisão da Rebeca em
08/09/2026. O detalhe está no docstring de `funcoes.eh_cargo`.
"""
from __future__ import annotations

import asyncio
import os
import re
import sqlite3
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
JBR_DB = os.environ.get("JBR_DB", "/opt/capiblu/jbr_base/jbr_pf.db")
# Quantos candidatos vão ao MK por pessoa. A cota é 2000/dia e o gateway
# estrangula acima de ~250 chamadas rápidas; 12 cobre o caso comum sem
# transformar uma busca numa varredura.
MAX_MK = int(os.environ.get("FUNIL_MAX_MK", "12"))


def _pela_jbr(nome: str, teto: int = 400) -> tuple[list[dict[str, Any]], str]:
    """CPFs com esse nome, da base local. Grátis, 223,7 milhões, sem teto de API.

    ESTA ETAPA TINHA FICADO DE FORA. O docstring do módulo listava a JBR e o
    código nunca a abria — o funil ia direto da WorkAPI para a busca PAGA da
    Assertiva. Nos funcionários da BLU isso trocou uma resposta gratuita e
    completa por consulta paga que voltava vazia, porque quem não está no
    índice de nome da Assertiva naquela cidade simplesmente não existe para
    ela. A JBR não tem esse problema: é a base inteira.

    Tenta `nome_norm=` exato primeiro; sem resultado, cai para primeiro+último,
    que é o que resolve nome do meio escondido no LinkedIn.

    Consulta por FAIXA (>= / <), nunca `LIKE 'X%'`: o LIKE varre as 223 milhões
    de linhas em 87 s, a faixa usa o índice e responde em 0,026 s.
    """
    nn = I._norm(nome)
    if not nn:
        return [], ""
    try:
        con = sqlite3.connect("file:%s?mode=ro" % JBR_DB, uri=True)
    except Exception:
        return [], ""
    try:
        linhas = con.execute(
            "SELECT cpf,nome,nascimento FROM pessoas WHERE nome_norm=? LIMIT ?",
            (nn, teto)).fetchall()
        modo = "exato"
        if not linhas:
            partes = [p for p in nn.split() if len(p) > 1]
            if len(partes) >= 2:
                pref = partes[0] + " "
                fim = pref[:-1] + chr(ord(" ") + 1)
                linhas = con.execute(
                    "SELECT cpf,nome,nascimento FROM pessoas WHERE nome_norm >= ? "
                    "AND nome_norm < ? AND nome_norm LIKE ? LIMIT ?",
                    (pref, fim, "% " + partes[-1], teto)).fetchall()
                modo = "primeiro+ultimo"
    except Exception:
        return [], ""
    finally:
        con.close()
    return ([{"cpf": r[0], "nome": r[1], "nascimento": r[2]} for r in linhas
             if _cpf(r[0])], modo if linhas else "")


_razoes: dict[str, str] = {}


def _razao_do_cnpj(cnpj: Any) -> str:
    """CNPJ -> razão social, da base da Receita. Índice é `cnpj_basico`."""
    d = re.sub(r"\D", "", str(cnpj or ""))[:8]
    if len(d) != 8:
        return ""
    if d in _razoes:
        return _razoes[d]
    try:
        con = sqlite3.connect("file:%s?mode=ro" % I.CNPJ_DB, uri=True)
        r = con.execute("SELECT razao_social FROM empresas WHERE cnpj_basico=?",
                        (d,)).fetchone()
        con.close()
    except Exception:
        r = None
    _razoes[d] = (r[0] if r and r[0] else "")
    return _razoes[d]


async def _pelo_mk(candidatos: list[dict[str, Any]], cidade: str, uf: str,
                   empresa: str, gasto: Gasto) -> list[dict[str, Any]]:
    """Confirma cada candidato no MK: cidade, empresa e telefone. Cota grátis.

    A OUTRA ETAPA QUE FALTAVA. `mkbuscas` estava importado no módulo e nunca
    era chamado. É ele que fecha o caso de graça: as `empresas` do MK vêm com
    CNPJ, e a razão social da Receita cruzada com o nome da empresa do LinkedIn
    dá o mesmo tipo de prova que a Assertiva cobra R$ 0,119 para dar.
    """
    toks_alvo = I._tokens_empresa(empresa)
    saida = []
    for c in candidatos[:MAX_MK]:
        d = await mkbuscas.consulta_cpf(c["cpf"])
        gasto.mk += 1
        if d.get("status") != "ok":
            continue
        dd = d.get("data") or {}
        ends = [e for e in (dd.get("enderecos") or []) if isinstance(e, dict)]
        cidade_bate = bool(cidade) and any(
            I._norm(e.get("cidade")) == I._norm(cidade) for e in ends)
        uf_bate = bool(uf) and any(
            str(e.get("uf") or "").upper() == uf.upper() for e in ends)
        razoes, empresa_bate = [], False
        for e2 in (dd.get("empresas") or [])[:10]:
            if not isinstance(e2, dict):
                continue
            rz = _razao_do_cnpj(e2.get("cnpj"))
            if rz:
                razoes.append(rz)
                if toks_alvo & I._tokens_empresa(rz):
                    empresa_bate = True
        # Mesma hierarquia do `avaliar()`, com o que o MK oferece de graça.
        forca = 0
        motivos = []
        if empresa_bate:
            forca = 90
            motivos.append("empresa confere no quadro societário (MK, grátis)")
        elif cidade_bate:
            forca = 60
            motivos.append("mora na cidade do perfil")
        elif uf_bate:
            forca = 25
            motivos.append("mora no estado do perfil")
        saida.append({**c, "forca": forca, "elimina": False, "motivos": motivos,
                      "telefones": mkbuscas._extract_phones(dd),
                      "cidade_bate": cidade_bate, "empresa_bate": empresa_bate})
    return saida


async def _pela_workapi(nome: str, gasto: Gasto) -> list[dict[str, Any]]:
    """Candidatos com CPF e ENDEREÇO, de graça.

    NÃO FILTRA POR CIDADE, e isso é deliberado — o endereço serve para ORDENAR,
    nunca para cortar. Quem mudou de estado tem cadastro velho: Luiz Gustavo
    Turmina aparece em Francisco Beltrão/PR enquanto o LinkedIn diz Balneário
    Camboriú/SC, e os telefones dele saem com DDD 41 e 46 — ele é do Paraná
    mesmo. Cortando por cidade, o único candidato certo era descartado e o caso
    ia parar na busca paga, que voltava vazia.

    Três tentativas porque o gateway recusa rajada com 403; ver `workapi.py`.
    """
    r = await workapi.nome_search(nome, limit=60, tentativas=3)
    gasto.workapi += 1
    if r.get("status") != "ok":
        return []
    return [p for p in (r.get("pessoas") or [])
            if _cpf(p.get("cpf")) and _nome_contido(nome, p.get("nome"))]


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


async def resolver_pessoa(perfil: dict[str, Any], emp: Empresa, gasto: Gasto,
                          barrar_sem_cargo: bool = False) -> dict[str, Any]:
    """Um perfil do LinkedIn -> um CPF, ou o motivo de não ter dado.

    Roda as DEZ etapas documentadas, nesta ordem. Antes rodava cinco: a JBR e o
    MK estavam no docstring e não no código, e `mkbuscas` ficava importado sem
    nunca ser chamado. O funil pulava da WorkAPI direto para a busca PAGA e,
    quando a pessoa não estava no índice de nome da Assertiva naquela cidade,
    voltava vazio — enquanto a JBR, que tem a base inteira, teria respondido de
    graça. Foi o que aconteceu com os funcionários da BLU.
    """
    t0 = time.time()
    nome = (perfil.get("nome") or "").strip()
    cargo = perfil.get("cargo") or ""
    cid = I.cidade_do_linkedin(perfil.get("cidade"))
    uf = (linkedin_cache.uf_de(perfil.get("cidade") or "")
          # "Greater São Paulo Area" não tem vírgula, então `uf_de` volta
          # vazio. A UF sai do nome do município quando ele é único.
          or I.uf_da_cidade(cid) or emp.uf)
    etapas: list[str] = []

    def saida(situacao, cpf="", confianca=0, **extra):
        return {"nome": nome, "empresa": emp.nome, "cargo": cargo,
                "cidade": cid, "uf": uf, "cpf": cpf, "situacao": situacao,
                "confianca": confianca, "etapas": etapas,
                "ms": int((time.time() - t0) * 1000), **extra}

    if len([t for t in I._norm(nome).split() if len(t) > 1]) < 2:
        return saida("nome_incompleto")

    # ETAPA 01 — porta de cargo. Roda para ROTULAR; só barra se pedirem.
    # Desligada por decisão da Rebeca em 08/09/2026: medida, ela dava +1,7 pp
    # de razão e custava 14 CPFs. Ver `funcoes.eh_cargo`.
    tem_cargo = funcoes.eh_cargo(cargo)
    etapas.append("01 cargo:%s" % ("sim" if tem_cargo else "nao"))
    if barrar_sem_cargo and not tem_cargo:
        return saida("barrado_sem_cargo")

    # ETAPAS 02/03/04 — porte, decisores e RAIS, já resolvidos por empresa.
    etapa, cpf = emp.por_lista(nome)
    etapas.append("03/04 listas do CNPJ:%d+%d"
                  % (len(emp.decisores), len(emp.vinculos)))
    if cpf:
        return saida("resolvido_por_" + etapa, cpf, 90,
                     porque="nome único na lista de %s do CNPJ" % etapa)

    de, ate = linkedin_cache.faixa_nascimento(
        int(perfil.get("formatura_ano") or 0),
        int(perfil.get("carreira_desde") or 0))

    # ETAPA 05 — JBR: enumera os candidatos. Grátis, local, base inteira.
    jbr, modo = _pela_jbr(nome)
    if de:
        f = [c for c in jbr
             if linkedin_cache.dentro_da_faixa(c.get("nascimento"), de, ate)]
        if f:
            jbr = f
    etapas.append("05 JBR:%d(%s)" % (len(jbr), modo or "vazio"))

    # ETAPA 06 — WorkAPI: endereço de graça, cruzado por CPF com a JBR.
    livres = await _pela_workapi(nome, gasto)
    if de:
        f = [p for p in livres
             if linkedin_cache.dentro_da_faixa(p.get("data_nascimento"), de, ate)]
        if f:
            livres = f
    ends = {_cpf(p["cpf"]): p["endereco"] for p in livres if _cpf(p["cpf"])}
    etapas.append("06 WorkAPI:%d" % len(livres))

    # A WorkAPI pode achar quem a JBR não achou (e vice-versa). Une os dois.
    candidatos = {c["cpf"]: c for c in jbr}
    for p in livres:
        d = _cpf(p["cpf"])
        if d and d not in candidatos:
            candidatos[d] = {"cpf": d, "nome": p.get("nome") or "",
                             "nascimento": p.get("data_nascimento") or ""}
    lista = list(candidatos.values())

    # Ordena pelo endereço que a WorkAPI deu: cidade do perfil primeiro.
    def ordem(c):
        e = ends.get(c["cpf"])
        if not e:
            return 2
        if cid and I._norm(e.get("cidade")) == I._norm(cid):
            return 0
        if uf and str(e.get("uf") or "").upper() == uf.upper():
            return 1
        return 3
    lista.sort(key=ordem)

    # ETAPA 07 — MK: confirma cidade e EMPRESA. Cota grátis, e é aqui que o
    # caso costuma fechar sem gastar: as empresas do MK vêm com CNPJ, e a razão
    # social da Receita cruzada com a empresa do LinkedIn é prova do mesmo tipo
    # que a Assertiva cobra para dar.
    if lista:
        avaliados = await _pelo_mk(lista, cid, uf, emp.nome, gasto)
        etapas.append("07 MK:%d" % len(avaliados))
        fortes = [a for a in avaliados if a["forca"] >= 60]
        if fortes:
            d = I.decidir(fortes, concorrentes=len(fortes))
            if d.get("cpf"):
                return saida("resolvido_gratis", d["cpf"], d["confianca"],
                             porque=d.get("porque", ""),
                             motivos=(fortes[0].get("motivos") or []),
                             telefones=next((a["telefones"] for a in fortes
                                             if a["cpf"] == d["cpf"]), []))
        # Candidato único que sobreviveu a tudo: a regra do concorrente vale.
        if len(avaliados) == 1:
            d = I.decidir(avaliados, concorrentes=1)
            if d.get("cpf"):
                return saida("resolvido_gratis", d["cpf"], d["confianca"],
                             porque=d.get("porque", ""),
                             telefones=avaliados[0].get("telefones") or [])

    if not emp.estrategia.get("pode_buscar", True):
        return saida("precisa_escolher_filial", confianca=0,
                     porque=emp.estrategia.get("porque", ""),
                     escolher_entre=emp.estrategia.get("escolher_entre") or [])

    # ETAPA 08 — busca paga
    pf, por_uf, truncou = await _pela_assertiva(nome, cid, uf, gasto)
    etapas.append("08 Assertiva:%d%s" % (len(pf), " por UF" if por_uf else ""))
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

    etapas.append("09 consulta_cpf:%d" % len(avaliados))
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
