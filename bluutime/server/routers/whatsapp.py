"""Conversas de WhatsApp — o módulo WHATSAPP do Meetime."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Conversation, Lead, Message
from ..serial import iso

router = APIRouter(prefix="/api/whatsapp")


def _conv(c: Conversation, last: Message | None = None) -> dict:
    return {"id": c.id, "phone": c.phone, "title": c.title or (c.lead.name if c.lead else c.phone),
            "lastMessageAt": iso(c.last_message_at),
            "lead": {"id": c.lead.id, "name": c.lead.name, "company": c.lead.company,
                     "status": c.lead.status} if c.lead else None,
            "preview": (last.body[:90] if last else "")}


@router.get("/instances/state")
def instance_state():
    return {"state": "CONNECTED", "provider": "EVOLUTION_API", "instance": "bluutime-blu"}


@router.get("/conversations")
def conversations(q: str | None = None, db: Session = Depends(get_db)):
    query = db.query(Conversation)
    if q:
        query = query.filter(Conversation.title.ilike(f"%{q}%"))
    rows = query.order_by(Conversation.last_message_at.desc()).all()
    out = []
    for c in rows:
        last = (db.query(Message).filter_by(conversation_id=c.id)
                .order_by(Message.sent_at.desc()).first())
        out.append(_conv(c, last))
    return out


@router.get("/conversations/{cid}")
def conversation(cid: int, db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversa não encontrada.")
    msgs = (db.query(Message).filter_by(conversation_id=cid)
            .order_by(Message.sent_at).all())
    return {**_conv(c), "messages": [{"id": m.id, "direction": m.direction,
                                      "body": m.body, "sentAt": iso(m.sent_at)}
                                     for m in msgs]}


@router.post("/conversations")
def open_conversation(payload: dict = Body(...), db: Session = Depends(get_db)):
    lead = db.get(Lead, payload["leadId"]) if payload.get("leadId") else None
    phone = payload.get("phone") or (lead.phone if lead else "")
    if not phone:
        raise HTTPException(400, "Informe o telefone ou um lead com telefone.")
    existing = db.query(Conversation).filter_by(phone=phone).first()
    if existing:
        return _conv(existing)
    c = Conversation(lead_id=lead.id if lead else None, phone=phone,
                     title=lead.name if lead else phone)
    db.add(c)
    db.commit()
    return _conv(c)


@router.post("/conversations/{cid}/messages")
def send_message(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversa não encontrada.")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Mensagem vazia.")
    m = Message(conversation_id=cid, direction="OUT", body=body)
    db.add(m)
    c.last_message_at = m.sent_at = datetime.utcnow()
    db.commit()
    return {"id": m.id, "direction": m.direction, "body": m.body, "sentAt": iso(m.sent_at)}
