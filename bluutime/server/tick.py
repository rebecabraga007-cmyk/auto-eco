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
import threading
import traceback
from datetime import datetime, timedelta

from sqlalchemy import func

from . import agenda, webhooks
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
        r = LostReason(name=FIM_DE_CADENCIA)
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
    from .routers.flow import _fechar_prospeccao  # evita import circular
    from . import serial
    reason = _lost_reason_id(db)
    now = agenda.to_utc(agenda.now_local())
    for lead in leads:
        lead.status = "LOST"
        lead.lost_reason_id = reason
        lead.lost_at = now
        lead.reprospect_at, lead.reprospect_cadence_id = None, None
        # Fecha a passagem pela cadência e avisa quem assina LEAD.LOST: é o
        # maior motivo de perda e nenhum CRM integrado ficava sabendo.
        _fechar_prospeccao(db, lead, "LOST")
        webhooks.enfileirar(db, "LEAD.LOST", serial.lead(lead))
    return len(leads)


def release_stuck_sends(db) -> int:
    """Envio que ficou reservado (SENDING) por mais de 10 min volta para a
    fila — o processo caiu no meio do envio e ninguém concluiu."""
    limite = datetime.utcnow() - timedelta(minutes=10)
    return (db.query(LeadActivity)
            .filter(LeadActivity.status == "SENDING", LeadActivity.done_at < limite)
            .update({"status": "PENDING", "done_at": None}, synchronize_session=False))


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


def restart_reprospects(db) -> int:
    """Perdido por reaproveitamento cuja data chegou → volta a ser prospectado
    na cadência escolhida, com o mesmo responsável."""
    from .routers.flow import _apagar_atividades, _schedule_cadence  # evita import circular
    hoje = agenda.now_local().date()
    leads = (db.query(Lead).filter(Lead.status == "LOST", Lead.reprospect_at.isnot(None),
                                   Lead.reprospect_at <= hoje).all())
    for lead in leads:
        cad = db.get(Cadence, lead.reprospect_cadence_id) if lead.reprospect_cadence_id else None
        lead.reprospect_at, lead.reprospect_cadence_id = None, None
        if not cad:
            continue
        lead.cadence_id = cad.id
        lead.lost_reason_id, lead.lost_at = None, None
        lead.status, lead.current_step = "WAITING", 0
        _apagar_atividades(db, lead_id=lead.id, apenas_pendentes=True)
        _schedule_cadence(db, lead)
    return len(leads)


_trava = threading.Lock()


def run_once() -> dict:
    """Uma passada. Devolve o que mudou — é o corpo de `POST /api/admin/tick`.

    Cada etapa tem a própria transação: antes, um erro em qualquer uma (um
    motivo de perda que não dava para criar, por exemplo) desfazia todas e
    parava o despacho de webhooks para sempre. A trava impede o laço e o
    `POST /api/admin/tick` de rodarem juntos e entregarem o mesmo webhook duas
    vezes ou agendarem a mesma cadência em dobro."""
    if not _trava.acquire(blocking=False):
        return {"ocupado": True}
    report = {}
    try:
        for nome, etapa in (("sendsLiberados", release_stuck_sends), ("expired", expire_stale_activities),
                            ("reprospected", restart_reprospects), ("closed", close_finished_cadences),
                            ("webhooks", webhooks.despachar)):
            db = SessionLocal()
            try:
                report[nome] = etapa(db)
                db.commit()
            except Exception:
                db.rollback()
                traceback.print_exc()
                report[nome] = "erro"
            finally:
                db.close()
        return report
    finally:
        _trava.release()


async def loop() -> None:
    while True:
        await asyncio.sleep(TICK_SECONDS)
        try:
            report = await asyncio.to_thread(run_once)
            if any(report.values()):
                print(f"[bluutime] tick: {report}")
        except Exception:                                   # não derruba o laço
            traceback.print_exc()
