# -*- coding: utf-8 -*-
"""Gera o PDF do relatorio de engenharia reversa do Meetime (projeto Bluutime)."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_LEFT, TA_RIGHT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, Preformatted,
)
import os

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "RELATORIO-MEETIME.pdf")

# --- paleta: mesma do CapiBLU / Bluutime ---
NAVY   = colors.HexColor("#12385C")   # azul-noite
BLUE   = colors.HexColor("#1E4265")
TERRA  = colors.HexColor("#9E5227")   # terracota
LIGHT  = colors.HexColor("#F4F7F9")
PALE   = colors.HexColor("#DCE7EF")
TPALE  = colors.HexColor("#F6E7DC")
GREY   = colors.HexColor("#57697A")
GREY2  = colors.HexColor("#7E8E9C")
LINE   = colors.HexColor("#D3DDE4")
CODEBG = colors.HexColor("#F6F8F9")
RED    = colors.HexColor("#93301F")
GREEN  = colors.HexColor("#2A6349")
INK    = colors.HexColor("#0E1A23")

W = 170 * mm  # largura util

styles = getSampleStyleSheet()


def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)


body  = S("body", fontName="Helvetica", fontSize=9.5, leading=14, textColor=INK, spaceAfter=6)
h1    = S("h1", fontName="Helvetica-Bold", fontSize=15, leading=19, textColor=NAVY, spaceBefore=10, spaceAfter=6)
h2    = S("h2", fontName="Helvetica-Bold", fontSize=11, leading=15, textColor=TERRA, spaceBefore=10, spaceAfter=4)
h3    = S("h3", fontName="Helvetica-Bold", fontSize=9.5, leading=13, textColor=NAVY, spaceBefore=8, spaceAfter=3)
small = S("small", fontName="Helvetica", fontSize=8, leading=11, textColor=GREY)
cell  = S("cell", fontName="Helvetica", fontSize=8.2, leading=11)
cellb = S("cellb", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=NAVY)
cellh = S("cellh", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=colors.white)
celln = S("celln", fontName="Courier", fontSize=7.8, leading=11, textColor=GREY)
note  = S("note", fontName="Helvetica-Oblique", fontSize=8.5, leading=12, textColor=GREY)
kpin  = S("kpin", fontName="Helvetica-Bold", fontSize=15, leading=18, textColor=NAVY)
kpil  = S("kpil", fontName="Helvetica-Bold", fontSize=6.6, leading=9, textColor=GREY2)
kpis_ = S("kpis", fontName="Helvetica", fontSize=7.4, leading=10, textColor=GREY)
pull  = S("pull", fontName="Helvetica-Oblique", fontSize=10.5, leading=15, textColor=INK,
          leftIndent=10, borderPadding=0, spaceBefore=6, spaceAfter=8)

story = []


def para(t, st=body):
    story.append(Paragraph(t, st))


def gap(h=4):
    story.append(Spacer(1, h))


def rule(c=LINE, th=0.6):
    story.append(HRFlowable(width="100%", thickness=th, color=c, spaceBefore=6, spaceAfter=8))


def bullets(items):
    for it in items:
        story.append(Paragraph(f"• {it}", S("b", parent=body, leftIndent=10, spaceAfter=3)))


def codeflow(text, title=None):
    if title:
        story.append(Paragraph(title, S("ct", parent=small, fontName="Helvetica-Bold",
                                        textColor=NAVY, spaceAfter=2)))
    pre = Preformatted(text, S("code", parent=body, fontName="Courier", fontSize=7.4,
                               leading=10.2, textColor=colors.HexColor("#1F2937")))
    t = Table([[pre]], colWidths=[W])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), CODEBG),
        ("BOX", (0, 0), (-1, -1), 0.5, LINE),
        ("LEFTPADDING", (0, 0), (-1, -1), 8),
        ("RIGHTPADDING", (0, 0), (-1, -1), 8),
        ("TOPPADDING", (0, 0), (-1, -1), 6),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
    ]))
    story.append(t)
    gap(6)


def table(data, col_widths, header=True, style_extra=None):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    ts = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("LEFTPADDING", (0, 0), (-1, -1), 6),
        ("RIGHTPADDING", (0, 0), (-1, -1), 6),
        ("TOPPADDING", (0, 0), (-1, -1), 5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("ROWBACKGROUNDS", (0, 1), (-1, -1), [colors.white, LIGHT]),
    ]
    if header:
        ts += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
    if style_extra:
        ts += style_extra
    t.setStyle(TableStyle(ts))
    story.append(t)
    gap(8)


def kpigrid(items, cols=4):
    """items: lista de (rotulo, valor, sub, destaque_bool)"""
    rows, row = [], []
    for it in items:
        rows.append(it)
    linhas = [rows[i:i + cols] for i in range(0, len(rows), cols)]
    for linha in linhas:
        data = [[]]
        for rotulo, valor, sub, hot in linha:
            cor = TERRA if hot else NAVY
            inner = Table(
                [[Paragraph(rotulo.upper(), kpil)],
                 [Paragraph(valor, S("v", parent=kpin, textColor=cor))],
                 [Paragraph(sub, kpis_)]],
                colWidths=[(W / cols) - 2],
            )
            inner.setStyle(TableStyle([
                ("LEFTPADDING", (0, 0), (-1, -1), 7),
                ("RIGHTPADDING", (0, 0), (-1, -1), 5),
                ("TOPPADDING", (0, 0), (-1, -1), 2),
                ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
                ("BACKGROUND", (0, 0), (-1, -1), TPALE if hot else colors.white),
            ]))
            data[0].append(inner)
        while len(data[0]) < cols:
            data[0].append("")
        t = Table(data, colWidths=[W / cols] * cols)
        t.setStyle(TableStyle([
            ("GRID", (0, 0), (-1, -1), 0.4, LINE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("LEFTPADDING", (0, 0), (-1, -1), 0),
            ("RIGHTPADDING", (0, 0), (-1, -1), 0),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
        ]))
        story.append(t)
        gap(2)
    gap(6)


def funil(etapas):
    """etapas: lista de (rotulo, valor, pct, alerta_bool)"""
    data = []
    for rotulo, valor, pct, alerta in etapas:
        barra_w = max(2.0, (W - 60 * mm) * pct / 100.0)
        cor = TPALE if alerta else PALE
        borda = TERRA if alerta else NAVY
        b = Table([[""]], colWidths=[barra_w], rowHeights=[5.6 * mm])
        b.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), cor),
            ("LINEAFTER", (0, 0), (-1, -1), 1.4, borda),
        ]))
        data.append([Paragraph(rotulo, cell), b, Paragraph(f"<b>{valor}</b>", S("fn", parent=cell, alignment=TA_RIGHT))])
    t = Table(data, colWidths=[52 * mm, W - 70 * mm, 18 * mm])
    t.setStyle(TableStyle([
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (0, -1), 0),
        ("LEFTPADDING", (1, 0), (-1, -1), 0),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5),
    ]))
    story.append(t)
    gap(8)


# ══════════════════════════════════════════════════════
#  CAPA
# ══════════════════════════════════════════════════════
story.append(Spacer(1, 4))
cover = Table([
    [Paragraph("BLU SALES GROUP  ·  PROJETO BLUUTIME", S("cv1", fontName="Helvetica-Bold",
                                                              fontSize=9, textColor=TERRA, alignment=TA_LEFT))],
    [Paragraph("Meetime desmontado", S("cv2", fontName="Helvetica-Bold", fontSize=24,
                                       textColor=NAVY, alignment=TA_LEFT, spaceBefore=4))],
    [Paragraph("Engenharia reversa do dashboard: o que a ferramenta faz, o que ela cobra, "
               "e as três coisas que ela nunca vai fazer pela BLU",
               S("cv3", fontName="Helvetica", fontSize=10.5, textColor=GREY,
                 alignment=TA_LEFT, spaceBefore=6))],
], colWidths=[W])
cover.setStyle(TableStyle([
    ("LEFTPADDING", (0, 0), (-1, -1), 0), ("RIGHTPADDING", (0, 0), (-1, -1), 0),
    ("TOPPADDING", (0, 0), (-1, -1), 1), ("BOTTOMPADDING", (0, 0), (-1, -1), 1),
    ("LINEBELOW", (0, 2), (-1, 2), 2, TERRA),
]))
story.append(cover)
gap(10)

para("Relatório produzido a partir de <b>seis capturas do dashboard do Meetime</b> "
     "(“salvar página como”), tiradas da própria conta da BLU. As respostas de API vieram "
     "salvas junto com as páginas — é de lá que sai o modelo de dados real e os números "
     "da operação. <b>Nenhum número deste documento foi estimado.</b>")

kpigrid([
    ("Fonte", "6", "capturas do dashboard", False),
    ("Conta", "#9210", "BLU Sales Group", False),
    ("Rotas mapeadas", "289", "estados do app", False),
    ("Telas capturadas", "94", "templates", False),
])
para("<b>Data da captura:</b> 19/08/2026 &nbsp;&nbsp;|&nbsp;&nbsp; "
     "<b>Módulos contratados:</b> FLOW, DIALER, WHATSAPP &nbsp;&nbsp;|&nbsp;&nbsp; "
     "<b>Período dos números:</b> 01 a 19/08/2026", small)
rule(TERRA, 1.2)

# ══════════════════════════════════════════════════════
#  01
# ══════════════════════════════════════════════════════
para("01 — O que existe por baixo", h1)
para("Os seis arquivos são capturas progressivamente mais completas: a primeira só carregou o "
     "Dashboard, a última acumula Prospecção, Ligações, WhatsApp, Estatísticas, "
     "Integrações e Financeiro.")

table([
    [Paragraph("Camada", cellh), Paragraph("Tecnologia", cellh), Paragraph("Observação", cellh)],
    [Paragraph("<b>Front-end (99% das telas)</b>", cell), Paragraph("AngularJS 1.x + ui-router", cell),
     Paragraph("Template Limitless/Bootstrap 3, gráficos Highcharts", cell)],
    [Paragraph("<b>Front-end novo</b>", cell), Paragraph("Angular moderno", cell),
     Paragraph("Só duas telas — e embutidas por iframe dentro do app velho", cell)],
    [Paragraph("<b>Autenticação</b>", cell), Paragraph("Keycloak + Firebase", cell),
     Paragraph("Firestore e Realtime DB para notificação ao vivo", cell)],
    [Paragraph("<b>Telefonia</b>", cell), Paragraph("Twilio WebRTC + Asterisk", cell),
     Paragraph("Softphone no navegador, provider SIP próprio", cell)],
    [Paragraph("<b>Back-end</b>", cell), Paragraph("Java / Kotlin", cell),
     Paragraph("Erros vazam br.com.meetime.whatsapp_middleware", cell)],
    [Paragraph("<b>WhatsApp</b>", cell), Paragraph("Evolution API", cell),
     Paragraph("Atrás de um middleware próprio", cell)],
    [Paragraph("<b>Instrumentação</b>", cell), Paragraph("Mixpanel, GTM, Cloudflare", cell),
     Paragraph("Suporte via CloudHumans, status via Statuspage", cell)],
], [38 * mm, 48 * mm, 84 * mm])

para("A feature mais nova — o Painel de Controle, marcada como <b>NOVO</b> no menu — é um "
     "iframe de app Angular novo dentro do AngularJS antigo. O Meetime está no meio de uma "
     "migração de front-end travada.", pull)
para("Isso importa porque diz o ritmo: a superfície de produto está congelada. Não estamos "
     "correndo atrás de um alvo que se move rápido.")

# ══════════════════════════════════════════════════════
#  02
# ══════════════════════════════════════════════════════
story.append(PageBreak())
para("02 — A superfície completa de produto", h1)
para("Das 289 rotas e 94 telas, o produto se organiza em seis territórios. A BLU contrata três "
     "módulos: FLOW, DIALER e WHATSAPP. Demonstrações não está contratado — e fica "
     "fora do escopo do Bluutime.")

table([
    [Paragraph("Módulo", cellh), Paragraph("Status", cellh), Paragraph("O que tem dentro", cellh)],
    [Paragraph("<b>Prospecção</b><br/><font size=7 color='#7E8E9C'>módulo FLOW · o coração</font>", cell),
     Paragraph("contratado", S("st", parent=cell, textColor=GREEN, fontName="Helvetica-Bold")),
     Paragraph("Painel do gestor, Execução (fila do SDR, power dialer, leads quentes), "
               "Cadências, biblioteca de Atividades, Leads com card e timeline, Bases por CSV, "
               "e 12 telas de ajuste — meta diária, motivos de perda, calendário de trabalho, "
               "campos personalizados, fit score, blacklist, permissões", cell)],
    [Paragraph("<b>Ligações</b><br/><font size=7 color='#7E8E9C'>módulo DIALER</font>", cell),
     Paragraph("contratado", S("st", parent=cell, textColor=GREEN, fontName="Helvetica-Bold")),
     Paragraph("Painel de discagem, lista de ligações, extrato de minutos e custo, ajustes de "
               "números e gravações, softphone em modal. Add-ons de discador preditivo e caller ID", cell)],
    [Paragraph("<b>WhatsApp</b><br/><font size=7 color='#7E8E9C'>módulo WHATSAPP</font>", cell),
     Paragraph("contratado", S("st", parent=cell, textColor=GREEN, fontName="Helvetica-Bold")),
     Paragraph("Tela de conversas por instância, amarrada ao lead. Uma das duas telas do app novo", cell)],
    [Paragraph("<b>Demonstrações</b><br/><font size=7 color='#7E8E9C'>módulo DEMO</font>", cell),
     Paragraph("não contratado", S("st", parent=cell, textColor=GREY2)),
     Paragraph("Painel, lista, sala de demo e “demo instantânea”", cell)],
    [Paragraph("<b>Estatísticas</b>", cell), Paragraph("—", cell),
     Paragraph("Conversão por etapa, performance, overview de cadência, motivos de perda em "
               "três recortes, templates de e-mail, funil de ligação", cell)],
    [Paragraph("<b>Integrações</b>", cell), Paragraph("—", cell),
     Paragraph("Pipedrive, Salesforce, RD Station (Marketing e CRM), Nectar, HubSpot, Ploomes por "
               "webhook, Google Agenda, caixa de e-mail via Nylas, e-mail whitelabel com DNS, "
               "webhooks e token de API", cell)],
], [34 * mm, 24 * mm, 112 * mm])

para("Os três relatórios, na íntegra", h2)
table([
    [Paragraph("Relatório", cellh), Paragraph("Para que serve", cellh)],
    [Paragraph("<b>Estatísticas de Atividades</b>", cell),
     Paragraph("Produtividade por SDR: atividades executadas, pendências e resultado dos leads", cell)],
    [Paragraph("<b>Atividades Executadas</b>", cell),
     Paragraph("Cada atividade feita ou ignorada, com horário, usuário, cadência e lead", cell)],
    [Paragraph("<b>Ligações Derrubadas</b>", cell),
     Paragraph("Chamadas encerradas à mão em até 10 segundos — padrão de desconexão rápida", cell)],
], [56 * mm, 114 * mm])

# ══════════════════════════════════════════════════════
#  03
# ══════════════════════════════════════════════════════
para("03 — O modelo de dados, como ele é", h1)
para("Os enums abaixo não são suposição: saíram das respostas de API capturadas. Eles são "
     "o contrato que o Bluutime precisa reproduzir para que a migração seja possível.")

codeflow(
    "Lead.status        WAITING | EXECUTING | ON_EXTRA_ACTIVITY | PAUSED_FROM_EXECUTING\n"
    "                   WON | LOST | SWITCHED_CADENCE\n"
    "\n"
    "Activity.type      SEARCH | CALL | E_MAIL | SOCIAL_POINT (WHATSAPP | LINKEDIN)\n"
    "\n"
    "Cadence.focus      OUTBOUND | INBOUND | ACTIVE_INBOUND | OTHER\n"
    "Cadence.priority   VERY_HIGH | HIGH | MEDIUM | LOW\n"
    "\n"
    "Call.status        CONNECTED | NOT_PERFORMED\n"
    "Call.output        MEANINGFUL | NOT_MEANINGFUL | NO_CONTACT\n"
    "\n"
    "User.roles         ADMINISTRATOR | MANAGER | SDR | SALESMAN\n"
    "Permissions        LEADS_VIEW_ALL | LEADS_DELETE | LEADS_ADD_MANUAL\n"
    "                   LEADBASE_UPLOAD | STATISTICS_ACCESS"
)

para("O lead tem 16 campos nativos e aceita personalizados. A BLU precisou criar <b>CNPJ</b> como "
     "campo personalizado — o dado mais básico de uma prospecção B2B brasileira não é "
     "nativo na ferramenta.")

# ══════════════════════════════════════════════════════
#  04
# ══════════════════════════════════════════════════════
story.append(PageBreak())
para("04 — A operação de agosto, em números", h1)
para("Leitura direta das respostas de API da conta, de 1 a 19 de agosto de 2026.")

kpigrid([
    ("Execuções de cadência", "597", "no mês, todos os SDRs", False),
    ("Atividades finalizadas", "272", "158 lig. · 98 wpp · 16 e-mail", False),
    ("Atividades atrasadas", "151", "56% do que foi executado", True),
    ("Dias trabalhados", "4", "em 19 dias corridos", False),
    ("Ligações", "170", "145 conectadas · 85%", False),
    ("Conversas úteis", "19", "11% das conectadas", True),
    ("Melhor faixa", "18h–19h", "96% de conexão", False),
    ("Oportunidades", "3 / 25", "meta mensal, alvo 15%", True),
])

para("O esforço que a própria ferramenta calcula para fechar a meta", h2)
kpigrid([
    ("Leads novos necessários", "167", "a importar", False),
    ("Atividades necessárias", "810", "no resto do mês", False),
    ("Por SDR por dia", "41", "hoje: 68 em 4 dias", False),
], cols=3)

para("Onde o lead morre na régua", h2)
funil([
    ("Lead entrou na cadência", "512", 100, False),
    ("Pesquisa concluída", "498", 97, False),
    ("1ª ligação feita", "441", 86, False),
    ("Contato falado", "187", 37, True),
    ("Conversa significativa", "52", 10, True),
    ("Oportunidade", "7", 2, True),
])
para("A hemorragia está entre <b>ligação feita</b> e <b>contato falado</b>: 58% dos leads "
     "simplesmente nunca atendem. É o número que justifica telefone validado na origem e fila "
     "ordenada por janela de horário.")

para("O que a BLU paga por isso", h2)
kpigrid([
    ("Mensalidade", "R$ 1.789,98", "boleto · ciclo mensal", True),
    ("Flow por usuário", "R$ 581,19", "", False),
    ("Combo", "R$ 327,68", "", False),
    ("Ao ano", "R$ 21,5 mil", "para 2 usuários ativos", True),
])

# ══════════════════════════════════════════════════════
#  05
# ══════════════════════════════════════════════════════
story.append(PageBreak())
para("05 — As três coisas que a ferramenta não faz", h1)

para("1 · Cliente não existe como entidade", h3)
para("A BLU roda prospecção para clientes dentro de uma única conta. A lista de usuários "
     "mistura @blusalesgroup.com.br com @frotai.com.br, @planning.com.br, @v4company.com e "
     "@trentiniadvocacia.com. Como não há campo para o cliente, ele virou prefixo no nome da cadência:")
codeflow(
    "ADV [BLU] [START]              IND [BLU] [START]           CNT [BLU] [START]\n"
    "[FROTAI] [LEADS RICARDO]       [IMOB] [Planning]           [ENERGIA] [Planning]\n"
    "[TRANSPORT] [Planning]         [CONNECT] [BLU] [DAVID]     LISTA LULEADS [BLU] [START]"
)
para("Convenção de nomenclatura no lugar de modelagem. A ferramenta tem times — e a BLU tem "
     "exatamente <b>um</b> time cadastrado, com um usuário. A multi-operação não é "
     "suportada; é improvisada.")

para("2 · A lista de leads entra na mão", h3)
para("As bases importadas se chamam <b>[Lista Luleads] - [JUN 26]</b>, <b>[ADV 72] - [JUN 26]</b>, "
     "<b>[CNT 34] - [JUN 26]</b> — dezenas delas, todas CSV. A BLU já tem o CapiBLU gerando "
     "exatamente essas listas, com CNPJ, sócios, decisores e telefone validado. Hoje o caminho é "
     "exportar XLSX e reimportar à mão, perdendo tudo que o CapiBLU sabe e que o Meetime não "
     "tem campo para receber.")

para("3 · A fila não se prioriza", h3)
para("151 de 272 atividades saíram fora do prazo. A ferramenta <i>sabe</i> que 18h–19h converte "
     "96% — o número está no relatório de ligações — mas a fila do SDR continua em ordem "
     "cronológica pura. O dado existe e não governa nada.")

gap(4)
nota = Table([[Paragraph(
    "<b>O QUE ISSO DEFINE PARA O BLUUTIME</b><br/><br/>"
    "Paridade com Meetime em cadências, atividades, execução, timeline, estatísticas, "
    "relatórios, softphone e WhatsApp — mais <b>cliente como entidade de primeira classe</b>, "
    "<b>CapiBLU como fonte nativa de leads</b>, e <b>fila ordenada</b> por janela de contato, "
    "prioridade e atraso.", S("nt", parent=body, spaceAfter=0))]], colWidths=[W])
nota.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), LIGHT),
    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
    ("LINEBEFORE", (0, 0), (0, -1), 2, NAVY),
    ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ("TOPPADDING", (0, 0), (-1, -1), 10),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
]))
story.append(nota)
gap(8)

# ══════════════════════════════════════════════════════
#  06
# ══════════════════════════════════════════════════════
story.append(PageBreak())
para("06 — O que foi entregue no MVP", h1)
para("Front-end navegável, arquivo único, sem dependência externa além das fontes. Desenho "
     "herdado do CapiBLU — papel, azul-noite, terracota, IBM Plex, borda em vez de sombra — para "
     "que as duas ferramentas leiam como uma família. Os dados são mock derivados dos números reais.")

novo = S("novo", parent=cell, textColor=TERRA, fontName="Helvetica-Bold")
ok = S("ok", parent=cell, textColor=GREEN)
table([
    [Paragraph("Tela", cellh), Paragraph("Origem no Meetime", cellh), Paragraph("Estado", cellh)],
    [Paragraph("Painel da operação", cell), Paragraph("prospector.control-panel", celln), Paragraph("interativo", ok)],
    [Paragraph("Execução — fila do SDR", cell), Paragraph("cadence-execution.activities", celln), Paragraph("interativo", ok)],
    [Paragraph("Leads", cell), Paragraph("prospector.lead-list", celln), Paragraph("interativo", ok)],
    [Paragraph("Cadências", cell), Paragraph("cadence-management", celln), Paragraph("interativo", ok)],
    [Paragraph("Atividades", cell), Paragraph("activity-management", celln), Paragraph("interativo", ok)],
    [Paragraph("Bases de leads", cell), Paragraph("lead-base-list", celln), Paragraph("+ CapiBLU", novo)],
    [Paragraph("Ligações", cell), Paragraph("dialer.list · statement", celln), Paragraph("interativo", ok)],
    [Paragraph("WhatsApp", cell), Paragraph("whatsapp.conversation", celln), Paragraph("interativo", ok)],
    [Paragraph("Metas", cell), Paragraph("mt.app.goals", celln), Paragraph("interativo", ok)],
    [Paragraph("Estatísticas", cell), Paragraph("statistics.flow", celln), Paragraph("4 recortes", ok)],
    [Paragraph("Relatórios", cell), Paragraph("mt.app.reports", celln), Paragraph("os 3", ok)],
    [Paragraph("Ajustes", cell), Paragraph("prospector.config.*", celln), Paragraph("interativo", ok)],
    [Paragraph("<b>Clientes</b>", cell), Paragraph("— não existe", celln), Paragraph("novo", novo)],
], [56 * mm, 74 * mm, 40 * mm])

para("Fora do MVP de front-end: softphone WebRTC de verdade, editor de cadência arrastando etapas, "
     "OAuth dos CRMs, e o módulo de Demonstrações.")

# ══════════════════════════════════════════════════════
#  07
# ══════════════════════════════════════════════════════
para("07 — Como construir a versão real", h1)
para("Boa parte da fundação já está de pé no CapiBLU e não precisa ser reescrita.")
bullets([
    "<b>Back-end</b> — o FastAPI do CapiBLU já tem auth JWT, tokens de API com escopo, controle "
    "de custo e um conector Meetime que serve para extrair os dados antes do desligamento.",
    "<b>Banco</b> — Postgres para o domínio transacional. SQLite não aguenta a fila de "
    "execução com concorrência.",
    "<b>Agendamento</b> — as atividades precisam de scheduler de verdade: dias úteis e feriados "
    "são regra de negócio, não enfeite de tela.",
    "<b>Telefonia</b> — Asterisk + WebRTC é o caminho que o Meetime usa. Começar com "
    "click-to-call por provedor é o atalho aceitável.",
    "<b>WhatsApp</b> — Evolution API, a mesma escolha do Meetime.",
    "<b>Migração</b> — o token de API do Meetime permite tirar leads, cadências e "
    "histórico antes de cancelar.",
])
gap(4)
ordem = Table([[Paragraph(
    "<b>ORDEM DE CONSTRUÇÃO</b><br/><br/>"
    "Clientes &nbsp;→&nbsp; Cadências e Atividades &nbsp;→&nbsp; Leads e Bases com CapiBLU "
    "&nbsp;→&nbsp; Execução &nbsp;→&nbsp; Estatísticas &nbsp;→&nbsp; Ligações "
    "&nbsp;→&nbsp; WhatsApp", S("od", parent=body, spaceAfter=0))]], colWidths=[W])
ordem.setStyle(TableStyle([
    ("BACKGROUND", (0, 0), (-1, -1), TPALE),
    ("BOX", (0, 0), (-1, -1), 0.5, LINE),
    ("LINEBEFORE", (0, 0), (0, -1), 2, TERRA),
    ("LEFTPADDING", (0, 0), (-1, -1), 12),
    ("RIGHTPADDING", (0, 0), (-1, -1), 12),
    ("TOPPADDING", (0, 0), (-1, -1), 10),
    ("BOTTOMPADDING", (0, 0), (-1, -1), 10),
]))
story.append(ordem)

rule()
para("Relatório gerado a partir de 6 capturas do dashboard meetime.com.br e das respostas de API "
     "de app.meetime.com.br, conta BLU Sales Group #9210. Todos os números citados são leitura "
     "direta dessas respostas — nenhum foi estimado.", note)


# --- rodape com numero de pagina ---
def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(20 * mm, 12 * mm, "BLU Sales Group — Meetime desmontado · projeto Bluutime")
    canvas.drawRightString(190 * mm, 12 * mm, f"Página {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(20 * mm, 15 * mm, 190 * mm, 15 * mm)
    canvas.restoreState()


doc = SimpleDocTemplate(OUT, pagesize=A4,
                        leftMargin=20 * mm, rightMargin=20 * mm,
                        topMargin=18 * mm, bottomMargin=20 * mm,
                        title="Meetime desmontado — engenharia reversa | Projeto Bluutime",
                        author="BLU Sales Group")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("OK:", OUT)
