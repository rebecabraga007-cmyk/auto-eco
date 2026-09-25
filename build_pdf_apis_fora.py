# -*- coding: utf-8 -*-
"""Gera o PDF da tabela de funcoes das APIs fora do ar no CapiBLU.

A tabela NAO e copiada aqui: e lida de lupa-empresas/APIS_FORA_DO_AR.md (secao
"Tabela de funcoes"), para o PDF e o documento nunca divergirem. Mudou o .md,
roda de novo.

    python build_pdf_apis_fora.py
"""
import os
import re

from reportlab.lib import colors
from reportlab.lib.pagesizes import A3, landscape
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.pdfbase import pdfmetrics
from reportlab.pdfbase.ttfonts import TTFont
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

MD = os.path.join("lupa-empresas", "APIS_FORA_DO_AR.md")
OUT = os.path.join("exports", "apis-fora-do-ar-tabela.pdf")

# --- paleta (mesma familia dos outros PDFs do projeto) ---
NAVY      = colors.HexColor("#0F2E4A")
BLUE_SOFT = colors.HexColor("#EAF0F5")
GREEN     = colors.HexColor("#2F6B4F")
GREEN_SFT = colors.HexColor("#EAF1EC")
RED       = colors.HexColor("#9A3324")
RED_SFT   = colors.HexColor("#F7EAE7")
GREY      = colors.HexColor("#55595F")
GREY_SFT  = colors.HexColor("#EDEDED")
LINE      = colors.HexColor("#DBD4C6")
HEAD_BG   = colors.HexColor("#F0ECE3")
WHITE     = colors.white

_FONTS = r"C:\Windows\Fonts"
pdfmetrics.registerFont(TTFont("Arial", os.path.join(_FONTS, "arial.ttf")))
pdfmetrics.registerFont(TTFont("Arial-Bold", os.path.join(_FONTS, "arialbd.ttf")))
pdfmetrics.registerFont(TTFont("Consolas", os.path.join(_FONTS, "consola.ttf")))
pdfmetrics.registerFontFamily("Arial", normal="Arial", bold="Arial-Bold",
                              italic="Arial", boldItalic="Arial-Bold")

S_TITULO = ParagraphStyle("t", fontName="Arial-Bold", fontSize=20, textColor=NAVY, leading=24)
S_SUB = ParagraphStyle("s", fontName="Arial", fontSize=10, textColor=GREY, leading=14)
S_CEL = ParagraphStyle("c", fontName="Arial", fontSize=8, leading=10.2, textColor=colors.black)
S_CAB = ParagraphStyle("h", parent=S_CEL, fontName="Arial-Bold", textColor=WHITE)
S_NOTA = ParagraphStyle("n", parent=S_SUB, fontSize=8.5, leading=12)


def _tabela_do_md() -> tuple[list[str], list[list[str]], str]:
    """Cabecalho, linhas e o paragrafo introdutorio da secao 'Tabela de funcoes'."""
    with open(MD, encoding="utf-8") as f:
        texto = f.read()
    ini = texto.index("## Tabela de funções")
    fim = texto.index("\n## ", ini + 5)
    secao = texto[ini:fim]
    linhas = [l for l in secao.splitlines() if l.startswith("|")]
    celulas = [[c.strip() for c in l.strip().strip("|").split(" | ")] for l in linhas]
    intro = " ".join(l for l in secao.splitlines()[1:] if l and not l.startswith("|"))
    return celulas[0], [c for c in celulas[2:]], intro


def _md(s: str) -> str:
    """Markdown inline -> marcacao do Paragraph do reportlab."""
    s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    s = re.sub(r"`([^`]+)`", r'<font name="Consolas" size="7.3">\1</font>', s)
    s = re.sub(r"\*\*([^*]+)\*\*", r"<b>\1</b>", s)
    s = re.sub(r"\[([^\]]+)\]\([^)]+\)", r"\1", s)
    return s


def _situacao(s: str) -> tuple[str, colors.Color, colors.Color]:
    """Os emojis do .md nao existem na Arial: vira texto + cor de fundo."""
    if "⚫" in s:
        return s.replace("⚫", "").strip(), GREY, GREY_SFT
    if "✅" in s:
        return s.replace("✅", "").strip(), GREEN, GREEN_SFT
    return s.replace("🔴", "").strip(), RED, RED_SFT


def main():
    cab, linhas, intro = _tabela_do_md()
    idx_sit = cab.index("Situação")

    # larguras (mm) somando a area util do A3 paisagem com margens de 12 mm
    larg_mm = [8, 34, 50, 22, 58, 58, 55, 38, 45]
    util = landscape(A3)[0] / mm - 24
    larg = [w * util / sum(larg_mm) * mm for w in larg_mm]

    dados = [[Paragraph(_md(c), S_CAB) for c in cab]]
    estilo = [
        ("BACKGROUND", (0, 0), (-1, 0), NAVY),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("TOPPADDING", (0, 0), (-1, -1), 4),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 5),
        ("LEFTPADDING", (0, 0), (-1, -1), 4),
        ("RIGHTPADDING", (0, 0), (-1, -1), 4),
    ]
    for i, lin in enumerate(linhas, start=1):
        texto_sit, cor, fundo = _situacao(lin[idx_sit])
        cel = []
        for j, c in enumerate(lin):
            if j == idx_sit:
                cel.append(Paragraph('<font color="%s"><b>%s</b></font>'
                                     % (cor.hexval().replace("0x", "#"), _md(texto_sit)), S_CEL))
            else:
                cel.append(Paragraph(_md(c), S_CEL))
        dados.append(cel)
        estilo.append(("BACKGROUND", (idx_sit, i), (idx_sit, i), fundo))
        if i % 2 == 0:
            estilo.append(("BACKGROUND", (0, i), (idx_sit - 1, i), BLUE_SOFT))
            estilo.append(("BACKGROUND", (idx_sit + 1, i), (-1, i), BLUE_SOFT))
    # coluna "Alternativa já integrada" em verde: e a resposta que o leitor procura
    idx_alt = cab.index("Alternativa já integrada")
    estilo.append(("BACKGROUND", (idx_alt, 1), (idx_alt, -1), GREEN_SFT))
    estilo.append(("LINEBEFORE", (idx_alt, 0), (idx_alt, -1), 1.2, GREEN))

    tabela = Table(dados, colWidths=larg, repeatRows=1)
    tabela.setStyle(TableStyle(estilo))

    def rodape(canvas, doc):
        canvas.saveState()
        canvas.setFont("Arial", 7.5)
        canvas.setFillColor(GREY)
        canvas.drawString(12 * mm, 7 * mm,
                          "CapiBLU · APIs fora do ar · medido em 25/09/2026 no servidor de produção")
        canvas.drawRightString(landscape(A3)[0] - 12 * mm, 7 * mm, "página %d" % doc.page)
        canvas.restoreState()

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    doc = SimpleDocTemplate(OUT, pagesize=landscape(A3), leftMargin=12 * mm,
                            rightMargin=12 * mm, topMargin=12 * mm, bottomMargin=14 * mm,
                            title="APIs fora do ar no CapiBLU — tabela de funções",
                            author="Blu Sales Group")
    historia = [
        Paragraph("APIs fora do ar no CapiBLU — tabela de funções", S_TITULO),
        Spacer(1, 3 * mm),
        Paragraph("Medido em 25/09/2026, de dentro do servidor de produção (Hetzner), com as "
                  "chaves de produção. Fora do ar: <b>WorkAPI</b> (523, servidor deles caiu), "
                  "<b>FDX/RAIS</b> (token expirado), <b>DonoDoZap</b> (CAPTCHA) e a raspagem do "
                  "<b>Google</b>. A <b>Bright Data</b> teve a conta suspensa entre 17/09 e 25/09 "
                  "e foi <b>reativada em 25/09</b> (linhas 7 a 9, em verde, testadas de ponta a "
                  "ponta depois da reativação).", S_SUB),
        Spacer(1, 2 * mm),
        Paragraph(_md(intro), S_NOTA),
        Spacer(1, 5 * mm),
        tabela,
        Spacer(1, 4 * mm),
        Paragraph("Detalhe de cada endpoint, rotas afetadas, investigação da Bright Data e "
                  "comandos para medir de novo: <font name=\"Consolas\">lupa-empresas/"
                  "APIS_FORA_DO_AR.md</font>.", S_NOTA),
    ]
    doc.build(historia, onFirstPage=rodape, onLaterPages=rodape)
    print(OUT)


if __name__ == "__main__":
    main()
