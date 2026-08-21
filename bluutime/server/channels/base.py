"""O contrato que todo canal cumpre.

Uma regra manda no desenho: **nunca fingir que enviou**. Até aqui
`POST /conversations/{id}/messages` gravava a linha e devolvia 200 — quem olhava
a tela via "enviada" sem ninguém ter recebido nada. Aqui todo envio devolve um
`SendResult` com um estado explícito, e "não configurado" é um estado, não um
sucesso silencioso.
"""
from dataclasses import dataclass, field
from datetime import datetime

# SENT      — o provedor aceitou e devolveu um id
# FAILED    — o provedor recusou; `error` diz o porquê
# SIMULATED — envio desligado ou sem credencial: nada saiu, e está registrado
# BLOCKED   — recusado aqui dentro (não perturbe, fora da janela, sem número)
STATUSES = ("SENT", "FAILED", "SIMULATED", "BLOCKED")


@dataclass
class SendResult:
    status: str
    provider: str = ""
    provider_id: str = ""
    error: str = ""
    detail: dict = field(default_factory=dict)
    at: datetime = field(default_factory=datetime.utcnow)

    @property
    def ok(self) -> bool:
        return self.status == "SENT"

    def as_dict(self) -> dict:
        return {"status": self.status, "provider": self.provider,
                "providerId": self.provider_id, "error": self.error,
                "detail": self.detail, "at": self.at.isoformat(timespec="seconds") + "Z"}


class Channel:
    """Implementado por whatsapp.py, email.py e voice.py."""

    key = ""
    label = ""

    def configured(self) -> tuple[bool, str]:
        """(pronto?, motivo se não). O motivo vai direto para a tela."""
        raise NotImplementedError

    async def state(self) -> dict:
        """Estado ao vivo do canal — sem inventar `CONNECTED`."""
        ok, why = self.configured()
        return {"channel": self.key, "label": self.label,
                "configured": ok, "reason": why, "state": "UNKNOWN"}

    async def send(self, *, to: str, body: str, subject: str = "",
                   **extra) -> SendResult:
        raise NotImplementedError
