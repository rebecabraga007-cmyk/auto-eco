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
from starlette.exceptions import HTTPException as StarletteHTTPException

# auth.py mora no backend/ — reaproveitamos o mesmo módulo.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.join(os.path.dirname(_HERE), "backend")
_FRONTEND = os.path.join(os.path.dirname(_HERE), "frontend")
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)
# O app sobe de duas formas: `uvicorn main:app` de dentro de app_online/ e
# `uvicorn app_online.main:app` da raiz (como no Render). No segundo caso este
# diretório não entra no path sozinho, e `import api_v1` quebrava.
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(_HERE), ".env"))
except Exception:
    pass

import api_tokens  # noqa: E402
import auth as _auth  # noqa: E402

DATA_SERVICE_URL = os.environ.get("DATA_SERVICE_URL", "http://127.0.0.1:8011").strip().rstrip("/")
PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()
_TIMEOUT = httpx.Timeout(120.0)
# hop-by-hop / que não devem ser repassados. accept-encoding é forçado a identity
# (a Cloudflare comprimiria a resposta e o body chegaria ilegível ao cliente).
_SKIP_REQ_HEADERS = {"host", "content-length", "connection", "authorization", "accept-encoding"}
_SKIP_RESP_HEADERS = {"content-length", "transfer-encoding", "connection", "content-encoding"}

# /docs é a documentação que escrevemos; o Swagger automático fica em /swagger.
app = FastAPI(title="CapiBLU — App Online", version="1.0.0", docs_url="/swagger")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

_auth.init()
api_tokens.init()
app.include_router(_auth.router)

# API pública v1 (token Bearer, JSON para outros serviços). Importada depois do
# app existir porque o módulo lê DATA_SERVICE_URL/PROXY_SECRET daqui.
from api_v1 import router as _api_v1_router  # noqa: E402
app.include_router(_api_v1_router)

_PUBLIC_API = {"/api/auth/login", "/api/auth/logout"}


@app.exception_handler(StarletteHTTPException)
async def _erro_padronizado(request: Request, exc: StarletteHTTPException):
    """A API pública promete `{"error": {"code", "message"}}`; o resto do app
    (e o frontend) espera `detail`. Traduz só o que sai de /api/v1."""
    if request.url.path.startswith("/api/v1/"):
        codigos = {400: "requisicao_invalida", 401: "nao_autenticado",
                   403: "sem_permissao", 404: "nao_encontrado",
                   429: "limite_atingido", 502: "servico_indisponivel",
                   503: "servico_indisponivel"}
        return JSONResponse(status_code=exc.status_code, content={"error": {
            "code": codigos.get(exc.status_code, "erro"),
            "message": exc.detail if isinstance(exc.detail, str) else "Falha na requisição.",
        }})
    return JSONResponse(status_code=exc.status_code, content={"detail": exc.detail})


@app.middleware("http")
async def _cache_control(request: Request, call_next):
    """Impede cache do shell/JS/CSS (Cloudflare estava servindo auth.js/capiblu.js
    antigos, ignorando o ?v=). Assets estáticos sempre revalidam → todos pegam a
    versão nova. As rotas /api já são dinâmicas."""
    resp = await call_next(request)
    p = request.url.path
    if p == "/" or p.endswith((".html", ".js", ".css")):
        resp.headers["Cache-Control"] = "no-store, must-revalidate"
    return resp


@app.middleware("http")
async def _auth_guard(request: Request, call_next):
    """Exige sessão válida (cookie httpOnly OU header Bearer) em /api/* exceto login/logout."""
    path = request.url.path
    if (request.method == "OPTIONS" or not path.startswith("/api/")
            or path in _PUBLIC_API or path.startswith("/api/v1/")):
        # /api/v1/* é a API pública: autentica por token Bearer no próprio router,
        # não por sessão de navegador.
        return await call_next(request)
    user = _auth.user_from_request(request)
    if not user:
        return JSONResponse({"detail": "Não autenticado."}, status_code=401)
    request.state.user = user
    resp = await call_next(request)
    # Sessão deslizante: quem está usando não é deslogado no meio do trabalho.
    if _auth.deve_renovar(request):
        _auth.renovar_sessao(resp, user, request)
    return resp


# Rotas de auth/admin são tratadas AQUI (router acima). O resto de /api é PROXEADO.
_LOCAL_PREFIXES = ("/api/auth/", "/api/admin/", "/api/v1/")

# Rotas que efetivamente gastam Assertiva/MK — só essas contam pro limite diário.
_CONSULTA_PREFIXES = (
    "/api/person", "/api/phone", "/api/assertiva", "/api/company",
    "/api/dossie", "/api/companies/search", "/api/prospeccao/pessoas",
    "/api/enrich/upload", "/api/enrich/run", "/api/enrich/export",
)

# ... MENOS estas, que só leem base LOCAL (JBR/RFB) e não custam nada a ninguém.
# Elas caíam no prefixo genérico acima e queimavam a cota diária: uma busca por
# nome dispara DUAS chamadas (exata + ampla), então 50 buscas de graça zeravam
# as 100 "consultas" do dia e o usuário levava erro sem entender por quê.
_ROTAS_GRATUITAS = (
    "/api/person/name-search",
    "/api/person/resolve",
    "/api/cnpj/lookup",
    "/api/prospeccao/modelo",
    "/api/prospeccao/modelos",
)


def _custa_consulta(full: str) -> bool:
    if any(full.startswith(g) for g in _ROTAS_GRATUITAS):
        return False
    return any(full.startswith(p) for p in _CONSULTA_PREFIXES)


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
        headers["X-User-Grupo"] = user.get("grupo_id") or ""
        if user.get("role") != "admin" and _custa_consulta(full):
            limite = _auth.limite_efetivo(user)
            consumo = _auth.consumo_hoje(user["id"])
            if consumo >= limite:
                return JSONResponse(
                    {"detail": f"Limite diário de {limite} consultas atingido. Fale com um admin para aumentar."},
                    status_code=429)
            _auth.registrar_consumo(user["id"])
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


# Documentação da API. Aberta de propósito: sem token, ninguém tira dado dela —
# e quem vai integrar precisa ler antes de ter o token na mão.
@app.get("/api-docs", include_in_schema=False)
@app.get("/docs", include_in_schema=False)
async def documentacao_api():
    return FileResponse(os.path.join(_FRONTEND, "api-docs.html"))


app.mount("/", StaticFiles(directory=_FRONTEND, html=True), name="static")
