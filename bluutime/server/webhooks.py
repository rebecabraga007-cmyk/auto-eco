"""Entrega de evento para fora — a saída do Bluutime.

O envio anterior era `httpx.post(...)` com `except: pass` dentro do request:
bloqueava a resposta enquanto o receptor pensava, perdia o evento na primeira
falha e mandava o segredo em texto para todo mundo que recebesse.

Aqui a entrega é **enfileirada**, assinada e repetida:

1. `enfileirar()` só grava a tentativa e volta — o request do usuário não espera
   um servidor de terceiro.
2. O `tick` chama `despachar()`, que entrega o que está vencido.
3. Falha vira reagendamento com espera crescente, até `MAX_TENTATIVAS`.
"""
import hashlib
import hmac
import json
from datetime import datetime, timedelta

import httpx

from .models import Webhook, WebhookDelivery

# 1min, 5min, 30min, 2h, 6h — cobre desde o reinício rápido do receptor até a
# manutenção que passa da madrugada.
ESPERAS = [60, 300, 1800, 7200, 21600]
MAX_TENTATIVAS = len(ESPERAS) + 1
TIMEOUT = 10.0

EVENTOS = ["LEAD.CREATED", "LEAD.WON", "LEAD.LOST", "LEAD.REPLIED",
           "ACTIVITY.DONE", "MESSAGE.SENT", "BASE.IMPORTED"]


def assinar(secret: str, corpo: bytes) -> str:
    """HMAC-SHA256 do corpo exato.

    O receptor recalcula e compara — é o que prova que o pedido veio daqui e
    não foi alterado no caminho. O cabeçalho antigo mandava o segredo em si, o
    que dá ao receptor tudo o que ele precisa para se passar por nós.
    """
    return "sha256=" + hmac.new(secret.encode(), corpo, hashlib.sha256).hexdigest()


def enfileirar(db, event: str, data: dict) -> int:
    """Grava uma tentativa por webhook inscrito. Não faz rede."""
    if event not in EVENTOS:
        return 0
    corpo = json.dumps({"event": event, "data": data,
                        "sentAt": datetime.utcnow().isoformat(timespec="seconds") + "Z"},
                       ensure_ascii=False, default=str)
    n = 0
    for hook in db.query(Webhook).filter(Webhook.enabled.is_(True)).all():
        # `events` é lista separada por vírgula; comparação exata para
        # "LEAD.WON" não casar com "LEAD.WONTFIX".
        if event not in [e.strip() for e in (hook.events or "").split(",")]:
            continue
        db.add(WebhookDelivery(webhook_id=hook.id, event=event, payload=corpo))
        n += 1
    return n


def _entregar(hook: Webhook, entrega: WebhookDelivery) -> tuple[bool, int, str]:
    corpo = entrega.payload.encode()
    headers = {
        "Content-Type": "application/json",
        "X-Bluutime-Event": entrega.event,
        "X-Bluutime-Delivery": str(entrega.id),
        "User-Agent": "Bluutime-Webhook/1",
    }
    if hook.secret:
        headers["X-Bluutime-Signature"] = assinar(hook.secret, corpo)
    try:
        r = httpx.post(hook.target_url, content=corpo, headers=headers, timeout=TIMEOUT)
        # 2xx é sucesso. 4xx que não seja 408/429 é erro do payload e não
        # melhora com repique — desistir cedo evita martelar o receptor.
        if 200 <= r.status_code < 300:
            return True, r.status_code, ""
        permanente = 400 <= r.status_code < 500 and r.status_code not in (408, 429)
        return (False, r.status_code,
                ("recusado" if permanente else "erro temporário") + f": HTTP {r.status_code}")
    except Exception as exc:
        return False, 0, f"{type(exc).__name__}: {exc}"[:200]


def despachar(db, limite: int = 50) -> dict:
    """Entrega o que está vencido. Chamado pelo tick."""
    agora = datetime.utcnow()
    pendentes = (db.query(WebhookDelivery)
                 .filter(WebhookDelivery.status == "PENDING",
                         WebhookDelivery.next_try_at <= agora)
                 .order_by(WebhookDelivery.next_try_at).limit(limite).all())
    relatorio = {"tentadas": 0, "entregues": 0, "reagendadas": 0, "desistidas": 0}
    for entrega in pendentes:
        hook = entrega.webhook
        if not hook or not hook.enabled:
            entrega.status = "FAILED"
            entrega.error = "Webhook removido ou desativado."
            relatorio["desistidas"] += 1
            continue
        ok, code, erro = _entregar(hook, entrega)
        entrega.attempts += 1
        entrega.response_code = code
        entrega.error = erro
        relatorio["tentadas"] += 1
        if ok:
            entrega.status = "SENT"
            entrega.delivered_at = datetime.utcnow()
            relatorio["entregues"] += 1
        elif erro.startswith("recusado") or entrega.attempts >= MAX_TENTATIVAS:
            entrega.status = "FAILED"
            relatorio["desistidas"] += 1
        else:
            espera = ESPERAS[min(entrega.attempts - 1, len(ESPERAS) - 1)]
            entrega.next_try_at = datetime.utcnow() + timedelta(seconds=espera)
            relatorio["reagendadas"] += 1
    db.commit()
    return relatorio
