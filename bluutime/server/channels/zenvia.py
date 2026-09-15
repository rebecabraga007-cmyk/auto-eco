"""SMS pela Zenvia.

Fica ao lado do WhatsApp (wuzapi) e do e-mail (SMTP) como um terceiro canal,
mas nasce sem credencial: `configured()` volta `False` até alguém colar
`ZENVIA_API_TOKEN`/`ZENVIA_FROM` no `.env`. Até lá, `send()` cai em
`SIMULATED` — como todo canal aqui, nunca finge que entregou.

API v2 da Zenvia (https://api.zenvia.com/v2/channels/sms/messages): token vai
no header `X-API-TOKEN`, sem "Bearer"; o corpo é uma lista de `contents`
porque o mesmo endpoint aceita texto, arquivo etc — aqui só texto importa.
"""
import os

import httpx

from .base import Channel, SendResult


class Zenvia(Channel):
    key = "SMS"
    label = "SMS (Zenvia)"

    def __init__(self):
        self.token = os.environ.get("ZENVIA_API_TOKEN") or ""
        self.from_ = os.environ.get("ZENVIA_FROM") or ""
        self.base = "https://api.zenvia.com/v2"

    def configured(self) -> tuple[bool, str]:
        faltando = [n for n, v in (("ZENVIA_API_TOKEN", self.token),
                                   ("ZENVIA_FROM", self.from_)) if not v]
        if faltando:
            return False, f"Falta configurar {', '.join(faltando)} no .env."
        return True, ""

    async def state(self) -> dict:
        ok, why = self.configured()
        # Diferente do WhatsApp, a Zenvia não tem sessão para consultar — é uma
        # API HTTP sem estado. "CONNECTED" aqui só diz "há credencial pronta
        # para tentar", não que uma mensagem já foi entregue.
        return {"channel": self.key, "label": self.label, "configured": ok,
                "reason": why, "state": "CONNECTED" if ok else "NOT_CONFIGURED",
                "instance": self.from_ if ok else "", "provider": "zenvia"}

    async def send(self, *, to: str, body: str, subject: str = "", **extra) -> SendResult:
        ok, why = self.configured()
        if not ok:
            return SendResult("SIMULATED", "zenvia", error=why)
        num = (to or "").strip()
        if not num:
            return SendResult("BLOCKED", "zenvia", error="Sem número de telefone.")
        try:
            async with httpx.AsyncClient(base_url=self.base, timeout=30.0,
                                         headers={"X-API-TOKEN": self.token,
                                                  "Content-Type": "application/json"}) as c:
                r = await c.post("/channels/sms/messages", json={
                    "from": self.from_, "to": num,
                    "contents": [{"type": "text", "text": body}]})
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                return SendResult("FAILED", "zenvia",
                                  error=str(data.get("message") or data)[:200], detail=data)
            return SendResult("SENT", "zenvia", provider_id=str(data.get("id", "")), detail=data)
        except Exception as exc:
            return SendResult("FAILED", "zenvia", error=f"{type(exc).__name__}: {exc}"[:200])
