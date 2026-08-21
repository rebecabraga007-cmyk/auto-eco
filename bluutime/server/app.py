"""Bluutime — a operação de prospecção da BLU com a cara da Meetime e os dados
do CapiBLU.

Um processo só:
- login e usuários vêm do `auth.py` do CapiBLU (mesmo JWT, mesmo banco);
- `/capiblu/api/*` é o serviço de dados do CapiBLU montado em processo;
- `/api/*` é o domínio novo (cadências, leads, execução, ligações, métricas);
- `/` serve a SPA no design system da Meetime.
"""
import asyncio
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CAPIBLU_BACKEND, WEB, capiblu_on_path
from .deps import set_session_user

capiblu_on_path()
import auth as capiblu_auth  # noqa: E402  — vive em lupa-empresas/backend

from .capiblu_client import capiblu_app, capiblu_error  # noqa: E402
from .migrate import run as run_migrations  # noqa: E402
from . import tick  # noqa: E402
from .routers import (analytics, capiblu, core, dialer, flow,  # noqa: E402
                      meetime, whatsapp)
from .seed import seed_if_empty  # noqa: E402

app = FastAPI(title="Bluutime", version="0.1.0", docs_url="/swagger")

capiblu_auth.init()
_migrated = run_migrations()
if _migrated:
    print(f"[bluutime] colunas adicionadas: {', '.join(_migrated)}")
seed_if_empty()

app.include_router(capiblu_auth.router)     # /api/auth/*, /api/admin/*
app.include_router(core.router)
app.include_router(flow.router)
app.include_router(dialer.router)
app.include_router(analytics.router)
app.include_router(whatsapp.router)
app.include_router(capiblu.router)
app.include_router(meetime.router)

_PUBLIC = {"/api/auth/login", "/api/auth/logout", "/api/auth/emergency-reset"}

# Rotas do serviço de dados que realmente gastam consulta paga — mesmo recorte
# do proxy de produção (app_online/main.py).
_CONSULTA_PREFIXES = ("/capiblu/api/person", "/capiblu/api/phone",
                      "/capiblu/api/assertiva", "/capiblu/api/company",
                      "/capiblu/api/dossie", "/capiblu/api/enrich/run")
_GRATUITAS = ("/capiblu/api/person/name-search", "/capiblu/api/person/resolve",
              "/capiblu/api/cnpj/lookup", "/capiblu/api/prospeccao/modelo")


def _custa(path: str) -> bool:
    if any(path.startswith(g) for g in _GRATUITAS):
        return False
    return any(path.startswith(p) for p in _CONSULTA_PREFIXES)


@app.middleware("http")
async def sessao(request: Request, call_next):
    """Exige login em tudo que não é tela pública e publica o usuário no contexto."""
    path = request.url.path
    protected = path.startswith(("/api/", "/capiblu/api/"))
    user = capiblu_auth.user_from_request(request) if protected or path == "/" else None
    set_session_user(user)

    if protected and path not in _PUBLIC:
        if not user:
            return JSONResponse({"detail": "Não autenticado."}, status_code=401)
        request.state.user = user
        if user.get("role") != "admin" and _custa(path):
            limite = capiblu_auth.limite_efetivo(user)
            if capiblu_auth.consumo_hoje(user["id"]) >= limite:
                return JSONResponse(
                    {"detail": f"Limite diário de {limite} consultas atingido. "
                               "Fale com um admin para aumentar."}, status_code=429)
            capiblu_auth.registrar_consumo(user["id"])

    response = await call_next(request)
    if user and capiblu_auth.deve_renovar(request):
        capiblu_auth.renovar_sessao(response, user, request)
    if path == "/" or path.endswith((".html", ".js", ".css")):
        response.headers["Cache-Control"] = "no-store, must-revalidate"
    return response


# O serviço de dados do CapiBLU inteiro, em processo. Se a importação falhar
# (base ou chave ausente), o resto do Bluutime continua de pé e a UI mostra o
# motivo em /api/capiblu/status.
_data_app = capiblu_app()
if _data_app is not None:
    app.mount("/capiblu", _data_app)
else:
    print(f"[bluutime] CapiBLU indisponível: {capiblu_error()}")


@app.on_event("startup")
async def _start_tick():
    """O laço que fecha cadência e limpa atividade vencida (server/tick.py)."""
    app.state.tick = asyncio.create_task(tick.loop())


@app.on_event("shutdown")
async def _stop_tick():
    task = getattr(app.state, "tick", None)
    if task:
        task.cancel()


@app.get("/health")
def health():
    return {"status": "ok", "capiblu": capiblu_error() is None}


@app.post("/api/admin/tick")
async def run_tick(request: Request):
    """Roda agora o que o laço faria — para não esperar 5 min ao testar."""
    if (request.state.user or {}).get("role") != "admin":
        raise HTTPException(403, "Só admin.")
    return await asyncio.to_thread(tick.run_once)


@app.get("/")
def index():
    return FileResponse(os.path.join(WEB, "index.html"))


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
