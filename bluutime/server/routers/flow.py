"""Prospecção: cadências, atividades, leads, bases e a fila de execução."""
import csv
import io
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import (Activity, Cadence, CadenceStep, CadenceUser, Client,
                      CustomField, Lead, LeadActivity, LeadBase, LeadFieldValue,
                      LostReason, Template, User)
from .. import agenda, render, serial

router = APIRouter(prefix="/api/flow")


def _overview(db: Session, cadence_id: int) -> dict:
    rows = (db.query(Lead.status, func.count(Lead.id))
            .filter(Lead.cadence_id == cadence_id).group_by(Lead.status).all())
    counts = dict(rows)
    return {"total": sum(counts.values()),
            "won": counts.get("WON", 0), "lost": counts.get("LOST", 0),
            "waiting": counts.get("WAITING", 0), "executing": counts.get("EXECUTING", 0),
            "onExtraActivity": counts.get("ON_EXTRA_ACTIVITY", 0),
            "paused": counts.get("PAUSED_FROM_EXECUTING", 0),
            "switchedCadence": counts.get("SWITCHED_CADENCE", 0)}


def _cadence_users(db: Session, cadence_id: int) -> list[User]:
    return (db.query(User).join(CadenceUser, CadenceUser.user_id == User.id)
            .filter(CadenceUser.cadence_id == cadence_id).all())


# ── Cadências ──
@router.get("/cadences")
def list_cadences(client_id: int | None = None, focus: str | None = None,
                  priority: str | None = None, executing: bool | None = None,
                  q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Cadence)
    if client_id:
        query = query.filter(Cadence.client_id == client_id)
    if focus:
        query = query.filter(Cadence.focus == focus)
    if priority:
        query = query.filter(Cadence.priority == priority)
    if executing is not None:
        query = query.filter(Cadence.executing == executing)
    if q:
        query = query.filter(Cadence.name.ilike(f"%{q}%"))
    return [serial.cadence(c, _overview(db, c.id), _cadence_users(db, c.id))
            for c in query.order_by(Cadence.executing.desc(), Cadence.name).all()]


@router.get("/cadences/overview")
def cadences_overview(db: Session = Depends(get_db)):
    return [{"id": c.id, "overview": _overview(db, c.id)} for c in db.query(Cadence).all()]


@router.get("/cadences/{cid}")
def get_cadence(cid: int, db: Session = Depends(get_db)):
    c = db.get(Cadence, cid)
    if not c:
        raise HTTPException(404, "Cadência não encontrada.")
    data = serial.cadence(c, _overview(db, cid), _cadence_users(db, cid))
    data["steps"] = [serial.cadence_step(s) for s in c.steps]
    return data


@router.post("/cadences")
def create_cadence(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome da cadência é obrigatório.")
    c = Cadence(name=name, description=payload.get("description", ""),
                focus=payload.get("cadenceFocus", "OUTBOUND"),
                priority=payload.get("priority", "MEDIUM"),
                executing=bool(payload.get("executing", True)),
                client_id=payload.get("clientId"))
    db.add(c)
    db.flush()
    for uid in payload.get("userIds", []):
        db.add(CadenceUser(cadence_id=c.id, user_id=uid,
                           daily_goal=payload.get("dailyGoal", 200)))
    db.commit()
    return serial.cadence(c, _overview(db, c.id), _cadence_users(db, c.id))


@router.patch("/cadences/{cid}")
def update_cadence(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    c = db.get(Cadence, cid)
    if not c:
        raise HTTPException(404, "Cadência não encontrada.")
    for key, attr in [("name", "name"), ("description", "description"),
                      ("cadenceFocus", "focus"), ("priority", "priority"),
                      ("executing", "executing"), ("clientId", "client_id")]:
        if key in payload:
            setattr(c, attr, payload[key])
    if "userIds" in payload:
        db.query(CadenceUser).filter_by(cadence_id=cid).delete()
        for uid in payload["userIds"]:
            db.add(CadenceUser(cadence_id=cid, user_id=uid))
    db.commit()
    return serial.cadence(c, _overview(db, cid), _cadence_users(db, cid))


@router.delete("/cadences/{cid}")
def delete_cadence(cid: int, db: Session = Depends(get_db)):
    c = db.get(Cadence, cid)
    if not c:
        raise HTTPException(404, "Cadência não encontrada.")
    if db.query(func.count(Lead.id)).filter_by(cadence_id=cid).scalar():
        raise HTTPException(400, "A cadência tem leads. Transfira-os antes de excluir.")
    db.delete(c)
    db.commit()
    return {"ok": True}


@router.post("/cadences/{cid}/steps")
def add_step(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    if not db.get(Cadence, cid):
        raise HTTPException(404, "Cadência não encontrada.")
    activity_id = payload.get("activityId")
    if not activity_id or not db.get(Activity, activity_id):
        raise HTTPException(400, "Atividade inválida.")
    day = int(payload.get("day", 1))
    order = (db.query(func.count(CadenceStep.id))
             .filter_by(cadence_id=cid, day=day).scalar() or 0) + 1
    template_id = payload.get("templateId")
    if template_id and not db.get(Template, template_id):
        raise HTTPException(400, "Modelo de mensagem inválido.")
    s = CadenceStep(cadence_id=cid, activity_id=activity_id, day=day,
                    order_in_day=order, template_id=template_id)
    db.add(s)
    db.commit()
    return serial.cadence_step(s)


@router.delete("/cadences/{cid}/steps/{sid}")
def delete_step(cid: int, sid: int, db: Session = Depends(get_db)):
    s = db.get(CadenceStep, sid)
    if s and s.cadence_id == cid:
        db.delete(s)
        db.commit()
    return {"ok": True}


# ── Modelos de mensagem ──
CHANNELS = {"EMAIL", "WHATSAPP", "SOCIAL"}


def _template(t: Template) -> dict:
    return {"id": t.id, "name": t.name, "channel": t.channel, "subject": t.subject,
            "body": t.body, "clientId": t.client_id, "active": t.active,
            "variables": sorted({m.group(1).lower()
                                 for m in render._VAR.finditer(f"{t.subject} {t.body}")})}


@router.get("/templates")
def list_templates(channel: str | None = None, client_id: int | None = None,
                   db: Session = Depends(get_db)):
    q = db.query(Template).filter(Template.active.is_(True))
    if channel:
        q = q.filter(Template.channel == channel.upper())
    if client_id:
        q = q.filter(Template.client_id == client_id)
    return [_template(t) for t in q.order_by(Template.name).all()]


@router.post("/templates")
def create_template(payload: dict = Body(...), db: Session = Depends(get_db)):
    channel = (payload.get("channel") or "EMAIL").upper()
    if channel not in CHANNELS:
        raise HTTPException(400, f"Canal inválido. Use: {', '.join(sorted(CHANNELS))}")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Dê um nome ao modelo.")
    t = Template(name=name, channel=channel, subject=payload.get("subject", ""),
                 body=payload.get("body", ""), client_id=payload.get("clientId"),
                 created_by_id=payload.get("createdById"))
    db.add(t)
    db.commit()
    return _template(t)


@router.patch("/templates/{tid}")
def update_template(tid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    t = db.get(Template, tid)
    if not t:
        raise HTTPException(404, "Modelo não encontrado.")
    for key, attr in {"name": "name", "subject": "subject", "body": "body",
                      "clientId": "client_id", "active": "active"}.items():
        if key in payload:
            setattr(t, attr, payload[key])
    if "channel" in payload:
        if payload["channel"].upper() not in CHANNELS:
            raise HTTPException(400, "Canal inválido.")
        t.channel = payload["channel"].upper()
    db.commit()
    return _template(t)


@router.delete("/templates/{tid}")
def delete_template(tid: int, db: Session = Depends(get_db)):
    t = db.get(Template, tid)
    if not t:
        raise HTTPException(404, "Modelo não encontrado.")
    # Passo de cadência aponta para o modelo — desativar preserva o histórico.
    used = db.query(CadenceStep).filter(CadenceStep.template_id == tid).count()
    if used:
        t.active = False
        db.commit()
        return {"ok": True, "deactivated": True, "usedBySteps": used}
    db.delete(t)
    db.commit()
    return {"ok": True, "deactivated": False}


@router.post("/templates/{tid}/preview")
def preview_template(tid: int, payload: dict = Body(default={}),
                     db: Session = Depends(get_db)):
    """Renderiza o modelo com um lead real — ou com o primeiro que houver.

    É o que evita mandar "Olá {{primeiro_nome}}" para um cliente.
    """
    t = db.get(Template, tid)
    if not t:
        raise HTTPException(404, "Modelo não encontrado.")
    lead = (db.get(Lead, payload["leadId"]) if payload.get("leadId")
            else db.query(Lead).order_by(Lead.id.desc()).first())
    if not lead:
        raise HTTPException(400, "Não há lead para pré-visualizar.")
    user = db.get(User, payload["userId"]) if payload.get("userId") else lead.sdr
    values = render.lead_vars(lead, user)
    return {"leadId": lead.id, "leadName": lead.name,
            "subject": render.render(t.subject, values),
            "body": render.render(t.body, values),
            "missing": render.missing(f"{t.subject}\n{t.body}", values)}


# ── Biblioteca de atividades ──
@router.get("/activities")
def list_activities(type: str | None = None, client_id: int | None = None,
                    q: str | None = None, limit: int = Query(200, le=1000),
                    db: Session = Depends(get_db)):
    query = db.query(Activity)
    if type:
        query = query.filter(Activity.type == type)
    if client_id:
        query = query.filter(Activity.client_id == client_id)
    if q:
        query = query.filter(Activity.name.ilike(f"%{q}%"))
    return [serial.activity(a) for a in query.order_by(Activity.id.desc()).limit(limit)]


@router.post("/activities")
def create_activity(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome da atividade é obrigatório.")
    a = Activity(name=name, type=payload.get("type", "CALL"),
                 social_network=payload.get("socialNetwork", ""),
                 instruction=payload.get("instruction", ""),
                 email_subject=(payload.get("emailTemplate") or {}).get("subject", ""),
                 email_html=(payload.get("emailTemplate") or {}).get("html", ""),
                 client_id=payload.get("clientId"))
    db.add(a)
    db.commit()
    return serial.activity(a)


@router.patch("/activities/{aid}")
def update_activity(aid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    a = db.get(Activity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    for key, attr in [("name", "name"), ("type", "type"), ("instruction", "instruction"),
                      ("socialNetwork", "social_network"), ("clientId", "client_id")]:
        if key in payload:
            setattr(a, attr, payload[key])
    if "emailTemplate" in payload:
        a.email_subject = payload["emailTemplate"].get("subject", "")
        a.email_html = payload["emailTemplate"].get("html", "")
    db.commit()
    return serial.activity(a)


@router.delete("/activities/{aid}")
def delete_activity(aid: int, db: Session = Depends(get_db)):
    a = db.get(Activity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    if db.query(func.count(CadenceStep.id)).filter_by(activity_id=aid).scalar():
        raise HTTPException(400, "Atividade em uso por uma cadência.")
    db.delete(a)
    db.commit()
    return {"ok": True}


# ── Leads ──
def _custom_values(db: Session, lead_id: int) -> dict:
    rows = (db.query(CustomField.identifier, LeadFieldValue.value)
            .join(LeadFieldValue, LeadFieldValue.field_id == CustomField.id)
            .filter(LeadFieldValue.lead_id == lead_id).all())
    return dict(rows)


@router.get("/leads")
def list_leads(status: str | None = None, cadence_id: int | None = None,
               client_id: int | None = None, sdr_id: int | None = None,
               lead_base_id: int | None = None, q: str | None = None,
               page: int = 1, limit: int = Query(50, le=500),
               db: Session = Depends(get_db)):
    query = db.query(Lead)
    if status:
        query = query.filter(Lead.status.in_(status.split(",")))
    if cadence_id:
        query = query.filter(Lead.cadence_id == cadence_id)
    if client_id:
        query = query.filter(Lead.client_id == client_id)
    if sdr_id:
        query = query.filter(Lead.sdr_id == sdr_id)
    if lead_base_id:
        query = query.filter(Lead.lead_base_id == lead_base_id)
    if q:
        like = f"%{q}%"
        query = query.filter(or_(Lead.name.ilike(like), Lead.company.ilike(like),
                                 Lead.email.ilike(like), Lead.cnpj.ilike(like)))
    total = query.count()
    rows = (query.order_by(Lead.id.desc())
            .offset((page - 1) * limit).limit(limit).all())
    return {"data": [serial.lead(l) for l in rows],
            "pagination": {"page": page, "perPage": limit, "totalRowCount": total,
                           "totalPageCount": max(1, -(-total // limit)),
                           "hasPrev": page > 1, "hasNext": page * limit < total}}


@router.get("/leads/{lid}")
def get_lead(lid: int, db: Session = Depends(get_db)):
    l = db.get(Lead, lid)
    if not l:
        raise HTTPException(404, "Lead não encontrado.")
    data = serial.lead(l, _custom_values(db, lid))
    now = datetime.utcnow()
    acts = (db.query(LeadActivity).filter_by(lead_id=lid)
            .order_by(LeadActivity.scheduled_at).all())
    data["timeline"] = [serial.lead_activity(a, now) for a in acts]
    return data


@router.post("/leads")
def create_lead(payload: dict = Body(...), db: Session = Depends(get_db)):
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome do lead é obrigatório.")
    l = _build_lead(db, payload)
    db.add(l)
    db.flush()
    _schedule_cadence(db, l)
    db.commit()
    return serial.lead(l)


def _build_lead(db: Session, row: dict, defaults: dict | None = None) -> Lead:
    d = {**(defaults or {}), **{k: v for k, v in row.items() if v not in (None, "")}}
    name = (d.get("name") or "").strip()
    return Lead(
        name=name, first_name=(d.get("firstName") or name.split(" ")[0] if name else ""),
        email=d.get("email", ""), company=d.get("company", ""),
        position=d.get("position", ""), phone=d.get("phone", ""),
        site=d.get("site", ""), state=d.get("state", ""), city=d.get("city", ""),
        linkedin=d.get("linkedIn", ""), annotations=d.get("annotations", ""),
        external_reference=d.get("externalReference", ""),
        cnpj=str(d.get("cnpj", "")), cpf=str(d.get("cpf", "")),
        razao_social=d.get("razaoSocial", "") or d.get("company", ""),
        cadence_id=d.get("cadenceId"), sdr_id=d.get("sdrId"),
        client_id=d.get("clientId"), lead_base_id=d.get("leadBaseId"),
        best_hour=int(d.get("bestHour", 18)),
        decision_level=int(d.get("decisionLevel") or 0),
        contact_kind=d.get("contactKind", ""), phone_kind=d.get("phoneKind", ""),
        whatsapp=bool(d.get("whatsapp")), do_not_call=bool(d.get("doNotCall")),
        status="WAITING",
    )


def _schedule_cadence(db: Session, lead: Lead) -> int:
    """Agenda as atividades da cadência em dias úteis, no fuso da operação.

    O dia 1 da cadência é o dia da entrada do lead; os demais contam em dias
    úteis, pulando fim de semana e feriado. `scheduled_at` é gravado em UTC.
    """
    if not lead.cadence_id:
        return 0
    cadence = db.get(Cadence, lead.cadence_id)
    if not cadence:
        return 0
    holidays = agenda.holiday_dates(db)
    start = agenda.now_local().date()
    created = 0
    for step in sorted(cadence.steps, key=lambda s: (s.day, s.order_in_day)):
        day = agenda.add_business_days(start, step.day - 1, holidays)
        when = agenda.slot(day, lead.best_hour, holidays)
        db.add(LeadActivity(lead_id=lead.id, activity_id=step.activity_id,
                            cadence_step_id=step.id, user_id=lead.sdr_id,
                            type=step.activity.type,
                            social_network=step.activity.social_network,
                            scheduled_at=agenda.to_utc(when)))
        created += 1
    if created:
        lead.status = "EXECUTING"
    return created


@router.patch("/leads/{lid}")
def update_lead(lid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    l = db.get(Lead, lid)
    if not l:
        raise HTTPException(404, "Lead não encontrado.")
    fields = {"name": "name", "firstName": "first_name", "email": "email",
              "company": "company", "position": "position", "phone": "phone",
              "site": "site", "state": "state", "city": "city", "linkedIn": "linkedin",
              "annotations": "annotations", "cnpj": "cnpj", "cpf": "cpf",
              "razaoSocial": "razao_social", "sdrId": "sdr_id", "clientId": "client_id",
              "bestHour": "best_hour", "cadenceId": "cadence_id",
              "leadBaseId": "lead_base_id", "externalReference": "external_reference",
              "decisionLevel": "decision_level", "whatsapp": "whatsapp",
              "doNotCall": "do_not_call"}
    # Campo que não existe é erro, não silêncio: antes `cadenceId` não estava no
    # mapa e o PATCH devolvia 200 sem ter mudado nada.
    unknown = set(payload) - set(fields) - {"customFields"}
    if unknown:
        raise HTTPException(400, f"Campo desconhecido: {', '.join(sorted(unknown))}")
    if payload.get("cadenceId") and not db.get(Cadence, payload["cadenceId"]):
        raise HTTPException(400, "Cadência inexistente.")
    for key, attr in fields.items():
        if key in payload:
            setattr(l, attr, payload[key])
    for ident, value in (payload.get("customFields") or {}).items():
        f = db.query(CustomField).filter_by(identifier=ident).first()
        if not f:
            continue
        v = db.query(LeadFieldValue).filter_by(lead_id=lid, field_id=f.id).first()
        if v:
            v.value = str(value)
        else:
            db.add(LeadFieldValue(lead_id=lid, field_id=f.id, value=str(value)))
    db.commit()
    return serial.lead(l, _custom_values(db, lid))


@router.post("/leads/bulk")
def bulk_action(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Ações em massa da lista de leads (transferir, trocar cadência, perder, apagar)."""
    ids = payload.get("leadIds") or []
    action = payload.get("action")
    if not ids or not action:
        raise HTTPException(400, "Informe leadIds e action.")
    leads = db.query(Lead).filter(Lead.id.in_(ids)).all()
    if action == "transfer":
        uid = payload.get("sdrId")
        if not db.get(User, uid):
            raise HTTPException(400, "SDR inválido.")
        for l in leads:
            l.sdr_id = uid
        db.query(LeadActivity).filter(LeadActivity.lead_id.in_(ids),
                                      LeadActivity.status == "PENDING").update(
            {"user_id": uid}, synchronize_session=False)
    elif action == "switch_cadence":
        cid = payload.get("cadenceId")
        if not db.get(Cadence, cid):
            raise HTTPException(400, "Cadência inválida.")
        for l in leads:
            db.query(LeadActivity).filter_by(lead_id=l.id, status="PENDING").delete()
            l.cadence_id = cid
            l.current_step = 0
            l.status = "SWITCHED_CADENCE"
            db.flush()
            _schedule_cadence(db, l)
    elif action == "back_to_waiting":
        for l in leads:
            db.query(LeadActivity).filter_by(lead_id=l.id, status="PENDING").delete()
            l.status = "WAITING"
    elif action == "lost":
        reason_id = payload.get("lostReasonId")
        for l in leads:
            l.status = "LOST"
            l.lost_at = datetime.utcnow()
            l.lost_reason_id = reason_id
            db.query(LeadActivity).filter_by(lead_id=l.id, status="PENDING").update(
                {"status": "SKIPPED", "done_at": datetime.utcnow()})
    elif action == "delete":
        db.query(LeadActivity).filter(LeadActivity.lead_id.in_(ids)).delete(
            synchronize_session=False)
        db.query(Lead).filter(Lead.id.in_(ids)).delete(synchronize_session=False)
    else:
        raise HTTPException(400, f"Ação desconhecida: {action}")
    db.commit()
    return {"ok": True, "affected": len(ids), "action": action}


@router.post("/leads/{lid}/start")
def start_lead(lid: int, payload: dict = Body(default={}), db: Session = Depends(get_db)):
    l = db.get(Lead, lid)
    if not l:
        raise HTTPException(404, "Lead não encontrado.")
    if payload.get("cadenceId"):
        l.cadence_id = payload["cadenceId"]
    if payload.get("sdrId"):
        l.sdr_id = payload["sdrId"]
    if not l.cadence_id:
        raise HTTPException(400, "Escolha uma cadência antes de iniciar a execução.")
    db.query(LeadActivity).filter_by(lead_id=lid, status="PENDING").delete()
    l.current_step = 0
    created = _schedule_cadence(db, l)
    db.commit()
    return {"ok": True, "scheduled": created, "lead": serial.lead(l)}


# ── Bases de leads ──
@router.get("/lead-bases")
def list_bases(client_id: int | None = None, source: str | None = None,
               db: Session = Depends(get_db)):
    query = db.query(LeadBase)
    if client_id:
        query = query.filter(LeadBase.client_id == client_id)
    if source:
        query = query.filter(LeadBase.source == source)
    rows = query.order_by(LeadBase.created_at.desc()).all()
    return {"data": [serial.lead_base(b) for b in rows],
            "pagination": {"page": 1, "perPage": len(rows), "totalRowCount": len(rows)}}


@router.get("/lead-bases/{bid}")
def get_base(bid: int, db: Session = Depends(get_db)):
    b = db.get(LeadBase, bid)
    if not b:
        raise HTTPException(404, "Base não encontrada.")
    data = serial.lead_base(b)
    data["leads"] = [serial.lead(l) for l in
                     db.query(Lead).filter_by(lead_base_id=bid).limit(500)]
    return data


@router.post("/lead-bases/preview")
async def preview_csv(file: UploadFile = File(...)):
    """Passo 1 do wizard: lê o CSV e devolve colunas + amostra."""
    raw = (await file.read()).decode("utf-8-sig", errors="replace")
    sample = raw[:4096]
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delim = dialect.delimiter
    except csv.Error:
        delim = ";" if sample.count(";") > sample.count(",") else ","
    reader = csv.DictReader(io.StringIO(raw), delimiter=delim)
    rows = [r for _, r in zip(range(20), reader)]
    return {"filename": file.filename, "delimiter": delim,
            "columns": reader.fieldnames or [], "sample": rows,
            "content": raw if len(raw) < 2_000_000 else ""}


@router.post("/lead-bases/import")
def import_base(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Passo 2 do wizard: cria a base a partir do CSV com o mapa de colunas."""
    name = (payload.get("name") or "").strip()
    content = payload.get("content") or ""
    mapping = payload.get("mapping") or {}
    if not name or not content:
        raise HTTPException(400, "Informe o nome da base e o conteúdo do arquivo.")
    delim = payload.get("delimiter") or ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delim)

    base = LeadBase(name=name, source="CSV", client_id=payload.get("clientId"),
                    created_by_id=payload.get("createdById"), status="PROCESSING")
    db.add(base)
    db.flush()

    defaults = {"cadenceId": payload.get("cadenceId"), "sdrId": payload.get("sdrId"),
                "clientId": payload.get("clientId"), "leadBaseId": base.id}
    imported = discarded = 0
    for raw in reader:
        row = {field: (raw.get(col) or "").strip()
               for field, col in mapping.items() if col}
        if not row.get("name"):
            discarded += 1
            continue
        lead = _build_lead(db, row, defaults)
        lead.lead_base_id = base.id
        db.add(lead)
        db.flush()
        if payload.get("cadenceId"):
            _schedule_cadence(db, lead)
        imported += 1
    base.number_of_leads = imported
    base.discarded_leads = discarded
    base.status = "COMPLETED"
    db.commit()
    return {"leadBase": serial.lead_base(base), "imported": imported, "discarded": discarded}


@router.delete("/lead-bases/{bid}")
def delete_base(bid: int, db: Session = Depends(get_db)):
    b = db.get(LeadBase, bid)
    if not b:
        raise HTTPException(404, "Base não encontrada.")
    if db.query(func.count(Lead.id)).filter_by(lead_base_id=bid).scalar():
        raise HTTPException(400, "A base tem leads vinculados.")
    db.delete(b)
    db.commit()
    return {"ok": True}


# ── Execução: a fila do SDR ──
@router.get("/execution/queue")
def queue(sdr_id: int | None = None, client_id: int | None = None,
          cadence_id: int | None = None, type: str | None = None,
          limit: int = Query(60, le=300), db: Session = Depends(get_db)):
    """Fila priorizada. Ordena por atraso × prioridade × janela de melhor contato —
    em vez da ordem cronológica pura do Meetime."""
    now = datetime.utcnow()
    query = (db.query(LeadActivity).join(Lead, LeadActivity.lead_id == Lead.id)
             .filter(LeadActivity.status == "PENDING",
                     Lead.status.in_(["EXECUTING", "WAITING", "ON_EXTRA_ACTIVITY"]),
                     LeadActivity.scheduled_at <= now + timedelta(days=1)))
    if sdr_id:
        query = query.filter(LeadActivity.user_id == sdr_id)
    if client_id:
        query = query.filter(Lead.client_id == client_id)
    if cadence_id:
        query = query.filter(Lead.cadence_id == cadence_id)
    if type:
        query = query.filter(LeadActivity.type == type)
    items = query.all()
    scored = sorted(items, key=lambda a: serial.queue_score(a, now), reverse=True)[:limit]
    out = []
    for a in scored:
        row = serial.lead_activity(a, now)
        row["score"] = serial.queue_score(a, now)
        out.append(row)
    late = sum(1 for a in items if a.scheduled_at < now)
    return {"data": out, "meta": {"total": len(items), "late": late,
                                  "onTime": len(items) - late,
                                  "generatedAt": serial.iso(now)}}


@router.post("/execution/activities/{aid}/execute")
def execute_activity(aid: int, payload: dict = Body(default={}),
                     db: Session = Depends(get_db)):
    a = db.get(LeadActivity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    if a.status != "PENDING":
        raise HTTPException(400, "Atividade já finalizada.")
    a.status = "SKIPPED" if payload.get("skip") else "DONE"
    a.done_at = datetime.utcnow()
    if payload.get("notes"):                 # não apaga anotação ao executar sem texto
        a.notes = payload["notes"]
    lead = a.lead
    lead.current_step += 1
    if lead.status == "WAITING":
        lead.status = "EXECUTING"

    # Regra de avanço: o lead respondeu, então a sequência automática para.
    # Continuar disparando e-mail de cadência para quem já está conversando com
    # o SDR é o jeito mais rápido de queimar o lead.
    paused = 0
    if payload.get("replied"):
        # `LeadActivity.id != aid` porque a atividade recém-executada ainda não
        # foi para o banco: sem isso ela entraria na contagem das pausadas.
        paused = (db.query(LeadActivity)
                  .filter(LeadActivity.lead_id == lead.id,
                          LeadActivity.id != aid,
                          LeadActivity.status == "PENDING")
                  .update({"status": "PAUSED"}, synchronize_session=False))
        lead.status = "ON_EXTRA_ACTIVITY"
    db.commit()
    return {"ok": True, "pausedActivities": paused,
            "activity": serial.lead_activity(a, datetime.utcnow()),
            "lead": serial.lead(lead)}


@router.post("/execution/leads/{lid}/resume")
def resume_cadence(lid: int, payload: dict = Body(default={}),
                   db: Session = Depends(get_db)):
    """Retoma a cadência pausada pela resposta do lead.

    As atividades que sobraram são reagendadas a partir de hoje — remontar no
    calendário original devolveria tudo já vencido.
    """
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    paused = (db.query(LeadActivity)
              .filter(LeadActivity.lead_id == lid, LeadActivity.status == "PAUSED")
              .order_by(LeadActivity.scheduled_at).all())
    if not paused:
        raise HTTPException(400, "Esse lead não tem atividade pausada.")

    holidays = agenda.holiday_dates(db)
    start = agenda.now_local().date()
    # Preserva o espaçamento original entre as etapas, recontado a partir de hoje.
    first = paused[0].scheduled_at.date()
    for act in paused:
        gap = (act.scheduled_at.date() - first).days
        day = agenda.add_business_days(start, gap, holidays)
        act.scheduled_at = agenda.to_utc(agenda.slot(day, lead.best_hour, holidays))
        act.status = "PENDING"
    lead.status = "EXECUTING"
    db.commit()
    return {"ok": True, "resumed": len(paused),
            "nextAt": serial.iso(paused[0].scheduled_at)}


@router.post("/execution/leads/{lid}/outcome")
def lead_outcome(lid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Ganho ou perda — encerra a execução e limpa a fila do lead."""
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    outcome = payload.get("outcome")
    now = datetime.utcnow()
    if outcome == "WON":
        lead.status, lead.won_at = "WON", now
    elif outcome == "LOST":
        reason_id = payload.get("lostReasonId")
        if reason_id and not db.get(LostReason, reason_id):
            raise HTTPException(400, "Motivo de perda inválido.")
        lead.status, lead.lost_at, lead.lost_reason_id = "LOST", now, reason_id
    else:
        raise HTTPException(400, "outcome deve ser WON ou LOST.")
    if payload.get("annotations"):
        lead.annotations = payload["annotations"]
    db.query(LeadActivity).filter_by(lead_id=lid, status="PENDING").update(
        {"status": "SKIPPED", "done_at": now})
    db.commit()
    _fire_webhooks(db, f"LEAD.{outcome}", serial.lead(lead))
    return {"ok": True, "lead": serial.lead(lead)}


@router.post("/execution/activities/{aid}/reschedule")
def reschedule(aid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    a = db.get(LeadActivity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    try:
        wanted = datetime.fromisoformat(payload["scheduledAt"].replace("Z", ""))
    except (KeyError, ValueError):
        raise HTTPException(400, "scheduledAt inválido.")
    # Chega em UTC; a janela útil é local. Sem isso dava para reagendar uma
    # ligação para domingo às 3h da manhã.
    local = agenda.next_open(agenda.to_local(wanted), agenda.holiday_dates(db))
    a.scheduled_at = agenda.to_utc(local)
    a.status = "PENDING"
    db.commit()
    return {**serial.lead_activity(a, datetime.utcnow()),
            "adjusted": local != agenda.to_local(wanted),
            "scheduledLocal": local.isoformat(timespec="minutes")}


def _fire_webhooks(db: Session, event: str, data: dict) -> None:
    """Entrega best-effort — um webhook fora do ar não pode derrubar a operação."""
    import httpx
    from ..models import Webhook
    hooks = db.query(Webhook).filter(Webhook.enabled,
                                     Webhook.events.contains(event.split(".")[0])).all()
    for h in hooks:
        if event not in h.events.split(","):
            continue
        try:
            httpx.post(h.target_url, json={"event": event, "data": data},
                       headers={"X-Bluutime-Secret": h.secret}, timeout=5)
        except Exception:
            pass
