# -*- coding: utf-8 -*-
"""Gera o PDF com os 28 endpoints da API Localize V3 da Assertiva.

A tabela sai do swagger oficial
(integracao.assertivasolucoes.com.br/v3/swagger/localize/swagger.json),
não de documentação de terceiros. Paleta = design system do CapiBLU.
"""
import json
import os
import sys

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER
from reportlab.lib.pagesizes import A4, landscape
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle,
)

OUT = os.path.join("exports", "assertiva-localize-endpoints.pdf")

# --- paleta do CapiBLU ---
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


h1    = S("h1", fontName="Helvetica-Bold", fontSize=17, leading=21, textColor=NAVY, spaceAfter=2)
sub   = S("sub", fontName="Helvetica", fontSize=9.5, leading=13, textColor=GREY, spaceAfter=10)
h2    = S("h2", fontName="Helvetica-Bold", fontSize=10.5, leading=14, textColor=TERRACOTA,
          spaceBefore=12, spaceAfter=5)
cellh = S("cellh", fontName="Helvetica-Bold", fontSize=7.6, leading=10, textColor=colors.white)
cell  = S("cell", fontName="Helvetica", fontSize=7.4, leading=9.6)
cellb = S("cellb", fontName="Helvetica-Bold", fontSize=7.4, leading=9.6, textColor=NAVY)
mono  = S("mono", fontName="Courier-Bold", fontSize=7.2, leading=9.6, textColor=BLUE)
par   = S("par", fontName="Courier", fontSize=6.6, leading=8.8, textColor=GREY)
ctr   = S("ctr", fontName="Helvetica-Bold", fontSize=7.4, leading=9.6, alignment=TA_CENTER)
note  = S("note", fontName="Helvetica-Oblique", fontSize=8, leading=11.5, textColor=GREY)
foot  = S("foot", fontName="Helvetica", fontSize=7.5, leading=10, textColor=GREY)

# (metodo, rota, o que faz, obrigatorios, opcionais/body, gasta, capiblu)
LINHAS = [
    ("GET", "/localize/v3/cpf", "Cadastro completo de uma pessoa",
     "cpf, idFinalidade", "", "Sim", "sim"),
    ("GET", "/localize/v3/cnpj", "Cadastro completo de uma empresa",
     "cnpj, idFinalidade", "", "Sim", "sim"),
    ("GET", "/localize/v3/email", "Quem esta por tras do e-mail",
     "email, idFinalidade", "", "Sim", "sim"),
    ("GET", "/localize/v3/nome-endereco", "Busca por nome ou endereco",
     "buscarPor, idFinalidade",
     "opc: nomeOuRazaoSocial, nomeOuRazaoSocialExata, sexo, "
     "dataNascimentoOuAbertura, uf, cidade, bairro, cepOuNomeRua, "
     "numeroInicial, numeroFinal, complemento", "Sim", "sim"),
    ("GET", "/localize/v3/telefone", "Dono do numero (PF ou PJ)",
     "telefone, idFinalidade", "", "Sim", "sim"),
    ("GET", "/localize/v3/mais-telefones", "Telefones adicionais de um documento",
     "tipo, documento, protocolo", "", "Provavel (1)", "nao"),
    ("GET", "/localize/v3/pessoas-de-referencia", "Mae, filhos, irmaos e socios de um CPF",
     "cpf, retornarMae, idFinalidade", "opc: protocolo", "Provavel (1)", "nao"),
    ("GET", "/localize/v3/possiveis-decisores", "Gestores de um CNPJ, com cargo",
     "cnpj, protocolo", "", "Sim, subitem do CNPJ", "sim"),
    ("GET", "/localize-api/v1/base-cadastral/conexoes", "Conexoes de CPF/CNPJ, com telefone",
     "documento, tipo, idFinalidade", "opc: conjuge, telefones", "Sim, item proprio (2)", "sim"),
    ("GET", "/feedback/v3/telefone", "Lista avaliacoes e justificativas possiveis",
     "", "", "Nao", "nao"),
    ("POST", "/feedback/v3/telefone", "Avalia um telefone devolvido pela Assertiva",
     "", "body: tipo, documento, telefone, idAvaliacao, idJustificativa", "Nao", "nao"),
    ("PUT", "/feedback/v3/telefone/{id}", "Altera a avaliacao",
     "id", "body: tipo, documento, telefone, idAvaliacao, idJustificativa", "Nao", "nao"),
    ("DELETE", "/feedback/v3/telefone/{id}", "Exclui a avaliacao", "id", "", "Nao", "nao"),
    ("POST", "/meu-portal/v3/comentario", "Anexa comentario ao documento",
     "", "body: tipo, documento, comentario", "Nao", "nao"),
    ("PUT", "/meu-portal/v3/comentario/{id}", "Altera o comentario",
     "id", "body: tipo, documento, comentario", "Nao", "nao"),
    ("DELETE", "/meu-portal/v3/comentario/{id}", "Exclui o comentario", "id", "", "Nao", "nao"),
    ("POST", "/meu-portal/v3/email", "Cadastra e-mail de contato",
     "", "body: tipo, documento, email", "Nao", "nao"),
    ("PUT", "/meu-portal/v3/email/{id}", "Altera o e-mail",
     "id", "body: tipo, documento, email", "Nao", "nao"),
    ("DELETE", "/meu-portal/v3/email/{id}", "Exclui o e-mail", "id", "", "Nao", "nao"),
    ("POST", "/meu-portal/v3/endereco", "Cadastra endereco",
     "", "body: tipo, documento, tipoLogradouro, logradouro, numero, "
         "complemento, bairro, cidade, uf, cep", "Nao", "nao"),
    ("PUT", "/meu-portal/v3/endereco/{id}", "Altera o endereco",
     "id", "body: idem POST", "Nao", "nao"),
    ("DELETE", "/meu-portal/v3/endereco/{id}", "Exclui o endereco", "id", "", "Nao", "nao"),
    ("POST", "/meu-portal/v3/telefone", "Cadastra telefone de contato",
     "", "body: tipo, documento, tipoTelefone, telefone, aplicativos", "Nao", "nao"),
    ("PUT", "/meu-portal/v3/telefone/{id}", "Altera o telefone",
     "id", "body: idem POST", "Nao", "nao"),
    ("DELETE", "/meu-portal/v3/telefone/{id}", "Exclui o telefone", "id", "", "Nao", "nao"),
    ("GET", "/localize/v3/report/usage", "Consultas feitas no periodo",
     "", "opc: status (TODOS/LOC/NLOC/ERRO), startDate, endDate, numPage, numPageSize",
     "Nao", "nao"),
    ("GET", "/localize/v3/report/usage/export", "O mesmo em CSV (URL assinada do S3)",
     "", "opc: status, startDate, endDate", "Nao", "nao"),
    ("GET", "/ultimas-consultas/v3", "Ultimas 30 consultas (20 de hoje + 10 anteriores)",
     "produto", "", "Nao", "nao"),
]

GRUPOS = {1: "Consultas principais — gastam consulta",
          6: "Complementos — exigem o protocolo de uma consulta anterior",
          10: "Feedback de telefone — nao gastam consulta",
          14: "Meu Portal — dados que voce mesma cadastra",
          26: "Relatorios — nao gastam consulta"}


def cabecalho(canvas, doc):
    canvas.saveState()
    canvas.setFillColor(NAVY)
    canvas.rect(0, doc.pagesize[1] - 12 * mm, doc.pagesize[0], 12 * mm, stroke=0, fill=1)
    canvas.setFillColor(colors.white)
    canvas.setFont("Helvetica-Bold", 9)
    canvas.drawString(14 * mm, doc.pagesize[1] - 8 * mm, "CapiBLU · API Localize V3 da Assertiva")
    canvas.setFont("Helvetica", 8)
    canvas.drawRightString(doc.pagesize[0] - 14 * mm, doc.pagesize[1] - 8 * mm,
                           f"pagina {doc.page}")
    canvas.setFillColor(GREY)
    canvas.setFont("Helvetica", 7)
    canvas.drawString(14 * mm, 8 * mm,
                      "Fonte: swagger oficial em integracao.assertivasolucoes.com.br/v3/swagger/localize/swagger.json")
    canvas.drawRightString(doc.pagesize[0] - 14 * mm, 8 * mm, "base: https://api.assertivasolucoes.com.br")
    canvas.restoreState()


def build():
    os.makedirs("exports", exist_ok=True)
    doc = SimpleDocTemplate(
        OUT, pagesize=landscape(A4),
        leftMargin=13 * mm, rightMargin=13 * mm,
        topMargin=17 * mm, bottomMargin=13 * mm,
        title="API Localize V3 da Assertiva — 28 endpoints",
        author="CapiBLU",
    )

    flow = [
        Paragraph("Os 28 endpoints da API Localize V3", h1),
        Paragraph(
            "Levantamento feito a partir do swagger oficial da Assertiva. A coluna "
            "\"gasta consulta\" foi conferida no relatorio de uso da propria Assertiva "
            "(/localize/v3/report/usage), que e o que ela conta para faturar — nao e estimativa.",
            sub),
        HRFlowable(width="100%", color=LINE, spaceAfter=8),
    ]

    dados = [[Paragraph("#", cellh), Paragraph("Metodo", cellh), Paragraph("Rota", cellh),
              Paragraph("O que faz", cellh), Paragraph("Parametros", cellh),
              Paragraph("Gasta consulta?", cellh), Paragraph("CapiBLU", cellh)]]

    estilos = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 3),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 3),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]

    linha_atual = 1
    for i, (metodo, rota, oque, obrig, opc, gasta, tem) in enumerate(LINHAS, start=1):
        if i in GRUPOS:
            dados.append([Paragraph(GRUPOS[i], ParagraphStyle(
                "g", fontName="Helvetica-Bold", fontSize=8, leading=11, textColor=TERRACOTA)),
                "", "", "", "", "", ""])
            estilos += [("SPAN", (0, linha_atual), (-1, linha_atual)),
                        ("BACKGROUND", (0, linha_atual), (-1, linha_atual), PAPEL)]
            linha_atual += 1

        partes = []
        if obrig:
            partes.append(f"<b>{obrig}</b>")
        if opc:
            partes.append(opc)
        params = "<br/>".join(partes) if partes else "—"

        cor_metodo = {"GET": BLUE, "POST": GREEN, "PUT": TERRACOTA,
                      "DELETE": colors.HexColor("#9A3324")}[metodo]
        dados.append([
            Paragraph(str(i), cell),
            Paragraph(f'<font color="#{cor_metodo.hexval()[2:]}"><b>{metodo}</b></font>', cell),
            Paragraph(rota, mono),
            Paragraph(oque, cell),
            Paragraph(params, par),
            Paragraph(gasta, cell),
            Paragraph("SIM" if tem == "sim" else "—", ctr),
        ])
        if tem == "sim":
            estilos.append(("TEXTCOLOR", (6, linha_atual), (6, linha_atual), GREEN))
            estilos.append(("BACKGROUND", (6, linha_atual), (6, linha_atual),
                            colors.HexColor("#EAF1EC")))
        elif linha_atual % 2 == 0:
            estilos.append(("BACKGROUND", (0, linha_atual), (-1, linha_atual), ZEBRA))
        linha_atual += 1

    larguras = [8 * mm, 15 * mm, 62 * mm, 58 * mm, 84 * mm, 30 * mm, 16 * mm]
    tabela = Table(dados, colWidths=larguras, repeatRows=1)
    tabela.setStyle(TableStyle(estilos))
    flow.append(tabela)

    flow += [
        Spacer(1, 8),
        Paragraph("(1) Inferencia, nao medicao: seguem o mesmo padrao do possiveis-decisores "
                  "(exigem protocolo de uma consulta anterior), entao devem aparecer como subitem. "
                  "Nao foram testados — testar custaria consulta.", note),
        Paragraph("(2) Medido: apareceu como item proprio no relatorio de uso, com a etiqueta "
                  "\"Conexoes API\".", note),
        Spacer(1, 6),
        Paragraph("<b>Autenticacao</b> (swagger separado): POST /oauth2/v3/token — "
                  "Basic base64(client_id:client_secret), grant_type=client_credentials. "
                  "Implementado no CapiBLU.", foot),
        Paragraph("<b>Placar:</b> 8 de 28 implementadas (7 da Localize + o token). "
                  "Cobranca: a unidade e o documento consultado — 602 decisores num CNPJ "
                  "contam como 1 consulta, e reconsulta do mesmo documento nao conta de novo.", foot),
    ]

    doc.build(flow, onFirstPage=cabecalho, onLaterPages=cabecalho)
    print("PDF gerado:", OUT, os.path.getsize(OUT), "bytes")


if __name__ == "__main__":
    build()
