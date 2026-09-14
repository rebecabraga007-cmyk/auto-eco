# -*- coding: utf-8 -*-
"""Amarra a empresa que veio da Bright Data a um CNPJ brasileiro.

O PROBLEMA
----------
O dataset de empresas da Bright Data tem 26 campos e NENHUM e fiscal --
conferido no registro cru: nao ha CNPJ, nao ha inscricao, nao ha tax id. Faz
sentido, e raspagem do LinkedIn, e o LinkedIn nao pede CNPJ. O `company_id`
que vem junto e o id interno DELES e nao vale nada fora do LinkedIn.

Entao o CNPJ nao chega pronto: ele tem que ser deduzido deste lado.

AS DUAS CHAVES, NESSA ORDEM
---------------------------
1. DOMINIO DO SITE -- literal. `website_simplified` da Bright Data contra o
   dominio de `estabelecimentos.email` da Receita, via o indice
   `dominios.db` (ver cnpj_base/build_dominios.py; sem ele a consulta varre
   71,8 milhoes de linhas). E chave de verdade: nao confunde "Senior
   Sistemas" com "Senior Engenheiros Associados", que o nome confunde.

2. NOME -- semelhanca, so quando nao ha dominio ou o dominio nao achou.
   Aqui o resultado NUNCA e afirmado sozinho: precisa de folga sobre o
   segundo colocado, senao a funcao prefere devolver nada.

E a UF da sede, que nao escolhe nada: so desempata.

O CRITERIO
----------
Achar 40 CNPJs candidatos nao e achar. O que conta e resolver para UM. Por
isso `resolver()` devolve `cnpj` vazio com o motivo quando ficou ambiguo --
uma empresa sem CNPJ e um problema visivel; uma empresa com o CNPJ errado
contamina a lista inteira e ninguem percebe.
"""
import os
import re
import sqlite3
import unicodedata
from difflib import SequenceMatcher
from typing import Any

# Dominios que nao identificam ninguem: se o site da empresa e um desses, ou
# a Bright Data pegou a rede social no lugar do site, ou e MEI com e-mail
# pessoal. Em qualquer dos casos o dominio nao serve de chave.
GENERICO = {
    "linkedin.com", "gmail.com", "hotmail.com", "outlook.com", "yahoo.com",
    "yahoo.com.br", "bol.com.br", "uol.com.br", "terra.com.br", "ig.com.br",
    "facebook.com", "instagram.com", "twitter.com", "x.com", "youtube.com",
    "bit.ly", "linktr.ee", "wa.me", "api.whatsapp.com", "sites.google.com",
    "wixsite.com", "blogspot.com", "wordpress.com", "google.com",
}

# Palavras que aparecem em toda razao social e por isso nao distinguem nada.
# Comparar "Gerdau S.A." com "Gerdau Acos Longos Ltda" pelo texto cru daria
# semelhanca alta pelos motivos errados.
RUIDO = {
    "ltda", "sa", "s", "a", "me", "epp", "eireli", "mei", "do", "da", "de",
    "dos", "das", "e", "em", "group", "grupo", "brasil", "brazil", "inc",
    "corp", "corporation", "holding", "holdings", "cia", "companhia",
    "industria", "comercio", "servicos", "participacoes", "empreendimentos",
}

UFS = ("AC AL AP AM BA CE DF ES GO MA MT MS MG PA PB PR PE PI RJ RN RS RO RR "
       "SC SP SE TO").split()

# Abaixo disso o nome nao afirma nada. E acima disso ainda precisa da FOLGA:
# 0,90 contra 0,89 nao e um vencedor, sao dois empates.
NOTA_MIN = 0.82
FOLGA_MIN = 0.08

# Dominancia: a raiz que concentra o dominio e a dona dele. Precisa de massa
# para significar alguma coisa -- em 3 linhas, "a maior" e ruido.
#
# So a fatia, sem exigir folga sobre o segundo. A versao com "e pelo menos o
# dobro do segundo" reprovava a Magalu, medida assim no proprio dominio:
#   MAGAZINE LUIZA S/A ......... 1.532 de 2.543 (60,2%)
#   MAGALOG SERVICOS LOGISTICOS ...  956        (37,6%)
# 60,2% e a resposta certa e o dobro nunca aconteceria. Alem disso a exigencia
# era redundante: quem passa de 60% do total ja e maior que qualquer outro.
MIN_LINHAS_DOMINANCIA = 8
FATIA_DOMINANTE = 0.60


def _dir_dados() -> str:
    aqui = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("CNPJ_DB_DIR"), r"C:\capiblu_data",
              "/capiblu_data", aqui):
        if d and os.path.exists(os.path.join(d, "cnpj.db")):
            return d
    return aqui


_DIR = _dir_dados()
DOM_PATH = os.path.join(_DIR, "dominios.db")
CNPJ_PATH = os.path.join(_DIR, "cnpj.db")
FTS_PATH = os.path.join(_DIR, "cnpj_fts.db")


def disponivel() -> bool:
    return os.path.exists(DOM_PATH) or os.path.exists(FTS_PATH)


def _ro(p: str) -> str:
    return "file:%s?mode=ro" % p.replace("?", "%3f").replace("#", "%23")


def _norma(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or ""))
    s = "".join(c for c in s if not unicodedata.combining(c)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9]+", " ", s)).strip()


def nucleo(s: Any) -> str:
    """O nome sem as palavras que toda empresa tem."""
    return " ".join(t for t in _norma(s).split() if t not in RUIDO)


def dominio(site: Any) -> str:
    """Dominio aproveitavel do site, ou vazio.

    Tira protocolo, `www.`, caminho e porta. Devolve vazio para rede social e
    provedor gratuito -- esses existem no campo, mas nao sao chave.
    """
    s = re.sub(r"^\w+://", "", str(site or "").strip().lower())
    s = re.sub(r"^www\.", "", s).split("/")[0].split("?")[0].split(":")[0]
    s = s.strip().strip(".")
    if not s or "." not in s or " " in s:
        return ""
    if s in GENERICO or any(s.endswith("." + g) for g in GENERICO):
        return ""
    return s


def uf_do_registro(rec: dict) -> str:
    """UF da sede, quando o registro da Bright Data concorda consigo mesmo.

    `locations` traz TODAS as unidades. Se elas apontam para estados
    diferentes, a UF nao diz onde e a sede -- e ai ela nao pode desempatar
    nada, entao devolve vazio.
    """
    txt = " ".join(str(x) for x in (rec.get("formatted_locations") or []))
    txt += " " + str(rec.get("headquarters") or "")
    txt += " " + " ".join(str(x) for x in (rec.get("locations") or []))
    achadas = {u for u in UFS if re.search(r"\b%s\b" % u, txt)}
    return achadas.pop() if len(achadas) == 1 else ""


# ------------------------------------------------------------------ chave 1
def por_dominio(dom: str, limite: int = 80) -> list[dict]:
    """Um candidato por RAIZ, com quantas unidades ele tem no dominio.

    Agrega no SQL de proposito. Trazer linha a linha nao escalaria -- o
    dominio da Magalu tem 2.940 estabelecimentos, e o corte em 200 linhas
    falsearia exatamente a contagem que decide a dominancia.

    `matriz` vira o CNPJ terminado em 0001 quando existe; senao o menor da
    raiz, que e estavel entre consultas.
    """
    if not dom or not os.path.exists(DOM_PATH):
        return []
    try:
        con = sqlite3.connect(_ro(DOM_PATH), uri=True, timeout=3)
        linhas = con.execute(
            """SELECT raiz,
                      count(*),
                      max(CASE WHEN matriz=1 THEN cnpj END),
                      min(cnpj),
                      max(uf),
                      max(CASE WHEN situacao='02' THEN 1 ELSE 0 END),
                      max(fantasia)
                 FROM dominio_cnpj WHERE dominio=?
                GROUP BY raiz ORDER BY count(*) DESC LIMIT ?""",
            (dom, limite)).fetchall()
        con.close()
    except Exception:
        return []
    return [{"cnpj": l[2] or l[3], "raiz": l[0], "linhas": l[1],
             "matriz": "1" if l[2] else "", "uf": l[4],
             "situacao": "02" if l[5] else "", "nome": l[6] or ""}
            for l in linhas]


def _razoes(raizes: list[str]) -> dict[str, str]:
    """Razao social de cada raiz, para poder comparar nomes.

    O indice de dominio carrega `nome_fantasia`, que existe em so 16% dos
    estabelecimentos -- na pratica quase sempre vazio. Comparar o nome do
    LinkedIn contra vazio da semelhanca zero para TODOS os candidatos, e ai o
    desempate nunca acontece: foi o que aconteceu com Cervello, Octa e Eu
    Entrego, que tinham dominio bom e mesmo assim nao resolveram.

    A razao social esta em `empresas`, indexada por cnpj_basico -- barata.
    """
    raizes = [r for r in dict.fromkeys(raizes) if r][:40]
    if not raizes or not os.path.exists(CNPJ_PATH):
        return {}
    try:
        con = sqlite3.connect(_ro(CNPJ_PATH), uri=True, timeout=5)
        linhas = con.execute(
            "SELECT cnpj_basico, razao_social FROM empresas WHERE cnpj_basico "
            "IN (%s)" % ",".join("?" * len(raizes)), raizes).fetchall()
        con.close()
    except Exception:
        return {}
    return {l[0]: l[1] or "" for l in linhas}


# ------------------------------------------------------------------ chave 2
def por_nome(nome: str, uf: str = "", limite: int = 60) -> list[dict]:
    n = nucleo(nome)
    if len(n) < 4 or not os.path.exists(FTS_PATH):
        return []
    # Mesma sintaxe do cnpj_lookup: tokens com prefixo, restritos as colunas
    # de nome. Sem o escopo, "sul" casaria com o municipio e traria lixo.
    toks = [t for t in n.split() if len(t) >= 3][:4]
    if not toks:
        return []
    expr = "{razao fantasia} : (%s)" % " ".join('"%s"*' % t for t in toks)
    if uf:
        expr += " AND uf:%s" % uf.lower()
    try:
        con = sqlite3.connect(_ro(FTS_PATH), uri=True, timeout=5)
        linhas = con.execute(
            "SELECT cnpj, razao, fantasia, uf, situacao FROM estab_fts "
            "WHERE estab_fts MATCH ? LIMIT ?", (expr, limite)).fetchall()
        con.close()
    except Exception:
        return []
    return [{"cnpj": l[0], "raiz": (l[0] or "")[:8],
             "matriz": "1" if (l[0] or "")[8:12] == "0001" else "",
             "uf": l[3], "situacao": l[4],
             "nome": l[2] or l[1] or "", "razao": l[1] or ""}
            for l in linhas]


# ------------------------------------------------------------------ escolha
def _escolher(nome: str, cands: list[dict], uf: str = "") -> tuple[str, str]:
    """De muitos candidatos para UM, ou nenhum. Devolve (cnpj, motivo)."""
    if not cands:
        return "", "sem candidato"

    ativos = [c for c in cands if c.get("situacao") == "02"] or cands
    if uf:
        na_uf = [c for c in ativos if (c.get("uf") or "") == uf]
        if na_uf:
            ativos = na_uf

    if len(ativos) == 1:
        return ativos[0]["cnpj"], "candidato unico"

    # Muitas linhas, uma empresa: sao filiais. A matriz representa o grupo.
    # E o caso da Magalu (900 lojas) e da Gerdau -- justamente as que o
    # filtro mais quer, e que um corte por quantidade destruiria.
    raizes = {c.get("raiz") or c["cnpj"][:8] for c in ativos}
    if len(raizes) == 1:
        matriz = [c for c in ativos if str(c.get("matriz")) == "1"]
        unid = sum(int(c.get("linhas") or 1) for c in ativos)
        if matriz:
            return matriz[0]["cnpj"], "matriz de %d unidades" % unid
        return sorted(ativos, key=lambda c: c["cnpj"])[0]["cnpj"], "raiz unica"

    # DOMINANCIA. Grupo grande tem muitas raizes -- Magalu 53, Gerdau 76,
    # Banrisul 58 (Luizacred, Luizaseg, Luizalabs, as adquiridas). Contar
    # raizes nao separa grupo de escritorio de contabilidade: os dois tem
    # dezenas. O que separa e a concentracao. No dominio da Magalu uma raiz
    # responde por quase todas as linhas; no do contador, cada cliente tem
    # uma ou duas e ninguem concentra.
    #
    # So vale quando ha muitas linhas: entre 3 raizes com 2, 1 e 1 linha, a
    # "dominante" nao significa nada.
    ordem = sorted(ativos, key=lambda c: -int(c.get("linhas") or 1))
    total = sum(int(c.get("linhas") or 1) for c in ordem)
    maior = int(ordem[0].get("linhas") or 1)
    if total >= MIN_LINHAS_DOMINANCIA and maior >= FATIA_DOMINANTE * total:
        return ordem[0]["cnpj"], ("raiz dominante: %d de %d unidades do dominio"
                                  % (maior, total))

    # Raizes diferentes sem dominancia: sao empresas diferentes e so o nome separa.
    alvo = nucleo(nome)
    if not alvo:
        return "", "%d empresas distintas, sem nome para desempatar" % len(raizes)

    # Quem nao tem fantasia nem razao entra na comparacao com string vazia e
    # tira nota zero -- o que nao e "nao parece", e "nao sei". Busca a razao
    # social antes de julgar.
    if any(not (c.get("nome") or c.get("razao")) for c in ativos):
        rz = _razoes([c.get("raiz") or c["cnpj"][:8] for c in ativos])
        for c in ativos:
            if not (c.get("nome") or c.get("razao")):
                c["razao"] = rz.get(c.get("raiz") or c["cnpj"][:8], "")

    notas = sorted(
        ((SequenceMatcher(None, alvo, nucleo(c.get("nome") or c.get("razao")
                                             or "")).ratio(), c)
         for c in ativos), key=lambda x: -x[0])
    melhor, nota = notas[0][1], notas[0][0]
    segunda = notas[1][0] if len(notas) > 1 else 0.0
    if nota >= NOTA_MIN and (nota - segunda) >= FOLGA_MIN:
        return melhor["cnpj"], "nome desempata (%.2f contra %.2f)" % (nota, segunda)
    return "", ("%d empresas distintas, nome nao desempata (%.2f contra %.2f)"
                % (len(raizes), nota, segunda))


def _matriz_da_raiz(cnpj: str) -> str:
    """Troca a filial pela matriz da mesma raiz, quando ela existe e esta ativa.

    O caminho por NOME casa contra qualquer estabelecimento, entao ele devolve
    filial com facilidade -- medido: Construtora Tenda saiu como .../0014-50 e
    Infracommerce como .../0628-45. Nao esta errado, sao CNPJs da empresa; mas
    como IDENTIDADE da empresa quem responde e a matriz, e e nela que o QSA e
    os socios estao pendurados.

    Nao achando matriz ativa, devolve o que veio: filial identificada e melhor
    que nada identificado.
    """
    d = re.sub(r"\D", "", cnpj or "")
    if len(d) != 14 or d[8:12] == "0001" or not os.path.exists(CNPJ_PATH):
        return cnpj
    try:
        con = sqlite3.connect(_ro(CNPJ_PATH), uri=True, timeout=5)
        r = con.execute(
            "SELECT cnpj FROM estabelecimentos WHERE cnpj_basico=? "
            "AND matriz_filial='1' AND situacao='02' LIMIT 1", (d[:8],)).fetchone()
        con.close()
    except Exception:
        return cnpj
    return r[0] if r and r[0] else cnpj


def resolver(nome: str = "", site: str = "", uf: str = "",
             registro: dict | None = None) -> dict[str, Any]:
    """CNPJ de uma empresa da Bright Data.

    Devolve sempre a mesma forma:
        {cnpj, confianca: alta|media|nenhuma, chave: dominio|nome|"",
         motivo, dominio, candidatos}

    `cnpj` vazio nao e falha do codigo: e a recusa de escolher entre empresas
    diferentes. Preferivel a devolver o CNPJ errado, que ninguem confere.
    """
    if registro:
        nome = nome or registro.get("name") or registro.get("nome") or ""
        site = site or (registro.get("website_simplified")
                        or registro.get("website") or registro.get("site") or "")
        # O estado do PERFIL manda: ele e evidencia sobre a empresa, e o `uf`
        # recebido de fora e so a dica de quem pesquisou. So vale quando o
        # perfil nao diz nada.
        uf = uf_do_registro(registro) or uf

    dom = dominio(site)
    saida = {"cnpj": "", "confianca": "nenhuma", "chave": "", "motivo": "",
             "dominio": dom, "candidatos": 0}

    if dom:
        cands = por_dominio(dom)
        saida["candidatos"] = len(cands)
        cnpj, motivo = _escolher(nome, cands, uf)
        if cnpj:
            saida.update(cnpj=_matriz_da_raiz(cnpj), confianca="alta",
                         chave="dominio",
                         motivo="dominio %s -> %s" % (dom, motivo))
            return saida
        if cands:
            saida["motivo"] = "dominio %s: %s" % (dom, motivo)

    cands = por_nome(nome, uf)
    saida["candidatos"] = saida["candidatos"] or len(cands)
    cnpj, motivo = _escolher(nome, cands, uf)

    # ESTADO DIFERENTE DERRUBA O CASAMENTO POR NOME.
    #
    # A preferencia por UF dentro de `_escolher` e so preferencia: quando
    # nenhum candidato esta no estado certo, ela desiste e aceita qualquer um.
    # Para o dominio isso e aceitavel -- o dominio E a prova, e uma matriz em
    # outro estado continua sendo a mesma empresa. Para o NOME nao e: visto em
    # 14/set/2026, "Tequilaville" (SC no LinkedIn) casou com uma MEI chamada
    # CLEIDINA ALVES LINHARES no Ceara, e a lista de uma busca por SC mostrou
    # uma empresa do CE. Nome parecido em outro estado nao e a mesma empresa.
    if cnpj and uf:
        escolhido = next((c for c in cands if c.get("cnpj") == cnpj), None)
        if escolhido and (escolhido.get("uf") or "").upper()[:2] not in ("", uf.upper()[:2]):
            cnpj, motivo = "", ("nome casou em %s, mas a empresa e de %s"
                                % (escolhido.get("uf"), uf.upper()[:2]))

    if cnpj:
        # Media, nao alta: nome parecido nao e prova. "Senior Sistemas" e
        # "Senior Engenheiros Associados" existem as duas, no mesmo pais.
        saida.update(cnpj=_matriz_da_raiz(cnpj), confianca="media",
                     chave="nome", motivo="nome -> %s" % motivo)
        return saida
    saida["motivo"] = saida["motivo"] or ("nome: %s" % motivo)
    return saida



def dominio_do_cnpj(cnpj: str) -> str:
    """Caminho INVERSO: do CNPJ para o dominio do site.

    Serve para achar a empresa no LinkedIn partindo da Receita, que e o que a
    aba B2B faz o tempo todo -- ela lista empresas da Receita e depois quer os
    decisores no LinkedIn.

    Sem isto, a busca de pessoas usa a RAZAO SOCIAL, e razao social quase
    nunca e o nome que a empresa usa no LinkedIn. Medido: o CNPJ
    17.688.085/0001-45 e "L3 SOLUCOES EM TECNOLOGIA LTDA" na Receita e "Even3"
    no LinkedIn -- procurar por L3 devolvia zero, e a empresa tem 45 pessoas
    la dentro.

    Pega o dominio mais frequente entre os e-mails da RAIZ (nao so do
    estabelecimento pedido): filial costuma cadastrar e-mail pessoal do gerente
    e a matriz costuma ter o corporativo.
    """
    d = re.sub(r"\D", "", cnpj or "")
    if len(d) < 8 or not os.path.exists(CNPJ_PATH):
        return ""
    try:
        con = sqlite3.connect(_ro(CNPJ_PATH), uri=True, timeout=5)
        linhas = con.execute(
            "SELECT email FROM estabelecimentos WHERE cnpj_basico=? "
            "AND email LIKE '%@%.%' LIMIT 200", (d[:8],)).fetchall()
        con.close()
    except Exception:
        return ""
    contagem: dict[str, int] = {}
    for (em,) in linhas:
        dom = str(em or "").strip().lower().rsplit("@", 1)[-1]
        if not dom or dom in GENERICO:
            continue
        contagem[dom] = contagem.get(dom, 0) + 1
    if not contagem:
        return ""
    return max(contagem.items(), key=lambda kv: kv[1])[0]


def resolver_varias(registros: list[dict]) -> list[dict]:
    """Mesma coisa para uma lista -- o caso do filtro B2B em massa.

    Sem chamada externa e sem custo: as duas chaves sao consultas locais.
    """
    saida = []
    for r in registros or []:
        d = resolver(registro=r)
        d["nome"] = r.get("name") or r.get("nome") or ""
        saida.append(d)
    return saida
