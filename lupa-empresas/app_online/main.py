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


# ── MUDAMOS DE ENDEREÇO ──
# O mesmo código roda em dois lugares: no Hetzner (app.capiblu.net, o de verdade)
# e no Render (www.capiblu.net, o antigo). Com CAPIBLU_ENDERECO_NOVO definida --
# SÓ no Render -- este app deixa de ser usado: toda página vira o aviso de
# mudança (frontend/mudamos.html) e o login é recusado com o novo endereço.
#
# Por que recusar o login e não só trocar a página: o Render tem o PRÓPRIO
# cadastro de usuários (capiblu_auth.db no disco dele). Enquanto alguém ainda
# entrasse aqui, senha trocada ou usuário criado de um lado não existiria do
# outro -- a divergência que motivou a mudança.
#
# /api/v1/* continua respondendo: é a API de máquina, e uma integração que
# ainda aponte para cá não pode quebrar sem aviso só porque a tela mudou.
_ENDERECO_NOVO = os.environ.get("CAPIBLU_ENDERECO_NOVO", "").strip().rstrip("/")


def _pagina_mudamos(host: str) -> str:
    with open(os.path.join(_FRONTEND, "mudamos.html"), encoding="utf-8") as f:
        html = f.read()
    curto = _ENDERECO_NOVO.split("://", 1)[-1]
    return (html.replace("{{ENDERECO_CURTO}}", curto)
                .replace("{{ENDERECO}}", _ENDERECO_NOVO)
                .replace("{{HOST}}", (host or "endereço antigo").split(":")[0]))


@app.middleware("http")
async def _mudamos_de_endereco(request: Request, call_next):
    if not _ENDERECO_NOVO:
        return await call_next(request)
    path = request.url.path
    if path.startswith("/api/v1/") or request.method == "OPTIONS":
        return await call_next(request)
    sem_cache = {"Cache-Control": "no-store, must-revalidate"}
    if path.startswith("/api/"):
        # Aba antiga ainda aberta: a mensagem aparece onde a tela mostraria o erro.
        return JSONResponse(
            {"detail": "O CapiBLU mudou de endereço. Acesse %s e entre por lá."
                       % _ENDERECO_NOVO,
             "endereco_novo": _ENDERECO_NOVO},
            status_code=410, headers=sem_cache)
    return Response(_pagina_mudamos(request.headers.get("host", "")),
                    media_type="text/html; charset=utf-8", headers=sem_cache)


# Rotas de auth/admin são tratadas AQUI (router acima). O resto de /api é PROXEADO.
_LOCAL_PREFIXES = ("/api/auth/", "/api/admin/", "/api/v1/")

# Rotas que efetivamente gastam Assertiva/MK — só essas contam pro limite diário.
_CONSULTA_PREFIXES = (
    "/api/person", "/api/phone", "/api/assertiva", "/api/company",
    "/api/dossie", "/api/companies/search", "/api/prospeccao/pessoas",
    # ENRIQUECIMENTO NAO ENTRA NA COTA -- decisao da Rebeca em 17/set/2026.
    #
    # A cota diaria existe para conter consulta avulsa: a pessoa digitando CPF
    # atras de CPF na tela, sem nada que a faca parar. Planilha e outra coisa.
    # Ela ja nasce com tamanho decidido antes de rodar, ja aparece com o custo
    # em consultas na tela antes de começar, e o gasto total fica no livro do
    # admin de qualquer jeito. Contar as duas com a mesma regua fazia quem
    # trabalha com lista bater no teto no meio do trabalho -- e a contagem
    # ainda dependia do TAMANHO DO LOTE, que e detalhe tecnico: 100 linhas em
    # lotes de 10 contavam 10, as mesmas 100 num job so contariam 1.
    #
    # Fica registrado o que isso custa: enriquecer e o caminho mais caro do
    # sistema, e agora ele nao tem freio automatico. O freio passa a ser o
    # relatorio de uso do painel admin, que e onde o valor em reais aparece.
    # O funil é o endpoint MAIS caro do app: um lote pode disparar dezenas de
    # consultas pagas num clique. Precisa ser nomeado inteiro, e não como
    # "/api/funil", porque `/api/funil/empresa` só lê a base da Receita local
    # e não pode queimar cota de ninguém.
    "/api/funil/resolver",
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


_IDENTIDADE = {"x-user-email", "x-user-role", "x-user-grupo", "x-proxy-secret"}


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
    # Identidade NUNCA vem do navegador: o serviço de dados decide admin, grupo
    # e em nome de quem registrar custo por estes cabeçalhos. Antes eles eram
    # copiados, e como o Starlette entrega a chave em minúsculas, o
    # "x-user-role: admin" do cliente seguia ao lado do "X-User-Role" daqui — e
    # o serviço lia o primeiro. Qualquer usuário virava admin.
    headers = {k: v for k, v in request.headers.items()
               if k.lower() not in _SKIP_REQ_HEADERS and k.lower() not in _IDENTIDADE}
    headers["Accept-Encoding"] = "identity"  # evita resposta comprimida pela Cloudflare
    if PROXY_SECRET:
        headers["X-Proxy-Secret"] = PROXY_SECRET
    # A COTA VIAJA NA RESPOSTA, EM CABECALHO.
    #
    # Assim a tela sabe quanto sobrou sem fazer nenhuma chamada a mais: todo
    # resultado que ela ja pede traz o numero junto. O caso que motivou:
    # alguem bateu no teto e reportou que "a Assertiva caiu" -- ninguem tinha
    # como ver que estava em 100 de 100 antes de travar.
    cota_agora = cota_limite = None
    user = getattr(request.state, "user", None)
    if user:
        headers["X-User-Email"] = user.get("email", "")
        headers["X-User-Role"] = user.get("role", "")
        headers["X-User-Grupo"] = user.get("grupo_id") or ""
        if user.get("role") != "admin" and _custa_consulta(full):
            limite = _auth.limite_efetivo(user)
            consumo = _auth.consumo_hoje(user["id"])
            if consumo >= limite:
                # O 429 TAMBEM leva os cabecalhos: e justamente nele que a
                # tela precisa saber o numero para explicar o bloqueio.
                return JSONResponse(
                    {"detail": f"Limite diário de {limite} consultas atingido. Fale com um admin para aumentar."},
                    status_code=429,
                    headers={"X-Cota-Usada": str(consumo),
                             "X-Cota-Limite": str(limite)})
            cota_agora = _auth.registrar_consumo(user["id"])
            cota_limite = limite
    body = await request.body()
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(request.method, url, params=dict(request.query_params),
                                     content=body, headers=headers)
    except httpx.RequestError as exc:
        return JSONResponse(
            {"detail": f"Serviço de dados indisponível (túnel/PC offline?): {str(exc)[:120]}"},
            status_code=502)
    # ROTA GRATUITA QUE CUSTOU. Com a contingência "Work API Suspenso" ligada,
    # a busca por nome (gratuita em `_ROTAS_GRATUITAS`) passa a consultar a
    # Assertiva. Só o serviço de dados sabe se a chamada pagou -- ele avisa por
    # cabeçalho, e a conta entra depois do fato (não bloqueia esta, mas a
    # próxima paga já encontra a cota atualizada).
    if (user and user.get("role") != "admin" and cota_agora is None
            and r.headers.get("x-consulta-paga") == "1"):
        cota_agora = _auth.registrar_consumo(user["id"])
        cota_limite = _auth.limite_efetivo(user)
    resp_headers = {k: v for k, v in r.headers.items() if k.lower() not in _SKIP_RESP_HEADERS}
    if cota_agora is not None and cota_limite is not None:
        resp_headers["X-Cota-Usada"] = str(cota_agora)
        resp_headers["X-Cota-Limite"] = str(cota_limite)
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
