"""Painel do gestor, metas, estatísticas e relatórios."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (Cadence, Call, Client, Goal, Lead, LeadActivity, LeadBase,
                      LostReason, User)
from .. import serial

router = APIRouter(prefix="/api")


def _month_range(ref: str | None) -> tuple[datetime, datetime]:
    d = date.fromisoformat(ref) if ref else date.today()
    start = datetime(d.year, d.month, 1)
    end = datetime(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return start, end


@router.get("/flow/control-panel")
def control_panel(client_id: int | None = None, db: Session = Depends(get_db)):
    """Painel de controle diário: uma linha por SDR, como no Meetime."""
    now = datetime.utcnow()
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    rows = []
    for u in db.query(User).filter(User.active).order_by(User.name).all():
        leads = db.query(Lead).filter(Lead.sdr_id == u.id)
        if client_id:
            leads = leads.filter(Lead.client_id == client_id)
        by_status = Counter(l.status for l in leads.all())

        acts = db.query(LeadActivity).join(Lead, LeadActivity.lead_id == Lead.id) \
            .filter(LeadActivity.user_id == u.id)
        if client_id:
            acts = acts.filter(Lead.client_id == client_id)
        pending = acts.filter(LeadActivity.status == "PENDING").count()
        late = acts.filter(LeadActivity.status == "PENDING",
                           LeadActivity.scheduled_at < now).count()
        today = acts.filter(LeadActivity.done_at >= day_start).all()
        done = [a for a in today if a.status == "DONE"]
        skipped = [a for a in today if a.status == "SKIPPED"]
        by_type = Counter(a.type for a in done)

        calls_today = db.query(Call).filter(Call.user_id == u.id,
                                            Call.started_at >= day_start).all()
        last = (db.query(LeadActivity).filter(LeadActivity.user_id == u.id,
                                              LeadActivity.done_at.isnot(None))
                .order_by(LeadActivity.done_at.desc()).first())
        rows.append({
            "user": serial.user_min(u), "online": u.online, "dailyGoal": u.daily_goal,
            "lastActivity": serial.lead_activity(last, now) if last else None,
            "leads": {"prospecting": by_status.get("EXECUTING", 0) + by_status.get("ON_EXTRA_ACTIVITY", 0),
                      "available": by_status.get("WAITING", 0),
                      "won": by_status.get("WON", 0), "lost": by_status.get("LOST", 0)},
            "activities": {"pending": pending, "late": late, "done": len(done),
                           "skipped": len(skipped),
                           "call": by_type.get("CALL", 0), "email": by_type.get("E_MAIL", 0),
                           "search": by_type.get("SEARCH", 0),
                           "social": by_type.get("SOCIAL_POINT", 0)},
            "calls": {"total": len(calls_today),
                      "connected": sum(1 for c in calls_today if c.status == "CONNECTED"),
                      "dropped": sum(1 for c in calls_today
                                     if c.status == "CONNECTED" and c.duration <= 10)},
        })
    return {"data": rows, "meta": {"generatedAt": serial.iso(now)}}


@router.get("/flow/goals/{ref}/progress")
def goal_progress(ref: str, db: Session = Depends(get_db)):
    """Dashboard de metas: ganhos por dia × linha da meta, ranking e insights."""
    start, end = _month_range(ref)
    today = min(datetime.utcnow(), end)
    goals = db.query(Goal).filter_by(target_month=start.date()).all()
    target = sum(g.opportunities_goal for g in goals) or 25
    conv_goal = (sum(g.conversion_rate_goal for g in goals) / len(goals)) if goals else 0.15

    won = db.query(Lead).filter(Lead.won_at.between(start, end)).all()
    lost = db.query(Lead).filter(Lead.lost_at.between(start, end)).all()
    per_day = Counter(l.won_at.date().isoformat() for l in won)

    days_in_month = (end - start).days
    elapsed = max(1, (today - start).days)
    series, acc = [], 0
    for i in range(days_in_month):
        d = (start + timedelta(days=i)).date()
        acc += per_day.get(d.isoformat(), 0)
        series.append({"date": d.isoformat(),
                       "actual": acc if d <= today.date() else None,
                       "target": round(target * (i + 1) / days_in_month, 2)})

    expected = round(target * elapsed / days_in_month)
    gap = (len(won) - expected) / expected * 100 if expected else 0
    total = len(won) + len(lost)

    ranking = []
    for u in db.query(User).filter(User.active).all():
        uwon = [l for l in won if l.sdr_id == u.id]
        ulost = [l for l in lost if l.sdr_id == u.id]
        ucalls = db.query(Call).filter(Call.user_id == u.id,
                                       Call.started_at.between(start, end)).all()
        udone = db.query(func.count(LeadActivity.id)).filter(
            LeadActivity.user_id == u.id, LeadActivity.status == "DONE",
            LeadActivity.done_at.between(start, end)).scalar()
        ranking.append({"user": serial.user_min(u), "won": len(uwon), "lost": len(ulost),
                        "activities": udone, "calls": len(ucalls),
                        "meaningful": sum(1 for c in ucalls if c.output == "MEANINGFUL"),
                        "conversion": round(len(uwon) / (len(uwon) + len(ulost)) * 100, 1)
                        if (uwon or ulost) else 0})
    ranking.sort(key=lambda r: r["won"], reverse=True)

    reasons = Counter()
    for l in lost:
        reasons[l.lost_reason.name if l.lost_reason else "Sem motivo"] += 1

    by_client = defaultdict(lambda: {"won": 0, "lost": 0})
    for l in won:
        by_client[l.client.name if l.client else "Sem cliente"]["won"] += 1
    for l in lost:
        by_client[l.client.name if l.client else "Sem cliente"]["lost"] += 1

    return {
        "targetMonth": start.date().isoformat(),
        "goal": {"opportunities": target, "conversionRate": conv_goal},
        "actual": {"won": len(won), "lost": len(lost),
                   "conversion": round(len(won) / total * 100, 1) if total else 0},
        "expectedByNow": expected, "gapPercent": round(gap, 1),
        "series": series, "ranking": ranking,
        "lostReasons": [{"name": k, "count": v} for k, v in reasons.most_common()],
        "byClient": [{"client": k, **v} for k, v in sorted(by_client.items())],
        "effort": calculate_effort(ref, db),
    }


@router.get("/flow/goals/{ref}/calculate-effort")
def calculate_effort(ref: str, db: Session = Depends(get_db)):
    """Quantos leads e atividades a meta exige — o `calculate-effort` do Meetime."""
    start, end = _month_range(ref)
    goals = db.query(Goal).filter_by(target_month=start.date()).all()
    target = sum(g.opportunities_goal for g in goals) or 25
    conv = (sum(g.conversion_rate_goal for g in goals) / len(goals)) if goals else 0.15
    leads_needed = round(target / conv) if conv else 0

    avg_steps = db.query(func.count(LeadActivity.id)).scalar() or 0
    leads_total = db.query(func.count(Lead.id)).scalar() or 1
    per_lead = max(1, round(avg_steps / leads_total))
    activities = leads_needed * per_lead

    business_days = sum(1 for i in range((end - start).days)
                        if (start + timedelta(days=i)).weekday() < 5)
    sdrs = max(1, db.query(func.count(User.id)).filter(User.active).scalar())
    return {"leadsNeeded": leads_needed, "activitiesNeeded": activities,
            "activitiesPerUserPerDay": round(activities / business_days / sdrs),
            "businessDays": business_days, "activitiesPerLead": per_lead,
            "conversionRateGoal": conv}


@router.get("/flow/statistics/summary")
def statistics(since: str | None = None, until: str | None = None,
               client_id: int | None = None, db: Session = Depends(get_db)):
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)

    acts = db.query(LeadActivity).join(Lead, LeadActivity.lead_id == Lead.id) \
        .filter(LeadActivity.done_at.between(start, end))
    if client_id:
        acts = acts.filter(Lead.client_id == client_id)
    acts = acts.all()
    done = [a for a in acts if a.status == "DONE"]
    late = [a for a in done if a.done_at > a.scheduled_at + timedelta(hours=1)]
    by_type = Counter(a.type for a in done)

    won_q = db.query(Lead).filter(Lead.won_at.between(start, end))
    lost_q = db.query(Lead).filter(Lead.lost_at.between(start, end))
    if client_id:
        won_q = won_q.filter(Lead.client_id == client_id)
        lost_q = lost_q.filter(Lead.client_id == client_id)
    won, lost = won_q.all(), lost_q.all()

    reasons = Counter(l.lost_reason.name if l.lost_reason else "Sem motivo" for l in lost)
    origins = defaultdict(lambda: {"won": 0, "lost": 0, "total": 0})
    for l in won + lost:
        key = l.lead_base.name if l.lead_base else "Sem base"
        origins[key]["won" if l.status == "WON" else "lost"] += 1
        origins[key]["total"] += 1

    funnel = []
    for status in ["WAITING", "EXECUTING", "ON_EXTRA_ACTIVITY", "WON", "LOST"]:
        q = db.query(func.count(Lead.id)).filter(Lead.status == status)
        if client_id:
            q = q.filter(Lead.client_id == client_id)
        funnel.append({"status": status, "count": q.scalar()})

    cadences = []
    for c in db.query(Cadence).filter(Cadence.executing).all():
        total = db.query(func.count(Lead.id)).filter_by(cadence_id=c.id).scalar()
        cwon = db.query(func.count(Lead.id)).filter_by(cadence_id=c.id, status="WON").scalar()
        if total:
            cadences.append({"id": c.id, "name": c.name, "priority": c.priority,
                             "client": serial.client(c.client), "total": total, "won": cwon,
                             "conversion": round(cwon / total * 100, 1)})
    cadences.sort(key=lambda r: r["conversion"], reverse=True)

    return {
        "period": {"start": serial.iso(start), "end": serial.iso(end)},
        "activities": {"total": len(done), "late": len(late),
                       "latePercent": round(len(late) / len(done) * 100, 1) if done else 0,
                       "skipped": sum(1 for a in acts if a.status == "SKIPPED"),
                       "byType": [{"type": k, "count": v} for k, v in by_type.most_common()]},
        "outcomes": {"won": len(won), "lost": len(lost),
                     "conversion": round(len(won) / (len(won) + len(lost)) * 100, 1)
                     if (won or lost) else 0},
        "lostReasons": [{"name": k, "count": v} for k, v in reasons.most_common()],
        "origins": [{"name": k, **v} for k, v in
                    sorted(origins.items(), key=lambda kv: -kv[1]["total"])],
        "funnel": funnel, "cadences": cadences[:12],
    }


# ── Relatórios (download CSV) ──
def _csv_response(name: str, header: list[str], rows: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    writer = csv.writer(buf, delimiter=";")
    writer.writerow(header)
    writer.writerows(rows)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]),
                             media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{name}"'})


@router.get("/reports")
def list_reports():
    return [
        {"key": "activity-statistics", "name": "Estatísticas de Atividades",
         "description": "Produtividade e performance por usuário."},
        {"key": "executed-activities", "name": "Atividades Executadas",
         "description": "Todas as atividades realizadas ou ignoradas, com horário, usuário, cadência e lead."},
        {"key": "dropped-calls", "name": "Ligações Derrubadas",
         "description": "Chamadas conectadas e encerradas em até 10 segundos."},
        {"key": "leads", "name": "Leads", "description": "Base completa de leads com status e cliente."},
    ]


@router.get("/reports/{key}")
def download_report(key: str, since: str | None = None, until: str | None = None,
                    db: Session = Depends(get_db)):
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)

    if key == "activity-statistics":
        rows = []
        for u in db.query(User).filter(User.active).all():
            acts = db.query(LeadActivity).filter(
                LeadActivity.user_id == u.id,
                LeadActivity.done_at.between(start, end)).all()
            done = [a for a in acts if a.status == "DONE"]
            calls = db.query(Call).filter(Call.user_id == u.id,
                                          Call.started_at.between(start, end)).all()
            rows.append([u.name, u.email, len(done),
                         sum(1 for a in acts if a.status == "SKIPPED"),
                         sum(1 for a in done if a.done_at > a.scheduled_at + timedelta(hours=1)),
                         len(calls), sum(1 for c in calls if c.output == "MEANINGFUL"),
                         db.query(func.count(Lead.id)).filter(
                             Lead.sdr_id == u.id, Lead.won_at.between(start, end)).scalar()])
        return _csv_response("estatisticas-atividades.csv",
                             ["Usuário", "E-mail", "Realizadas", "Ignoradas", "Atrasadas",
                              "Ligações", "Significativas", "Ganhos"], rows)

    if key == "executed-activities":
        acts = (db.query(LeadActivity).filter(LeadActivity.done_at.between(start, end))
                .order_by(LeadActivity.done_at.desc()).limit(20000).all())
        rows = [[a.done_at.strftime("%d/%m/%Y %H:%M"), a.status, a.type,
                 a.user.name if a.user else "", a.lead.name if a.lead else "",
                 a.lead.company if a.lead else "",
                 a.lead.cadence.name if a.lead and a.lead.cadence else "",
                 a.lead.client.name if a.lead and a.lead.client else "",
                 a.activity.name if a.activity else ""] for a in acts]
        return _csv_response("atividades-executadas.csv",
                             ["Data", "Situação", "Tipo", "Usuário", "Lead", "Empresa",
                              "Cadência", "Cliente", "Atividade"], rows)

    if key == "dropped-calls":
        calls = (db.query(Call).filter(Call.started_at.between(start, end),
                                       Call.status == "CONNECTED", Call.duration <= 10)
                 .order_by(Call.started_at.desc()).all())
        rows = [[c.started_at.strftime("%d/%m/%Y %H:%M"), c.user.name if c.user else "",
                 c.lead.name if c.lead else "", c.lead.company if c.lead else "",
                 c.receiver_phone, c.duration, c.output] for c in calls]
        return _csv_response("ligacoes-derrubadas.csv",
                             ["Data", "Usuário", "Lead", "Empresa", "Número",
                              "Duração (s)", "Resultado"], rows)

    if key == "leads":
        leads = db.query(Lead).order_by(Lead.id.desc()).limit(20000).all()
        rows = [[l.id, l.name, l.company, l.cnpj, l.email, l.phone, l.city, l.state,
                 l.status, l.cadence.name if l.cadence else "",
                 l.client.name if l.client else "", l.sdr.name if l.sdr else "",
                 l.lead_base.name if l.lead_base else "",
                 l.created_at.strftime("%d/%m/%Y")] for l in leads]
        return _csv_response("leads.csv",
                             ["ID", "Nome", "Empresa", "CNPJ", "E-mail", "Telefone",
                              "Cidade", "UF", "Situação", "Cadência", "Cliente", "SDR",
                              "Base", "Criado em"], rows)

    raise HTTPException(404, "Relatório desconhecido.")
