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


def _campo(data: dict, *nomes, padrao=None):
    """Lê o primeiro nome presente. O wuzapi trocou `Connected`/`LoggedIn`/
    `QRCode`/`Id` por minúsculas entre versões, e a imagem é `latest`: com só
    um dos formatos, o estado aparecia DISCONNECTED com o número conectado."""
    for n in nomes:
        if isinstance(data, dict) and n in data and data[n] not in (None, ""):
            return data[n]
    return padrao

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
            conectado = bool(_campo(data, "connected", "Connected", padrao=False))
            logado = bool(_campo(data, "loggedIn", "LoggedIn", padrao=False))
            out["state"] = ("CONNECTED" if conectado and logado
                            else "PAIRING" if conectado
                            else "DISCONNECTED")
            out["instance"] = _campo(data, "name", "Name", "id", "Id", padrao="")
            # Número pareado, sem o sufixo de aparelho. Nada além disso sai daqui:
            # a resposta do wuzapi traz o TOKEN do usuário, e antes ela ia inteira
            # (`raw`) para qualquer pessoa logada no Bluutime.
            jid = str(_campo(data, "jid", "JID", padrao="") or "")
            out["numero"] = jid.split("@")[0].split(":")[0]
            out["webhookConfigurado"] = bool(_campo(data, "webhook", "Webhook", padrao=""))
        except Exception as exc:
            out["state"] = "UNREACHABLE"
            out["reason"] = type(exc).__name__
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
            return {"ok": False, "error": type(exc).__name__}

    async def qrcode(self) -> dict:
        """QR em base64 para parear. Vazio quando a sessão já está logada."""
        ok, why = self.configured()
        if not ok:
            return {"ok": False, "error": why}
        try:
            async with self._client() as c:
                r = await c.get("/session/qr")
            data = (r.json() or {}).get("data", {}) if r.status_code < 400 else {}
            qr = _campo(data, "QRCode", "qrcode", "qrCode", padrao="")
            return {"ok": bool(qr), "qrcode": qr, "status": r.status_code}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

    async def disconnect(self, *, logout: bool = False) -> dict:
        """Fecha a sessão. Com `logout`, desparea o número de vez.

        São coisas diferentes: desconectar cai e volta sozinho no próximo
        connect; deslogar exige ler o QR de novo no celular.
        """
        ok, why = self.configured()
        if not ok:
            return {"ok": False, "error": why}
        rota = "/session/logout" if logout else "/session/disconnect"
        try:
            async with self._client() as c:
                r = await c.post(rota)
            return {"ok": r.status_code < 400, "status": r.status_code,
                    "body": (r.json() if r.content else {})}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}


    async def configurar_webhook(self, url: str) -> dict:
        """Aponta o webhook do usuário do wuzapi para o Bluutime.

        Estava vazio em produção: nenhuma resposta de lead chegava. Manda os
        dois nomes de campo porque a API mudou entre versões."""
        ok, why = self.configured()
        if not ok:
            return {"ok": False, "error": why}
        try:
            async with self._client() as c:
                r = await c.post("/webhook", json={"webhookURL": url, "webhook": url,
                                                   "events": ["Message"]})
            return {"ok": r.status_code < 400, "status": r.status_code}
        except Exception as exc:
            return {"ok": False, "error": type(exc).__name__}

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
            dados = (r.json() or {}).get("data", {}) or {}
            users = _campo(dados, "Users", "users", padrao=[])
            return bool(users and _campo(users[0], "IsInWhatsapp", "isInWhatsapp", padrao=False))
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
                              provider_id=str(_campo(data.get("data") or {}, "Id", "id", padrao="")),
                              detail=data)
        except Exception as exc:
            return SendResult("FAILED", "wuzapi", error=type(exc).__name__)
