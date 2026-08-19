# -*- coding: utf-8 -*-
"""Gera o PDF da documentação da API v1 do CapiBLU.

Mesmo conteúdo da página em /docs, diagramado para papel: capa, sumário,
cartão por endpoint com método e custo, tabelas de parâmetro e exemplos em
curl. Paleta = design system do CapiBLU (papel + azul-noite + terracota).

    python build_pdf_api.py
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

OUT = os.path.join("exports", "capiblu-api-v1.pdf")
BASE_URL = "https://capiblu-app.onrender.com/api/v1"

# --- paleta do CapiBLU ---
NAVY      = colors.HexColor("#0F2E4A")
BLUE      = colors.HexColor("#12385C")
BLUE_SOFT = colors.HexColor("#EAF0F5")
TERRACOTA = colors.HexColor("#A85A2C")
TERRA_SFT = colors.HexColor("#FBEFE7")
GREEN     = colors.HexColor("#2F6B4F")
GREEN_SFT = colors.HexColor("#EAF1EC")
AMBER     = colors.HexColor("#8C6A16")
AMBER_SFT = colors.HexColor("#F7F1E1")
RED       = colors.HexColor("#9A3324")
PAPEL     = colors.HexColor("#F1EEE7")
GREY      = colors.HexColor("#55595F")
GREY_MID  = colors.HexColor("#45423B")
LINE      = colors.HexColor("#DBD4C6")
HEAD_BG   = colors.HexColor("#F0ECE3")
CODE_BG   = colors.HexColor("#10222F")
CODE_FG   = colors.HexColor("#DCE6EE")

styles = getSampleStyleSheet()
LARGURA = A4[0] - 30 * mm          # margens de 15mm


def S(name, **kw):
    return ParagraphStyle(name, parent=kw.pop("parent", styles["Normal"]), **kw)


h1     = S("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY,
           spaceBefore=4, spaceAfter=4)
h2     = S("h2", fontName="Helvetica-Bold", fontSize=10.8, leading=14, textColor=TERRACOTA,
           spaceBefore=11, spaceAfter=4)
corpo  = S("corpo", fontName="Helvetica", fontSize=8.6, leading=12, textColor=GREY_MID,
           spaceAfter=4)
item   = S("item", parent=corpo, leftIndent=10, bulletIndent=2, spaceAfter=2)
cellh  = S("cellh", fontName="Helvetica-Bold", fontSize=7, leading=9, textColor=GREY)
cell   = S("cell", fontName="Helvetica", fontSize=7.6, leading=10, textColor=GREY_MID)
cellm  = S("cellm", fontName="Courier", fontSize=7.4, leading=10, textColor=BLUE)
rota   = S("rota", fontName="Courier-Bold", fontSize=9.4, leading=12, textColor=NAVY)
codigo = S("codigo", fontName="Courier", fontSize=7.1, leading=9.4, textColor=CODE_FG)
nota   = S("nota", fontName="Helvetica", fontSize=8, leading=11, textColor=GREY_MID)
notat  = S("notat", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=NAVY)
selo   = S("selo", fontName="Helvetica-Bold", fontSize=6.4, leading=8, alignment=TA_CENTER)
capa_t = S("capa_t", fontName="Helvetica-Bold", fontSize=30, leading=34, textColor=colors.white)
capa_s = S("capa_s", fontName="Helvetica", fontSize=11, leading=16,
           textColor=colors.HexColor("#C3D5E3"))
sumario_i = S("sumario_i", fontName="Helvetica", fontSize=9, leading=15, textColor=GREY_MID)


def c(txt):
    """Trecho em monoespaçado dentro de um parágrafo."""
    return f'<font face="Courier" color="#12385C">{txt}</font>'


def p(txt, estilo=corpo):
    return Paragraph(txt, estilo)


def lista(itens):
    return [Paragraph(t, item, bulletText="•") for t in itens]


def esc(t):
    """& < > antes de tudo: o parser do reportlab lê & como início de entidade,
    e sem isso "?uf=MG&municipio=" sai impresso como "&municipio;="."""
    return t.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


def code(txt):
    """Bloco de código sobre fundo escuro."""
    linhas = [Paragraph(esc(l).replace(" ", "&nbsp;") or "&nbsp;", codigo)
              for l in txt.strip("\n").split("\n")]
    t = Table([[linhas]], colWidths=[LARGURA])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODE_BG),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 7), ("BOTTOMPADDING", (0, 0), (-1, -1), 7),
    ]))
    return [Spacer(1, 4), t, Spacer(1, 6)]


def tabela(cabecalho_, linhas, larguras):
    # cabecalho_ = None para tabela de rótulo/valor: sem título de coluna a faixa
    # cinza do topo aparecia vazia.
    tem_cabecalho = bool(cabecalho_ and any(cabecalho_))
    dados = [[Paragraph(x.upper(), cellh) for x in cabecalho_]] if tem_cabecalho else []
    for ln in linhas:
        dados.append([Paragraph(x, cellm if x.startswith("<") is False and
                                (x.startswith("/") or x.startswith("{")) else cell)
                      for x in ln])
    t = Table(dados, colWidths=larguras, repeatRows=1 if tem_cabecalho else 0)
    estilo = [
        ("GRID", (0, 0), (-1, -1), 0.3, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 5), ("RIGHTPADDING", (0, 0), (-1, -1), 5),
        ("TOPPADDING", (0, 0), (-1, -1), 3.5), ("BOTTOMPADDING", (0, 0), (-1, -1), 3.5),
    ]
    if tem_cabecalho:
        estilo += [("BACKGROUND", (0, 0), (-1, 0), HEAD_BG),
                   ("LINEBELOW", (0, 0), (-1, 0), 0.7, LINE)]
    for i in range(1 if tem_cabecalho else 0, len(dados)):
        if i % 2 == (0 if tem_cabecalho else 1):
            estilo.append(("BACKGROUND", (0, i), (-1, i), colors.HexColor("#FBFAF7")))
    t.setStyle(TableStyle(estilo))
    return [Spacer(1, 3), t, Spacer(1, 7)]


CORES_SELO = {
    "GET":    (BLUE, colors.white),
    "POST":   (GREEN, colors.white),
    "DELETE": (RED, colors.white),
    "paga":   (TERRA_SFT, TERRACOTA),
    "gratis": (GREEN_SFT, GREEN),
    "adm":    (AMBER_SFT, AMBER),
    "bruto":  (HEAD_BG, GREY),
}


def cabeca_endpoint(metodo, caminho, selos):
    """Linha do topo do cartão: método, rota e selos de custo."""
    celulas, larguras, estilo = [], [], [
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 4), ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 3), ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
    ]
    fundo, texto = CORES_SELO[metodo]
    celulas.append(Paragraph(f'<font color="#{texto.hexval()[2:]}">{metodo}</font>', selo))
    larguras.append(15 * mm)
    estilo += [("BACKGROUND", (0, 0), (0, 0), fundo)]

    celulas.append(Paragraph(caminho, rota))
    larguras.append(LARGURA - 15 * mm - sum(28 * mm for _ in selos))

    for i, (tipo, rotulo) in enumerate(selos, start=2):
        fundo, texto = CORES_SELO[tipo]
        celulas.append(Paragraph(f'<font color="#{texto.hexval()[2:]}">{rotulo}</font>', selo))
        larguras.append(28 * mm)
        estilo += [("BACKGROUND", (i, 0), (i, 0), fundo),
                   ("BOX", (i, 0), (i, 0), 0.4, texto)]

    t = Table([celulas], colWidths=larguras)
    t.setStyle(TableStyle(estilo))
    return t


def endpoint(metodo, caminho, selos, dentro):
    """Cartão de endpoint: não quebra no meio da página quando dá para evitar."""
    bloco = [cabeca_endpoint(metodo, caminho, selos)]
    bloco += dentro
    bloco += [Spacer(1, 3), HRFlowable(width="100%", color=LINE, thickness=0.4),
              Spacer(1, 7)]
    # Cartão curto não se parte no meio da página; cartão longo tem de poder quebrar.
    return [KeepTogether(bloco)] if len(bloco) < 9 else bloco


def aviso(titulo, texto, tom="info"):
    fundo = {"info": BLUE_SOFT, "aviso": AMBER_SFT, "perigo": colors.HexColor("#F7ECE9")}[tom]
    borda = {"info": BLUE, "aviso": AMBER, "perigo": RED}[tom]
    t = Table([[[Paragraph(titulo, notat), Paragraph(texto, nota)]]], colWidths=[LARGURA])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), fundo),
        ("LINEBEFORE", (0, 0), (0, -1), 2.2, borda),
        ("LEFTPADDING", (0, 0), (-1, -1), 8), ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6), ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    return [Spacer(1, 3), t, Spacer(1, 7)]


def moldura(canvas, doc):
    canvas.saveState()
    if doc.page == 1:                       # a capa tem arte própria
        canvas.restoreState()
        return
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 11 * mm, A4[0], 11 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8.4)
    canvas.drawString(15 * mm, A4[1] - 7.6 * mm, "CapiBLU · API v1 — Documentação")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(A4[0] - 15 * mm, A4[1] - 7.6 * mm, f"página {doc.page}")
    canvas.setFillColor(GREY)
    canvas.setFont("Courier", 6.8)
    canvas.drawString(15 * mm, 8 * mm, BASE_URL)
    canvas.setFont("Helvetica", 6.8)
    canvas.drawRightString(A4[0] - 15 * mm, 8 * mm,
                           "Versão da página web: /docs · atualize os dois ao mudar a API")
    canvas.restoreState()


def capa(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, A4[1] - 118 * mm, A4[0], 118 * mm, stroke=0, fill=1)
    canvas.setFillColor(TERRACOTA)
    canvas.rect(0, A4[1] - 121 * mm, A4[0], 3 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 31)
    canvas.drawString(20 * mm, A4[1] - 62 * mm, "API CapiBLU")
    canvas.setFont("Helvetica-Bold", 16)
    canvas.setFillColor(colors.HexColor("#C3D5E3"))
    canvas.drawString(20 * mm, A4[1] - 74 * mm, "Versão 1 — documentação técnica")
    canvas.setFont("Helvetica", 10)
    canvas.drawString(20 * mm, A4[1] - 88 * mm,
                      "REST · JSON · autenticação por API Token · 34 endpoints")
    canvas.setFont("Courier", 9)
    canvas.setFillColor(colors.white)
    canvas.drawString(20 * mm, A4[1] - 100 * mm, BASE_URL)
    canvas.restoreState()


# ══════════════════════════════════════════════════════════
#  Conteúdo
# ══════════════════════════════════════════════════════════
def conteudo():
    f = []

    # ── capa: o desenho vem do onPage; aqui só o que fica abaixo dele ──
    f.append(Spacer(1, 117 * mm))
    f += tabela(None, [
        ["Versão", "1.0"],
        ["Arquitetura", "REST / HTTP"],
        ["Formato", "JSON"],
        ["Autenticação", "API Token (Bearer)"],
        ["Endpoints", "34"],
        ["URL base", BASE_URL],
        ["Página web", "https://capiblu-app.onrender.com/docs"],
    ], [38 * mm, LARGURA - 38 * mm])
    f.append(Spacer(1, 6))
    f.append(p("Sumário", h2))
    for linha in [
        "1. Introdução", "2. Autenticação e escopos", "3. Conceitos gerais",
        "4.1 Conta", "4.2 Empresas", "4.3 Pessoas", "4.4 Telefones",
        "4.5 JSON bruto das fontes", "4.6 Visões compostas", "4.7 Lote",
        "4.8 Apoio, consumo e dossiê", "5. Administração de tokens",
        "6. Objetos e relacionamentos", "7. Casos de uso", "8. Boas práticas",
    ]:
        f.append(Paragraph(linha, sumario_i))
    f.append(PageBreak())

    # ── 1 ──
    f.append(p("1. Introdução", h1))
    f.append(p(
        "A API do CapiBLU expõe o que a plataforma alcança: cadastro de empresas da Receita "
        "Federal, quadro de sócios com CPF resolvido, possíveis decisores com cargo, vínculos "
        "empregatícios da RAIS, telefones priorizados por atualidade e parentes."))
    f.append(p("O que dá para fazer", h2))
    f += lista([
        "Buscar empresas por UF, município, CNAE, porte e capital social",
        "Trazer sócios com CPF resolvido e decisores com cargo e nível de decisão",
        "Consultar quem trabalha (ou trabalhou) numa empresa, pela RAIS",
        "Descobrir onde uma pessoa trabalha, a partir do CPF",
        "Montar contatos para abordagem, com telefone do mais atual para o mais antigo",
        f"Puxar o {c('JSON bruto')} de cada fonte quando precisar de um campo que a tela não mostra",
        "Acompanhar o próprio consumo e o limite diário",
    ])
    f.append(Spacer(1, 4))
    f.append(p("<b>Pré-requisito:</b> um token de API, gerado por um administrador no painel."))

    # ── 2 ──
    f.append(p("2. Autenticação e escopos", h1))
    f.append(p("Toda requisição leva o token no header:"))
    f += code("Authorization: Bearer capi_a1b2c3d4_xxxxxxxxxxxxxxxxxxxxxxxx")
    f.append(p("Como obter", h2))
    f.append(p(
        "Um administrador cria o token no painel, em <b>Painel administrativo → Tokens de "
        "API</b>. O valor em claro aparece <b>uma única vez, na criação</b> — o CapiBLU guarda "
        "apenas o hash. Se perder, revogue e gere outro."))
    f.append(p("Escopos", h2))
    f += tabela(["Escopo", "O que libera"], [
        ["leitura", "Só o que sai de base local: empresas, sócios, busca por nome, "
                    "cadastro de CPF. Não gera custo."],
        ["consulta", "Também o que <b>gasta consulta paga</b>: telefones, decisores, RAIS, "
                     "parentes, conexões."],
    ], [24 * mm, LARGURA - 24 * mm])
    f.append(p(
        f"Token {c('leitura')} que chamar rota paga recebe <b>403</b> com explicação. Serve para "
        "entregar acesso a um sistema de leitura sem risco de ele gerar custo."))
    f += aviso("Segurança",
               "Nunca coloque o token em repositório nem em código de frontend. Use variável "
               "de ambiente. Revogar é imediato: a chamada seguinte já recebe 401.", "perigo")

    # ── 3 ──
    f.append(PageBreak())
    f.append(p("3. Conceitos gerais", h1))
    f.append(p("3.1 Datas", h2))
    f.append(p(
        f"ISO 8601 em UTC: {c('2026-08-19T17:00:00Z')}. Datas que vêm de base pública (RAIS, "
        f"Receita) podem chegar no formato original {c('dd/mm/aaaa')} — nesse caso o campo tem "
        f"sufixo {c('_br')}."))
    f.append(p("3.2 Filtros e paginação", h2))
    f += code("GET /api/v1/empresas?uf=MG&municipio=GOVERNADOR%20VALADARES&porte=05")
    f += tabela(["Parâmetro", "Tipo", "Descrição"], [
        ["page", "integer", "Página, começando em 1"],
        ["limit", "integer", "Registros por página (o máximo varia por rota)"],
    ], [30 * mm, 22 * mm, LARGURA - 52 * mm])
    f.append(p("3.3 Estrutura das respostas", h2))
    f.append(p("Todo retorno bem-sucedido usa o mesmo envelope:"))
    f += code("""{
  "data": [ ... ],
  "meta": { "total": 100, "page": 1, "limit": 20, "fonte": "Receita Federal" }
}""")
    f.append(p("E todo erro tem corpo previsível:"))
    f += code('{ "error": { "code": "cnpj_invalido", "message": "CNPJ deve ter 14 digitos." } }')
    f += tabela(["Status", "Quando acontece"], [
        ["200", "Sucesso"],
        ["400", "Requisição inválida (documento malformado, filtro impossível, campo inexistente)"],
        ["401", "Token ausente, inválido ou revogado"],
        ["403", "Escopo insuficiente, usuário inativo, ou rota só de admin"],
        ["404", "Documento não encontrado na fonte"],
        ["429", "Limite diário de consultas atingido"],
        ["502 / 503", "Serviço de dados indisponível"],
    ], [22 * mm, LARGURA - 22 * mm])
    f.append(p("3.4 Custo por chamada", h2))
    f.append(p(
        "Rotas marcadas <b>gasta consulta</b> consomem o limite diário do usuário dono do token "
        f"— o mesmo contador da plataforma. Rotas de base local não consomem nada. Veja o saldo "
        f"em {c('GET /conta')}."))
    f += aviso("Ausência não é erro",
               f"Micro empresa sem decisor devolve {c('200')} com {c('data: []')} e um "
               f"{c('meta.aviso')} explicando. É resposta legítima, não falha.", "info")

    # ── 4.1 ──
    f.append(PageBreak())
    f.append(p("4.1 Conta", h1))
    f += endpoint("GET", "/conta", [("gratis", "não gasta")], [
        p("Quem é o dono do token, qual token está em uso e quanto ainda cabe de consulta hoje."),
        *code("""{
  "data": {
    "usuario": { "id": 1, "nome": "Rebeca", "email": "rebeca@...", "role": "admin" },
    "token":   { "id": 3, "nome": "Integracao CRM", "escopo": "consulta" },
    "limites": { "consultas_por_dia": 100, "usadas_hoje": 12,
                 "restantes_hoje": 88, "ilimitado": false }
  },
  "meta": { "gerado_em": "2026-08-19T20:14:03Z" }
}"""),
    ])

    # ── 4.2 ──
    f.append(p("4.2 Empresas", h1))
    f += endpoint("GET", "/empresas", [("gratis", "base local")], [
        p("Busca na base local da Receita Federal."),
        *tabela(["Parâmetro", "Tipo", "Descrição"], [
            ["uf", "string", "Sigla do estado"],
            ["municipio", "string", "Nome do município"],
            ["cnae", "string", "Código CNAE (vários separados por vírgula)"],
            ["porte", "string", "01 micro · 03 pequeno · 05 demais"],
            ["situacao", "string", "Ex.: ATIVA"],
            ["capital_min / capital_max", "integer", "Faixa de capital social"],
            ["com_telefone", "boolean", "Só empresas com telefone na Receita"],
            ["somente_matriz", "boolean", "Exclui filiais"],
            ["texto", "string", "Busca livre por razão social / nome fantasia"],
            ["page / limit", "integer", "Paginação (limit máximo 200)"],
        ], [42 * mm, 20 * mm, LARGURA - 62 * mm]),
        *aviso("A Receita não classifica “grande”",
               f"{c('05')} é o balde de médias <b>e</b> grandes. Para chegar nas grandes, "
               f"combine {c('porte=05')} com {c('capital_min')}.", "aviso"),
    ])
    f += endpoint("GET", "/empresas/{cnpj}", [("gratis", "base local")], [
        p("Cadastro completo: razão social, situação, CNAE, endereço, capital social e QSA."),
    ])
    f += endpoint("GET", "/empresas/{cnpj}/socios", [("gratis", "base local")], [
        p("Quadro de sócios com <b>CPF resolvido</b> quando a base local consegue cruzar."),
        *code("""{ "data": [ { "nome": "CELIO COUTINHO DA CUNHA",
              "qualificacao": "Socio-Administrador",
              "cpf": "03702149600", "data_entrada": "2021-06-10" } ],
  "meta": { "total": 1, "fonte": "Receita Federal (QSA)" } }"""),
    ])
    f += endpoint("GET", "/empresas/{cnpj}/decisores", [("paga", "gasta consulta")], [
        p("Possíveis decisores com cargo, classificados em três níveis de decisão."),
        *tabela(["Parâmetro", "Tipo", "Descrição"], [
            ["nivel", "string", "1 decide sozinho · 2 decide na área · 3 influencia"],
            ["cargo", "string", "Filtro por cargo, ex.: diretor"],
            ["page / limit", "integer", "Paginação"],
        ], [30 * mm, 20 * mm, LARGURA - 50 * mm]),
        *aviso("Cobertura desigual",
               "Empresa grande costuma ter muitos (medimos 602 no CNPJ da Google Brasil); micro "
               f"empresa quase nunca tem. Nesses casos {c('meta.aviso')} explica e "
               f"{c('data')} vem vazio.", "aviso"),
    ])
    f += endpoint("GET", "/empresas/{cnpj}/funcionarios", [("paga", "gasta consulta")], [
        p("Vínculos declarados na RAIS: nome, CPF, admissão, desligamento e tempo de casa."),
        *tabela(["Parâmetro", "Tipo", "Descrição"], [
            ["situacao", "string", "ativos ou desligados"],
            ["page / limit", "integer", "Paginação (limit máximo 500)"],
        ], [30 * mm, 20 * mm, LARGURA - 50 * mm]),
        *aviso("A RAIS é um retrato, não tempo real",
               f"Vale o último ano entregue ({c('meta.referencia')}): quem entrou depois não "
               "aparece, e “ativo” significa “estava lá naquela data”. De quem saiu, a base "
               "informa dia e mês, sem o ano.", "aviso"),
    ])
    f += endpoint("GET", "/empresas/{cnpj}/contatos", [("paga", "gasta consulta")], [
        p("O endpoint de prospecção: sócios e decisores já com telefone priorizado."),
        *tabela(["Parâmetro", "Tipo", "Padrão", "Descrição"], [
            ["incluir_decisores", "boolean", "true", "Anexa decisores que não são sócios"],
            ["cargos", "string", "—", "Filtro de cargo dos decisores"],
            ["max_decisores", "integer", "3", "Teto por empresa"],
            ["max_telefones", "integer", "3", "Telefones por contato"],
            ["tipo_telefone", "string", "celular", "celular, celular_fixo ou todos"],
            ["fonte_telefone", "string", "assertiva", "assertiva ou mk"],
        ], [34 * mm, 18 * mm, 20 * mm, LARGURA - 72 * mm]),
        p("Os telefones vêm <b>do mais atual para o mais antigo</b>, usando o último contato "
          "registrado, linha quente e se o número é do próprio titular."),
    ])
    f += endpoint("GET", "/empresas/{cnpj}/conexoes", [("paga", "gasta consulta")], [
        p("Sócios, possíveis decisores e empresas ligadas — com telefone e indicação de WhatsApp."),
    ])

    # ── 4.3 ──
    f.append(p("4.3 Pessoas", h1))
    f += endpoint("GET", "/pessoas", [("gratis", "base local")], [
        p("Busca por nome na base local de CPF."),
        *tabela(["Parâmetro", "Tipo", "Descrição"], [
            ["nome", "string", "<b>Obrigatório</b>, mínimo 3 caracteres"],
            ["ampla", "boolean", "true procura nomes compostos parecidos"],
            ["page / limit", "integer", "Paginação"],
        ], [30 * mm, 20 * mm, LARGURA - 50 * mm]),
    ])
    f += endpoint("GET", "/pessoas/{cpf}", [("gratis", "base local")], [
        p("Cadastrais: nome, nascimento, sexo e nome da mãe quando disponível."),
    ])
    f += endpoint("GET", "/pessoas/{cpf}/telefones", [("paga", "gasta consulta")], [
        p("Telefones da pessoa, ordenados do mais atual para o mais antigo."),
    ])
    f += endpoint("GET", "/pessoas/{cpf}/vinculos", [("paga", "gasta consulta")], [
        p("Onde a pessoa trabalha ou trabalhou, pela RAIS — o inverso do CNPJ."),
    ])
    f += endpoint("GET", "/pessoas/{cpf}/parentes", [("paga", "gasta 2 consultas")], [
        p("Mãe, pai, filhos, irmãos, cônjuge e sócios, com telefone quando existe. Funde duas "
          f"fontes e marca a origem de cada linha em {c('fonte')}."),
    ])

    # ── 4.4 ──
    f.append(p("4.4 Telefones", h1))
    f += endpoint("GET", "/telefones/{numero}", [("paga", "gasta consulta")], [
        p("Telefone reverso: CPFs e CNPJs atrelados ao número. Aceita 10 ou 11 dígitos com DDD, "
          "com ou sem máscara."),
    ])
    f += endpoint("GET", "/telefones/{numero}/pertence/{documento}",
                      [("paga", "gasta consulta")], [
        p("Confirma se o número é daquele CPF/CNPJ e avisa quando é linha compartilhada."),
    ])

    # ── 4.5 ──
    f.append(PageBreak())
    f.append(p("4.5 JSON bruto das fontes", h1))
    f.append(p(
        "Cada fonte devolve muito mais campo do que a tela mostra. Nestas rotas o "
        f"{c('meta.bruto')} vem {c('true')}: o {c('data')} é o JSON da fonte, sem tradução "
        "nossa. Use quando precisar de um campo que a API tratada não expõe. Todas <b>gastam "
        "consulta</b>."))
    f += tabela(["Rota", "O que devolve"], [
        ["GET /empresas/{cnpj}/assertiva", "Resposta completa da Assertiva para o CNPJ, sem recorte"],
        ["GET /pessoas/{cpf}/assertiva", "Resposta completa da Assertiva para o CPF"],
        ["GET /pessoas/{cpf}/mk", "Perfil Mk: renda, score, endereços, parentes, vizinhos, benefícios"],
        ["GET /pessoas/{cpf}/contatos", "Telefones e e-mails pela Serasa"],
        ["GET /empresas/{cnpj}/contatos-serasa", "Telefones e e-mails da empresa pela Serasa"],
        ["GET /empresas/{cnpj}/linkedin", "Funcionários com cargo pelo LinkedIn"],
        ["GET /assertiva/telefone/{numero}", "Dono do telefone, resposta completa"],
        ["GET /assertiva/email/{email}", "Quem está por trás do e-mail"],
        ["POST /pessoas/busca-avancada", "Busca por nome e/ou endereço na Assertiva"],
    ], [66 * mm, LARGURA - 66 * mm])

    # ── 4.6 ──
    f.append(p("4.6 Visões compostas — tudo numa chamada", h1))
    f += endpoint("GET", "/empresas/{cnpj}/completo", [("paga", "gasta por bloco")], [
        *code("GET /empresas/{cnpj}/completo?incluir=cadastro,socios,decisores,\n"
              "    funcionarios,conexoes,assertiva,linkedin"),
        p("Cada bloco é opcional e <b>cada bloco pago gasta consulta</b> — peça só o que vai "
          "usar. Um bloco que falha <b>não derruba os outros</b>:"),
        *code("""{
  "data": { "cadastro": {...}, "socios": [...], "decisores": {...} },
  "meta": {
    "blocos": ["cadastro", "socios", "decisores"],
    "falhas": { "funcionarios": "A base RAIS respondeu 504." }
  }
}"""),
        p("Medido no CNPJ da Google Brasil com cinco blocos: cadastro, 3 sócios, <b>602 "
          "decisores</b>, <b>1.023 funcionários</b> e 14 conexões, tudo em uma resposta."),
    ])
    f += endpoint("GET", "/pessoas/{cpf}/completo", [("paga", "gasta por bloco")], [
        *code("GET /pessoas/{cpf}/completo?incluir=cadastro,mk,assertiva,vinculos,\n"
              "    parentes,serasa"),
        p(f"Mesma mecânica: {c('meta.blocos')} diz o que veio, {c('meta.falhas')} diz o que não "
          f"veio e por quê. Bloco inexistente devolve {c('400 bloco_invalido')} listando os "
          "aceitos."),
    ])

    # ── 4.7 ──
    f.append(p("4.7 Lote", h1))
    f += endpoint("POST", "/enriquecimento", [("paga", "gasta se pedir campo pago")], [
        p("O “Minha planilha” em API: manda CNPJs e a lista de campos, recebe uma linha por "
          "CNPJ. Máximo de 200 por chamada."),
        *code("""curl -X POST "$BASE/enriquecimento" \\
  -H "Authorization: Bearer $TOKEN" \\
  -H 'Content-Type: application/json' \\
  -d '{"cnpjs":["06990590000123"],
       "campos":["rfb_razao","rfb_municipio","as_empresa_tel"]}'"""),
        p("Campos da Receita não gastam consulta; campos de fonte paga gastam "
          f"({c('meta.gasta_consulta')} avisa qual foi o caso)."),
        *aviso("Campo errado não passa em silêncio",
               f"Nome desconhecido volta em {c('meta.campos_ignorados')}; se <i>nenhum</i> campo "
               f"for válido, a resposta é {c('400 campos_desconhecidos')}. O catálogo está em "
               f"{c('GET /enriquecimento/campos')}.", "info"),
    ])
    f += endpoint("GET", "/enriquecimento/campos", [("gratis", "não gasta")], [
        p("Catálogo dos campos aceitos, agrupados por fonte, com indicação de quais cobram."),
    ])
    f += endpoint("POST", "/prospeccao/cobertura", [("paga", "2 consultas/CNPJ")], [
        p("Mede em quantas empresas da lista existe decisor na base, <b>sem puxar telefone</b>. "
          "Serve para decidir se vale rodar a prospecção antes de gastar. Máximo de 60 CNPJs."),
        *code('{ "meta": { "testadas": 3, "com_decisor": 1, "taxa": 33.3,\n'
              '           "consultas_gastas": 6 } }'),
    ])
    f += endpoint("POST", "/prospeccao/pessoas", [("gratis", "base local")], [
        p("Sócios e pessoas por filtros de empresa (UF, município, CNAE, porte), direto da base "
          "local."),
    ])

    # ── 4.8 ──
    f.append(p("4.8 Apoio, consumo e dossiê", h1))
    f += endpoint("GET", "/fontes", [("gratis", "não gasta")], [
        p("Quais fontes estão ativas, o que cada uma entrega e se cobra. Bom para o seu sistema "
          "degradar sozinho quando uma fonte cai."),
    ])
    f += endpoint("GET", "/lookups/{tipo}", [("gratis", "não gasta")], [
        p(f"Listas de domínio para montar filtro: {c('cnae')}, {c('natureza')}, "
          f"{c('municipio')}, {c('pais')}, {c('qualificacao')}, {c('motivo')}."),
    ])
    f += endpoint("GET", "/consumo", [("gratis", "não gasta")], [
        p("Consumo de hoje, limite e tokens do usuário. Para token de admin, inclui o relatório "
          f"do período ({c('?dias=30')}) com o total oficial da Assertiva."),
    ])
    f += endpoint("GET", "/dossie/{tipo}/{documento}",
                      [("adm", "só admin"), ("paga", "gasta consulta")], [
        p(f"Devolve {c('application/pdf')}, não JSON. {c('tipo')} é {c('cpf')} ou {c('cnpj')}; "
          f"aceita {c('insight=true')} (resumo por IA) e {c('familia=true')} (consulta os "
          "parentes)."),
        *code('curl -H "Authorization: Bearer $TOKEN" \\\n'
              '  "$BASE/dossie/cnpj/06990590000123?insight=true" -o dossie.pdf'),
    ])

    # ── 5 ──
    f.append(PageBreak())
    f.append(p("5. Administração de tokens", h1))
    f.append(p("Estas rotas usam <b>sessão de administrador</b>, não token de API — é o que a "
               "tela do painel consome."))
    f += tabela(["Método", "Rota", "Descrição"], [
        ["GET", "/api/admin/tokens", "Lista tokens (só o prefixo, nunca o segredo)"],
        ["POST", "/api/admin/tokens", "Cria token. Body: {user_id, nome, escopo}"],
        ["DELETE", "/api/admin/tokens/{id}", "Revoga um token"],
    ], [20 * mm, 48 * mm, LARGURA - 68 * mm])
    f.append(p("O token herda o <b>limite diário do usuário</b> a que pertence. Para dar mais "
               "folga a uma integração, ajuste o limite desse usuário no painel."))

    # ── 6 ──
    f.append(p("6. Objetos e relacionamentos", h1))
    f += tabela(["Objeto", "Descrição", "Relacionamentos"], [
        ["Empresa", "CNPJ na base da Receita", "tem Sócios, Decisores, Funcionários, Conexões"],
        ["Sócio", "Pessoa no quadro societário",
         "pertence a Empresa; é uma Pessoa quando o CPF resolve"],
        ["Decisor", "Gestor ligado ao CNPJ, com cargo e nível", "pertence a Empresa; é uma Pessoa"],
        ["Funcionário", "Vínculo declarado na RAIS",
         "liga Pessoa e Empresa, com admissão e desligamento"],
        ["Pessoa", "CPF na base local", "tem Telefones, Vínculos, Parentes"],
        ["Contato", "Sócio ou Decisor já com telefone", "o que a prospecção consome"],
    ], [26 * mm, 58 * mm, LARGURA - 84 * mm])

    # ── 7 ──
    f.append(p("7. Casos de uso", h1))
    f.append(p("Enriquecer um CRM com quem decide", h2))
    f += code("""# 1. acha as empresas do perfil
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \\
  "$BASE/empresas?uf=MG&porte=05&capital_min=1000000&limit=50"

# 2. para cada CNPJ, pega contatos com telefone
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \\
  "$BASE/empresas/06990590000123/contatos?max_decisores=2&tipo_telefone=celular\"""")
    f.append(p("Descobrir onde um lead trabalha, a partir do CPF", h2))
    f += code('curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \\\n'
              '  "$BASE/pessoas/03702149600/vinculos"')
    f.append(p("Validar de quem é um número que ligou", h2))
    f += code('curl -H "Authorization: Bearer $CAPIBLU_TOKEN" "$BASE/telefones/33997332652"')
    f.append(p("Controlar custo antes de rodar em lote", h2))
    f += code("""curl -H "Authorization: Bearer $CAPIBLU_TOKEN" "$BASE/conta"
# -> data.limites.restantes_hoje diz quantas consultas ainda cabem

curl -X POST "$BASE/prospeccao/cobertura" -H "Authorization: Bearer $CAPIBLU_TOKEN" \\
  -H 'Content-Type: application/json' -d '{"cnpjs":["...","..."]}'
# -> meta.taxa diz se vale rodar a lista inteira""")

    # ── 8 ──
    f.append(p("8. Boas práticas", h1))
    f += lista([
        "<b>Um token por integração</b>, com nome que diga quem usa. Revogar fica cirúrgico.",
        f"<b>Escopo {c('leitura')} por padrão.</b> Só suba para {c('consulta')} o que precisa gastar.",
        "<b>Trate o 429.</b> O limite é diário e por usuário: espere o dia virar ou peça mais "
        "folga a um admin.",
        "<b>Cacheie do seu lado.</b> CNPJ e RAIS mudam devagar; consultar o mesmo documento duas "
        "vezes no mesmo dia é dinheiro fora.",
        f"<b>Não trate ausência como erro.</b> {c('200')} com {c('data: []')} e um "
        f"{c('meta.aviso')} é resposta legítima.",
        f"<b>Peça só os blocos que usa</b> em {c('/completo')} — cada bloco pago cobra separado.",
    ])
    return f


def build():
    os.makedirs("exports", exist_ok=True)
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=15 * mm, rightMargin=15 * mm,
        topMargin=17 * mm, bottomMargin=14 * mm,
        title="API CapiBLU v1 — Documentação", author="CapiBLU",
        subject="Documentação técnica da API v1 do CapiBLU",
    )
    doc.build(conteudo(), onFirstPage=capa, onLaterPages=moldura)
    print(f"{OUT} — {os.path.getsize(OUT) / 1024:.0f} KB")


if __name__ == "__main__":
    build()
