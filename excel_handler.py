"""
excel_handler.py
----------------
Le a planilha exportada dos Favoritos do Mais Obras e gera uma saida limpa.

O arquivo original do Mais Obras costuma vir assim:
  Linha 1: titulo "Meus Favoritos"
  Linhas 2-3: vazias
  Linha 4: cabecalho real
  Linha 5+: dados

A planilha enriquecida gerada por este modulo sempre sai assim:
  Linha 1: cabecalho
  Linha 2+: dados
"""

import io
import logging
import re
import unicodedata
from dataclasses import dataclass

import openpyxl
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

logger = logging.getLogger(__name__)

HEADER_ROW = 4
DATA_START_ROW = 5

COL_PROFISSIONAL = 0
COL_PROPRIETARIO = 1
COL_ENDERECO = 5
COL_CIDADE = 8
COL_UF = 9

COLUNAS_NOVAS = [
    "Telefone Arquiteto 1",
    "Telefone Arquiteto 2",
    "Email Arquiteto",
    "Telefone Proprietario 1",
    "Telefone Proprietario 2",
    "Email Proprietario",
    "Status",
]

COR_HEADER = "56181B"
COR_HEADER_NOVO = "CBB068"
COR_HEADER_FONT = "FFF7E2"
COR_HEADER_NOVO_FONT = "56181B"
COR_ZEBRA = "FBF7EF"
COR_BORDA = "E2D7C8"


@dataclass
class ObraRow:
    """Representa uma linha do Excel com dados suficientes para buscar no Mais Obras."""

    row_index: int
    nome_profissional: str
    nome_proprietario: str
    cidade: str
    uf: str
    endereco: str
    chave: str = ""

    def __post_init__(self):
        self.chave = _chave(self.nome_profissional, self.nome_proprietario, self.cidade)


def _normalizar(texto: str) -> str:
    if not texto:
        return ""
    txt = unicodedata.normalize("NFD", str(texto))
    txt = "".join(c for c in txt if unicodedata.category(c) != "Mn")
    return txt.strip().upper()


def _chave(profissional: str, proprietario: str, cidade: str) -> str:
    return f"{_normalizar(profissional)}|{_normalizar(proprietario)}|{_normalizar(cidade)}"


def carregar_excel(conteudo: bytes) -> tuple[openpyxl.Workbook, list[ObraRow]]:
    """Carrega o Excel exportado dos favoritos e extrai as obras."""
    wb = openpyxl.load_workbook(io.BytesIO(conteudo))
    ws = wb.active

    header_row = list(ws.iter_rows(min_row=HEADER_ROW, max_row=HEADER_ROW, values_only=True))[0]
    if not any(h and "profissional" in str(h).lower() for h in header_row):
        raise ValueError(
            "Formato de arquivo nao reconhecido. "
            "Esperava 'Nome do profissional' na linha 4. "
            "Verifique se o arquivo foi exportado corretamente dos Favoritos do Mais Obras."
        )

    obras = []
    for row_idx, row in enumerate(
        ws.iter_rows(min_row=DATA_START_ROW, values_only=True), start=DATA_START_ROW
    ):
        profissional = str(row[COL_PROFISSIONAL] or "").strip()
        proprietario = str(row[COL_PROPRIETARIO] or "").strip()
        cidade = str(row[COL_CIDADE] or "").strip()
        uf = str(row[COL_UF] or "").strip()
        endereco = str(row[COL_ENDERECO] or "").strip()

        if not profissional and not proprietario:
            continue

        obras.append(
            ObraRow(
                row_index=row_idx,
                nome_profissional=profissional,
                nome_proprietario=proprietario,
                cidade=cidade,
                uf=uf,
                endereco=endereco,
            )
        )

    logger.info("Excel carregado: %s obras encontradas.", len(obras))
    return wb, obras


def enriquecer_excel(
    wb: openpyxl.Workbook,
    obras: list[ObraRow],
    contatos: list,
) -> bytes:
    """
    Gera uma planilha limpa para download.
    A primeira linha da saida sempre contem o cabecalho, seguida pelas linhas de dados.
    """
    ws_origem = wb.active
    mapa: dict[str, object] = {c.chave: c for c in contatos}
    mapa_por_row: dict[int, object] = {c.row_index: c for c in contatos}

    original_max_col = ws_origem.max_column
    while original_max_col > 1 and not ws_origem.cell(HEADER_ROW, original_max_col).value:
        original_max_col -= 1

    headers = [
        ws_origem.cell(HEADER_ROW, col).value or f"Coluna {col}"
        for col in range(1, original_max_col + 1)
    ]

    wb_saida = openpyxl.Workbook()
    ws = wb_saida.active
    ws.title = "Leads Enriquecidos"
    ws.append(headers + COLUNAS_NOVAS)

    for saida_row, obra in enumerate(obras, start=2):
        contato = mapa_por_row.get(obra.row_index) or mapa.get(obra.chave)
        valores_originais = [
            ws_origem.cell(obra.row_index, col).value
            for col in range(1, original_max_col + 1)
        ]

        if contato is None:
            valores = ["", "", "", "", "", "", "Nao processado"]
        elif contato.erro:
            valores = ["", "", "", "", "", "", f"Erro: {contato.erro[:60]}"]
        else:
            tem_contato = bool(contato.tel_arq_1 or contato.tel_prop_1)
            status = "OK" if tem_contato else "Sem telefone cadastrado"
            valores = [
                contato.tel_arq_1,
                contato.tel_arq_2,
                contato.email_arq,
                contato.tel_prop_1,
                contato.tel_prop_2,
                contato.email_prop,
                status,
            ]

        ws.append(valores_originais + valores)
        ws.row_dimensions[saida_row].height = 34

    _formatar_planilha(ws, original_max_col, len(headers) + len(COLUNAS_NOVAS), len(obras) + 1)

    output = io.BytesIO()
    wb_saida.save(output)
    output.seek(0)
    logger.info("Excel enriquecido gerado.")
    return output.read()


def _formatar_planilha(ws, primeira_col_enriquecida: int, total_cols: int, total_rows: int) -> None:
    """Aplica uma formatacao simples, legivel e consistente para usuarios leigos."""
    header_fill = PatternFill("solid", fgColor=COR_HEADER)
    new_header_fill = PatternFill("solid", fgColor=COR_HEADER_NOVO)
    zebra_fill = PatternFill("solid", fgColor=COR_ZEBRA)
    border = Border(
        left=Side(style="thin", color=COR_BORDA),
        right=Side(style="thin", color=COR_BORDA),
        top=Side(style="thin", color=COR_BORDA),
        bottom=Side(style="thin", color=COR_BORDA),
    )

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(total_cols)}{max(total_rows, 1)}"
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 32

    for col in range(1, total_cols + 1):
        cell = ws.cell(1, col)
        is_new = col > primeira_col_enriquecida
        cell.fill = new_header_fill if is_new else header_fill
        cell.font = Font(bold=True, color=COR_HEADER_NOVO_FONT if is_new else COR_HEADER_FONT)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    for row in range(2, total_rows + 1):
        for col in range(1, total_cols + 1):
            cell = ws.cell(row, col)
            if row % 2 == 0:
                cell.fill = zebra_fill
            cell.alignment = Alignment(vertical="top", wrap_text=True)
            cell.border = border
            if col > primeira_col_enriquecida:
                cell.font = Font(color="1F1F1F")

    for col in range(1, total_cols + 1):
        letter = get_column_letter(col)
        header = str(ws.cell(1, col).value or "")
        values = [str(ws.cell(row, col).value or "") for row in range(1, min(total_rows, 30) + 1)]
        longest = max([len(header), *(len(v) for v in values)], default=12)

        if col > primeira_col_enriquecida:
            width = min(max(longest + 3, 18), 32)
        elif "email" in header.lower() or "informa" in header.lower() or "feedback" in header.lower():
            width = min(max(longest + 2, 22), 38)
        elif "telefone" in header.lower() or "tel" in header.lower():
            width = 19
        else:
            width = min(max(longest + 2, 12), 28)

        ws.column_dimensions[letter].width = width


# ---------------------------------------------------------------------------
# Exportação formato Meetime
# ---------------------------------------------------------------------------

def normalizar_tel(tel: str) -> str:
    """Remove tudo que nao for digito. Ex: '(11) 9 9999-9999' -> '11999999999'."""
    if not tel:
        return ""
    return re.sub(r"\D", "", str(tel))


COLUNAS_MEETIME = [
    "Nome",
    "Tipo",
    "Telefone 1",
    "Telefone 2",
    "Email",
    "Empresa / Condominio",
    "Cidade",
    "UF",
    "Status",
]


def gerar_meetime_excel(obras: list[ObraRow], contatos: list) -> bytes:
    """
    Gera planilha no formato Meetime: 1 linha por contato, telefones normalizados.
    Aba 'Todos' com todos os contatos + uma aba por cidade.
    """
    mapa_por_row: dict[int, object] = {c.row_index: c for c in contatos}
    mapa_por_chave: dict[str, object] = {c.chave: c for c in contatos}

    def _linha(nome, tipo, tel1, tel2, email, empresa, cidade, uf, status, cidade_key):
        return {
            "Nome": nome,
            "Tipo": tipo,
            "Telefone 1": normalizar_tel(tel1),
            "Telefone 2": normalizar_tel(tel2),
            "Email": email or "",
            "Empresa / Condominio": empresa,
            "Cidade": cidade,
            "UF": uf,
            "Status": status,
            "_cidade_key": cidade_key,
        }

    def _montar_linhas_obra(obra: ObraRow) -> list[dict]:
        contato = mapa_por_row.get(obra.row_index) or mapa_por_chave.get(obra.chave)
        empresa = obra.endereco or ""
        cidade = obra.cidade
        uf = obra.uf
        cidade_key = _normalizar(cidade)

        if contato is None:
            resultado = []
            if obra.nome_profissional:
                resultado.append(_linha(obra.nome_profissional, "Arquiteto", "", "", "", empresa, cidade, uf, "Nao processado", cidade_key))
            if obra.nome_proprietario:
                resultado.append(_linha(obra.nome_proprietario, "Proprietario", "", "", "", empresa, cidade, uf, "Nao processado", cidade_key))
            return resultado

        if contato.erro:
            resultado = []
            if obra.nome_profissional:
                resultado.append(_linha(obra.nome_profissional, "Arquiteto", "", "", "", empresa, cidade, uf, "Erro", cidade_key))
            if obra.nome_proprietario:
                resultado.append(_linha(obra.nome_proprietario, "Proprietario", "", "", "", empresa, cidade, uf, "Erro", cidade_key))
            return resultado

        resultado = []
        nome_arq = contato.nome_arquiteto or obra.nome_profissional
        if nome_arq:
            status_arq = "Com telefone" if contato.tel_arq_1 else "Sem telefone"
            resultado.append(_linha(nome_arq, "Arquiteto", contato.tel_arq_1, contato.tel_arq_2, contato.email_arq, empresa, cidade, uf, status_arq, cidade_key))

        nome_prop = contato.nome_proprietario or obra.nome_proprietario
        if nome_prop:
            status_prop = "Com telefone" if contato.tel_prop_1 else "Sem telefone"
            resultado.append(_linha(nome_prop, "Proprietario", contato.tel_prop_1, contato.tel_prop_2, contato.email_prop, empresa, cidade, uf, status_prop, cidade_key))

        return resultado

    todas_linhas: list[dict] = []
    for obra in obras:
        todas_linhas.extend(_montar_linhas_obra(obra))

    wb = openpyxl.Workbook()
    ws_todos = wb.active
    ws_todos.title = "Todos"
    _escrever_aba_meetime(ws_todos, todas_linhas)

    cidades_vistas: list[tuple[str, str]] = []
    vistas: set[str] = set()
    for linha in todas_linhas:
        chave = linha["_cidade_key"]
        if chave and chave not in vistas:
            vistas.add(chave)
            cidades_vistas.append((chave, linha["Cidade"]))

    for chave, nome_cidade in cidades_vistas:
        linhas_cidade = [l for l in todas_linhas if l["_cidade_key"] == chave]
        if not linhas_cidade:
            continue
        titulo = (nome_cidade or chave or "Sem Cidade")[:31]
        ws_cidade = wb.create_sheet(title=titulo)
        _escrever_aba_meetime(ws_cidade, linhas_cidade)

    output = io.BytesIO()
    wb.save(output)
    output.seek(0)
    logger.info("Excel Meetime gerado: %s contatos, %s cidades.", len(todas_linhas), len(cidades_vistas))
    return output.read()


def _escrever_aba_meetime(ws, linhas: list[dict]) -> None:
    ws.append(COLUNAS_MEETIME)
    for linha in linhas:
        ws.append([linha.get(c, "") for c in COLUNAS_MEETIME])
    _formatar_planilha_meetime(ws, len(linhas) + 1)


def _formatar_planilha_meetime(ws, total_rows: int) -> None:
    total_cols = len(COLUNAS_MEETIME)
    header_fill = PatternFill("solid", fgColor=COR_HEADER)
    zebra_fill = PatternFill("solid", fgColor=COR_ZEBRA)
    border = Border(
        left=Side(style="thin", color=COR_BORDA),
        right=Side(style="thin", color=COR_BORDA),
        top=Side(style="thin", color=COR_BORDA),
        bottom=Side(style="thin", color=COR_BORDA),
    )

    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(total_cols)}{max(total_rows, 1)}"
    ws.sheet_view.showGridLines = False
    ws.row_dimensions[1].height = 32

    for col in range(1, total_cols + 1):
        cell = ws.cell(1, col)
        cell.fill = header_fill
        cell.font = Font(bold=True, color=COR_HEADER_FONT)
        cell.alignment = Alignment(horizontal="center", vertical="center", wrap_text=True)
        cell.border = border

    col_widths = {
        "Nome": 30, "Tipo": 14, "Telefone 1": 18, "Telefone 2": 18,
        "Email": 32, "Empresa / Condominio": 28, "Cidade": 18, "UF": 6, "Status": 16,
    }

    for row in range(2, total_rows + 1):
        ws.row_dimensions[row].height = 26
        for col in range(1, total_cols + 1):
            cell = ws.cell(row, col)
            if row % 2 == 0:
                cell.fill = zebra_fill
            cell.alignment = Alignment(vertical="top", wrap_text=False)
            cell.border = border

    for col, header in enumerate(COLUNAS_MEETIME, start=1):
        ws.column_dimensions[get_column_letter(col)].width = col_widths.get(header, 18)
