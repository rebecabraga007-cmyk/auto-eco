"""Calendário da operação: quando uma atividade pode cair.

Três regras que o agendador anterior não tinha:

1. **Fuso.** O banco guarda UTC, mas "ligar às 18h" é 18h de Brasília. Aplicar
   `hour=18` sobre `utcnow()` agendava para as 15h locais.
2. **Feriado.** O modelo `Holiday` existia e nunca era consultado.
3. **Janela útil.** Fora de 9h–18h a ligação não é feita; empurra para a próxima
   abertura em vez de cair de madrugada.
"""
from datetime import date, datetime, time, timedelta, timezone

from sqlalchemy.orm import Session

from .models import Holiday

# A operação é toda em Brasília. Sem horário de verão desde 2019, então o
# deslocamento fixo é correto e evita depender de tzdata no Windows.
TZ = timezone(timedelta(hours=-3))

WORK_START = 9
WORK_END = 18   # exclusivo: 18h ainda vale, 18h01 não


def now_local() -> datetime:
    """Agora, no fuso da operação, sem tzinfo (para comparar com o que está no banco)."""
    return datetime.now(TZ).replace(tzinfo=None)


def to_utc(local: datetime) -> datetime:
    return local.replace(tzinfo=TZ).astimezone(timezone.utc).replace(tzinfo=None)


def to_local(utc: datetime) -> datetime:
    return utc.replace(tzinfo=timezone.utc).astimezone(TZ).replace(tzinfo=None)


def holiday_dates(db: Session) -> set[date]:
    return {h.day for h in db.query(Holiday).all() if h.day}


def is_business_day(day: date, holidays: set[date]) -> bool:
    return day.weekday() < 5 and day not in holidays


def next_business_day(day: date, holidays: set[date]) -> date:
    while not is_business_day(day, holidays):
        day += timedelta(days=1)
    return day


def add_business_days(start: date, days: int, holidays: set[date]) -> date:
    """`days` dias úteis à frente. Dia 1 da cadência é o próprio dia de entrada."""
    day = next_business_day(start, holidays)
    for _ in range(max(0, days)):
        day = next_business_day(day + timedelta(days=1), holidays)
    return day


def slot(day: date, hour: int, holidays: set[date]) -> datetime:
    """Encaixa `hour` na janela útil do dia — ou joga para a próxima abertura.

    Devolve horário **local**; quem grava converte com `to_utc`.
    """
    hour = min(max(int(hour or WORK_START), WORK_START), WORK_END)
    return datetime.combine(next_business_day(day, holidays), time(hour=hour))


def business_days_ago(days: int, holidays: set[date]) -> datetime:
    """Abertura do expediente `days` dias úteis atrás (local)."""
    day = now_local().date()
    for _ in range(max(0, days)):
        day -= timedelta(days=1)
        while not is_business_day(day, holidays):
            day -= timedelta(days=1)
    return datetime.combine(day, time(hour=WORK_START))


def next_open(after: datetime, holidays: set[date]) -> datetime:
    """Primeiro instante útil a partir de `after` (local)."""
    if after.hour >= WORK_END:
        after = datetime.combine(after.date() + timedelta(days=1), time(hour=WORK_START))
    elif after.hour < WORK_START:
        after = after.replace(hour=WORK_START, minute=0, second=0, microsecond=0)
    return datetime.combine(next_business_day(after.date(), holidays), after.time())
