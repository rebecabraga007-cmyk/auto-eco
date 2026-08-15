# -*- coding: utf-8 -*-
"""PDF com TODOS os campos que cada endpoint da API Localize V3 devolve.

Os campos saem do swagger oficial da Assertiva, achatados a partir dos schemas
de resposta (o script de extração fica no scratchpad: extrai_campos.py).
Notação: `a.b` = objeto aninhado, `a[]` = lista, `a[].b` = campo de cada item.
"""
import json
import os

from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate, Spacer,
    Table, TableStyle,
)

CAMPOS = os.path.join(
    os.environ.get("TEMP", "."),
    r"claude\C--Users-rebec-OneDrive-Documentos-BLU-AUTO-maisobras-enricher"
    r"\6fdb8f80-bdc9-44ab-a66e-5faf28bc51bd\scratchpad\campos_localize.json")
OUT = os.path.join("exports", "assertiva-localize-campos.pdf")

NAVY      = colors.HexColor("#0F2E4A")
BLUE      = colors.HexColor("#12385C")
TERRACOTA = colors.HexColor("#A85A2C")
PAPEL     = colors.HexColor("#F1EEE7")
GREEN     = colors.HexColor("#2F6B4F")
GREY      = colors.HexColor("#55595F")
LINE      = colors.HexColor("#DBD4C6")
ZEBRA     = colors.HexColor("#FBFAF7")

styles = getSampleStyleSheet()


def S(name, **kw):
    base = kw.pop("parent", styles["Normal"])
    return ParagraphStyle(name, parent=base, **kw)


h1   = S("h1", fontName="Helvetica-Bold", fontSize=16, leading=20, textColor=NAVY, spaceAfter=3)
sub  = S("sub", fontName="Helvetica", fontSize=9, leading=12.5, textColor=GREY, spaceAfter=8)
h2   = S("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=colors.white)
h2s  = S("h2s", fontName="Helvetica", fontSize=8, leading=11, textColor=colors.HexColor("#C6D8E5"))
cab  = S("cab", fontName="Helvetica-Bold", fontSize=7.4, leading=9.6, textColor=colors.white)
campo = S("campo", fontName="Courier", fontSize=7.2, leading=9.2, textColor=colors.HexColor("#1A1D21"))
campob = S("campob", fontName="Courier-Bold", fontSize=7.2, leading=9.2, textColor=BLUE)
tipo = S("tipo", fontName="Helvetica", fontSize=7, leading=9.2, textColor=GREY)
ex   = S("ex", fontName="Helvetica-Oblique", fontSize=6.8, leading=9.2, textColor=GREY)
foot = S("foot", fontName="Helvetica", fontSize=7.5, leading=10.5, textColor=GREY)
dest = S("dest", fontName="Helvetica", fontSize=8.5, leading=12, textColor=colors.HexColor("#1A1D21"))

# Campos que respondem perguntas de negócio comuns — marcados no PDF.
DESTAQUES = {
    "resposta.dadosCadastrais.quantidadeFuncionarios",
    "resposta.dadosCadastrais.porteEmpresa",
    "resposta.dadosCadastrais.idadeEmpresa",
    "resposta.dadosCadastrais.faturamentoPresumido",
    "resposta.possiveisDecisores[].cargo",
    "resposta.dadosCadastrais.rendaPresumida",
}


def cabecalho(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, doc.pagesize[1] - 11 * mm, doc.pagesize[0], 11 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 8.5)
    canvas.drawString(14 * mm, doc.pagesize[1] - 7.5 * mm, "CapiBLU · campos do JSON da API Localize V3")
    canvas.setFont("Helvetica", 7.5)
    canvas.drawRightString(doc.pagesize[0] - 14 * mm, doc.pagesize[1] - 7.5 * mm, f"pagina {doc.page}")
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 6.8)
    canvas.drawString(14 * mm, 8 * mm, "Fonte: swagger oficial da Assertiva · notacao: a.b = objeto, a[] = lista")
    canvas.restoreState()


def build():
    catalogo = json.load(open(CAMPOS, encoding="utf-8"))
    os.makedirs("exports", exist_ok=True)
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=14 * mm, rightMargin=14 * mm,
        topMargin=15 * mm, bottomMargin=13 * mm,
        title="Campos do JSON da API Localize V3 — Assertiva", author="CapiBLU")

    total = sum(len(c["campos"]) for c in catalogo)
    com_dado = [c for c in catalogo if c["campos"]]

    flow = [
        Paragraph("Tudo que a Localize devolve, campo por campo", h1),
        Paragraph(
            f"{total} campos em {len(com_dado)} endpoints, extraidos dos schemas de resposta do "
            "swagger oficial da Assertiva. <b>Notacao:</b> <font face='Courier'>a.b</font> = objeto "
            "aninhado, <font face='Courier'>a[]</font> = lista, <font face='Courier'>a[].b</font> = "
            "campo de cada item da lista. Os exemplos sao os do proprio swagger (dados ficticios).",
            sub),
        Paragraph(
            "<b>Atalho para as perguntas mais comuns:</b> quantos funcionarios e qual o porte da "
            "empresa estao em <font face='Courier'>resposta.dadosCadastrais.quantidadeFuncionarios</font> "
            "e <font face='Courier'>porteEmpresa</font>, na consulta de CNPJ — junto com "
            "<font face='Courier'>idadeEmpresa</font>, <font face='Courier'>site</font> e "
            "<font face='Courier'>temGoogleMeuNegocio</font>. Campos assim vem destacados em terracota.",
            dest),
        HRFlowable(width="100%", color=LINE, spaceBefore=8, spaceAfter=4),
    ]

    for i, item in enumerate(catalogo):
        if not item["campos"]:
            continue
        titulo = Table(
            [[Paragraph(f"{item['metodo']} {item['rota']}", h2)],
             [Paragraph(f"{item['resumo']} — {len(item['campos'])} campos", h2s)]],
            colWidths=[doc.width])
        titulo.setStyle(TableStyle([
            ("BACKGROUND", (0, 0), (-1, -1), NAVY),
            ("LEFTPADDING", (0, 0), (-1, -1), 8),
            ("RIGHTPADDING", (0, 0), (-1, -1), 8),
            ("TOPPADDING", (0, 0), (-1, 0), 5),
            ("BOTTOMPADDING", (0, -1), (-1, -1), 5),
            ("TOPPADDING", (0, 1), (-1, 1), 0),
        ]))

        dados = [[Paragraph("Campo", cab), Paragraph("Tipo", cab), Paragraph("Exemplo", cab)]]
        estilos = [
            ("BACKGROUND", (0, 0), (-1, 0), BLUE),
            ("VALIGN", (0, 0), (-1, -1), "TOP"),
            ("GRID", (0, 0), (-1, -1), 0.3, LINE),
            ("TOPPADDING", (0, 0), (-1, -1), 2),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 2),
            ("LEFTPADDING", (0, 0), (-1, -1), 4),
            ("RIGHTPADDING", (0, 0), (-1, -1), 4),
        ]
        for k, c in enumerate(item["campos"], start=1):
            destaque = c["campo"] in DESTAQUES
            estilo_campo = campob if (destaque or c["tipo"] in ("objeto", "lista")) else campo
            dados.append([
                Paragraph(c["campo"].replace(".", ".<font size=1> </font>"), estilo_campo),
                Paragraph(c["tipo"], tipo),
                Paragraph(c["exemplo"] or "", ex),
            ])
            if destaque:
                estilos.append(("BACKGROUND", (0, k), (-1, k), colors.HexColor("#FBEFE7")))
                estilos.append(("TEXTCOLOR", (0, k), (0, k), TERRACOTA))
            elif k % 2 == 0:
                estilos.append(("BACKGROUND", (0, k), (-1, k), ZEBRA))

        tabela = Table(dados, colWidths=[92 * mm, 24 * mm, doc.width - 116 * mm], repeatRows=1)
        tabela.setStyle(TableStyle(estilos))

        flow.append(KeepTogether([titulo, Spacer(1, 3)]))
        flow.append(tabela)
        flow.append(Spacer(1, 10))

    flow += [
        HRFlowable(width="100%", color=LINE, spaceBefore=4, spaceAfter=6),
        Paragraph("Campos marcados como <i>(recursivo: X)</i> apontam de volta para um schema ja "
                  "listado — o swagger define estruturas que se referenciam.", foot),
        Paragraph("Endpoints sem campos listados (report/usage/export) devolvem apenas uma URL de "
                  "download; os DELETE devolvem so a confirmacao da operacao.", foot),
    ]

    doc.build(flow, onFirstPage=cabecalho, onLaterPages=cabecalho)
    print("PDF gerado:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    build()
