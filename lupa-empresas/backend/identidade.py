# -*- coding: utf-8 -*-
"""Liga um perfil do LinkedIn a um CPF, com o motivo declarado.

POR QUE EXISTE: a Bright Data entrega nome, cargo, empresa e cidade — nunca CPF
nem telefone (46 campos, nenhum de contato). Este módulo faz a ponte, e a parte
difícil não é achar candidatos: é decidir QUAL é a pessoa sem chutar.

HIERARQUIA DE EVIDÊNCIA, do que prova ao que só sugere. Medida em 166 perfis:

  1. CNPJ do empregador bate com o da empresa .... PROVA. sem margem.
  2. razão social do empregador bate ............. forte
  3. cidade do cadastro == cidade do LinkedIn .... forte
  4. profissão/setor coerente com o cargo ........ médio
  5. faixa de nascimento (formação/1º emprego) ... médio, só filtra
  6. DDD do telefone == DDD da cidade ............ fraco, quase sempre redundante
  7. profissão INCOMPATÍVEL ...................... ELIMINA (médico ≠ vendas)

De onde vem cada coisa, e o que custa:

  Assertiva `nome-endereco`  R$ 0,119  candidatos: cpf, nascimento, mãe, endereço
  Assertiva `consulta_cpf`   R$ 0,119  vínculo empregatício COM CNPJ, telefones,
                                       e-mails, histórico profissional, setor
  MK `integrax-cpf`          cota      endereços (todos), telefones, renda
  JBR                        grátis    homônimos no país — mede a ambiguidade
  cnpj.db / cnpj_fts.db      grátis    CNPJ da empresa, razão social, cidade→DDD

REGRA DE OURO: toda resposta paga é lida INTEIRA. O `consulta_cpf` traz o
vínculo empregatício junto com o telefone — ignorar isso foi o erro que manteve
a taxa em 57% quando ela podia ser 61%.

E o que este módulo NUNCA faz: escolher um candidato sem evidência. Quando nada
separa, devolve `nao_resolvido` com os candidatos e o motivo. Telefone errado no
funil é pior que telefone nenhum.
"""
import json
import os
import re
import sqlite3
import unicodedata
from typing import Any

import assertiva
import funcoes
import linkedin_cache
import mkbuscas

CNPJ_DB = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"), "cnpj.db")
FTS_DB = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"), "cnpj_fts.db")
MAPA_DDD = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"),
                        "cidade_ddd.json")

# A busca por nome+cidade devolve no máximo 50, em ordem alfabética e sem
# paginação. Exatamente 50 = truncado E enviesado: a pessoa pode estar depois do
# corte, então não se escolhe ninguém.
TETO_ASSERTIVA = 50
# Acima disto não vale pagar consulta por candidato: o custo cresce linear e a
# chance de acerto não.
MAX_CANDIDATOS = 20
# Consultas PAGAS por candidato, por pessoa buscada.
MAX_PAGO = 4

PART = {"DA", "DE", "DO", "DAS", "DOS", "E"}
RUIDO_EMP = {"GRUPO", "COMPANHIA", "CIA", "LTDA", "SA", "EIRELI", "ME", "EPP",
             "HOLDING", "PARTICIPACOES", "LOJAS", "SISTEMAS", "TECNOLOGIA",
             "SERVICOS", "COMERCIO", "INDUSTRIA", "BRASIL"}

# As tabelas de família e os pares incompatíveis viviam aqui e foram para o
# `funcoes.py`, que corrigiu o bug do `` no fim do radical — `vend` nunca
# casava com "vendedor" e a família VENDAS, a maior da base, ficou cega por um
# dia inteiro de testes. Removidas daqui para não haver duas versões, uma delas
# quebrada, esperando alguém importar a errada.

_mapa_ddd: dict | None = None


def _norm(s: Any) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return " ".join(s.upper().split())


def _familias(texto: Any) -> set:
    t = _norm(texto).lower()
    return {n for n, p in _FAMILIAS if re.search(p, t)}


def _incompativel(a: set, b: set) -> bool:
    if not a or not b or (a & b):
        return False
    return any((u in a and v in b) or (v in a and u in b) for u, v in _INCOMPATIVEIS)


def _tokens_empresa(s: Any) -> set:
    return {t for t in _norm(s).split() if len(t) > 3 and t not in RUIDO_EMP}


def cidade_do_linkedin(texto: Any) -> str:
    """'Niterói, Rio de Janeiro, Brazil' -> 'NITEROI'."""
    p = [x.strip() for x in str(texto or "").split(",") if x.strip()]
    return _norm(p[0]) if p else ""


def ddd_da_cidade(cidade: str, uf: str) -> str:
    """DDD de um município, apurado dos 59,5 milhões de estabelecimentos que
    declararam telefone à Receita — voto de maioria, não tabela chutada.

    A chave inclui a UF de propósito: existe Toledo no PR (45) e em MG (35), e
    chavear só pelo nome devolvia o DDD do município errado.
    """
    global _mapa_ddd
    if _mapa_ddd is None:
        try:
            _mapa_ddd = json.load(open(MAPA_DDD, encoding="utf-8"))
        except Exception:
            _mapa_ddd = {}
    m = _mapa_ddd.get("%s|%s" % (_norm(cidade), (uf or "").upper()))
    return m["ddd"] if m else ""


def cnpj_da_empresa(nome: str, uf: str = "") -> tuple[str, str]:
    """Nome do LinkedIn -> (CNPJ da matriz, razão social). Local e grátis.

    Usa o índice de texto, não o cnpj.db: `razao_social` NÃO tem índice, e uma
    faixa nela vira varredura de 30 GB.

    Desempate, nesta ordem: mesma UF do perfil > não-holding > maior capital.

    A UF entrou depois de "Unimed" resolver para a cooperativa de São Paulo
    quando o perfil dizia Unimed Costa Oeste, de Toledo. Cooperativa e franquia
    — Unimed, Sicredi, Sicoob, Cacau Show — são centenas de CNPJs independentes
    com o mesmo nome, e escolher pelo maior capital erra a região sempre.

    Só capital também escolhia a controladora, que não tem empregado: foi assim
    que 'Suzano' virou SUZANO HOLDING, com 9 decisores em vez do quadro real.
    """
    toks = [t for t in _norm(nome).split() if len(t) > 2 and t not in RUIDO_EMP]
    if not toks:
        return "", ""
    chave = " ".join(toks)
    try:
        fts = sqlite3.connect("file:%s?mode=ro" % FTS_DB, uri=True)
        linhas = fts.execute(
            "SELECT cnpj, razao, situacao, uf FROM estab_fts WHERE estab_fts "
            "MATCH ? LIMIT 3000", ('razao:"%s"' % chave,)).fetchall()
        fts.close()
    except sqlite3.OperationalError:
        return "", ""
    if not linhas:
        return "", ""
    con = sqlite3.connect("file:%s?mode=ro" % CNPJ_DB, uri=True)
    melhor = None
    alvo_uf = (uf or "").upper()[:2]
    for cnpj, razao, sit, uf_est in linhas:
        if len(cnpj) != 14 or cnpj[8:12] != "0001" or str(sit) != "02":
            continue                       # só matriz ativa
        if not _norm(razao).startswith(chave):
            continue
        r = con.execute("SELECT capital_social FROM empresas WHERE cnpj_basico=?",
                        (cnpj[:8],)).fetchone()
        try:
            cap = float(str(r[0]).replace(",", ".")) if r and r[0] else 0.0
        except (TypeError, ValueError):
            cap = 0.0
        holding = "HOLDING" in _norm(razao) or "PARTICIPACOES" in _norm(razao)
        mesma_uf = 1 if (alvo_uf and str(uf_est or "").upper() == alvo_uf) else 0
        chave_ord = (mesma_uf, 0 if holding else 1, cap)
        if melhor is None or chave_ord > melhor[0]:
            melhor = (chave_ord, cnpj, razao)
    con.close()
    if not melhor:
        return ("", "")
    return (melhor[1], melhor[2])


def cnpj_com_aviso(nome: str, uf: str = "") -> dict[str, Any]:
    """Igual a `cnpj_da_empresa`, mas avisa quando a UF trocou a EMPRESA.

    "Gerdau" sem UF resolve 33611500000119; com RS resolve 87040598000120 —
    são dois grupos econômicos diferentes que começam com o mesmo nome. A
    preferência de UF é certa para cooperativa e franquia, e traiçoeira para
    conglomerado: o resultado fica coerente com o filtro e pode não ser a
    empresa que o operador tinha em mente.
    """
    cnpj_uf, razao_uf = cnpj_da_empresa(nome, uf)
    if not uf:
        return {"cnpj": cnpj_uf, "razao": razao_uf, "aviso": ""}
    cnpj_sem, razao_sem = cnpj_da_empresa(nome, "")
    aviso = ""
    if cnpj_sem and cnpj_uf and cnpj_sem[:8] != cnpj_uf[:8]:
        aviso = ("o filtro de %s escolheu '%s'; sem filtro seria '%s' — "
                 "confira se é a empresa certa" % (uf, razao_uf[:34], razao_sem[:34]))
    return {"cnpj": cnpj_uf, "razao": razao_uf, "aviso": aviso}


def sinais_do_cpf(resposta_assertiva: dict) -> dict[str, Any]:
    """Extrai TUDO que a resposta paga do `consulta_cpf` traz de útil.

    É a regra de ouro do módulo: a consulta já foi paga, então nada se descarta.
    O vínculo empregatício estava sendo ignorado, e é o sinal mais forte que
    existe aqui.
    """
    resp = (resposta_assertiva.get("data") or {}).get("resposta") or {}
    vinculos = []
    for h in (resp.get("possivelHistoricoProfissional") or []):
        if isinstance(h, dict):
            vinculos.append({
                "cnpj": re.sub(r"\D", "", str(h.get("cnpj") or "")),
                "razao": h.get("razaoSocial") or "",
                "cargo": h.get("cboDescricao") or "",
                "setor": h.get("setor") or "",
                "desde": h.get("dataRegistro") or "",
                "tipo": "emprego",
            })
    for h in (resp.get("participacoesEmpresas") or []):
        if isinstance(h, dict):
            vinculos.append({
                "cnpj": re.sub(r"\D", "", str(h.get("cnpj") or "")),
                "razao": h.get("razaoSocial") or "",
                "cargo": h.get("cargo") or "",
                "setor": "",
                "desde": h.get("dataEntrada") or "",
                "tipo": "societario",
            })
    profissoes = [str(x.get("profissao")) for x in (resp.get("registrosProfissionais") or [])
                  if isinstance(x, dict) and x.get("profissao")]
    tels = assertiva._flatten_tel(resp.get("telefones")) + \
        assertiva._flatten_tel(resp.get("telefonesAdicionados"))
    cidades = {_norm(e.get("cidade")) for e in (resp.get("enderecos") or [])
               if isinstance(e, dict) and e.get("cidade")}
    return {"vinculos": vinculos, "profissoes": profissoes, "telefones": tels,
            "cidades": cidades,
            "emails": [e.get("email") for e in (resp.get("emails") or [])
                       if isinstance(e, dict) and e.get("email")]}


def avaliar(sinais: dict, alvo: dict,
            cidade_ja_filtrada: bool = True) -> dict[str, Any]:
    """Compara um candidato com o perfil do LinkedIn. Devolve motivo e força.

    `alvo`: {cnpj_empresa, empresa, cargo, cidade, ddd}

    `cidade_ja_filtrada`: quando a busca na Assertiva JÁ foi por cidade, todos
    os candidatos moram lá por construção — então "a cidade confere" não
    distingue ninguém e vale ZERO. Contá-la como evidência forte fazia todo
    mundo empatar em 60 e nada resolver. Só vale quando a busca foi por UF.
    """
    motivos, forca, elimina = [], 0, False
    toks_emp = _tokens_empresa(alvo.get("empresa"))
    cnpj_emp = re.sub(r"\D", "", str(alvo.get("cnpj_empresa") or ""))[:8]
    fam_cargo = funcoes.areas(alvo.get("cargo")) or funcoes.setores(alvo.get("cargo"))
    fam_cand = set()

    # Dois eixos: o que a pessoa FAZ (área) e onde ela faz (setor econômico).
    # Com um eixo só, dois vendedores empatavam — um em agropecuária, outro em
    # informática. Com os dois, o que casa o "SaaS/B2B" do perfil se separa.
    setor_alvo = funcoes.setor_economico(alvo.get("empresa"))                  | funcoes.setor_economico(alvo.get("cargo"))
    setor_cand = set()
    vinc_na_area = 0
    for v in sinais["vinculos"]:
        a_v = funcoes.areas(v["cargo"]) | funcoes.areas(v["setor"])               | funcoes.setores(v["setor"])
        fam_cand |= a_v
        setor_cand |= funcoes.setor_economico(v["setor"])                       | funcoes.setor_economico(v["razao"])
        if fam_cargo & a_v:
            vinc_na_area += 1
        if cnpj_emp and v["cnpj"][:8] == cnpj_emp:
            motivos.append("CNPJ do empregador confere (%s)" % v["razao"][:40])
            forca = max(forca, 100)
        elif toks_emp and (toks_emp & _tokens_empresa(v["razao"])):
            motivos.append("empregador '%s' bate com a empresa" % v["razao"][:40])
            forca = max(forca, 80)
    for p in sinais["profissoes"]:
        fam_cand |= funcoes.areas(p)

    if alvo.get("cidade") and _norm(alvo["cidade"]) in sinais["cidades"]:
        if cidade_ja_filtrada:
            motivos.append("cidade confere (esperado — a busca já filtrou por ela)")
        else:
            motivos.append("cidade do cadastro confere")
            forca = max(forca, 60)

    if funcoes.incompativel(fam_cargo, fam_cand):
        elimina = True
        motivos.append("profissão incompatível (%s x %s)"
                       % (",".join(sorted(fam_cargo)), ",".join(sorted(fam_cand))))
    elif fam_cargo & fam_cand:
        casadas = sorted(fam_cargo & fam_cand)
        # 30 pela área + até 30 pela CONSISTÊNCIA da trajetória + 25 pelo setor.
        # A consistência importa: dois vínculos de vendas em três dizem mais que
        # um em quatro. Antes eu dava 50 fixo e o vínculo isolado empatava com a
        # carreira inteira.
        total_v = max(len(sinais["vinculos"]), 1)
        consistencia = vinc_na_area / total_v
        p = 30 + int(30 * consistencia)
        casou_setor = bool(setor_alvo & setor_cand)
        if casou_setor:
            p += 25
        motivos.append(
            "profissão coerente: %s (%d de %d vínculos%s)"
            % (", ".join(funcoes.rotulo_area(x) for x in casadas),
               vinc_na_area, total_v,
               "; setor %s também" % ", ".join(
                   funcoes.rotulo_setor(x) for x in sorted(setor_alvo & setor_cand))
               if casou_setor else ""))
        forca = max(forca, p)

    ddd = alvo.get("ddd")
    if ddd:
        for t in sinais["telefones"]:
            n = re.sub(r"\D", "", str(t.get("telefone") or ""))
            if len(n) >= 10 and n[:2] == ddd:
                motivos.append("telefone com DDD %s da cidade" % ddd)
                forca = max(forca, 20)
                break

    return {"forca": forca, "motivos": motivos, "elimina": elimina}


# limiar de confirmação — SÓ existe para desempatar
FORCA_MINIMA = 50


def decidir(candidatos: list[dict[str, Any]],
            concorrentes: int = 0) -> dict[str, Any]:
    """Escolhe o CPF entre os candidatos avaliados. É AQUI que a regra mora.

    REGRA (definida pela Rebeca): a força mínima só se aplica quando há
    CONCORRÊNCIA — ambiguidade, empate, homônimo. Quem não tem concorrente não
    precisa de contraprova: se sobrou uma pessoa possível, é ela.

    O QUE CONTA COMO CONCORRENTE (também definido pela Rebeca): não é quem a
    Assertiva devolveu na bruta. É quem CHEGOU VIVO até a chamada por nome e
    endereço, depois de já ter passado pelo JBR, pelo WorkAPI de nome, pelo MK
    e pelo RAIS. Essas etapas são gratuitas ou baratas e existem justamente
    para derrubar homônimo antes de gastar. Quem sobreviver a todas elas e
    ainda for único não tem rival nenhum — cobrar contraprova dele é cobrar
    duas vezes pelo mesmo filtro.

    Por que isso importa tanto: no teste das 10 empresas médias, 149 consultas
    renderam 1,6 candidato por perfil — quase todo caso tinha UM nome possível.
    Exigir força >= 50 ali descartou 30 perfis que não eram ambíguos, eram
    apenas gente sem contraprova disponível. O limiar existe para separar duas
    pessoas com o mesmo nome; usado contra uma pessoa sozinha, só joga fora o
    acerto.

    `concorrentes` distingue dois "único" que não são iguais:
        unico            — chegou sozinho na fase paga
        unico_por_corte  — havia rivais aqui e a evidência os eliminou
                           (profissão incompatível, fora da faixa de idade)
    Os dois são aceitos, mas a tela deve mostrar a diferença: o segundo depende
    de o corte ter sido justo.

    `elimina` sempre vale, inclusive contra candidato único: médico não vira
    vendedor por ser o único médico da cidade.
    """
    vivos = [c for c in candidatos if not c.get("elimina")]
    if not vivos:
        return {"cpf": "", "situacao": "todos_eliminados", "confianca": 0,
                "candidatos_vivos": 0}
    vivos.sort(key=lambda c: -int(c.get("forca") or 0))
    melhor = vivos[0]
    base = {"cpf": melhor.get("cpf", ""), "nome": melhor.get("nome", ""),
            "forca": int(melhor.get("forca") or 0),
            "motivos": melhor.get("motivos") or [],
            "candidatos_vivos": len(vivos)}

    if len(vivos) == 1:
        sozinho = concorrentes <= 1
        return {**base,
                "situacao": "unico" if sozinho else "unico_por_corte",
                # sem contraprova a confiança não é 100 — mas é aceito
                "confianca": max(base["forca"], 70 if sozinho else 60),
                "porque": ("chegou sozinho à fase paga, depois de JBR/WorkAPI/"
                           "MK/RAIS — sem concorrente, não precisa de "
                           "contraprova")
                          if sozinho else
                          ("%d candidatos chegaram aqui, %d eliminados por "
                           "evidência — sobrou um"
                           % (concorrentes, concorrentes - 1))}

    # daqui para baixo HÁ concorrência: o limiar entra em cena
    if melhor["forca"] >= FORCA_MINIMA and \
            melhor["forca"] > int(vivos[1].get("forca") or 0):
        return {**base, "situacao": "resolvido_por_evidencia",
                "confianca": base["forca"],
                "porque": "%d candidatos; este ganhou por %d pontos: %s"
                          % (len(vivos),
                             melhor["forca"] - int(vivos[1].get("forca") or 0),
                             "; ".join(base["motivos"][:2]))}
    if melhor["forca"] >= FORCA_MINIMA:
        return {"cpf": "", "situacao": "empatado", "confianca": 0,
                "candidatos_vivos": len(vivos),
                "porque": "%d candidatos empatados em força %d"
                          % (sum(1 for c in vivos
                                 if int(c.get("forca") or 0) == melhor["forca"]),
                             melhor["forca"])}
    return {"cpf": "", "situacao": "ambiguo_sem_evidencia", "confianca": 0,
            "candidatos_vivos": len(vivos),
            "porque": "%d candidatos e nenhum passou de força %d — precisa de "
                      "pista do operador" % (len(vivos), FORCA_MINIMA)}


# ===========================================================================
# ESTRATÉGIA POR PORTE DA EMPRESA
# ===========================================================================
# A cidade só confirma quando a pessoa mora onde trabalha. Medido:
#
#     empresa média (1 estabelecimento) .... 46,1% confirmados pela cidade
#     multinacional (58+ filiais) ..........  2,4%
#
# Vinte vezes menos. Em rede grande o funcionário está espalhado — mora em
# Alphaville e a matriz é em São Paulo, ou se mudou de estado. Insistir no MK
# para conferir cidade lá é gastar cota para não descobrir nada.
#
# O CBO e o vínculo empregatício NÃO dependem de geografia. Em rede grande eles
# viram o caminho principal, não o plano B.
#
# O porte sai de graça do cnpj.db: número de estabelecimentos e de UFs.
# ===========================================================================
# TRÊS FAIXAS DE PORTE, com teto de consulta próprio para cada uma.
#
# Calibradas nas 14 empresas testadas hoje. O corte de duas faixas colocava a
# Sankhya (25 filiais, 9 UFs) junto da Gerdau (184 em 23) — mas a Sankhya rendeu
# como empresa local, 63,2%. Três faixas separam esses casos.
#
#   LOCAL     até 5 filiais e até 2 UFs .... Ploomes, Agendor, Omie, Solides
#             a cidade confirma 46% -> triagem grátis no MK resolve, teto baixo
#   REGIONAL  até 60 filiais ou até 12 UFs .. Sankhya, Embraer, TOTVS, Natura
#             a cidade ajuda em parte; teto médio
#   NACIONAL  acima disso ................... Gerdau, Ambev, Localiza, Magalu
#             a cidade confirma 2,4% -> só o vínculo funciona, e aí vale pagar
#             até 50 consultas por pessoa, porque é o único caminho que existe
#
# O TETO DE 50 É CARO: R$ 5,95 por pessoa. Só se justifica para decisor de
# empresa grande, onde o valor do contato paga a consulta. Para volume, usar
# o teto da faixa local.
FAIXAS = [
    ("local",    5,    2,  4,  60),   # (nome, max_filiais, max_ufs, teto_pago, peso_cidade)
    ("regional", 60,  12, 15,  30),
    ("nacional", 10**9, 99, 50,  0),
]

LIMITE_FILIAIS = 15     # mediana medida: 1 nas médias, 58 nas multinacionais
LIMITE_UFS = 4


def porte_da_empresa(cnpj: str) -> dict[str, Any]:
    """Quantos estabelecimentos e em quantas UFs. Local e grátis.

    Devolve `espalhada`: True quando a cidade deixa de ser sinal confiável.
    """
    base = re.sub(r"\D", "", str(cnpj or ""))[:8]
    if len(base) != 8:
        return {"filiais": 0, "ufs": 0, "espalhada": False, "conhecida": False,
            "faixa": "desconhecida", "teto_pago": MAX_PAGO, "peso_cidade": 60}
    try:
        con = sqlite3.connect("file:%s?mode=ro" % CNPJ_DB, uri=True)
        n, u = con.execute("SELECT COUNT(*), COUNT(DISTINCT uf) FROM "
                           "estabelecimentos WHERE cnpj_basico=?", (base,)).fetchone()
        con.close()
    except Exception:
        return {"filiais": 0, "ufs": 0, "espalhada": False, "conhecida": False,
                "faixa": "desconhecida", "teto_pago": MAX_PAGO, "peso_cidade": 60}
    for nome, max_f, max_u, teto, peso in FAIXAS:
        if n <= max_f and u <= max_u:
            return {"filiais": n, "ufs": u, "conhecida": True, "faixa": nome,
                    "teto_pago": teto, "peso_cidade": peso,
                    "espalhada": nome == "nacional"}
    return {"filiais": n, "ufs": u, "conhecida": True, "faixa": "nacional",
            "teto_pago": 50, "peso_cidade": 0, "espalhada": True}


def estrategia(cnpj: str, cidade_escolhida: str = "", uf_escolhida: str = "",
               nome_empresa: str = "") -> dict[str, Any]:
    """Como buscar, dado o porte da empresa E se o operador já escolheu a cidade.

    O ACHADO QUE MUDA TUDO: a cidade não é só um sinal de confirmação — ela é a
    seleção da FILIAL. Com ela escolhida, a Gerdau de São Paulo é uma empresa
    local: as outras 183 unidades param de existir para a busca, e a cidade
    volta a confirmar em 46% dos casos em vez de 2,4%.

    Por isso o porte NÃO decide quanto gastar. Ele decide se o filtro de cidade
    é OBRIGATÓRIO. Em rede nacional, buscar sem cidade é pagar caro para achar
    pouco; com cidade, custa o mesmo de uma empresa pequena.

    A aba B2B já tem esse filtro. Não precisa de tela nova — precisa exigi-lo
    quando a empresa for grande, e oferecer só as cidades onde ela tem unidade.

    BUSCA POR ESTADO (regra da Rebeca): quem procura "empresa de T.I. em MG"
    não sabe a cidade e não deveria ser obrigado a adivinhar. Com a UF, a rede
    nacional deixa de ser nacional: sobram as unidades daquele estado. Se for
    uma só, o caso já é local. Se forem várias, devolve a LISTA para o operador
    escolher — e `unidade_padrao` diz qual seria usada se ele não escolher,
    seguindo a mesma regra da maior unidade do escopo.
    """
    p = porte_da_empresa(cnpj)
    faixa = p.get("faixa", "desconhecida")
    tem_cidade = bool((cidade_escolhida or "").strip())
    ufa = (uf_escolhida or "").strip().upper()[:2]

    if faixa == "nacional" and not tem_cidade and ufa:
        no_estado = filiais_da_empresa(cnpj, nome_empresa, 30, uf=ufa)
        padrao = unidade_principal(cnpj, uf=ufa)
        if len(no_estado) == 1:
            # um estado, uma cidade: acabou a ambiguidade da rede
            unica = no_estado[0]["cidade"]
            return {**estrategia(cnpj, cidade_escolhida=unica),
                    "modo": "única unidade em %s (%s)" % (ufa, unica.title()),
                    "cidade_resolvida": unica, "filiais_no_estado": no_estado,
                    "unidade_padrao": padrao}
        if no_estado:
            return {**p, "modo": "rede nacional, estado %s" % ufa,
                    "exige_cidade": True, "pode_buscar": False,
                    "escolher_entre": [x["cidade"] for x in no_estado],
                    "filiais_no_estado": no_estado, "unidade_padrao": padrao,
                    "ordem": ["vinculo_cnpj", "razao_social", "cidade",
                              "profissao", "ddd"],
                    "peso_cidade": 30, "teto_pago": 15,
                    "custo_max_brl": round(15 * 0.119, 2),
                    "porque": "%d cidades de %s têm unidade (de %d no país). "
                              "Escolha uma; sem escolher, a busca usa %s."
                              % (len(no_estado), ufa, p["filiais"],
                                 (padrao.get("cidade") or "?").title())}
        # Nenhuma unidade nesta raiz — mas grupo grande fatia a marca em
        # várias raízes. Antes de dizer "não tem nada em MG", procurar as
        # irmãs: a Gerdau de Minas está sob outra raiz, com 172 unidades.
        irmas = raizes_da_marca(nome_empresa or p.get("razao", ""), ufa) \
            if (nome_empresa or "").strip() else []
        irmas = [x for x in irmas
                 if x["raiz"] != re.sub(r"\D", "", str(cnpj or ""))[:8]]
        if irmas:
            outra = irmas[0]
            alt = estrategia(outra["raiz"] + "0001", uf_escolhida=ufa,
                             nome_empresa=nome_empresa)
            return {**alt, "raiz_trocada": outra["raiz"],
                    "raizes_da_marca": irmas,
                    "porque": "a razão social que o nome resolve não tem "
                              "unidade em %s, mas %s tem %d — usando essa "
                              "raiz. %s" % (ufa, outra["razao"][:40],
                                            outra["unidades"],
                                            alt.get("porque", ""))}
        return {**p, "modo": "sem unidade em %s" % ufa,
                "exige_cidade": True, "pode_buscar": False,
                "filiais_no_estado": [], "unidade_padrao": padrao,
                "ordem": ["vinculo_cnpj", "razao_social", "profissao"],
                "peso_cidade": 0, "teto_pago": 50,
                "custo_max_brl": round(50 * 0.119, 2),
                "porque": "nenhuma unidade ativa em %s. %s" % (ufa,
                          padrao.get("aviso") or "Escolha outra cidade.")}

    if faixa == "nacional" and not tem_cidade:
        return {**p, "modo": "rede nacional SEM cidade",
                "exige_cidade": True, "pode_buscar": False,
                "ordem": ["vinculo_cnpj", "razao_social", "profissao"],
                "peso_cidade": 0, "teto_pago": 50,
                "custo_max_brl": round(50 * 0.119, 2),
                "porque": "%d unidades em %d UFs. Sem escolher a cidade, a "
                          "confirmação cai para 2,4%% e cada pessoa custa até "
                          "R$ 5,95. Escolha a unidade ou ao menos o estado."
                          % (p["filiais"], p["ufs"])}

    if tem_cidade:
        # com a filial escolhida, qualquer porte vira caso local
        return {**p, "modo": "unidade escolhida (%s)" % cidade_escolhida,
                "exige_cidade": False, "pode_buscar": True,
                "ordem": ["vinculo_cnpj", "razao_social", "cidade", "profissao", "ddd"],
                "peso_cidade": 60, "teto_pago": 4,
                "custo_max_brl": round(4 * 0.119, 2),
                "porque": "cidade definida — a busca fica local e a confirmação "
                          "volta a valer, mesmo numa rede de %d unidades"
                          % p["filiais"]}

    if faixa == "regional":
        return {**p, "modo": "rede regional", "exige_cidade": False,
                "pode_buscar": True,
                "ordem": ["vinculo_cnpj", "razao_social", "cidade", "profissao", "ddd"],
                "peso_cidade": 30, "teto_pago": 15,
                "custo_max_brl": round(15 * 0.119, 2),
                "porque": "%d unidades em %d UFs — escolher a cidade melhora, "
                          "mas não é obrigatório" % (p["filiais"], p["ufs"])}

    return {**p, "modo": "empresa local", "exige_cidade": False,
            "pode_buscar": True,
            "ordem": ["vinculo_cnpj", "razao_social", "cidade", "profissao", "ddd"],
            "peso_cidade": 60, "teto_pago": 4,
            "custo_max_brl": round(4 * 0.119, 2),
            "porque": "%d estabelecimento(s) — a cidade confirma em 46%% dos casos"
                      % p["filiais"]}


def filiais_da_empresa(cnpj: str, nome_empresa: str = "",
                       limite: int = 20, uf: str = "") -> list[dict[str, Any]]:
    """As UNIDADES da empresa agrupadas por CIDADE, para o operador escolher.

    Com `uf`, lista só as unidades daquele estado. É o caso "empresa de T.I.
    em MG": o operador não quer escolher entre as 119 cidades do país, quer ver
    as 6 de Minas.

    Por que por cidade e não por CNPJ: a Ambev tem 8 estabelecimentos só em São
    Paulo e 119 no país. Listar CNPJ a CNPJ é ilegível — ninguém prospecta a
    "07526557010920", prospecta "a Ambev de Jaguariúna". A cidade é a unidade
    que a operação usa e é também o sinal que precisamos de volta.

    Por que isso vem ANTES de buscar, em rede grande: saber a cidade devolve o
    sinal que confirma 46% dos casos em empresa local, contra 2,4% em rede
    espalhada. Uma pergunta ao operador substitui R$ 5,95 de consultas.

    `perfis_no_cache` conta gente DAQUELA EMPRESA naquela cidade — antes eu
    contava todo mundo da cidade, e São Paulo aparecia com 1.279 em toda linha.
    """
    base = re.sub(r"\D", "", str(cnpj or ""))[:8]
    if len(base) != 8:
        return []
    ufa = (uf or "").strip().upper()[:2]
    try:
        con = sqlite3.connect("file:%s?mode=ro" % CNPJ_DB, uri=True)
        linhas = con.execute(
            "SELECT COALESCE(l.descricao,''), e.uf, COUNT(*), "
            "       MAX(CASE WHEN e.matriz_filial='1' THEN 1 ELSE 0 END), "
            "       MIN(e.cnpj) "
            "FROM estabelecimentos e "
            "LEFT JOIN lookup l ON l.tipo='municipio' AND l.codigo=e.municipio "
            "WHERE e.cnpj_basico=? AND e.situacao='02' "
            + ("AND e.uf=? " if ufa else "") +
            "GROUP BY l.descricao, e.uf",
            ((base, ufa) if ufa else (base,))).fetchall()
        con.close()
    except Exception:
        return []

    # gente DESSA empresa por cidade, no cache do LinkedIn
    peso = {}
    if nome_empresa:
        try:
            lc = sqlite3.connect(
                "file:%s?mode=ro" % os.path.join(
                    os.environ.get("CNPJ_DB_DIR", "/capiblu_data"),
                    "linkedin_cache.db"), uri=True)
            chave = "%" + " ".join(_norm(nome_empresa).split()[:2]).lower() + "%"
            for cid, q in lc.execute(
                    "SELECT cidade, COUNT(*) FROM perfis WHERE pais='BR' "
                    "AND cidade<>'' AND empresa_norm LIKE ? GROUP BY cidade",
                    (chave,)):
                c = cidade_do_linkedin(cid)
                peso[c] = peso.get(c, 0) + q
            lc.close()
        except Exception:
            pass

    saida = []
    for nome_mun, uf, n, tem_matriz, um_cnpj in linhas:
        cidade = _norm(nome_mun)
        if not cidade:
            continue
        saida.append({"cidade": cidade, "uf": uf, "unidades": n,
                      "matriz": bool(tem_matriz), "cnpj_exemplo": um_cnpj,
                      "perfis_no_cache": peso.get(cidade, 0)})
    # onde já temos gente mapeada vem primeiro; depois matriz; depois tamanho
    saida.sort(key=lambda x: (-x["perfis_no_cache"], not x["matriz"],
                              -x["unidades"]))
    return saida[:limite]


def raizes_da_marca(nome_empresa: str, uf: str = "",
                    limite: int = 6) -> list[dict[str, Any]]:
    """As RAÍZES de CNPJ que carregam a mesma marca — opcionalmente numa UF.

    POR QUE ISSO EXISTE: `filiais_da_empresa` lista por raiz de CNPJ, e grupo
    grande fatia a marca em várias raízes. "Gerdau em MG" dava ZERO unidade,
    porque a raiz que o nome resolve é a GERDAU S.A. (a holding, matriz em SP)
    — enquanto as 172 unidades mineiras estão sob GERDAU AÇOS LONGOS S.A., raiz
    07358761. Sem isto, a busca por estado descartava a operação inteira do
    estado e dizia ao operador que não havia nada lá.

    O corte contra ruído: a marca tem que ser a PRIMEIRA palavra significativa
    da razão ou do fantasia. Sem isso, "gerdau" trazia a Potamos Engenharia e o
    Museu das Minas (que só citam a marca), e "ambev" trazia uma associação de
    moradores. Um MEI chamado "Gerdau Bezerra do Valle" ainda passa — mas tem 1
    unidade e cai para o fim da ordem, que é por tamanho.
    """
    marca = _norm(nome_empresa).split()
    if not marca:
        return []
    termo = marca[0].lower()
    if len(termo) < 3:
        return []
    ufa = (uf or "").strip().upper()[:2]
    fts = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"),
                       "cnpj_fts.db")
    try:
        con = sqlite3.connect("file:%s?mode=ro" % fts, uri=True)
        sql = ("SELECT substr(cnpj,1,8), razao, fantasia, COUNT(*) "
               "FROM estab_fts WHERE estab_fts MATCH ? AND situacao='02' "
               + ("AND uf=? " if ufa else "") +
               "GROUP BY substr(cnpj,1,8) ORDER BY COUNT(*) DESC LIMIT 40")
        args = ("razao:%s OR fantasia:%s" % (termo, termo),)
        linhas = con.execute(sql, args + ((ufa,) if ufa else ())).fetchall()
        con.close()
    except Exception:
        return []

    def comeca_com(texto: str) -> bool:
        # descarta tokens iniciais só de dígitos/pontuação (razão de MEI vem
        # como "54.449.847 FULANO"), depois compara a primeira palavra real
        for t in _norm(texto).split():
            if re.sub(r"\D", "", t) == t.replace(".", "").replace("-", ""):
                continue
            return t == marca[0]
        return False

    saida = []
    for base, razao, fantasia, n in linhas:
        if not (comeca_com(razao or "") or comeca_com(fantasia or "")):
            continue
        saida.append({"raiz": base, "razao": razao or "", "unidades": n})
    return saida[:limite]


def precisa_escolher_filial(cnpj: str) -> bool:
    """Em rede nacional, perguntar a unidade sai mais barato que varrer.

    Uma pergunta ao operador contra R$ 5,95 de consultas por pessoa — e com
    resultado melhor, porque devolve o sinal de cidade que a rede tinha tirado.
    """
    return porte_da_empresa(cnpj).get("faixa") == "nacional"


def unidade_principal(cnpj: str, cidade: str = "", uf: str = "") -> dict[str, Any]:
    """A unidade que representa a empresa na busca, no escopo mais estreito.

    REGRA (definida pela Rebeca): a menos que o usuário informe um CNPJ
    específico, usar só a MAIOR unidade do escopo disponível — cidade, senão
    estado, senão país. Buscar contra as 1.913 lojas do Magazine Luiza ao mesmo
    tempo não ajuda ninguém; a unidade principal daquele escopo basta.

    "Maior" é um proxy, e vale dizer por quê: a base da Receita NÃO traz número
    de funcionários por estabelecimento. Uso, nesta ordem:
        1. matriz         — é onde a estrutura corporativa e os decisores ficam
        2. mais antiga    — unidade consolidada, não recém-aberta
    Se aparecer uma fonte com headcount por CNPJ, é aqui que ela entra.

    `escopo` diz qual filtro pegou, para a tela poder mostrar.
    """
    base = re.sub(r"\D", "", str(cnpj or ""))[:8]
    if len(base) != 8:
        return {}
    cid, ufa = _norm(cidade), (uf or "").upper()[:2]
    try:
        con = sqlite3.connect("file:%s?mode=ro" % CNPJ_DB, uri=True)
        linhas = con.execute(
            "SELECT e.cnpj, e.matriz_filial, e.uf, e.data_inicio, "
            "       COALESCE(l.descricao,''), e.ddd1, e.tel1 "
            "FROM estabelecimentos e "
            "LEFT JOIN lookup l ON l.tipo='municipio' AND l.codigo=e.municipio "
            "WHERE e.cnpj_basico=? AND e.situacao='02'", (base,)).fetchall()
        con.close()
    except Exception:
        return {}
    if not linhas:
        return {}

    def campo(r):
        cidade_est = _norm(r[4])
        return {"cnpj": r[0], "matriz": str(r[1]) == "1", "uf": r[2],
                "desde": r[3], "cidade": cidade_est,
                # O DDD sai do MAPA da cidade, não do telefone declarado pelo
                # estabelecimento: a loja do Magazine Luiza em Salvador declara
                # o telefone da sede em Franca e devolvia DDD 16 para a Bahia.
                "ddd": ddd_da_cidade(cidade_est, r[2]),
                "ddd_declarado": re.sub(r"\D", "", str(r[5] or ""))[:2]}

    todas = [campo(r) for r in linhas]
    # escopo mais estreito que ainda tenha unidade
    for nome_escopo, filtro in (
            ("cidade", lambda x: cid and x["cidade"] == cid),
            ("estado", lambda x: ufa and x["uf"] == ufa),
            ("pais", lambda x: True)):
        cand = [x for x in todas if filtro(x)]
        if cand:
            # matriz primeiro; depois a mais antiga
            cand.sort(key=lambda x: (not x["matriz"], str(x["desde"] or "9999")))
            e = cand[0]
            # Quando o operador pediu uma cidade e não há unidade lá, a regra
            # cai para o estado — e isso PRECISA aparecer. Sem o aviso, ele
            # pede Porto Alegre, recebe Sapucaia do Sul e não fica sabendo.
            aviso = ""
            if cid and nome_escopo != "cidade":
                aviso = ("não há unidade ativa em %s; usando %s (%s)"
                         % (cidade.strip(), e["cidade"].title(), nome_escopo))
            elif ufa and nome_escopo == "pais":
                aviso = ("não há unidade ativa em %s; usando a matriz em %s"
                         % (ufa, e["cidade"].title()))
            return {**e, "escopo": nome_escopo, "unidades_no_escopo": len(cand),
                    "total_unidades": len(todas), "aviso": aviso,
                    "atendeu_pedido": not aviso}
    return {}
