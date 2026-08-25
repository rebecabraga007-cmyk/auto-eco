"""Conversas de WhatsApp — o módulo WHATSAPP do Meetime."""
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import channels
from ..db import get_db
from ..models import Conversation, Delivery, Lead, Message
from ..serial import iso

router = APIRouter(prefix="/api/whatsapp")


def _conv(c: Conversation, last: Message | None = None) -> dict:
    return {"id": c.id, "phone": c.phone, "title": c.title or (c.lead.name if c.lead else c.phone),
            "lastMessageAt": iso(c.last_message_at),
            "lead": {"id": c.lead.id, "name": c.lead.name, "company": c.lead.company,
                     "status": c.lead.status} if c.lead else None,
            "preview": (last.body[:90] if last else "")}


@router.get("/instances/state")
async def instance_state():
    """Estado real da instância. Antes isto devolvia `CONNECTED` fixo — a tela
    dizia que estava conectado mesmo sem nenhuma credencial configurada."""
    return await channels.get("WHATSAPP").state()


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
async def send_message(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Manda a mensagem pelo provedor e grava o que aconteceu.

    Antes esta rota gravava a linha e devolvia 200 — a conversa mostrava a
    mensagem como enviada sem ninguém ter recebido nada.
    """
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversa não encontrada.")
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Mensagem vazia.")
    lead = c.lead
    # Sem escape por parâmetro: para falar com este lead, tira-se a marca no
    # cadastro dele — ato deliberado — em vez de repetir a chamada com um flag.
    if lead and lead.do_not_call:
        raise HTTPException(403, "Lead marcado como 'não perturbe'. "
                                 "Remova a marca no cadastro do lead.")

    destino = c.phone or (lead.phone if lead else "")
    r = await channels.send("WHATSAPP", to=destino, body=body)

    m = Message(conversation_id=cid, direction="OUT", body=body, status=r.status,
                provider_id=r.provider_id, error=r.error, sent_at=r.at)
    db.add(m)
    if lead:
        db.add(Delivery(lead_id=lead.id, user_id=payload.get("userId"),
                        channel="WHATSAPP", to_address=destino, body=body,
                        status=r.status, provider=r.provider,
                        provider_id=r.provider_id, error=r.error))
    c.last_message_at = r.at
    db.commit()
    return {"id": m.id, "direction": m.direction, "body": m.body,
            "sentAt": iso(m.sent_at), **r.as_dict()}


def _ler_entrada(payload: dict) -> tuple[str, str, bool]:
    """Extrai `(texto, número, é do próprio número)` do webhook.

    Os dois provedores mandam formatos diferentes e a rota atende os dois, para
    trocar `WHATSAPP_PROVIDER` não exigir mexer aqui:

    - **wuzapi/whatsmeow**: `{"type":"Message","event":{"Info":{...},"Message":{...}}}`,
      com `Info.Sender` no formato `5541999998888:12@s.whatsapp.net` — o `:12`
      é o identificador do aparelho no multidevice e precisa sair.
    - **Evolution**: `{"data":{"key":{...},"message":{...}}}`.
    """
    # wuzapi
    evento = payload.get("event")
    if isinstance(evento, dict) and ("Info" in evento or "Message" in evento):
        info = evento.get("Info") or {}
        msg = evento.get("Message") or {}
        texto = (msg.get("conversation")
                 or (msg.get("extendedTextMessage") or {}).get("text") or "").strip()
        remetente = str(info.get("Sender") or info.get("Chat") or "")
        numero = remetente.split("@")[0].split(":")[0]
        return texto, numero, bool(info.get("IsFromMe"))

    # Evolution
    data = payload.get("data") or {}
    key = data.get("key") or {}
    msg = data.get("message") or {}
    texto = (msg.get("conversation")
             or (msg.get("extendedTextMessage") or {}).get("text") or "").strip()
    numero = (key.get("remoteJid") or "").split("@")[0].split(":")[0]
    return texto, numero, bool(key.get("fromMe"))


@router.post("/webhook")
async def webhook(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Mensagem que chega da Evolution API.

    Aberta sem autenticação de usuário porque quem chama é o provedor, não o
    navegador — daí a conferência do `EVOLUTION_WEBHOOK_TOKEN`. Mensagem do
    próprio número (`fromMe`) é descartada: senão o que o SDR manda volta como
    se o lead tivesse respondido.
    """
    import os
    esperado = os.environ.get("EVOLUTION_WEBHOOK_TOKEN", "")
    if esperado and payload.get("token") != esperado:
        raise HTTPException(401, "Token de webhook inválido.")

    texto, jid, proprio = _ler_entrada(payload)
    if proprio:
        return {"ok": True, "ignored": "fromMe"}
    if not texto or not jid:
        return {"ok": True, "ignored": "sem texto ou remetente"}

    # Casa pelos últimos 8 dígitos: o nono dígito do celular e o DDI entram e
    # saem conforme a origem do cadastro, e comparar a string inteira erra.
    sufixo = jid[-8:]
    conv = (db.query(Conversation)
            .filter(Conversation.phone.like(f"%{sufixo}")).first())
    if not conv:
        lead = db.query(Lead).filter(Lead.phone.like(f"%{sufixo}")).first()
        conv = Conversation(lead_id=lead.id if lead else None, phone=jid,
                            title=(lead.name if lead else jid))
        db.add(conv)
        db.flush()
    db.add(Message(conversation_id=conv.id, direction="IN", body=texto, status="SENT"))
    conv.last_message_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "conversationId": conv.id,
            "leadId": conv.lead_id, "matched": bool(conv.lead_id)}
