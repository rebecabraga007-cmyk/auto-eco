"""Feriados nacionais brasileiros, calculados — não digitados.

O suporte a feriado existia desde a Fase 1 e a tabela estava **vazia**: o
agendador consultava `Holiday`, não achava nada e caía para "só pula fim de
semana". Recurso que parece pronto e não funciona por falta de dado é pior que
recurso ausente, porque ninguém vai procurar.

Lista fixa mais os móveis, que dependem da Páscoa. Feriado municipal e estadual
não entram: variam por cidade e a operação atende o país inteiro — quem precisar
acrescenta pela tabela.
"""
from datetime import date, timedelta

# Data · nome · é feriado legal (True) ou ponto facultativo (False).
# Carnaval, Sexta-feira Santa e Corpus Christi não são feriado nacional por lei,
# mas na prática comercial ninguém atende — por isso entram como não-úteis.
FIXOS = [
    ((1, 1), "Confraternização Universal"),
    ((4, 21), "Tiradentes"),
    ((5, 1), "Dia do Trabalho"),
    ((9, 7), "Independência"),
    ((10, 12), "Nossa Senhora Aparecida"),
    ((11, 2), "Finados"),
    ((11, 15), "Proclamação da República"),
    ((11, 20), "Consciência Negra"),      # nacional desde 2024 (Lei 14.759)
    ((12, 25), "Natal"),
]


def pascoa(ano: int) -> date:
    """Domingo de Páscoa pelo algoritmo de Meeus/Jones/Butcher."""
    a = ano % 19
    b, c = divmod(ano, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    m = (32 + 2 * e + 2 * i - h - k) % 7
    n = (a + 11 * h + 22 * m) // 451
    mes, dia = divmod(h + m - 7 * n + 114, 31)
    return date(ano, mes, dia + 1)


def do_ano(ano: int) -> list[tuple[date, str]]:
    p = pascoa(ano)
    moveis = [
        (p - timedelta(days=48), "Carnaval"),
        (p - timedelta(days=47), "Carnaval"),
        (p - timedelta(days=2), "Sexta-feira Santa"),
        (p + timedelta(days=60), "Corpus Christi"),
    ]
    return sorted([(date(ano, m, d), nome) for (m, d), nome in FIXOS] + moveis)


def carregar(db, anos: list[int]) -> int:
    """Insere os feriados que faltarem. Idempotente — roda a cada subida."""
    from .models import Holiday

    existentes = {h.day for h in db.query(Holiday).all()}
    novos = 0
    for ano in anos:
        for dia, nome in do_ano(ano):
            if dia not in existentes:
                db.add(Holiday(day=dia, name=nome))
                existentes.add(dia)
                novos += 1
    if novos:
        db.commit()
    return novos
