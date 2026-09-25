"""Conversas de WhatsApp — o módulo WHATSAPP do Meetime."""
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Request
from sqlalchemy import and_, func, or_
from sqlalchemy.orm import Session

from .. import channels, perm, ratelimit
from ..db import get_db
from ..models import Company, Conversation, Delivery, Lead, Message, User
from ..serial import iso

router = APIRouter(prefix="/api/whatsapp")


def _conv(c: Conversation, last: Message | None = None, nao_lidas: int = 0) -> dict:
    return {"id": c.id, "phone": c.phone, "title": c.title or (c.lead.name if c.lead else c.phone),
            "lastMessageAt": iso(c.last_message_at),
            "lead": {"id": c.lead.id, "name": c.lead.name, "company": c.lead.company,
                     "status": c.lead.status} if c.lead else None,
            "assignedUser": ({"id": c.assigned_user.id, "name": c.assigned_user.name}
                             if c.assigned_user else None),
            "unread": nao_lidas,
            "preview": (last.body[:90] if last else "")}


@router.get("/instances/state")
async def instance_state():
    """Estado real da instância. Antes isto devolvia `CONNECTED` fixo — a tela
    dizia que estava conectado mesmo sem nenhuma credencial configurada."""
    return await channels.get("WHATSAPP").state()


@router.get("/conversations")
def conversations(q: str | None = None, user_id: int | None = None,
                  unread: bool | None = None, db: Session = Depends(get_db)):
    ator = perm.ator(db)
    query = db.query(Conversation)
    if not ator.pelo_menos("gestor"):
        empresa = db.query(Company).first()
        if not (empresa and empresa.leads_visible_all):
            # Conversa sem lead (telefone avulso) não tem dono pra restringir;
            # conversa de lead só aparece pra quem é dono dele.
            minhas = db.query(Lead.id).filter(Lead.sdr_id == (ator.user_id or -1))
            query = query.filter(or_(Conversation.lead_id.is_(None),
                                     Conversation.lead_id.in_(minhas)))
    if q:
        alvo = f"%{q.strip()}%"
        query = query.filter(or_(Conversation.title.ilike(alvo), Conversation.phone.ilike(alvo)))
    if user_id:
        # Atendente é quem assumiu a conversa; quando ninguém assumiu, vale o
        # dono do lead — é como o time enxerga "minhas conversas".
        do_lead = db.query(Lead.id).filter(Lead.sdr_id == user_id)
        query = query.filter(or_(Conversation.assigned_user_id == user_id,
                                 and_(Conversation.assigned_user_id.is_(None),
                                      Conversation.lead_id.in_(do_lead))))
    rows = query.order_by(Conversation.last_message_at.desc()).all()
    out = []
    for c in rows:
        last = (db.query(Message).filter_by(conversation_id=c.id)
                .order_by(Message.sent_at.desc()).first())
        nao_lidas = (db.query(func.count(Message.id))
                     .filter(Message.conversation_id == c.id, Message.direction == "IN",
                             Message.sent_at > (c.last_read_at or datetime(1970, 1, 1)))
                     .scalar())
        if unread and not nao_lidas:
            continue
        out.append(_conv(c, last, nao_lidas))
    return out


@router.get("/conversations/{cid}")
def conversation(cid: int, limit: int = 60, before: int | None = None,
                 db: Session = Depends(get_db)):
    """A conversa e as últimas mensagens.

    `before` carrega o trecho anterior: uma conversa de meses não cabe numa
    resposta só, e abrir a tela não pode depender de baixar tudo.
    """
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversa não encontrada.")
    perm.exigir_dono_lead(db, perm.ator(db), c.lead)
    limit = max(10, min(200, limit))
    q = db.query(Message).filter_by(conversation_id=cid)
    if before:
        q = q.filter(Message.id < before)
    msgs = list(reversed(q.order_by(Message.id.desc()).limit(limit).all()))
    restantes = (db.query(func.count(Message.id))
                 .filter(Message.conversation_id == cid,
                         Message.id < (msgs[0].id if msgs else 0)).scalar())
    # Abrir a conversa é lê-la: o contador zera aqui, não num botão separado.
    if not before:
        c.last_read_at = datetime.utcnow()
        db.commit()
    return {**_conv(c), "restantes": restantes,
            "messages": [{"id": m.id, "direction": m.direction, "body": m.body,
                          "status": m.status, "sentAt": iso(m.sent_at)} for m in msgs]}


@router.patch("/conversations/{cid}")
def update_conversation(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Atribui a conversa a alguém, ou devolve para a fila.

    Sem dono explícito, duas pessoas respondiam o mesmo contato — e no
    telefone avulso, sem lead, não havia nem a quem perguntar.
    """
    c = db.get(Conversation, cid)
    if not c:
        raise HTTPException(404, "Conversa não encontrada.")
    ator = perm.ator(db)
    perm.exigir_dono_lead(db, ator, c.lead)
    if "assignedUserId" in payload:
        uid = payload["assignedUserId"]
        if uid and not db.get(User, int(uid)):
            raise HTTPException(400, "Usuário inválido.")
        c.assigned_user_id = int(uid) if uid else None
    db.commit()
    return _conv(c)


@router.post("/conversations")
def open_conversation(payload: dict = Body(...), db: Session = Depends(get_db)):
    ator = perm.ator(db)
    lead = db.get(Lead, payload["leadId"]) if payload.get("leadId") else None
    if payload.get("leadId") and not lead:
        raise HTTPException(404, "Lead não encontrado.")
    if lead:
        perm.exigir_dono_lead(db, ator, lead)
    elif not ator.pelo_menos("gestor"):
        # Conversa avulsa, sem lead, pulava o dono e o "não perturbe": bastava
        # digitar o telefone de um lead alheio em outro formato.
        raise HTTPException(403, "Abra a conversa a partir de um lead seu.")
    phone = payload.get("phone") or (lead.phone if lead else "")
    if not phone:
        raise HTTPException(400, "Informe o telefone ou um lead com telefone.")
    digitos = re.sub(r"\D", "", phone)[-11:]
    if len(digitos) < 10:
        raise HTTPException(400, "Telefone incompleto: informe DDD + número.")
    if lead and lead.do_not_call:
        raise HTTPException(403, "Lead marcado como 'não perturbe'.")
    # O mesmo número em outro formato ("+55 (41) ..." × "41...") é a mesma pessoa.
    existing = next((c for c in db.query(Conversation).all()
                     if re.sub(r"\D", "", c.phone or "")[-11:] == digitos), None)
    if existing:
        perm.exigir_dono_lead(db, ator, existing.lead if existing.lead_id else None)
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
    ator = perm.ator(db)
    perm.exigir_dono_lead(db, ator, c.lead)
    body = (payload.get("body") or "").strip()
    if not body:
        raise HTTPException(400, "Mensagem vazia.")
    if len(body) > 4096:
        raise HTTPException(400, "Mensagem longa demais (máximo de 4096 caracteres).")
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
        # O autor é quem está logado: `userId` no corpo deixava atribuir o
        # envio a outra pessoa e distorcer as métricas dela.
        db.add(Delivery(lead_id=lead.id, user_id=ator.user_id,
                        channel="WHATSAPP", to_address=destino, body=body,
                        status=r.status, provider=r.provider,
                        provider_id=r.provider_id, error=r.error))
    c.last_message_at = r.at
    db.commit()
    return {"id": m.id, "direction": m.direction, "body": m.body,
            "sentAt": iso(m.sent_at), **r.as_dict()}


def digitos(tel: str) -> str:
    return re.sub(r"\D", "", tel or "")


def mesmo_numero(a: str, b: str) -> bool:
    """Mesmo telefone? Pelos últimos 8 dígitos: DDI e o nono dígito entram e
    saem conforme a origem do cadastro. Comparar o texto errava sempre que o
    lead estava gravado com máscara, "(41) 99999-8888"."""
    da, db_ = digitos(a), digitos(b)
    return len(da) >= 8 and len(db_) >= 8 and da[-8:] == db_[-8:]


def achar_conversa(db: Session, tel: str) -> Conversation | None:
    fim = digitos(tel)[-4:]
    candidatas = db.query(Conversation).filter(Conversation.phone.like(f"%{fim}%")).all() if fim else []
    return next((c for c in candidatas if mesmo_numero(c.phone, tel)), None)


def achar_leads(db: Session, tel: str) -> list[Lead]:
    """Todos os leads com esse telefone (em qualquer um dos números do cadastro)."""
    fim = digitos(tel)[-4:]
    if not fim:
        return []
    candidatos = db.query(Lead).filter(Lead.phone.like(f"%{fim[:2]}%{fim[2:]}%")).all()
    return [l for l in candidatos
            if any(mesmo_numero(t, tel) for t in re.split(r"[,;/|]", l.phone or ""))]


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
        # Grupo não é conversa com lead: a mensagem de um participante viraria
        # "lead respondeu" para quem tivesse o número parecido.
        if info.get("IsGroup") or "@g.us" in str(info.get("Chat") or ""):
            return "", "", True
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


async def _corpo_webhook(request: Request) -> dict:
    """O wuzapi manda JSON ou formulário com o JSON no campo `jsonData`,
    conforme a versão e a configuração; a Evolution manda JSON."""
    import json
    tipo = request.headers.get("content-type", "")
    if "form" in tipo:
        form = await request.form()
        bruto = form.get("jsonData") or "{}"
        try:
            dados = json.loads(bruto)
        except ValueError:
            dados = {}
        if form.get("token") and "token" not in dados:
            dados["token"] = form.get("token")
        return dados if isinstance(dados, dict) else {}
    try:
        dados = await request.json()
    except ValueError:
        return {}
    return dados if isinstance(dados, dict) else {}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """Mensagem que chega da Evolution API.

    Aberta sem autenticação de usuário porque quem chama é o provedor, não o
    navegador — daí a conferência do `EVOLUTION_WEBHOOK_TOKEN`. Mensagem do
    próprio número (`fromMe`) é descartada: senão o que o SDR manda volta como
    se o lead tivesse respondido.
    """
    import hmac
    import os
    origem = request.client.host if request.client else "desconhecido"
    # Rota pública — sem isso, alguém tenta o token errado sem limite
    # nenhum. O espaço do token já é grande o bastante pra tornar
    # força-bruta inviável de qualquer forma; isto é só um freio a mais.
    if not ratelimit.permitir(f"wa-webhook:{origem}", 120, 60):
        raise HTTPException(429, "Muitas chamadas em pouco tempo.")
    esperado = os.environ.get("EVOLUTION_WEBHOOK_TOKEN", "")
    if not esperado:
        # Fail-closed: sem token configurado, a rota é pública sem exigir
        # sessão — aceitar tudo mesmo sem token deixava qualquer request
        # externo criar conversa/mensagem falsa e até disparar "lead
        # respondeu" (pausa cadência de verdade).
        raise HTTPException(503, "EVOLUTION_WEBHOOK_TOKEN não configurado no servidor.")
    payload = await _corpo_webhook(request)
    # O token pode vir na URL (`?token=`), que é como o wuzapi é configurado:
    # ele não repete no corpo um segredo nosso.
    recebido = request.query_params.get("token") or str(payload.get("token") or "")
    if not hmac.compare_digest(recebido, esperado):
        raise HTTPException(401, "Token de webhook inválido.")

    texto, jid, proprio = _ler_entrada(payload)
    if proprio:
        return {"ok": True, "ignored": "fromMe"}
    if not texto or not jid:
        return {"ok": True, "ignored": "sem texto ou remetente"}

    conv = achar_conversa(db, jid)
    if not conv:
        leads = achar_leads(db, jid)
        # Com mais de um lead no mesmo número, fica o que está em prospecção.
        lead = next((l for l in leads if l.status in ("EXECUTING", "ON_EXTRA_ACTIVITY")),
                    leads[0] if leads else None)
        conv = Conversation(lead_id=lead.id if lead else None, phone=jid,
                            title=(lead.name if lead else jid))
        db.add(conv)
        db.flush()
    db.add(Message(conversation_id=conv.id, direction="IN", body=texto, status="SENT"))
    conv.last_message_at = datetime.utcnow()
    db.commit()
    return {"ok": True, "conversationId": conv.id,
            "leadId": conv.lead_id, "matched": bool(conv.lead_id)}
