"""Webhooks de saída: cadastro, fila e reenvio.

A entrega em si vive em `server/webhooks.py`; aqui é a superfície de gestão.
"""
import json
import secrets
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import perm, serial, webhooks
from ..db import get_db
from ..models import Webhook, WebhookDelivery

router = APIRouter(prefix="/api/integracoes")


def _hook(w: Webhook, stats: dict | None = None) -> dict:
    return {"id": w.id, "targetUrl": w.target_url,
            "events": [e.strip() for e in (w.events or "").split(",") if e.strip()],
            "enabled": w.enabled, "hasSecret": bool(w.secret),
            "createdAt": serial.iso(w.created_at), "stats": stats or {}}


@router.get("/eventos")
def eventos():
    """Os eventos que dá para assinar, e como conferir a assinatura."""
    return {
        "events": webhooks.EVENTOS,
        "signature": {
            "header": "X-Bluutime-Signature",
            "algorithm": "HMAC-SHA256 do corpo cru, em hexadecimal, prefixado por 'sha256='",
            "verify": "hmac.new(secret, request.body, hashlib.sha256).hexdigest()",
        },
        "retry": {"attempts": webhooks.MAX_TENTATIVAS, "backoffSeconds": webhooks.ESPERAS},
    }


@router.get("/webhooks")
def listar(db: Session = Depends(get_db)):
    saida = []
    for w in db.query(Webhook).order_by(Webhook.id).all():
        linhas = db.query(WebhookDelivery).filter(WebhookDelivery.webhook_id == w.id).all()
        saida.append(_hook(w, {
            "pending": sum(1 for d in linhas if d.status == "PENDING"),
            "sent": sum(1 for d in linhas if d.status == "SENT"),
            "failed": sum(1 for d in linhas if d.status == "FAILED"),
        }))
    return {"data": saida}


@router.post("/webhooks")
def criar(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "cadastrar webhook")
    url = (payload.get("targetUrl") or "").strip()
    if not url.startswith(("http://", "https://")):
        raise HTTPException(400, "A URL precisa começar com http:// ou https://.")
    eventos_pedidos = payload.get("events") or []
    desconhecidos = [e for e in eventos_pedidos if e not in webhooks.EVENTOS]
    if desconhecidos:
        raise HTTPException(400, f"Evento desconhecido: {', '.join(desconhecidos)}. "
                                 f"Use: {', '.join(webhooks.EVENTOS)}")
    if not eventos_pedidos:
        raise HTTPException(400, "Escolha ao menos um evento.")
    # Segredo gerado aqui: se o usuário escolhesse, escolheria algo fraco — e o
    # valor precisa ser aleatório para a assinatura significar alguma coisa.
    w = Webhook(target_url=url, events=",".join(eventos_pedidos),
                secret=payload.get("secret") or secrets.token_urlsafe(24),
                enabled=bool(payload.get("enabled", True)))
    db.add(w)
    db.commit()
    # Única vez que o segredo sai daqui: o receptor precisa dele para conferir.
    return {**_hook(w), "secret": w.secret}


@router.patch("/webhooks/{wid}")
def atualizar(wid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "alterar webhook")
    w = db.get(Webhook, wid)
    if not w:
        raise HTTPException(404, "Webhook não encontrado.")
    if "targetUrl" in payload:
        w.target_url = payload["targetUrl"]
    if "enabled" in payload:
        w.enabled = bool(payload["enabled"])
    if "events" in payload:
        ruins = [e for e in payload["events"] if e not in webhooks.EVENTOS]
        if ruins:
            raise HTTPException(400, f"Evento desconhecido: {', '.join(ruins)}")
        w.events = ",".join(payload["events"])
    db.commit()
    return _hook(w)


@router.delete("/webhooks/{wid}")
def excluir(wid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "excluir webhook")
    w = db.get(Webhook, wid)
    if w:
        db.delete(w)
        db.commit()
    return {"ok": True}


@router.post("/webhooks/{wid}/testar")
def testar(wid: int, db: Session = Depends(get_db)):
    """Manda um evento de mentira e entrega na hora, sem esperar o tick."""
    w = db.get(Webhook, wid)
    if not w:
        raise HTTPException(404, "Webhook não encontrado.")
    entrega = WebhookDelivery(
        webhook_id=w.id, event="LEAD.WON",
        payload=json.dumps({"event": "LEAD.WON", "test": True,
                            "data": {"id": 0, "name": "Lead de teste",
                                     "company": "Empresa de teste"},
                            "sentAt": datetime.utcnow().isoformat(timespec="seconds") + "Z"},
                           ensure_ascii=False))
    db.add(entrega)
    db.commit()
    ok, code, erro = webhooks._entregar(w, entrega)
    entrega.attempts = 1
    entrega.response_code = code
    entrega.error = erro
    entrega.status = "SENT" if ok else "FAILED"
    if ok:
        entrega.delivered_at = datetime.utcnow()
    db.commit()
    return {"ok": ok, "responseCode": code, "error": erro, "deliveryId": entrega.id}


@router.get("/entregas")
def entregas(webhook_id: int | None = None, status: str | None = None,
             limit: int = 100, db: Session = Depends(get_db)):
    q = db.query(WebhookDelivery)
    if webhook_id:
        q = q.filter(WebhookDelivery.webhook_id == webhook_id)
    if status:
        q = q.filter(WebhookDelivery.status == status.upper())
    linhas = q.order_by(WebhookDelivery.created_at.desc()).limit(min(limit, 500)).all()
    return {"data": [{
        "id": d.id, "webhookId": d.webhook_id, "event": d.event, "status": d.status,
        "attempts": d.attempts, "responseCode": d.response_code, "error": d.error,
        "createdAt": serial.iso(d.created_at), "nextTryAt": serial.iso(d.next_try_at),
        "deliveredAt": serial.iso(d.delivered_at),
        "targetUrl": d.webhook.target_url if d.webhook else "",
    } for d in linhas]}


@router.post("/entregas/{did}/reenviar")
def reenviar(did: int, db: Session = Depends(get_db)):
    """Devolve uma entrega desistida para a fila."""
    d = db.get(WebhookDelivery, did)
    if not d:
        raise HTTPException(404, "Entrega não encontrada.")
    d.status = "PENDING"
    d.attempts = 0
    d.error = ""
    d.next_try_at = datetime.utcnow()
    db.commit()
    return {"ok": True, **webhooks.despachar(db)}


@router.post("/despachar")
def despachar_agora(db: Session = Depends(get_db)):
    """Roda a fila agora, em vez de esperar o tick de 5 min."""
    return webhooks.despachar(db)
