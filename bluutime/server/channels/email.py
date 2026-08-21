"""E-mail por SMTP.

O Meetime rastreia abertura e clique; aqui o pixel de abertura fica preparado
(`tracking_pixel`) mas desligado por padrão — abrir imagem remota sem avisar é
justamente o que faz e-mail cair em spam, e é dado pessoal coletado sem
necessidade. Quem quiser liga em `EMAIL_TRACK_OPEN=1`.
"""
import os
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import anyio

from .base import Channel, SendResult


class Email(Channel):
    key = "EMAIL"
    label = "E-mail (SMTP)"

    def __init__(self):
        self.host = os.environ.get("SMTP_HOST") or ""
        self.port = int(os.environ.get("SMTP_PORT") or 587)
        self.user = os.environ.get("SMTP_USER") or ""
        self.password = os.environ.get("SMTP_PASSWORD") or ""
        self.from_name = os.environ.get("SMTP_FROM_NAME") or "BLU Sales Group"
        self.from_addr = os.environ.get("SMTP_FROM") or self.user
        self.starttls = (os.environ.get("SMTP_STARTTLS", "1") != "0")

    def configured(self) -> tuple[bool, str]:
        faltando = [n for n, v in (("SMTP_HOST", self.host), ("SMTP_USER", self.user),
                                   ("SMTP_PASSWORD", self.password)) if not v]
        if faltando:
            return False, f"Falta configurar {', '.join(faltando)} no .env."
        return True, ""

    async def state(self) -> dict:
        ok, why = self.configured()
        out = {"channel": self.key, "label": self.label, "configured": ok,
               "reason": why, "state": "NOT_CONFIGURED",
               "from": self.from_addr, "host": f"{self.host}:{self.port}" if self.host else ""}
        if not ok:
            return out
        try:
            await anyio.to_thread.run_sync(self._login_test)
            out["state"] = "CONNECTED"
        except Exception as exc:
            out["state"] = "UNREACHABLE"
            out["reason"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    def _login_test(self) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=15) as s:
            if self.starttls:
                s.starttls(context=ssl.create_default_context())
            s.login(self.user, self.password)

    def _send_sync(self, to: str, subject: str, body: str, reply_to: str) -> str:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((self.from_name, self.from_addr))
        msg["To"] = to
        if reply_to:
            msg["Reply-To"] = reply_to
        # O Message-ID é guardado para casar a resposta com o lead quando a
        # caixa de entrada for lida (fase seguinte).
        mid = make_msgid()
        msg["Message-ID"] = mid
        msg.set_content(body)
        # O corpo vem de um Template, que é texto puro; a versão HTML só troca
        # quebra de linha por <br> para não exigir dois campos de quem escreve.
        msg.add_alternative(
            "<div style=\"font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif\">"
            + body.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
            + "</div>", subtype="html")
        with smtplib.SMTP(self.host, self.port, timeout=30) as s:
            if self.starttls:
                s.starttls(context=ssl.create_default_context())
            s.login(self.user, self.password)
            s.send_message(msg)
        return mid

    async def send(self, *, to: str, body: str, subject: str = "", **extra) -> SendResult:
        ok, why = self.configured()
        if not ok:
            return SendResult("SIMULATED", self.key, error=why)
        if not (to or "").strip():
            return SendResult("BLOCKED", self.key, error="Lead sem e-mail.")
        if not subject.strip():
            return SendResult("BLOCKED", self.key, error="E-mail sem assunto.")
        try:
            mid = await anyio.to_thread.run_sync(
                self._send_sync, to, subject, body, extra.get("reply_to", ""))
            return SendResult("SENT", self.key, provider_id=mid)
        except Exception as exc:
            return SendResult("FAILED", self.key, error=f"{type(exc).__name__}: {exc}"[:200])
