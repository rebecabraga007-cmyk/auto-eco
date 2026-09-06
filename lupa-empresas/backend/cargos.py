# -*- coding: utf-8 -*-
"""Classifica o texto livre do cargo em DEPARTAMENTO e SENIORIDADE.

POR QUE EXISTE: a Datastone filtra por 23 departamentos e 6 senioridades, mas
nenhum desses campos vem do LinkedIn — são classificações que eles calcularam.
O LinkedIn dá só uma linha de texto ("Líder de operações na Movida"). Aqui a
gente deriva o mesmo vocabulário, pra tela poder oferecer os mesmos filtros.

As listas seguem exatamente as opções capturadas em /b2b/filter-options.

LIMITE HONESTO: isto é casamento de palavra, não entendimento. "Analista" sozinho
não diz o departamento. Por isso existe "Não classificável" — é melhor assumir a
dúvida do que chutar e a pessoa filtrar por algo que não corresponde a nada.

DOIS CUIDADOS que só apareceram medindo em 7.301 cargos reais do cache:

  FLEXÃO — `\\binstrutor\\b` NÃO casa "Instrutora": o `\\b` exige fim de palavra e
  vem um "a" depois. Todo radical que flexiona leva _FLEX no fim.

  INGLÊS — o LinkedIn brasileiro tem muito "Sales Director", "Head of People".
  Sem os termos em inglês, decisor de multinacional escapava inteiro.

E o `\\b` é OBRIGATÓRIO em todo padrão: sem ele, "ti" casa dentro de
"adminis(ti)rativo" e joga meio mundo em TI.
"""
import re

# --- vocabulário da Datastone (/internal/v1/b2b/filter-options) ---
DEPARTAMENTOS = [
    "Administrativo", "Agronegócios", "Atendimento/Suporte ao Cliente",
    "Consultoria", "Educação", "Engenharia", "Imobiliário",
    "Logística/Suprimentos", "Manutenção", "Operações/Produção",
    "Pesquisa & Desenvolvimento (P&D)", "Planejamento", "Projetos", "Qualidade",
    "Saúde", "Segurança, Saúde e Meio Ambiente", "Varejo", "Comercial/Vendas",
    "Financeiro/Contábil", "TI (Tecnologia da Informação)",
    "Marketing/Comunicação", "Recursos Humanos", "Não classificável",
]

SENIORIDADES = ["Estagiário/Trainee", "Iniciante", "Junior", "Pleno", "Sênior",
                "Decisores"]

F = "[oa]?s?"          # flexão de gênero/número no fim do radical

# Ordem IMPORTA: o primeiro que casar vence, então o específico vem antes do
# genérico — "analista de rh" tem que cair em RH, não em Administrativo.
_DEPTO_REGRAS = [
    ("Recursos Humanos",
     r"\b(rh|recursos humanos|recrutament" + F + r"|selecao|people|talent|dho|"
     r"departamento pessoal|human resources)\b"),
    ("TI (Tecnologia da Informação)",
     r"\b(ti|tecnologia da informacao|desenvolvedor" + F + r"|programador" + F + r"|"
     r"software|devops|sre|dados|data|infraestrutura|suporte tecnico|qa|"
     r"full ?stack|back ?end|front ?end|cloud|seguranca da informacao|"
     r"developer|analista de sistemas|banco de dados)\b"),
    ("Marketing/Comunicação",
     r"\b(marketing|comunicacao|midia|social media|branding|publicidade|"
     r"conteudo|trafego|growth|designer" + F + r"|communications)\b"),
    ("Financeiro/Contábil",
     r"\b(financeir" + F + r"|contabil|contabilidade|controladoria|tesouraria|"
     r"fiscal|custos|contas a (pagar|receber)|credito|cobranca|auditor" + F + r"|"
     r"finance|financial|accounting|controller)\b"),
    ("Comercial/Vendas",
     r"\b(comercial|vendas|vendedor" + F + r"|executiv" + F + r" de contas|account|"
     r"sdr|bdr|pre.?vendas|closer|representante|key account|locacao|"
     r"corretor" + F + r"|sales|business development)\b"),
    ("Atendimento/Suporte ao Cliente",
     r"\b(atendimento|atendente" + F + r"|suporte ao cliente|"
     r"customer (success|service|experience)|sac|call center|telemarketing|"
     r"recepcionista" + F + r")\b"),
    ("Logística/Suprimentos",
     r"\b(logistica|suprimentos|compras|almoxarifado|estoque|expedicao|"
     r"transporte|frota|supply|armazem|motorista" + F + r"|logistics|"
     r"procurement)\b"),
    ("Engenharia",
     r"\b(engenheir" + F + r"|engenharia|engineer|engineering)\b"),
    ("Saúde",
     r"\b(medic" + F + r"|enfermeir" + F + r"|farmaceutic" + F + r"|"
     r"fisioterapeuta" + F + r"|psicolog" + F + r"|nutricionista" + F + r"|"
     r"odonto|dentista" + F + r"|veterinari" + F + r"|biomedic" + F + r"|saude)\b"),
    ("Segurança, Saúde e Meio Ambiente",
     r"\b(sesmt|seguranca do trabalho|meio ambiente|ambiental|hse|ehs|"
     r"bombeir" + F + r"|vigilante" + F + r"|porteir" + F + r"|"
     r"seguranca patrimonial)\b"),
    ("Qualidade", r"\b(qualidade|quality|iso 9001|melhoria continua)\b"),
    ("Manutenção",
     r"\b(manutencao|mecanic" + F + r"|eletricista" + F + r"|maintenance|"
     r"usinagem|extrusao|soldador" + F + r"|torneiro)\b"),
    ("Operações/Produção",
     r"\b(operacoes|operacional|producao|fabrica|industrial|chao de fabrica|"
     r"operador" + F + r"|encarregad" + F + r"|operations|production)\b"),
    ("Projetos",
     r"\b(projet" + F + r"|pmo|scrum master|product owner|project manager)\b"),
    ("Planejamento",
     r"\b(planejamento|pcp|estrategia|business intelligence|strategy|planning)\b"),
    ("Pesquisa & Desenvolvimento (P&D)",
     r"\b(pesquisa e desenvolvimento|inovacao|pesquisador" + F + r"|research)\b"),
    ("Agronegócios",
     r"\b(agro|agronegoci" + F + r"|agronom" + F + r"|zootecnia|pecuaria|"
     r"lavoura|rural|agricultura)\b"),
    ("Educação",
     r"\b(professor" + F + r"|docente" + F + r"|pedagog" + F + r"|"
     r"instrutor" + F + r"|educacao|educacional|teacher|monitor" + F + r"|"
     r"bacharel|licenciatura|estudante" + F + r"|alun" + F + r")\b"),
    ("Imobiliário",
     r"\b(imobiliari" + F + r"|imoveis|sindic" + F + r"|condominio)\b"),
    ("Varejo",
     r"\b(varejo|loja|caixa|repositor" + F + r"|balconista" + F + r"|retail)\b"),
    ("Consultoria", r"\b(consultor" + F + r"|consultoria|advisory)\b"),
    ("Administrativo",
     r"\b(administrativ" + F + r"|secretari" + F + r"|office|backoffice|"
     r"juridic" + F + r"|advogad" + F + r"|direito|compliance|administracao|"
     r"lawyer|legal|administrator|assistente|auxiliar)\b"),
]

# "Decisores" é a categoria que a operação realmente usa — por isso vem primeiro.
_SENIOR_REGRAS = [
    ("Decisores",
     r"\b(ceo|cfo|coo|cto|cio|cmo|chro|presidente|vice.?presidente|vp|"
     r"diretor" + F + r"|director|head|soci" + F + r"|founder|fundador" + F + r"|"
     r"proprietari" + F + r"|owner|partner|superintendente" + F + r"|chief)\b"),
    ("Estagiário/Trainee",
     r"\b(estagiari" + F + r"|estagio|trainee|intern|aprendiz|"
     r"estudante" + F + r"|alun" + F + r"|student)\b"),
    ("Sênior",
     r"\b(senior|sr|especialista" + F + r"|expert|principal|lead|gerente" + F + r"|"
     r"manager|coordenador" + F + r"|supervisor" + F + r"|lider" + F + r"|"
     r"chefe" + F + r")\b"),
    ("Junior",
     r"\b(junior|jr|assistente" + F + r"|auxiliar" + F + r"|aux)\b"),
    ("Pleno",
     r"\b(pleno|analista" + F + r"|tecnic" + F + r"|consultor" + F + r"|"
     r"specialist)\b"),
    ("Iniciante",
     r"\b(operador" + F + r"|atendente" + F + r"|recepcionista" + F + r"|"
     r"ajudante" + F + r"|servicos gerais|motorista" + F + r"|vendedor" + F + r"|"
     r"assistant)\b"),
]

_ACENTOS = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")

# Compila uma vez: são ~30 padrões rodando sobre milhares de linhas.
_DEPTO = [(n, re.compile(p)) for n, p in _DEPTO_REGRAS]
_SENIOR = [(n, re.compile(p)) for n, p in _SENIOR_REGRAS]


def _norm(texto: str) -> str:
    t = (texto or "").lower().translate(_ACENTOS)
    return re.sub(r"[^a-z0-9& ]+", " ", t)


def departamento(cargo: str) -> str:
    t = _norm(cargo)
    if not t.strip():
        return "Não classificável"
    for nome, rx in _DEPTO:
        if rx.search(t):
            return nome
    return "Não classificável"


def senioridade(cargo: str) -> str:
    t = _norm(cargo)
    if not t.strip():
        return ""
    for nome, rx in _SENIOR:
        if rx.search(t):
            return nome
    return ""


def classificar(cargo: str) -> dict[str, str]:
    return {"departamento": departamento(cargo), "senioridade": senioridade(cargo)}
