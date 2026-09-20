"""E-mail por SMTP.

O Meetime rastreia abertura e clique; aqui o pixel de abertura fica preparado
(`tracking_pixel`) mas desligado por padrão — abrir imagem remota sem avisar é
justamente o que faz e-mail cair em spam, e é dado pessoal coletado sem
necessidade. Quem quiser liga em `EMAIL_TRACK_OPEN=1`.
"""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from urllib.parse import quote

import anyio

from .base import Channel, SendResult


class Email(Channel):
    key = "EMAIL"
    label = "E-mail (SMTP)"

    def __init__(self):
        # O relay é o mesmo Resend do CapiBLU, que já vive no `.env` com o
        # prefixo `CAPIBLU_SMTP_`. Ler só `SMTP_*` fazia o canal se declarar
        # "não configurado" com a credencial certa dois nomes ao lado — e o
        # e-mail nunca sairia, mesmo com o freio de mão solto.
        env = os.environ.get
        self.host = env("SMTP_HOST") or env("CAPIBLU_SMTP_HOST") or ""
        self.port = int(env("SMTP_PORT") or env("CAPIBLU_SMTP_PORT") or 587)
        self.user = env("SMTP_USER") or env("CAPIBLU_SMTP_USER") or ""
        self.password = env("SMTP_PASSWORD") or env("CAPIBLU_SMTP_SENHA") or ""
        self.from_name = env("SMTP_FROM_NAME") or "BLU Sales Group"
        self.from_addr = env("SMTP_FROM") or env("CAPIBLU_SMTP_DE") or self.user
        self.starttls = (env("SMTP_STARTTLS", "1") != "0")

    def configured(self) -> tuple[bool, str]:
        faltando = [n for n, v in (("SMTP_HOST", self.host), ("SMTP_USER", self.user),
                                   ("SMTP_PASSWORD", self.password)) if not v]
        if faltando:
            return False, ("Falta configurar " + ", ".join(faltando)
                           + " no .env (ou os equivalentes CAPIBLU_SMTP_*).")
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
            out["reason"] = type(exc).__name__
        return out

    def _login_test(self) -> None:
        with smtplib.SMTP(self.host, self.port, timeout=15) as s:
            if self.starttls:
                s.starttls(context=ssl.create_default_context())
            s.login(self.user, self.password)

    def _html(self, body: str, token: str) -> str:
        """Corpo em HTML, com pixel e links reescritos quando há rastreio.

        O rastreio é opcional de propósito (`EMAIL_TRACK=1`): imagem remota e
        link mascarado são justamente o que derruba reputação de domínio, e é
        dado pessoal coletado. Quem liga, liga sabendo.
        """
        html = ("<div style=\"font:14px/1.5 -apple-system,Segoe UI,Roboto,sans-serif\">"
                + body.replace("&", "&amp;").replace("<", "&lt;").replace("\n", "<br>")
                + "</div>")
        if not (token and os.environ.get("EMAIL_TRACK") == "1"):
            return html
        base = (os.environ.get("TRACK_BASE_URL") or "https://bluu.capiblu.net").rstrip("/")
        html = re.sub(
            r'(?<![\w/])(https?://[^\s<>"]+)',
            lambda m: f"{base}/t/c/{token}?u={quote(m.group(1), safe='')}", html)
        return html + f'<img src="{base}/t/o/{token}.gif" width="1" height="1" alt="">'

    def _send_sync(self, to: str, subject: str, body: str, reply_to: str,
                   from_name: str = "", from_addr: str = "", token: str = "") -> str:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = formataddr((from_name or self.from_name, from_addr or self.from_addr))
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
        # A versão em texto fica SEM rastreio — quem lê em texto puro não é
        # contabilizado, e é melhor não contar do que contar errado.
        msg.add_alternative(self._html(body, token), subtype="html")
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
                self._send_sync, to, subject, body, extra.get("reply_to", ""),
                extra.get("from_name", ""), extra.get("from_addr", ""),
                extra.get("tracking_token", ""))
            return SendResult("SENT", self.key, provider_id=mid)
        except Exception as exc:
            return SendResult("FAILED", self.key, error=type(exc).__name__)
