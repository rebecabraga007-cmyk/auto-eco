"""O que o sistema faz sozinho, sem ninguém clicar.

Até aqui o Bluutime só reagia a request: cadência não terminava, atividade
vencida ficava pendente para sempre e nenhum lead saía da fila por conta
própria. Na operação real "Fim de cadência" é o maior motivo de perda — 254 de
507 — e isso é justamente o que precisa acontecer sozinho.

O laço roda a cada `TICK_SECONDS` dentro do próprio processo. Um agendador de
verdade (cron, worker separado) seria melhor num deploy multi-instância; para
uma instância local, um `asyncio.Task` basta e não acrescenta dependência.
"""
import asyncio
import traceback

from sqlalchemy import func

from . import agenda
from .db import SessionLocal
from .models import Cadence, Lead, LeadActivity, LostReason

TICK_SECONDS = 300           # 5 min
STALE_AFTER_DAYS = 3         # atividade vencida há mais de 3 dias úteis é abandonada
FIM_DE_CADENCIA = "Fim de cadência"


def _lost_reason_id(db) -> int | None:
    """O motivo padrão de perda automática, criado na primeira vez que faltar."""
    r = db.query(LostReason).filter(func.lower(LostReason.name)
                                    == FIM_DE_CADENCIA.lower()).first()
    if not r:
        r = LostReason(name=FIM_DE_CADENCIA, active=True)
        db.add(r)
        db.flush()
    return r.id


def close_finished_cadences(db) -> int:
    """Lead em execução sem nenhuma atividade pendente → perdido por fim de cadência.

    Só fecha quem já teve alguma atividade: lead recém-criado cuja cadência ainda
    não tem etapa nenhuma continua esperando, em vez de nascer perdido.
    """
    pending = (db.query(LeadActivity.lead_id)
               .filter(LeadActivity.status == "PENDING").subquery())
    ever = db.query(LeadActivity.lead_id).subquery()

    leads = (db.query(Lead)
             .filter(Lead.status == "EXECUTING",
                     Lead.id.notin_(db.query(pending.c.lead_id)),
                     Lead.id.in_(db.query(ever.c.lead_id)))
             .all())
    if not leads:
        return 0
    reason = _lost_reason_id(db)
    now = agenda.to_utc(agenda.now_local())
    for lead in leads:
        lead.status = "LOST"
        lead.lost_reason_id = reason
        lead.lost_at = now
    return len(leads)


def expire_stale_activities(db) -> int:
    """Atividade vencida há dias vira SKIPPED — senão a fila só cresce.

    Sem isso o SDR abre a execução e vê tarefa de três semanas atrás no topo,
    e o lead nunca chega ao fim da cadência.
    """
    holidays = agenda.holiday_dates(db)
    cutoff = agenda.to_utc(agenda.business_days_ago(STALE_AFTER_DAYS, holidays))

    stale = (db.query(LeadActivity)
             .filter(LeadActivity.status == "PENDING",
                     LeadActivity.scheduled_at < cutoff)
             .all())
    for act in stale:
        act.status = "SKIPPED"
        act.notes = (act.notes + "\n" if act.notes else "") + \
            "Ignorada automaticamente: vencida há mais de "\
            f"{STALE_AFTER_DAYS} dias úteis."
    return len(stale)


def run_once() -> dict:
    """Uma passada. Devolve o que mudou — é o corpo de `POST /api/admin/tick`."""
    db = SessionLocal()
    try:
        report = {"expired": expire_stale_activities(db)}
        db.flush()
        report["closed"] = close_finished_cadences(db)
        db.commit()
        return report
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


async def loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            report = await asyncio.to_thread(run_once)
            if any(report.values()):
                print(f"[bluutime] tick: {report}")
        except Exception:                                   # não derruba o laço
            traceback.print_exc()
