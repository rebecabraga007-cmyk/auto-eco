# -*- coding: utf-8 -*-
"""Gera o PDF de alinhamento de projetos da Blu Sales Group."""
from reportlab.lib.pagesizes import A4
from reportlab.lib.units import mm
from reportlab.lib import colors
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_CENTER, TA_LEFT
from reportlab.platypus import (
    SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
    PageBreak, HRFlowable, KeepTogether, Preformatted,
)

OUT = "ALINHAMENTO-PROJETOS.pdf"

# --- paleta ---
NAVY   = colors.HexColor("#1B2A4A")
BLUE   = colors.HexColor("#2563EB")
LIGHT  = colors.HexColor("#EEF2FB")
GREY   = colors.HexColor("#5B6473")
LINE   = colors.HexColor("#D5DAE5")
CODEBG = colors.HexColor("#F4F6FA")
RED    = colors.HexColor("#DC2626")
ORANGE = colors.HexColor("#EA8C00")
YELLOW = colors.HexColor("#CA8A04")
GREEN  = colors.HexColor("#16A34A")

styles = getSampleStyleSheet()

def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)

body   = S("body", fontName="Helvetica", fontSize=9.5, leading=14, textColor=colors.HexColor("#222831"), spaceAfter=6)
h1     = S("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceBefore=10, spaceAfter=6)
h2     = S("h2", fontName="Helvetica-Bold", fontSize=11.5, leading=15, textColor=BLUE, spaceBefore=10, spaceAfter=4)
small  = S("small", fontName="Helvetica", fontSize=8, leading=11, textColor=GREY)
cell   = S("cell", fontName="Helvetica", fontSize=8.2, leading=11)
cellb  = S("cellb", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=NAVY)
cellh  = S("cellh", fontName="Helvetica-Bold", fontSize=8.2, leading=11, textColor=colors.white)
note   = S("note", fontName="Helvetica-Oblique", fontSize=8.5, leading=12, textColor=GREY)

story = []

def para(t, st=body): story.append(Paragraph(t, st))
def gap(h=4): story.append(Spacer(1, h))
def rule(): story.append(HRFlowable(width="100%", thickness=0.6, color=LINE, spaceBefore=6, spaceAfter=8))

def bullets(items):
    for it in items:
        story.append(Paragraph(f"• {it}", S("b", parent=body, leftIndent=10, spaceAfter=3)))

def codeflow(text, title=None):
    if title:
        story.append(Paragraph(title, S("ct", parent=small, fontName="Helvetica-Bold", textColor=NAVY, spaceAfter=2)))
    pre = Preformatted(text, S("code", parent=body, fontName="Courier", fontSize=7.8, leading=10.5, textColor=colors.HexColor("#1F2937")))
    t = Table([[pre]], colWidths=[170*mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,-1), CODEBG),
        ("BOX", (0,0), (-1,-1), 0.5, LINE),
        ("LEFTPADDING", (0,0), (-1,-1), 8),
        ("RIGHTPADDING", (0,0), (-1,-1), 8),
        ("TOPPADDING", (0,0), (-1,-1), 6),
        ("BOTTOMPADDING", (0,0), (-1,-1), 6),
    ]))
    story.append(t)
    gap(6)

def table(data, col_widths, header=True, align_first_left=True, style_extra=None):
    t = Table(data, colWidths=col_widths, repeatRows=1 if header else 0)
    ts = [
        ("GRID", (0,0), (-1,-1), 0.4, LINE),
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("LEFTPADDING", (0,0), (-1,-1), 6),
        ("RIGHTPADDING", (0,0), (-1,-1), 6),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ("ROWBACKGROUNDS", (0,1), (-1,-1), [colors.white, LIGHT]),
    ]
    if header:
        ts += [("BACKGROUND", (0,0), (-1,0), NAVY)]
    if style_extra:
        ts += style_extra
    t.setStyle(TableStyle(ts))
    story.append(t)
    gap(8)

# ============ CAPA / CABEÇALHO ============
story.append(Spacer(1, 6))
cover = Table([[Paragraph("BLU SALES GROUP", S("cv1", fontName="Helvetica-Bold", fontSize=10, textColor=BLUE, alignment=TA_LEFT))],
               [Paragraph("Alinhamento de Projetos", S("cv2", fontName="Helvetica-Bold", fontSize=22, textColor=NAVY, alignment=TA_LEFT, spaceBefore=2))],
               [Paragraph("Escopo, tecnologias, metodologias e fluxos de execução", S("cv3", fontName="Helvetica", fontSize=10.5, textColor=GREY, alignment=TA_LEFT, spaceBefore=4))]],
              colWidths=[170*mm])
cover.setStyle(TableStyle([
    ("LEFTPADDING",(0,0),(-1,-1),0),("RIGHTPADDING",(0,0),(-1,-1),0),
    ("TOPPADDING",(0,0),(-1,-1),1),("BOTTOMPADDING",(0,0),(-1,-1),1),
    ("LINEBELOW",(0,2),(-1,2),2,BLUE),
]))
story.append(cover)
gap(8)
para("Documento de alinhamento gerado a partir da reunião entre <b>João Gonçalves</b> (demandante) e "
     "<b>Rebeca Sampaio</b> (desenvolvimento). Objetivo: consolidar o escopo, as tecnologias, as metodologias "
     "e os fluxos de cada projeto, e definir a fila de execução.")
para("<b>Data de referência:</b> 30/06/2026 &nbsp;&nbsp;|&nbsp;&nbsp; <b>Participantes:</b> João Gonçalves, Rebeca Sampaio", small)
rule()

# ============ VISÃO GERAL ============
para("Visão geral e priorização", h1)
data = [
    [Paragraph("#",cellh), Paragraph("Projeto",cellh), Paragraph("Cliente / Dono",cellh),
     Paragraph("Tipo",cellh), Paragraph("Prioridade",cellh), Paragraph("Entrega",cellh)],
    [Paragraph("1",cell), Paragraph("<b>Vânia</b> — Centralizador de WhatsApp",cell), Paragraph("Movida (Inbound) — Vânia",cell),
     Paragraph("Produto Blu / Dashboard",cell), Paragraph("Top 1 — agora",S("p",parent=cell,textColor=RED,fontName="Helvetica-Bold")), Paragraph("Rebeca",cell)],
    [Paragraph("2",cell), Paragraph("<b>Capiblu</b> — Enriquecedor próprio",cell), Paragraph("Blu (proprietário)",cell),
     Paragraph("Substitui Datastone",cell), Paragraph("Após APIs",S("p",parent=cell,textColor=ORANGE,fontName="Helvetica-Bold")), Paragraph("João → Rebeca",cell)],
    [Paragraph("3",cell), Paragraph("<b>Eproc</b> — Empresas processadas",cell), Paragraph("Escritório de advocacia",cell),
     Paragraph("Geração de leads",cell), Paragraph("Depois do Capiblu",S("p",parent=cell,textColor=YELLOW,fontName="Helvetica-Bold")), Paragraph("Rebeca",cell)],
    [Paragraph("4",cell), Paragraph("<b>Pedreira</b> — Telemetria",cell), Paragraph("João (pessoal, fora da Blu)",cell),
     Paragraph("IoT + Dashboard",cell), Paragraph("Fim da fila",S("p",parent=cell,textColor=GREY,fontName="Helvetica-Bold")), Paragraph("Rebeca (à parte)",cell)],
]
table(data, [8*mm, 42*mm, 33*mm, 32*mm, 28*mm, 27*mm])
para("<b>Sequência acordada:</b> João dedica a semana entrante a fechar as APIs (Serasa, Claro, Vivo etc.) para o Capiblu. "
     "Em paralelo, Rebeca inicia o projeto Vânia (WhatsApp), de maior prioridade imediata. Eproc entra após o Capiblu. "
     "Pedreira fica para o fim da fila.")
story.append(PageBreak())

# ============ PROJETO 1 ============
para("Projeto 1 — Vânia (Centralizador de WhatsApp da Movida)", h1)
para("Objetivo", h2)
para("Centralizar e ler os WhatsApps dos executivos de venda da Movida (inbound) para extrair <b>métricas de atendimento</b> "
     "que hoje não existem — porque o CRM (Meetime) não é atualizado em tempo real e toda a conversa com o lead acontece dentro do WhatsApp.")
para("Contexto de negócio — fluxo atual", h2)
bullets([
    "SDR recebe lead de inbound no Meetime e qualifica.",
    "SDR repassa o lead a um executivo e o avisa <b>pelo WhatsApp</b>.",
    "O executivo contata o lead <b>pelo WhatsApp</b> para vender (ex.: aluguel de frota).",
    "Hoje não há visibilidade sobre o que acontece a partir daí.",
])
para("Métricas a extrair (via LLM lendo as conversas)", h2)
bullets([
    "<b>Tempo de resposta SDR → executivo:</b> intervalo entre repassar o lead e o executivo chamá-lo.",
    "<b>Conteúdo e desfecho:</b> objeções (\"achei caro\", \"a Localiza é mais barata\"), adiamentos, motivo da não contratação.",
    "<b>Falha de follow-up:</b> quando o executivo não deu sequência quando deveria.",
    "<b>Volume por executivo:</b> quantos leads recebeu por semana e tempo médio de resposta.",
])
para("Escopo — o que é e o que não é", h2)
bullets([
    "<font color='#16A34A'><b>✔</b></font> <b>Apenas leitura</b> das conversas — ver e coletar métricas.",
    "<font color='#DC2626'><b>✘</b></font> <b>Não</b> envia nem responde mensagens (não é CRM operacional).",
    "<font color='#16A34A'><b>✔</b></font> Interface de <b>conexão por QR Code</b> (igual WhatsApp Web) para reconectar quando a sessão cair.",
    "<font color='#16A34A'><b>✔</b></font> Acesso de <b>administrador</b> para a gestora abrir a conversa de qualquer executivo.",
    "<font color='#16A34A'><b>✔</b></font> As informações alimentam <b>dashboard / e-mail / relatório</b>.",
])
para("Tecnologias", h2)
bullets([
    "<b>Linguagem:</b> Python.",
    "<b>Conexão WhatsApp:</b> integração via protocolo WhatsApp Web (QR Code).",
    "<b>LLM:</b> API da Anthropic (<b>Claude</b>) — chave própria da Blu — para interpretar as conversas.",
    "<b>Entrega:</b> integração com o Dashboard existente.",
])
para("Fluxo de implementação", h2)
codeflow(
"Executivo conecta WhatsApp via QR Code (interface de conexao)\n"
"        |\n"
"Sincronizacao das conversas (somente leitura)\n"
"        |\n"
"LLM (Claude) le cada conversa e extrai:\n"
"   tempo de resposta | objecoes | desfecho | follow-up pendente\n"
"        |\n"
"Metricas estruturadas\n"
"        |\n"
"Painel admin (gestora ve qualquer executivo)  +  Dashboard / e-mail")
para("Integração com o Dashboard", h2)
para("O WhatsApp será tratado como <b>mais um canal/API</b> do dashboard existente (que já consome Meetime, Zenvia e planilha). "
     "É o \"passo 2\" do dashboard: construído separadamente e depois conectado como uma API adicional, exportável no \"modo Movida\".")
para("Pontos de atenção", h2)
bullets([
    "<b>Estabilidade da sessão:</b> prever reconexão fácil (QR Code) — a sessão pode cair com frequência.",
    "<b>Privacidade / LGPD:</b> monitorar comunicação de colaboradores e dados de leads exige base legal e transparência. Validar política e consentimento antes do go-live.",
    "<b>Nome do projeto:</b> Vânia (homenagem à responsável que solicitou).",
])
story.append(PageBreak())

# ============ PROJETO 2 ============
para("Projeto 2 — Capiblu (Enriquecedor de leads proprietário)", h1)
para("Objetivo", h2)
para("Construir um enriquecedor de leads <b>próprio da Blu</b> para deixar de depender da Datastone, integrando diretamente as "
     "fontes (Serasa, telefonias) e oferecendo uma interface com <b>chat</b> onde o usuário pede leads em linguagem natural.")
para("Escopo", h2)
bullets([
    "Enriquecimento a partir de fontes próprias: <b>Serasa, Claro, Vivo</b> e outros bureaus a negociar.",
    "<b>Interface com chat</b>: o usuário pede, ex.: \"quero 50 leads de contabilidade\", e o sistema retorna.",
    "Base visual: reaproveitar a <b>interface já clonada da Datastone</b> (\"Testone\"), <b>adicionando</b> a camada de chat.",
])
para("Tecnologias", h2)
bullets([
    "<b>APIs de dados:</b> Serasa, Claro, Vivo e demais bureaus (negociadas/contratadas por João).",
    "<b>Front-end:</b> clone da interface Datastone + módulo de chat (linguagem natural → consulta às APIs).",
    "<b>Back-end:</b> orquestração das chamadas às APIs de enriquecimento.",
])
para("Fluxo", h2)
codeflow(
"[Fase Joao - semana entrante]\n"
"Negociar e contratar as APIs (Serasa, Claro, Vivo, ...)\n"
"        |\n"
"Entregar credenciais/contratos das APIs a Rebeca\n"
"        |\n"
"[Fase Rebeca]\n"
"Montar o back-end de orquestracao das APIs\n"
"        |\n"
"Construir o chat sobre a interface clonada (Testone)\n"
"        |\n"
"Usuario pede em linguagem natural -> sistema enriquece e retorna leads")
para("Pré-requisito / bloqueio", h2)
bullets([
    "<font color='#DC2626'><b>⛔ Depende das APIs.</b></font> Rebeca só inicia quando João entregar as APIs negociadas (compromisso para a semana entrante).",
])
para("Pontos de atenção", h2)
bullets([
    "<b>Não usar a API da Datastone</b> — o objetivo é justamente substituí-la por fontes próprias.",
    "A coleta de \"sinais\"/engenharia reversa de APIs de terceiros é juridicamente sensível; priorizar a contratação oficial das APIs (caminho já acordado).",
    "<b>Nome do projeto:</b> Capiblu.",
])
story.append(PageBreak())

# ============ PROJETO 3 ============
para("Projeto 3 — Eproc (Prospecção de empresas processadas)", h1)
para("Objetivo", h2)
para("Gerar leads para um <b>escritório de advocacia</b> que vende serviço de <b>redução/defesa de dívida</b>. O escritório atende "
     "<b>empresas processadas por bancos</b>. A ideia é extrair, de fontes públicas, o <b>CNPJ das empresas processadas</b> para prospectá-las.")
para("Contexto de negócio", h2)
bullets([
    "Quando um banco entra com ação de cobrança contra uma empresa, a informação é <b>pública</b> (TJ / sistema Eproc).",
    "Muitas vezes a empresa sabe da dívida mas não sabe que já foi judicializada → <b>timing é o diferencial</b>.",
    "O cliente do escritório é a <b>empresa processada</b> (não o banco) — o objetivo é ajudá-la a se defender.",
])
para("Escopo", h2)
bullets([
    "Extrair <b>diariamente</b> a lista de empresas processadas (comporta-se como inbound contínuo).",
    "Capturar o <b>CNPJ da empresa processada</b> (não precisa de lead 100% enriquecido nessa etapa).",
    "Enriquecimento posterior via Datastone ou o próprio Capiblu.",
])
para("Tecnologias", h2)
bullets([
    "<b>Fonte:</b> Eproc (processos eletrônicos / dados públicos do TJ).",
    "<b>Automação:</b> busca/raspagem <b>agendada</b> que roda sozinha todos os dias.",
    "<b>Enriquecimento:</b> Datastone (ou Capiblu).",
])
para("Fluxo", h2)
codeflow(
"[Diariamente - automatico]\n"
"Consultar o Eproc por novas acoes de bancos contra empresas\n"
"        |\n"
"Extrair o CNPJ da empresa processada (parte re)\n"
"        |\n"
"Montar lista de leads do dia\n"
"        |\n"
"Enriquecer (Datastone / Capiblu)\n"
"        |\n"
"Entregar ao escritorio de advocacia para prospeccao")
para("Pesquisa pendente (antes de desenvolver)", h2)
bullets([
    "<b>❓ Verificar se o Eproc exige acesso/credenciais de advogado (OAB)</b> para consultar os processos.",
])
para("Pontos de atenção", h2)
bullets([
    "Sem material escrito do cliente — escopo levantado em ligação. Validar regra de negócio com João ao longo do desenvolvimento.",
    "Confirmar grafia/sistema: \"Eproc\" (e-Proc).",
    "Atenção a termos de uso e limites de consulta de dados judiciais públicos.",
])
story.append(PageBreak())

# ============ PROJETO 4 ============
para("Projeto 4 — Pedreira (Telemetria de mineração) — fora da Blu", h1)
para("Objetivo", h2)
para("Dar visibilidade de <b>estoque e produção</b> das pedreiras/mineradoras de João (12 unidades). Hoje o controle é "
     "<b>manual</b> — uma pessoa percorre as pedreiras e anota tudo num caderno.")
para("Contexto de negócio", h2)
bullets([
    "A rocha é explodida, britada e separada por granularidade (rachão, brita, pó de brita, concreto).",
    "Falta visibilidade de: quanto entrou de pedra, quanto saiu (por peneira) e quanto há em estoque.",
])
para("Escopo", h2)
bullets([
    "Pesar o material na entrada e na saída, por peneira/granularidade.",
    "Enviar os dados a um computador e processá-los em um <b>dashboard</b> de entrada × produção × estoque × vendas.",
])
para("Tecnologias", h2)
bullets([
    "<b>Hardware:</b> balanças de esteira com sensores.",
    "<b>Aquisição de sinal:</b> módulos tipo Arduino para ler as balanças e transmitir os dados.",
    "<b>Software:</b> ingestão → processamento → dashboard.",
    "<font color='#16A34A'><b>✔ Vantagem:</b></font> o hardware já existe — é \"montar as peças do quebra-cabeça\", não desenvolver hardware do zero.",
])
para("Fluxo", h2)
codeflow(
"Balanca de esteira (sensor) -> modulo Arduino\n"
"        |\n"
"Transmissao dos dados de peso (entrada / saida por peneira)\n"
"        |\n"
"Computador / servidor processa\n"
"        |\n"
"Dashboard: entrou X t -> britas Y, po Z, rachao W -> estoque + vendido")
para("Pontos de atenção", h2)
bullets([
    "<b>Projeto pessoal de João, fora da Blu</b> — remuneração à parte.",
    "Requer <b>visita presencial</b> (Itajaí) — passagem/hospedagem custeadas por João.",
    "João fará visita a uma pedreira na semana seguinte para mapear a montagem.",
    "<b>Prioridade:</b> fim da fila, após o Capiblu.",
])
story.append(PageBreak())

# ============ RESUMO DE TECNOLOGIAS ============
para("Resumo de tecnologias por projeto", h1)
data = [
    [Paragraph("Projeto",cellh), Paragraph("Stack",cellh), Paragraph("Fontes/APIs",cellh),
     Paragraph("LLM",cellh), Paragraph("Hardware",cellh), Paragraph("Entrega",cellh)],
    [Paragraph("<b>Vânia</b>",cellb), Paragraph("Python",cell), Paragraph("WhatsApp Web (QR)",cell),
     Paragraph("Claude",cell), Paragraph("—",cell), Paragraph("Dashboard + admin + e-mail",cell)],
    [Paragraph("<b>Capiblu</b>",cellb), Paragraph("Front (clone) + back",cell), Paragraph("Serasa, Claro, Vivo, bureaus",cell),
     Paragraph("LLM no chat",cell), Paragraph("—",cell), Paragraph("Interface com chat",cell)],
    [Paragraph("<b>Eproc</b>",cellb), Paragraph("Python (scraper agendado)",cell), Paragraph("Eproc + Datastone/Capiblu",cell),
     Paragraph("—",cell), Paragraph("—",cell), Paragraph("Lista diária de CNPJs",cell)],
    [Paragraph("<b>Pedreira</b>",cellb), Paragraph("Ingestão + dashboard",cell), Paragraph("—",cell),
     Paragraph("—",cell), Paragraph("Balança + Arduino",cell), Paragraph("Dashboard de estoque",cell)],
]
table(data, [24*mm, 33*mm, 38*mm, 18*mm, 27*mm, 30*mm])

# ============ PRÓXIMOS PASSOS ============
para("Próximos passos / checklist", h1)
para("João", h2)
bullets([
    "☐ Negociar e contratar APIs do Capiblu (Serasa, Claro, Vivo, demais) — semana entrante.",
    "☐ Entregar credenciais/contratos das APIs à Rebeca quando fechadas.",
    "☐ Visitar pedreira para mapear montagem das balanças (projeto Pedreira).",
    "☐ Responder dúvidas pontuais (pode enviar perguntas que Rebeca compilar).",
])
para("Rebeca", h2)
bullets([
    "☐ <b>Iniciar Projeto Vânia (WhatsApp)</b> — prioridade imediata.",
    "☐ Validar biblioteca de conexão WhatsApp (QR Code) e teste de leitura.",
    "☐ Definir prompt/estrutura da LLM (Claude) para extrair as métricas.",
    "☐ Pesquisar acesso ao Eproc (exige OAB?).",
    "☐ Planejar integração do canal WhatsApp como nova API do Dashboard.",
    "☐ Aguardar APIs para iniciar o Capiblu.",
])
rule()
para("Documento de alinhamento interno — Blu Sales Group. Sujeito a revisão conforme validações de negócio e viabilidade técnica.", note)


# --- rodapé com número de página ---
def footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(GREY)
    canvas.drawString(20*mm, 12*mm, "Blu Sales Group — Alinhamento de Projetos")
    canvas.drawRightString(190*mm, 12*mm, f"Página {doc.page}")
    canvas.setStrokeColor(LINE)
    canvas.line(20*mm, 15*mm, 190*mm, 15*mm)
    canvas.restoreState()

doc = SimpleDocTemplate(OUT, pagesize=A4,
                        leftMargin=20*mm, rightMargin=20*mm,
                        topMargin=18*mm, bottomMargin=20*mm,
                        title="Alinhamento de Projetos — Blu Sales Group",
                        author="Blu Sales Group")
doc.build(story, onFirstPage=footer, onLaterPages=footer)
print("OK:", OUT)
