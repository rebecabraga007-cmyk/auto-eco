"""API externa do Bluutime: enviar WhatsApp por outro sistema.

Autentica com os tokens de API do CapiBLU (`capi_...`, criados em Ajustes →
Tokens de API) no escopo `whatsapp`: o mesmo cadastro de tokens, com um escopo
novo, em vez de uma segunda credencial para gerir. O token manda
`Authorization: Bearer <token>`; a sessão do navegador não serve aqui.

A mensagem sai pelo mesmo caminho da tela (`channels.send`) e passa pelas
mesmas travas, na mesma ordem:

1. **Não perturbe** — se o número é de algum lead marcado, recusa. Não há
   parâmetro que fure.
2. **Janela útil** (9h–18h) — `foraDaJanela: true` quando for intencional.
3. **Freio de mão** — sem `BLUUTIME_SEND=1` volta `SIMULATED`, como tudo.

E mais duas que só uma API precisa: limite por token (30/min e 500/dia) e
`referencia` idempotente — o cliente que repete a chamada por timeout não
manda a mensagem duas vezes.
"""
import re
from datetime import datetime, timedelta

from fastapi import APIRouter, Body, Depends, Header, HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import agenda, channels, ratelimit
from ..config import capiblu_on_path
from ..db import get_db
from ..models import AuditLog, Conversation, Delivery, Message
from ..serial import iso
from .whatsapp import achar_conversa, achar_leads, digitos

router = APIRouter(prefix="/api/v1/whatsapp")

ESCOPO = "whatsapp"
POR_MINUTO, POR_DIA = 30, 500
MAX_CARACTERES = 4096


def _token(authorization: str = Header(default="")) -> dict:
    """Valida o token de API e o escopo. Devolve {token_id, user_id, nome}."""
    bruto = authorization[7:].strip() if authorization.lower().startswith("bearer ") else ""
    if not bruto:
        raise HTTPException(401, "Envie o token de API em 'Authorization: Bearer <token>'.")
    capiblu_on_path()
    import api_tokens  # lupa-empresas/backend/api_tokens.py — o mesmo cadastro do CapiBLU
    t = api_tokens.autenticar(bruto)
    if not t:
        raise HTTPException(401, "Token de API inválido ou revogado.")
    if t["escopo"] != ESCOPO:
        raise HTTPException(403, f"Este token é do escopo '{t['escopo']}'. "
                                 f"Crie um token com escopo '{ESCOPO}' para enviar WhatsApp.")
    return t


def _origem(t: dict) -> str:
    return f"api:{t['token_id']}:{t['nome']}"[:80]


def _mensagem(m: Message) -> dict:
    return {"id": m.id, "status": m.status, "providerId": m.provider_id, "erro": m.error,
            "referencia": m.referencia or None, "enviadaEm": iso(m.sent_at),
            "conversationId": m.conversation_id}


def _auditar(db: Session, t: dict, telefone: str, status: int, detalhe: str) -> None:
    fim = digitos(telefone)
    db.add(AuditLog(actor_email=f"api-token:{t['nome']}"[:160], actor_level="api",
                    action="WHATSAPP_API", subject=("*" * max(0, len(fim) - 4)) + fim[-4:],
                    path="/api/v1/whatsapp/mensagens", status=status, detail=detalhe[:240]))


@router.get("/status")
async def status(t: dict = Depends(_token)):
    """O canal está pronto para mandar? Mesmo estado que a tela de Canais mostra."""
    st = await channels.get("WHATSAPP").state()
    return {"estado": st.get("state"), "numero": st.get("numero") or None,
            "envioLigado": channels.envio_ligado(), "motivo": st.get("reason") or None}


@router.post("/mensagens", status_code=201)
async def enviar(payload: dict = Body(...), t: dict = Depends(_token),
                 db: Session = Depends(get_db)):
    """Envia uma mensagem de texto.

    Corpo: `{"telefone": "5541999998888", "mensagem": "...", "referencia": "pedido-123",
    "foraDaJanela": false}`. O telefone aceita máscara e DDI opcional.
    """
    telefone = str(payload.get("telefone") or payload.get("phone") or "").strip()
    mensagem = str(payload.get("mensagem") or payload.get("body") or "").strip()
    referencia = str(payload.get("referencia") or "").strip()[:120]
    d = digitos(telefone)
    if len(d) < 10 or len(d) > 13:
        raise HTTPException(400, "Telefone inválido: informe DDD + número (DDI 55 opcional).")
    if not mensagem:
        raise HTTPException(400, "Mensagem vazia.")
    if len(mensagem) > MAX_CARACTERES:
        raise HTTPException(400, f"Mensagem longa demais (máximo de {MAX_CARACTERES} caracteres).")

    # Idempotência: a mesma referência do mesmo token devolve o envio anterior.
    if referencia:
        anterior = (db.query(Message).filter(Message.origem.like(f"api:{t['token_id']}:%"),
                                             Message.referencia == referencia).first())
        if anterior:
            return {**_mensagem(anterior), "repetida": True}

    if not ratelimit.permitir(f"wa-api-min:{t['token_id']}", POR_MINUTO, 60):
        raise HTTPException(429, f"Limite de {POR_MINUTO} mensagens por minuto para este token.")
    desde = datetime.utcnow() - timedelta(days=1)
    no_dia = (db.query(func.count(Message.id))
              .filter(Message.origem.like(f"api:{t['token_id']}:%"), Message.sent_at >= desde).scalar())
    if no_dia >= POR_DIA:
        raise HTTPException(429, f"Limite de {POR_DIA} mensagens por dia para este token.")

    leads = achar_leads(db, telefone)
    if any(l.do_not_call for l in leads):
        _auditar(db, t, telefone, 403, "bloqueado: não perturbe")
        db.commit()
        raise HTTPException(403, "Este número pertence a um lead marcado como 'não perturbe'.")
    if not payload.get("foraDaJanela"):
        agora = agenda.now_local()
        if agora.hour < agenda.WORK_START or agora.hour >= agenda.WORK_END:
            raise HTTPException(422, f"Fora da janela de {agenda.WORK_START}h–{agenda.WORK_END}h "
                                     f"(agora são {agora:%H:%M}). Envie foraDaJanela=true se for intencional.")

    lead = next((l for l in leads if l.status in ("EXECUTING", "ON_EXTRA_ACTIVITY")),
                leads[0] if leads else None)
    conv = achar_conversa(db, telefone)
    if not conv:
        conv = Conversation(lead_id=lead.id if lead else None, phone=telefone,
                            title=lead.name if lead else telefone)
        db.add(conv)
        db.flush()

    r = await channels.send("WHATSAPP", to=telefone, body=mensagem)
    m = Message(conversation_id=conv.id, direction="OUT", body=mensagem, status=r.status,
                provider_id=r.provider_id, error=r.error, sent_at=r.at,
                origem=_origem(t), referencia=referencia)
    db.add(m)
    if conv.lead_id:
        db.add(Delivery(lead_id=conv.lead_id, user_id=None, channel="WHATSAPP",
                        to_address=telefone, body=mensagem, status=r.status,
                        provider=r.provider, provider_id=r.provider_id, error=r.error))
    conv.last_message_at = r.at
    _auditar(db, t, telefone, 201, f"{r.status} {r.provider_id or r.error}")
    db.commit()
    return {**_mensagem(m), "leadId": conv.lead_id, "repetida": False}


@router.get("/mensagens/{mid}")
def consultar(mid: int, t: dict = Depends(_token), db: Session = Depends(get_db)):
    """Situação de uma mensagem enviada por ESTE token."""
    m = db.get(Message, mid)
    if not m or not (m.origem or "").startswith(f"api:{t['token_id']}:"):
        raise HTTPException(404, "Mensagem não encontrada.")
    return _mensagem(m)
