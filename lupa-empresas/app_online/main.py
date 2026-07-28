"""CapiBLU — App Online (front door, roda no Render).

Responsabilidades:
- Servir o frontend estático.
- Autenticação: login (JWT), gestão de usuários (admin) — via `auth.py`.
- PROXY: reencaminha as rotas de dados (/api/* que não sejam auth) para o
  SERVIÇO DE DADOS local, através do Cloudflare Tunnel, com o segredo de proxy.

NÃO guarda base pesada nem chave de API — tudo isso fica no serviço de dados local.

Env:
- DATA_SERVICE_URL   URL do serviço de dados (túnel Cloudflare). Ex.: https://data.capiblu.com.br
- PROXY_SECRET       segredo compartilhado enviado ao serviço de dados (header X-Proxy-Secret)
- JWT_SECRET         segredo do JWT (compartilhe o mesmo valor entre restarts)
- ADMIN_EMAIL / ADMIN_PASSWORD   admin inicial
- AUTH_DB_PATH       caminho do SQLite de usuários (use disco persistente no Render)
"""
import os
import sys

import httpx
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, Response
from fastapi.staticfiles import StaticFiles

# auth.py mora no backend/ — reaproveitamos o mesmo módulo.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
_FRONTEND = os.path.join(os.path.dirname(_HERE), "frontend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))
except Exception:
    pass

import auth as _auth  # noqa: E402

DATA_SERVICE_URL = os.environ.get("DATA_SERVICE_URL", "http://127.0.0.1:8011").strip().rstrip("/")
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()
_TIMEOUT = httpx.Timeout(120.0)
# hop-by-hop / que não devem ser repassados. accept-encoding é forçado a identity
# (a Cloudflare comprimiria a resposta e o body chegaria ilegível ao cliente).
_SKIP_REQ_HEADERS = {"host", "content-length", "connection", "authorization", "accept-encoding"}
_SKIP_RESP_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding"}

app = FastAPI(title="CapiBLU — App Online", version="1.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_auth.init()
app.include_router(_auth.router)

_PUBLIC_API = {"/api/auth/login"}


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    """Exige JWT válido em /api/* (exceto login). Estáticos ficam livres."""
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path in _PUBLIC_API:
        return await call_next(request)
    user = _auth.user_from_bearer(request.headers.get("authorization", ""))
    if not user:
        return JSONResponse({"detail": "Não autenticado."}, status_code=401)
    request.state.user = user
    return await call_next(request)


# Rotas de auth/admin são tratadas AQUI (router acima). O resto de /api é PROXEADO.
_LOCAL_PREFIXES = ("/api/auth/", "/api/admin/")


@app.api_route("/api/{path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
async def proxy(path: str, request: Request):
    full = "/api/" + path
    if any(full.startswith(p) for p in _LOCAL_PREFIXES):
        # já deveria ter casado no router local; se chegou aqui, não existe.
        return JSONResponse({"detail": "Rota não encontrada."}, status_code=404)
    url = f"{DATA_SERVICE_URL}{full}"
    headers = {k: v for k, v in request.headers.items() if k.lower() not in _SKIP_REQ_HEADERS}
    headers["Accept-Encoding"] = "identity"  # evita resposta comprimida pela Cloudflare
    if PROXY_SECRET:
        headers["X-Proxy-Secret"] = PROXY_SECRET
    user = getattr(request.state, "user", None)
    if user:
        headers["X-User-Email"] = user.get("email", "")
        headers["X-User-Role"] = user.get("role", "")
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(request.method, url, params=dict(request.query_params),
                                     content=body, headers=headers)
    except httpx.RequestError as exc:
        return JSONResponse(
            {"detail": f"Serviço de dados indisponível (túnel/PC offline?): {str(exc)[:120]}"},
            status_code=502)
    resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in _SKIP_RESP_HEADERS}
    return Response(content=r.content, status_code=r.status_code,
                    headers=resp_headers, media_type=r.headers.get("content-type"))


# ── Frontend estático ──
@app.get("/")
async def index():
    return FileResponse(os.path.join(_FRONTEND, "index.html"))


app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="static")
