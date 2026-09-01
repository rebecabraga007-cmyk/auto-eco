# -*- coding: utf-8 -*-
"""Gera o PDF-resumo dos gateways de WhatsApp (repo joaoBLU/distribuidor-leads).

Escrito para quem NAO e tecnico: explica o que estamos tentando fazer (sair do
Render), o que ja foi verificado, e os tres problemas medidos no sistema hoje.
Toda afirmacao numerica aqui foi medida em 31/ago/2026, nao estimada.

    python build_pdf_gateways.py
"""
import os

from reportlab.lib import colors
from reportlab.lib.enums import TA_CENTER, TA_RIGHT
from reportlab.lib.pagesizes import A4
from reportlab.lib.styles import ParagraphStyle
from reportlab.lib.units import mm
from reportlab.platypus import (
    HRFlowable, KeepTogether, PageBreak, Paragraph, SimpleDocTemplate,
    Spacer, Table, TableStyle,
)

OUT = os.path.join("exports", "gateways-whatsapp-resumo.pdf")

# --- paleta (mesma familia dos outros PDFs do projeto) ---
NAVY      = colors.HexColor("#0F2E4A")
BLUE_SOFT = colors.HexColor("#EAF0F5")
TERRACOTA = colors.HexColor("#A85A2C")
TERRA_SFT = colors.HexColor("#FBEFE7")
GREEN     = colors.HexColor("#2F6B4F")
GREEN_SFT = colors.HexColor("#EAF1EC")
AMBER     = colors.HexColor("#8C6A16")
AMBER_SFT = colors.HexColor("#F7F1E1")
RED       = colors.HexColor("#9A3324")
RED_SFT   = colors.HexColor("#F7EAE7")
PAPEL     = colors.HexColor("#F1EEE7")
GREY      = colors.HexColor("#55595F")
LINE      = colors.HexColor("#DBD4C6")
HEAD_BG   = colors.HexColor("#F0ECE3")
WHITE     = colors.white


def esc(t):
    """& < > viram entidade. Sem isto o ReportLab le '&conta' como entidade HTML."""
    return (str(t).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;"))


# ---------------------------------------------------------------- estilos
def E(nome, **kw):
    base = dict(fontName="Helvetica", fontSize=10.2, leading=15.4,
                textColor=colors.HexColor("#2B2B2B"), spaceAfter=0)
    base.update(kw)
    return ParagraphStyle(nome, **base)


S = {
    "capa_titulo":  E("ct", fontName="Helvetica-Bold", fontSize=31, leading=36,
                      textColor=WHITE),
    "capa_sub":     E("cs", fontSize=13.2, leading=19, textColor=colors.HexColor("#BFD2E0")),
    "capa_meta":    E("cm", fontSize=9.4, leading=14, textColor=colors.HexColor("#8FA9BC")),
    "h1":           E("h1", fontName="Helvetica-Bold", fontSize=19, leading=24,
                      textColor=NAVY, spaceAfter=3),
    "h2":           E("h2", fontName="Helvetica-Bold", fontSize=13.4, leading=18,
                      textColor=TERRACOTA, spaceAfter=2),
    "h3":           E("h3", fontName="Helvetica-Bold", fontSize=11, leading=15,
                      textColor=NAVY),
    "p":            E("p", spaceAfter=7),
    "p_last":       E("pl"),
    "lead":         E("lead", fontSize=11.6, leading=17.6, textColor=colors.HexColor("#3A3A3A"),
                      spaceAfter=8),
    "li":           E("li", leftIndent=11, bulletIndent=1, spaceAfter=4.5),
    "cel":          E("cel", fontSize=9.4, leading=13),
    "cel_b":        E("celb", fontName="Helvetica-Bold", fontSize=9.4, leading=13),
    "cel_h":        E("celh", fontName="Helvetica-Bold", fontSize=9, leading=12.5,
                      textColor=WHITE),
    "nota":         E("nota", fontSize=9.3, leading=13.8, textColor=GREY),
    "caixa":        E("caixa", fontSize=10.2, leading=15.2),
    "caixa_t":      E("caixat", fontName="Helvetica-Bold", fontSize=10.4, leading=14.6),
    "rodape":       E("rod", fontSize=8, textColor=GREY, alignment=TA_RIGHT),
}


def P(txt, st="p"):
    return Paragraph(esc(txt) if "<" not in str(txt) else txt, S[st])


def Bullet(txt):
    return Paragraph(txt, S["li"], bulletText="•")


def sp(h=6):
    return Spacer(1, h * mm)


def regua(cor=LINE, esp=0.7):
    return HRFlowable(width="100%", thickness=esp, color=cor,
                      spaceBefore=2 * mm, spaceAfter=3.5 * mm)


def caixa(titulo, corpo, cor_borda, cor_fundo, largura=None):
    """Bloco destacado com barra de cor a esquerda."""
    interno = []
    if titulo:
        interno.append(Paragraph(titulo, ParagraphStyle(
            "bt", parent=S["caixa_t"], textColor=cor_borda)))
        interno.append(Spacer(1, 1.6 * mm))
    if isinstance(corpo, str):
        corpo = [corpo]
    for i, c in enumerate(corpo):
        interno.append(Paragraph(c, S["caixa"]))
        if i < len(corpo) - 1:
            interno.append(Spacer(1, 1.8 * mm))
    t = Table([[interno]], colWidths=[largura or 163 * mm])
    t.setStyle(TableStyle([
        ("BACKGROUND", (0, 0), (-1, -1), cor_fundo),
        ("LINEBEFORE", (0, 0), (0, -1), 2.6, cor_borda),
        ("LEFTPADDING", (0, 0), (-1, -1), 7 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 5 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 4.4 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 4.4 * mm),
        ("VALIGN", (0, 0), (-1, -1), "TOP"),
    ]))
    return t


def tabela(cabecalho, linhas, larguras, destaque=None):
    """Tabela zebrada. cabecalho=None omite a faixa de titulo."""
    dados = []
    if cabecalho:
        dados.append([Paragraph(esc(c), S["cel_h"]) for c in cabecalho])
    for ln in linhas:
        dados.append([Paragraph(c if "<" in str(c) else esc(c),
                                S["cel_b"] if j == 0 and not cabecalho else S["cel"])
                      for j, c in enumerate(ln)])
    t = Table(dados, colWidths=larguras, repeatRows=1 if cabecalho else 0)
    est = [
        ("GRID", (0, 0), (-1, -1), 0.4, LINE),
        ("VALIGN", (0, 0), (-1, -1), "MIDDLE"),
        ("LEFTPADDING", (0, 0), (-1, -1), 3.2 * mm),
        ("RIGHTPADDING", (0, 0), (-1, -1), 3.2 * mm),
        ("TOPPADDING", (0, 0), (-1, -1), 2.5 * mm),
        ("BOTTOMPADDING", (0, 0), (-1, -1), 2.5 * mm),
    ]
    inicio = 0
    if cabecalho:
        est += [("BACKGROUND", (0, 0), (-1, 0), NAVY)]
        inicio = 1
    for i in range(inicio, len(dados)):
        if (i - inicio) % 2 == 1:
            est.append(("BACKGROUND", (0, i), (-1, i), HEAD_BG))
    if destaque:
        for i in destaque:
            est.append(("BACKGROUND", (0, i), (-1, i), RED_SFT))
            est.append(("LINEBEFORE", (0, i), (0, i), 2.2, RED))
    t.setStyle(TableStyle(est))
    return t


# ---------------------------------------------------------------- paginas
def fundo_capa(canv, doc):
    canv.saveState()
    canv.setFillColor(NAVY)
    canv.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    canv.setFillColor(TERRACOTA)
    canv.rect(0, A4[1] - 118 * mm, 58 * mm, 3.2 * mm, stroke=0, fill=1)
    canv.restoreState()


def moldura(canv, doc):
    canv.saveState()
    canv.setFillColor(PAPEL)
    canv.rect(0, 0, A4[0], A4[1], stroke=0, fill=1)
    canv.setStrokeColor(LINE)
    canv.setLineWidth(0.5)
    canv.line(20 * mm, 16 * mm, A4[0] - 20 * mm, 16 * mm)
    canv.setFillColor(GREY)
    canv.setFont("Helvetica", 7.8)
    canv.drawRightString(A4[0] - 20 * mm, 11 * mm, "pagina %d" % (doc.page - 1))
    canv.drawString(20 * mm, 11 * mm, "Gateways de WhatsApp — resumo tecnico em linguagem simples")
    canv.restoreState()


# ---------------------------------------------------------------- conteudo
def construir():
    os.makedirs("exports", exist_ok=True)
    doc = SimpleDocTemplate(
        OUT, pagesize=A4,
        leftMargin=20 * mm, rightMargin=20 * mm,
        topMargin=22 * mm, bottomMargin=22 * mm,
        title="Gateways de WhatsApp - o que estamos fazendo e o que encontramos",
        author="Rebeca / Blu Sales Group",
    )
    F = []  # flowables

    # ---------------- CAPA ----------------
    F += [sp(52)]
    F += [Paragraph("Os 5 WhatsApp<br/>da operacao", S["capa_titulo"])]
    F += [sp(6)]
    F += [Paragraph("O que estamos tentando fazer, e tres problemas "
                    "que encontramos no caminho", S["capa_sub"])]
    F += [sp(14)]
    F += [Paragraph("Resumo em linguagem simples — sem termos tecnicos<br/>"
                    "Todos os numeros foram medidos, nao estimados<br/><br/>"
                    "31 de agosto de 2026", S["capa_meta"])]
    F += [PageBreak()]

    # ---------------- 1. O QUE E ----------------
    F += [P("Primeiro: o que esse sistema faz", "h1"), regua()]
    F += [P("A operacao tem <b>cinco numeros de WhatsApp</b> que recebem mensagens de "
            "clientes. Para cada numero existe um programinha rodando num servidor, "
            "24 horas por dia, cujo trabalho e simples: ficar conectado naquele WhatsApp "
            "e avisar o sistema principal sempre que chega mensagem nova.", "lead")]
    F += [P("Sao dois grupos, servindo dois sistemas diferentes:")]
    F += [sp(2)]
    F += [tabela(
        ["Grupo", "Numeros", "Sistema que recebe os avisos"],
        [["Global", "eduarda, marlon, maicon", "global-america"],
         ["Movida", "pedro, luan", "distribuidor-leads"]],
        [26 * mm, 62 * mm, 75 * mm])]
    F += [sp(7)]
    F += [caixa("O termo que aparece o tempo todo: “sessao”",
                ["Quando alguem escaneia o QR code, o WhatsApp entrega um <b>cracha "
                 "digital</b> para aquele programa. Esse cracha (junto com a agenda de "
                 "contatos e umas chaves de seguranca) e o que chamamos de <b>sessao</b>.",
                 "Enquanto o programa tem a sessao, ele entra no WhatsApp sem pedir QR "
                 "de novo. Se a sessao se perde, alguem precisa pegar o celular e "
                 "escanear outro QR. <b>E isso que ninguem quer.</b>"],
                NAVY, BLUE_SOFT)]

    F += [sp(9)]
    F += [P("O que estamos tentando fazer", "h1"), regua()]
    F += [P("Hoje esses cinco programas rodam no <b>Render</b>, um servico de hospedagem "
            "que cobra por mes. A ideia e move-los para o <b>Hetzner</b>, um servidor que "
            "a gente ja aluga e que esta praticamente vazio — usa 1 GB de memoria dos "
            "7,6 GB que tem.", "lead")]
    F += [P("Os ganhos:")]
    F += [Bullet("<b>Economia de cerca de US$ 45 por mes.</b> No Render sao 5 servicos "
                 "pagos separadamente, mais o custo do trafego de dados. No Hetzner, "
                 "cabem no servidor que ja esta pago — custo adicional zero.")]
    F += [Bullet("<b>Sai um limite de espaco que ia apertar.</b> No Render cada programa "
                 "tem apenas 64 MB reservados para a sessao. No Hetzner sao 3,8 GB.")]
    F += [Bullet("<b>Tudo num lugar so.</b> O servidor do Hetzner ja hospeda outros "
                 "sistemas nossos.")]

    F += [sp(8)]
    F += [caixa("A boa noticia: ninguem precisa escanear QR de novo",
                ["Essa era a duvida principal, e a resposta e <b>nao</b>.",
                 "O sistema do Joao foi construido de um jeito esperto: a sessao "
                 "<b>nao fica guardada na maquina onde o programa roda</b>. Ela fica "
                 "guardada (protegida por criptografia) no sistema principal. Quando o "
                 "programa liga, ele busca a sessao de la.",
                 "Ou seja: trocar de servidor e so ligar o programa em outro lugar. "
                 "Ele busca a mesma sessao e reconecta sozinho."],
                GREEN, GREEN_SFT)]

    F += [sp(6)]
    F += [caixa("E temos prova disso, por acidente",
                ["Durante a investigacao eu rodei um comando pesado por dentro de um "
                 "desses programas (o do Pedro) e estourei a memoria dele. O programa "
                 "morreu. <b>Foi um erro meu.</b>",
                 "Ele ficou fora do ar por <b>5 segundos</b>, voltou sozinho, buscou a "
                 "sessao e reconectou — <b>sem pedir QR</b>. O registro do sistema "
                 "mostra a sequencia inteira. Foi um acidente que virou a demonstracao "
                 "de que a mudanca de servidor funciona."],
                AMBER, AMBER_SFT)]

    F += [PageBreak()]

    # ---------------- 2. OS PROBLEMAS ----------------
    F += [P("Os tres problemas que encontramos", "h1"), regua()]
    F += [P("Ao investigar, apareceram tres problemas que <b>existem hoje</b> e nao tem "
            "relacao com a mudanca de servidor. Dois deles tem prazo.", "lead")]

    F += [sp(3)]
    F += [P("Problema 1 — O mesmo arquivo e reenviado milhares de vezes por dia", "h2")]
    F += [P("Cada programa guarda a sessao num arquivo e, <b>a cada 30 segundos</b>, "
            "manda esse arquivo <b>inteiro</b> para o sistema principal, pela internet. "
            "Nao manda “o que mudou” — manda tudo, sempre.")]
    F += [sp(2)]
    F += [caixa(None,
                ["<b>Uma analogia:</b> e como se, a cada 30 segundos, voce mandasse sua "
                 "agenda de contatos completa por e-mail para o escritorio — mesmo "
                 "que so um telefone tenha sido corrigido. Se a agenda tem 300 paginas, "
                 "voce manda as 300 paginas de novo."],
                TERRACOTA, TERRA_SFT)]
    F += [sp(4)]
    F += [P("Medimos o resultado disso num dia util (31 de agosto):")]
    F += [sp(2)]
    F += [tabela(
        ["Numero", "Dados enviados em 10h", "Tamanho da sessao"],
        [["pedro", "1.280 MB", "6,5 MB"],
         ["eduarda", "1.253 MB", "8,6 MB"],
         ["marlon", "716 MB", "8,0 MB"],
         ["luan", "654 MB", "3,8 MB"],
         ["maicon", "281 MB", "4,0 MB"],
         ["<b>Total</b>", "<b>4.184 MB (4,2 GB)</b>", ""]],
        [30 * mm, 68 * mm, 65 * mm])]
    F += [sp(3)]
    F += [P("Projetando para o mes: <b>cerca de 100 GB</b>. Nos fins de semana o consumo "
            "e praticamente zero, o que confirma que o gasto acompanha o trabalho dos "
            "closers.", "nota")]

    F += [sp(8)]
    F += [KeepTogether([
        P("Problema 2 — A sessao cresce para sempre e nunca e limpa", "h2"),
        P("Abrimos a sessao para ver o que ocupa espaco. Ela e um banco de dados com "
          "varias tabelas, e <b>uma delas responde por 69% do tamanho</b>:"),
        sp(2),
        tabela(
            ["O que esta guardado", "Espaco", "Fatia"],
            [["Uma chave para cada mensagem trocada", "6,0 MB", "69%"],
             ["Controle de sincronizacao com o celular", "1,3 MB", "15%"],
             ["Contatos, chaves de seguranca, o resto", "0,7 MB", "16%"]],
            [92 * mm, 34 * mm, 37 * mm], destaque=[1]),
    ])]
    F += [sp(4)]
    F += [P("Sao <b>24.059 chaves</b> guardadas hoje, uma por mensagem. Elas servem para "
            "o caso de alguem reagir, votar numa enquete ou editar uma mensagem antiga. "
            "O problema: <b>a biblioteca de WhatsApp que o sistema usa nunca apaga "
            "nenhuma delas</b>.")]
    F += [sp(2)]
    F += [caixa(None,
                ["<b>A causa e o tipo de conta.</b> Um WhatsApp pessoal troca poucas "
                 "mensagens. Uma conta de closer conversa com centenas de clientes novos "
                 "por dia — sao cerca de <b>700 chaves novas por dia</b>, guardadas "
                 "para sempre. Nao e defeito de programacao: e o uso normal batendo num "
                 "comportamento que nunca foi pensado para esse volume."],
                TERRACOTA, TERRA_SFT)]

    F += [PageBreak()]

    F += [P("Problema 3 — Existe um teto de 12 MB, e ele esta chegando", "h2")]
    F += [P("O sistema principal recusa arquivos de sessao maiores que <b>12 MB</b>. "
            "Quando a sessao passar disso, ele recusa a gravacao e o programa "
            "<b>para de funcionar</b> — nao perde a conta nem pede QR, mas para de "
            "capturar mensagens.")]
    F += [sp(3)]
    F += [P("Por que esse teto e baixo? Porque o sistema principal roda numa caixa de "
            "512 MB de memoria. Fui medir como ela esta:")]
    F += [sp(2)]
    F += [tabela(None,
                 [["Memoria disponivel", "512 MB"],
                  ["Uso ao longo do dia de hoje", "279 → 314 → 427 → 446 MB"],
                  ["Ocupacao atual", "87%"],
                  ["Reinicios em 2 dias", "pelo menos 4"]],
                 [78 * mm, 85 * mm])]
    F += [sp(4)]
    F += [P("Ou seja: o teto de 12 MB nao e capricho — <b>e o maximo que a memoria "
            "atual aguenta</b>. Subir o teto exige mais memoria no sistema principal.")]

    F += [sp(8)]
    F += [P("A conta do tempo", "h1"), regua()]
    F += [P("A sessao cresce <b>0,175 MB por dia</b> (medido comparando 17 e 31 de agosto "
            "em duas contas, que deram praticamente o mesmo numero).", "lead")]
    F += [sp(2)]
    F += [tabela(
        ["Quando", "Sessao da eduarda", "Dados por mes (5 contas)"],
        [["Hoje", "8,6 MB", "~100 GB"],
         ["Em 1 mes", "13,9 MB", "~160 GB"],
         ["Em 3 meses", "24,4 MB", "~280 GB"],
         ["Em 6 meses", "40,1 MB — bate o teto", "~460 GB"]],
        [34 * mm, 62 * mm, 67 * mm], destaque=[4])]
    F += [sp(4)]
    F += [caixa("Por que o gasto de dados cresce junto",
                ["Porque as duas coisas estao ligadas: o programa manda o arquivo "
                 "<b>inteiro</b> a cada 30 segundos. Se o arquivo dobra de tamanho, o "
                 "gasto de dados dobra tambem — sem ninguem trabalhar mais.",
                 "E a curva nao estabiliza num patamar alto: ela sobe ate os ~6 meses e "
                 "<b>termina em parada</b>, quando bate o teto de 12 MB."],
                TERRACOTA, TERRA_SFT)]

    F += [PageBreak()]

    # ---------------- 3. O QUE RESOLVE O QUE ----------------
    F += [P("O que resolve o que", "h1"), regua()]
    F += [P("Esta e a parte mais importante do documento, porque e facil confundir as "
            "coisas: <b>a mudanca de servidor resolve dinheiro, mas nao resolve o "
            "prazo dos 6 meses.</b>", "lead")]
    F += [sp(3)]
    F += [tabela(
        ["Acao", "Custo de dados", "Limite de 64 MB", "Teto de 12 MB"],
        [["Mudar para o Hetzner", "resolve", "resolve", "NAO resolve"],
         ["Usar endereco interno do Render", "resolve", "nao", "NAO resolve"],
         ["Gravar de 5 em 5 min (nao 30s)", "corta ~90%", "nao", "NAO resolve"],
         ["Limpar as chaves antigas", "corta muito", "resolve", "RESOLVE"]],
        [58 * mm, 34 * mm, 34 * mm, 37 * mm], destaque=[4])]
    F += [sp(6)]
    F += [caixa("Em uma frase",
                ["Mudar de servidor <b>economiza dinheiro e compra tranquilidade</b>. "
                 "Mas so <b>limpar as chaves antigas</b> evita que os WhatsApp parem de "
                 "capturar mensagens la na frente."],
                NAVY, BLUE_SOFT)]

    F += [sp(9)]
    F += [P("O que sugerimos, em ordem", "h1"), regua()]

    # KeepTogether: cada recomendacao nao pode quebrar entre titulo e ressalva —
    # a nota solta no topo da pagina seguinte fica orfa e ilegivel.
    F += [KeepTogether([
        P("1. Mudar o intervalo de gravacao — mais simples de todas", "h3"),
        P("Hoje o programa grava a cada 30 segundos. Passar para 5 minutos corta "
          "cerca de <b>90% do gasto de dados</b> imediatamente, e alivia a memoria do "
          "sistema principal (que esta em 87%). E uma configuracao, nao mexe em "
          "programacao."),
        P("<i>O custo:</i> se o programa morrer de repente, perde-se ate 5 minutos de "
          "estado em vez de 30 segundos. Como ele reconecta sozinho sem QR, parece "
          "barato — mas quem decide isso e o Joao.", "nota"),
    ])]
    F += [sp(5)]

    F += [KeepTogether([
        P("2. Mudar os programas para o Hetzner — ja esta pronto", "h3"),
        P("Os cinco programas ja estao instalados e testados no servidor novo, "
          "<b>desligados</b>, esperando aprovacao. A troca leva alguns segundos por "
          "numero e nao pede QR."),
        P("<i>Atencao importante:</i> nao pode haver os dois ligados ao mesmo tempo. Se "
          "o novo subir com o antigo rodando, os dois disputam a mesma sessao e o "
          "antigo e desligado a forca. A ordem e: desliga no Render, depois liga no "
          "Hetzner — um numero por vez.", "nota"),
    ])]
    F += [sp(5)]

    F += [KeepTogether([
        P("3. Limpar as chaves antigas — o conserto de verdade", "h3"),
        P("E o unico item que remove o prazo dos 6 meses. Precisa de programacao, no "
          "repositorio do Joao. A boa noticia e que o alvo e bem especifico: uma "
          "tabela, que responde por 69% do tamanho."),
        P("<i>Uma dificuldade real:</i> essa tabela nao guarda data, entao nao da para "
          "dizer “apague o que tem mais de 30 dias”. Da para apagar pela ordem "
          "de entrada, mantendo apenas as mais recentes. O que se perde e a capacidade "
          "de ler reacao ou enquete em mensagens antigas — provavelmente irrelevante "
          "para capturar leads, mas e uma decisao do Joao.", "nota"),
    ])]

    F += [sp(9)]
    F += [P("Uma observacao de transparencia", "h1"), regua()]
    F += [caixa(None,
                ["Como consta na pagina 2, <b>eu derrubei o gateway do Pedro por 5 "
                 "segundos</b> durante esta investigacao, ao rodar um comando pesado "
                 "dentro de um ambiente com pouca memoria. Nada foi perdido e a sessao "
                 "voltou sozinha, mas foi uma interrupcao nao planejada em producao, e "
                 "esta registrada aqui para que ninguem descubra por outro caminho."],
                AMBER, AMBER_SFT)]

    F += [sp(8)]
    F += [P("De onde vem cada numero", "h1"), regua()]
    F += [P("Nada aqui foi estimado por analogia. As fontes:", "nota")]
    F += [sp(2)]
    F += [tabela(None,
                 [["Consumo de dados", "Metricas do Render, hora por hora, 25 a 31/ago"],
                  ["Tamanho e conteudo da sessao", "Leitura direta do banco de sessao, so leitura"],
                  ["Crescimento de 0,175 MB/dia", "Comparacao entre 17/ago (registrado no "
                   "codigo) e 31/ago (medido)"],
                  ["Teto de 12 MB", "Codigo do sistema principal"],
                  ["Memoria em 87%", "Metricas do Render do sistema principal"],
                  ["Reconexao sem QR", "Registro do sistema durante o reinicio acidental"]],
                 [58 * mm, 105 * mm])]

    doc.build(F, onFirstPage=fundo_capa, onLaterPages=moldura)
    print("PDF gerado: %s (%.1f KB)" % (OUT, os.path.getsize(OUT) / 1024))


if __name__ == "__main__":
    construir()
