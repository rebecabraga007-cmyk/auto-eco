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
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .config import CAPIBLU_BACKEND, WEB, capiblu_on_path
from .deps import set_session_user

capiblu_on_path()
import auth as capiblu_auth  # noqa: E402  — vive em lupa-empresas/backend

from .capiblu_client import capiblu_app, capiblu_error  # noqa: E402
from .capiblu_client import cota_estourada as capiblu_cota_estourada  # noqa: E402
from .capiblu_client import custa as capiblu_custa  # noqa: E402
from .capiblu_client import identidade as capiblu_client_identidade  # noqa: E402
from .migrate import run as run_migrations  # noqa: E402
from . import agenda, auditoria, feriados, perm, tick  # noqa: E402
from .db import SessionLocal  # noqa: E402
from .routers import (academia, analytics, api_v1, capiblu, core, dialer, envio,  # noqa: E402
                      flow, integracoes, meetime, whatsapp)
from .seed import seed_if_empty  # noqa: E402

app = FastAPI(title="Bluutime", version="0.1.0", docs_url="/swagger")

capiblu_auth.init()
_migrated = run_migrations()
if _migrated:
    print(f"[bluutime] colunas adicionadas: {', '.join(_migrated)}")
seed_if_empty()

# Feriado do ano corrente e do seguinte. A carga é idempotente e o agendador
# depende dela: sem registro, `agenda` só pulava fim de semana.
_db = SessionLocal()
try:
    _ano = agenda.now_local().year
    _novos = feriados.carregar(_db, [_ano, _ano + 1])
    if _novos:
        print(f"[bluutime] {_novos} feriados carregados ({_ano}–{_ano + 1})")
finally:
    _db.close()

app.include_router(capiblu_auth.router)     # /api/auth/*, /api/admin/*
app.include_router(core.router)
app.include_router(flow.router)
app.include_router(dialer.router)
app.include_router(analytics.router)
app.include_router(whatsapp.router)
app.include_router(capiblu.router)
app.include_router(envio.router)
app.include_router(envio.publico)            # /t/o/*, /t/c/* — abertos pelo lead
app.include_router(integracoes.router)
app.include_router(meetime.router)
app.include_router(academia.router)
app.include_router(api_v1.router)             # /api/v1/* — token de API, não sessão

_PUBLIC = {"/api/auth/login", "/api/auth/logout", "/api/auth/emergency-reset",
           # Chamado pelo provedor, nao pelo navegador — autentica por token proprio.
           "/api/whatsapp/webhook"}

_IDENTIDADE = {b"x-user-email", b"x-user-role", b"x-user-grupo", b"x-proxy-secret"}


@app.middleware("http")
async def sessao(request: Request, call_next):
    """Exige login em tudo que não é tela pública e publica o usuário no contexto."""
    path = request.url.path
    protected = path.startswith(("/api/", "/capiblu/api/"))
    user = capiblu_auth.user_from_request(request) if protected or path == "/" else None
    set_session_user(user)

    # /api/v1/* é a API externa: autentica por token de API dentro da rota.
    if protected and path not in _PUBLIC and not path.startswith("/api/v1/"):
        if not user:
            return JSONResponse({"detail": "Não autenticado."}, status_code=401)
        request.state.user = user
        if path.startswith("/capiblu/"):
            # O serviço de dados montado aqui decide admin e grupo pelos headers
            # X-User-*. Os que vieram do navegador são descartados e trocados
            # pelos da sessão — antes, um SDR mandava "X-User-Role: admin".
            limpos = [(k, v) for k, v in request.scope["headers"] if k.lower() not in _IDENTIDADE]
            limpos += [(k.lower().encode(), str(v).encode())
                       for k, v in capiblu_client_identidade(user).items()]
            request.scope["headers"] = limpos
            if capiblu_custa(path[len("/capiblu"):]):
                bloqueio = capiblu_cota_estourada(user)
                if bloqueio:
                    return JSONResponse({"detail": bloqueio}, status_code=429)

    response = await call_next(request)

    # Auditoria no middleware, e não nas rotas: rota nova nasce auditada.
    acao = auditoria.acao_de(path) if protected and user else ""
    if acao:
        db = SessionLocal()
        try:
            await asyncio.to_thread(
                auditoria.registrar, path=path, acao=acao, ator=perm.ator(db),
                status=response.status_code,
                detail=request.method + " " + (request.url.query or "")[:120])
        finally:
            db.close()

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
    """Serve o index carimbando `app.js`/`app.css` com a data do arquivo.

    O HTML pedia `app.js?v=1` fixo: como a chave de cache é a URL inteira, o
    navegador de quem já tinha aberto o Bluutime continuava rodando a versão
    antiga depois de cada deploy, sem jeito de forçar pelo lado do servidor.
    """
    html = open(os.path.join(WEB, "index.html"), encoding="utf-8").read()
    for arquivo in ("app.js", "app.css"):
        try:
            carimbo = int(os.path.getmtime(os.path.join(WEB, arquivo)))
        except OSError:
            continue
        html = html.replace(f"{arquivo}?v=1", f"{arquivo}?v={carimbo}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store, must-revalidate"})


app.mount("/", StaticFiles(directory=WEB, html=True), name="web")
