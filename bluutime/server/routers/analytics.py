"""Painel do gestor, metas, estatísticas e relatórios."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import perm, serial
from ..db import get_db
from ..models import (Cadence, Call, Client, Goal, Lead, LeadActivity, LeadBase,
                      LostReason, Team, User)

router = APIRouter(prefix="/api")


def _month_range(ref: str | None) -> tuple[datetime, datetime]:
    d = date.fromisoformat(ref) if ref else date.today()
    start = datetime(d.year, d.month, 1)
    end = datetime(d.year + (d.month == 12), (d.month % 12) + 1, 1)
    return start, end


@router.get("/flow/control-panel")
def control_panel(client_id: int | None = None, db: Session = Depends(get_db)):
    """Painel de controle diário: uma linha por SDR, como no Meetime.

    É a visão do gestor — dado de todo o time, não só do próprio SDR."""
    perm.ator(db).exigir("gestor", "ver o painel de controle")
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


def usuarios_do_time(db: Session, team_id: int | None) -> list[int] | None:
    """Ids de quem está no time, ou `None` quando não há filtro de time.

    Lista vazia não é o mesmo que `None`: um time sem ninguém tem que devolver
    zero, não a empresa inteira — por isso o chamador testa `is not None`.
    """
    if not team_id:
        return None
    return [r[0] for r in db.query(User.id).filter(User.team_id == team_id).all()]


@router.get("/flow/statistics/cadence-overview")
def cadence_overview(team_id: int | None = None, db: Session = Depends(get_db)):
    """Distribuição dos leads nas cadências — quantos em cada situação.

    É a tela `cadence-overview` do original: mostra onde a base está parada,
    coisa que a conversão sozinha não conta.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    do_time = usuarios_do_time(db, team_id)
    situacoes = ["WAITING", "EXECUTING", "ON_EXTRA_ACTIVITY", "WON", "LOST"]
    saida = []
    for c in db.query(Cadence).order_by(Cadence.name).all():
        q = db.query(Lead.status, func.count(Lead.id)).filter(Lead.cadence_id == c.id)
        if do_time is not None:
            q = q.filter(Lead.sdr_id.in_(do_time))
        por_situacao = dict(q.group_by(Lead.status).all())
        total = sum(por_situacao.values())
        if not total:
            continue
        saida.append({"id": c.id, "name": c.name, "total": total,
                      "porSituacao": {s: por_situacao.get(s, 0) for s in situacoes},
                      "conversao": round(por_situacao.get("WON", 0) / total * 100, 1)})
    saida.sort(key=lambda r: r["total"], reverse=True)
    return {"data": saida}


@router.get("/flow/statistics/cadence-steps/{cadence_id}")
def cadence_steps(cadence_id: int, since: str | None = None, until: str | None = None,
                  db: Session = Depends(get_db)):
    """Conversão passo a passo de UMA cadência.

    O original só oferece isto com uma cadência escolhida, e por um bom
    motivo: passo 3 de cadências diferentes não é a mesma coisa, então somar
    tudo produziria uma média sem significado.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)

    cad = db.get(Cadence, cadence_id)
    if not cad:
        raise HTTPException(404, "Cadência não encontrada.")

    passos = []
    for i, step in enumerate(sorted(cad.steps, key=lambda s: (s.day, s.order_in_day)), 1):
        base = db.query(LeadActivity).filter(LeadActivity.cadence_step_id == step.id,
                                             LeadActivity.done_at.between(start, end))
        executados = base.filter(LeadActivity.status == "DONE").count()
        engajadas = base.filter(LeadActivity.status == "DONE",
                                LeadActivity.replied.is_(True)).count()
        ganhos = (base.filter(LeadActivity.status == "DONE")
                  .join(Lead, LeadActivity.lead_id == Lead.id)
                  .filter(Lead.status == "WON").count())
        passos.append({"passo": i, "dia": step.day,
                       "atividade": step.activity.name if step.activity else "—",
                       "executados": executados, "engajadas": engajadas, "ganhos": ganhos,
                       "engajamento": round(engajadas / executados * 100, 1) if executados else 0.0})

    leads_q = db.query(Lead).filter(Lead.cadence_id == cadence_id)
    finalizados = leads_q.filter(Lead.status.in_(["WON", "LOST"])).count()
    ganhos_total = leads_q.filter(Lead.status == "WON").count()
    engajados = (db.query(func.count(func.distinct(LeadActivity.lead_id)))
                 .join(Lead, LeadActivity.lead_id == Lead.id)
                 .filter(Lead.cadence_id == cadence_id, LeadActivity.replied.is_(True)).scalar())
    total_leads = leads_q.count()
    return {"cadence": {"id": cad.id, "name": cad.name},
            "resumo": {"leads": total_leads, "finalizados": finalizados,
                       "ganhos": ganhos_total, "engajados": engajados,
                       "taxaEngajados": round(engajados / total_leads * 100, 1) if total_leads else 0.0,
                       "taxaGanhos": round(ganhos_total / total_leads * 100, 1) if total_leads else 0.0},
            "passos": passos}


@router.get("/flow/statistics/response-time")
def response_time(since: str | None = None, until: str | None = None,
                  team_id: int | None = None, db: Session = Depends(get_db)):
    """Quanto tempo entre o lead chegar e a primeira abordagem.

    Mede só quem JÁ foi abordado. Lead que ninguém tocou ainda não tem tempo
    de resposta — misturar os dois faria a média melhorar quanto mais gente
    fosse ignorada, que é exatamente o contrário do que a métrica serve.
    """
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)
    meta_horas = _company_goal_hours(db)

    q = db.query(Lead).filter(Lead.created_at.between(start, end))
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Lead.sdr_id.in_(do_time))
    leads = q.all()

    primeiras = dict(
        db.query(LeadActivity.lead_id, func.min(LeadActivity.done_at))
        .filter(LeadActivity.status == "DONE",
                LeadActivity.lead_id.in_([l.id for l in leads] or [0]))
        .group_by(LeadActivity.lead_id).all())

    por_usuario: dict = {}
    horas_todas: list[float] = []
    dentro = 0
    for l in leads:
        primeira = primeiras.get(l.id)
        if not primeira or not l.created_at:
            continue
        horas = (primeira - l.created_at).total_seconds() / 3600
        if horas < 0:
            continue
        horas_todas.append(horas)
        no_prazo = horas <= meta_horas
        dentro += 1 if no_prazo else 0
        nome = l.sdr.name if l.sdr else "Sem SDR"
        linha = por_usuario.setdefault(nome, {"label": nome, "abordados": 0,
                                              "dentro": 0, "horas": []})
        linha["abordados"] += 1
        linha["dentro"] += 1 if no_prazo else 0
        linha["horas"].append(horas)

    ranking = []
    for linha in por_usuario.values():
        ranking.append({"label": linha["label"], "abordados": linha["abordados"],
                        "dentro": linha["dentro"],
                        "percentual": round(linha["dentro"] / linha["abordados"] * 100, 1),
                        "mediaHoras": round(sum(linha["horas"]) / len(linha["horas"]), 1)})
    ranking.sort(key=lambda r: r["percentual"], reverse=True)

    abordados = len(horas_todas)
    return {"metaHoras": meta_horas, "novosLeads": len(leads), "abordados": abordados,
            "naoAbordados": len(leads) - abordados,
            "dentroDaMeta": dentro,
            "percentual": round(dentro / abordados * 100, 1) if abordados else 0.0,
            "mediaHoras": round(sum(horas_todas) / abordados, 1) if abordados else 0.0,
            "ranking": ranking}


def _company_goal_hours(db: Session) -> int:
    from ..models import Company
    c = db.query(Company).first()
    return getattr(c, "response_time_goal_hours", 24) or 24


@router.get("/flow/statistics/lost-reasons")
def lost_reasons_breakdown(since: str | None = None, until: str | None = None,
                           by: str = "reason", team_id: int | None = None,
                           db: Session = Depends(get_db)):
    """Motivos de perda por motivo, usuário, time ou cadência."""
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)
    q = db.query(Lead).filter(Lead.lost_at.between(start, end))
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Lead.sdr_id.in_(do_time))

    times = {t.id: t.name for t in db.query(Team).all()}
    contagem: Counter = Counter()
    for l in q.all():
        if by == "user":
            chave = l.sdr.name if l.sdr else "Sem SDR"
        elif by == "team":
            chave = times.get(l.sdr.team_id, "Sem time") if l.sdr and l.sdr.team_id else "Sem time"
        elif by == "cadence":
            chave = l.cadence.name if l.cadence else "Sem cadência"
        else:
            chave = l.lost_reason.name if l.lost_reason else "Sem motivo"
        contagem[chave] += 1
    return {"by": by, "data": [{"label": k, "count": v} for k, v in contagem.most_common()]}


@router.get("/flow/statistics/summary")
def statistics(since: str | None = None, until: str | None = None,
               client_id: int | None = None, team_id: int | None = None,
               db: Session = Depends(get_db)):
    perm.exigir_ou_permissao(db, perm.ator(db), "statistics_access", "acessar estatísticas")
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end - timedelta(days=30)
    # Time é um conjunto de pessoas, então filtrar por time é filtrar pelo dono:
    # o executor da atividade, o SDR do lead.
    do_time = usuarios_do_time(db, team_id)

    acts = db.query(LeadActivity).join(Lead, LeadActivity.lead_id == Lead.id) \
        .filter(LeadActivity.done_at.between(start, end))
    if client_id:
        acts = acts.filter(Lead.client_id == client_id)
    if do_time is not None:
        acts = acts.filter(LeadActivity.user_id.in_(do_time))
    acts = acts.all()
    done = [a for a in acts if a.status == "DONE"]
    late = [a for a in done if a.done_at > a.scheduled_at + timedelta(hours=1)]
    by_type = Counter(a.type for a in done)

    won_q = db.query(Lead).filter(Lead.won_at.between(start, end))
    lost_q = db.query(Lead).filter(Lead.lost_at.between(start, end))
    if client_id:
        won_q = won_q.filter(Lead.client_id == client_id)
        lost_q = lost_q.filter(Lead.client_id == client_id)
    if do_time is not None:
        won_q = won_q.filter(Lead.sdr_id.in_(do_time))
        lost_q = lost_q.filter(Lead.sdr_id.in_(do_time))
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
        if do_time is not None:
            q = q.filter(Lead.sdr_id.in_(do_time))
        funnel.append({"status": status, "count": q.scalar()})

    cadences = []
    for c in db.query(Cadence).filter(Cadence.executing).all():
        base = db.query(func.count(Lead.id)).filter(Lead.cadence_id == c.id)
        if do_time is not None:
            base = base.filter(Lead.sdr_id.in_(do_time))
        total = base.scalar()
        cwon = base.filter(Lead.status == "WON").scalar()
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
    # Os 4 relatórios são agregados da empresa inteira (todo usuário, toda
    # carteira) — não é dado "meu", é dado de time. `statistics_access` nasce
    # ligado por padrão (Company.statistics_access=True), então até aqui
    # qualquer SDR baixava a base de leads inteira em CSV. O menu
    # "Relatórios" já é gestor+ (index.html); o servidor tinha ficado mais
    # permissivo que a própria tela que leva até ele.
    perm.ator(db).exigir("gestor", "baixar relatório")
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
