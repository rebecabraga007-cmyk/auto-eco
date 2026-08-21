"""WhatsApp pela Evolution API.

A Evolution é um invólucro em cima do WhatsApp Web: cada "instância" é um
número pareado por QR Code. Duas consequências que importam aqui:

1. **A instância cai sozinha.** Celular sem bateria, sessão expirada, WhatsApp
   Web aberto noutro lugar — e ela desconecta. Por isso `state()` pergunta ao
   provedor em vez de devolver `CONNECTED` fixo, como fazia antes.
2. **Número tem de existir no WhatsApp.** Mandar para número que não tem conta
   não dá erro no envio; some. `check_number` pergunta antes.
"""
import os
import re

import httpx

from .base import Channel, SendResult


def _digits(phone: str) -> str:
    return re.sub(r"\D", "", phone or "")


def to_jid(phone: str) -> str:
    """Número brasileiro no formato que a Evolution espera (E.164 sem '+').

    O nono dígito é a armadilha: o WhatsApp guarda celular de DDD <= 30 com o 9
    e alguns registros antigos vêm sem. Aqui só normalizamos o país; o resto
    fica com a checagem de existência.
    """
    d = _digits(phone)
    if not d:
        return ""
    if d.startswith("55"):
        return d
    if len(d) in (10, 11):
        return "55" + d
    return d


class WhatsApp(Channel):
    key = "WHATSAPP"
    label = "WhatsApp (Evolution API)"

    def __init__(self):
        self.base = (os.environ.get("EVOLUTION_API_URL") or "").rstrip("/")
        self.token = os.environ.get("EVOLUTION_API_KEY") or ""
        self.instance = os.environ.get("EVOLUTION_INSTANCE") or ""

    def configured(self) -> tuple[bool, str]:
        faltando = [nome for nome, v in (("EVOLUTION_API_URL", self.base),
                                         ("EVOLUTION_API_KEY", self.token),
                                         ("EVOLUTION_INSTANCE", self.instance)) if not v]
        if faltando:
            return False, f"Falta configurar {', '.join(faltando)} no .env."
        return True, ""

    def _client(self) -> httpx.AsyncClient:
        return httpx.AsyncClient(base_url=self.base, timeout=30.0,
                                 headers={"apikey": self.token})

    async def state(self) -> dict:
        ok, why = self.configured()
        out = {"channel": self.key, "label": self.label, "configured": ok,
               "reason": why, "state": "NOT_CONFIGURED", "instance": self.instance}
        if not ok:
            return out
        try:
            async with self._client() as c:
                r = await c.get(f"/instance/connectionState/{self.instance}")
            data = r.json() if r.status_code < 400 else {}
            # A Evolution responde {"instance": {"state": "open"}}; "open" é
            # conectado, "close"/"connecting" não.
            raw = ((data.get("instance") or {}).get("state")
                   or data.get("state") or "").lower()
            out["state"] = {"open": "CONNECTED", "connecting": "CONNECTING",
                            "close": "DISCONNECTED"}.get(raw, raw.upper() or "UNKNOWN")
            out["raw"] = raw
        except Exception as exc:                       # provedor fora do ar
            out["state"] = "UNREACHABLE"
            out["reason"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    async def check_number(self, phone: str) -> bool | None:
        """O número tem WhatsApp? `None` quando não deu para saber."""
        ok, _ = self.configured()
        jid = to_jid(phone)
        if not ok or not jid:
            return None
        try:
            async with self._client() as c:
                r = await c.post(f"/chat/whatsappNumbers/{self.instance}",
                                 json={"numbers": [jid]})
            if r.status_code >= 400:
                return None
            rows = r.json()
            return bool(rows and rows[0].get("exists"))
        except Exception:
            return None

    async def send(self, *, to: str, body: str, subject: str = "", **extra) -> SendResult:
        ok, why = self.configured()
        if not ok:
            return SendResult("SIMULATED", self.key, error=why)
        jid = to_jid(to)
        if not jid:
            return SendResult("BLOCKED", self.key, error="Sem número de telefone.")
        try:
            async with self._client() as c:
                r = await c.post(f"/message/sendText/{self.instance}",
                                 json={"number": jid, "text": body})
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                return SendResult("FAILED", self.key,
                                  error=str(data.get("message") or data)[:200], detail=data)
            key = data.get("key") or {}
            return SendResult("SENT", self.key, provider_id=key.get("id", ""), detail=data)
        except Exception as exc:
            return SendResult("FAILED", self.key, error=f"{type(exc).__name__}: {exc}"[:200])
