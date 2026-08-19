"""API pública do CapiBLU (v1) — JSON para outros serviços, autenticada por token.

Desenhada nos moldes da API da Meetime, que o time já conhece:

- `Authorization: Bearer <token>` em toda requisição
- datas em ISO 8601 UTC
- filtros por query string
- paginação por `page` / `limit` (e `offset` quando faz sentido)
- envelope único: `{"data": ..., "meta": {...}}`
- erros com corpo previsível: `{"error": {"code", "message"}}` e HTTP 400/401/403/404/429

Roda no app-online (Render), que é quem tem endereço público. Os dados vêm do
SERVIÇO DE DADOS local pelo túnel — este módulo só traduz para o formato da API
e nunca fala com Assertiva/Mk/RAIS direto.

Escopos:
- `leitura`  → só o que sai de base local/gratuita (empresas, sócios, nome, CPF)
- `consulta` → libera o que gasta consulta paga (telefone, decisores, RAIS,
               parentes, dossiê). Respeita o mesmo limite diário do usuário.
"""

import re
import time
from typing import Any, Optional

import httpx
from fastapi import APIRouter, Body, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse

import api_tokens
import auth as _auth

router = APIRouter(prefix="/api/v1", tags=["API pública v1"])

_TIMEOUT = httpx.Timeout(180.0)

# Rotas do serviço de dados que gastam consulta paga — exigem escopo 'consulta'.
_PAGO = "consulta"


def _erro(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(status_code=status, content={"error": {"code": code, "message": message}})


def _iso(ts: Optional[float]) -> Optional[str]:
    if not ts:
        return None
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts))


def _envelope(data: Any, **meta) -> dict:
    return {"data": data, "meta": {k: v for k, v in meta.items() if v is not None}}


class Contexto:
    """Quem está chamando: token, usuário e escopo."""

    def __init__(self, tok: dict, user: dict):
        self.token_id = tok["token_id"]
        self.escopo = tok["escopo"]
        self.token_nome = tok["nome"]
        self.user = user

    @property
    def pode_gastar(self) -> bool:
        return self.escopo == _PAGO


def _contexto(authorization: str) -> Contexto:
    """Valida o Bearer e devolve o contexto — ou levanta HTTPException."""
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Envie 'Authorization: Bearer <token>'.")
    tok = api_tokens.autenticar(authorization.split(" ", 1)[1].strip())
    if not tok:
        raise HTTPException(status_code=401, detail="Token inválido ou revogado.")
    usuarios = {u["id"]: u for u in _auth.list_users()}
    user = usuarios.get(tok["user_id"])
    if not user or not user.get("ativo"):
        raise HTTPException(status_code=403, detail="Usuário do token está inativo.")
    return Contexto(tok, user)


async def _dados(request: Request, ctx: Contexto, metodo: str, rota: str,
                 params: dict = None, json_body: dict = None, gasta: bool = False) -> dict:
    """Chama o serviço de dados pelo túnel, com o segredo de proxy e a identidade."""
    # Import tardio (evita circular) e tolerante aos dois modos de subir o app.
    try:
        from app_online.main import DATA_SERVICE_URL, PROXY_SECRET
    except ImportError:
        from main import DATA_SERVICE_URL, PROXY_SECRET

    if gasta and not ctx.pode_gastar:
        raise HTTPException(
            status_code=403,
            detail="Este recurso gasta consulta paga e o token tem escopo 'leitura'. "
                   "Gere um token com escopo 'consulta'.")

    if gasta and ctx.user.get("role") != "admin":
        limite = _auth.limite_efetivo(ctx.user)
        if _auth.consumo_hoje(ctx.user["id"]) >= limite:
            raise HTTPException(status_code=429,
                                detail=f"Limite diário de {limite} consultas atingido.")
        _auth.registrar_consumo(ctx.user["id"])

    headers = {"X-User-Email": ctx.user.get("email", ""),
               "X-User-Role": ctx.user.get("role", ""),
               "X-User-Grupo": ctx.user.get("grupo_id") or "",
               "Accept-Encoding": "identity"}
    if PROXY_SECRET:
        headers["X-Proxy-Secret"] = PROXY_SECRET
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            r = await client.request(metodo, f"{DATA_SERVICE_URL}{rota}",
                                     params=params, json=json_body, headers=headers)
    except httpx.RequestError as exc:
        raise HTTPException(status_code=503,
                            detail=f"Serviço de dados indisponível: {str(exc)[:100]}")
    if r.status_code >= 500:
        raise HTTPException(status_code=502, detail="Falha no serviço de dados.")
    try:
        return r.json()
    except ValueError:
        raise HTTPException(status_code=502, detail="Serviço de dados devolveu resposta inválida.")


def _so_digitos(s: str) -> str:
    return re.sub(r"\D", "", s or "")


def _pagina(itens: list, page: int, limit: int) -> tuple[list, dict]:
    total = len(itens)
    ini = max(0, (page - 1) * limit)
    return itens[ini:ini + limit], {"total": total, "page": page, "limit": limit,
                                    "pages": max(1, -(-total // limit))}


# ───────────────────────────── conta ─────────────────────────────

@router.get("/conta", summary="Dados da conta e do token em uso")
async def conta(request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    u = ctx.user
    limite = _auth.limite_efetivo(u)
    usado = _auth.consumo_hoje(u["id"])
    return _envelope({
        "usuario": {"id": u["id"], "nome": u.get("nome"), "email": u["email"],
                    "role": u["role"], "grupo_id": u.get("grupo_id")},
        "token": {"id": ctx.token_id, "nome": ctx.token_nome, "escopo": ctx.escopo},
        "limites": {"consultas_por_dia": limite, "usadas_hoje": usado,
                    "restantes_hoje": max(0, limite - usado),
                    "ilimitado": u["role"] == "admin"},
    }, gerado_em=_iso(time.time()))


# ─────────────────────────── empresas ────────────────────────────

@router.get("/empresas", summary="Busca empresas por filtros (base local da Receita)")
async def empresas(
    request: Request,
    authorization: str = Header(default=""),
    uf: str = Query("", description="Sigla do estado, ex.: MG"),
    municipio: str = Query("", description="Nome do município"),
    cnae: str = Query("", description="Código CNAE (um ou vários separados por vírgula)"),
    porte: str = Query("", description="01 micro · 03 pequeno · 05 demais (médias e grandes)"),
    situacao: str = Query("", description="Situação cadastral, ex.: ATIVA"),
    capital_min: int = Query(0, ge=0),
    capital_max: int = Query(0, ge=0),
    com_telefone: bool = Query(False, description="Só empresas com telefone na Receita"),
    somente_matriz: bool = Query(False),
    texto: str = Query("", description="Busca livre por razão social/nome fantasia"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
):
    ctx = _contexto(authorization)
    filtros = {"uf": uf, "municipio": municipio, "cnae": cnae, "porte": porte,
               "situacao": situacao, "capital_min": capital_min, "capital_max": capital_max,
               "com_telefone": com_telefone, "somente_matriz": somente_matriz, "texto": texto}
    filtros = {k: v for k, v in filtros.items() if v not in ("", 0, False)}
    r = await _dados(request, ctx, "POST", "/api/companies/search",
                     json_body={"filtros": filtros, "limite": limit, "offset": (page - 1) * limit})
    if r.get("status") != "ok":
        return _erro(400, "busca_falhou", r.get("message") or "Não foi possível buscar empresas.")
    empresas_ = r.get("empresas") or []
    return _envelope([{
        "cnpj": _so_digitos(e.get("cnpj")),
        "razao_social": e.get("razao_social"),
        "nome_fantasia": e.get("nome_fantasia"),
        "municipio": e.get("municipio"), "uf": e.get("uf"),
        "porte": e.get("porte"), "situacao": e.get("situacao"),
        "cnae": e.get("cnae"), "cnae_codigo": e.get("cnae_codigo"),
        "capital_social": e.get("capital_social"),
    } for e in empresas_],
        total=r.get("total"), page=page, limit=limit, fonte=r.get("fonte"))


@router.get("/empresas/{cnpj}", summary="Cadastro completo de uma empresa")
async def empresa(cnpj: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}")
    if r.get("status") != "ok":
        return _erro(404, "nao_encontrada", r.get("message") or "Empresa não encontrada.")
    return _envelope(r.get("company"), fonte="Receita Federal")


@router.get("/empresas/{cnpj}/socios", summary="Quadro de sócios, com CPF resolvido quando possível")
async def socios(cnpj: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}")
    if r.get("status") != "ok":
        return _erro(404, "nao_encontrada", "Empresa não encontrada.")
    qsa = (r.get("company") or {}).get("qsa") or []
    return _envelope([{
        "nome": s.get("nome_socio"),
        "qualificacao": s.get("qualificacao_socio"),
        "cpf": s.get("cpf_completo") or None,
        "cpf_mascarado": s.get("cnpj_cpf_do_socio"),
        "data_entrada": s.get("data_entrada_sociedade"),
        "faixa_etaria": s.get("faixa_etaria"),
    } for s in qsa], total=len(qsa), fonte="Receita Federal (QSA)")


@router.get("/empresas/{cnpj}/decisores",
            summary="Possíveis decisores com cargo e nível de decisão (gasta consulta)")
async def decisores(cnpj: str, request: Request, authorization: str = Header(default=""),
                    nivel: str = Query("", description="Filtrar por nível: 1, 2 ou 3"),
                    cargo: str = Query("", description="Filtrar por cargo, ex.: diretor"),
                    page: int = Query(1, ge=1), limit: int = Query(50, ge=1, le=200)):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/decisores", gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso="A base não tem decisor para este CNPJ.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha ao consultar decisores.")
    lista = r.get("decisores") or []
    if nivel:
        lista = [d for d in lista if str(d.get("nivel")) == nivel.strip()]
    if cargo:
        alvo = cargo.strip().lower()
        lista = [d for d in lista if alvo in (d.get("cargo") or "").lower()]
    itens, meta = _pagina(lista, page, limit)
    return _envelope(itens, **meta, por_nivel=r.get("por_nivel"),
                     cadastro=r.get("cadastro_assertiva"), fonte="Assertiva Localize")


@router.get("/empresas/{cnpj}/funcionarios",
            summary="Vínculos empregatícios declarados na RAIS (gasta consulta)")
async def funcionarios(cnpj: str, request: Request, authorization: str = Header(default=""),
                       situacao: str = Query("", description="ativos | desligados"),
                       page: int = Query(1, ge=1), limit: int = Query(100, ge=1, le=500)):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/vinculos", gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso="Nenhum vínculo declarado na RAIS para este CNPJ.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha ao consultar a RAIS.")
    lista = r.get("vinculos") or []
    if situacao == "ativos":
        lista = [v for v in lista if v.get("ativo")]
    elif situacao == "desligados":
        lista = [v for v in lista if not v.get("ativo")]
    itens, meta = _pagina(lista, page, limit)
    return _envelope(itens, **meta, referencia=r.get("referencia"),
                     ativos=r.get("ativos"), desligados=r.get("desligados"),
                     hierarquia=r.get("hierarquia"),
                     fonte="RAIS · Ministério do Trabalho")


@router.get("/empresas/{cnpj}/contatos",
            summary="Contatos prontos para abordagem: sócios e decisores com telefone (gasta consulta)")
async def contatos(cnpj: str, request: Request, authorization: str = Header(default=""),
                   incluir_decisores: bool = Query(True),
                   cargos: str = Query("", description="Filtro de cargo dos decisores"),
                   max_decisores: int = Query(3, ge=0, le=20),
                   max_telefones: int = Query(3, ge=1, le=10),
                   tipo_telefone: str = Query("celular", description="celular | celular_fixo | todos"),
                   fonte_telefone: str = Query("assertiva", description="assertiva | mk")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/leads", params={
        "decisores": str(incluir_decisores).lower(), "decisores_cargos": cargos,
        "max_decisores": max_decisores, "max_tel": max_telefones,
        "modo_tel": tipo_telefone, "fonte_tel": fonte_telefone,
    }, gasta=True)
    if r.get("status") != "ok":
        return _erro(404, "nao_encontrada", r.get("message") or "Empresa não encontrada.")
    contatos_ = r.get("contatos") or []
    return _envelope([{
        "tipo": c.get("tipo"), "nome": c.get("nome"), "cargo": c.get("cargo"),
        "nivel_decisao": c.get("nivel"), "area": c.get("area"),
        "cpf": c.get("cpf") or None, "fonte_cargo": c.get("fonte_cargo"),
        "telefones": [{"numero": t.get("raw"), "formatado": t.get("display"),
                       "categoria": t.get("categoria"), "whatsapp": t.get("whatsapp")}
                      for t in (c.get("telefones") or [])],
    } for c in contatos_],
        total=len(contatos_), empresa=r.get("empresa"),
        decisores=r.get("decisores_info"))


@router.get("/empresas/{cnpj}/conexoes",
            summary="Sócios, decisores e empresas ligadas, com telefone (gasta consulta)")
async def conexoes(cnpj: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/conexoes", gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso="Nenhuma conexão encontrada.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha ao consultar conexões.")
    return _envelope(r.get("conexoes") or [], total=r.get("total"),
                     por_tipo=r.get("por_tipo"), fonte="Assertiva Localize")


# ─────────────────────────── pessoas ─────────────────────────────

@router.get("/pessoas", summary="Busca pessoas por nome (base local)")
async def pessoas(request: Request, authorization: str = Header(default=""),
                  nome: str = Query(..., min_length=3, description="Nome a buscar"),
                  ampla: bool = Query(False, description="true = nomes compostos parecidos"),
                  page: int = Query(1, ge=1), limit: int = Query(40, ge=1, le=200)):
    ctx = _contexto(authorization)
    r = await _dados(request, ctx, "GET", "/api/person/name-search", params={
        "q": nome, "broad": str(ampla).lower(), "limit": limit, "offset": (page - 1) * limit})
    if r.get("status") != "ok":
        return _erro(400, "busca_falhou", r.get("message") or "Falha na busca por nome.")
    return _envelope(r.get("pessoas") or [], total=r.get("total"), page=page, limit=limit,
                     devolvidos=r.get("returned"), fonte="Base local de CPF")


@router.get("/pessoas/{cpf}", summary="Dados cadastrais de uma pessoa (base local)")
async def pessoa(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}")
    if r.get("status") == "not_found" or not r.get("pessoa"):
        return _erro(404, "nao_encontrada", "CPF não encontrado na base.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("pessoa"), fonte="Base local de CPF")


@router.get("/pessoas/{cpf}/telefones", summary="Telefones de uma pessoa (gasta consulta)")
async def telefones_pessoa(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}/mk", gasta=True)
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha ao consultar telefones.")
    d = r.get("data") or {}
    return _envelope([{"numero": t.get("telefone") or t.get("numero"),
                       "tipo": t.get("tipo"), "whatsapp": t.get("whatsapp")}
                      for t in (d.get("telefones") or [])],
                     total=len(d.get("telefones") or []), fonte="Mk Buscas")


@router.get("/pessoas/{cpf}/vinculos",
            summary="Onde a pessoa trabalha ou trabalhou, pela RAIS (gasta consulta)")
async def vinculos_pessoa(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}/vinculos", gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso="Nenhum vínculo declarado na RAIS para este CPF.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha ao consultar a RAIS.")
    return _envelope(r.get("vinculos") or [], total=r.get("total"), nome=r.get("nome"),
                     referencia=r.get("referencia"), ativos=r.get("ativos"),
                     fonte="RAIS · Ministério do Trabalho")


@router.get("/pessoas/{cpf}/parentes",
            summary="Parentes e conexões de uma pessoa (gasta 2 consultas)")
async def parentes(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 dígitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}/parentes", gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso="Nenhum parente ou conexão encontrada.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("parentes") or [], total=r.get("total"),
                     com_telefone=r.get("com_telefone"), por_relacao=r.get("por_relacao"),
                     fonte="Assertiva Localize")


# ────────────────────────── telefones ────────────────────────────

@router.get("/telefones/{numero}", summary="De quem é este telefone (gasta consulta)")
async def telefone_reverso(numero: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    tel = _so_digitos(numero)
    if len(tel) not in (10, 11):
        return _erro(400, "telefone_invalido", "Telefone deve ter 10 ou 11 dígitos com DDD.")
    r = await _dados(request, ctx, "GET", f"/api/phone/{tel}/reverse", gasta=True)
    if r.get("status") != "ok":
        return _erro(404, "nao_encontrado", r.get("message") or "Nenhum vínculo para este número.")
    return _envelope(r.get("data") or r, fonte="Telefone reverso")


# ──────────────────────────── consumo ────────────────────────────

@router.get("/consumo", summary="Quanto este usuário consumiu no período")
async def consumo(request: Request, authorization: str = Header(default=""),
                  dias: int = Query(30, ge=1, le=365)):
    ctx = _contexto(authorization)
    u = ctx.user
    limite = _auth.limite_efetivo(u)
    usado = _auth.consumo_hoje(u["id"])
    corpo = {
        "hoje": {"usadas": usado, "limite": limite, "restantes": max(0, limite - usado)},
        "tokens": [t for t in api_tokens.listar(u["id"])],
    }
    if u.get("role") == "admin":
        r = await _dados(request, ctx, "GET", "/api/custos/total", params={"dias": dias})
        if isinstance(r, dict) and r.get("status") == "ok":
            corpo["periodo"] = r.get("periodo")
            corpo["assertiva"] = {k: r["assertiva"].get(k) for k in
                                  ("total_registros", "custo_estimado", "por_funcionalidade")}
            corpo["capiblu"] = {"chamadas": r["interno"]["chamadas"],
                                "custo_estimado": r["interno"]["custo_estimado"]}
    return _envelope(corpo, gerado_em=_iso(time.time()))


# ═══════════════════════════════════════════════════════════════════
#  COBERTURA TOTAL — tudo o que a plataforma alcança, exposto na API.
#  Os blocos acima entregam dados já tratados; daqui em diante vêm o
#  JSON BRUTO das fontes e as operações compostas.
# ═══════════════════════════════════════════════════════════════════

@router.get("/lookups/{tipo}", summary="Listas de apoio para montar filtros (não gasta)")
async def lookups(tipo: str, request: Request, authorization: str = Header(default="")):
    """tipo: cnae · natureza · municipio · pais · qualificacao · motivo"""
    ctx = _contexto(authorization)
    if tipo not in ("cnae", "natureza", "municipio", "pais", "qualificacao", "motivo"):
        return _erro(400, "tipo_invalido",
                     "tipo deve ser cnae, natureza, municipio, pais, qualificacao ou motivo.")
    r = await _dados(request, ctx, "GET", "/api/cnpj/lookup", params={"tipo": tipo})
    itens = r.get("itens") or []
    return _envelope(itens, total=len(itens), tipo=tipo, fonte="Receita Federal")


@router.get("/fontes", summary="Fontes de dados ativas e o que cada uma entrega")
async def fontes(request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    ast = await _dados(request, ctx, "GET", "/api/assertiva/status")
    return _envelope({
        "receita_federal": {"ativa": True, "custo": "gratis",
                            "entrega": "cadastro, socios, CNAE, capital, endereco"},
        "base_local_cpf": {"ativa": True, "custo": "gratis",
                           "entrega": "nome, nascimento, sexo, CPF por nome"},
        "assertiva": {"ativa": bool(ast.get("enabled")), "custo": "por consulta",
                      "finalidade_padrao": ast.get("finalidade_padrao"),
                      "entrega": "cadastro completo, telefones, e-mails, enderecos, "
                                 "decisores, parentes, conexoes"},
        "rais": {"ativa": True, "custo": "por consulta",
                 "entrega": "vinculos empregaticios por CNPJ e por CPF"},
        "mk_buscas": {"ativa": True, "custo": "por consulta",
                      "entrega": "telefones, enderecos, renda, score, parentes, vizinhos"},
        "linkedin": {"ativa": True, "custo": "por consulta",
                     "entrega": "funcionarios com cargo — cobertura irregular"},
    }, gerado_em=_iso(time.time()))


# ─────────── JSON bruto das fontes (todos os campos, sem recorte) ───────────

@router.get("/empresas/{cnpj}/assertiva",
            summary="JSON completo da Assertiva para o CNPJ (gasta consulta)")
async def empresa_assertiva(cnpj: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 digitos.")
    r = await _dados(request, ctx, "GET", "/api/assertiva/cnpj", params={"cnpj": doc}, gasta=True)
    if r.get("status") == "not_found":
        return _erro(404, "nao_encontrada", r.get("message") or "CNPJ nao localizado.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("data"), fonte="Assertiva Localize", bruto=True)


@router.get("/pessoas/{cpf}/assertiva",
            summary="JSON completo da Assertiva para o CPF (gasta consulta)")
async def pessoa_assertiva(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 digitos.")
    r = await _dados(request, ctx, "GET", "/api/assertiva/cpf", params={"cpf": doc}, gasta=True)
    if r.get("status") == "not_found":
        return _erro(404, "nao_encontrada", r.get("message") or "CPF nao localizado.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("data"), fonte="Assertiva Localize", bruto=True)


@router.get("/pessoas/{cpf}/mk",
            summary="Perfil completo na Mk: renda, score, enderecos, parentes, vizinhos (gasta)")
async def pessoa_mk(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 digitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}/mk", gasta=True)
    if r.get("status") == "unavailable":
        return _erro(503, "fonte_indisponivel", r.get("message") or "Mk Buscas nao configurada.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("data"), fonte="Mk Buscas", bruto=True)


@router.get("/pessoas/{cpf}/contatos",
            summary="Telefones e e-mails da pessoa pela Serasa (gasta consulta)")
async def pessoa_contatos_serasa(cpf: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 digitos.")
    r = await _dados(request, ctx, "GET", f"/api/person/{doc}/contacts", gasta=True)
    if r.get("status") == "unavailable":
        return _erro(503, "fonte_indisponivel", r.get("message") or "Serasa nao configurada.")
    return _envelope(r, fonte="Serasa Infomais")


@router.get("/empresas/{cnpj}/contatos-serasa",
            summary="Telefones e e-mails da empresa pela Serasa (gasta consulta)")
async def empresa_contatos_serasa(cnpj: str, request: Request,
                                  authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 digitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/contacts", gasta=True)
    if r.get("status") == "unavailable":
        return _erro(503, "fonte_indisponivel", r.get("message") or "Serasa nao configurada.")
    return _envelope(r, fonte="Serasa Infomais")


@router.get("/empresas/{cnpj}/linkedin",
            summary="Funcionarios com cargo pelo LinkedIn (lento, cobertura irregular)")
async def empresa_linkedin(cnpj: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 digitos.")
    r = await _dados(request, ctx, "GET", f"/api/company/{doc}/employees", gasta=True)
    lista = r.get("employees") or []
    return _envelope(lista, total=len(lista), empresa=r.get("company"),
                     aviso=r.get("message") or None, fonte="LinkedIn via Bright Data")


# ─────────────── outras entradas da Assertiva ───────────────

@router.get("/assertiva/telefone/{numero}",
            summary="Dono do telefone pela Assertiva (gasta consulta)")
async def assertiva_telefone(numero: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    tel = _so_digitos(numero)
    if len(tel) not in (10, 11):
        return _erro(400, "telefone_invalido", "Telefone deve ter 10 ou 11 digitos com DDD.")
    r = await _dados(request, ctx, "GET", "/api/assertiva/telefone",
                     params={"telefone": tel}, gasta=True)
    if r.get("status") == "not_found":
        return _erro(404, "nao_encontrado", r.get("message") or "Numero nao localizado.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("data"), fonte="Assertiva Localize", bruto=True)


@router.get("/assertiva/email/{email}",
            summary="Quem esta por tras do e-mail, pela Assertiva (gasta consulta)")
async def assertiva_email(email: str, request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    if "@" not in email:
        return _erro(400, "email_invalido", "E-mail invalido.")
    r = await _dados(request, ctx, "GET", "/api/assertiva/email",
                     params={"email": email}, gasta=True)
    if r.get("status") == "not_found":
        return _erro(404, "nao_encontrado", r.get("message") or "E-mail nao localizado.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na consulta.")
    return _envelope(r.get("data"), fonte="Assertiva Localize", bruto=True)


@router.post("/pessoas/busca-avancada",
             summary="Busca por nome e/ou endereco na Assertiva (gasta consulta)")
async def busca_avancada(request: Request, authorization: str = Header(default=""),
                         corpo: dict = Body(default={})):
    ctx = _contexto(authorization)
    filtros = {k: v for k, v in (corpo.get("filtros") or corpo).items() if v not in ("", None)}
    if not filtros:
        return _erro(400, "filtros_obrigatorios", "Informe ao menos um filtro.")
    r = await _dados(request, ctx, "POST", "/api/assertiva/nome",
                     json_body={"filtros": filtros}, gasta=True)
    if r.get("status") == "not_found":
        return _envelope([], total=0, aviso=r.get("message") or "Nada encontrado.")
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha na busca.")
    return _envelope(r.get("data"), fonte="Assertiva Localize", bruto=True)


# ─────────────── validacao de telefone ───────────────

@router.get("/telefones/{numero}/pertence/{documento}",
            summary="Confirma se o telefone e de determinado CPF/CNPJ (gasta consulta)")
async def telefone_pertence(numero: str, documento: str, request: Request,
                            authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    tel, doc = _so_digitos(numero), _so_digitos(documento)
    if len(tel) not in (10, 11):
        return _erro(400, "telefone_invalido", "Telefone deve ter 10 ou 11 digitos com DDD.")
    if len(doc) not in (11, 14):
        return _erro(400, "documento_invalido", "Documento deve ser CPF (11) ou CNPJ (14).")
    r = await _dados(request, ctx, "GET", f"/api/phone/{tel}/pertence/{doc}", gasta=True)
    if r.get("status") == "no_access":
        return _erro(503, "sem_acesso_modulo",
                     r.get("message") or "Chave sem acesso ao telefone reverso.")
    return _envelope({"telefone": tel, "documento": doc,
                      "pertence": bool(r.get("atrelado")), "nome": r.get("nome"),
                      "compartilhado": bool(r.get("alerta_compartilhado")),
                      "total_vinculos": r.get("total")}, fonte="Telefone reverso")


# ─────────────── visoes compostas: TUDO de uma vez ───────────────

@router.get("/empresas/{cnpj}/completo",
            summary="Tudo o que o CapiBLU sabe da empresa, numa chamada (gasta varias consultas)")
async def empresa_completo(cnpj: str, request: Request, authorization: str = Header(default=""),
                           incluir: str = Query(
                               "cadastro,socios,decisores,funcionarios,conexoes,assertiva",
                               description="Blocos separados por virgula. Disponiveis: cadastro, "
                                           "socios, decisores, funcionarios, conexoes, assertiva, linkedin")):
    """Um bloco falho nao derruba os outros: `meta.blocos` diz o que veio e
    `meta.falhas` diz o que nao veio e por que. Cada bloco pago gasta consulta —
    peca so o que for usar."""
    ctx = _contexto(authorization)
    doc = _so_digitos(cnpj)
    if len(doc) != 14:
        return _erro(400, "cnpj_invalido", "CNPJ deve ter 14 digitos.")
    validos = ("cadastro", "socios", "decisores", "funcionarios", "conexoes", "assertiva", "linkedin")
    pedidos = [b.strip() for b in (incluir or "").split(",") if b.strip()]
    fora = [b for b in pedidos if b not in validos]
    if fora:
        return _erro(400, "bloco_invalido", f"Blocos desconhecidos: {', '.join(fora)}.")

    out, blocos, falhas = {}, [], {}

    async def bloco(nome, rota, gasta, params=None, extrai=None):
        if nome not in pedidos:
            return
        try:
            r = await _dados(request, ctx, "GET", rota, params=params, gasta=gasta)
        except HTTPException as exc:
            falhas[nome] = exc.detail
            return
        if r.get("status") == "ok":
            out[nome] = extrai(r) if extrai else r
            blocos.append(nome)
        else:
            falhas[nome] = r.get("message") or r.get("status") or "sem dados"

    if "cadastro" in pedidos or "socios" in pedidos:
        try:
            emp = await _dados(request, ctx, "GET", f"/api/company/{doc}")
            if emp.get("status") == "ok":
                c = emp.get("company") or {}
                if "cadastro" in pedidos:
                    out["cadastro"] = c
                    blocos.append("cadastro")
                if "socios" in pedidos:
                    out["socios"] = c.get("qsa") or []
                    blocos.append("socios")
            else:
                falhas["cadastro"] = emp.get("message") or "empresa nao encontrada"
        except HTTPException as exc:
            falhas["cadastro"] = exc.detail

    await bloco("decisores", f"/api/company/{doc}/decisores", True,
                extrai=lambda r: {"total": r.get("total"), "por_nivel": r.get("por_nivel"),
                                  "cadastro_assertiva": r.get("cadastro_assertiva"),
                                  "lista": r.get("decisores") or []})
    await bloco("funcionarios", f"/api/company/{doc}/vinculos", True,
                extrai=lambda r: {"total": r.get("total"), "ativos": r.get("ativos"),
                                  "desligados": r.get("desligados"),
                                  "referencia": r.get("referencia"),
                                  "hierarquia": r.get("hierarquia"),
                                  "lista": r.get("vinculos") or []})
    await bloco("conexoes", f"/api/company/{doc}/conexoes", True,
                extrai=lambda r: {"total": r.get("total"), "por_tipo": r.get("por_tipo"),
                                  "lista": r.get("conexoes") or []})
    await bloco("linkedin", f"/api/company/{doc}/employees", True,
                extrai=lambda r: {"lista": r.get("employees") or [], "aviso": r.get("message")})
    await bloco("assertiva", "/api/assertiva/cnpj", True, params={"cnpj": doc},
                extrai=lambda r: r.get("data"))

    return _envelope(out, cnpj=doc, blocos=blocos, falhas=falhas or None,
                     gerado_em=_iso(time.time()))


@router.get("/pessoas/{cpf}/completo",
            summary="Tudo o que o CapiBLU sabe da pessoa, numa chamada (gasta varias consultas)")
async def pessoa_completo(cpf: str, request: Request, authorization: str = Header(default=""),
                          incluir: str = Query(
                              "cadastro,mk,assertiva,vinculos,parentes",
                              description="Blocos: cadastro, mk, assertiva, vinculos, parentes, serasa")):
    ctx = _contexto(authorization)
    doc = _so_digitos(cpf)
    if len(doc) != 11:
        return _erro(400, "cpf_invalido", "CPF deve ter 11 digitos.")
    validos = ("cadastro", "mk", "assertiva", "vinculos", "parentes", "serasa")
    pedidos = [b.strip() for b in (incluir or "").split(",") if b.strip()]
    fora = [b for b in pedidos if b not in validos]
    if fora:
        return _erro(400, "bloco_invalido", f"Blocos desconhecidos: {', '.join(fora)}.")

    out, blocos, falhas = {}, [], {}

    async def bloco(nome, rota, gasta, params=None, extrai=None):
        if nome not in pedidos:
            return
        try:
            r = await _dados(request, ctx, "GET", rota, params=params, gasta=gasta)
        except HTTPException as exc:
            falhas[nome] = exc.detail
            return
        if r.get("status") == "ok":
            out[nome] = extrai(r) if extrai else r
            blocos.append(nome)
        else:
            falhas[nome] = r.get("message") or r.get("status") or "sem dados"

    await bloco("cadastro", f"/api/person/{doc}", False, extrai=lambda r: r.get("pessoa"))
    await bloco("mk", f"/api/person/{doc}/mk", True, extrai=lambda r: r.get("data"))
    await bloco("assertiva", "/api/assertiva/cpf", True, params={"cpf": doc},
                extrai=lambda r: r.get("data"))
    await bloco("vinculos", f"/api/person/{doc}/vinculos", True,
                extrai=lambda r: {"total": r.get("total"), "nome": r.get("nome"),
                                  "referencia": r.get("referencia"),
                                  "lista": r.get("vinculos") or []})
    await bloco("parentes", f"/api/person/{doc}/parentes", True,
                extrai=lambda r: {"total": r.get("total"), "por_relacao": r.get("por_relacao"),
                                  "lista": r.get("parentes") or []})
    await bloco("serasa", f"/api/person/{doc}/contacts", True)

    return _envelope(out, cpf=doc, blocos=blocos, falhas=falhas or None,
                     gerado_em=_iso(time.time()))


# ─────────────── prospeccao em lote ───────────────

@router.post("/prospeccao/cobertura",
             summary="Mede em quantas empresas existe decisor, sem puxar telefone (2 por CNPJ)")
async def cobertura(request: Request, authorization: str = Header(default=""),
                    corpo: dict = Body(default={})):
    """Body: {cnpjs: [...], cargos: "diretor,gerente"}. Maximo 60 CNPJs."""
    ctx = _contexto(authorization)
    cnpjs = [c for c in (_so_digitos(x) for x in (corpo.get("cnpjs") or [])) if len(c) == 14]
    if not cnpjs:
        return _erro(400, "cnpjs_obrigatorios", "Envie ao menos um CNPJ valido em 'cnpjs'.")
    if not ctx.pode_gastar:
        return _erro(403, "sem_permissao",
                     "O teste consulta a Assertiva; use token com escopo 'consulta'.")
    r = await _dados(request, ctx, "POST", "/api/prospeccao/cobertura-decisores",
                     json_body={"cnpjs": cnpjs, "cargos": corpo.get("cargos") or ""})
    if r.get("status") != "ok":
        return _erro(400, "consulta_falhou", r.get("message") or "Falha no teste de cobertura.")
    return _envelope(r.get("detalhe") or [], testadas=r.get("testadas"),
                     com_decisor=r.get("com_decisor"), taxa=r.get("taxa"),
                     taxa_cargo=r.get("taxa_cargo"), media_decisores=r.get("media_decisores"),
                     cargos_encontrados=r.get("cargos_encontrados"),
                     consultas_gastas=r.get("consultas_gastas"))


@router.post("/prospeccao/pessoas",
             summary="Busca socios/pessoas por filtros na base local (nao gasta)")
async def prospeccao_pessoas(request: Request, authorization: str = Header(default=""),
                             corpo: dict = Body(default={})):
    ctx = _contexto(authorization)
    r = await _dados(request, ctx, "POST", "/api/prospeccao/pessoas", json_body={
        "filtros": corpo.get("filtros") or {},
        "limite": min(int(corpo.get("limite") or 20), 200),
        "offset": int(corpo.get("offset") or 0)})
    if r.get("status") != "ok":
        return _erro(400, "busca_falhou", r.get("message") or "Falha na busca.")
    return _envelope(r.get("pessoas") or [], total=r.get("total"), fonte="Base local")


@router.get("/enriquecimento/campos",
            summary="Catalogo de campos disponiveis para enriquecimento (nao gasta)")
async def enriquecimento_campos(request: Request, authorization: str = Header(default="")):
    ctx = _contexto(authorization)
    r = await _dados(request, ctx, "GET", "/api/enrich/catalog")
    return _envelope(r.get("grupos") or r.get("catalogo") or r, fonte="Catalogo de enriquecimento")


@router.post("/enriquecimento",
             summary="Enriquece uma lista de CNPJs com os campos escolhidos (gasta por linha)")
async def enriquecimento(request: Request, authorization: str = Header(default=""),
                         corpo: dict = Body(default={})):
    """A versao em API do 'Minha planilha': manda CNPJs e campos, recebe uma
    linha por CNPJ ja enriquecida, sem subir arquivo.

    Body: {cnpjs: [...], campos: ["rfb_razao_social", "as_empresa_tel", ...]}.
    Catalogo em GET /enriquecimento/campos. Maximo 200 CNPJs por chamada.
    """
    ctx = _contexto(authorization)
    cnpjs = [c for c in (_so_digitos(x) for x in (corpo.get("cnpjs") or [])) if len(c) == 14][:200]
    campos = [c for c in (corpo.get("campos") or []) if isinstance(c, str)]
    if not cnpjs:
        return _erro(400, "cnpjs_obrigatorios", "Envie ao menos um CNPJ valido em 'cnpjs'.")
    if not campos:
        return _erro(400, "campos_obrigatorios",
                     "Escolha ao menos um campo. Veja GET /enriquecimento/campos.")
    paga = any(c.startswith(("as_", "so_", "vf_")) for c in campos)
    if paga and not ctx.pode_gastar:
        return _erro(403, "sem_permissao",
                     "Campos de Assertiva, socios ou validacao gastam consulta; "
                     "use token com escopo 'consulta'.")
    linhas, ignorados = [], []
    for doc in cnpjs:
        r = await _dados(request, ctx, "POST", "/api/enrich/linha",
                         json_body={"cnpj": doc, "campos": campos}, gasta=paga)
        ignorados = r.get("ignorados") or ignorados
        linhas.append({"cnpj": doc, **(r.get("dados") or {})})
    # Todos os campos errados = pedido sem sentido; devolver linha vazia esconderia o erro.
    if ignorados and len(ignorados) >= len(campos):
        return _erro(400, "campos_desconhecidos",
                     f"Nenhum campo válido. Desconhecidos: {', '.join(ignorados)}. "
                     "Veja GET /enriquecimento/campos.")
    return _envelope(linhas, total=len(linhas), campos=campos,
                     campos_ignorados=ignorados or None,
                     gasta_consulta=paga, fonte="Enriquecimento CapiBLU")


# ─────────────── dossie em PDF ───────────────

@router.get("/dossie/{tipo}/{documento}",
            summary="Dossie completo em PDF (so token de admin; gasta varias consultas)")
async def dossie(tipo: str, documento: str, request: Request,
                 authorization: str = Header(default=""),
                 insight: bool = Query(False, description="Inclui resumo gerado por IA"),
                 familia: bool = Query(False, description="Consulta tambem os parentes")):
    """tipo: cpf | cnpj. Devolve application/pdf, nao JSON.

    Restrito a admin, igual a tela: o dossie junta tudo o que a plataforma sabe
    de uma pessoa num arquivo que passa a circular fora do sistema.
    """
    ctx = _contexto(authorization)
    if ctx.user.get("role") != "admin":
        return _erro(403, "sem_permissao", "O dossie e restrito a administradores.")
    if tipo not in ("cpf", "cnpj"):
        return _erro(400, "tipo_invalido", "tipo deve ser 'cpf' ou 'cnpj'.")
    doc = _so_digitos(documento)
    if (tipo == "cpf" and len(doc) != 11) or (tipo == "cnpj" and len(doc) != 14):
        return _erro(400, "documento_invalido", f"{tipo.upper()} invalido.")
    try:
        from app_online.main import DATA_SERVICE_URL, PROXY_SECRET
    except ImportError:
        from main import DATA_SERVICE_URL, PROXY_SECRET
    headers = {"X-User-Email": ctx.user.get("email", ""), "X-User-Role": "admin",
               "Accept-Encoding": "identity"}
    if PROXY_SECRET:
        headers["X-Proxy-Secret"] = PROXY_SECRET
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(600.0)) as client:
            r = await client.get(f"{DATA_SERVICE_URL}/api/dossie/pdf", headers=headers,
                                 params={"tipo": tipo, "doc": doc,
                                         "insight": str(insight).lower(),
                                         "familia": str(familia).lower()})
    except httpx.RequestError as exc:
        return _erro(503, "servico_indisponivel", f"Servico de dados indisponivel: {str(exc)[:80]}")
    if r.status_code != 200 or "pdf" not in (r.headers.get("content-type") or ""):
        return _erro(400, "dossie_falhou", "Nao foi possivel gerar o dossie.")
    from fastapi.responses import Response as RespostaBinaria
    return RespostaBinaria(content=r.content, media_type="application/pdf", headers={
        "Content-Disposition": f'attachment; filename="dossie-{tipo}-{doc}.pdf"'})
