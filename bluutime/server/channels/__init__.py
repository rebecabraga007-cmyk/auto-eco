"""Os canais por onde uma mensagem sai de verdade.

`ENVIO_LIGADO` é o freio de mão. Ter credencial no `.env` não basta: enquanto
`BLUUTIME_SEND` não for `1`, todo envio volta como `SIMULATED` e fica
registrado como tal. Sem isso, no dia em que alguém colar a chave da Evolution
no `.env`, a cadência inteira dispararia para leads reais sem ninguém ter
decidido isso.
"""
import os

from .base import STATUSES, Channel, SendResult
from .email import Email
from .whatsapp import WhatsApp

_CHANNELS: dict[str, Channel] = {}


def envio_ligado() -> bool:
    return os.environ.get("BLUUTIME_SEND", "").strip() == "1"


def get(channel: str) -> Channel | None:
    """Instância do canal — recriada quando o `.env` muda em desenvolvimento."""
    key = (channel or "").upper()
    if key not in _CHANNELS:
        cls = {"WHATSAPP": WhatsApp, "EMAIL": Email}.get(key)
        if not cls:
            return None
        _CHANNELS[key] = cls()
    return _CHANNELS[key]


def reset() -> None:
    _CHANNELS.clear()


async def send(channel: str, *, to: str, body: str, subject: str = "",
               **extra) -> SendResult:
    """Ponto único de saída. Respeita o freio de mão antes de tudo."""
    ch = get(channel)
    if ch is None:
        return SendResult("BLOCKED", channel, error=f"Canal {channel} não envia mensagem.")
    if not envio_ligado():
        ok, why = ch.configured()
        return SendResult("SIMULATED", ch.key,
                          error="Envio desligado (BLUUTIME_SEND != 1)."
                                + ("" if ok else f" {why}"))
    return await ch.send(to=to, body=body, subject=subject, **extra)


async def states() -> list[dict]:
    out = []
    for key in ("WHATSAPP", "EMAIL"):
        st = await get(key).state()
        st["sendingEnabled"] = envio_ligado()
        out.append(st)
    return out


__all__ = ["STATUSES", "Channel", "SendResult", "envio_ligado", "get",
           "reset", "send", "states"]
