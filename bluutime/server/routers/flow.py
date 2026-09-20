"""Prospecção: cadências, atividades, leads, bases e a fila de execução."""
import csv
import io
import json
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query, UploadFile, File
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from fastapi.responses import StreamingResponse

from ..db import get_db
from ..models import (Activity, Cadence, CadenceStep, CadenceUser, Call, Client,
                      Company, Conversation, CustomField, Delivery, FitscoreRule,
                      CadenceRun, Lead, LeadActivity,
                      LeadBase, LeadFeedback, LeadFieldValue, LostReason, Message,
                      Template, User, ACTIVITY_TYPES, channel_of)
from .. import agenda, perm, render, serial, webhooks

router = APIRouter(prefix="/api/flow")


def _erros_de_entrega(db: Session, cadence_id: int) -> int:
    """Entregas que não saíram, dos leads desta cadência.

    É o badge de erro da tabela do original. Aqui o erro que existe de verdade
    é a entrega bloqueada ou falha — não há execução de passo que estoure
    sozinha.
    """
    return (db.query(func.count(Delivery.id))
            .join(Lead, Delivery.lead_id == Lead.id)
            .filter(Lead.cadence_id == cadence_id,
                    Delivery.status.in_(["BLOCKED", "FAILED", "ERROR"]))
            .scalar() or 0)


def _overview(db: Session, cadence_id: int) -> dict:
    rows = (db.query(Lead.status, func.count(Lead.id))
            .filter(Lead.cadence_id == cadence_id).group_by(Lead.status).all())
    counts = dict(rows)
    return {"total": sum(counts.values()),
            "errosEntrega": _erros_de_entrega(db, cadence_id),
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
    perm.ator(db).exigir("gestor", "criar cadência")
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
    perm.ator(db).exigir("gestor", "alterar cadência")
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
    perm.ator(db).exigir("gestor", "excluir cadência")
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
    perm.ator(db).exigir("gestor", "editar etapa de cadência")
    if not db.get(Cadence, cid):
        raise HTTPException(404, "Cadência não encontrada.")
    activity_id = payload.get("activityId")
    if not activity_id or not db.get(Activity, activity_id):
        raise HTTPException(400, "Atividade inválida.")
    day = int(payload.get("day", 1))
    order = (db.query(func.count(CadenceStep.id))
             .filter_by(cadence_id=cid, day=day).scalar() or 0) + 1
    template_id = payload.get("templateId")
    if template_id:
        tpl = db.get(Template, template_id)
        if not tpl:
            raise HTTPException(400, "Modelo de mensagem inválido.")
        # Sem esta checagem dava para pendurar um modelo de WhatsApp num passo
        # de e-mail — e só se descobria quando a mensagem saísse errada.
        act = db.get(Activity, activity_id)
        canal = channel_of(act.type, act.social_network)
        if tpl.channel != canal:
            raise HTTPException(
                400, f"O modelo é de {tpl.channel} e o passo é de {canal}.")
    s = CadenceStep(cadence_id=cid, activity_id=activity_id, day=day,
                    order_in_day=order, template_id=template_id)
    db.add(s)
    db.commit()
    return serial.cadence_step(s)


@router.delete("/cadences/{cid}/steps/{sid}")
def delete_step(cid: int, sid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "editar etapa de cadência")
    s = db.get(CadenceStep, sid)
    if s and s.cadence_id == cid:
        db.delete(s)
        db.commit()
    return {"ok": True}


# ── Modelos de mensagem ──
# Canal de modelo: os que carregam texto (SEARCH e CALL não têm corpo).
TEMPLATE_CHANNELS = {"EMAIL", "WHATSAPP", "SOCIAL"}


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
    perm.ator(db).exigir("gestor", "criar modelo de mensagem")
    channel = (payload.get("channel") or "EMAIL").upper()
    if channel not in TEMPLATE_CHANNELS:
        raise HTTPException(400, f"Canal inválido. Use: {', '.join(sorted(TEMPLATE_CHANNELS))}")
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
    perm.ator(db).exigir("gestor", "alterar modelo de mensagem")
    t = db.get(Template, tid)
    if not t:
        raise HTTPException(404, "Modelo não encontrado.")
    for key, attr in {"name": "name", "subject": "subject", "body": "body",
                      "clientId": "client_id", "active": "active"}.items():
        if key in payload:
            setattr(t, attr, payload[key])
    if "channel" in payload:
        if payload["channel"].upper() not in TEMPLATE_CHANNELS:
            raise HTTPException(400, "Canal inválido.")
        t.channel = payload["channel"].upper()
    db.commit()
    return _template(t)


@router.delete("/templates/{tid}")
def delete_template(tid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "excluir modelo de mensagem")
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
    ator = perm.ator(db)
    if payload.get("leadId"):
        lead = db.get(Lead, payload["leadId"])
        perm.exigir_dono_lead(db, ator, lead)
    else:
        # Sem leadId, cai no lead mais recente — mas o mais recente DA
        # CARTEIRA de quem pediu, não da empresa inteira (senão a prévia
        # virava um jeito de espiar o cadastro de um lead alheio).
        query = db.query(Lead)
        if not ator.pelo_menos("gestor"):
            empresa = db.query(Company).first()
            if not (empresa and empresa.leads_visible_all):
                query = query.filter(Lead.sdr_id == (ator.user_id or -1))
        lead = query.order_by(Lead.id.desc()).first()
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
    perm.ator(db).exigir("gestor", "criar atividade")
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
    perm.ator(db).exigir("gestor", "alterar atividade")
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
    perm.ator(db).exigir("gestor", "excluir atividade")
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


def _gravar_campos(db: Session, lead_id: int, valores: dict | None) -> None:
    """Grava valores de campo personalizado por IDENTIFICADOR.

    Campo que não existe é ignorado em silêncio de propósito: o payload vem de
    importação e de formulário, e derrubar a criação inteira de um lead por
    causa de uma chave a mais seria pior que guardar o que dá.
    """
    for ident, value in (valores or {}).items():
        f = db.query(CustomField).filter_by(identifier=ident).first()
        if not f:
            continue
        v = db.query(LeadFieldValue).filter_by(lead_id=lead_id, field_id=f.id).first()
        if v:
            v.value = str(value)
        else:
            db.add(LeadFieldValue(lead_id=lead_id, field_id=f.id, value=str(value)))


def _campos_faltando(db: Session, lead_id: int, campo_obrigatorio: str) -> list[str]:
    """Nomes dos campos personalizados marcados como obrigatórios (ganho ou
    perda, conforme `campo_obrigatorio`) que este lead ainda não preencheu."""
    campos = db.query(CustomField).filter(
        getattr(CustomField, campo_obrigatorio).is_(True)).all()
    if not campos:
        return []
    valores = _custom_values(db, lead_id)
    return [c.name for c in campos if not (valores.get(c.identifier) or "").strip()]


def _fitscore_ligado(db: Session) -> bool:
    empresa = db.query(Company).first()
    return bool(empresa.fitscore_enabled) if empresa else True


def _fitscore(db: Session, custom: dict) -> int:
    """Soma os pontos das regras de fitscore que baterem no lead.

    LIKE é "contém" (case-insensitive); EQUALS é igual exato. `custom` já vem
    indexado por identifier (mesmo formato de `_custom_values`)."""
    if not _fitscore_ligado(db):
        return 0
    total = 0
    regras = (db.query(FitscoreRule, CustomField.identifier)
              .join(CustomField, FitscoreRule.field_id == CustomField.id).all())
    for regra, ident in regras:
        valor = str(custom.get(ident, "") or "")
        alvo = regra.target_value or ""
        bateu = (alvo.lower() in valor.lower()) if regra.expression_type == "LIKE" else (valor == alvo)
        if bateu:
            total += regra.score
    return total


def _fitscore_bulk(db: Session, lead_ids: list[int]) -> dict[int, int]:
    """Mesma conta que `_fitscore`, mas pra uma página inteira de leads de
    uma vez — sem isso, a lista faria uma consulta de regras por linha."""
    if not lead_ids or not _fitscore_ligado(db):
        return {}
    regras = (db.query(FitscoreRule, CustomField.identifier)
              .join(CustomField, FitscoreRule.field_id == CustomField.id).all())
    if not regras:
        return {}
    valores = (db.query(LeadFieldValue.lead_id, CustomField.identifier, LeadFieldValue.value)
              .join(CustomField, LeadFieldValue.field_id == CustomField.id)
              .filter(LeadFieldValue.lead_id.in_(lead_ids)).all())
    por_lead: dict[int, dict] = {}
    for lead_id, ident, valor in valores:
        por_lead.setdefault(lead_id, {})[ident] = valor
    out = {}
    for lid in lead_ids:
        custom = por_lead.get(lid, {})
        total = 0
        for regra, ident in regras:
            valor = str(custom.get(ident, "") or "")
            alvo = regra.target_value or ""
            bateu = (alvo.lower() in valor.lower()) if regra.expression_type == "LIKE" else (valor == alvo)
            if bateu:
                total += regra.score
        out[lid] = total
    return out


def _csv(nome: str, cabecalho: list[str], linhas: list[list]) -> StreamingResponse:
    buf = io.StringIO()
    escritor = csv.writer(buf, delimiter=";")
    escritor.writerow(cabecalho)
    escritor.writerows(linhas)
    buf.seek(0)
    # utf-8-sig porque o Excel pt-BR abre utf-8 puro com acento quebrado.
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]),
                             media_type="text/csv",
                             headers={"Content-Disposition": f'attachment; filename="{nome}"'})


def _campo_etapa(db: Session) -> CustomField | None:
    """O campo personalizado eleito como etapa do lead, se houver.

    O Meetime não tem tabela de etapa: ele elege UM campo personalizado e usa
    as opções dele como as etapas do funil. Copiar isso é mais barato e evita
    um segundo lugar para cadastrar a mesma lista.
    """
    empresa = db.query(Company).first()
    fid = getattr(empresa, "lead_stage_field_id", None) if empresa else None
    return db.get(CustomField, fid) if fid else None


def etapas_do_funil(db: Session, campo: CustomField | None) -> list[dict]:
    """Cada opção do campo eleito com quantos leads estão nela."""
    if not campo:
        return []
    contagem = dict(db.query(LeadFieldValue.value, func.count(LeadFieldValue.id))
                    .filter(LeadFieldValue.field_id == campo.id)
                    .group_by(LeadFieldValue.value).all())
    return [{"label": o, "count": contagem.get(o, 0)}
            for o in (campo.options or "").splitlines() if o.strip()]


@router.get("/leads")
def list_leads(status: str | None = None, cadence_id: int | None = None,
               client_id: int | None = None, sdr_id: int | None = None,
               lead_base_id: int | None = None, q: str | None = None,
               stage: str | None = None,
               field_id: int | None = None, field_op: str = "EQUALS",
               field_value: str | None = None,
               page: int = 1, limit: int = Query(50, le=500),
               db: Session = Depends(get_db)):
    # SDR vê só a própria carteira; gestor e admin veem tudo. Antes disso,
    # qualquer conta listava os leads da empresa inteira.
    query = perm.escopo_leads(db, db.query(Lead), perm.ator(db), Lead.sdr_id)
    campo_etapa = _campo_etapa(db)
    if stage and campo_etapa:
        query = query.filter(Lead.id.in_(
            db.query(LeadFieldValue.lead_id)
            .filter(LeadFieldValue.field_id == campo_etapa.id,
                    LeadFieldValue.value == stage)))
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
    # Filtro por campo personalizado — o `mt-custom-filter` do original, que a
    # lista de Leads reusa. Mesmo vocabulário das regras de fitscore.
    if field_id and field_value:
        alvo = db.query(LeadFieldValue.lead_id).filter(LeadFieldValue.field_id == field_id)
        alvo = (alvo.filter(LeadFieldValue.value.ilike(f"%{field_value}%"))
                if field_op == "LIKE" else alvo.filter(LeadFieldValue.value == field_value))
        query = query.filter(Lead.id.in_(alvo))
    total = query.count()
    rows = (query.order_by(Lead.id.desc())
            .offset((page - 1) * limit).limit(limit).all())
    scores = _fitscore_bulk(db, [l.id for l in rows])
    return {"data": [serial.lead(l, fitscore=scores.get(l.id, 0)) for l in rows],
            "stageField": ({"id": campo_etapa.id, "name": campo_etapa.name,
                            "identifier": campo_etapa.identifier} if campo_etapa else None),
            "stages": etapas_do_funil(db, campo_etapa),
            "pagination": {"page": page, "perPage": limit, "totalRowCount": total,
                           "totalPageCount": max(1, -(-total // limit)),
                           "hasPrev": page > 1, "hasNext": page * limit < total}}


@router.get("/lead-stages")
def lead_stages(db: Session = Depends(get_db)):
    """Qual campo é a etapa e quais são as opções — a página do lead precisa
    disso mesmo quando aberta direto pela URL, sem passar pela lista."""
    campo = _campo_etapa(db)
    if not campo:
        return {"field": None, "options": []}
    return {"field": {"id": campo.id, "name": campo.name, "identifier": campo.identifier},
            "options": [o.strip() for o in (campo.options or "").splitlines() if o.strip()]}


@router.put("/leads/{lid}/stage")
def set_lead_stage(lid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Move o lead de etapa — grava no campo eleito, não num campo próprio."""
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    perm.exigir_dono_lead(db, perm.ator(db), lead)
    campo = _campo_etapa(db)
    if not campo:
        raise HTTPException(400, "Nenhum campo personalizado está definido como etapa do lead.")
    etapa = (payload.get("stage") or "").strip()
    validas = [o.strip() for o in (campo.options or "").splitlines() if o.strip()]
    if etapa and etapa not in validas:
        raise HTTPException(400, f"Etapa desconhecida: {etapa}.")
    linha = (db.query(LeadFieldValue)
             .filter_by(lead_id=lid, field_id=campo.id).first())
    if linha:
        linha.value = etapa
    else:
        db.add(LeadFieldValue(lead_id=lid, field_id=campo.id, value=etapa))
    db.commit()
    return {"ok": True, "stage": etapa}


@router.post("/leads/{lid}/activities")
def create_extra_activity(lid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Agenda uma atividade avulsa no lead — a aba "Agendar atividade" do
    original.

    Não precisa de campo novo: atividade SEM `cadence_step_id` já é, por
    construção, atividade fora da cadência. Inventar um "scope" duplicaria
    uma informação que a própria ausência do passo já dá.
    """
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    ator = perm.ator(db)
    perm.exigir_dono_lead(db, ator, lead)

    tipo = (payload.get("type") or "").strip().upper()
    if tipo not in ACTIVITY_TYPES:
        raise HTTPException(400, f"Tipo inválido. Use um de: {', '.join(ACTIVITY_TYPES)}.")
    quando = payload.get("scheduledAt")
    try:
        agendada = datetime.fromisoformat(quando) if quando else datetime.utcnow()
    except ValueError:
        raise HTTPException(400, "Data inválida.")

    modelo_id = payload.get("activityId")
    if modelo_id and not db.get(Activity, modelo_id):
        raise HTTPException(400, "Atividade da biblioteca não encontrada.")

    # "Já aconteceu" nasce concluída: registrar uma reunião de ontem como
    # pendente colocaria na fila de hoje uma coisa que ninguém precisa fazer.
    feita = bool(payload.get("done"))
    a = LeadActivity(lead_id=lid, activity_id=modelo_id, cadence_step_id=None,
                     user_id=lead.sdr_id or ator.user_id, type=tipo,
                     social_network=payload.get("socialNetwork", ""),
                     status="DONE" if feita else "PENDING", scheduled_at=agendada,
                     done_at=agendada if feita else None,
                     notes=(payload.get("notes") or "").strip())
    db.add(a)
    # Reunião registrada responde metade do feedback de oportunidade: se há um
    # pendente sem data, a data passa a ser esta em vez de ficar em branco.
    if feita and tipo == "MEETING":
        fb = (db.query(LeadFeedback)
              .filter(LeadFeedback.lead_id == lid, LeadFeedback.meeting_at.is_(None))
              .order_by(LeadFeedback.created_at.desc()).first())
        if fb:
            fb.meeting_at = agendada
    # Lead parado com atividade marcada volta a contar como em prospecção —
    # senão ele sumiria da fila justamente depois de alguém agendar algo.
    if lead.status == "WAITING" and not feita:
        lead.status = "EXECUTING"
    db.commit()
    return serial.lead_activity(a, datetime.utcnow())


@router.get("/execution/overall")
def execution_overall(db: Session = Depends(get_db)):
    """Meu progresso de hoje — o `executionOverall` do original.

    Responde três perguntas que a fila sozinha não responde: quantos leads eu
    estou tocando, quantos ainda dá para puxar, e quanto já andei da meta.
    """
    ator = perm.ator(db)
    hoje = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)

    meus = perm.escopo_leads(db, db.query(Lead), ator, Lead.sdr_id)
    por_situacao = dict(meus.with_entities(Lead.status, func.count(Lead.id))
                        .group_by(Lead.status).all())
    prospectando = por_situacao.get("EXECUTING", 0) + por_situacao.get("ON_EXTRA_ACTIVITY", 0)

    # Disponíveis: em espera E sem cadência começada — é o que o botão
    # "iniciar novos leads" consegue de fato puxar.
    disponiveis = meus.filter(Lead.status == "WAITING").count()

    feitas = db.query(func.count(LeadActivity.id)).filter(
        LeadActivity.user_id == (ator.user_id or -1),
        LeadActivity.status == "DONE", LeadActivity.done_at >= hoje).scalar()
    ignoradas = db.query(func.count(LeadActivity.id)).filter(
        LeadActivity.user_id == (ator.user_id or -1),
        LeadActivity.status == "SKIPPED", LeadActivity.done_at >= hoje).scalar()
    porTipo = dict(db.query(LeadActivity.type, func.count(LeadActivity.id)).filter(
        LeadActivity.user_id == (ator.user_id or -1),
        LeadActivity.status == "DONE", LeadActivity.done_at >= hoje)
        .group_by(LeadActivity.type).all())

    usuario = db.get(User, ator.user_id) if ator.user_id else None
    meta = (usuario.daily_goal if usuario else 0) or 0
    return {"prospectando": prospectando, "disponiveis": disponiveis,
            "ganhos": por_situacao.get("WON", 0), "perdidos": por_situacao.get("LOST", 0),
            "hoje": {"feitas": feitas, "ignoradas": ignoradas, "meta": meta,
                     "percentual": round(feitas / meta * 100, 1) if meta else 0,
                     "porTipo": porTipo},
            "bateuMeta": bool(meta and feitas >= meta)}


@router.get("/hot-leads")
def hot_leads(limit: int = Query(20, le=100), db: Session = Depends(get_db)):
    """Leads esperando a PRIMEIRA ligação — o painel `mtHotLeads` do original.

    O critério é literal: lead em prospecção que ainda não tem nenhuma ligação
    registrada. Quanto mais tempo desde a entrada, mais no topo — lead novo
    esfria rápido, e é justamente essa fila que a tela existe para furar.
    """
    ator = perm.ator(db)
    q = perm.escopo_leads(db, db.query(Lead), ator, Lead.sdr_id)
    q = q.filter(Lead.status.in_(["WAITING", "EXECUTING"]),
                 ~Lead.id.in_(db.query(Call.lead_id).filter(Call.lead_id.isnot(None))),
                 Lead.phone != "")
    linhas = q.order_by(Lead.created_at).limit(limit).all()
    agora = datetime.utcnow()
    return {"data": [{**serial.lead(l),
                      "horasEsperando": round((agora - l.created_at).total_seconds() / 3600, 1)
                      if l.created_at else None}
                     for l in linhas]}


@router.get("/leads/export")
def export_leads(status: str | None = None, cadence_id: int | None = None,
                 client_id: int | None = None, sdr_id: int | None = None,
                 lead_base_id: int | None = None, q: str | None = None,
                 stage: str | None = None, field_id: int | None = None,
                 field_op: str = "EQUALS", field_value: str | None = None,
                 db: Session = Depends(get_db)):
    """Exporta a LISTA FILTRADA, não a base inteira.

    Já existia um relatório `leads` que despeja tudo; o que faltava — e é o
    que o botão Exportar da lista do original faz — é levar embora exatamente
    o recorte que está na tela. Exportar 20 mil linhas quando a pessoa filtrou
    30 não é a mesma funcionalidade.
    """
    resultado = list_leads(status=status, cadence_id=cadence_id, client_id=client_id,
                           sdr_id=sdr_id, lead_base_id=lead_base_id, q=q, stage=stage,
                           field_id=field_id, field_op=field_op, field_value=field_value,
                           page=1, limit=20000, db=db)
    linhas = [[l["id"], l["name"], l["company"], l["cnpj"], l["email"], l["phone"],
               l["city"], l["state"], l["status"],
               (l["cadence"] or {}).get("name", ""), (l["client"] or {}).get("name", ""),
               (l["sdr"] or {}).get("name", ""), (l["leadBase"] or {}).get("name", ""),
               l["fitscore"], (l["createdAt"] or "")[:10]]
              for l in resultado["data"]]
    return _csv(f"leads-{datetime.utcnow():%Y%m%d}.csv",
                ["ID", "Nome", "Empresa", "CNPJ", "E-mail", "Telefone", "Cidade", "UF",
                 "Situação", "Cadência", "Cliente", "SDR", "Base", "Fit score", "Criado em"],
                linhas)


@router.get("/leads/{lid}")
def get_lead(lid: int, db: Session = Depends(get_db)):
    l = db.get(Lead, lid)
    if not l:
        raise HTTPException(404, "Lead não encontrado.")
    perm.exigir_dono_lead(db, perm.ator(db), l)
    custom = _custom_values(db, lid)
    data = serial.lead(l, custom, _fitscore(db, custom))
    now = datetime.utcnow()
    acts = (db.query(LeadActivity).filter_by(lead_id=lid)
            .order_by(LeadActivity.scheduled_at).all())
    linha = [serial.lead_activity(a, now) for a in acts]
    # A ligação mora em `Call`, não em `LeadActivity` — sem isto o histórico do
    # lead mostrava a atividade "Ligar" agendada e nunca a ligação que aconteceu.
    for c in db.query(Call).filter_by(lead_id=lid).all():
        linha.append({"kind": "CALL", **serial.call(c)})
    # A entrega conta o que a atividade não conta: se saiu, se foi bloqueada e
    # por quê, e se o lead abriu ou clicou. Sem isto, "mandei o e-mail" e "o
    # e-mail chegou" eram a mesma linha na tela.
    for d in db.query(Delivery).filter(Delivery.lead_id == lid).all():
        linha.append({"kind": "DELIVERY", "id": d.id, "channel": d.channel,
                      "status": d.status, "subject": d.subject, "to": d.to_address,
                      "error": d.error, "openedAt": serial.iso(d.opened_at),
                      "clickedAt": serial.iso(d.clicked_at),
                      "openCount": d.open_count, "clickCount": d.click_count,
                      "createdAt": serial.iso(d.created_at)})
    linha.sort(key=lambda r: r.get("originStarted") or r.get("createdAt")
               or r.get("doneAt") or r.get("scheduledAt") or "")
    data["timeline"] = linha
    # Prospecções: cada passagem do lead por uma cadência, para a linha do
    # tempo agrupar por elas em vez de virar uma lista corrida.
    data["prospeccoes"] = [
        {"id": r.id, "cadencia": r.cadence.name if r.cadence else "Sem cadência",
         "inicio": serial.iso(r.started_at), "fim": serial.iso(r.ended_at),
         "desfecho": r.outcome, "user": serial.user_min(r.user)}
        for r in (db.query(CadenceRun).filter(CadenceRun.lead_id == lid)
                  .order_by(CadenceRun.started_at).all())]

    # Contadores da sidebar do original: o que já foi feito, quantos e-mails o
    # lead abriu e se há conversa. Antes a coluna só repetia o cadastro.
    entregas = db.query(Delivery).filter(Delivery.lead_id == lid,
                                         Delivery.channel == "EMAIL").all()
    proxima = next((a for a in acts if a.status == "PENDING"), None)
    data["contadores"] = {
        "concluidas": sum(1 for a in acts if a.status == "DONE"),
        "pendentes": sum(1 for a in acts if a.status == "PENDING"),
        "ligacoes": db.query(func.count(Call.id)).filter(Call.lead_id == lid).scalar(),
        "emailsEnviados": sum(1 for d in entregas if d.status in ("SENT", "SIMULATED")),
        "emailsAbertos": sum(1 for d in entregas if d.opened_at),
        "conversas": db.query(func.count(Conversation.id))
                       .filter(Conversation.lead_id == lid).scalar(),
        "proximaAtividade": serial.iso(proxima.scheduled_at) if proxima else None,
        # Início agendado e perda automática prevista: o lead some da fila
        # sozinho quando a última atividade da cadência é executada, e ninguém
        # via essa data chegando.
        "inicioAgendado": serial.iso(acts[0].scheduled_at) if acts else None,
        "perdaPrevista": (serial.iso(max(a.scheduled_at for a in acts
                                         if a.status == "PENDING"))
                          if l.status in ("EXECUTING", "WAITING")
                          and any(a.status == "PENDING" for a in acts) else None),
    }
    return data


@router.post("/leads")
def create_lead(payload: dict = Body(...), db: Session = Depends(get_db)):
    ator = perm.ator(db)
    perm.exigir_ou_permissao(db, ator, "leads_add_manual", "adicionar lead manualmente")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome do lead é obrigatório.")
    if not ator.pelo_menos("gestor"):
        # Sem isso, um SDR com a permissão de criar lead ligado atribuía o
        # lead criado a QUALQUER colega, não só a si mesmo.
        payload = {**payload, "sdrId": ator.user_id}
    l = _build_lead(db, payload)
    db.add(l)
    db.flush()
    # Campos personalizados na CRIAÇÃO — antes só o update gravava, então o
    # lead nascia sem etapa, sem porte, sem nada do que o formulário pedia.
    _gravar_campos(db, l.id, payload.get("customFields"))
    # "Aguardar" deixa o lead na cadência sem atividade agendada: quem cadastra
    # em lote à noite não quer a fila de amanhã cheia de gente que ainda vai
    # ser revisada.
    if payload.get("startNow", True):
        _schedule_cadence(db, l)
    _fire_webhooks(db, "LEAD.CREATED", serial.lead(l))
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
        source=d.get("source", ""), channel=d.get("channel", ""),
        campaign=d.get("campaign", ""), inbound=bool(d.get("inbound")),
        status="WAITING",
    )


def _apagar_atividades(db: Session, *, lead_ids: list[int] | None = None,
                       lead_id: int | None = None, apenas_pendentes: bool = False) -> int:
    """Apaga atividades soltando antes o que aponta para elas.

    `delivery.lead_activity_id` não tem CASCADE, então apagar a atividade
    direto estourava FOREIGN KEY — e, quando não estourava, deixava a entrega
    apontando para um id que o SQLite depois reaproveitava em OUTRO lead. Foi
    o que aconteceu aqui: quatro entregas de agosto acabaram penduradas na
    atividade de um lead criado meses depois. A entrega interessa mesmo sem a
    atividade ("por que este lead não recebeu nada?"), então o vínculo é
    solto, não apagado.
    """
    alvo = db.query(LeadActivity)
    if lead_ids is not None:
        alvo = alvo.filter(LeadActivity.lead_id.in_(lead_ids or [-1]))
    if lead_id is not None:
        alvo = alvo.filter(LeadActivity.lead_id == lead_id)
    if apenas_pendentes:
        alvo = alvo.filter(LeadActivity.status == "PENDING")
    ids = [r[0] for r in alvo.with_entities(LeadActivity.id).all()]
    if not ids:
        return 0
    (db.query(Delivery).filter(Delivery.lead_activity_id.in_(ids))
     .update({"lead_activity_id": None}, synchronize_session=False))
    n = (db.query(LeadActivity).filter(LeadActivity.id.in_(ids))
         .delete(synchronize_session=False))
    return n


def _abrir_prospeccao(db: Session, lead: Lead, motivo_anterior: str = "SWITCHED") -> None:
    """Fecha a prospecção aberta (se houver) e abre uma nova.

    É o que dá nome aos grupos da linha do tempo: sem isso, trocar de cadência
    misturava as atividades das duas na mesma lista.
    """
    if not lead.cadence_id:
        return
    aberta = (db.query(CadenceRun)
              .filter(CadenceRun.lead_id == lead.id, CadenceRun.ended_at.is_(None))
              .order_by(CadenceRun.started_at.desc()).first())
    if aberta is not None:
        if aberta.cadence_id == lead.cadence_id:
            return                     # já é esta cadência: nada a abrir
        aberta.ended_at = datetime.utcnow()
        aberta.outcome = motivo_anterior
    db.add(CadenceRun(lead_id=lead.id, cadence_id=lead.cadence_id,
                      user_id=lead.sdr_id))


def _fechar_prospeccao(db: Session, lead: Lead, desfecho: str) -> None:
    aberta = (db.query(CadenceRun)
              .filter(CadenceRun.lead_id == lead.id, CadenceRun.ended_at.is_(None))
              .order_by(CadenceRun.started_at.desc()).first())
    if aberta is not None:
        aberta.ended_at = datetime.utcnow()
        aberta.outcome = desfecho


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
    _abrir_prospeccao(db, lead)
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
    perm.exigir_dono_lead(db, perm.ator(db), l)
    fields = {"name": "name", "firstName": "first_name", "email": "email",
              "company": "company", "position": "position", "phone": "phone",
              "site": "site", "state": "state", "city": "city", "linkedIn": "linkedin",
              "annotations": "annotations", "cnpj": "cnpj", "cpf": "cpf",
              "razaoSocial": "razao_social", "sdrId": "sdr_id", "clientId": "client_id",
              "bestHour": "best_hour", "cadenceId": "cadence_id",
              "leadBaseId": "lead_base_id", "externalReference": "external_reference",
              "decisionLevel": "decision_level", "whatsapp": "whatsapp",
              "doNotCall": "do_not_call", "source": "source", "channel": "channel",
              "campaign": "campaign", "inbound": "inbound"}
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
    _gravar_campos(db, lid, payload.get("customFields"))
    db.commit()
    return serial.lead(l, _custom_values(db, lid))


@router.post("/leads/bulk")
def bulk_action(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Ações em massa da lista de leads (transferir, trocar cadência, perder, apagar).

    Tudo exige gestor, com UMA exceção: apagar, quando a empresa liga
    `leads_delete` — e aí só os próprios leads. É a permissão "Deletar leads"
    do original, que aqui era anunciada e não existia de fato.
    """
    ator = perm.ator(db)
    ids = payload.get("leadIds") or []
    action = payload.get("action")
    if not ids or not action:
        raise HTTPException(400, "Informe leadIds e action.")
    leads = db.query(Lead).filter(Lead.id.in_(ids)).all()

    if not ator.pelo_menos("gestor"):
        empresa = db.query(Company).first()
        if action != "delete" or not getattr(empresa, "leads_delete", False):
            raise HTTPException(403, "Ação em massa sobre leads exige gestor.")
        alheios = [l.id for l in leads if l.sdr_id != ator.user_id]
        if alheios:
            raise HTTPException(403, f"{len(alheios)} lead(s) não são seus.")
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
            _apagar_atividades(db, lead_id=l.id, apenas_pendentes=True)
            l.cadence_id = cid
            l.current_step = 0
            l.status = "SWITCHED_CADENCE"
            db.flush()
            _schedule_cadence(db, l)
    elif action == "back_to_waiting":
        for l in leads:
            _apagar_atividades(db, lead_id=l.id, apenas_pendentes=True)
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
        _apagar_atividades(db, lead_ids=ids)
        # A conversa é conteúdo do lead e vai junto; a ligação fica, sem o
        # vínculo, porque o extrato tem que continuar batendo com a fatura da
        # operadora — e `call.lead_id` não tem CASCADE, então sem soltar aqui
        # o apagar estourava FOREIGN KEY.
        conversas = [r[0] for r in db.query(Conversation.id)
                     .filter(Conversation.lead_id.in_(ids)).all()]
        if conversas:
            (db.query(Message).filter(Message.conversation_id.in_(conversas))
             .delete(synchronize_session=False))
            (db.query(Conversation).filter(Conversation.id.in_(conversas))
             .delete(synchronize_session=False))
        (db.query(Call).filter(Call.lead_id.in_(ids))
         .update({"lead_id": None}, synchronize_session=False))
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
    a = perm.ator(db)
    if not a.pelo_menos("gestor"):
        # SDR pode puxar um lead disponível (sem dono) pra si; não pode tomar
        # o lead de outro SDR nem se atribuir um lead em nome de terceiro.
        if l.sdr_id and l.sdr_id != a.user_id:
            raise HTTPException(403, "Este lead já é de outro usuário.")
        if payload.get("sdrId") and payload["sdrId"] != a.user_id:
            raise HTTPException(403, "Só é possível iniciar o lead para você mesmo.")
    if payload.get("cadenceId"):
        l.cadence_id = payload["cadenceId"]
    if payload.get("sdrId"):
        l.sdr_id = payload["sdrId"]
    if not l.cadence_id:
        raise HTTPException(400, "Escolha uma cadência antes de iniciar a execução.")
    _apagar_atividades(db, lead_id=lid, apenas_pendentes=True)
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


@router.post("/lead-bases/draft")
def salvar_rascunho(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Guarda o arquivo e o mapa no meio do wizard.

    A importação é um passo só no servidor, mas o wizard tem três telas: sem
    isto, fechar a aba entre escolher o arquivo e confirmar o mapeamento
    jogava fora o upload inteiro.
    """
    ator = perm.ator(db)
    perm.exigir_ou_permissao(db, ator, "regular_user_can_import", "importar lista de leads")
    conteudo = payload.get("content") or ""
    if not conteudo:
        raise HTTPException(400, "Sem conteúdo para guardar.")
    if len(conteudo) > 4_000_000:
        raise HTTPException(400, "Arquivo grande demais para guardar como rascunho.")
    bid = payload.get("id")
    base = db.get(LeadBase, bid) if bid else None
    if base is None:
        base = LeadBase(name=(payload.get("name") or "Importação em andamento").strip(),
                        source="CSV", status="DRAFT",
                        created_by_id=ator.user_id)
        db.add(base)
    elif base.status != "DRAFT":
        raise HTTPException(400, "Esta base já foi importada.")
    base.name = (payload.get("name") or base.name).strip()
    base.draft_content = conteudo
    base.draft_mapping = json.dumps(payload.get("mapping") or {}, ensure_ascii=False)
    base.client_id = payload.get("clientId") or None
    db.commit()
    return {"id": base.id, "status": base.status}


@router.get("/lead-bases/{bid}/draft")
def ler_rascunho(bid: int, db: Session = Depends(get_db)):
    base = db.get(LeadBase, bid)
    if not base or base.status != "DRAFT":
        raise HTTPException(404, "Rascunho não encontrado.")
    perm.ator(db)                            # exige sessão; a base em si não tem dono
    try:
        mapa = json.loads(base.draft_mapping or "{}")
    except ValueError:
        mapa = {}
    return {"id": base.id, "name": base.name, "content": base.draft_content,
            "mapping": mapa, "clientId": base.client_id}


@router.post("/lead-bases/import")
def import_base(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Passo 2 do wizard: cria a base a partir do CSV com o mapa de colunas."""
    ator = perm.ator(db)
    perm.exigir_ou_permissao(db, ator, "regular_user_can_import", "importar lista de leads")
    name = (payload.get("name") or "").strip()
    content = payload.get("content") or ""
    mapping = payload.get("mapping") or {}
    if not name or not content:
        raise HTTPException(400, "Informe o nome da base e o conteúdo do arquivo.")
    sdr_id = payload.get("sdrId")
    if not ator.pelo_menos("gestor"):
        # Mesma regra de create_lead: SDR importa só pra si — nem no default
        # da base, nem mapeando uma coluna do CSV pra "sdrId".
        sdr_id = ator.user_id
        mapping = {k: v for k, v in mapping.items() if k != "sdrId"}
    delim = payload.get("delimiter") or ","
    reader = csv.DictReader(io.StringIO(content), delimiter=delim)

    base = LeadBase(name=name, source="CSV", client_id=payload.get("clientId"),
                    created_by_id=payload.get("createdById"), status="PROCESSING")
    db.add(base)
    db.flush()

    defaults = {"cadenceId": payload.get("cadenceId"), "sdrId": sdr_id,
                "clientId": payload.get("clientId"), "leadBaseId": base.id}
    imported = discarded = 0
    descartadas = []
    for raw in reader:
        row = {field: (raw.get(col) or "").strip()
               for field, col in mapping.items() if col}
        if not row.get("name"):
            discarded += 1
            if len(descartadas) < 20:      # amostra, não o arquivo inteiro
                descartadas.append({"linha": discarded + imported + 1,
                                    "motivo": "sem nome",
                                    "dados": {k: v for k, v in list(raw.items())[:6]}})
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
    base.draft_content = ""
    base.draft_mapping = ""
    rascunho = payload.get("draftId")
    if rascunho:
        # O rascunho vira histórico: a base recém-criada é que fica.
        antigo = db.get(LeadBase, int(rascunho))
        if antigo is not None and antigo.status == "DRAFT" and antigo.id != base.id:
            db.delete(antigo)
    base.discarded_sample = json.dumps(descartadas, ensure_ascii=False)
    base.status = "COMPLETED"
    _fire_webhooks(db, "BASE.IMPORTED", {"leadBaseId": base.id, "name": base.name,
                                         "imported": imported, "discarded": discarded})
    db.commit()
    return {"leadBase": serial.lead_base(base), "imported": imported, "discarded": discarded}


@router.delete("/lead-bases/{bid}")
def delete_base(bid: int, com_leads: bool = False, db: Session = Depends(get_db)):
    """Apaga a base. Com `com_leads=true`, apaga também os leads importados.

    O padrão continua recusando: apagar uma importação leva junto o histórico
    de quem já foi trabalhado. Quem quiser mesmo pede explicitamente, e a tela
    mostra quantos leads vão embora antes de perguntar.
    """
    perm.ator(db).exigir("gestor", "excluir base de leads")
    b = db.get(LeadBase, bid)
    if not b:
        raise HTTPException(404, "Base não encontrada.")
    quantos = db.query(func.count(Lead.id)).filter_by(lead_base_id=bid).scalar()
    if quantos and not com_leads:
        raise HTTPException(400, f"A base tem {quantos} leads vinculados. "
                                 "Use com_leads=true para apagar tudo.")
    if quantos:
        # Apagar leads em massa sem admin seria perda de dado grande demais
        # para um papel que não responde pela conta.
        perm.ator(db).exigir("admin", f"apagar {quantos} leads junto com a base")
        db.query(Lead).filter(Lead.lead_base_id == bid).delete(synchronize_session=False)
    db.delete(b)
    db.commit()
    return {"ok": True, "leadsApagados": quantos if com_leads else 0}


# ── Execução: a fila do SDR ──
@router.get("/execution/queue")
def queue(sdr_id: int | None = None, client_id: int | None = None,
          cadence_id: int | None = None, type: str | None = None,
          q: str | None = None, field_id: int | None = None,
          field_op: str = "EQUALS", field_value: str | None = None,
          escopo: str = "todas", limit: int = Query(60, le=300),
          db: Session = Depends(get_db)):
    """Fila priorizada. Ordena por atraso × prioridade × janela de melhor contato —
    em vez da ordem cronológica pura do Meetime."""
    now = datetime.utcnow()
    query = (db.query(LeadActivity).join(Lead, LeadActivity.lead_id == Lead.id)
             .filter(LeadActivity.status == "PENDING",
                     Lead.status.in_(["EXECUTING", "WAITING", "ON_EXTRA_ACTIVITY"]),
                     LeadActivity.scheduled_at <= now + timedelta(days=1)))
    query = perm.escopo_leads(db, query, perm.ator(db), LeadActivity.user_id)
    if sdr_id:
        query = query.filter(LeadActivity.user_id == sdr_id)
    if client_id:
        query = query.filter(Lead.client_id == client_id)
    if cadence_id:
        query = query.filter(Lead.cadence_id == cadence_id)
    if type:
        query = query.filter(LeadActivity.type == type)
    if q:
        like = f"%{q.strip()}%"
        query = query.filter(or_(Lead.name.ilike(like), Lead.company.ilike(like),
                                 Lead.email.ilike(like), Lead.phone.ilike(like)))
    # Mesmo filtro de campo personalizado da lista de Leads: quem separa a
    # fila por segmento ou origem não precisa sair da tela de execução.
    if field_id and field_value:
        alvo = db.query(LeadFieldValue.lead_id).filter(LeadFieldValue.field_id == field_id)
        alvo = (alvo.filter(LeadFieldValue.value.ilike(f"%{field_value}%"))
                if field_op == "LIKE" else alvo.filter(LeadFieldValue.value == field_value))
        query = query.filter(Lead.id.in_(alvo))
    # Atividade sem passo de cadência é atividade extra — o original as separa
    # da cadência porque nascem de uma decisão do SDR, não do roteiro.
    if escopo == "cadencia":
        query = query.filter(LeadActivity.cadence_step_id.isnot(None))
    elif escopo == "extras":
        query = query.filter(LeadActivity.cadence_step_id.is_(None))
    items = query.all()
    scored = sorted(items, key=lambda a: serial.queue_score(a, now), reverse=True)[:limit]

    # Tentativas por lead numa consulta só: em fila de 60 itens, contar dentro
    # do laço eram 60 idas ao banco.
    ids = [a.lead_id for a in scored]
    tentativas = dict(db.query(LeadActivity.lead_id, func.count(LeadActivity.id))
                      .filter(LeadActivity.lead_id.in_(ids or [-1]),
                              LeadActivity.status.in_(["DONE", "SKIPPED"]))
                      .group_by(LeadActivity.lead_id).all()) if ids else {}
    passos = {p.id: p for p in db.query(CadenceStep).filter(
        CadenceStep.id.in_([a.cadence_step_id for a in scored if a.cadence_step_id] or [-1])).all()}         if scored else {}

    out = []
    for a in scored:
        row = serial.lead_activity(a, now)
        row["score"] = serial.queue_score(a, now)
        row["tentativas"] = tentativas.get(a.lead_id, 0)
        passo = passos.get(a.cadence_step_id)
        row["extra"] = a.cadence_step_id is None
        row["passo"] = ({"id": passo.id, "dia": passo.day, "ordem": passo.order_in_day}
                        if passo else None)
        out.append(row)
    late = sum(1 for a in items if a.scheduled_at < now)
    extras = sum(1 for a in items if a.cadence_step_id is None)
    return {"data": out, "meta": {"total": len(items), "late": late,
                                  "onTime": len(items) - late, "extras": extras,
                                  "generatedAt": serial.iso(now)}}


@router.post("/execution/activities/{aid}/execute")
def execute_activity(aid: int, payload: dict = Body(default={}),
                     db: Session = Depends(get_db)):
    a = db.get(LeadActivity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    perm.exigir_dono_lead(db, perm.ator(db), a.lead)
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
    a.replied = bool(payload.get("replied"))
    if payload.get("replied"):
        # `LeadActivity.id != aid` porque a atividade recém-executada ainda não
        # foi para o banco: sem isso ela entraria na contagem das pausadas.
        paused = (db.query(LeadActivity)
                  .filter(LeadActivity.lead_id == lead.id,
                          LeadActivity.id != aid,
                          LeadActivity.status == "PENDING")
                  .update({"status": "PAUSED"}, synchronize_session=False))
        lead.status = "ON_EXTRA_ACTIVITY"
        _fire_webhooks(db, "LEAD.REPLIED", serial.lead(lead))
    if a.status == "DONE":
        _fire_webhooks(db, "ACTIVITY.DONE", {**serial.lead_activity(a, datetime.utcnow()),
                                             "lead": serial.lead(lead)})
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
    perm.exigir_dono_lead(db, perm.ator(db), lead)
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
    perm.exigir_dono_lead(db, perm.ator(db), lead)
    outcome = payload.get("outcome")
    now = datetime.utcnow()
    if outcome == "WON":
        faltando = _campos_faltando(db, lid, "won_mandatory")
        if faltando:
            raise HTTPException(422, "Preencha os campos obrigatórios para marcar como "
                                     f"ganho: {', '.join(faltando)}.")
        lead.status, lead.won_at = "WON", now
        _fechar_prospeccao(db, lead, "WON")
        company = db.query(Company).first()
        if company and company.deal_feedback_enabled:
            db.add(LeadFeedback(lead_id=lid, user_id=lead.sdr_id))
    elif outcome == "LOST":
        faltando = _campos_faltando(db, lid, "lost_mandatory")
        if faltando:
            raise HTTPException(422, "Preencha os campos obrigatórios para marcar como "
                                     f"perdido: {', '.join(faltando)}.")
        reason_id = payload.get("lostReasonId")
        if reason_id and not db.get(LostReason, reason_id):
            raise HTTPException(400, "Motivo de perda inválido.")
        lead.status, lead.lost_at, lead.lost_reason_id = "LOST", now, reason_id
        _fechar_prospeccao(db, lead, "LOST")
    else:
        raise HTTPException(400, "outcome deve ser WON ou LOST.")
    if payload.get("annotations"):
        lead.annotations = payload["annotations"]
    db.query(LeadActivity).filter_by(lead_id=lid, status="PENDING").update(
        {"status": "SKIPPED", "done_at": now})
    # Enfileira ANTES do commit: `_fire_webhooks` agora só grava na fila, então
    # precisa entrar na mesma transação — depois do commit a linha se perderia.
    _fire_webhooks(db, f"LEAD.{outcome}", serial.lead(lead))
    db.commit()
    return {"ok": True, "lead": serial.lead(lead)}


# ── Feedback de oportunidade ──
# Nasce (LeadFeedback sem filled_at) quando o lead vira WON com a
# funcionalidade ligada; o vendedor responde depois da reunião (ou não).
def _fb_dia(valor: str | None, fim: bool = False) -> datetime | None:
    """Converte AAAA-MM-DD no começo (ou no fim) daquele dia."""
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(valor[:10])
    except ValueError:
        raise HTTPException(400, f"Data inválida: {valor}")
    return d + timedelta(days=1, microseconds=-1) if fim else d


def _fb_balde(quando: datetime, intervalo: str) -> str:
    if intervalo == "mes":
        return quando.strftime("%Y-%m")
    if intervalo == "semana":
        inicio = quando - timedelta(days=quando.weekday())
        return inicio.strftime("%Y-%m-%d")
    return quando.strftime("%Y-%m-%d")


def _fb_escopo(db: Session, query, ator, team_id: int | None):
    """Quem não é gestor só vê o próprio feedback; o time é filtro do gestor."""
    if not ator.pelo_menos("gestor"):
        return query.filter(LeadFeedback.user_id == (ator.user_id or -1))
    if team_id:
        ids = [r[0] for r in db.query(User.id).filter(User.team_id == team_id).all()]
        # Time sem ninguém tem que devolver zero, e não a empresa inteira.
        query = query.filter(LeadFeedback.user_id.in_(ids or [-1]))
    return query


def _fb_query(db: Session, *, status: str, de: str | None, ate: str | None,
              respondido_de: str | None, respondido_ate: str | None,
              reuniao_de: str | None, reuniao_ate: str | None,
              cadence_id: int | None, user_id: int | None, team_id: int | None,
              meeting: str | None):
    ator = perm.ator(db)
    query = _fb_escopo(db, db.query(LeadFeedback).join(Lead, LeadFeedback.lead_id == Lead.id),
                       ator, team_id)
    if status == "pending":
        query = query.filter(LeadFeedback.filled_at.is_(None))
    elif status == "filled":
        query = query.filter(LeadFeedback.filled_at.isnot(None))
    for coluna, inicio, fim in ((LeadFeedback.created_at, de, ate),
                                (LeadFeedback.filled_at, respondido_de, respondido_ate),
                                (LeadFeedback.meeting_at, reuniao_de, reuniao_ate)):
        if inicio:
            query = query.filter(coluna >= _fb_dia(inicio))
        if fim:
            query = query.filter(coluna <= _fb_dia(fim, fim=True))
    if cadence_id:
        query = query.filter(Lead.cadence_id == cadence_id)
    if user_id:
        query = query.filter(LeadFeedback.user_id == user_id)
    if meeting == "yes":
        query = query.filter(LeadFeedback.meeting_happened.is_(True))
    elif meeting == "no":
        query = query.filter(LeadFeedback.meeting_happened.is_(False))
    return query


def _ser_deal_feedback(r: LeadFeedback) -> dict:
    lead = r.lead
    return {"id": r.id, "leadId": r.lead_id, "leadName": lead.name if lead else "",
            "company": lead.company if lead else "",
            "leadStatus": lead.status if lead else "",
            "cadence": ({"id": lead.cadence.id, "name": lead.cadence.name}
                        if lead and lead.cadence else None),
            # Dono do lead é quem prospectou; dono da oportunidade é quem
            # responde o feedback. Quase sempre é a mesma pessoa, mas o Meetime
            # separa as duas colunas porque nem sempre é.
            "leadOwner": serial.user_min(lead.sdr) if lead else None,
            "user": serial.user_min(r.user),
            "meetingHappened": r.meeting_happened,
            "meetingAt": serial.iso(r.meeting_at),
            "qualification": json.loads(r.qualification or "{}"),
            "notes": r.notes, "createdAt": serial.iso(r.created_at),
            "filledAt": serial.iso(r.filled_at)}


def _fb_tag(linhas: list[dict], tag: str | None, tag_value: str | None) -> list[dict]:
    """Filtro por resposta de qualificação — fica em Python porque a
    qualificação é um JSON em texto, não uma coluna."""
    if not tag:
        return linhas
    quer = tag_value != "0"
    return [l for l in linhas if bool(l["qualification"].get(tag)) is quer]


@router.get("/deal-feedbacks")
def list_deal_feedbacks(status: str = "pending", de: str | None = None,
                        ate: str | None = None, respondido_de: str | None = None,
                        respondido_ate: str | None = None, reuniao_de: str | None = None,
                        reuniao_ate: str | None = None, cadence_id: int | None = None,
                        user_id: int | None = None, team_id: int | None = None,
                        meeting: str | None = None, tag: str | None = None,
                        tag_value: str | None = None, q: str | None = None,
                        page: int = 1, per_page: int = 25,
                        db: Session = Depends(get_db)):
    query = _fb_query(db, status=status, de=de, ate=ate, respondido_de=respondido_de,
                      respondido_ate=respondido_ate, reuniao_de=reuniao_de,
                      reuniao_ate=reuniao_ate, cadence_id=cadence_id, user_id=user_id,
                      team_id=team_id, meeting=meeting)
    if q:
        alvo = f"%{q.strip()}%"
        query = query.filter(or_(Lead.name.ilike(alvo), Lead.company.ilike(alvo)))
    ordem = (LeadFeedback.filled_at.desc() if status == "filled"
             else LeadFeedback.created_at.desc())
    linhas = [_ser_deal_feedback(r) for r in query.order_by(ordem).all()]
    linhas = _fb_tag(linhas, tag, tag_value)
    per_page = max(5, min(200, per_page))
    page = max(1, page)
    inicio = (page - 1) * per_page
    return {"items": linhas[inicio:inicio + per_page], "total": len(linhas),
            "page": page, "perPage": per_page}


@router.get("/deal-feedbacks/{fid}")
def get_deal_feedback(fid: int, db: Session = Depends(get_db)):
    """Tudo o que o modal de informações do Meetime mostra em uma chamada."""
    fb = db.get(LeadFeedback, fid)
    if not fb:
        raise HTTPException(404, "Feedback não encontrado.")
    ator = perm.ator(db)
    if not ator.pelo_menos("gestor") and fb.user_id != ator.user_id:
        raise HTTPException(403, "Este feedback não é seu.")
    company = db.query(Company).first()
    perguntas = [t.strip() for t in ((company.deal_feedback_tags or "").splitlines()
                                     if company else []) if t.strip()]
    dados = _ser_deal_feedback(fb)
    respostas = dados["qualification"]
    # As perguntas cadastradas hoje mandam na ordem; uma resposta de pergunta
    # já removida da configuração continua aparecendo, senão ela sumiria do
    # histórico sem aviso.
    dados["answers"] = ([{"tag": t, "value": respostas.get(t)} for t in perguntas]
                        + [{"tag": t, "value": v} for t, v in respostas.items()
                           if t not in perguntas])
    return dados


@router.delete("/deal-feedbacks")
def delete_deal_feedbacks(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Exclusão em massa — é do gestor, e some de vez (o Meetime também)."""
    perm.ator(db).exigir("gestor", "excluir feedbacks de oportunidade")
    ids = [int(i) for i in (payload.get("ids") or [])]
    if not ids:
        raise HTTPException(400, "Selecione ao menos um feedback.")
    n = (db.query(LeadFeedback).filter(LeadFeedback.id.in_(ids))
         .delete(synchronize_session=False))
    db.commit()
    return {"ok": True, "removidos": n}


@router.post("/deal-feedbacks/{fid}")
def fill_deal_feedback(fid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    fb = db.get(LeadFeedback, fid)
    if not fb:
        raise HTTPException(404, "Feedback não encontrado.")
    ator = perm.ator(db)
    if fb.user_id and fb.user_id != ator.user_id and not ator.pelo_menos("gestor"):
        raise HTTPException(403, "Este feedback não é seu.")
    fb.meeting_happened = bool(payload.get("meetingHappened"))
    fb.qualification = json.dumps(
        {str(k): bool(v) for k, v in (payload.get("qualification") or {}).items()})
    fb.notes = (payload.get("notes") or "").strip()
    quando = payload.get("meetingAt")
    if quando:
        try:
            fb.meeting_at = datetime.fromisoformat(str(quando).replace("Z", ""))
        except ValueError:
            raise HTTPException(400, "Data da reunião inválida.")
    fb.filled_at = datetime.utcnow()
    # Quem não teve reunião pode ser reencaminhado a uma cadência específica
    # pra buscar novo agendamento — só se a empresa configurou uma.
    if fb.meeting_happened is False:
        company = db.query(Company).first()
        if company and company.deal_feedback_automation_cadence_id and fb.lead:
            fb.lead.cadence_id = company.deal_feedback_automation_cadence_id
            fb.lead.current_step = 0
            fb.lead.status = "WAITING"
            _schedule_cadence(db, fb.lead)
    db.commit()
    return {"ok": True}


@router.get("/statistics/deal-feedbacks")
def deal_feedback_statistics(de: str | None = None, ate: str | None = None,
                             respondido_de: str | None = None,
                             respondido_ate: str | None = None,
                             reuniao_de: str | None = None,
                             reuniao_ate: str | None = None,
                             cadence_id: int | None = None, user_id: int | None = None,
                             team_id: int | None = None, meeting: str | None = None,
                             intervalo: str = "dia", db: Session = Depends(get_db)):
    """Os mesmos filtros da lista, para que o gráfico e os números batam com
    o que está na tela — antes as estatísticas eram sempre da empresa toda."""
    comum = dict(de=de, ate=ate, respondido_de=respondido_de,
                 respondido_ate=respondido_ate, reuniao_de=reuniao_de,
                 reuniao_ate=reuniao_ate, cadence_id=cadence_id, user_id=user_id,
                 team_id=team_id, meeting=meeting)
    respondidos = _fb_query(db, status="filled", **comum).all()
    aguardando = _fb_query(db, status="pending", **comum).all()
    meeting_yes = sum(1 for f in respondidos if f.meeting_happened)
    meeting_no = sum(1 for f in respondidos if f.meeting_happened is False)
    tag_counts: dict[str, dict[str, int]] = {}
    for f in respondidos:
        for tag, valor in json.loads(f.qualification or "{}").items():
            slot = tag_counts.setdefault(tag, {"sim": 0, "nao": 0})
            slot["sim" if valor else "nao"] += 1
    tags = [{"tag": t, "sim": v["sim"], "nao": v["nao"], "total": v["sim"] + v["nao"],
             "simPercentual": round(100 * v["sim"] / max(1, v["sim"] + v["nao"]))}
            for t, v in sorted(tag_counts.items(),
                               key=lambda kv: -(kv[1]["sim"] + kv[1]["nao"]))]
    # Série temporal: respondidos x pendentes ao longo do período. A chave é a
    # data de criação, que é a única que os dois lados têm.
    balde: dict[str, dict[str, int]] = {}
    for f in respondidos + aguardando:
        if not f.created_at:
            continue
        chave = _fb_balde(f.created_at, intervalo)
        slot = balde.setdefault(chave, {"respondidos": 0, "pendentes": 0})
        slot["respondidos" if f.filled_at else "pendentes"] += 1
    serie = [{"data": k, **v} for k, v in sorted(balde.items())]
    return {"pending": len(aguardando), "filled": len(respondidos),
            "meetingHappened": meeting_yes, "meetingNotHappened": meeting_no,
            "tags": tags, "serie": serie}


@router.patch("/execution/activities/{aid}")
def update_activity_notes(aid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Edita a anotação de uma atividade já realizada.

    O que o SDR escreveu na hora costuma ser telegráfico; a correção vinha
    depois, e não havia onde escrever — só dava para anotar no lead inteiro,
    perdendo a qual ligação aquilo se referia.
    """
    a = db.get(LeadActivity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    perm.exigir_dono_lead(db, perm.ator(db), a.lead)
    if "notes" in payload:
        a.notes = (payload["notes"] or "").strip()
    db.commit()
    return serial.lead_activity(a, datetime.utcnow())


@router.post("/execution/activities/{aid}/reschedule")
def reschedule(aid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    a = db.get(LeadActivity, aid)
    if not a:
        raise HTTPException(404, "Atividade não encontrada.")
    perm.exigir_dono_lead(db, perm.ator(db), a.lead)
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
    """Enfileira o evento; quem entrega é o tick.

    Antes isto fazia `httpx.post` aqui mesmo: o SDR marcava um lead como ganho e
    ficava esperando o CRM de terceiro responder, e se ele estivesse fora do ar
    o evento sumia num `except: pass`.
    """
    webhooks.enfileirar(db, event, data)
