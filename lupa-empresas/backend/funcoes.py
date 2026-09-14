# -*- coding: utf-8 -*-
"""Dicionário de funções profissionais: sinônimos, siglas e flexões.

POR QUE EXISTE: o classificador anterior usava `\\b` no fim do radical, e
`\\bvend\\b` NUNCA casa com "vendedor" — a palavra continua depois. Resultado:
dois vendedores de comércio varejista foram classificados como "financeiro" e
"administrativo", e a família VENDAS — a mais importante para a operação da BLU
— ficou cega em todos os testes de um dia inteiro.

REGRA DESTE MÓDULO: o termo é um RADICAL, casado por prefixo de palavra.
"vend" pega vendedor, vendedora, vendas, vendendo. Nunca colocar `\\b` no fim de
algo que flexiona em português.

TRÊS VOCABULÁRIOS CONVIVEM aqui, e é de propósito:
  1. como a pessoa escreve no LinkedIn ...... "BDR", "Head of Growth", "Closer"
  2. como o CBO da Assertiva escreve ........ "Vendedor de comércio varejista"
  3. como a Receita descreve o setor ........ "Comércio varejista de..."
Os três aparecem no mesmo fluxo, e um termo de um não casa com o outro.

Os radicais foram tirados dos 4.000 cargos reais do cache, não inventados.
"""
import re
import unicodedata

# ---------------------------------------------------------------------------
# ÁREAS. Cada uma: rótulo humano + radicais (prefixo de palavra) + siglas
# (palavra inteira, porque sigla curta gera falso positivo em substring).
# ---------------------------------------------------------------------------
AREAS: dict[str, dict] = {
    "vendas": {
        "rotulo": "Comercial e Vendas",
        "radicais": [
            "vend",            # vendedor, vendedora, vendas
            "comerci",         # comercial, comerciante, comerciário
            "represent",       # representante comercial
            "revend",          # revendedor
            "negoci",          # negócios, negociação
            "prospec",         # prospecção
            "captac",          # captação
            "closer", "hunter", "farmer",
            "account", "sales", "selling", "seller",
            "business develop", "new business", "inside sales", "field sales",
            "pre-vend", "pre vend", "pos-vend", "pos vend",
            "balconist", "atendente comercial", "promotor de vend",
            "corretor", "consultor de vend", "executivo de cont",
            "key account", "growth",
        ],
        "siglas": ["bdr", "sdr", "ae", "ov", "kam"],
    },
    "atendimento": {
        "rotulo": "Atendimento e Sucesso do Cliente",
        "radicais": [
            "atendiment", "atendente", "suporte", "help desk", "helpdesk",
            "call center", "callcenter", "telemarketing", "teleatend",
            "relacionament", "ouvidor", "customer success", "customer service",
            "customer experience", "pos-venda", "recepcionist",
        ],
        "siglas": ["cs", "cx", "sac"],
    },
    "marketing": {
        "rotulo": "Marketing e Comunicação",
        "radicais": [
            "marketing", "comunicac", "publicid", "propagand", "midia",
            "social media", "conteud", "branding", "brand", "design",
            "designer", "criacao", "audiovisual", "trafego pago", "seo",
            "assessoria de impren", "endomarketing", "produtor de conteud",
        ],
        "siglas": ["mkt"],
    },
    "ti": {
        "rotulo": "Tecnologia da Informação",
        "radicais": [
            "desenvolvedor", "desenvolviment de sistem", "programad",
            "software", "sistem de informac", "analista de sistem",
            "banco de dados", "infraestrutura de ti", "redes de computad",
            "seguranca da informac", "cientista de dados", "engenheiro de dados",
            "engenheiro de software", "devops", "sre", "qa", "tester",
            "front-end", "frontend", "back-end", "backend", "full stack",
            "fullstack", "mobile", "cloud", "suporte tecnic de ti",
            "product owner", "scrum",
            # inglês: a auditoria achou 40+ cargos em inglês sem classificação
            "business intelligence", "data scien", "data engineer",
            "data analyst", "machine learning", "artificial intelligence",
            "project management", "product manag", "tech lead", "engineer de",
            "software engineer", "web develop", "site reliability",
            "cyber security", "cibersegur", "analytics",
        ],
        "siglas": ["ti", "it", "dba", "po", "bi", "ml", "ia", "pm"],
    },
    "engenharia": {
        "rotulo": "Engenharia e Projetos",
        "radicais": [
            "engenheir", "engenharia", "projetist", "arquitet", "topograf",
            "desenhista tecnic", "tecnic em edificac", "obras civis",
            "planejament de obra", "manutenc industrial", "automac",
            "metrolog", "instrument",
        ],
        "siglas": [],
    },
    "financeiro": {
        "rotulo": "Financeiro e Contábil",
        "radicais": [
            "financ", "contab", "contador", "fiscal", "tesour", "tributari",
            "faturament", "cobranc", "credito", "auditor", "custos",
            "controlad", "orcament", "caixa", "bancari", "investiment",
            "analista de credit", "escritur",
        ],
        "siglas": ["cfo", "fpa"],
    },
    "rh": {
        "rotulo": "Recursos Humanos",
        "radicais": [
            "recursos human", "recrutad", "recrutament", "selecao de pessoal",
            "departament pessoal", "folha de pagament", "treinament e desenvolv",
            "business partner de rh", "talent", "people", "cargos e salari",
            "seguranca do trabalh", "medicina do trabalh",
        ],
        "siglas": ["rh", "hr", "dp", "bp"],
    },
    "juridico": {
        "rotulo": "Jurídico",
        "radicais": [
            "advogad", "juridic", "paralegal", "procurador", "defensor",
            "tabeli", "cartori", "compliance", "contrato",
        ],
        "siglas": ["oab"],
    },
    "saude": {
        "rotulo": "Saúde",
        "radicais": [
            "medic", "enfermeir", "enfermagem", "fisioterap", "farmaceutic",
            "dentist", "odontolog", "psicolog", "nutricion", "biomedic",
            "fonoaudiolog", "terapeuta", "veterinari", "tecnic de enfermag",
            "radiolog", "socorrist", "cuidador",
        ],
        "siglas": ["crm", "coren"],
    },
    "educacao": {
        "rotulo": "Educação",
        "radicais": [
            "professor", "docente", "pedagog", "instrutor", "educador",
            "tutor", "coordenador pedagog", "diretor de escol", "monitor de turm",
            "orientador educac",
        ],
        "siglas": [],
    },
    "logistica": {
        "rotulo": "Logística e Suprimentos",
        "radicais": [
            "logistic", "estoqu", "almoxarif", "expedic", "armazenag",
            "motorist", "entregad", "transport", "frota", "suprimen",
            "compras", "comprador", "supply", "planejament de demanda",
            "conferente", "empilhadeir", "distribuic",
            "correios", "carteir", "servicos postai", "encomend",
        ],
        "siglas": ["pcp", "ect"],
    },
    "producao": {
        "rotulo": "Produção e Operações",
        "radicais": [
            "producao", "operador de maquin", "operador de produc", "montador",
            "soldador", "torneiro", "mecanic", "eletricist", "manutenc",
            "pedreir", "servent", "ajudante geral", "auxiliar de produc",
            "encarregado de obra", "qualidade", "inspetor",
        ],
        "siglas": [],
    },
    "seguranca": {
        "rotulo": "Segurança",
        "termos_nota": "47 ocorrências na auditoria e nenhuma área cobria",
        "radicais": [
            "vigilant", "seguranca patrimonial", "seguranca privada",
            "porteir", "controlador de acess", "guarda", "brigadist",
            "agente de seguranc", "monitorament de alarm", "escolt",
            "seguranca do event",
        ],
        "siglas": [],
    },
    "militar": {
        "rotulo": "Militar e Defesa",
        "radicais": [
            "exercito", "marinha", "aeronautic", "forcas armadas", "cabo",
            "sargento", "tenente", "capitao", "soldado", "fuzileir",
            "policia militar", "policia civil", "policia federal",
            "bombeir militar", "cadete", "aman", "espcex",
        ],
        "siglas": ["pm", "pf", "prf", "cbm"],
    },
    "administrativo": {
        "rotulo": "Administrativo",
        "radicais": [
            "administrativ", "administrador", "escritori", "secretari",
            "auxiliar administrativ", "assistente administrativ", "recepc",
            "arquiv", "protocol", "expedient", "office",
        ],
        "siglas": [],
    },
    "agro": {
        "rotulo": "Agronegócio",
        "radicais": [
            "agronom", "agricol", "pecuari", "zootecnic", "tratorist",
            "agropecuari", "rural", "florest", "veterinari de camp",
        ],
        "siglas": [],
    },
    "publico": {
        "rotulo": "Serviço Público",
        "radicais": [
            "servidor public", "prefeitura", "secretaria municipal",
            "dirigente do servic public", "agente public", "guarda municipal",
            "policial", "militar", "bombeir", "fiscal de post",
        ],
        "siglas": [],
    },
}

# ---------------------------------------------------------------------------
# SENIORIDADE. Ortogonal à área: "Gerente Comercial" é gerencia + vendas.
# ---------------------------------------------------------------------------
NIVEIS: dict[str, dict] = {
    "clevel": {"rotulo": "Alta direção", "peso": 6,
               "radicais": ["presidente", "founder", "co-founder", "cofundador",
                            "fundador", "proprietari", "socio-administrador",
                            "socio administrador", "owner", "chief", "board",
                            "conselheir"],
               "siglas": ["ceo", "cfo", "coo", "cto", "cio", "cmo", "chro", "cro"]},
    "diretoria": {"rotulo": "Diretoria", "peso": 5,
                  "radicais": ["diretor", "diretora", "superintendent",
                               "vice-presidente", "vice presidente", "head of",
                               "head de"],
                  "siglas": ["vp", "head"]},
    "gerencia": {"rotulo": "Gerência", "peso": 4,
                 "radicais": ["gerente", "gerencia", "gestor", "gestora",
                              "manager", "gerenciament"],
                 "siglas": []},
    "coordenacao": {"rotulo": "Coordenação", "peso": 3,
                    "radicais": ["coordenador", "coordenac", "supervisor",
                                 "supervis", "encarregad", "lider", "lideranc",
                                 "chefe", "team lead", "tech lead"],
                    "siglas": ["lead"]},
    "especialista": {"rotulo": "Especialista", "peso": 2,
                     "radicais": ["especialist", "consultor", "analista",
                                  "senior", "pleno", "expert", "principal"],
                     "siglas": []},
    "operacional": {"rotulo": "Operacional", "peso": 1,
                    "radicais": ["assistente", "auxiliar", "operador",
                                 "tecnic", "junior", "ajudante", "atendente",
                                 "aprendiz de"],
                    "siglas": []},
    "entrada": {"rotulo": "Entrada", "peso": 0,
                "radicais": ["estagiari", "estagio", "trainee", "aprendiz",
                             "bolsist", "voluntari", "aluno", "estudante"],
                "siglas": []},
}

# ---------------------------------------------------------------------------
# PARES QUE NUNCA SÃO A MESMA PESSOA. Usados para ELIMINAR candidato.
# Conservador de propósito: eliminar errado descarta a pessoa certa, e esse
# erro é invisível. Só entram pares que exigem formação/registro excludente.
# ---------------------------------------------------------------------------
INCOMPATIVEIS = [
    ("saude", "vendas"), ("saude", "ti"), ("saude", "logistica"),
    ("saude", "producao"), ("saude", "juridico"), ("saude", "engenharia"),
    ("juridico", "vendas"), ("juridico", "ti"), ("juridico", "producao"),
    ("juridico", "logistica"), ("juridico", "saude"),
    ("educacao", "producao"), ("educacao", "logistica"),
    ("agro", "ti"), ("agro", "juridico"), ("agro", "saude"),
]


def _norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9 ]+", " ", s.lower())


def _casa(texto_norm: str, grupo: dict) -> bool:
    """Radical casa por PREFIXO DE PALAVRA; sigla casa por palavra inteira."""
    for r in grupo.get("radicais", ()):
        if re.search(r"(^|\s)" + re.escape(r), texto_norm):
            return True
    for s in grupo.get("siglas", ()):
        if re.search(r"(^|\s)" + re.escape(s) + r"($|\s)", texto_norm):
            return True
    return False


def areas(texto) -> set:
    """Áreas profissionais mencionadas no texto. Pode devolver mais de uma."""
    t = " " + _norm(texto) + " "
    return {k for k, g in AREAS.items() if _casa(t, g)}


def nivel(texto) -> tuple[str, int]:
    """Senioridade mais ALTA mencionada. ('', -1) quando não dá pra dizer."""
    t = " " + _norm(texto) + " "

    # VICE-PRESIDENTE É DIRETORIA, NÃO PRESIDÊNCIA.
    #
    # O radical "presidente" do C-level casa por prefixo de PALAVRA, e em
    # "vice presidente" a palavra "presidente" está lá inteira -- então um VP
    # era classificado como alta direção, acima de Diretor. Consequência
    # medida: procurar por "diretor" não achava "Vice-Presidente de Vendas",
    # que é exatamente o cargo que se procura. Só o C-level enxerga o texto
    # com a palavra colada; a diretoria continua casando pelo radical dela.
    t_clevel = (t.replace(" vice presidente", " vicepresidente")
                 .replace(" vice presidencia", " vicepresidencia"))
    achados = [(g["peso"], k) for k, g in NIVEIS.items()
               if _casa(t_clevel if k == "clevel" else t, g)]
    if not achados:
        return "", -1
    peso, chave = max(achados)
    return chave, peso



# ---------------------------------------------------------------------------
# SETORES. O LinkedIn gera sozinho rótulos como "Profissional de Varejo" quando
# a pessoa não escreve cargo — é 40% do que ficava sem classificação. O texto
# depois de "Profissional de" é SETOR, não cargo, mas mapeia para área.
# Também cobre "Bacharel em Direito", "Formado em Enfermagem".
# ---------------------------------------------------------------------------
SETORES = {
    "vendas":        ["varejo", "atacad", "bens de consumo", "e-commerce",
                      "ecommerce", "comercio"],
    "producao":      ["construc", "industria", "manufatur", "metalurg",
                      "quimic", "textil", "automotiv", "papel e celulose",
                      "alimentos e bebidas", "mineracao", "petroleo", "energia"],
    "ti":            ["tecnologia da informac", "software e servic",
                      "telecomunicac", "internet", "computac"],
    "saude":         ["saude", "hospitalar", "farmaceutic", "bem-estar",
                      "educacao fisica", "medicin", "odontolog", "enfermagem"],
    "financeiro":    ["servicos financeir", "bancari", "seguros", "contabil",
                      "financas", "ciencias contabeis", "economia"],
    "educacao":      ["ensino", "educac", "pedagogia", "universidad", "escola"],
    "juridico":      ["direito", "juridic", "advocacia"],
    "logistica":     ["transporte", "logistic", "armazenag", "aviac",
                      "maritim", "rodoviari"],
    "engenharia":    ["engenharia", "arquitetura", "imobiliari"],
    "marketing":     ["publicidade", "midia", "entretenim", "design grafic"],
    "rh":            ["recursos human", "recrutamento", "gestao de pessoas"],
    "agro":          ["agricultura", "agropecuari", "agronegoci", "agronomia"],
    "administrativo":["administrac", "gestao empresarial", "servicos"],
    "publico":       ["governo", "administracao public", "setor public"],
}

# Onde o setor costuma aparecer: depois destes marcadores.
_MARCADORES = re.compile(
    r"(?:profissional de|especialista em|bacharel em|formad[oa] em|"
    r"graduad[oa] em|tecnolog[oa] em|licenciatura em|setor de|area de)\s+(.{3,60})")


def setores(texto) -> set:
    """Áreas deduzidas do SETOR ou da FORMAÇÃO, quando não há cargo.

    Vale menos que o cargo: dizer "Profissional de Varejo" não é dizer que
    vende — pode ser o contador da loja. Por isso é sinal de apoio, e quem
    consome deve saber disso.
    """
    t = _norm(texto)
    trechos = [t] + _MARCADORES.findall(t)
    achados = set()
    for area, termos in SETORES.items():
        for trecho in trechos:
            if any(re.search(r"(^|\s)" + re.escape(x), trecho) for x in termos):
                achados.add(area)
                break
    return achados


def classificar(texto) -> dict:
    """Leitura completa de um cargo: área, de onde veio, e senioridade.

    `origem` importa na hora de comparar candidatos: área vinda do CARGO é
    evidência; vinda do SETOR é pista.
    """
    a = areas(texto)
    if a:
        origem = "cargo"
    else:
        a = setores(texto)
        origem = "setor" if a else "nenhuma"
    k, p = nivel(texto)
    return {"areas": a, "origem": origem, "nivel": k, "peso": p,
            "decisor": p >= 3}


def rotulo_area(chave: str) -> str:
    return AREAS.get(chave, {}).get("rotulo", chave)


def incompativel(a: set, b: set) -> bool:
    """As duas áreas se excluem? Se houver qualquer sobreposição, NÃO."""
    if not a or not b or (a & b):
        return False
    return any((u in a and v in b) or (v in a and u in b) for u, v in INCOMPATIVEIS)


def decisor(texto) -> bool:
    """Coordenação para cima."""
    return nivel(texto)[1] >= 3


# ===========================================================================
# CATALOGO DE CARGOS DE DECISAO — para o operador escolher na tela
# ===========================================================================
# Existe porque "decisor" não é uma coisa só. Quem vende software de RH quer
# falar com o Head de Gente; quem vende maquinário quer o Gerente Industrial.
# Oferecer só o botão "decisores" faz a lista vir com os dois e o SDR filtrar
# no olho.
#
# A lista sai do próprio dicionário (NIVEIS × AREAS), não de uma tabela solta:
# assim, quando um radical novo entra no classificador, ele aparece aqui
# sozinho — e o que a tela oferece nunca diverge do que o filtro entende.
NIVEIS_DECISAO = ("clevel", "diretoria", "gerencia", "coordenacao")


def catalogo_decisores() -> dict:
    """Cargos de decisão que a tela pode oferecer, agrupados.

    Devolve:
      niveis  os quatro degraus de decisão, com o peso (para ordenar)
      areas   as 17 áreas, com rótulo legível
      cargos  as combinações concretas — "Diretor Comercial", "Gerente de TI" —
              com os TERMOS que o filtro usa, para a tela mandar de volta o que
              o backend entende sem tradução no meio
    """
    niveis = [{"chave": k, "rotulo": NIVEIS[k]["rotulo"],
               "peso": NIVEIS[k]["peso"],
               "termos": sorted(set(NIVEIS[k]["radicais"] + NIVEIS[k]["siglas"]))}
              for k in NIVEIS_DECISAO]

    areas = [{"chave": a, "rotulo": rotulo_area(a)} for a in sorted(AREAS)]

    # combinações: nível × área. Só as que fazem sentido dizer em voz alta —
    # "Estagiário de Diretoria" não existe, e por isso o nível já vem filtrado.
    cargos = []
    for n in niveis:
        for a in areas:
            cargos.append({
                "id": "%s:%s" % (n["chave"], a["chave"]),
                "rotulo": "%s · %s" % (n["rotulo"], a["rotulo"]),
                "nivel": n["chave"], "area": a["chave"],
            })
    return {"niveis": niveis, "areas": areas, "cargos": cargos}


# A TELA fala "diretor", o dicionário fala "diretoria". São as duas linguagens
# do mesmo degrau, e traduzir aqui é melhor que renomear os botões: os valores
# `data-c` da tela já vão para outros filtros que casam por pedaço do nome do
# cargo, e mexer neles quebraria esses.
APELIDO_NIVEL = {
    "diretor": "diretoria", "diretora": "diretoria", "direcao": "diretoria",
    "gerente": "gerencia", "gestor": "gerencia",
    "coordenador": "coordenacao", "coordenacao": "coordenacao",
    "presidente": "clevel", "socio": "clevel", "administrador": "clevel",
    "representante": "clevel", "ceo": "clevel", "c-level": "clevel",
}


def casa_escolha(texto, escolhas: list) -> bool:
    """O cargo casa com alguma escolha da tela?

    `escolhas` aceita três formas, porque a tela pode mandar qualquer uma:
      "gerencia"          só o nível
      "vendas"            só a área
      "gerencia:vendas"   nível E área juntos
    Lista vazia = sem filtro, tudo passa. É o padrão, e é deliberado: filtro
    que começa restringindo esconde resultado de quem não sabe que ele existe.
    """
    if not escolhas:
        return True
    n = nivel(texto)[0]
    a = areas(texto)
    for e in escolhas:
        e = str(e or "").strip().lower()
        if not e:
            continue
        if ":" in e:
            en, ea = e.split(":", 1)
            en = APELIDO_NIVEL.get(en, en)
            if n == en and ea in a:
                return True
        elif APELIDO_NIVEL.get(e, e) in NIVEIS:
            if n == APELIDO_NIVEL.get(e, e):
                return True
        elif e in AREAS:
            if e in a:
                return True
    return False


# Os 23 DEPARTAMENTOS da tela (vocabulário copiado da Datastone, em
# `cargos.DEPARTAMENTOS`) contra as 17 ÁREAS deste dicionário. São listas
# diferentes feitas para fins diferentes, e a ponte tem que ser explícita:
# sem ela, escolher "TI (Tecnologia da Informação)" na tela não produzia termo
# de busca nenhum e o filtro passava batido, sem erro.
#
# Seis departamentos não têm área correspondente e caem para "" de propósito:
# Consultoria e Imobiliário não são função, são setor; Planejamento, Projetos,
# Qualidade e P&D atravessam todas as áreas. Forçá-los numa área daria filtro
# errado com cara de certo.
DEPARTAMENTO_PARA_AREA = {
    # As chaves estão como `_norm()` as produz: ele troca / ( ) & , por espaço,
    # então "Comercial/Vendas" chega aqui como "comercial vendas". Escrever a
    # chave com a barra fazia metade do mapa nunca casar, em silêncio.
    "administrativo": "administrativo",
    "agronegocios": "agro",
    "atendimento suporte ao cliente": "atendimento",
    "educacao": "educacao",
    "engenharia": "engenharia",
    "logistica suprimentos": "logistica",
    "manutencao": "producao",
    "operacoes producao": "producao",
    "pesquisa desenvolvimento p d": "engenharia",
    "projetos": "engenharia",
    "qualidade": "producao",
    "saude": "saude",
    "seguranca saude e meio ambiente": "seguranca",
    "varejo": "vendas",
    "comercial vendas": "vendas",
    "financeiro contabil": "financeiro",
    "ti tecnologia da informacao": "ti",
    "marketing comunicacao": "marketing",
    "recursos humanos": "rh",
}


def area_do_departamento(departamento: str) -> str:
    """Nome do departamento da tela -> chave de área deste dicionário, ou ""."""
    d = " ".join(_norm(departamento).lower().split())
    if d in AREAS:
        return d
    return DEPARTAMENTO_PARA_AREA.get(d, "")


def termos_para_busca(area_ou_departamento: str, teto: int = 4) -> list[str]:
    """Radicais de uma área, prontos para filtrar `position` na Bright Data.

    ESCOLHA DE CUSTO (decisão da Rebeca): mandar os termos como filtro na
    consulta é mais barato e menos preciso que puxar tudo e classificar aqui.
    Mais barato porque a Bright Data cobra por registro ENTREGUE — filtrando
    lá, só chega quem interessa. Menos preciso porque o `or` deles aceita no
    máximo 4 termos, e uma área tem dezenas de radicais.

    Então este teto de 4 não é detalhe de implementação: é o filtro inteiro.
    Os quatro escolhidos são os PRIMEIROS da lista de radicais, que estão em
    ordem de frequência nos 4.000 cargos reais do cache — "vend" antes de
    "key account". Perde-se a cauda longa; ganha-se não pagar por ela.
    """
    a = area_do_departamento(area_ou_departamento)
    d = AREAS.get(a)
    if not d:
        return []
    # radicais primeiro (casam por prefixo, pegam flexão); siglas só se sobrar
    return (d["radicais"] + d["siglas"])[:teto]


if __name__ == "__main__":
    # Casos que já falharam de verdade neste projeto.
    CASOS = [
        ("Vendedor de comércio varejista", {"vendas"}),
        ("BDR | outbound prospecting", {"vendas"}),
        ("SDR", {"vendas"}),
        ("Gerente Comercial", {"vendas"}),
        ("Executivo de Contas", {"vendas"}),
        ("Closer | SaaS | B2B", {"vendas"}),
        ("Instrutora de treinamento", {"educacao"}),
        ("Analista de Sistemas", {"ti"}),
        ("Médica", {"saude"}),
        ("Advogada", {"juridico"}),
        ("Auxiliar administrativo", {"administrativo"}),
        ("Coordenador de Produção", {"producao"}),
    ]
    erros = 0
    print("%-38s %-22s %s" % ("TEXTO", "ESPERADO", "OBTIDO"))
    print("-" * 78)
    for txt, esp in CASOS:
        got = areas(txt)
        ok = bool(esp & got)
        erros += 0 if ok else 1
        print("%-38s %-22s %-20s %s" % (txt[:38], ",".join(sorted(esp)),
                                        ",".join(sorted(got)) or "—",
                                        "ok" if ok else "FALHOU"))
    print()
    for txt in ("Diretor Comercial", "BDR", "Estagiário de marketing",
                "Sócio-Administrador", "Head de Vendas"):
        k, p = nivel(txt)
        print("  %-28s nível=%-14s peso=%d  áreas=%s"
              % (txt, k or "—", p, ",".join(sorted(areas(txt))) or "—"))
    print("\n%d falha(s)" % erros)


# ===========================================================================
# SEGUNDO EIXO: SETOR ECONÔMICO — o que a EMPRESA faz.
# ===========================================================================
# Por que dois eixos. "Vendedor de comércio varejista" numa AGROPECUÁRIA e numa
# LOJA DE INFORMÁTICA são a mesma ÁREA (vendas) e contextos completamente
# diferentes. Com um eixo só, os dois Felipe Oliveira de Araruama empatavam;
# com dois, o perfil que diz "SaaS, B2B" casa com informática e não com
# agropecuária.
#
# O vocabulário vem do catálogo de CNAE da Receita (1.359 descrições), que é
# como a Assertiva escreve o campo `setor` do histórico profissional. Os
# prefixos são regulares: "Fabricação de", "Comércio atacadista de",
# "Comércio varejista de", "Cultivo de", "Extração de", "Transporte...".
# ===========================================================================
SETOR_ECONOMICO: dict[str, dict] = {
    "tecnologia": {
        "rotulo": "Tecnologia e Software",
        "termos": ["informatica", "software", "computac", "tecnologia da informac",
                   "processamento de dados", "hospedagem", "portais", "internet",
                   "desenvolvimento de programa", "consultoria em tecnologia",
                   "saas", "b2b tech", "startup"],
    },
    "telecom": {
        "rotulo": "Telecomunicações",
        "termos": ["telecomunicac", "telefonia", "provedor de acesso",
                   "radiodifus", "televis", "satelite"],
    },
    "varejo": {
        "rotulo": "Comércio Varejista",
        "termos": ["comercio varejista", "loja", "supermercad", "minimercad",
                   "farmacia", "drogaria", "magazine", "boutique", "e-commerce"],
    },
    "atacado": {
        "rotulo": "Comércio Atacadista e Distribuição",
        "termos": ["comercio atacadista", "distribuidora", "representantes comerciais",
                   "intermediac do comercio"],
    },
    "industria": {
        "rotulo": "Indústria e Manufatura",
        "termos": ["fabricac", "manufatur", "metalurg", "siderurg", "usinag",
                   "beneficiamento", "montagem industrial", "quimic", "petroquimic",
                   "papel e celulose", "textil", "calcad", "plastic", "cimento",
                   "automotiv", "autopec"],
    },
    "construcao": {
        "rotulo": "Construção Civil",
        "termos": ["construc", "obras de", "incorporac imobiliari", "empreiteir",
                   "instalac eletric", "instalac hidraulic", "terraplen",
                   "engenharia civil"],
    },
    "saude": {
        "rotulo": "Saúde e Bem-estar",
        "termos": ["atividades de atenc a saude", "hospital", "clinic",
                   "laboratori de anali", "odontolog", "atendimento medic",
                   "plano de saude", "farmaceutic", "ambulator", "diagnostic"],
    },
    "educacao": {
        "rotulo": "Educação",
        "termos": ["ensino", "educac", "escola", "faculdade", "universidad",
                   "curso", "treinamento profissional"],
    },
    "financeiro": {
        "rotulo": "Financeiro e Seguros",
        "termos": ["banco", "bancari", "credito", "cooperativa de credito",
                   "seguros", "previdenc", "corretora", "financeir",
                   "meios de pagamento", "cartoes de credito", "cambio",
                   "atividades de servicos financeir", "consorcio"],
    },
    "agro": {
        "rotulo": "Agronegócio",
        "termos": ["cultivo de", "criacao de", "agricultura", "pecuari",
                   "agropecuari", "producao florestal", "pesca", "aquicultura",
                   "sementes", "defensivos", "insumos agricol"],
    },
    "logistica": {
        "rotulo": "Transporte e Logística",
        "termos": ["transporte", "armazenamento", "armazenag", "carga",
                   "logistic", "correio", "entrega", "frete", "aereo",
                   "ferroviari", "aquaviari", "rodoviari"],
    },
    "energia": {
        "rotulo": "Energia e Utilities",
        "termos": ["energia eletric", "geracao de energia", "distribuicao de energia",
                   "gas", "saneament", "agua", "esgoto", "residuos"],
    },
    "extrativa": {
        "rotulo": "Extrativa e Mineração",
        "termos": ["extrac de", "mineracao", "minerio", "petroleo bruto",
                   "pedreira", "garimp"],
    },
    "servicos": {
        "rotulo": "Serviços Profissionais",
        "termos": ["consultoria", "assessoria", "escritorio de advocacia",
                   "contabilidade", "auditoria", "publicidade", "arquitetura",
                   "servicos de engenharia", "recursos humanos", "agencia de",
                   "testes e analises tecnica"],
    },
    "alimentacao": {
        "rotulo": "Alimentação e Hospitalaria",
        "termos": ["restaurante", "lanchonete", "bar", "hotel", "hotelaria",
                   "pousada", "buffet", "catering", "padaria", "alimentos e bebidas"],
    },
    "publico": {
        "rotulo": "Setor Público",
        "termos": ["administracao public", "administracao do estado", "prefeitura",
                   "secretaria municipal", "secretaria de estado", "autarquia",
                   "defesa", "seguridade social", "justica"],
    },
    "imobiliario": {
        "rotulo": "Imobiliário",
        "termos": ["atividades imobiliari", "aluguel de imove", "condomini",
                   "corretagem de imove", "loteament"],
    },
}


def setor_economico(texto) -> set:
    """O que a EMPRESA faz. Segundo eixo, independente do que a PESSOA faz.

    Alimentado pelo campo `setor` do histórico profissional da Assertiva e pela
    descrição de CNAE da Receita — os dois usam o mesmo vocabulário.
    """
    t = " " + _norm(texto) + " "
    return {k for k, g in SETOR_ECONOMICO.items()
            if any(re.search(r"(^|\s)" + re.escape(x), t) for x in g["termos"])}


def rotulo_setor(chave: str) -> str:
    return SETOR_ECONOMICO.get(chave, {}).get("rotulo", chave)


def perfil_completo(cargo, setor="") -> dict:
    """Os dois eixos de uma vez: o que a pessoa faz e onde ela faz.

    Comparar `perfil_completo` de dois candidatos é mais discriminante que
    comparar só a área: mesma área E mesmo setor é evidência bem mais forte
    que só a área.
    """
    c = classificar(cargo)
    return {**c, "setor_economico": setor_economico(setor or cargo)}


# ===========================================================================
# NÃO É CARGO. A auditoria achou 100+ perfis onde o campo traz SITUAÇÃO, não
# ocupação: "procurando emprego", "dona de casa", "aposentado", "Student",
# "Frequentou <escola>" (rótulo que o próprio LinkedIn gera).
#
# Por que separar de "não classificado": são coisas diferentes para quem usa.
# "Gestão da Rede Prestadora" é cargo que meu dicionário não conhece — buraco
# meu, conserta-se. "Procurando emprego" não é cargo nenhum — não há o que
# consertar, e gastar consulta paga tentando desambiguar essas pessoas é jogar
# dinheiro fora.
# ===========================================================================
NAO_E_CARGO = [
    "procurando emprego", "busca de emprego", "buscando oportunidad",
    "novas oportunidad", "nova oportunidad", "novos desafios",
    "aberto a oportunidad", "open to work", "recolocacao",
    "primeiro emprego", "disponivel para", "disponivel no mercado",
    "mercado de trabalho", "dona de casa", "do lar", "aposentad",
    "desempregad", "autonomo", "freelancer", "freelance", "estudante",
    "student", "frequentou", "cursando", "sem experiencia",
    "profissional independente", "empreendedor individual",
]


def eh_cargo(texto) -> bool:
    """False quando o campo traz situação, não ocupação.

    NÃO USAR COMO PORTA DE BUSCA. Decisão da Rebeca em 08/09/2026, depois de
    medir. Serve para rotular e para escolher entre candidatos; não para
    decidir quem vale a pena procurar.

    A premissa antiga era que perfil sem cargo real resolve mal — eu projetei
    30% contra 60%, e em cima disso a porta foi ligada. Rodando os 166 perfis
    já medidos, o grupo barrado resolveu a 46,2%: dos 26 que a porta cortou,
    12 JÁ TINHAM CPF confirmado. São estudantes e gente em recolocação, que
    costumam ter cadastro único e limpo, justamente o caso fácil.

    E o efeito no número é uma ilusão de razão:

        porta ligada .....  91 CPFs de 140 = 65,0%
        porta desligada ... 105 CPFs de 166 = 63,3%

    Ela ganha 1,7 pp de porcentagem tirando casos do denominador, e entrega
    14 CPFs a menos. Quem olha só a taxa acha que melhorou.

    (Existe também um erro de classificação nesse conjunto: "Prevenção de
    perdas - centro logístico" é cargo de verdade e foi barrado. Mas o motivo
    de desligar não é esse — é a premissa.)
    """
    t = _norm(texto).strip()
    if len(t) < 3 or not re.search(r"[a-z]{3}", t):
        return False
    return not any(x in t for x in NAO_E_CARGO)


def diagnostico(texto) -> dict:
    """Leitura final de um campo de cargo, com o motivo quando não classifica.

    `situacao`:
      cargo_classificado  tem área identificada
      cargo_desconhecido  é cargo, mas o dicionário não cobre — buraco nosso
      nao_e_cargo         situação ("procurando emprego"), não ocupação
      vazio               sem texto útil
    """
    t = _norm(texto).strip()
    if not t or not re.search(r"[a-z]{3}", t):
        return {"situacao": "vazio", "areas": set(), "nivel": "", "peso": -1}
    if not eh_cargo(texto):
        return {"situacao": "nao_e_cargo", "areas": set(),
                "nivel": nivel(texto)[0], "peso": nivel(texto)[1]}
    c = classificar(texto)
    c["situacao"] = ("cargo_classificado" if c["areas"] else "cargo_desconhecido")
    return c

# ---------------------------------------------------------------------------
# CARGO DIGITADO À MÃO: grafia, maiúscula e sinônimo
#
# A tela deixa escrever o cargo livremente, e a pessoa escreve do jeito dela:
# "Diretor", "DIRETORA", "diretor", "Dir.", "Head", "CEO". Do outro lado, o
# cargo vem do cadastro ou do perfil e também não segue padrão nenhum --
# medido: "GERENTE DE RELACIONAMENTO COMERCIAL na CIELO", "Head of Engineering
# & R&D", "super visor de vendas".
#
# A comparação antiga era `termo in cargo.lower()`: substring crua. Ela erra
# dos dois lados -- "diretor" não acha "Diretora" (acha, por prefixo) mas não
# acha "Superintendente" nem "Head"; e o acento derruba tudo ("sócio" nunca
# acha "SOCIO"). O vocabulário para resolver isso já existe neste arquivo, em
# NIVEIS e AREAS; faltava usá-lo para o texto que a pessoa DIGITA, e não só
# para o que ela clica.
# ---------------------------------------------------------------------------

def _termo_nivel(termo: str) -> str:
    """Nível que o termo digitado designa, ou "".

    Aceita a chave ("gerencia"), o apelido ("gerente", "gestor") e qualquer
    radical ou sigla do nível ("diretora", "superintendente", "head", "ceo").
    """
    t = " ".join(_norm(termo).split())
    if not t:
        return ""
    if t in NIVEIS:
        return t
    if t in APELIDO_NIVEL:
        return APELIDO_NIVEL[t]
    return nivel(t)[0]


def _termo_area(termo: str) -> str:
    """Área que o termo designa -- SÓ quando ele é o nome da área.

    Deliberadamente estreito. "vendas" é o nome de uma área e quem digita isso
    quer a área inteira; "vendedor" só casa o radical dela, e tratar os dois
    igual faria uma busca por "vendedor" devolver o Diretor Comercial. Quem
    digita o cargo inteiro está sendo específico de propósito.
    """
    t = " ".join(_norm(termo).split())
    return t if t in AREAS else ""


def casa_cargo(texto, termos) -> bool:
    """O cargo `texto` casa com algum termo digitado?

    Três caminhos, do mais específico para o mais amplo:

      "gerente comercial"  nível E área: exige os dois
      "diretor"            nível: casa Diretora, Superintendente, Head, VP
      "vendas"             área: casa qualquer cargo de vendas
      "closer"             literal: prefixo de palavra, sem acento e sem caixa

    Lista vazia = sem filtro. O literal é sempre tentado por último, então uma
    palavra que o dicionário não conhece continua funcionando como antes.
    """
    if not termos:
        return True
    if isinstance(termos, str):
        termos = [t for t in re.split(r"[;,]", termos) if t.strip()]

    alvo = " " + _norm(texto) + " "
    nvl = nivel(texto)[0]
    ars = areas(texto)

    for bruto in termos:
        t = str(bruto or "").strip()
        if not t:
            continue

        # "gerencia:vendas" e as escolhas dos botões continuam pelo caminho
        # de sempre -- é a mesma pergunta, feita pela tela em vez do teclado.
        if ":" in t or _norm(t).strip() in AREAS or _norm(t).strip() in NIVEIS:
            if casa_escolha(texto, [_norm(t).strip()]):
                return True

        palavras = [p for p in _norm(t).split() if p]
        tn = _termo_nivel(t)
        ta = _termo_area(t)

        # Duas palavras costumam ser nível + área: "gerente comercial",
        # "diretor de TI", "coordenadora de marketing".
        if not (tn and ta) and len(palavras) > 1:
            niveis_p = [x for x in (_termo_nivel(p) for p in palavras) if x]
            areas_p = [x for x in (_termo_area(p) for p in palavras) if x]
            if not areas_p:
                # "diretor comercial": "comercial" não é chave de área, mas o
                # dicionário de áreas conhece o radical.
                for p in palavras:
                    if _termo_nivel(p):
                        continue
                    achadas = areas(p)
                    if len(achadas) == 1:
                        areas_p.append(achadas.pop())
            if niveis_p and areas_p:
                if nvl == niveis_p[0] and areas_p[0] in ars:
                    return True
                # Nível e área pedidos e o candidato não tem os dois: este
                # termo não casa. Cair no literal aqui devolveria qualquer
                # cargo que contivesse a palavra solta.
                continue

        if tn and not ta and nvl == tn:
            return True
        if ta and not tn and ta in ars:
            return True

        # LITERAL, por prefixo de palavra e sem acento: "socio" acha "SÓCIO
        # ADMINISTRADOR", "closer" acha "Closer de Vendas".
        alvo_t = " ".join(palavras)
        if alvo_t and re.search(r"(^|\s)" + re.escape(alvo_t), alvo):
            return True
    return False


def termos_cargo_para_busca(termos, teto: int = 4) -> list[str]:
    """Cargo digitado -> radicais para filtrar `position` na Bright Data.

    Mesma ideia de `termos_para_busca`, mas partindo do texto livre. "diretor"
    vira `diretor, superintendent, head, vp` -- que é como o cargo aparece
    escrito nos perfis reais.

    INTERCALA quando há mais de um termo: o `or` deles trava em 4, e expandir
    um termo de cada vez gastaria as quatro vagas no primeiro, sumindo com o
    segundo sem aviso.
    """
    listas: list[list[str]] = []
    if isinstance(termos, str):
        termos = re.split(r"[;,]", termos)
    for bruto in termos or []:
        t = str(bruto or "").strip()
        if not t:
            continue
        base = " ".join(_norm(t).split())
        expandido = [base]
        n = _termo_nivel(t)
        if n and len(base.split()) == 1:
            # Só para termo de uma palavra: "gerente comercial" já é
            # específico, e trocá-lo pelos radicais do nível perderia a área.
            g = NIVEIS[n]
            expandido += list(g.get("radicais", ())) + list(g.get("siglas", ()))
        a = _termo_area(t)
        if a:
            expandido += termos_para_busca(a, teto=teto)
        listas.append(list(dict.fromkeys(x for x in expandido if x)))

    saida: list[str] = []
    for i in range(max((len(x) for x in listas), default=0)):
        for lista in listas:
            if i < len(lista):
                saida.append(lista[i])
    return list(dict.fromkeys(saida))[:teto]
