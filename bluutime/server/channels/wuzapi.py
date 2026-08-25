"""WhatsApp pelo wuzapi — REST em cima do whatsmeow.

Diferenças que importam em relação à Evolution, e que moldaram este arquivo:

1. **Dois níveis de token.** O `admin` cria usuários; cada usuário tem o próprio
   `token`, e é ele que vai no header das chamadas de mensagem. A Evolution tem
   uma `apikey` global só.
2. **Sessão é explícita.** É preciso `POST /session/connect` antes de mandar
   qualquer coisa; a Evolution reconecta sozinha.
3. **O número vai sem sufixo de JID** (`5541999998888`), não `@s.whatsapp.net`.

O whatsmeow é a mesma biblioteca que o WhatsApp Web usa por baixo, então as
regras de versão mínima de cliente valem igual — quando o WhatsApp exigir uma
versão nova, é a imagem do wuzapi que precisa subir.
"""
import os
import re

import httpx

from .base import Channel, SendResult


def to_phone(phone: str) -> str:
    """Número no formato que o wuzapi espera: dígitos com DDI, sem `+` nem JID."""
    d = re.sub(r"\D", "", phone or "")
    if not d:
        return ""
    if d.startswith("55"):
        return d
    if len(d) in (10, 11):
        return "55" + d
    return d


class Wuzapi(Channel):
    key = "WHATSAPP"
    label = "WhatsApp (wuzapi · whatsmeow)"

    def __init__(self):
        self.base = (os.environ.get("WUZAPI_URL") or "").rstrip("/")
        self.token = os.environ.get("WUZAPI_TOKEN") or ""
        self.admin_token = os.environ.get("WUZAPI_ADMIN_TOKEN") or ""

    def configured(self) -> tuple[bool, str]:
        faltando = [n for n, v in (("WUZAPI_URL", self.base),
                                   ("WUZAPI_TOKEN", self.token)) if not v]
        if faltando:
            return False, f"Falta configurar {', '.join(faltando)} no .env."
        return True, ""

    def _client(self) -> httpx.AsyncClient:
        # O header é `token`, sem "Bearer" — o wuzapi rejeita o formato Bearer.
        return httpx.AsyncClient(base_url=self.base, timeout=30.0,
                                 headers={"token": self.token})

    async def state(self) -> dict:
        ok, why = self.configured()
        out = {"channel": self.key, "label": self.label, "configured": ok,
               "reason": why, "state": "NOT_CONFIGURED", "provider": "wuzapi"}
        if not ok:
            return out
        try:
            async with self._client() as c:
                r = await c.get("/session/status")
            if r.status_code == 401:
                out["state"] = "UNAUTHORIZED"
                out["reason"] = "WUZAPI_TOKEN recusado pelo servidor."
                return out
            data = (r.json() or {}).get("data", {}) if r.status_code < 400 else {}
            # `Connected` é o socket com o WhatsApp; `LoggedIn` é a sessão
            # pareada. Conectado sem estar logado significa que o QR expirou ou
            # ninguém escaneou — e é um estado bem diferente de "pronto".
            conectado, logado = bool(data.get("Connected")), bool(data.get("LoggedIn"))
            out["state"] = ("CONNECTED" if conectado and logado
                            else "PAIRING" if conectado
                            else "DISCONNECTED")
            out["instance"] = data.get("Name") or data.get("Id") or ""
            out["raw"] = data
        except Exception as exc:
            out["state"] = "UNREACHABLE"
            out["reason"] = f"{type(exc).__name__}: {exc}"[:160]
        return out

    async def connect(self) -> dict:
        """Abre a sessão. Idempotente — chamar com sessão viva não derruba nada."""
        ok, why = self.configured()
        if not ok:
            return {"ok": False, "error": why}
        try:
            async with self._client() as c:
                r = await c.post("/session/connect",
                                 json={"Subscribe": ["Message"], "Immediate": True})
            return {"ok": r.status_code < 400, "status": r.status_code,
                    "body": (r.json() if r.content else {})}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}

    async def qrcode(self) -> dict:
        """QR em base64 para parear. Vazio quando a sessão já está logada."""
        ok, why = self.configured()
        if not ok:
            return {"ok": False, "error": why}
        try:
            async with self._client() as c:
                r = await c.get("/session/qr")
            data = (r.json() or {}).get("data", {}) if r.status_code < 400 else {}
            return {"ok": bool(data.get("QRCode")), "qrcode": data.get("QRCode", ""),
                    "status": r.status_code}
        except Exception as exc:
            return {"ok": False, "error": f"{type(exc).__name__}: {exc}"[:160]}

    async def check_number(self, phone: str) -> bool | None:
        ok, _ = self.configured()
        num = to_phone(phone)
        if not ok or not num:
            return None
        try:
            async with self._client() as c:
                r = await c.post("/user/check", json={"Phone": [num]})
            if r.status_code >= 400:
                return None
            users = ((r.json() or {}).get("data", {}) or {}).get("Users", [])
            return bool(users and users[0].get("IsInWhatsapp"))
        except Exception:
            return None

    async def send(self, *, to: str, body: str, subject: str = "", **extra) -> SendResult:
        ok, why = self.configured()
        if not ok:
            return SendResult("SIMULATED", "wuzapi", error=why)
        num = to_phone(to)
        if not num:
            return SendResult("BLOCKED", "wuzapi", error="Sem número de telefone.")
        try:
            async with self._client() as c:
                r = await c.post("/chat/send/text", json={"Phone": num, "Body": body})
            data = r.json() if r.content else {}
            if r.status_code >= 400:
                return SendResult("FAILED", "wuzapi",
                                  error=str(data.get("error") or data)[:200], detail=data)
            return SendResult("SENT", "wuzapi",
                              provider_id=str((data.get("data") or {}).get("Id", "")),
                              detail=data)
        except Exception as exc:
            return SendResult("FAILED", "wuzapi", error=f"{type(exc).__name__}: {exc}"[:200])
