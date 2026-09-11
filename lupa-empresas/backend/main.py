"""Lupa de Empresas - FastAPI backend.

Serve a API (busca, dados da empresa, funcionarios do LinkedIn) e tambem os
arquivos estaticos do frontend, tudo em http://localhost:8010.
"""

import os

# Carrega .env (se existir) ANTES de importar modulos que leem env no import.
try:
    from dotenv import load_dotenv

    _ENV_PATH = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"
    )
    load_dotenv(_ENV_PATH)
except Exception:
    pass

import asyncio
import io
import re
import sys
import uuid

from fastapi import Body, FastAPI, File, Form, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles

import assertiva
import auth
import brasilapi
import casadosdados
import config_store
import custos
import decisores as decisor_lib
import donodozap
import meetime
import navlog
import sheet_reader
import linkedin_scraper
import mkbuscas
import rais
import serasa
import dossie
import mistral
import workapi
import brightdata_pessoas
import empresas_li
import linkedin_cache
import rodadas
import cargos
import chamados
import funcoes
import identidade
import funil

# Base local de CPF (JBR_PF) — modulo compartilhado em ../../jbr_base.
_JBR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "jbr_base",
)
if _JBR not in sys.path:
    sys.path.insert(0, _JBR)
try:
    import cpf_lookup
except Exception:
    cpf_lookup = None

# Base local de CNPJ (Dados Abertos RFB) — modulo em ../../cnpj_base.
_CNPJ = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "cnpj_base",
)
if _CNPJ not in sys.path:
    sys.path.insert(0, _CNPJ)
try:
    import cnpj_lookup
except Exception:
    cnpj_lookup = None


def _cnpj_local() -> bool:
    return bool(cnpj_lookup and cnpj_lookup.ready())

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
FRONTEND_DIR = os.path.join(BASE_DIR, "frontend")

app = FastAPI(title="Lupa de Empresas", version="1.0.0")

try:
    linkedin_cache.init()      # cria o SQLite do cache na primeira subida
except Exception:
    pass

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── SERVIÇO DE DADOS (local) ──────────────────────────────────────────────
# A autenticação (login/usuários) vive no app-online (Render). Aqui só validamos
# o SEGREDO DE PROXY: só o app-online (que conhece o segredo) pode chamar as rotas
# de dados através do túnel. Sem PROXY_SECRET definido → modo dev aberto (localhost).
_PROXY_SECRET = os.environ.get("PROXY_SECRET", "").strip()


@app.get("/api/health")
async def health():
    return {"ok": True, "service": "capiblu-data", "protegido": bool(_PROXY_SECRET)}


@app.middleware("http")
async def _proxy_guard(request, call_next):
    path = request.url.path
    if request.method == "OPTIONS" or not path.startswith("/api/") or path == "/api/health":
        return await call_next(request)
    if _PROXY_SECRET and request.headers.get("x-proxy-secret", "") != _PROXY_SECRET:
        return JSONResponse({"detail": "Acesso negado (segredo de proxy)."}, status_code=401)
    custos.set_current_user(request.headers.get("x-user-email", ""))
    return await call_next(request)


def _cpf_ready() -> bool:
    return bool(cpf_lookup and cpf_lookup.ready())


def _enrich_qsa_cpf(company: dict) -> None:
    """Enriquece cada socio do QSA com o CPF completo, quando resolvivel.

    Cruza nome + 6 digitos do meio da mascara (ex.: '***912137**') na base JBR.
    """
    if not _cpf_ready():
        return
    qsa = company.get("qsa") or []
    for socio in qsa:
        if not isinstance(socio, dict):
            continue
        nome = socio.get("nome_socio") or ""
        mask = socio.get("cnpj_cpf_do_socio") or ""
        # So PF: mascara de CPF tem 6 digitos (CNPJ de socio PJ tem outro formato).
        try:
            res = cpf_lookup.resolve_socio(nome, mask)
        except Exception:
            continue
        socio["cpf_status"] = res.get("status")
        if res.get("status") == "resolved":
            socio["cpf_completo"] = res.get("cpf")
            p = res.get("pessoa") or {}
            socio["nascimento"] = p.get("nascimento")
            socio["sexo"] = p.get("sexo")


@app.get("/api/person/name-search")
async def person_name_search(
    q: str = "", broad: bool = False, limit: int = 40, offset: int = 0, uf: str = ""
):
    """Busca pessoas por nome em JBR (local) + WorkAPI (online). broad=true usa LIKE.

    Parâmetros:
    - q: nome (obrigatório)
    - broad: bool — LIKE em vez de match exato (nomes compostos)
    - limit: máximo de resultados (padrão 40)
    - offset: para paginação (JBR só)
    - uf: filtro opcional por estado (deduplica + valida por localização)

    Retorna 'total' = total de matches (JBR só). JBR é instantâneo e tem CPF completo;
    WorkAPI complementa com dados mais frescos e localização. Deduplica por CPF quando
    ambos têm, ou por nome quando só tem mascarado. uf filtra por estado.
    """
    if not q or not q.strip():
        return {"status": "error", "message": "Parâmetro q obrigatório."}

    q = q.strip()
    uf = (uf or "").strip().upper()
    jbr_ready = _cpf_ready()

    # Chama JBR e WorkAPI em paralelo
    jbr_res = None
    workapi_res = None
    try:
        if jbr_ready:
            if broad:
                jbr_pessoas = cpf_lookup.by_name_broad(q, limit=limit, offset=offset)
                jbr_total = cpf_lookup.count_name_broad(q)
            else:
                jbr_pessoas = cpf_lookup.by_name(q, limit=limit)
                jbr_total = len(jbr_pessoas)
            jbr_res = {"pessoas": jbr_pessoas, "total": jbr_total}
    except Exception as exc:
        jbr_res = {"pessoas": [], "total": 0, "erro": str(exc)[:80]}

    if workapi.enabled():
        wa_res = await workapi.nome_search(q, limit=limit)
        if wa_res.get("status") == "ok":
            workapi_res = wa_res.get("pessoas", [])

    # Mescla: por CPF quando disponível, senão por nome
    por_cpf = {}
    ordem = []

    if jbr_res:
        for p in jbr_res.get("pessoas") or []:
            cpf = p.get("cpf") or ""
            chave = cpf or ("nome:" + (p.get("nome") or "").upper())
            if chave not in por_cpf:
                por_cpf[chave] = {"fonte": "JBR", **p}
                ordem.append(chave)

    if workapi_res:
        for p in workapi_res:
            # WorkAPI tem CPF mascarado tipo "347*****821" — usamos como é
            cpf = p.get("cpf") or ""
            # Tenta casar: se já temos JBR com esse CPF, enriquece
            chave = cpf or ("nome:" + (p.get("nome") or "").upper())
            if chave in por_cpf:
                # Junta info: WorkAPI tem endereco, data_nascimento etc que JBR pode não ter
                atual = por_cpf[chave]
                for k, v in p.items():
                    if v and not atual.get(k):
                        atual[k] = v
                if "WorkAPI" not in (atual.get("fonte") or ""):
                    atual["fonte"] = (atual.get("fonte") or "JBR") + " + WorkAPI"
            else:
                por_cpf[chave] = {"fonte": "WorkAPI", **p}
                ordem.append(chave)

    resultado = [por_cpf[k] for k in ordem]

    # Filtro por UF (se especificado)
    if uf:
        resultado = [p for p in resultado if (p.get("endereco", {}).get("uf") or "").upper() == uf]

    total_jbr = jbr_res.get("total", 0) if jbr_res else 0

    return {
        "status": "ok",
        "total": total_jbr,
        "returned": len(resultado),
        "offset": offset,
        "broad": broad,
        "uf_filtro": uf or None,
        "pessoas": resultado,
        "fontes": {
            "jbr": "ok" if jbr_ready else "unavailable",
            "workapi": "ok" if workapi_res else "unavailable",
        }
    }


@app.get("/api/person/{cpf}/mk")
async def person_mk(cpf: str):
    """Dados completos da Mk Buscas (intelgrax-cpfv2) para um CPF."""
    if not mkbuscas.enabled():
        return {"status": "unavailable", "message": "Mk não configurada."}
    return await mkbuscas.consulta_cpf(cpf)


@app.get("/api/cnpj/lookup")
def cnpj_lookup_list(tipo: str = "cnae"):
    """Lista de códigos de apoio (cnae|natureza|municipio) para os selects do front."""
    if not cnpj_lookup:
        return {"status": "unavailable", "itens": []}
    if tipo not in ("cnae", "natureza", "municipio", "pais", "qualificacao", "motivo"):
        return {"status": "error", "message": "tipo inválido", "itens": []}
    return {"status": "ok", "tipo": tipo, "itens": cnpj_lookup.list_lookup(tipo)}


@app.get("/api/phone/{phone}/reverse")
async def phone_reverse(phone: str):
    """Telefone reverso (WorkAPI intelgrax-tel): CPFs/CNPJs atrelados ao número."""
    return await mkbuscas.consulta_telefone(phone)


@app.get("/api/phone/{phone}/pertence/{doc}")
async def phone_pertence(phone: str, doc: str):
    """Valida se um CPF/CNPJ está atrelado a um telefone (validação de contato)."""
    return await mkbuscas.telefone_pertence(phone, doc)


@app.get("/api/phone/{phone}/donodozap")
async def phone_donodozap(phone: str, nome: str = ""):
    """Valida se um telefone pertence a determinada pessoa via DonoDoZap."""
    return await donodozap.consultar(phone, nome)


# ---- Busca Assertiva (API Localize V3) ----

@app.get("/api/assertiva/status")
async def assertiva_status():
    """Diz se a integração Assertiva está configurada (sem expor credenciais)."""
    return {"enabled": assertiva.enabled(), "finalidade_padrao": assertiva.DEFAULT_FINALIDADE}


@app.get("/api/assertiva/cpf")
async def assertiva_cpf(cpf: str, finalidade: int | None = None):
    return await assertiva.consulta_cpf(cpf, finalidade)


@app.get("/api/assertiva/cnpj")
async def assertiva_cnpj(cnpj: str, finalidade: int | None = None):
    return await assertiva.consulta_cnpj(cnpj, finalidade)


@app.get("/api/assertiva/telefone")
async def assertiva_telefone(telefone: str, finalidade: int | None = None):
    return await assertiva.consulta_telefone(telefone, finalidade)


@app.get("/api/assertiva/email")
async def assertiva_email(email: str, finalidade: int | None = None):
    return await assertiva.consulta_email(email, finalidade)


@app.post("/api/assertiva/nome")
async def assertiva_nome(payload: dict = Body(default={})):
    """Busca por nome/razão social e/ou endereço (Localize nome-endereco)."""
    filtros = payload.get("filtros") or payload or {}
    finalidade = payload.get("finalidade")
    return await assertiva.busca_nome_endereco(filtros, finalidade)


@app.get("/api/search")
async def search(q: str = ""):
    """Busca empresas por CNPJ (exato) ou nome. NAO faz scraping de LinkedIn."""
    return await brasilapi.search_companies(q)


@app.get("/api/person/{cpf}")
async def person_by_cpf(cpf: str):
    """Consulta identidade por CPF exato na base JBR."""
    if not _cpf_ready():
        return {"status": "unavailable", "message": "Base de CPF ainda carregando ou indisponivel."}
    p = cpf_lookup.by_cpf(cpf)
    return {"status": "ok" if p else "not_found", "pessoa": p}


@app.get("/api/person/resolve/")
async def person_resolve(name: str = "", mask: str = ""):
    """Resolve CPF por nome (+ mascara opcional). Usado para socios/funcionarios."""
    if not _cpf_ready():
        return {"status": "unavailable", "message": "Base de CPF ainda carregando ou indisponivel."}
    return cpf_lookup.resolve_socio(name, mask)


@app.get("/api/person/{cpf}/contacts")
async def person_contacts(cpf: str):
    """Telefones/emails de uma PF por CPF, via Serasa Infomais (on-demand)."""
    if not serasa.enabled():
        return {"status": "unavailable", "message": "Serasa nao configurada (defina SERASA_CLIENT_ID/SECRET)."}
    return await serasa.enrich_person(cpf)


@app.get("/api/company/{cnpj}/contacts")
async def company_contacts(cnpj: str):
    """Telefones/emails de uma PJ por CNPJ, via Serasa Infomais (on-demand)."""
    if not serasa.enabled():
        return {"status": "unavailable", "message": "Serasa nao configurada (defina SERASA_CLIENT_ID/SECRET)."}
    return await serasa.enrich_company(cnpj)


@app.get("/api/company/{cnpj}")
async def company(cnpj: str):
    """Dados completos da empresa. Base local (RFB) primeiro — instantânea e
    já traz o QSA, sem gastar rede. BrasilAPI só entra se a base local não
    tiver a empresa (mesmo padrão de /api/company/{cnpj}/leads e afins)."""
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) != 14:
        return JSONResponse(status_code=400,
                            content={"status": "error", "message": "CNPJ invalido (precisa de 14 digitos)."})
    if _cnpj_local():
        loc = cnpj_lookup.by_cnpj(digits)
        if loc.get("status") == "ok":
            data = loc["company"]
            _enrich_qsa_cpf(data)
            return {"status": "ok", "company": data}
        if loc.get("status") == "not_found":
            return JSONResponse(status_code=404,
                                content={"status": "error", "message": "CNPJ nao encontrado na base local."})
    try:
        data = await brasilapi.fetch_company(cnpj)
        _enrich_qsa_cpf(data)
        return {"status": "ok", "company": data}
    except ValueError as exc:
        return JSONResponse(status_code=400, content={"status": "error", "message": str(exc)})
    except LookupError as exc:
        return JSONResponse(status_code=404, content={"status": "error", "message": str(exc)})
    except Exception:
        return JSONResponse(
            status_code=502,
            content={"status": "error", "message": "Falha ao consultar a BrasilAPI."},
        )


@app.get("/api/dossie/pdf")
async def dossie_pdf(request: Request, tipo: str, doc: str, insight: bool = False,
                     familia: bool = False, web: bool = False):
    """Dossiê em PDF: junta Mk Buscas + Assertiva + confirmação de telefone
    (CPF) ou Receita Federal + Assertiva + confirmação de telefone (CNPJ).
    insight=true chama a Mistral pra gerar resumo de vida + perfil psicológico
    inferido (ver aviso no próprio PDF — é inferência, não avaliação clínica).
    familia=true consulta Mk/Assertiva pra cada parente encontrado (custo extra
    por parente — opt-in).
    web=true executa a web_search da Mistral e inclui achados/fontes no PDF.

    SÓ ADMIN: o dossiê junta tudo o que a plataforma sabe de uma pessoa num
    arquivo que sai da tela e passa a circular por fora. Esconder o botão no
    front é conveniência; a recusa aqui é a trava.
    """
    if not _is_admin(request):
        return JSONResponse(
            status_code=403,
            content={"status": "error",
                     "message": "O dossiê é restrito a administradores."})
    doc_digits = re.sub(r"\D", "", doc or "")
    try:
        if tipo == "cpf":
            if len(doc_digits) != 11:
                return JSONResponse(status_code=400, content={"status": "error", "message": "CPF inválido."})
            dados = await dossie.montar_cpf(doc_digits, incluir_familia=familia)
            if web or insight:
                dados["achados_web"] = await mistral.web_search_dossie(dados)
            if insight and mistral.enabled():
                dados["insight_ia"] = await mistral.gerar_insight_pessoa(dados)
                if familia and any(p.get("resumo") for p in dados.get("parentes", [])):
                    dados["insight_familia"] = await mistral.gerar_hipoteses_familia(dados)
            pdf_bytes = dossie.gerar_pdf_cpf(dados)
            nome_arquivo = f"dossie-cpf-{doc_digits}.pdf"
        elif tipo == "cnpj":
            if len(doc_digits) != 14:
                return JSONResponse(status_code=400, content={"status": "error", "message": "CNPJ inválido."})
            dados = await dossie.montar_cnpj(doc_digits)
            pdf_bytes = dossie.gerar_pdf_cnpj(dados)
            nome_arquivo = f"dossie-cnpj-{doc_digits}.pdf"
        else:
            return JSONResponse(status_code=400, content={"status": "error", "message": "tipo deve ser 'cpf' ou 'cnpj'."})
    except Exception as exc:
        return JSONResponse(status_code=500, content={"status": "error", "message": f"Falha ao montar dossiê: {str(exc)[:200]}"})

    return StreamingResponse(
        io.BytesIO(pdf_bytes), media_type="application/pdf",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


# ---- Funcionários por empresa no dataset do LinkedIn (Bright Data) ----
# Duas rotas porque o filtro da Bright Data é um JOB de 1 a 4 minutos: segurar a
# requisição esperando daria timeout no proxy. Dispara → guarda o protocolo → consulta.

@app.get("/api/linkedin/status")
async def linkedin_status():
    """Diz se a busca por funcionários está configurada (sem expor a chave)."""
    try:
        cache = linkedin_cache.estatisticas()
    except Exception:
        cache = {}
    return {"enabled": brightdata_pessoas.enabled(),
            "limite_padrao": brightdata_pessoas.LIMITE_PADRAO,
            "limite_max": brightdata_pessoas.LIMITE_MAX,
            "cache": cache}


@app.get("/api/linkedin/cache")
async def linkedin_cache_busca(q: str = "", pais: str = "", limite: int = 100,
                               departamento: str = "", senioridade: str = "",
                               empresa: str = "",
                               nome: str = "", sobrenome: str = "",
                               cargo: str = "", ufs: str = "", cidade: str = "",
                               palavras: str = "", tempo_empresa: str = "",
                               so_com_foto: int = 0, min_seguidores: int = 0,
                               linkedin_url: str = ""):
    """Busca nos perfis JÁ PAGOS. Não gasta nada e responde na hora.

    Aceita o vocabulário de filtro da Datastone: nome, sobrenome, cargo,
    departamento, senioridade, UF, cidade, palavras-chave (o "especialidades"
    deles), tempo na empresa e dados disponíveis. `empresa` aceita vários nomes
    separados por vírgula, como o `selected_companies` deles.

    DOIS FILTROS SÓ FUNCIONAM AQUI, não na Bright Data:
      - `ufs`: o LinkedIn não tem campo de estado; a UF é deduzida do texto de
        cidade e fica vazia quando não dá pra afirmar.
      - `tempo_empresa`: vem de `experience`, que a API deles não filtra
        (HTTP 500 quando tentei).
    Por isso a resposta devolve `sem_uf` — quantos perfis do resultado não têm
    UF identificada — em vez de descartá-los em silêncio.
    """
    try:
        pessoas = linkedin_cache.procurar(
            q=q, pais=pais, limite=limite, departamento=departamento,
            senioridade=senioridade, empresa=empresa,
            nome=nome, sobrenome=sobrenome, cargo=cargo, ufs=ufs,
            cidade=cidade, palavras=palavras, tempo_empresa=tempo_empresa,
            so_com_foto=bool(so_com_foto), min_seguidores=min_seguidores,
            linkedin_url=linkedin_url)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:120], "pessoas": []}
    exatos = sum(1 for p in pessoas if p.get("exata") is not False)
    return {"status": "ok", "total": len(pessoas), "pessoas": pessoas,
            "exatos": exatos, "parecidos": len(pessoas) - exatos,
            "sem_uf": sum(1 for p in pessoas if not (p.get("uf") or "")),
            "sem_tempo_empresa": sum(1 for p in pessoas
                                     if not (p.get("desde_na_empresa") or ""))}


@app.post("/api/linkedin/buscar-fora")
async def linkedin_buscar_fora(request: Request, payload: dict = Body(default={})):
    """Busca na Bright Data o que NÃO está na base local. COBRA.

    Mesmo conjunto de filtros da tela, traduzido para o DSL deles. Recusa buscar
    sem nenhum filtro além do país: sem critério a chamada traria perfil
    aleatório e cobraria por cada um.

    Devolve `custo_usd` do que foi efetivamente entregue e grava no livro-caixa
    (`gastos_bd`), que alimenta o painel administrativo.
    """
    return await brightdata_pessoas.buscar_por_filtro(
        pais=str(payload.get("pais") or "BR"),
        empresas=payload.get("empresas") or payload.get("empresa") or [],
        empresa_ids=payload.get("empresa_ids") or [],
        cargos_termos=payload.get("cargo") or [],
        nome=str(payload.get("nome") or ""),
        sobrenome=str(payload.get("sobrenome") or ""),
        cidade=str(payload.get("cidade") or ""),
        palavras=payload.get("palavras") or [],
        min_seguidores=int(payload.get("min_seguidores") or 0),
        so_com_foto=payload.get("so_com_foto") is True,
        decisores=payload.get("decisores") is True,
        limite=int(payload.get("limite") or 50),
        usuario=(request.headers.get("x-user-email") or ""),
    )


@app.get("/api/linkedin/ufs")
async def linkedin_ufs():
    """UFs presentes no cache, com contagem. Só oferece UF que tem gente."""
    try:
        return {"status": "ok", "ufs": linkedin_cache.ufs_disponiveis()}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:120], "ufs": []}


def _limpa_custo(d: Any) -> Any:
    """Tira o custo da resposta. Só admin vê quanto cada busca gastou.

    Some NA ORIGEM, não por CSS: escondido no navegador o número continua no
    DOM e em qualquer inspeção. Quem opera não precisa saber o preço de cada
    linha — isso é conta de dono, e ver R$ 0,59 ao lado de um nome empurra a
    pessoa a não clicar justamente onde clicar valeria a pena.
    """
    if isinstance(d, dict):
        return {k: _limpa_custo(v) for k, v in d.items()
                if k not in ("custo", "custo_por_cpf", "custo_max_brl")}
    if isinstance(d, list):
        return [_limpa_custo(x) for x in d]
    return d


@app.get("/api/funil/empresa")
async def funil_empresa(request: Request, nome: str = "", cidade: str = "",
                        uf: str = "", cnpj: str = ""):
    """Porte da empresa e unidades disponíveis. NÃO GASTA NADA.

    O filtro B2B chama isto enquanto a pessoa digita o nome da empresa, para
    poder dizer antes da busca: "a Gerdau tem 184 unidades em 23 UFs, escolha
    a cidade". Sem isso, buscar decisor de rede nacional custa até R$ 5,71 por
    pessoa para confirmar 2,4% dos casos.
    """
    nome = (nome or "").strip()
    # Com CNPJ digitado, o nome vira opcional: quem sabe o CNPJ não precisa
    # acertar a grafia da razão social.
    if len(nome) < 3 and len(re.sub(r"\D", "", cnpj or "")) != 14:
        return {"status": "vazio", "filiais": []}
    try:
        r = {"status": "ok", **funil.contexto_empresa(nome, cidade, uf, cnpj)}
        return r if _is_admin(request) else _limpa_custo(r)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160], "filiais": []}


@app.get("/api/funil/cargos")
async def funil_cargos():
    """Catálogo de cargos de decisão para a tela oferecer. Local, grátis.

    Sai do mesmo dicionário que o filtro usa (`funcoes.NIVEIS` × `AREAS`), não
    de uma tabela paralela — assim o que a tela oferece nunca diverge do que o
    backend entende.
    """
    try:
        return {"status": "ok", **funcoes.catalogo_decisores()}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160]}


@app.post("/api/funil/decisores-linkedin")
async def funil_decisores_linkedin(request: Request, payload: dict = Body(...)):
    """Decisores que só o LinkedIn conhece, com telefone. GASTA.

    A aba B2B já traz sócio e decisor da Assertiva; isto traz o gestor
    contratado que não é sócio e ainda não apareceu em cadastro trabalhista —
    o que nenhuma das duas outras fontes enxerga.
    """
    empresa = str(payload.get("empresa") or "").strip()
    cnpj = re.sub(r"\D", "", str(payload.get("cnpj") or ""))
    if len(empresa) < 3 and len(cnpj) != 14:
        return {"status": "error", "message": "Informe a empresa ou o CNPJ."}
    try:
        teto = float(payload.get("teto_brl") or 6.0)
    except (TypeError, ValueError):
        teto = 6.0
    try:
        r = await funil.decisores_do_linkedin(
            empresa=empresa, cnpj=cnpj,
            cidade=str(payload.get("cidade") or "").strip(),
            uf=str(payload.get("uf") or "").strip().upper()[:2],
            limite=min(int(payload.get("limite") or 50), 100),
            teto_brl=max(0.0, min(teto, 60.0)),
            # nasce LIGADO: a aba monta lista para discar, e linha sem telefone
            # não é lead. O operador desmarca se quiser a lista inteira.
            so_com_telefone=payload.get("so_com_telefone", True) is not False,
            max_decisores=int(payload.get("max_decisores") or 0),
            max_socios=int(payload.get("max_socios") or 0),
            cargos_escolhidos=payload.get("cargos") or [])
        r = {"status": "ok", **r}
        return r if _is_admin(request) else _limpa_custo(r)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}


@app.post("/api/funil/resolver")
async def funil_resolver(request: Request, payload: dict = Body(...)):
    """Roda o funil num lote de perfis. ISTO GASTA DINHEIRO.

    Duas travas, porque a consulta é paga e o clique é fácil:
      - `teto_brl` limita o lote inteiro e é obrigatório respeitar; o padrão
        é conservador de propósito.
      - `usar_pagas=False` roda só as etapas gratuitas (WorkAPI e as listas
        por CNPJ que já estiverem em cache), para a tela poder mostrar quanto
        se resolve sem cobrar nada antes de oferecer o botão que cobra.
    """
    perfis = payload.get("perfis") or []
    if not isinstance(perfis, list) or not perfis:
        return {"status": "error", "message": "Nenhum perfil enviado."}
    if len(perfis) > 200:
        return {"status": "error",
                "message": "Máximo 200 perfis por lote (recebi %d)." % len(perfis)}
    try:
        teto = float(payload.get("teto_brl") or funil.TETO_LOTE_PADRAO)
    except (TypeError, ValueError):
        teto = funil.TETO_LOTE_PADRAO
    teto = max(0.0, min(teto, 200.0))
    try:
        r = await funil.resolver_lote(
            perfis,
            cidade=(payload.get("cidade") or "").strip(),
            uf=(payload.get("uf") or "").strip().upper()[:2],
            teto_brl=teto,
            usar_pagas=bool(payload.get("usar_pagas", True)),
            cnpj=str(payload.get("cnpj") or ""),
        )
        r = {"status": "ok", **r}
        return r if _is_admin(request) else _limpa_custo(r)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}


@app.post("/api/funil/pessoa")
async def funil_pessoa(request: Request, payload: dict = Body(...)):
    """O "ver mais" de UMA pessoa: acha o CPF e devolve os dados dela.

    ISTO GASTA. Teto baixo por padrão (R$ 3) porque nasce de um clique numa
    linha da tabela, e um clique não deve conseguir torrar o orçamento do dia.

    Aceita `cpf` direto quando a pessoa já foi identificada antes — aí pula o
    funil inteiro e só busca os dados, que é uma consulta em vez de várias.
    """
    cpf = re.sub(r"\D", "", str(payload.get("cpf") or ""))
    try:
        teto = float(payload.get("teto_brl") or 3.0)
    except (TypeError, ValueError):
        teto = 3.0
    teto = max(0.0, min(teto, 20.0))
    try:
        if len(cpf) == 11:
            r = {"status": "ok", "identificacao": {"cpf": cpf,
                 "situacao": "cpf_informado", "confianca": 100},
                 "dossie": await funil.dossie_pessoa(cpf, funil.Gasto(teto))}
            return r if _is_admin(request) else _limpa_custo(r)
        perfil = payload.get("perfil") or {}
        if not (perfil.get("nome") or "").strip():
            return {"status": "error", "message": "Informe o CPF ou o perfil."}
        r = await funil.resolver_e_detalhar(
            perfil,
            cidade=(payload.get("cidade") or "").strip(),
            uf=(payload.get("uf") or "").strip().upper()[:2],
            teto_brl=teto, cnpj=str(payload.get("cnpj") or ""))
        r = {"status": "ok", **r}
        return r if _is_admin(request) else _limpa_custo(r)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}


@app.get("/api/linkedin/custos")
async def linkedin_custos(request: Request, desde: str = "", ate: str = ""):
    """Livro-caixa da Bright Data — só admin.

    A fatura deles vem por mês e não diz quem pediu o quê. Isto registra cada
    chamada na hora, com usuário, e mostra junto o que o cache serviu de graça.
    """
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)

    def _ts(s: str, fim: bool = False) -> int:
        s = (s or "").strip()
        if not s:
            return 0
        try:
            import datetime as _dt
            d = _dt.datetime.strptime(s[:10], "%Y-%m-%d")
            if fim:
                d = d.replace(hour=23, minute=59, second=59)
            return int(d.timestamp())
        except Exception:
            return 0

    try:
        res = linkedin_cache.resumo_gastos(_ts(desde), _ts(ate, True))
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:150]}
    try:
        res["cache"] = linkedin_cache.estatisticas()
    except Exception:
        res["cache"] = {}
    res["status"] = "ok"
    return res


@app.post("/api/linkedin/cruzar")
async def linkedin_cruzar(payload: dict = Body(default={})):
    """Acha, no cache do LinkedIn, quem são as pessoas de uma lista da Receita.

    Body: {pessoas: [{nome, empresa}]}. Devolve os achados com a força do
    casamento — "nome+empresa" é confiável, "so nome" é pista (homônimo é comum).
    Não gasta nada: só olha o que já foi comprado.
    """
    pessoas = payload.get("pessoas") or []
    if not isinstance(pessoas, list):
        return {"status": "error", "message": "pessoas deve ser uma lista.", "achados": {}}
    try:
        achados = linkedin_cache.cruzar(pessoas[:500])
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:150], "achados": {}}
    fortes = sum(1 for v in achados.values() if v.get("forca") == "nome+empresa")
    return {"status": "ok", "achados": achados,
            "total": len(achados), "fortes": fortes,
            "fracos": len(achados) - fortes}


@app.post("/api/linkedin/funcionarios-varias")
async def linkedin_funcionarios_varias(payload: dict = Body(default={})):
    """Funcionários de VÁRIAS empresas de uma vez — como o filtro da Datastone.

    Body: {empresas: ["Movida", "Klabin"], pais, cargo, decisores, limite}.
    Lê o cache primeiro e só vai à Bright Data para as empresas descobertas,
    em grupos de 4 (teto do `or` de lá). Devolve `custo_estimado_usd`.
    """
    return await brightdata_pessoas.buscar_varias(
        empresas=payload.get("empresas") or [],
        pais=str(payload.get("pais") or "BR"),
        cargo=str(payload.get("cargo") or ""),
        limite_por_lote=int(payload.get("limite") or 50),
        decisores=payload.get("decisores", True) is not False,
    )


@app.get("/api/linkedin/filtro-opcoes")
async def linkedin_filtro_opcoes():
    """Vocabulário dos filtros — o mesmo da Datastone (/b2b/filter-options).

    Devolve também quantos perfis já temos em cada balde: filtro que promete
    uma opção sem ninguém atrás é pior que não oferecer a opção.
    """
    try:
        contagem = linkedin_cache.contagem_por_classificacao()
    except Exception:
        contagem = {"departamento": {}, "senioridade": {}}
    return {
        "status": "ok",
        "departamentos": cargos.DEPARTAMENTOS,
        "senioridades": cargos.SENIORIDADES,
        "contagem": contagem,
    }


@app.get("/api/linkedin/empresas")
async def linkedin_empresas_sugestao(q: str = "", conferir: int = 0):
    """Empresas parecidas com o termo. O cache é grátis; `conferir=N` raspa N
    URLs candidatas no LinkedIn (isso CUSTA, por isso é opt-in e limitado)."""
    return await brightdata_pessoas.sugerir_empresas(q, conferir=min(int(conferir or 0), 5))


@app.get("/api/empresas/catalogo")
async def empresas_catalogo():
    """Faixas de porte e tipos de organizacao, com quantas empresas ha em cada.

    Estatico: as contagens foram medidas contra o dataset e nao mudam a cada
    clique. A contagem vai junto de proposito -- escolher "5.001 a 10.000"
    sabendo que sao 302 empresas no Brasil e uma escolha; sem saber, e uma
    surpresa depois da busca ja cobrada.
    """
    return brightdata_pessoas.catalogo_empresas()


@app.post("/api/empresas/brightdata")
async def empresas_brightdata(request: Request, payload: dict = Body(default={})):
    """Busca de EMPRESAS no dataset da Bright Data (porte, tipo, fundacao).

    Complementa a busca da Receita (/api/companies/search), nao substitui: a
    Receita e gratis e sabe CNPJ, CNAE e situacao; esta sabe quantas pessoas a
    empresa tem no LinkedIn, o tipo de organizacao e o site. Cada registro
    entregue e cobrado, por isso `limite` tem teto baixo por padrao.
    """
    f = payload.get("filtros") or payload
    return await brightdata_pessoas.buscar_empresas_por_filtro(
        pais=str(f.get("pais") or "BR"),
        nomes=f.get("nomes") or f.get("empresas"),
        sites=f.get("sites"),
        porte_min=int(f.get("porte_min") or 0),
        tipos=f.get("tipos"),
        fundada_apos=int(f.get("fundada_apos") or 0),
        setores=f.get("setores"),
        so_com_cnpj=bool(f.get("so_com_cnpj")),
        limite=min(int(payload.get("limite") or f.get("limite") or 25), 100),
        usuario=(request.headers.get("x-user-email") or ""))


@app.post("/api/linkedin/empresa")
async def linkedin_empresa(payload: dict = Body(default={})):
    """Dados da empresa a partir do link do LinkedIn — rápido (segundos).

    Serve para acertar o nome antes de gastar a busca de funcionários, que casa
    por nome e é lenta: descobrir a grafia errada depois de 4 minutos de espera
    é o pior jeito de descobrir.
    """
    return await brightdata_pessoas.empresa_por_url(str(payload.get("url") or ""))


@app.post("/api/linkedin/funcionarios")
async def linkedin_funcionarios(payload: dict = Body(default={})):
    """Busca funcionários. CUSTA por registro entregue ($2,50/1.000).

    Usa o endpoint Search (síncrono, 2-3s). O Filter antigo era um job de 40s a
    4min pelo MESMO preço — a troca é por velocidade e paginação, não por custo.
    Antes de gastar, olha o cache: `forcar=true` pula essa checagem.
    """
    empresa = str(payload.get("empresa") or "")
    pais = str(payload.get("pais") or "BR")
    cargo = str(payload.get("cargo") or "")
    limite = int(payload.get("limite") or 0)

    so_decisores = payload.get("decisores", True) is not False

    if not payload.get("forcar") and not payload.get("cursor"):
        try:
            # `decisores` PRECISA vir até aqui. Sem ele, o checkbox "Só
            # decisores" só valia para a busca paga: quando o cache respondia,
            # a tela devolvia a empresa inteira com o filtro marcado.
            guardados = linkedin_cache.por_empresa(empresa, pais=pais, cargo=cargo,
                                                   limite=limite or 50,
                                                   decisores=so_decisores and not cargo)
        except Exception:
            guardados = []
        if guardados:
            return {"status": "cache", "empresa": empresa, "total": len(guardados),
                    "pessoas": guardados, "so_decisores": so_decisores and not cargo,
                    "message": "Do que já foi comprado antes — não gastou nada agora."}

    return await brightdata_pessoas.buscar_agora(
        empresa=empresa, pais=pais, cargo=cargo, limite=limite,
        cursor=payload.get("cursor"),
        # Padrão LIGADO: sem isso a busca traz uma fatia arbitrária da empresa.
        # Medido na Magalu: 40 perfis sem filtro deram ZERO decisores.
        decisores=so_decisores,
    )


@app.get("/api/linkedin/funcionarios/{protocolo}")
async def linkedin_funcionarios_resultado(protocolo: str, empresa: str = ""):
    """Consulta o protocolo. status: building (tente de novo) | ok | error."""
    return await brightdata_pessoas.consultar(protocolo, empresa=empresa)


@app.get("/api/company/{cnpj}/employees")
async def employees(cnpj: str):
    """Dispara o scraping do LinkedIn para os funcionarios da empresa."""
    company_name = ""
    company_legal = ""
    try:
        data = await brasilapi.fetch_company(cnpj)
        company_name = data.get("nome_fantasia") or data.get("razao_social") or ""
        company_legal = data.get("razao_social") or ""
    except Exception:
        # Se a BrasilAPI falhar, o scraper trata nomes vazios graciosamente.
        pass

    result = await linkedin_scraper.scrape_employees(
        brasilapi.only_digits(cnpj), company_name, company_legal
    )

    # Enriquece cada funcionario com o CPF, estilo Datastone:
    #   JBR (nome -> candidatos) + desambiguacao por empresa + cargo + CIDADE DA PESSOA.
    # A cidade e o cargo vem do proprio Bright (perfil do LinkedIn).
    if _cpf_ready() and isinstance(result.get("employees"), list):
        for emp in result["employees"]:
            nome = emp.get("name", "")
            try:
                cands = cpf_lookup.by_name(nome, limit=50)
            except Exception:
                continue

            if len(cands) == 1:
                emp["cpf_status"] = "resolved"
                emp["cpf"] = cands[0]["cpf"]
                continue

            # Varios homonimos: desambigua com sinais do Bright, se a Mk estiver ligada.
            if mkbuscas.enabled() and cands:
                res = await mkbuscas.disambiguate_multi(
                    cands,
                    company=company_name,
                    role=emp.get("title", ""),
                    city=emp.get("city", ""),
                )
                emp["cpf_status"] = res.get("status")
                if res.get("status") == "resolved":
                    emp["cpf"] = res.get("cpf")
                    tels = (res.get("pessoa") or {}).get("phones_mk", [])
                    if tels:
                        emp["phones_mk"] = tels
            else:
                emp["cpf_status"] = "ambiguous" if cands else "not_found"
                emp["cpf_candidates"] = len(cands)
    return result


# ---- Vínculos empregatícios (RAIS) ----

@app.get("/api/company/{cnpj}/vinculos")
async def company_vinculos(cnpj: str, refresh: bool = False):
    """Quem trabalha (ou trabalhou) na empresa, pela RAIS: nome, CPF, admissão.

    A RAIS não traz cargo, então o nível de decisão (1/2/3) vem do quadro de
    sócios da Receita — de graça e cruzado por CPF. Sócio que não está na folha
    entra como linha extra: continua sendo quem decide. Para cargo de
    funcionário não-sócio existe o /vinculos/cargos (LinkedIn, opt-in).
    """
    dados = await rais.vinculos_cnpj(cnpj, refresh=refresh)
    if dados.get("status") not in ("ok", "not_found"):
        return dados

    vinculos = dados.get("vinculos") or []
    dados["vinculos"] = vinculos
    try:
        empresa = await brasilapi.fetch_company(cnpj)
        _enrich_qsa_cpf(empresa)          # resolve o CPF completo do sócio na base JBR
        qsa = empresa.get("qsa") or []
        dados["qsa_status"] = "ok"
        dados["razao_social"] = dados.get("razao_social") or empresa.get("razao_social") or ""
    except Exception:
        qsa = []
        dados["qsa_status"] = "indisponivel"

    resultado_qsa = decisor_lib.anexar_qsa(vinculos, qsa)
    decisor_lib.normalizar(vinculos)
    decisor_lib.ordenar(vinculos)

    dados["socios_qsa"] = len(qsa)
    dados["socios_fora_da_folha"] = resultado_qsa["adicionados"]
    dados["total"] = len(vinculos)
    dados["ativos"] = sum(1 for v in vinculos if v.get("ativo"))
    dados["desligados"] = len(vinculos) - dados["ativos"]
    dados["hierarquia"] = decisor_lib.resumo(vinculos)
    if vinculos:
        dados["status"] = "ok"
    return dados


def _juntar_relacoes(itens: list[dict]) -> list[dict]:
    """Funde pessoas-de-referencia e conexões numa lista só, sem repetir gente.

    As duas fontes se sobrepõem (um irmão pode vir nas duas), mas cada uma traz
    algo que a outra não tem: referência dá o parentesco de mais gente,
    conexões dá telefone com flag de WhatsApp. Cruzamento por documento.
    """
    por_doc: dict[str, dict] = {}
    ordem: list[str] = []
    for it in itens:
        doc = re.sub(r"\D", "", it.get("documento") or "")
        chave = doc or ("nome:" + (it.get("nome") or "").upper())
        if chave not in por_doc:
            por_doc[chave] = it
            ordem.append(chave)
            continue
        atual = por_doc[chave]
        for campo, valor in it.items():
            if valor and not atual.get(campo):
                atual[campo] = valor
        fontes = set((atual.get("fonte") or "").split(" + ")) | {it.get("fonte")}
        atual["fonte"] = " + ".join(sorted(f for f in fontes if f))
    return [por_doc[k] for k in ordem]


@app.get("/api/person/{cpf}/parentes")
async def person_parentes(cpf: str, mae: bool = True):
    """Busca Parentes: junta pessoas-de-referência + conexões de um CPF.

    CUSTA 2 consultas Assertiva. Retorna {status, cpf, total, por_relacao,
    parentes:[{nome, documento, relacao, tipo_relacao, telefone, whatsapp,
    nao_perturbe, nascimento, fonte}]}.
    """
    doc = re.sub(r"\D", "", cpf or "")
    if len(doc) != 11:
        return {"status": "error", "message": "CPF inválido — precisa ter 11 dígitos.", "parentes": []}
    if not assertiva.enabled():
        return {"status": "unavailable", "message": "Assertiva não configurada.", "parentes": []}

    ref, con = await asyncio.gather(
        assertiva.pessoas_de_referencia(doc, retornar_mae=mae),
        assertiva.conexoes(doc, tipo="CPF"),
    )

    itens: list[dict] = []
    avisos = []

    if ref.get("status") == "ok":
        lista = (((ref.get("data") or {}).get("resposta") or {}).get("pessoasDeReferencia") or [])
        for p in lista:
            itens.append({
                "nome": (p.get("nomeOuRazaoSocial") or "").strip(),
                "documento": p.get("documento") or "",
                "relacao": (p.get("relacao") or "").strip(),
                "tipo_relacao": "Pessoas de referência",
                "nascimento": p.get("dataNascimentoOuAbertura") or "",
                "telefone": "", "whatsapp": None, "nao_perturbe": None,
                "fonte": "Pessoas de referência",
            })
    elif ref.get("status") != "not_found":
        avisos.append(f"Pessoas de referência: {ref.get('message', '')[:120]}")

    if con.get("status") == "ok":
        corpo = (con.get("data") or {}).get("resposta")
        for c in (corpo if isinstance(corpo, list) else []):
            if not isinstance(c, dict):
                continue
            itens.append({
                "nome": (c.get("nomeOuRazaoSocial") or "").strip(),
                "documento": c.get("documento") or "",
                "relacao": (c.get("relacao") or "").strip(),
                "tipo_relacao": (c.get("tipoRelacao") or "").strip(),
                "nascimento": c.get("dataNascimento") or c.get("dataAbertura") or "",
                "telefone": c.get("telefone") or "",
                "tipo_telefone": c.get("tipoTelefone") or "",
                "whatsapp": c.get("whatsapp"),
                "nao_perturbe": c.get("naoPerturbe"),
                "cargo": c.get("cargo") or "",
                "fonte": "Conexões",
            })
    elif con.get("status") != "not_found":
        avisos.append(f"Conexões: {con.get('message', '')[:120]}")

    parentes = _juntar_relacoes(itens)
    por_relacao: dict[str, int] = {}
    for p in parentes:
        rot = p.get("relacao") or p.get("tipo_relacao") or "Outros"
        por_relacao[rot] = por_relacao.get(rot, 0) + 1

    return {
        "status": "ok" if parentes else "not_found",
        "cpf": doc,
        "total": len(parentes),
        "com_telefone": sum(1 for p in parentes if p.get("telefone")),
        "por_relacao": por_relacao,
        "avisos": avisos,
        "message": "" if parentes else "Nenhum parente ou conexão encontrada para este CPF.",
        "parentes": parentes,
    }


@app.get("/api/company/{cnpj}/conexoes")
async def company_conexoes(cnpj: str):
    """Conexões de um CNPJ: sócios, possíveis decisores e empresas com
    participação — cada um com telefone e flag de WhatsApp. 1 consulta."""
    doc = re.sub(r"\D", "", cnpj or "")
    if len(doc) != 14:
        return {"status": "error", "message": "CNPJ inválido.", "conexoes": []}
    if not assertiva.enabled():
        return {"status": "unavailable", "message": "Assertiva não configurada.", "conexoes": []}

    c = await assertiva.conexoes(doc, tipo="CNPJ")
    if c.get("status") != "ok":
        return {"status": c.get("status", "error"),
                "message": c.get("message", "Falha ao consultar conexões."), "conexoes": []}

    corpo = (c.get("data") or {}).get("resposta")
    lista = [x for x in (corpo if isinstance(corpo, list) else []) if isinstance(x, dict)]
    por_tipo: dict[str, int] = {}
    for x in lista:
        rot = (x.get("tipoRelacao") or "Outros").strip()
        por_tipo[rot] = por_tipo.get(rot, 0) + 1
    return {"status": "ok" if lista else "not_found", "cnpj": doc,
            "total": len(lista), "por_tipo": por_tipo,
            "com_telefone": sum(1 for x in lista if x.get("telefone")),
            "conexoes": lista}


@app.get("/api/person/{cpf}/vinculos")
async def person_vinculos(cpf: str, refresh: bool = False):
    """Onde a pessoa trabalha (ou trabalhou), pela RAIS — o inverso do CNPJ."""
    return await rais.vinculos_cpf(cpf, refresh=refresh)


@app.get("/api/company/{cnpj}/decisores")
async def company_decisores(cnpj: str, conexoes: bool = False):
    """Possíveis decisores do CNPJ pela Assertiva, já classificados por nível.

    CUSTA 2 consultas Assertiva na primeira vez (a de CNPJ, que gera o
    protocolo, e a de decisores). Com conexoes=true, mais 1 — a de conexões
    traz telefone e flag de WhatsApp de sócios e decisores.
    """
    doc = re.sub(r"\D", "", cnpj or "")
    if len(doc) != 14:
        return {"status": "error", "message": "CNPJ inválido — precisa ter 14 dígitos.",
                "decisores": []}
    if not assertiva.enabled():
        return {"status": "unavailable",
                "message": "Assertiva não configurada (ASSERTIVA_CLIENT_ID/SECRET no .env).",
                "decisores": []}

    r = await assertiva.possiveis_decisores(doc)
    if r.get("status") != "ok":
        return {"status": r.get("status", "error"),
                "message": r.get("message", "Falha ao consultar a Assertiva."),
                "decisores": []}

    resposta = ((r.get("data") or {}).get("resposta") or {})
    lista = decisor_lib.da_assertiva(resposta.get("possiveisDecisores") or [])
    lista.sort(key=lambda p: (p["nivel"] or 9, p["nome"]))

    saida = {
        "status": "ok",
        "cnpj": doc,
        "total": len(lista),
        "por_nivel": {
            "nivel_1": sum(1 for p in lista if p["nivel"] == 1),
            "nivel_2": sum(1 for p in lista if p["nivel"] == 2),
            "nivel_3": sum(1 for p in lista if p["nivel"] == 3),
            "sem_nivel": sum(1 for p in lista if not p["nivel"]),
        },
        "decisores": lista,
    }

    # Dados cadastrais da própria consulta de CNPJ (já paga) — sem chamada extra.
    base = await assertiva.consulta_cnpj(doc)
    if base.get("status") == "ok":
        dc = (((base.get("data") or {}).get("resposta") or {}).get("dadosCadastrais") or {})
        saida["cadastro_assertiva"] = {
            "razao_social": dc.get("razaoSocial") or dc.get("nomeFantasia") or "",
            "quantidade_funcionarios": dc.get("quantidadeFuncionarios"),
            "porte": dc.get("porteEmpresa") or "",
            "idade_empresa": dc.get("idadeEmpresa"),
            "situacao": (dc.get("situacaoCadastral") or {}).get("descricao")
                        if isinstance(dc.get("situacaoCadastral"), dict) else dc.get("situacaoCadastral"),
        }
        saida["socios_assertiva"] = ((base.get("data") or {}).get("resposta") or {}).get("socios") or []

    if conexoes:
        c = await assertiva.conexoes(doc, "CNPJ")
        if c.get("status") == "ok":
            corpo = (c.get("data") or {}).get("resposta")
            saida["conexoes"] = corpo if isinstance(corpo, list) else []
        else:
            saida["conexoes_erro"] = c.get("message", "")

    return saida


@app.post("/api/prospeccao/b2b-linkedin")
async def prospeccao_b2b_linkedin(request: Request, payload: dict = Body(default={})):
    """Decisores do LinkedIn para VÁRIAS empresas de uma vez, funil curto.

    Estava escrito e sem porta de entrada: `funil.prospeccao_b2b` não tinha
    nenhuma referência fora do próprio arquivo. É o funil rápido que a Rebeca
    pediu para a lista em massa -- "50, 100 ao mesmo tempo, então o funil não
    pode ser grande".

    POR QUE ELE EXISTE, tendo `/api/company/{cnpj}/leads`: as três fontes
    enxergam gente DIFERENTE e nenhuma cobre a outra. Sócio do QSA é DONO;
    decisor da Assertiva é quem a folha registra como gestor e defasa; o
    LinkedIn é o único que vê o gerente contratado que ainda não apareceu em
    cadastro trabalhista. Medido antes: na Google Brasil a Assertiva deu 602
    pessoas e NENHUMA estava no quadro societário.

    O FUNIL É CURTO DE PROPÓSITO. Ele para no primeiro sinal barato: sócio do
    QSA, decisor do CNPJ, e-mail exato, JBR com nome único. Não faz WorkAPI,
    não paga busca por nome, não desempata homônimo -- desempatar custa até
    R$ 2,38 por pessoa, e aqui há cinquenta delas.

    `fonte`: "cache" (padrão, grátis) ou "brightdata" (cobra por perfil).
    """
    empresas = payload.get("empresas") or []
    if not empresas:
        return {"status": "error", "message": "Nenhuma empresa na lista."}
    # Teto duro de empresas por chamada. Não é limitação técnica: é que
    # cinquenta empresas já são a lista de um dia, e mil seriam uma conta de
    # telefone que ninguém pediu.
    empresas = empresas[:100]
    nomes = [str(e.get("nome") or e.get("razao_social") or "").strip()
             for e in empresas if isinstance(e, dict)]
    nomes = [n for n in nomes if n]
    if not nomes:
        return {"status": "error", "message": "As empresas vieram sem nome."}

    fonte = str(payload.get("fonte") or "cache").strip().lower()
    cargos = payload.get("cargos") or []
    max_por_empresa = max(1, min(int(payload.get("max_por_empresa") or 3), 20))

    perfis: list[dict] = []
    custo_usd = 0.0
    if fonte == "brightdata":
        r = await brightdata_pessoas.buscar_por_filtro(
            pais="BR", empresas=nomes,
            cargos_termos=(cargos if cargos else None),
            decisores=not cargos,
            limite=min(int(payload.get("limite") or 50), 100),
            usuario=(request.headers.get("x-user-email") or ""))
        if r.get("status") != "ok":
            return {"status": "error", "message": r.get("message") or "Bright Data falhou."}
        perfis = r.get("pessoas") or []
        custo_usd = float(r.get("custo_usd") or 0)
    else:
        # GRÁTIS E INSTANTÂNEO, e é o padrão: uma consulta para N empresas,
        # como a Datastone faz. Só depois de ver o que já temos é que faz
        # sentido decidir comprar.
        try:
            perfis = linkedin_cache.por_empresas(
                nomes, pais="BR", limite=300,
                departamento=str(payload.get("departamento") or ""),
                senioridade=str(payload.get("senioridade") or ""))
        except Exception as exc:
            return {"status": "error", "message": str(exc)[:180]}

    if cargos:
        perfis = [p for p in perfis
                  if funcoes.casa_escolha(p.get("cargo") or "", cargos)]

    # Teto POR EMPRESA, e não global: sem isso uma empresa grande consome a
    # cota inteira e as outras 49 saem vazias.
    porempresa: dict[str, list] = {}
    cortados = []
    for p in perfis:
        chave = (p.get("empresa") or "").strip().lower()
        if len(porempresa.setdefault(chave, [])) < max_por_empresa:
            porempresa[chave].append(p)
            cortados.append(p)
    perfis = cortados

    if not perfis:
        return {"status": "ok", "pessoas": [], "total": 0,
                "empresas_puladas": [],
                "message": ("Nenhum perfil dessas empresas no que já temos. "
                            "Busque na Bright Data para trazer de lá."
                            if fonte != "brightdata"
                            else "Nenhum perfil com esses filtros.")}

    cnpj_unico = re.sub(r"\D", "", str(empresas[0].get("cnpj") or "")) \
        if len(empresas) == 1 else ""
    try:
        r = await funil.prospeccao_b2b(
            perfis,
            uf=str(payload.get("uf") or "").strip().upper()[:2],
            cnpj=cnpj_unico,
            teto_brl=max(0.0, min(float(payload.get("teto_brl") or 6.0), 60.0)),
            so_com_telefone=payload.get("so_com_telefone", True) is not False)
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}
    r = {"status": "ok", "fonte": fonte, "custo_usd_brightdata": custo_usd, **r}
    return r if _is_admin(request) else _limpa_custo(r)


@app.post("/api/prospeccao/cobertura-decisores")
async def cobertura_decisores(payload: dict = Body(default={})):
    """Mede quantas empresas da amostra têm decisor na Assertiva, SEM puxar telefone.

    Serve pra decidir se vale montar a lista com decisores antes de gastar: o
    caro não é descobrir se existe decisor (2 consultas por empresa), é puxar
    telefone de cada um deles.

    Body: {cnpjs: [...], cargos: "diretor,gerente"}.
    Retorna a taxa de cobertura, a distribuição de cargos e a projeção de
    quantas empresas precisariam ser testadas pra fechar uma meta.
    """
    cnpjs = [re.sub(r"\D", "", str(c or "")) for c in (payload.get("cnpjs") or [])]
    cnpjs = [c for c in cnpjs if len(c) == 14][:60]
    cargos = str(payload.get("cargos") or "")
    if not cnpjs:
        return {"status": "error", "message": "Nenhum CNPJ válido na amostra."}
    if not assertiva.enabled():
        return {"status": "unavailable", "message": "Assertiva não configurada."}

    sem = asyncio.Semaphore(6)

    async def testar(cnpj: str) -> dict:
        async with sem:
            r = await assertiva.possiveis_decisores(cnpj)
        if r.get("status") != "ok":
            return {"cnpj": cnpj, "tem": False, "total": 0, "no_cargo": 0,
                    "motivo": r.get("status")}
        brutos = ((r.get("data") or {}).get("resposta") or {}).get("possiveisDecisores") or []
        todos = decisor_lib.da_assertiva(brutos)
        no_cargo = _filtra_decisores(todos, cargos, 0) if cargos else todos
        return {"cnpj": cnpj, "tem": bool(todos), "total": len(todos),
                "no_cargo": len(no_cargo), "motivo": "ok",
                "cargos": sorted({p["cargo"] for p in todos if p.get("cargo")})[:6]}

    resultados = await asyncio.gather(*[testar(c) for c in cnpjs])

    com_decisor = [r for r in resultados if r["tem"]]
    com_cargo = [r for r in resultados if r["no_cargo"]]
    dist: dict[str, int] = {}
    for r in resultados:
        for c in r.get("cargos") or []:
            dist[c] = dist.get(c, 0) + 1

    n = len(resultados)
    taxa = len(com_decisor) / n if n else 0
    taxa_cargo = len(com_cargo) / n if n else 0
    return {
        "status": "ok",
        "testadas": n,
        "com_decisor": len(com_decisor),
        "com_o_cargo": len(com_cargo),
        "taxa": round(taxa * 100, 1),
        "taxa_cargo": round(taxa_cargo * 100, 1),
        "media_decisores": round(sum(r["total"] for r in com_decisor) / len(com_decisor), 1)
                           if com_decisor else 0,
        "cargos_encontrados": dict(sorted(dist.items(), key=lambda x: -x[1])),
        "consultas_gastas": n * 2,   # cadastro + decisores por empresa
        "detalhe": resultados,
    }


@app.get("/api/company/{cnpj}/vinculos/assertiva")
async def company_vinculos_assertiva(cnpj: str):
    """Decisores da Assertiva prontos pra cruzar com a lista da RAIS que já
    está na tela: devolve só nome/CPF/cargo/nível, sem refazer a RAIS."""
    r = await company_decisores(cnpj)
    if r.get("status") != "ok":
        return r
    return {"status": "ok", "cnpj": r["cnpj"], "total": r["total"],
            "por_nivel": r["por_nivel"], "decisores": r["decisores"]}


@app.get("/api/company/{cnpj}/vinculos/cargos")
async def company_vinculos_cargos(cnpj: str):
    """Cargos do LinkedIn para cruzar com a lista da RAIS (lento e pago — opt-in).

    Devolve só o que casou por nome: {status, casados, cargos:[{cpf, cargo,
    nivel, rotulo, area}]}. O front aplica na lista que já está na tela, sem
    refazer a consulta da RAIS.
    """
    dados = await rais.vinculos_cnpj(cnpj)
    if dados.get("status") != "ok":
        return {"status": dados.get("status", "error"),
                "message": dados.get("message", "Sem vínculos para cruzar."), "cargos": []}

    try:
        empresa = await brasilapi.fetch_company(cnpj)
        nome = empresa.get("nome_fantasia") or empresa.get("razao_social") or ""
        legal = empresa.get("razao_social") or ""
    except Exception:
        nome = legal = ""

    try:
        scraped = await linkedin_scraper.scrape_employees(
            brasilapi.only_digits(cnpj), nome, legal)
    except Exception as exc:
        return {"status": "error", "message": f"Falha no LinkedIn: {str(exc)[:150]}", "cargos": []}

    vinculos = [dict(v) for v in (dados.get("vinculos") or [])]
    casados = decisor_lib.anexar_cargos_linkedin(vinculos, scraped.get("employees") or [])
    cargos = [{"cpf": v.get("cpf"), "nome": v.get("nome"), "cargo": v.get("cargo"),
               "fonte_cargo": v.get("fonte_cargo"), "nivel": v.get("nivel"),
               "rotulo": v.get("rotulo"), "area": v.get("area")}
              for v in vinculos if v.get("fonte_cargo") == "LinkedIn"]
    return {
        "status": "ok",
        "casados": casados,
        "perfis_linkedin": len(scraped.get("employees") or []),
        "message": scraped.get("message") or "",
        "cargos": cargos,
    }


_VIN_COLS = [
    ("nome", "Nome"),
    ("cargo", "Cargo"),
    ("nivel_txt", "Nível de decisão"),
    ("area", "Área"),
    ("fonte_cargo", "Fonte do cargo"),
    ("cpf", "CPF"),
    ("situacao_txt", "Situação"),
    ("admissao_br", "Admissão"),
    ("desligamento_br", "Desligamento"),
    ("tempo_casa", "Tempo de casa"),
]


@app.post("/api/vinculos/export")
async def vinculos_export(payload: dict = Body(default={})):
    """XLSX dos vínculos que estão na tela (já filtrados pelo front)."""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Font, PatternFill
    from openpyxl.utils import get_column_letter

    vinculos = payload.get("vinculos") or []
    cnpj = re.sub(r"\D", "", str(payload.get("cnpj") or ""))
    razao = str(payload.get("razao_social") or "")
    referencia = str(payload.get("referencia_br") or "")

    wb = Workbook()
    ws = wb.active
    ws.title = "Vinculos"

    ws["A1"] = f"Vínculos empregatícios — {razao or cnpj}"
    ws["A1"].font = Font(bold=True, size=12)
    ws["A2"] = (f"CNPJ {cnpj} · RAIS entregue em {referencia} · {len(vinculos)} pessoa(s) "
                f"· gerado pelo CapiBLU")
    ws["A2"].font = Font(size=9, color="666666")

    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="0F2E4A")  # azul-noite do design system
    for c, (_, label) in enumerate(_VIN_COLS, start=1):
        cell = ws.cell(row=4, column=c, value=label)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = Alignment(horizontal="center", vertical="center")

    for r, v in enumerate(vinculos, start=5):
        if not isinstance(v, dict):
            continue
        v = dict(v)
        v["situacao_txt"] = "Ainda na empresa" if v.get("ativo") else "Já saiu"
        nivel = v.get("nivel") or 0
        v["nivel_txt"] = f"{nivel} — {v.get('rotulo')}" if nivel else ""
        for c, (key, _) in enumerate(_VIN_COLS, start=1):
            ws.cell(row=r, column=c, value=v.get(key, ""))

    ws.freeze_panes = "A5"
    ws.auto_filter.ref = f"A4:{get_column_letter(len(_VIN_COLS))}{max(5, 4 + len(vinculos))}"
    for c, (key, label) in enumerate(_VIN_COLS, start=1):
        largura = 34 if key == "nome" else max(14, len(label) + 4)
        ws.column_dimensions[get_column_letter(c)].width = largura

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    nome_arquivo = f"vinculos-{cnpj or 'empresa'}.xlsx"
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": f'attachment; filename="{nome_arquivo}"'},
    )


async def _phones_for_cpf(cpf: str, modo: str = "celular", max_tel: int = 3,
                          fonte: str = "mk", modelo_id: str = "", modelo_nome: str = "",
                          cnpj: str = "") -> list[dict]:
    """Telefones para um CPF, filtrados/priorizados (celular atual primeiro).

    fonte: 'mk' (WorkAPI) | 'assertiva' (Localize). Ambos passam pelo mesmo
    refine_phones, garantindo o mesmo filtro (celular atual, dedupe, etc.).
    modelo_id/modelo_nome: se a fonte for assertiva, cada chamada é logada
    (custos.py) atribuída a esse modelo, pra rastrear gasto por planilha.
    """
    tels, _ = await _contato_for_cpf(cpf, modo, max_tel, fonte, modelo_id,
                                     modelo_nome, cnpj)
    return tels


async def _contato_for_cpf(cpf: str, modo: str = "celular", max_tel: int = 3,
                           fonte: str = "mk", modelo_id: str = "",
                           modelo_nome: str = "", cnpj: str = "") -> tuple:
    """Telefones E e-mails de um CPF, na MESMA consulta paga.

    Existe porque o e-mail estava sendo comprado e jogado fora: a resposta do
    Localize traz telefone e e-mail no mesmo corpo, e só o telefone era lido.
    A planilha tem colunas "Email 1" e "Email 2" desde sempre e elas saíam
    vazias -- não por falta de dado, por falta de leitura.

    O MK não devolve e-mail, então por ali a lista volta vazia. Isso importa
    na escolha da fonte: quem precisa de e-mail tem que usar a Assertiva.
    """
    if not cpf:
        return [], []
    try:
        if fonte == "assertiva":
            if not assertiva.enabled():
                return [], []
            r = await assertiva.telefones_documento(cpf, tipo="CPF")
            custos.log_assertiva(modelo_id=modelo_id, modelo_nome=modelo_nome, cnpj=cnpj, cpf=cpf)
            if r.get("status") == "ok":
                return (mkbuscas.refine_phones(r.get("telefones") or [],
                                               modo=modo, max_n=max_tel),
                        r.get("emails") or [])
            return [], []
        if not mkbuscas.enabled():
            return [], []
        mk = await mkbuscas.consulta_cpf(cpf)
        if mk.get("status") == "ok":
            raw = mkbuscas._extract_phones(mk.get("data") or {})
            return mkbuscas.refine_phones(raw, modo=modo, max_n=max_tel), []
    except Exception:
        pass
    return [], []


def _fmt_phone_digits(p: dict) -> str:
    ddd = str(p.get("ddd") or "").strip()
    num = str(p.get("number") or p.get("telefone") or "").strip()
    num = brasilapi.only_digits(num)
    if ddd and not num.startswith(ddd):
        return ddd + num
    return num or brasilapi.only_digits(str(p.get("telefone") or ""))


@app.post("/api/companies/search")
async def companies_search(payload: dict = Body(default={})):
    """Busca avancada de empresas (estilo Datastone) via Casa dos Dados.

    Body: {filtros: {...}, limite: int}. Retorna {status, total, empresas}.
    """
    filtros = payload.get("filtros") or {}
    limite = payload.get("limite") or 20
    offset = payload.get("offset") or 0
    # Base local (RFB) primeiro: sem cap de 20 e instantanea. Fallback: Casa dos Dados.
    if _cnpj_local():
        res = cnpj_lookup.search(filtros, limite=limite, offset=offset)
        res["fonte"] = "local"
        return res
    if not casadosdados.enabled():
        return {"status": "unavailable", "message": "Busca avancada indisponivel.", "empresas": []}
    res = await casadosdados.pesquisa_avancada(filtros, limite)
    res["fonte"] = "casadosdados"
    return res


# ---------------------------------------------------------------------
# LISTA UNIFICADA DE EMPRESAS — Receita + LinkedIn na mesma tabela
# ---------------------------------------------------------------------
#
# É o desenho da Datastone, e ele foi copiado de propósito depois de olhar as
# capturas do backoffice deles. O que eles fazem, e que faz sentido:
#
#   - uma base só, onde PARTE das empresas tem CNPJ e parte não
#   - um toggle "Possui CNPJ" (tooltip literal deles: "Esta opção indica se a
#     empresa possui CNPJ") — ou seja, eles assumem a falha em vez de escondê-la
#   - `/internal/v1/company/employees/` recebe `companyId` E `cnpj` juntos,
#     porque qualquer um dos dois pode faltar
#
# Aqui as duas fontes são complementares e nenhuma cobre a outra:
#
#   Receita   1,3 mi de estabelecimentos ativos com CNPJ, CNAE, situação,
#             capital, endereço. Grátis e instantânea. NÃO sabe quantas
#             pessoas trabalham lá nem o que a empresa diz de si.
#   LinkedIn  1,36 mi de páginas com contagem real de funcionários, tipo de
#             organização e fundação. COBRA por empresa entregue e não tem
#             CNPJ — ele é deduzido pelo domínio (ver empresa_cnpj).
#
# A fusão é por CNPJ. Empresa que aparece nas duas vira UMA linha com as
# colunas das duas; empresa que só existe num lado vem assim mesmo, marcada.

# Filtros que SÓ o LinkedIn responde. Se um deles estiver ligado e a busca não
# for ao LinkedIn, ele não filtra nada — e um filtro que silenciosamente não
# faz nada é pior que um filtro ausente, porque a pessoa confia no resultado.
FILTROS_SO_LINKEDIN = ("porte_min", "tipos", "fundada_apos", "sites")


def _digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


def _cnpj_bonito(v) -> str:
    """00.000.000/0000-00. A Receita ja devolve formatado e a deducao do
    LinkedIn devolve so digitos -- numa lista fundida isso apareceria como
    duas colunas diferentes na mesma coluna."""
    d = _digitos(v)
    if len(d) != 14:
        return str(v or "")
    return "%s.%s.%s/%s-%s" % (d[:2], d[2:5], d[5:8], d[8:12], d[12:])


def _linha_unificada(base: dict | None, li: dict | None) -> dict:
    """Uma linha da tabela, vinda de uma fonte ou das duas."""
    base = base or {}
    li = li or {}
    fontes = []
    if base:
        fontes.append("receita")
    if li:
        fontes.append("linkedin")
    return {
        # --- lado Receita (vazio quando a empresa só existe no LinkedIn) ---
        "cnpj": _cnpj_bonito(base.get("cnpj") or li.get("cnpj") or ""),
        "razao_social": base.get("razao_social") or "",
        "nome_fantasia": base.get("nome_fantasia") or "",
        "uf": base.get("uf") or "",
        "municipio": base.get("municipio") or "",
        "situacao": base.get("situacao") or "",
        "cnae": base.get("cnae") or "",
        "cnae_codigo": base.get("cnae_codigo") or "",
        "porte": base.get("porte") or "",
        "capital_social": base.get("capital_social") or 0,
        "telefone_1": base.get("telefone_1") or "",
        "telefone_2": base.get("telefone_2") or "",
        "email": base.get("email") or "",
        # --- lado LinkedIn (vazio quando só a Receita conhece) ---
        "nome_linkedin": li.get("nome") or "",
        "url_linkedin": li.get("url") or "",
        "company_id": li.get("company_id") or "",
        "funcionarios_linkedin": li.get("funcionarios_linkedin"),
        "setor_linkedin": li.get("setor") or "",
        "tipo_organizacao": li.get("tipo") or "",
        "fundada": li.get("fundada") or "",
        "site": li.get("site") or "",
        # --- de onde veio, e o que a linha permite fazer -------------------
        "fontes": fontes,
        # A tela precisa disto para explicar por que "Montar lista" não serve
        # para esta linha: sem CNPJ não há QSA, não há sócio, não há decisor
        # da Assertiva. É a mesma limitação que a Datastone tem.
        "tem_cnpj": bool(_digitos(base.get("cnpj") or li.get("cnpj"))),
        "cnpj_confianca": (li.get("cnpj_confianca") or "")
                          if not base else ("receita" if base else ""),
        "cnpj_motivo": li.get("cnpj_motivo") or "",
    }


@app.post("/api/empresas/unificada")
async def empresas_unificada(request: Request, payload: dict = Body(default={})):
    """Receita e LinkedIn na mesma lista, como a Datastone faz.

    A Receita responde sozinha o que ela sabe. Quando o filtro só existe no
    LinkedIn -- porte, tipo de organização, fundação -- a busca vai lá SEM
    PERGUNTAR: quem prospecta escolhe o perfil da empresa, não o orçamento.

    O controle de gasto não sumiu, mudou de lugar. Fica em `limite_linkedin`
    (teto baixo por padrão), na base local que absorve tudo que já foi
    comprado, e no extrato da aba de administração. Nenhum deles atrapalha
    quem está montando lista.

    `so_com_cnpj` é o "Possui CNPJ" deles. Filtra a lista JÁ MONTADA, então
    não reduz o que foi cobrado — reduz o que aparece. A resposta separa
    `registros_cobrados` de `total` para a tela poder dizer isso.
    """
    filtros = payload.get("filtros") or {}
    limite = min(int(payload.get("limite") or 50), 200)
    offset = int(payload.get("offset") or 0)
    quer_linkedin = bool(payload.get("linkedin"))
    so_com_cnpj = bool(payload.get("so_com_cnpj"))

    pedidos_li = [k for k in FILTROS_SO_LINKEDIN if filtros.get(k)]

    # A ROTAÇÃO É LIDA AQUI EM CIMA porque ela vale para as DUAS fontes.
    # Ficava só no caminho da Receita, e quando o disco passou a responder a
    # rotação morreu junto: a mesma busca devolvia as mesmas três empresas
    # para sempre, de graça — grátis e inútil.
    giro = rodadas.ler(filtros) if not offset else {"offset": 0, "cursor": None}

    # FILTRO QUE SÓ O LINKEDIN RESPONDE VAI SOZINHO, SEM PERGUNTAR.
    #
    # E ISTO TEM QUE SER DECIDIDO AQUI, antes de escolher quem comanda a
    # busca. Estava depois, e o efeito era silencioso e grave: `quer_linkedin`
    # ainda era falso quando a Receita decidia entrar, então uma busca por
    # "mais de 300 funcionários" vinha com consulado e cartório dentro --
    # linhas que a Receita devolveu e que não satisfazem o filtro nenhum,
    # porque a Receita não sabe quantas pessoas trabalham em lugar algum.
    #
    # A tela de permissão que existia aqui foi removida: ela empurrava para
    # o operador uma decisão de custo que não é dele. Quem prospecta escolhe
    # o perfil da empresa; o orçamento é do admin, que tem o extrato na aba
    # de administração. O limite continua em `limite_linkedin`, que tem teto
    # e padrão baixo.
    if pedidos_li:
        quer_linkedin = True

    # A API COMANDA; O BANCO COMPLETA.
    #
    # Decisão da Rebeca: não buscar pelo banco a menos que a API não ache
    # empresa suficiente. O motivo é o que a operação quer da aba -- empresa
    # que ela ainda não viu. A base da Receita é a mesma todo dia; o LinkedIn
    # é onde aparece quem entrou agora, e é lá que estão porte, tipo e setor
    # como a própria empresa se descreve.
    #
    # A API só pode comandar quando entende ALGUM filtro. Ela não sabe ler
    # código CNAE, situação cadastral, capital social nem natureza jurídica
    # -- isso é cadastro, e cadastro é da Receita. Numa busca feita só com
    # esses, mandar a API seria pedir "todas as empresas do Brasil" e pagar
    # por uma amostra aleatória.
    _API_ENTENDE = ("texto", "nomes", "nome_empresa", "setores", "sites",
                    "porte_min", "tipos", "fundada_apos", "uf", "ufs",
                    "municipio", "cidade")
    if any(filtros.get(k) for k in _API_ENTENDE):
        quer_linkedin = True

    # A BASE LOCAL PRIMEIRO. É o que faz a tela parecer a da Datastone: quando
    # o filtro cabe dentro da fatia já ingerida, a resposta sai do disco, em
    # milissegundos, de graça, e sem perguntar nada a ninguém. Só fora dela é
    # que a pergunta "posso gastar?" volta a fazer sentido.
    #
    # `completa` é a condição, e ela é estrita: a ingestão registra "func>200
    # terminou" e só então uma busca por porte >= 200 pode ser respondida
    # inteiramente daqui. Abaixo do piso a base tem parte das empresas, e
    # apresentá-la como tudo faria a pessoa concluir que o resto não existe.
    local = None
    if pedidos_li and empresas_li.disponivel():
        local = empresas_li.buscar(
            porte_min=int(filtros.get("porte_min") or 0),
            porte_max=int(filtros.get("porte_max") or 0),
            tipos=filtros.get("tipos"),
            fundada_apos=int(filtros.get("fundada_apos") or 0),
            setores=filtros.get("setores"),
            nomes=filtros.get("nomes") or filtros.get("texto") or "",
            ufs=filtros.get("uf") or filtros.get("ufs"),
            limite=min(int(payload.get("limite_linkedin") or 50), 200),
            # Continua de onde a rodada anterior parou -- é isto que faz a
            # mesma busca trazer empresa diferente, e de graça enquanto o
            # disco tiver.
            offset=giro["offset"])
        # QUANDO O DISCO BASTA.
        #
        # A primeira versão só aceitava o disco quando a fatia estava
        # INTEIRA ingerida (`completa`). Isso fazia sentido para uma base
        # comprada de uma vez, e nenhum para uma base que cresce sozinha a
        # cada compra: acumulando aos poucos, `completa` nunca fica
        # verdadeira, e o disco -- que já tem a resposta -- nunca seria
        # usado. Pagaríamos de novo por empresa que já está aqui.
        #
        # O critério que serve para os dois casos é este: o disco responde
        # quando ele TEM UMA PÁGINA CHEIA. Se tem, a pessoa recebe resultado
        # grátis e instantâneo; se falta, aí sim vale perguntar lá fora.
        #
        # A diferença entre os dois casos não some, ela vira rótulo:
        # `completa` continua dizendo se aquilo é TUDO que existe no filtro,
        # e a tela usa isso para oferecer "buscar mais" sem mentir que a
        # lista acabou.
        pagina = min(int(payload.get("limite_linkedin") or 25), 100)
        # O DISCO NÃO SUBSTITUI A BUSCA, ele a acumula.
        #
        # Eu tinha feito o disco responder sempre que tivesse uma página
        # cheia, para economizar. A Rebeca corrigiu a premissa: o preço por
        # empresa é baixo e o objetivo da aba é justamente trazer empresa
        # NOVA a cada busca. Sob essa premissa, deixar o disco responder é
        # servir o que já foi visto quando se queria o que ainda não foi.
        #
        # Então o disco só responde quando a fatia está INTEIRA ingerida --
        # aí ele tem o universo do filtro e não há nada novo para buscar
        # fora dele. Nos outros casos a busca vai à Bright Data, que
        # continua do cursor e por construção devolve inédito, e o que vier
        # fica guardado aqui.
        #
        # O acúmulo continua valendo por outros motivos: alimenta a ponte do
        # CNPJ, sobrevive a falha da API, e é o que faz a fatia comprada
        # valer alguma coisa.
        if local.get("status") != "ok" or not local.get("completa"):
            local = None
    if local is not None:
        pedidos_li = []          # respondidos aqui, sem custo
        quer_linkedin = True     # e o lado LinkedIn já está resolvido

    # ---- lado Receita ------------------------------------------------
    #
    # NAO roda quando o LinkedIn vai comandar. Parece desperdicio deixar de
    # usar uma base gratis, mas as linhas dela nao passariam pelo filtro que
    # a pessoa pediu: numa busca por "+200 funcionarios" a Receita devolve
    # MEIs, porque ela nao sabe quantos funcionarios ninguem tem. Medido --
    # as 8 primeiras linhas da lista eram MEIs de uma pessoa so, no meio de
    # um filtro de empresa grande.
    #
    # Lista que desobedece o filtro e pior que lista curta: a pessoa confia
    # no que pediu e liga para a empresa errada.
    base = {"empresas": [], "total": 0}
    # A Receita comanda só quando a API não pode -- ou seja, quando a busca
    # usou apenas filtros de cadastro. Nos outros casos ela entra depois,
    # completando o que faltou e enriquecendo por CNPJ, de graça.
    receita_comanda = local is None and not quer_linkedin
    # ROTACAO. A mesma busca repetida continua de onde parou, em vez de
    # devolver as mesmas empresas -- ver rodadas.py sobre por que avancar e
    # melhor que embaralhar. Só quando a tela não pediu uma página específica.
    if _cnpj_local() and receita_comanda:
        base = cnpj_lookup.search(filtros, limite=limite,
                                  offset=offset or giro["offset"])
        if not offset:
            trazidas = len(base.get("empresas") or [])
            rodadas.avancar(filtros, trazidas, acabou=(trazidas < limite))
    por_cnpj: dict[str, dict] = {}
    ordem: list[str] = []
    for e in base.get("empresas") or []:
        d = _digitos(e.get("cnpj"))
        if d and d not in por_cnpj:
            por_cnpj[d] = {"base": e, "li": None}
            ordem.append(d)


    # ---- lado LinkedIn: só quando pedido, porque cobra ----------------
    #
    # QUEM COMANDA A BUSCA. Se há filtro que só o LinkedIn responde, é ele que
    # seleciona e a Receita completa; senão a Receita seleciona e o LinkedIn
    # completa. Nunca as duas em paralelo: a primeira versão fazia isso e
    # media 0 empresas em comum, porque duas amostras de 8 e 10 linhas tiradas
    # de milhares não se cruzam. Dava uma tela que parecia fundida e eram duas
    # listas empilhadas.
    cobrados = 0
    custo = 0.0
    total_li = None
    if receita_comanda and local is None:
        # RECEITA COMANDA -- e agora isso só acontece quando a API NÃO PODE,
        # ou seja, numa busca feita só com filtros de cadastro. A condição
        # antes era `quer_linkedin and not pedidos_li`, e com a API passando
        # a comandar por padrão ela ficou invertida: entrava-se aqui para
        # enriquecer uma lista da Receita que nunca tinha sido buscada, e o
        # resultado era a API devolver zero e o banco completar tudo --
        # exatamente o contrário do que foi pedido.
        #
        # Cada linha vira uma consulta de 1 registro para achar a mesma
        # empresa no LinkedIn pelo domínio. Tem teto porque é por empresa:
        # 50 linhas são 50 registros.
        teto_enriq = min(int(payload.get("enriquecer_ate") or 25), 50)
        # UMA CONSULTA POR RAIZ, nao por linha. Filial nao tem pagina propria
        # no LinkedIn: as 6 filiais da Selbetti apontam para a mesma empresa,
        # e a versao anterior pagava 6 vezes pela mesma resposta. A chave do
        # LinkedIn e o dominio, e o dominio sai da RAIZ do CNPJ -- entao a
        # consulta tambem tem que ser por raiz.
        por_raiz: dict[str, list[str]] = {}
        for k in ordem:
            d = _digitos(k)
            if len(d) == 14:
                por_raiz.setdefault(d[:8], []).append(k)
        for raiz in list(por_raiz)[:teto_enriq]:
            achou = await brightdata_pessoas.nome_no_linkedin(cnpj=raiz)
            if (achou or {}).get("status") != "ok":
                continue
            cobrados += 1
            custo += float(achou.get("custo_usd") or 0)
            dados = {
                "nome": achou.get("nome") or "",
                "url": achou.get("url") or "",
                "company_id": achou.get("company_id") or "",
                "funcionarios_linkedin": achou.get("funcionarios_linkedin"),
                "site": achou.get("dominio") or "",
            }
            for k in por_raiz[raiz]:
                por_cnpj[k]["li"] = dados
    elif local is not None or quer_linkedin:
        # As duas origens do lado LinkedIn -- disco e API -- devolvem a MESMA
        # forma de resposta, de propósito. Só a origem muda aqui; o que
        # acontece com o resultado é um bloco só, embaixo.
        #
        # A primeira versão atribuía `r = local` num `elif` e deixava o código
        # que consome `r` dentro do `elif` seguinte, que não era tomado: a
        # busca local respondia certo, de graça, e a lista saía vazia. Custo
        # zero e resultado zero parecem a mesma coisa na tela.
        if local is not None:
            r = local
            if not offset:
                trazidas = len(r.get("empresas") or [])
                rodadas.avancar(filtros, trazidas,
                                acabou=(trazidas < pagina))
        else:
            r = await brightdata_pessoas.buscar_empresas_por_filtro(
                pais=str(filtros.get("pais") or "BR"),
                nomes=filtros.get("nomes") or filtros.get("texto") or "",
                sites=filtros.get("sites"),
                porte_min=int(filtros.get("porte_min") or 0),
                porte_max=int(filtros.get("porte_max") or 0),
                tipos=filtros.get("tipos"),
                fundada_apos=int(filtros.get("fundada_apos") or 0),
                setores=filtros.get("setores"),
                # A UF TEM que ir junto. Sem ela o lado LinkedIn ignora o estado
                # escolhido e a lista mistura empresa de SC com empresa de
                # qualquer lugar -- e pior, parece certa na tela. Foi o resultado
                # do primeiro teste desta fusão: 0 empresas em comum entre as
                # fontes, porque cada uma estava procurando outra coisa.
                ufs=filtros.get("uf") or filtros.get("ufs"),
                cidade=str(filtros.get("municipio") or filtros.get("cidade") or ""),
                so_com_cnpj=False,          # a fusão decide depois, não a fonte
                limite=min(int(payload.get("limite_linkedin") or 25), 100),
                # CURSOR GUARDADO. Sem ele, repetir a busca traz os MESMOS
                # primeiros N registros e cobra por eles de novo -- o pedido
                # de "trazer empresas novas" produziria o oposto.
                cursor=giro.get("cursor"),
                usuario=(request.headers.get("x-user-email") or ""))
        if r.get("status") != "ok":
            # A Receita já respondeu: devolve o que tem em vez de perder tudo.
            return {"status": "ok",
                    "empresas": [_linha_unificada(por_cnpj[d]["base"], None)
                                 for d in ordem],
                    "total": len(ordem), "registros_cobrados": 0,
                    "custo_usd": 0.0,
                    "message": "Receita ok; LinkedIn falhou: %s"
                               % (r.get("message") or "")}
        cobrados = int(r.get("registros_cobrados") or 0)
        custo = float(r.get("custo_usd") or 0)
        total_li = r.get("total_no_dataset")
        if not offset and r.get("cursor"):
            rodadas.avancar(filtros, 0, cursor=r.get("cursor"))
        for e in r.get("empresas") or []:
            d = _digitos(e.get("cnpj"))
            if d and d in por_cnpj:
                por_cnpj[d]["li"] = e          # mesma empresa, duas fontes
            elif d:
                por_cnpj[d] = {"base": None, "li": e}
                ordem.append(d)
            else:
                # Sem CNPJ não há chave para fundir. Entra como linha própria,
                # e é justamente esta que o "Possui CNPJ" tira.
                chave = "li:" + (e.get("url") or e.get("nome") or str(len(ordem)))
                por_cnpj[chave] = {"base": None, "li": e}
                ordem.append(chave)

        # A RECEITA COMPLETA, e isso é de graça: base local, consulta por
        # chave. Toda empresa que o LinkedIn trouxe com CNPJ ganha razão
        # social, CNAE, situação e capital sem custo nenhum. Não fazer isso
        # seria deixar metade da linha vazia por preguiça.
        for k in ordem:
            if por_cnpj[k]["base"] or not por_cnpj[k]["li"]:
                continue
            d = _digitos(por_cnpj[k]["li"].get("cnpj"))
            if len(d) != 14:
                continue
            try:
                co = cnpj_lookup.by_cnpj(d)
            except Exception:
                continue
            if (co or {}).get("status") != "ok":
                continue
            c = co.get("company") or co
            por_cnpj[k]["base"] = {
                "cnpj": c.get("cnpj") or d,
                "razao_social": c.get("razao_social") or "",
                "nome_fantasia": c.get("nome_fantasia") or "",
                "uf": c.get("uf") or "",
                "municipio": c.get("municipio") or "",
                "situacao": c.get("descricao_situacao_cadastral") or "",
                "cnae": c.get("cnae_fiscal_descricao") or "",
                "cnae_codigo": c.get("cnae_fiscal") or "",
                "porte": c.get("porte") or "",
                "capital_social": c.get("capital_social") or 0,
                "telefone_1": c.get("ddd_telefone_1") or "",
                "email": c.get("email") or "",
            }

    # ---- o banco COMPLETA quando a API nao achou o suficiente ---------
    #
    # É o "a menos que" do pedido. Lista curta é pior que lista com empresa
    # já conhecida: quem precisa de 25 para ligar hoje não pode receber 4
    # porque o LinkedIn não conhecia as outras 21.
    completou_do_banco = 0
    if (quer_linkedin and _cnpj_local() and not receita_comanda
            and len(ordem) < limite):
        falta = limite - len(ordem)
        try:
            extra = cnpj_lookup.search(filtros, limite=falta * 2,
                                       offset=offset or giro["offset"])
        except Exception:
            extra = {"empresas": []}
        for e in extra.get("empresas") or []:
            if len(ordem) >= limite:
                break
            d = _digitos(e.get("cnpj"))
            # Não duplica quem a API já trouxe: a mesma empresa apareceria
            # duas vezes, uma com as colunas do LinkedIn e outra sem.
            if not d or d in por_cnpj:
                continue
            por_cnpj[d] = {"base": e, "li": None}
            ordem.append(d)
            completou_do_banco += 1

    linhas = [_linha_unificada(por_cnpj[k]["base"], por_cnpj[k]["li"])
              for k in ordem]
    sem_cnpj = sum(1 for l in linhas if not l["tem_cnpj"])
    nas_duas = sum(1 for l in linhas if len(l["fontes"]) == 2)
    if so_com_cnpj:
        linhas = [l for l in linhas if l["tem_cnpj"]]

    return {
        "status": "ok",
        "empresas": linhas,
        "total": len(linhas),
        "total_receita": base.get("total") or 0,
        "total_linkedin": total_li,
        "nas_duas_fontes": nas_duas,
        "sem_cnpj": sem_cnpj,
        "registros_cobrados": cobrados,
        "custo_usd": custo,
        "linkedin_necessario": False,
        # Veio do disco, e o disco pode não ter o universo todo deste filtro.
        # Dizer isso é o que permite oferecer "buscar mais" sem dar a
        # entender que a lista acabou.
        "do_disco": local is not None,
        "disco_completo": bool(local and local.get("completa")),
        # Quantas vieram do banco por falta de resultado na API. "O LinkedIn
        # achou 4, completamos com 21 da Receita" é diferente de "achamos 25
        # no LinkedIn", e a tela precisa poder dizer qual dos dois foi.
        "completou_do_banco": completou_do_banco,
    }


@app.post("/api/prospeccao/pessoas")
async def prospeccao_pessoas(payload: dict = Body(default={})):
    """Busca de decisores. TRÊS CAMADAS, da mais barata para a mais cara.

    1. CACHE do LinkedIn — 9 mil perfis já comprados, instantâneo e grátis.
       É o que a tela mostra primeiro, como a Datastone faz com a base dela.
    2. SÓCIOS da Receita — 27,8 milhões, local e grátis. Cobre quem é DONO;
       não vê o gerente contratado.
    3. Bright Data — 43,2 milhões de perfis. Cobra por registro entregue, e
       só entra quando o operador pede (`fonte: "brightdata"`).

    Departamento e senioridade só existem nas camadas 1 e 3: a Receita tem
    qualificação SOCIETÁRIA, não cargo. Filtrar sócio por "TI" devolveria
    vazio, então esses filtros não são aplicados à camada 2 — e a resposta diz
    qual camada respondeu, para a tela poder explicar por que o filtro não
    mordeu.
    """
    filtros = payload.get("filtros") or {}
    limite = int(payload.get("limite") or 20)
    offset = int(payload.get("offset") or 0)
    fonte = str(payload.get("fonte") or "").strip().lower()

    # ---- camada 3: só quando pedida, porque cobra --------------------
    if fonte == "brightdata":
        try:
            r = await brightdata_pessoas.buscar_por_filtro(
                pais="BR",
                empresas=filtros.get("nome_empresa") or "",
                cargos_termos=filtros.get("cargo") or "",
                nome=filtros.get("nome") or "",
                sobrenome=filtros.get("sobrenome") or "",
                cidade=(filtros.get("cidade")
                        or filtros.get("localizacao_pessoa") or ""),
                departamentos=filtros.get("departamento") or "",
                # "Especialidades" casa no campo `about` do perfil, que é onde
                # a pessoa descreve o que faz. Estava desabilitado com o aviso
                # "requer dataset de perfis profissionais" -- o dataset existe
                # desde que a busca por filtro foi ligada.
                palavras=filtros.get("especialidades") or "",
                so_com_email=bool(filtros.get("so_com_email")),
                limite=min(limite, 100),
                usuario=str(payload.get("usuario") or ""))
            r["fonte"] = "brightdata"
            return r
        except Exception as exc:
            return {"status": "error", "fonte": "brightdata",
                    "message": str(exc)[:200], "pessoas": []}

    # ---- camada 1: o cache, de graça ---------------------------------
    #
    # SÓ RESPONDE QUANDO SABE HONRAR TODOS OS FILTROS. O cache guarda perfil
    # do LinkedIn: ele conhece nome, empresa, cargo, cidade. Não conhece CNAE,
    # situação cadastral, capital social nem matriz/filial — isso é cadastro
    # da Receita e não existe num perfil.
    #
    # Antes ele respondia mesmo assim, e como é a PRIMEIRA camada, a resposta
    # dele encerrava a busca: uma consulta por "alimentos" em SC devolvia
    # "BLU Sales Group" e "Braskem", porque só o UF tinha sido aplicado e o
    # resto foi descartado no caminho. Quanto MAIS filtros a pessoa usava,
    # pior ficava — e a camada da Receita, que filtraria certo, nunca era
    # alcançada.
    _CADASTRAIS = ("cnae", "setor", "situacao", "capital_min", "capital_max",
                   "somente_matriz", "mei_optante", "mei_excluir",
                   "natureza", "porte", "fundada_de", "fundada_ate",
                   "com_telefone", "tipo_empresa", "anos_min", "anos_max")
    cache_pode = not any(filtros.get(k) for k in _CADASTRAIS)
    try:
        do_cache = linkedin_cache.procurar(
            # `texto` é a lupa da tela e também não estava sendo passada.
            q=filtros.get("texto") or "",
            nome=filtros.get("nome") or "", empresa=filtros.get("nome_empresa") or "",
            cargo=filtros.get("cargo") or "",
            departamento=filtros.get("departamento") or "",
            senioridade=filtros.get("senioridade") or "",
            ufs=filtros.get("uf") or "",
            cidade=(filtros.get("cidade")
                    or filtros.get("localizacao_pessoa") or ""),
            palavras=filtros.get("especialidades") or "",
            # URL identifica UMA pessoa: quando vem preenchida, é ela que se
            # procura, e os outros filtros só podem restringir.
            linkedin_url=filtros.get("linkedin_url") or "",
            limite=limite) if cache_pode else []
    except Exception:
        do_cache = []
    if do_cache:
        return {"status": "ok", "fonte": "cache", "total": len(do_cache),
                "pessoas": do_cache,
                "message": "Do que já foi comprado — não gastou nada."}

    # ---- camada 2: sócios da Receita ---------------------------------
    if not _cnpj_local():
        return {"status": "unavailable", "fonte": "receita",
                "message": "Base local indisponível.", "pessoas": []}
    r = cnpj_lookup.search_pessoas(filtros, limite=limite, offset=offset)
    r["fonte"] = "receita"

    # OS QUATRO QUE ESTA CAMADA NÃO SABE RESPONDER, e o motivo é o mesmo: a
    # Receita conhece SÓCIO, não pessoa. Sócio tem qualificação societária
    # ("Sócio-Administrador"), não departamento nem senioridade; e o cadastro
    # não traz e-mail nem telefone DA PESSOA — os contatos são da empresa.
    #
    # Estruturado, e não só um texto: a tela precisa saber QUAIS foram
    # ignorados para oferecer a camada que os responde. Auditado em
    # 10/set/2026 — os quatro estavam sendo aceitos e descartados em silêncio,
    # junto com outros seis que agora funcionam.
    _SO_LINKEDIN = {
        "departamento": "departamento",
        "senioridade": "senioridade",
        "so_com_email": "só com e-mail",
        "so_com_telefone": "só com telefone",
        # Estes três estavam desabilitados na tela com um "🔜". O dataset que
        # eles esperavam existe agora — mas continuam sendo do LADO LinkedIn:
        # a Receita registra o endereço da EMPRESA, não o da pessoa, e não
        # sabe o que ela declara saber fazer.
        "localizacao_pessoa": "localização da pessoa",
        "especialidades": "especialidades",
        "linkedin_url": "perfil do LinkedIn",
        # `so_com_linkedin` NÃO entra aqui: a Receita não sabe responder isso
        # na consulta, mas a tela cruza o resultado com o cache logo depois e
        # aí dá para saber quem tem perfil. Ela aplica o corte. Listar aqui
        # seria avisar que um filtro foi ignorado quando ele não foi.
    }
    ignorados = [rotulo for chave, rotulo in _SO_LINKEDIN.items()
                 if filtros.get(chave)]
    if ignorados:
        r["filtros_ignorados"] = ignorados
        r["linkedin_necessario"] = True
        r["aviso"] = (
            "Não foi aplicado: %s. A Receita conhece SÓCIO, não pessoa — sócio "
            "tem qualificação societária, não departamento nem senioridade, e o "
            "cadastro não traz contato da pessoa. Esses filtros existem na busca "
            "do LinkedIn." % ", ".join(ignorados))
    return r


def _resolve_modelo(modelo_id: str) -> str:
    """Nome de exibição do modelo, pra atribuir custo (custos.py)."""
    if not modelo_id:
        return ""
    if modelo_id == custos.CLIENTE_ID:
        return custos.CLIENTE_NOME
    for m in _modelos_load():
        if m.get("id") == modelo_id:
            return m.get("nome") or modelo_id
    return modelo_id


def _filtra_decisores(lista: list[dict], cargos: str, maximo: int) -> list[dict]:
    """Filtra a lista de decisores por cargo/nível e corta no máximo pedido.

    `cargos` é uma lista separada por vírgula que aceita as duas linguagens:
    número de nível ("1,2") ou pedaço do nome do cargo ("diretor,gerente").
    Vazio = todos. A ordem final é por nível (decisor mais alto primeiro).
    """
    escolhidos = [c.strip().lower() for c in (cargos or "").split(",") if c.strip()]
    if escolhidos:
        # TERCEIRA linguagem, nova: "gerencia:vendas" — nível E área juntos.
        # Os seis botões da tela dizem só o nível, e "Diretor" não distingue
        # Diretor de TI de Diretor Comercial. O select de área ao lado manda
        # neste formato, e quem entende é o dicionário do classificador.
        com_area = [c for c in escolhidos if ":" in c or c in funcoes.AREAS]
        simples = [c for c in escolhidos if c not in com_area]
        niveis = {int(c) for c in simples if c.isdigit()}
        termos = [c for c in simples if not c.isdigit()]
        lista = [p for p in lista
                 if (p.get("nivel") in niveis)
                 or any(t in (p.get("cargo") or "").lower() for t in termos)
                 or (com_area
                     and funcoes.casa_escolha(p.get("cargo") or "", com_area))]
    lista = sorted(lista, key=lambda p: (p.get("nivel") or 9, p.get("nome") or ""))
    return lista[:maximo] if maximo and maximo > 0 else lista


@app.get("/api/company/{cnpj}/leads")
async def company_leads(cnpj: str, decisores: bool = False,
                        modo_tel: str = "celular", max_tel: int = 3,
                        fonte_tel: str = "mk",
                        socios_modo: str = "todos", max_socios: int = 0,
                        modelo_id: str = "",
                        decisores_fonte: str = "assertiva",
                        decisores_cargos: str = "",
                        max_decisores: int = 3,
                        pular_sem_decisor: bool = False,
                        fallback_hierarquia: int = 0,
                        apenas_cargo: bool = False,
                        so_com_telefone: bool = True):
    """Enriquece UMA empresa com contatos (socios do QSA + telefones).

    Retorna {status, empresa:{...}, contatos:[{tipo, nome, cargo, cpf, telefones[]}]}.
    modo_tel: 'celular' (padrao) | 'celular_fixo' | 'todos'.
    fonte_tel: 'mk' (WorkAPI) | 'assertiva' (Localize).
    max_tel: max de telefones por contato.
    socios_modo: 'todos' (padrao) | 'admin' (so socio-administrador/diretor/presidente).
    max_socios: 0 = sem limite; N = no maximo N socios (apos ordenar por qualificacao).
    modelo_id: modelo salvo (ou custos.CLIENTE_ID p/ planilha externa) — usado
    só pra atribuir o custo das consultas Assertiva desta montagem.

    Se decisores=true, anexa tambem quem manda na empresa sem ser socio:
    decisores_fonte: 'assertiva' (padrao — cargo real, rapido, 2 consultas por
      empresa) | 'linkedin' (lento e frequentemente bloqueado).
    decisores_cargos: filtro por nivel ("1,2") ou por nome de cargo
      ("diretor,gerente"); vazio = todos.
    max_decisores: teto por empresa (padrao 3). Importa no custo: cada decisor
      trazido ainda gasta uma consulta de telefone.
    pular_sem_decisor: descarta a empresa inteira quando a base nao tem nenhum
      decisor pra ela (micro empresa quase sempre cai aqui). Nem os socios vem.
    fallback_hierarquia: se o filtro de cargo nao casar com ninguem, traz ate N
      decisores pela hierarquia (nivel 1 primeiro). 0 = desligado.
    apenas_cargo: modo estrito — a lista fica SO com decisores do cargo pedido.
      Sem socios, sem fallback, e empresa que nao tem ninguem naquele cargo sai
      da lista. Serve pra campanha mirando um cargo especifico.
    so_com_telefone: NASCE LIGADO (decisao da Rebeca). Corta da lista quem nao
      voltou com nenhum telefone, e quando NINGUEM da empresa voltou com
      telefone a empresa inteira sai -- com o motivo em `pulada`, para a tela
      poder dizer por que ela sumiu em vez de a pessoa achar que e bug.

      A lista existe para discar. Linha sem telefone nao e lead pela metade:
      e uma linha que o operador vai percorrer com o olho e descartar, e que
      na planilha empurra as boas para baixo.

      Corta DEPOIS da consulta, e nao ha como ser antes -- so se sabe que nao
      ha telefone tendo perguntado. Ou seja: ele limpa a planilha, nao reduz
      o custo. Quem quer reduzir custo mexe em `max_decisores`.
    """
    # Base local (RFB) primeiro — instantânea e traz o QSA. Fallback: BrasilAPI.
    data = None
    if _cnpj_local():
        loc = cnpj_lookup.by_cnpj(cnpj)
        if loc.get("status") == "ok":
            data = loc["company"]
    if data is None:
        try:
            data = await brasilapi.fetch_company(cnpj)
        except LookupError:
            return {"status": "not_found", "cnpj": cnpj, "contatos": []}
        except Exception:
            return {"status": "error", "cnpj": cnpj, "message": "Falha BrasilAPI", "contatos": []}

    _enrich_qsa_cpf(data)
    qsa_all = [s for s in (data.get("qsa") or []) if isinstance(s, dict)]
    empresa = {
        "cnpj": brasilapi.format_cnpj(str(data.get("cnpj", "")) or cnpj),
        "razao_social": data.get("razao_social") or "",
        "nome_fantasia": data.get("nome_fantasia") or "",
        "municipio": data.get("municipio") or "",
        "uf": data.get("uf") or "",
        "porte": data.get("porte") or "",
        "capital_social": data.get("capital_social") or "",
        "cnae": data.get("cnae_fiscal_descricao") or "",
        "cnae_codigo": data.get("cnae_fiscal") or "",
        "situacao": data.get("descricao_situacao_cadastral") or "",
        "email": data.get("email") or "",
        "telefone_empresa": data.get("ddd_telefone_1") or "",
        # Campos extras p/ o export enriquecido (padrão da planilha modelo)
        "natureza_juridica": data.get("natureza_juridica") or "",
        "matriz_filial": data.get("matriz_filial") or "",
        "data_abertura": data.get("data_inicio_atividade") or "",
        "bairro": data.get("bairro") or "",
        "logradouro": data.get("logradouro") or "",
        "numero": data.get("numero") or "",
        "complemento": data.get("complemento") or "",
        "cep": data.get("cep") or "",
        "telefone_empresa_2": data.get("ddd_telefone_2") or "",
        "simples": data.get("opcao_simples") or "",
        "mei": data.get("opcao_mei") or "",
        "qtd_socios": len(qsa_all),
    }

    def _tel_payload(tels):
        return [{"raw": t.get("digits") or _fmt_phone_digits(t),
                 "display": t.get("telefone") or "", "categoria": t.get("categoria"),
                 "whatsapp": t.get("whatsapp")} for t in tels]

    socios = [s for s in (data.get("qsa") or []) if isinstance(s, dict)]
    # Preferir SÓCIO-ADMINISTRADOR como contato principal (Contato 1). A qualificação
    # societária (QSA) traz "Administrador"/"Sócio-Administrador"/"Diretor" — ordena
    # esses primeiro; mantém a ordem original como desempate.
    def _rank_socio(s):
        q = (s.get("qualificacao_socio") or s.get("qual") or "").lower()
        if "administrador" in q:
            return 0
        if "diretor" in q or "presidente" in q:
            return 1
        if "sócio" in q or "socio" in q:
            return 2
        return 3
    socios = sorted(socios, key=_rank_socio)
    if socios_modo == "admin":
        socios = [s for s in socios if _rank_socio(s) <= 1] or socios[:1]
    if max_socios and max_socios > 0:
        socios = socios[:max_socios]
    # Telefones de todos os socios em paralelo (era 1 a 1 => lento).
    modelo_nome = _resolve_modelo(modelo_id)
    tels_por_socio = await asyncio.gather(*[
        _contato_for_cpf(s.get("cpf_completo") or "", modo_tel, max_tel, fonte_tel,
                         modelo_id=modelo_id, modelo_nome=modelo_nome, cnpj=cnpj) for s in socios
    ])
    contatos = []
    for socio, (tels, emails) in zip(socios, tels_por_socio):
        cpf = socio.get("cpf_completo") or ""
        contatos.append({
            "tipo": "socio",
            "nome": socio.get("nome_socio") or socio.get("nome") or "",
            "cargo": socio.get("qualificacao_socio") or socio.get("qual") or "",
            "cpf": cpf,
            "cpf_status": socio.get("cpf_status") or ("resolved" if cpf else "not_found"),
            "telefones": _tel_payload(tels),
            # Vieram na MESMA consulta do telefone. Estavam sendo descartados.
            "emails": emails,
        })

    # Por que veio 0 decisor? Sem isto a tela mostra "Decisores 0" e a usuária
    # não sabe se falhou, se não foi pedido ou se a base não tem ninguém —
    # micro empresa quase nunca tem decisor na Assertiva (quem decide é o sócio).
    info_dec = {"pedido": bool(decisores), "fonte": decisores_fonte,
                "disponiveis": 0, "escolhidos": 0, "motivo": "", "mensagem": "",
                "pular": False, "usou_fallback": False}

    if decisores and decisores_fonte == "assertiva" and not assertiva.enabled():
        info_dec["motivo"] = "sem_credencial"
        info_dec["mensagem"] = "Assertiva não configurada."

    if decisores and decisores_fonte == "assertiva" and assertiva.enabled():
        try:
            r_dec = await assertiva.possiveis_decisores(brasilapi.only_digits(cnpj))
            if r_dec.get("status") != "ok":
                info_dec["motivo"] = r_dec.get("status") or "erro"
                info_dec["mensagem"] = str(r_dec.get("message") or "")[:160]
            brutos = ((r_dec.get("data") or {}).get("resposta") or {}).get("possiveisDecisores") or []
            todos_dec = decisor_lib.da_assertiva(brutos)
            info_dec["disponiveis"] = len(todos_dec)

            # "Pular empresas sem decisor na base": a empresa sai da lista
            # inteira, sócios inclusive. Devolve cedo pra nem gastar telefone.
            if pular_sem_decisor and not todos_dec:
                info_dec["pular"] = True
                info_dec["motivo"] = info_dec["motivo"] or "not_found"
                return {"status": "ok", "empresa": empresa, "contatos": [],
                        "decisores_info": info_dec}

            escolhidos = _filtra_decisores(todos_dec, decisores_cargos, max_decisores)

            # Modo estrito: só quem tem o cargo pedido. Nada de fallback, nada
            # de sócio, e empresa sem ninguém no cargo sai da lista.
            if apenas_cargo:
                info_dec["apenas_cargo"] = True
                if not escolhidos:
                    info_dec["pular"] = True
                    info_dec["motivo"] = "sem_o_cargo"
                    return {"status": "ok", "empresa": empresa, "contatos": [],
                            "decisores_info": info_dec}
                contatos = []          # descarta os sócios já montados

            # Filtro de cargo não casou com ninguém, mas a base TEM gente:
            # traz os de maior hierarquia em vez de devolver a empresa vazia.
            if not apenas_cargo and not escolhidos and todos_dec and fallback_hierarquia > 0:
                escolhidos = _filtra_decisores(todos_dec, "", fallback_hierarquia)
                info_dec["usou_fallback"] = bool(escolhidos)
            # CPFs que já entraram como sócio não viram contato duplicado.
            ja_tem = {c.get("cpf") for c in contatos if c.get("cpf")}
            escolhidos = [p for p in escolhidos if p.get("cpf") and p["cpf"] not in ja_tem]
            tels_dec = await asyncio.gather(*[
                _contato_for_cpf(p["cpf"], modo_tel, max_tel, fonte_tel,
                                modelo_id=modelo_id, modelo_nome=modelo_nome, cnpj=cnpj)
                for p in escolhidos
            ])
            for p, (tels, emails) in zip(escolhidos, tels_dec):
                contatos.append({
                    "tipo": "decisor",
                    "nome": p.get("nome") or "",
                    "cargo": p.get("cargo") or "",
                    "nivel": p.get("nivel") or 0,
                    "area": p.get("area") or "",
                    "fonte_cargo": "Assertiva",
                    "cpf": p["cpf"],
                    "cpf_status": "resolved",
                    "telefones": _tel_payload(tels),
                    "emails": emails,
                })
            info_dec["escolhidos"] = len(escolhidos)
            if not info_dec["motivo"]:
                if info_dec["usou_fallback"]:
                    info_dec["motivo"] = "fallback"
                elif info_dec["disponiveis"] and not escolhidos:
                    # A Assertiva tinha gente, mas o filtro de cargo cortou tudo.
                    info_dec["motivo"] = "filtrado"
                else:
                    info_dec["motivo"] = "ok"
        except Exception as exc:
            info_dec["motivo"] = "erro"
            info_dec["mensagem"] = str(exc)[:160]

    elif decisores and decisores_fonte == "linkedin" and _cpf_ready():
        try:
            emp_res = await linkedin_scraper.scrape_employees(
                brasilapi.only_digits(cnpj), empresa["nome_fantasia"] or empresa["razao_social"],
                empresa["razao_social"],
            )
            for emp in (emp_res.get("employees") or [])[:10]:
                nome = emp.get("name", "")
                cpf = ""
                try:
                    cands = cpf_lookup.by_name(nome, limit=50)
                    if len(cands) == 1:
                        cpf = cands[0]["cpf"]
                except Exception:
                    pass
                tels = await _phones_for_cpf(cpf, modo_tel, max_tel, fonte_tel,
                                             modelo_id=modelo_id, modelo_nome=modelo_nome,
                                             cnpj=cnpj) if cpf else []
                contatos.append({
                    "tipo": "decisor",
                    "nome": nome,
                    "cargo": emp.get("title") or "",
                    "cpf": cpf,
                    "cpf_status": "resolved" if cpf else "ambiguous",
                    "telefones": [{"raw": t.get("digits") or _fmt_phone_digits(t),
                                   "display": t.get("telefone") or "", "categoria": t.get("categoria"),
                                   "whatsapp": t.get("whatsapp")} for t in tels],
                })
        except Exception:
            pass

    if so_com_telefone:
        com_tel = [c for c in contatos if (c.get("telefones") or [])]
        if not com_tel:
            # Empresa inteira sai. `contatos: []` com o motivo explicito, para
            # a tela distinguir "nao achamos ninguem" de "achamos e nenhum
            # tinha telefone" -- sao problemas diferentes e levam a acoes
            # diferentes (mudar o filtro de cargo x mudar a fonte de telefone).
            return {"status": "ok", "empresa": empresa, "contatos": [],
                    "decisores_info": info_dec, "pulada": True,
                    "motivo_pulo": ("%d pessoa(s) identificada(s), nenhuma com "
                                    "telefone" % len(contatos)) if contatos
                                   else "nenhuma pessoa identificada"}
        contatos = com_tel

    return {"status": "ok", "empresa": empresa, "contatos": contatos,
            "decisores_info": info_dec, "pulada": False}


# Colunas de EMPRESA no export enriquecido (padrão da planilha modelo Datastone).
# (chave_no_payload | rótulo). Campos que ainda não temos dataset ficam em branco.
_EXP_EMPRESA_COLS = [
    ("cnpj", "CNPJ"),
    ("razao_social", "Razao Social"),
    ("nome_fantasia", "Nome Fantasia"),
    ("site", "Site (provavel)"),
    ("segmento", "Segmento"),
    ("setor_icp", "Setor ICP"),
    ("cnae_codigo", "CNAE Codigo"),
    ("cnae", "CNAE Descricao"),
    ("porte", "Porte"),
    ("funcionarios", "Funcionarios"),
    ("faturamento", "Faturamento"),
    ("matriz_filial", "Matriz/Filial"),
    ("natureza_juridica", "Natureza Juridica"),
    ("situacao", "Situacao Cadastral"),
    ("simples", "Simples Nacional"),
    ("data_abertura", "Data Abertura"),
    ("capital_social", "Capital Social"),
    ("uf", "UF"),
    ("municipio", "Municipio"),
    ("bairro", "Bairro"),
    ("logradouro", "Logradouro"),
    ("numero", "Numero"),
    ("cep", "CEP"),
    ("tel_empresa_1", "Tel Empresa 1"),
    ("tel_empresa_2", "Tel Empresa 2"),
    ("tel_empresa_3", "Tel Empresa 3"),
    ("email_empresa_1", "Email Empresa 1"),
    ("email_empresa_2", "Email Empresa 2"),
    ("email_empresa_3", "Email Empresa 3"),
    ("qtd_socios", "Qtd Socios"),
    ("qtd_membros", "Qtd Membros"),
    ("regional", "Regional"),
]

# Sufixos de cada bloco de contato (padrão "Contato N ...").
_EXP_CONTATO_FIELDS = [
    ("nome", "Nome"),
    ("cargo", "Cargo"),
    ("cpf", "CPF"),
    ("celular1", "Celular 1"),
    ("celular2", "Celular 2"),
    ("fixo", "Fixo"),
    ("whatsapp", "WhatsApp"),
    ("email1", "Email 1"),
    ("email2", "Email 2"),
]


def _split_contato(c: dict) -> dict:
    """Quebra um contato (com lista de telefones) nos campos do modelo:
    Celular 1/2, Fixo, WhatsApp, e-mails."""
    celulares, fixo, whats = [], "", False
    for t in (c.get("telefones") or []):
        disp = t.get("display") or t.get("raw") or ""
        cat = t.get("categoria") or ""
        if t.get("whatsapp"):
            whats = True
        if cat == "fixo":
            if not fixo:
                fixo = disp
        else:  # celular / celular_antigo
            celulares.append(disp)
    emails = c.get("emails") or []
    return {
        "nome": c.get("nome") or "",
        "cargo": c.get("cargo") or "",
        "cpf": c.get("cpf") or "",
        "celular1": celulares[0] if celulares else "",
        "celular2": celulares[1] if len(celulares) > 1 else "",
        "fixo": fixo,
        "whatsapp": "SIM" if whats else "",
        "email1": emails[0] if emails else "",
        "email2": emails[1] if len(emails) > 1 else "",
    }


def _site_from_email(email: str) -> str:
    email = (email or "").strip()
    if "@" in email:
        dom = email.split("@")[-1].strip().lower()
        generic = {"gmail.com", "hotmail.com", "outlook.com", "yahoo.com",
                   "yahoo.com.br", "uol.com.br", "bol.com.br", "terra.com.br",
                   "live.com", "icloud.com"}
        if dom and dom not in generic:
            return dom
    return ""


@app.post("/api/export/xlsx")
async def export_xlsx(payload: dict = Body(default={})):
    """Gera a planilha XLSX enriquecida (padrão Datastone), 1 linha por empresa.

    Body: {empresas: [{empresa:{...}, contatos:[{nome,cargo,cpf,telefones:[...],emails:[]}]}]}
    Compat: se vier {rows:[...]} (formato antigo por telefone), exporta assim mesmo.
    AutoFilter fica ligado em todas as colunas → dá pra adicionar mais filtros no Excel.
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill, Alignment
    from openpyxl.utils import get_column_letter

    empresas = payload.get("empresas")
    header_font = Font(bold=True, color="FFFFFF")
    header_fill = PatternFill("solid", fgColor="FF6A00")  # laranja do modelo
    header_align = Alignment(horizontal="center", vertical="center", wrap_text=True)

    wb = Workbook()
    ws = wb.active
    ws.title = "Prospeccao"

    if empresas is not None:
        # layout: 'empresa' = 1 CNPJ por linha (blocos Contato 1..N lado a lado);
        #         'contato' = 1 contato por linha (empresa repetida a cada contato).
        layout = (payload.get("layout") or "empresa").strip().lower()

        def _emp_vals(emp: dict) -> list:
            vals = []
            for key, _ in _EXP_EMPRESA_COLS:
                if key == "site":
                    vals.append(_site_from_email(emp.get("email") or emp.get("email_empresa_1") or ""))
                elif key == "tel_empresa_1":
                    vals.append(emp.get("telefone_empresa") or "")
                elif key == "tel_empresa_2":
                    vals.append(emp.get("telefone_empresa_2") or "")
                elif key == "email_empresa_1":
                    vals.append(emp.get("email") or "")
                elif key == "simples":
                    v = emp.get("simples") or ""
                    vals.append("SIM" if str(v).upper() in ("S", "SIM", "1") else ("NAO" if v else ""))
                else:
                    vals.append(emp.get(key, ""))
            return vals

        norm = []
        max_contatos = 4  # como no modelo
        for item in empresas:
            emp = item.get("empresa") or {}
            contatos = [_split_contato(c) for c in (item.get("contatos") or [])]
            max_contatos = max(max_contatos, len(contatos))
            norm.append((emp, contatos))

        r_idx = 2
        if layout == "contato":
            # Cabeçalho: colunas de empresa + UM bloco de contato (sem prefixo "Contato N").
            headers = [lbl for _, lbl in _EXP_EMPRESA_COLS] + \
                      [f"Contato {lbl}" for _, lbl in _EXP_CONTATO_FIELDS]
            for emp, contatos in norm:
                base = _emp_vals(emp)
                # Empresa sem contato ainda gera 1 linha (só dados da empresa).
                for c in (contatos or [None]):
                    vals = list(base)
                    for fkey, _ in _EXP_CONTATO_FIELDS:
                        vals.append((c or {}).get(fkey, ""))
                    for col_idx, v in enumerate(vals, start=1):
                        ws.cell(row=r_idx, column=col_idx, value=v)
                    r_idx += 1
        else:
            # layout 'empresa': blocos Contato 1..N lado a lado.
            headers = [lbl for _, lbl in _EXP_EMPRESA_COLS]
            for n in range(1, max_contatos + 1):
                headers += [f"Contato {n} {lbl}" for _, lbl in _EXP_CONTATO_FIELDS]
            for emp, contatos in norm:
                vals = _emp_vals(emp)
                for c in contatos:
                    for fkey, _ in _EXP_CONTATO_FIELDS:
                        vals.append(c.get(fkey, ""))
                for col_idx, v in enumerate(vals, start=1):
                    ws.cell(row=r_idx, column=col_idx, value=v)
                r_idx += 1

        for col_idx, label in enumerate(headers, start=1):
            c = ws.cell(row=1, column=col_idx, value=label)
            c.font = header_font
            c.fill = header_fill
            c.alignment = header_align
        for i in range(1, len(headers) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 20
        ws.freeze_panes = "C2"  # trava cabeçalho + CNPJ/Razão (como no modelo)
        last_col = get_column_letter(len(headers))
        ws.auto_filter.ref = f"A1:{last_col}{max(r_idx - 1, 1)}"
    else:
        # Fallback: formato antigo (uma linha por telefone).
        rows = payload.get("rows") or []
        legacy = [
            ("razao_social", "Razao Social"), ("nome_fantasia", "Nome Fantasia"),
            ("cnpj", "CNPJ"), ("municipio", "Municipio"), ("uf", "UF"),
            ("porte", "Porte"), ("cnae", "Atividade (CNAE)"), ("situacao", "Situacao"),
            ("contato_tipo", "Tipo Contato"), ("contato_nome", "Nome Contato"),
            ("contato_cargo", "Cargo"), ("contato_cpf", "CPF"), ("telefone", "Telefone"),
            ("tel_categoria", "Tipo Telefone"), ("validado", "Validado (telefone reverso)"),
            ("nome_donodozap", "Nome / Vinculo"),
        ]
        for col_idx, (_key, label) in enumerate(legacy, start=1):
            c = ws.cell(row=1, column=col_idx, value=label)
            c.font = header_font
            c.fill = header_fill
        for r_idx, row in enumerate(rows, start=2):
            for col_idx, (key, _label) in enumerate(legacy, start=1):
                ws.cell(row=r_idx, column=col_idx, value=row.get(key, ""))
        for i in range(1, len(legacy) + 1):
            ws.column_dimensions[get_column_letter(i)].width = 20
        ws.freeze_panes = "A2"
        ws.auto_filter.ref = f"A1:{get_column_letter(len(legacy))}{max(len(rows) + 1, 1)}"

    # Aba "Fontes": de onde saem os dados (nome da API/base) — transparência.
    fonte_tel = (payload.get("fonte_tel") or "assertiva").lower()
    tel_fonte = "Assertiva Localize (API)" if fonte_tel == "assertiva" else "Mk Buscas / WorkAPI (API)"
    fontes = [
        ("Dados da empresa (razão, fantasia, CNAE, porte, situação, capital, endereço, matriz/filial, Simples/MEI)",
         "Receita Federal — Cadastro Nacional de CNPJ (base local RFB dos Dados Abertos)"),
        ("Telefone e e-mail da empresa", "Receita Federal (RFB) — quando disponível no cadastro"),
        ("Nome e cargo do contato/sócio", "Receita Federal — Quadro de Sócios (QSA)"),
        ("CPF do contato", "Base JBR (resolução nome + máscara do CPF)"),
        ("Telefones do contato (Celular/Fixo/WhatsApp)", tel_fonte),
        ("E-mail do contato", "Assertiva Localize (API)"),
        ("Verificação de telefone (pertence ao CPF)", "integralX / intelgrax-tel (WorkAPI) — telefone reverso"),
    ]
    wf = wb.create_sheet("Fontes")
    wf.cell(row=1, column=1, value="Campo").font = header_font
    wf.cell(row=1, column=2, value="Origem dos dados").font = header_font
    wf.cell(row=1, column=1).fill = header_fill
    wf.cell(row=1, column=2).fill = header_fill
    for i, (campo, origem) in enumerate(fontes, start=2):
        wf.cell(row=i, column=1, value=campo)
        wf.cell(row=i, column=2, value=origem)
    wf.column_dimensions["A"].width = 62
    wf.column_dimensions["B"].width = 66

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf,
        media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="capiblu-prospeccao.xlsx"'},
    )


# ============================================================
#  PROSPECÇÃO B2B — "UPLOAD MODELO"
#  Sobe uma planilha-modelo → detecta cabeçalhos e qual fonte/API preenche cada um
#  → gera a lista seguindo EXATAMENTE os cabeçalhos do modelo.
# ============================================================
import unicodedata as _ud


def _norm_hdr(h) -> str:
    s = _ud.normalize("NFKD", str(h or "")).encode("ascii", "ignore").decode("ascii").lower()
    s = re.sub(r"[^a-z0-9 ]", " ", s)
    return re.sub(r"\s+", " ", s).strip()


# campo | label | fonte | aliases (normalizados). Ordem importa p/ desempate.
_MODELO_CAMPOS = [
    ("cnpj", "CNPJ", "Receita Federal", ["cnpj"]),
    ("razao_social", "Razão Social", "Receita Federal",
     ["razao social", "razao", "empresa", "nome empresa", "razaosocial", "company", "nome"]),
    ("nome_fantasia", "Nome Fantasia", "Receita Federal", ["nome fantasia", "fantasia"]),
    ("cnae", "CNAE (descrição)", "Receita Federal",
     ["cnae", "atividade", "ramo", "segmento", "industria", "descricao cnae"]),
    ("cnae_codigo", "CNAE (código)", "Receita Federal", ["cnae codigo", "codigo cnae"]),
    ("porte", "Porte", "Receita Federal", ["porte", "tamanho", "funcionarios", "qtd funcionarios"]),
    ("situacao", "Situação Cadastral", "Receita Federal", ["situacao", "situacao cadastral", "status"]),
    ("natureza_juridica", "Natureza Jurídica", "Receita Federal",
     ["natureza", "natureza juridica", "tipo empresa"]),
    ("capital_social", "Capital Social", "Receita Federal", ["capital", "capital social", "faturamento"]),
    ("data_abertura", "Data de Abertura", "Receita Federal",
     ["data abertura", "abertura", "fundacao", "fundada", "data fundacao", "dt abertura", "dt inclusao"]),
    ("matriz_filial", "Matriz/Filial", "Receita Federal", ["matriz", "filial", "matriz filial"]),
    ("uf", "UF", "Receita Federal", ["uf", "estado"]),
    ("municipio", "Município", "Receita Federal", ["municipio", "cidade", "municipio2"]),
    ("bairro", "Bairro", "Receita Federal", ["bairro"]),
    ("logradouro", "Logradouro", "Receita Federal", ["logradouro", "rua", "endereco"]),
    ("numero", "Número", "Receita Federal", ["numero"]),
    ("cep", "CEP", "Receita Federal", ["cep"]),
    ("tel_empresa", "Telefone da Empresa", "Receita/Assertiva",
     ["telefone empresa", "tel empresa", "telefone da empresa", "fone empresa"]),
    ("email_empresa", "E-mail da Empresa", "Receita/Assertiva",
     ["email empresa", "e mail empresa", "email da empresa"]),
    ("qtd_socios", "Qtd Sócios", "Receita Federal", ["qtd socios", "numero de socios", "socios"]),
    ("contato_nome", "Nome do Contato", "Receita (QSA)",
     ["contato", "nome contato", "socio", "decisor", "responsavel", "representante", "nome socio"]),
    ("contato_cargo", "Cargo do Contato", "Receita (QSA)", ["cargo", "funcao", "qualificacao"]),
    ("contato_cpf", "CPF do Contato", "Base JBR", ["cpf", "cpf contato", "cpf socio"]),
    ("contato_celular2", "Celular 2 do Contato", "Assertiva/Mk",
     ["celular 2", "telefone 2", "celular2", "tel 2", "segundo telefone"]),
    ("contato_celular", "Celular do Contato", "Assertiva/Mk",
     ["celular", "celular 1", "telefone", "telefone 1", "movel", "tel", "fone", "telefone celular", "whatsapp"]),
    ("contato_fixo", "Fixo do Contato", "Assertiva/Mk", ["fixo", "telefone fixo"]),
    ("contato_whatsapp", "Tem WhatsApp?", "Assertiva/Mk",
     ["whatsapp", "possui whatsapp", "tem whatsapp", "zap", "wpp"]),
    ("contato_email", "E-mail do Contato", "Assertiva",
     ["email", "e mail", "email 1", "email contato", "e-mail"]),
]
_MODELO_LABEL = {k: lbl for k, lbl, _, _ in _MODELO_CAMPOS}
_MODELO_FONTE = {k: f for k, _, f, _ in _MODELO_CAMPOS}


def _match_header(header: str) -> Optional[str]:
    """Mapeia um cabeçalho do modelo para um campo conhecido (melhor correspondência)."""
    h = _norm_hdr(header)
    if not h:
        return None
    words = set(h.split())
    best, best_score = None, 0
    for campo, _lbl, _f, aliases in _MODELO_CAMPOS:
        for a in aliases:
            aw = a.split()
            score = 0
            if h == a:
                score = 100 + len(a)                      # match exato — melhor
            elif h.startswith(a + " "):
                score = 75 + len(a)                       # começa com o alias (palavra)
            elif all(w in words for w in aw):
                score = 55 + len(a)                       # todas as palavras do alias presentes
            elif h.endswith(" " + a):
                score = 40 + len(a)                       # termina com o alias
            elif a in h or h in a:
                score = 20 + len(a)                       # substring solta (fraco)
            if score > best_score:
                best, best_score = campo, score
    return best


def _extrai_modelo(lead: dict, campo: str, idx: int = 1):
    """Extrai o valor de um campo a partir de um lead {empresa, contatos}."""
    emp = lead.get("empresa") or {}
    emp_map = {
        "cnpj": emp.get("cnpj"), "razao_social": emp.get("razao_social"),
        "nome_fantasia": emp.get("nome_fantasia"), "cnae": emp.get("cnae"),
        "cnae_codigo": emp.get("cnae_codigo"), "porte": emp.get("porte"),
        "situacao": emp.get("situacao"), "natureza_juridica": emp.get("natureza_juridica"),
        "capital_social": emp.get("capital_social"), "data_abertura": emp.get("data_abertura"),
        "matriz_filial": emp.get("matriz_filial"), "uf": emp.get("uf"),
        "municipio": emp.get("municipio"), "bairro": emp.get("bairro"),
        "logradouro": emp.get("logradouro"), "numero": emp.get("numero"),
        "cep": emp.get("cep"), "tel_empresa": emp.get("telefone_empresa"),
        "email_empresa": emp.get("email"), "qtd_socios": emp.get("qtd_socios"),
    }
    if campo in emp_map:
        return emp_map[campo] if emp_map[campo] is not None else ""
    contatos = lead.get("contatos") or []
    if not contatos:
        return ""
    c = contatos[min(idx, len(contatos)) - 1] if idx >= 1 else contatos[0]
    split = _split_contato(c)
    cmap = {
        "contato_nome": split["nome"], "contato_cargo": split["cargo"],
        "contato_cpf": split["cpf"], "contato_celular": split["celular1"],
        "contato_celular2": split["celular2"], "contato_fixo": split["fixo"],
        "contato_whatsapp": split["whatsapp"], "contato_email": split["email1"],
    }
    return cmap.get(campo, "")


@app.post("/api/prospeccao/modelo/analisar")
async def modelo_analisar(file: UploadFile = File(...)):
    """Lê os cabeçalhos da planilha-modelo e diz qual campo/fonte preenche cada um."""
    try:
        content = await file.read()
        parsed, _aviso = sheet_reader.read_table(file.filename or "", content)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Falha ao ler modelo: {str(exc)[:150]}"}
    cols = parsed[0]["columns"] if parsed else []
    colunas = []
    for h in cols:
        # detecta índice de contato no cabeçalho (ex.: "Contato 2 Celular")
        m = re.search(r"contato\s*(\d+)", _norm_hdr(h))
        idx = int(m.group(1)) if m else 1
        campo = _match_header(h)
        colunas.append({
            "header": h, "campo": campo, "idx": idx,
            "campo_label": _MODELO_LABEL.get(campo) if campo else None,
            "fonte": _MODELO_FONTE.get(campo) if campo else None,
            "fillable": bool(campo),
        })
    campos_disp = [{"campo": k, "label": lbl, "fonte": f} for k, lbl, f, _ in _MODELO_CAMPOS]
    return {"status": "ok", "aba": parsed[0]["title"] if parsed else "",
            "colunas": colunas, "campos_disponiveis": campos_disp}


@app.post("/api/prospeccao/modelo/exportar")
async def modelo_exportar(payload: dict = Body(default={})):
    """Gera o XLSX seguindo os cabeçalhos do modelo.

    Body: {colunas:[{header, campo, idx}], empresas:[{empresa, contatos}]}
    """
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    colunas = payload.get("colunas") or []
    empresas = payload.get("empresas") or []
    wb = Workbook()
    ws = wb.active
    ws.title = "Modelo preenchido"
    hf = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1D4ED8")
    for i, col in enumerate(colunas, start=1):
        c = ws.cell(row=1, column=i, value=col.get("header"))
        c.font = hf
        c.fill = fill
    for r_idx, lead in enumerate(empresas, start=2):
        for i, col in enumerate(colunas, start=1):
            campo = col.get("campo")
            val = _extrai_modelo(lead, campo, int(col.get("idx") or 1)) if campo else ""
            if hasattr(val, "isoformat"):
                val = val.isoformat(sep=" ")[:19]
            ws.cell(row=r_idx, column=i, value=val)
    for i in range(1, len(colunas) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 20
    ws.freeze_panes = "A2"
    if colunas:
        ws.auto_filter.ref = f"A1:{get_column_letter(len(colunas))}{max(len(empresas) + 1, 1)}"
    # aba Fontes (só das colunas mapeadas)
    wf = wb.create_sheet("Fontes")
    wf.cell(row=1, column=1, value="Coluna do modelo").font = hf
    wf.cell(row=1, column=2, value="Campo").font = hf
    wf.cell(row=1, column=3, value="Origem").font = hf
    for j in (1, 2, 3):
        wf.cell(row=1, column=j).fill = fill
    for i, col in enumerate(colunas, start=2):
        campo = col.get("campo")
        wf.cell(row=i, column=1, value=col.get("header"))
        wf.cell(row=i, column=2, value=_MODELO_LABEL.get(campo, "— não preenchido") if campo else "— não preenchido")
        wf.cell(row=i, column=3, value=_MODELO_FONTE.get(campo, "") if campo else "")
    for col, w in (("A", 34), ("B", 26), ("C", 24)):
        wf.column_dimensions[col].width = w

    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="capiblu-modelo.xlsx"'})


# ---- Modelos SALVOS (persistidos em JSON no diretório de dados) ----
def _modelos_path() -> str:
    base = r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "capiblu_modelos.json")


def _modelos_load() -> list:
    import json as _json
    try:
        with open(_modelos_path(), encoding="utf-8") as fh:
            return _json.load(fh)
    except Exception:
        return []


@app.get("/api/custos/assertiva")
async def custos_assertiva(desde: str = "", ate: str = ""):
    """Resumo de custo Assertiva por modelo, no intervalo [desde, ate] (YYYY-MM-DD).

    Sem desde/ate: sem filtro de início/fim (mas o frontend manda os últimos 7 dias
    por padrão). 'ate' é inclusivo até o fim daquele dia.
    """
    import datetime as _dt
    desde_ts = None
    ate_ts = None
    try:
        if desde:
            desde_ts = _dt.datetime.strptime(desde, "%Y-%m-%d").timestamp()
        if ate:
            ate_ts = _dt.datetime.strptime(ate, "%Y-%m-%d").timestamp() + 86400 - 1
    except ValueError:
        return {"status": "error", "message": "Datas inválidas (use YYYY-MM-DD)."}
    res = custos.resumo(desde_ts, ate_ts)
    res["status"] = "ok"
    res["cliente_id"] = custos.CLIENTE_ID
    res["cliente_nome"] = custos.CLIENTE_NOME
    return res


@app.get("/api/custos/usuario")
async def custos_por_usuario(request: Request, desde: str = "", ate: str = "", user: str = ""):
    """Custo de chamadas Assertiva por usuário, no intervalo [desde, ate] — só admin.

    Um admin não vê o custo de outro admin (mesma regra do /api/navlog).
    """
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    import datetime as _dt
    desde_ts = None
    ate_ts = None
    try:
        if desde:
            desde_ts = _dt.datetime.strptime(desde, "%Y-%m-%d").timestamp()
        if ate:
            ate_ts = _dt.datetime.strptime(ate, "%Y-%m-%d").timestamp() + 86400 - 1
    except ValueError:
        return {"status": "error", "message": "Datas inválidas (use YYYY-MM-DD)."}
    try:
        emails_admin = {u["email"] for u in auth.list_users() if u.get("role") == "admin"}
    except Exception:
        emails_admin = set()
    res = custos.resumo_por_usuario(desde_ts, ate_ts, excluir_emails=emails_admin)
    if user:
        alvo = user.strip().lower()
        res["usuarios"] = [u for u in res["usuarios"] if u["user"] == alvo]
    res["status"] = "ok"
    return res


@app.get("/api/custos/total")
async def custos_total(request: Request, desde: str = "", ate: str = "", dias: int = 30):
    """Relatório de uso TOTAL — só admin.

    Confronta duas contagens que nunca batem por bons motivos:

    1. O RELATÓRIO DA ASSERTIVA (/localize/v3/report/usage) — é o que ela
       registra pra faturar. Reconsulta do mesmo documento não conta de novo, e
       complementos (possíveis decisores, mais telefones) vêm como `subItems`
       da consulta que os originou.
    2. O NOSSO LOG interno — conta cada chamada HTTP que sai daqui, incluindo
       reconsulta e rotas que não faturam (o próprio relatório, por exemplo).

    O nosso número quase sempre vem MAIOR. O da Assertiva é o que chega na fatura.
    """
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)

    import datetime as _dt
    hoje = _dt.date.today()
    if not ate:
        ate = hoje.isoformat()
    if not desde:
        desde = (hoje - _dt.timedelta(days=max(1, dias) - 1)).isoformat()
    try:
        desde_ts = _dt.datetime.strptime(desde, "%Y-%m-%d").timestamp()
        ate_ts = _dt.datetime.strptime(ate, "%Y-%m-%d").timestamp() + 86400 - 1
    except ValueError:
        return {"status": "error", "message": "Datas inválidas (use YYYY-MM-DD)."}

    tabela = custos.precos()

    # ── 1. contagem oficial da Assertiva ──
    oficial = {"disponivel": False, "consultas": 0, "subitens": 0,
               "por_funcionalidade": {}, "por_usuario": {}, "truncado": False}
    if assertiva.enabled():
        rel = await assertiva.relatorio_uso(desde=desde, ate=ate)
        if rel.get("status") == "ok":
            oficial["disponivel"] = True
            oficial["truncado"] = bool(rel.get("truncado"))
            for it in rel.get("itens") or []:
                func = (it.get("functionality") or "—").strip()
                oficial["consultas"] += 1
                oficial["por_funcionalidade"][func] = oficial["por_funcionalidade"].get(func, 0) + 1
                quem = (it.get("userName") or "—").strip()
                oficial["por_usuario"][quem] = oficial["por_usuario"].get(quem, 0) + 1
                for sub in it.get("subItems") or []:
                    if not isinstance(sub, dict):
                        continue
                    sf = (sub.get("functionality") or "—").strip()
                    oficial["subitens"] += 1
                    oficial["por_funcionalidade"][sf] = oficial["por_funcionalidade"].get(sf, 0) + 1
        else:
            oficial["mensagem"] = rel.get("message", "")

    # ── 2. nosso log interno ──
    try:
        emails_admin = {u["email"] for u in auth.list_users() if u.get("role") == "admin"}
    except Exception:
        emails_admin = set()
    interno_user = custos.resumo_por_usuario(desde_ts, ate_ts, excluir_emails=set())
    interno_modelo = custos.resumo(desde_ts, ate_ts)

    custo_unit = custos.CUSTO_POR_CONSULTA
    total_oficial = oficial["consultas"] + oficial["subitens"]

    # Custo por funcionalidade, cada uma com o seu preço da tabela.
    custo_por_func = {f: round(n * custos.preco_de(f, tabela), 2)
                      for f, n in oficial["por_funcionalidade"].items()}
    custo_oficial = round(sum(custo_por_func.values()), 2)
    # Preço médio efetivo — só pra explicar o total, não é preço de tabela.
    medio = round(custo_oficial / total_oficial, 4) if total_oficial else custo_unit

    return {
        "status": "ok",
        "periodo": {"desde": desde, "ate": ate, "dias": (
            _dt.date.fromisoformat(ate) - _dt.date.fromisoformat(desde)).days + 1},
        "custo_por_consulta": custo_unit,
        "precos": tabela,
        "preco_medio": medio,
        "assertiva": {
            **oficial,
            "total_registros": total_oficial,
            "custo_por_funcionalidade": custo_por_func,
            "custo_estimado": custo_oficial,
        },
        "interno": {
            "chamadas": interno_user["total_consultas"],
            "custo_estimado": interno_user["total_geral"],
            "por_usuario": interno_user["usuarios"],
            "admins": sorted(emails_admin),
        },
        "modelos": interno_modelo,
        "diferenca": {
            "chamadas": interno_user["total_consultas"] - total_oficial,
            "custo": round(interno_user["total_geral"] - custo_oficial, 2),
        },
    }


@app.get("/api/custos/precos")
async def custos_precos_ler(request: Request):
    """Tabela de preço por tipo de consulta — só admin."""
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    import config_store
    salvos = config_store.get("assertiva_precos") or {}
    return {"status": "ok", "precos": custos.precos(),
            "padrao": custos.CUSTO_POR_CONSULTA,
            "definidos": sorted(salvos.keys()),
            "funcionalidades": custos.FUNCIONALIDADES}


@app.post("/api/custos/precos")
async def custos_precos_salvar(request: Request, payload: dict = Body(default={})):
    """Salva a tabela de preço. Body: {precos: {"CPF": 0.119, "CNPJ": 0.30, ...}}.

    Campo vazio volta ao padrão. Os nomes são os do relatório da Assertiva.
    """
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    tabela = custos.salvar_precos(payload.get("precos") or {})
    return {"status": "ok", "precos": tabela}


def _modelos_save(lst: list) -> None:
    import json as _json
    with open(_modelos_path(), "w", encoding="utf-8") as fh:
        _json.dump(lst, fh, ensure_ascii=False, indent=1)


@app.get("/api/prospeccao/modelo/campos")
async def modelo_campos():
    """Catálogo de campos disponíveis (para o construtor de modelos)."""
    return {"campos": [{"campo": k, "label": lbl, "fonte": f} for k, lbl, f, _ in _MODELO_CAMPOS]}


@app.get("/api/prospeccao/modelos")
async def modelos_listar():
    return {"modelos": _modelos_load()}


@app.post("/api/prospeccao/modelos")
async def modelos_salvar(payload: dict = Body(default={})):
    """Cria/atualiza um modelo salvo. Body: {id?, nome, colunas:[{header,campo,idx}]}."""
    nome = (payload.get("nome") or "").strip()
    colunas = payload.get("colunas") or []
    if not nome:
        return {"status": "error", "message": "Informe um nome para o modelo."}
    if not colunas:
        return {"status": "error", "message": "O modelo precisa de ao menos uma coluna."}
    lst = _modelos_load()
    mid = payload.get("id")
    if mid:  # atualização
        for m in lst:
            if m.get("id") == mid:
                m["nome"], m["colunas"] = nome, colunas
                _modelos_save(lst)
                return {"status": "ok", "modelo": m}
    novo = {"id": uuid.uuid4().hex[:10], "nome": nome, "colunas": colunas}
    lst.append(novo)
    _modelos_save(lst)
    return {"status": "ok", "modelo": novo}


@app.delete("/api/prospeccao/modelos/{mid}")
async def modelos_excluir(mid: str):
    lst = [m for m in _modelos_load() if m.get("id") != mid]
    _modelos_save(lst)
    return {"status": "ok"}


# ============================================================
#  ENRIQUECER LISTA (upload XLSX -> qualifica + telefone + verifica)
# ============================================================

# Catálogo de campos que o usuário pode optar por adicionar.
# grupo | [(key, rótulo)]. Prefixo da key indica a fonte:
#   rfb_ = Receita local (grátis) · as_ = Assertiva · vf_ = verificação integralX
_ENRICH_CATALOG = [
    {"grupo": "Empresa (Receita Federal)", "fonte": "RFB local (instantâneo)", "campos": [
        ("rfb_razao", "Razão Social (RFB)"), ("rfb_fantasia", "Nome Fantasia"),
        ("rfb_situacao", "Situação Cadastral"), ("rfb_cnae_cod", "CNAE Código"),
        ("rfb_cnae", "CNAE Descrição"), ("rfb_porte", "Porte"),
        ("rfb_capital", "Capital Social"), ("rfb_natureza", "Natureza Jurídica"),
        ("rfb_abertura", "Data Abertura"), ("rfb_matriz", "Matriz/Filial"),
        ("rfb_endereco", "Endereço"), ("rfb_municipio", "Município (RFB)"),
        ("rfb_uf", "UF (RFB)"), ("rfb_cep", "CEP"),
        ("rfb_tel1", "Telefone Empresa 1"), ("rfb_tel2", "Telefone Empresa 2"),
        ("rfb_email", "E-mail Empresa (RFB)"), ("rfb_qtd_socios", "Qtd Sócios"),
        ("rfb_socio1", "Sócio Principal"), ("rfb_simples", "Simples"), ("rfb_mei", "MEI"),
    ]},
    {"grupo": "Empresa – Telefone (Assertiva)", "fonte": "Assertiva Localize (consumo)", "campos": [
        ("as_empresa_tel", "Telefone Empresa (Assertiva)"),
        ("as_empresa_tel2", "Telefone Empresa 2 (Assertiva)"),
        ("as_empresa_email", "E-mail Empresa (Assertiva)"),
        ("as_empresa_whatsapp", "WhatsApp Empresa"),
    ]},
    {"grupo": "Sócios – contato pessoal (Assertiva)", "fonte": "JBR (CPF) + Assertiva (consumo)", "campos": [
        ("so_socio1_nome", "Sócio 1 Nome"),
        ("so_socio1_cpf", "Sócio 1 CPF"),
        ("so_socio1_celular", "Sócio 1 Celular"),
        ("so_socio1_whatsapp", "Sócio 1 WhatsApp"),
        ("so_socio1_email", "Sócio 1 E-mail"),
        ("so_socio2_nome", "Sócio 2 Nome"),
        ("so_socio2_cpf", "Sócio 2 CPF"),
        ("so_socio2_celular", "Sócio 2 Celular"),
        ("so_todos_tel", "Todos os sócios (nome — celular)"),
    ]},
    {"grupo": "Verificação de telefone (integralX)", "fonte": "WorkAPI intelgrax-tel (consumo)", "campos": [
        ("vf_telefone", "Telefone Verificado"),
        ("vf_status", "Status Verificação"),
        ("vf_vinculos", "Nº de Vínculos"),
    ]},
]
_ENRICH_KEYS = {k for g in _ENRICH_CATALOG for (k, _) in g["campos"]}

# Store em memória das planilhas enviadas (ferramenta local, 1 usuário).
_UPLOADS: dict[str, dict] = {}


def _guess_cnpj_col(columns: list[str]) -> str:
    for c in columns:
        if "cnpj" in (c or "").strip().lower():
            return c
    return columns[0] if columns else ""


@app.get("/api/enrich/catalog")
async def enrich_catalog():
    return {"grupos": [
        {"grupo": g["grupo"], "fonte": g["fonte"],
         "campos": [{"key": k, "label": lbl} for k, lbl in g["campos"]]}
        for g in _ENRICH_CATALOG
    ], "assertiva_ok": assertiva.enabled(), "integralx_ok": bool(mkbuscas.TEL_AUTH_VALUE)}


@app.post("/api/enrich/upload")
async def enrich_upload(file: UploadFile = File(...)):
    """Recebe XLSX/XLS/CSV/TSV e devolve as abas, colunas e um preview (sem enriquecer).

    Parsing robusto (sheet_reader): encoding/delimitador auto, cabeçalho bagunçado,
    células com erro, floats de CNPJ, abas quebradas.
    """
    try:
        content = await file.read()
    except Exception as exc:
        return {"status": "error", "message": f"Falha ao receber arquivo: {str(exc)[:150]}"}
    if not content:
        return {"status": "error", "message": "Arquivo vazio."}
    try:
        parsed, aviso = sheet_reader.read_table(file.filename or "", content)
    except ValueError as exc:
        return {"status": "error", "message": str(exc)}
    except Exception as exc:
        return {"status": "error", "message": f"Não consegui ler a planilha: {str(exc)[:150]}"}

    up_id = uuid.uuid4().hex[:12]
    store, sheets = {}, []
    for sh in parsed:
        title = sh["title"]
        # evita colisão de nomes de aba
        base, n = title, 2
        while title in store:
            title = f"{base} ({n})"; n += 1
        store[title] = {"columns": sh["columns"], "rows": sh["rows"]}
        sheets.append({"name": title, "columns": sh["columns"], "linhas": len(sh["rows"]),
                       "preview": sh["rows"][:3], "cnpj_col": _guess_cnpj_col(sh["columns"])})
    _UPLOADS[up_id] = store
    return {"status": "ok", "upload_id": up_id, "sheets": sheets, "aviso": aviso}


async def _enrich_cnpj(cnpj: str, want: set) -> dict:
    """Enriquece um CNPJ com os campos pedidos. Só chama Assertiva/integralX se
    houver campos daquela fonte selecionados (controla consumo)."""
    out = {k: "" for k in want}
    # normaliza a célula (float/sci-notation) antes de extrair dígitos
    digits = brasilapi.only_digits(str(sheet_reader.normalize_cell(cnpj) or ""))
    need_rfb = any(k.startswith("rfb_") for k in want)
    need_as = any(k.startswith("as_") for k in want)
    need_so = any(k.startswith("so_") for k in want)
    need_vf = any(k.startswith("vf_") for k in want)
    # Excel costuma comer o zero à esquerda do CNPJ (guarda como número) — completa 14.
    if 8 <= len(digits) < 14:
        digits = digits.zfill(14)

    company = None
    if (need_rfb or need_as or need_vf or need_so) and _cnpj_local():
        loc = cnpj_lookup.by_cnpj(digits)
        if loc.get("status") == "ok":
            company = loc["company"]
    if company:
        qsa = company.get("qsa") or []
        s1 = qsa[0] if qsa else {}
        mp = {
            "rfb_razao": company.get("razao_social", ""),
            "rfb_fantasia": company.get("nome_fantasia", ""),
            "rfb_situacao": company.get("descricao_situacao_cadastral", ""),
            "rfb_cnae_cod": company.get("cnae_fiscal", ""),
            "rfb_cnae": company.get("cnae_fiscal_descricao", ""),
            "rfb_porte": company.get("porte", ""),
            "rfb_capital": company.get("capital_social", ""),
            "rfb_natureza": company.get("natureza_juridica", ""),
            "rfb_abertura": company.get("data_inicio_atividade", ""),
            "rfb_matriz": company.get("matriz_filial", ""),
            "rfb_endereco": " ".join(str(x) for x in [company.get("logradouro", ""),
                            company.get("numero", ""), company.get("bairro", "")] if x).strip(),
            "rfb_municipio": company.get("municipio", ""),
            "rfb_uf": company.get("uf", ""),
            "rfb_cep": company.get("cep", ""),
            "rfb_tel1": company.get("ddd_telefone_1", ""),
            "rfb_tel2": company.get("ddd_telefone_2", ""),
            "rfb_email": company.get("email", ""),
            "rfb_qtd_socios": len(qsa),
            "rfb_socio1": s1.get("nome_socio", ""),
            "rfb_simples": company.get("opcao_simples", ""),
            "rfb_mei": company.get("opcao_mei", ""),
        }
        for k in want:
            if k in mp:
                out[k] = mp[k]

    # Assertiva: telefone/email da empresa por CNPJ
    best_mobile = ""
    if (need_as or need_vf) and assertiva.enabled():
        try:
            r = await assertiva.telefones_documento(digits, tipo="CNPJ")
            if r.get("status") == "ok":
                tels = mkbuscas.refine_phones(r.get("telefones") or [], modo="todos", max_n=5)
                celus = [t for t in tels if t.get("categoria") == "celular"]
                fixos = [t for t in tels if t.get("categoria") == "fixo"]
                best_mobile = (celus[0]["digits"] if celus else (tels[0]["digits"] if tels else ""))
                if "as_empresa_tel" in want:
                    out["as_empresa_tel"] = celus[0]["digits"] if celus else (tels[0]["digits"] if tels else "")
                if "as_empresa_tel2" in want:
                    out["as_empresa_tel2"] = celus[1]["digits"] if len(celus) > 1 else (fixos[0]["digits"] if fixos else "")
                if "as_empresa_whatsapp" in want:
                    out["as_empresa_whatsapp"] = "SIM" if any(t.get("whatsapp") for t in tels) else ""
            if "as_empresa_email" in want:
                a = await assertiva.consulta_cnpj(digits)
                if a.get("status") == "ok":
                    emails = ((a.get("data") or {}).get("resposta") or {}).get("emails") or []
                    if emails:
                        e0 = emails[0]
                        out["as_empresa_email"] = e0.get("email") if isinstance(e0, dict) else str(e0)
        except Exception:
            pass

    # telefone/CPF do sócio p/ a verificação (preenchidos no bloco de sócios abaixo)
    socio_vphone, socio_vcpf = "", ""
    # Sócios — contato PESSOAL: resolve CPF do sócio (JBR) + celular/e-mail (Assertiva)
    if (need_so or need_vf) and company:
        _enrich_qsa_cpf(company)  # resolve cpf_completo de cada sócio via JBR
        socios = [s for s in (company.get("qsa") or []) if isinstance(s, dict)]
        resumo = []
        # processa no máx. 3 sócios (controla consumo)
        for idx, s in enumerate(socios[:3], start=1):
            nome = s.get("nome_socio") or ""
            cpf = s.get("cpf_completo") or ""
            cel, cel2, wa, email = "", "", "", ""
            if cpf and assertiva.enabled():
                try:
                    c = await assertiva.contato_cpf(cpf)
                    if c.get("status") == "ok":
                        tels = mkbuscas.refine_phones(c.get("telefones") or [], modo="celular_fixo", max_n=5)
                        celus = [t["digits"] for t in tels if t.get("categoria") == "celular"]
                        cel = celus[0] if celus else ""
                        cel2 = celus[1] if len(celus) > 1 else ""
                        wa = "SIM" if any(t.get("whatsapp") for t in tels) else ""
                        email = (c.get("emails") or [""])[0]
                except Exception:
                    pass
            # guarda o 1º sócio com celular como alvo da verificação
            if cel and not socio_vphone:
                socio_vphone, socio_vcpf = cel, cpf
                if not need_so:   # só precisávamos do telefone p/ verificar
                    break
            if idx == 1:
                for k, v in (("so_socio1_nome", nome), ("so_socio1_cpf", cpf),
                             ("so_socio1_celular", cel), ("so_socio1_whatsapp", wa),
                             ("so_socio1_email", email)):
                    if k in want:
                        out[k] = v
            elif idx == 2:
                for k, v in (("so_socio2_nome", nome), ("so_socio2_cpf", cpf),
                             ("so_socio2_celular", cel)):
                    if k in want:
                        out[k] = v
            if nome and cel:
                resumo.append(f"{nome}: {cel}")
        if "so_todos_tel" in want:
            out["so_todos_tel"] = " | ".join(resumo)

    # Verificação integralX: prioriza o telefone do SÓCIO e checa se PERTENCE ao
    # CPF dele (verificação real). Sem CPF/sócio, cai no telefone da empresa (contagem).
    if need_vf:
        phone = socio_vphone or best_mobile or brasilapi.only_digits(str(out.get("rfb_tel1") or ""))
        cpf_alvo = socio_vcpf if socio_vphone else ""
        if "vf_telefone" in want:
            out["vf_telefone"] = phone
        if phone and len(phone) >= 10 and mkbuscas.TEL_AUTH_VALUE:
            try:
                if cpf_alvo:
                    r = await mkbuscas.telefone_pertence(phone, cpf_alvo)
                    if r.get("status") == "no_access":
                        if "vf_status" in want:
                            out["vf_status"] = "sem acesso (chave integralX)"
                    elif r.get("status") == "ok":
                        if "vf_vinculos" in want:
                            out["vf_vinculos"] = r.get("total", 0)
                        if "vf_status" in want:
                            out["vf_status"] = ("pertence ao sócio" if r.get("atrelado")
                                                else ("compartilhado" if r.get("alerta_compartilhado")
                                                      else "não pertence"))
                    else:
                        if "vf_status" in want:
                            out["vf_status"] = "n/d"
                else:
                    rev = await mkbuscas.consulta_telefone(phone)
                    if rev.get("status") == "ok":
                        total = rev.get("total", 0)
                        if "vf_vinculos" in want:
                            out["vf_vinculos"] = total
                        if "vf_status" in want:
                            out["vf_status"] = ("compartilhado/lixo" if total >= 50
                                                else ("válido" if total >= 1 else "sem vínculo"))
                    elif rev.get("status") == "no_access":
                        if "vf_status" in want:
                            out["vf_status"] = "sem acesso (chave integralX)"
                    else:
                        if "vf_status" in want:
                            out["vf_status"] = "n/d"
            except Exception:
                if "vf_status" in want:
                    out["vf_status"] = "erro"
    return out


@app.post("/api/enrich/linha")
async def enrich_linha(payload: dict = Body(default={})):
    """Enriquece UM CNPJ com os campos pedidos, sem passar por arquivo.

    É o que a API pública usa em /api/v1/enriquecimento: o fluxo da tela precisa
    de upload de planilha, mas outro sistema só quer mandar CNPJ + campos.
    Body: {cnpj, campos:[...]}.
    """
    cnpj = re.sub(r"\D", "", str(payload.get("cnpj") or ""))
    pedidos = [c for c in (payload.get("campos") or []) if isinstance(c, str)]
    campos = [c for c in pedidos if c in _ENRICH_KEYS]
    # Campo com nome errado era descartado em silêncio; agora volta na resposta.
    ignorados = [c for c in pedidos if c not in _ENRICH_KEYS]
    if len(cnpj) != 14:
        return {"status": "error", "message": "CNPJ inválido."}
    if not campos:
        return {"status": "error", "message": "Nenhum campo válido pedido.",
                "ignorados": ignorados}
    dados = await _enrich_cnpj(cnpj, set(campos))
    return {"status": "ok", "cnpj": cnpj, "dados": dados, "ignorados": ignorados}


@app.post("/api/enrich/run")
async def enrich_run(payload: dict = Body(default={})):
    """Enriquece as linhas de uma aba. Body: {upload_id, sheet, cnpj_col, fields:[], limite}."""
    up_id = payload.get("upload_id")
    store = _UPLOADS.get(up_id)
    if not store:
        return {"status": "error", "message": "Upload expirado — reenvie a planilha."}
    sheet = payload.get("sheet") or next(iter(store))
    if sheet not in store:
        return {"status": "error", "message": "Aba não encontrada."}
    cnpj_col = payload.get("cnpj_col") or _guess_cnpj_col(store[sheet]["columns"])
    fields = [f for f in (payload.get("fields") or []) if f in _ENRICH_KEYS]
    if not fields:
        return {"status": "error", "message": "Selecione ao menos um campo para enriquecer."}
    limite = int(payload.get("limite") or 100)
    rows = store[sheet]["rows"][:limite]
    want = set(fields)

    # Concorrência controlada (Assertiva/integralX têm limite diário).
    sem = asyncio.Semaphore(6)

    async def _one(row):
        async with sem:
            enr = await _enrich_cnpj(row.get(cnpj_col, ""), want)
        merged = dict(row)
        merged.update(enr)
        return merged

    enriched = await asyncio.gather(*[_one(r) for r in rows])
    label_of = {k: lbl for g in _ENRICH_CATALOG for (k, lbl) in g["campos"]}
    added_cols = [{"key": f, "label": label_of.get(f, f)} for f in fields]
    return {"status": "ok", "sheet": sheet, "cnpj_col": cnpj_col,
            "base_cols": store[sheet]["columns"], "added_cols": added_cols,
            "rows": enriched, "enriquecidas": len(enriched),
            "total_aba": len(store[sheet]["rows"])}


@app.post("/api/enrich/export")
async def enrich_export(payload: dict = Body(default={})):
    """Gera XLSX com as colunas originais + as escolhidas. Body: {columns:[{key,label}], rows:[...]}."""
    from openpyxl import Workbook
    from openpyxl.styles import Font, PatternFill
    from openpyxl.utils import get_column_letter

    columns = payload.get("columns") or []
    rows = payload.get("rows") or []
    wb = Workbook()
    ws = wb.active
    ws.title = "Lista enriquecida"
    hf = Font(bold=True, color="FFFFFF")
    fill = PatternFill("solid", fgColor="1D4ED8")
    for i, col in enumerate(columns, start=1):
        c = ws.cell(row=1, column=i, value=col.get("label", col.get("key")))
        c.font = hf
        c.fill = fill
    for r_idx, row in enumerate(rows, start=2):
        for i, col in enumerate(columns, start=1):
            v = row.get(col.get("key"), "")
            if hasattr(v, "isoformat"):
                v = v.isoformat(sep=" ")[:19]
            ws.cell(row=r_idx, column=i, value=v)
    for i in range(1, len(columns) + 1):
        ws.column_dimensions[get_column_letter(i)].width = 20
    ws.freeze_panes = "A2"
    ws.auto_filter.ref = f"A1:{get_column_letter(max(len(columns),1))}{max(len(rows)+1,1)}"
    buf = io.BytesIO()
    wb.save(buf)
    buf.seek(0)
    return StreamingResponse(
        buf, media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        headers={"Content-Disposition": 'attachment; filename="lista-enriquecida.xlsx"'})


# ---- Configurações de integração (admin) ----
# Admin é verificado pelo header X-User-Role, que SÓ o app-online (Render) envia
# após validar a sessão. O serviço de dados confia nele (só chega via proxy c/ segredo).

def _is_admin(request: Request) -> bool:
    return (request.headers.get("x-user-role") or "").lower() == "admin"


# ---------------------------------------------------------------------
# CHAMADOS — bug e melhoria reportados por quem usa
# ---------------------------------------------------------------------
@app.post("/api/chamados")
async def chamado_abrir(request: Request,
                        tipo: str = Form("bug"),
                        titulo: str = Form(""),
                        descricao: str = Form(""),
                        aba: str = Form(""),
                        contexto: str = Form(""),
                        anexos: list[UploadFile] = File(default=[])):
    """Abre um chamado. QUALQUER usuário logado — não é admin.

    É `multipart` e não JSON por causa do print: mandar imagem em JSON exige
    base64, que infla 33% e ainda passa pela memória do processo inteira
    antes de virar arquivo.

    `aba` e `contexto` vêm da tela e valem tanto quanto o texto: "não
    funciona" com a aba e os filtros junto é reproduzível; sem eles, alguém
    vai ter que adivinhar onde aquilo acontecia.
    """
    guardados = []
    for arq in (anexos or [])[:chamados.MAX_ANEXOS]:
        try:
            conteudo = await arq.read()
        except Exception:
            continue
        nome = chamados.salvar_anexo(arq.filename or "", conteudo,
                                     arq.content_type or "")
        if nome:
            guardados.append(nome)
    r = chamados.abrir(
        tipo=tipo, titulo=titulo, descricao=descricao,
        usuario=(request.headers.get("x-user-email") or ""),
        aba=aba, contexto=contexto, anexos=guardados)
    if r.get("status") == "ok":
        r["anexos_recebidos"] = len(guardados)
        # Diz quantos foram RECUSADOS. Print que some sem aviso faz a pessoa
        # achar que mandou e o admin achar que ela não mandou.
        r["anexos_recusados"] = len(anexos or []) - len(guardados)
    return r


@app.get("/api/chamados")
async def chamados_listar(request: Request, status: str = "", limite: int = 100):
    """Lista os chamados. SÓ ADMIN — são relatos de outras pessoas."""
    if not _is_admin(request):
        return {"status": "forbidden", "chamados": [], "novos": 0}
    return chamados.listar(status=status, limite=min(int(limite or 100), 500))


@app.get("/api/chamados/novos")
async def chamados_novos(request: Request):
    """Só a contagem, para a bolinha vermelha do menu.

    Endpoint próprio porque a tela consulta isto de tempos em tempos: trazer
    a lista inteira para mostrar um número seria carregar todos os chamados
    a cada ciclo.
    """
    if not _is_admin(request):
        return {"status": "ok", "novos": 0}
    return {"status": "ok", "novos": chamados.contar_novos()}


@app.post("/api/chamados/{ident}/status")
async def chamado_status(ident: str, request: Request,
                         payload: dict = Body(default={})):
    if not _is_admin(request):
        return {"status": "forbidden"}
    return chamados.marcar(ident, str(payload.get("status") or ""),
                           str(payload.get("resposta") or ""))


@app.get("/api/chamados/anexo/{nome}")
async def chamado_anexo(nome: str, request: Request):
    """Serve um print. SÓ ADMIN, e o nome é validado contra o formato que
    `chamados.salvar_anexo` gera — nome de arquivo vindo da URL é caminho
    vindo de fora."""
    if not _is_admin(request):
        return JSONResponse({"status": "forbidden"}, status_code=403)
    caminho = chamados.caminho_anexo(nome)
    if not caminho:
        return JSONResponse({"status": "not_found"}, status_code=404)
    return FileResponse(caminho)


@app.post("/api/navlog")
async def navlog_registrar(request: Request, payload: dict = Body(default={})):
    """Log de navegação: qualquer usuário logado pode registrar (não é admin-only)."""
    email = request.headers.get("x-user-email") or ""
    navlog.registrar(
        email, payload.get("tab") or "",
        tipo=payload.get("tipo") or "", query=payload.get("query") or "", resultado=payload.get("resultado") or "",
    )
    return {"ok": True}


@app.get("/api/navlog/mine")
async def navlog_mine(request: Request, dias: int = 7):
    """Resumo de uso do próprio usuário (painel "Início") — não é admin-only."""
    email = request.headers.get("x-user-email") or ""
    res = navlog.resumo_usuario(email, dias)
    res["status"] = "ok"
    return res


@app.get("/api/navlog")
async def navlog_listar(request: Request, desde: str = "", ate: str = "", user: str = ""):
    """Histórico de navegação de todos os usuários — só admin."""
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    import datetime as _dt
    desde_ts = None
    ate_ts = None
    try:
        if desde:
            desde_ts = _dt.datetime.strptime(desde, "%Y-%m-%d").timestamp()
        if ate:
            ate_ts = _dt.datetime.strptime(ate, "%Y-%m-%d").timestamp() + 86400 - 1
    except ValueError:
        return {"status": "error", "message": "Datas inválidas (use YYYY-MM-DD)."}
    res = navlog.listar(desde_ts, ate_ts, user)
    # Um admin não pode ver as pesquisas de outro admin — filtra qualquer email de role admin.
    try:
        emails_admin = {u["email"] for u in auth.list_users() if u.get("role") == "admin"}
    except Exception:
        emails_admin = set()
    if emails_admin:
        res["entradas"] = [e for e in res["entradas"] if e.get("user") not in emails_admin]
        res["usuarios"] = [u for u in res["usuarios"] if u not in emails_admin]
        res["por_usuario"] = {u: n for u, n in res["por_usuario"].items() if u not in emails_admin}
        res["total"] = sum(res["por_usuario"].values())
    res["status"] = "ok"
    return res


@app.get("/api/config")
async def config_get(request: Request):
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    tok = config_store.get("meetime_token") or os.environ.get("MEETIME_TOKEN", "")
    return {"meetime": {
        "configurado": bool(tok),
        "token_mascarado": (tok[:4] + "…" + tok[-4:]) if tok and len(tok) > 8 else ("definido" if tok else ""),
        "base_url": meetime._base_url(), "leads_path": meetime._leads_path(),
        "auth_header": meetime._auth_header(),
        "por_grupo": meetime.status_grupos(),
    }}


@app.post("/api/config/meetime")
async def config_meetime(request: Request, payload: dict = Body(default={})):
    if not _is_admin(request):
        return JSONResponse({"detail": "Requer admin."}, status_code=403)
    # Token específico de um grupo (multi-tenant) — não passa pelo config_store global.
    if payload.get("grupo_id"):
        meetime.set_token_grupo(payload["grupo_id"], str(payload.get("token") or "").strip())
        return {"status": "ok", "configurado": bool(meetime._token(payload["grupo_id"]))}
    updates = {}
    for k_in, k_cfg in (("token", "meetime_token"), ("base_url", "meetime_base_url"),
                        ("leads_path", "meetime_leads_path"), ("auth_header", "meetime_auth_header")):
        if payload.get(k_in) is not None:
            updates[k_cfg] = str(payload[k_in]).strip()
    config_store.set_many(updates)
    meetime._cache.clear()  # invalida cache (força rebaixar com a config nova)
    return {"status": "ok", "configurado": bool(meetime._token())}


# ---- Meetime: dedup (não prospectar quem já está no CRM) ----
# Cada usuário pertence a um grupo (X-User-Grupo, definido pelo admin em Usuários),
# e cada grupo tem seu próprio token/conta Meetime — usuários de grupos diferentes
# nunca cruzam dados de CRMs diferentes.

@app.get("/api/meetime/status")
async def meetime_status(request: Request, refresh: bool = False):
    grupo_id = request.headers.get("x-user-grupo") or ""
    usuario = request.headers.get("x-user-email") or ""
    if not meetime.enabled(grupo_id, "", usuario):
        return {"enabled": False}
    ex = await meetime.fetch_existing(force=refresh, grupo_id=grupo_id,
                                      usuario=usuario)
    return {"enabled": True, "status": ex.get("status"), "message": ex.get("message"),
            "total_cnpjs": len(ex.get("cnpjs") or []),
            "total_nomes": len(ex.get("nomes") or []), "cache": ex.get("cache")}


@app.get("/api/meetime/meu-token")
async def meetime_meu_token(request: Request):
    """Qual conta Meetime está ativa para mim — SEM devolver o token.

    Volta só os quatro últimos dígitos e de onde ele vem (meu, do grupo, ou
    nenhum). É o bastante para a pessoa reconhecer a conta e não é o
    bastante para usar a credencial.
    """
    return {"status": "ok", **meetime.status_usuario(
        request.headers.get("x-user-email") or "",
        request.headers.get("x-user-grupo") or "")}


@app.post("/api/meetime/meu-token")
async def meetime_salvar_token(request: Request, payload: dict = Body(default={})):
    """Troca o MEU token. Não é admin: é a conta do próprio operador.

    Guardar no servidor expõe MENOS que o campo antigo do painel de filtros,
    que fazia o segredo atravessar o navegador a cada busca. Aqui ele passa
    uma vez, na troca, e nunca volta.

    Token vazio apaga — é como a pessoa volta a usar o token do grupo.
    """
    email = request.headers.get("x-user-email") or ""
    r = meetime.set_token_usuario(email, str(payload.get("token") or ""))
    if r.get("status") != "ok":
        return r
    return {**r, **meetime.status_usuario(
        email, request.headers.get("x-user-grupo") or "")}


@app.post("/api/meetime/testar")
async def meetime_testar(request: Request, payload: dict = Body(default={})):
    """Diz se o token serve — em uma requisição, sem rodar a dedup inteira.

    QUALQUER usuário, e não só admin: quem cola o token na tela de busca é o
    operador, e mandá-lo esperar a dedup inteira falhar para descobrir que
    errou uma letra é o pior jeito possível de dar essa resposta.

    O token não é gravado nem devolvido. O que volta é o que ele ENXERGA:
    quantos leads a conta tem, quantos já estão guardados aqui e quantos
    faltam sincronizar.
    """
    return await meetime.testar_token(
        token=str(payload.get("token") or ""),
        grupo_id=str(payload.get("grupo_id") or ""),
        usuario=(request.headers.get("x-user-email") or ""))


@app.post("/api/meetime/dedup")
async def meetime_dedup(request: Request, payload: dict = Body(default={})):
    """Body: {empresas:[{cnpj, razao_social}]}. Remove quem já está na Meetime
    (CNPJ exato OU nome por similaridade LIKE %). Retorna {novos, removidos}."""
    grupo_id = request.headers.get("x-user-grupo") or ""
    empresas = payload.get("empresas") or payload.get("candidatos") or []
    # Token que o OPERADOR digitou, para filtrar contra uma conta que não é a
    # do grupo dele. Vale só para esta chamada: não é gravado em lugar nenhum
    # e não volta na resposta.
    token_avulso = str(payload.get("token") or "").strip()
    if not meetime.enabled(grupo_id, token_avulso,
                           request.headers.get("x-user-email") or ""):
        return {"status": "unavailable",
                "message": "Nenhuma conta Meetime ativa. Guarde o seu token em "
                           "\"Minha conta Meetime\", no menu do seu usuário, "
                           "ou cole um token só para esta busca.",
                "novos": empresas, "removidos": []}
    ex = await meetime.fetch_existing(force=bool(payload.get("refresh")),
                                      grupo_id=grupo_id, token_avulso=token_avulso,
                                      usuario=(request.headers.get("x-user-email") or ""))
    if ex.get("status") and ex["status"] != "ok":
        return {"status": ex["status"], "message": ex.get("message"),
                "novos": empresas, "removidos": []}
    res = meetime.dedup(empresas, ex)
    res["status"] = "ok"
    return res


# ---- Serviço de dados: NÃO serve o frontend ----
# A tela de login e o app ficam no app-online (Render). Aqui é só endpoint de dados,
# acessível apenas pelo proxy com o segredo. Servir a UI aqui confundia (login dava
# "segredo de proxy"). O root só explica o que é.

@app.get("/")
async def index():
    return JSONResponse({
        "service": "capiblu-data",
        "mensagem": "Este é o serviço de DADOS interno do CapiBLU (uso via proxy). "
                    "Para acessar a plataforma, use o app online.",
        "app": "https://app.capiblu.net",
    })


if __name__ == "__main__":
    import uvicorn

    uvicorn.run("main:app", host="0.0.0.0", port=8010, reload=True)
