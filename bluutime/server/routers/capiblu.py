"""CapiBLU dentro do Bluutime.

Duas camadas:
1. Passagem direta — as ferramentas do CapiBLU expostas na UI da Meetime
   (empresas, pessoas, telefone reverso, decisores, RAIS, enriquecimento…).
2. Ponte de prospecção — o que o Meetime não faz: transformar uma consulta do
   CapiBLU em base de leads e cadência, sem exportar XLSX e reimportar CSV.
"""
import asyncio
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query, Request
from sqlalchemy.orm import Session

from .. import serial
from ..capiblu_client import capiblu_error, get, post
from ..db import get_db
from ..models import Cadence, Lead, LeadBase
from .flow import _schedule_cadence

router = APIRouter(prefix="/api/capiblu")

TOOLS = [
    {"key": "empresas", "name": "Prospecção B2B", "area": "Empresas",
     "path": "/api/companies/search", "cost": "grátis (base RFB local)",
     "what": "Filtra empresas por UF, município, CNAE, porte e capital social."},
    {"key": "empresa", "name": "Uma empresa", "area": "Empresas",
     "path": "/api/company/{cnpj}", "cost": "grátis",
     "what": "Cadastro completo da Receita com QSA e CPF de sócio resolvido."},
    {"key": "decisores", "name": "Decisores", "area": "Empresas",
     "path": "/api/company/{cnpj}/decisores", "cost": "gasta consulta",
     "what": "Quem manda na empresa, com cargo e nível de decisão 1/2/3."},
    {"key": "vinculos", "name": "Vínculo empregatício (RAIS)", "area": "Empresas",
     "path": "/api/company/{cnpj}/vinculos", "cost": "gasta consulta",
     "what": "Quem trabalha ou trabalhou na empresa, com admissão e tempo de casa."},
    {"key": "conexoes", "name": "Conexões", "area": "Empresas",
     "path": "/api/company/{cnpj}/conexoes", "cost": "gasta consulta",
     "what": "Sócios, decisores e empresas ligadas, com telefone e flag de WhatsApp."},
    {"key": "contatos", "name": "Contatos prontos", "area": "Empresas",
     "path": "/api/company/{cnpj}/leads", "cost": "gasta consulta",
     "what": "Sócios e decisores já com telefone priorizado por atualidade."},
    {"key": "pessoa-nome", "name": "Pessoa pelo nome", "area": "Pessoas",
     "path": "/api/person/name-search", "cost": "grátis (base JBR local)",
     "what": "Busca por nome, exata ou ampla, em 223 milhões de linhas."},
    {"key": "pessoa", "name": "Uma pessoa", "area": "Pessoas",
     "path": "/api/person/{cpf}", "cost": "grátis",
     "what": "Identidade por CPF: nome, nascimento, sexo."},
    {"key": "pessoa-mk", "name": "Perfil completo (Mk)", "area": "Pessoas",
     "path": "/api/person/{cpf}/mk", "cost": "gasta consulta",
     "what": "Telefones, endereços, renda, score, parentes e vizinhos."},
    {"key": "parentes", "name": "Parentes e conexões", "area": "Pessoas",
     "path": "/api/person/{cpf}/parentes", "cost": "gasta 2 consultas",
     "what": "Mãe, pai, filhos, irmãos, cônjuge e sócios, com telefone."},
    {"key": "pessoa-vinculos", "name": "Onde a pessoa trabalha", "area": "Pessoas",
     "path": "/api/person/{cpf}/vinculos", "cost": "gasta consulta",
     "what": "O inverso do CNPJ: histórico de vínculos pela RAIS."},
    {"key": "telefone", "name": "De quem é este telefone", "area": "Telefones",
     "path": "/api/phone/{phone}/reverse", "cost": "gasta consulta",
     "what": "Telefone reverso: CPFs e CNPJs atrelados ao número."},
    {"key": "telefone-pertence", "name": "Validar telefone × documento", "area": "Telefones",
     "path": "/api/phone/{phone}/pertence/{doc}", "cost": "gasta consulta",
     "what": "Confirma se o número é daquele CPF/CNPJ e avisa se é linha compartilhada."},
    {"key": "assertiva", "name": "Consulta Assertiva", "area": "Fontes",
     "path": "/api/assertiva/*", "cost": "gasta consulta",
     "what": "Localize V3 bruto por CPF, CNPJ, telefone, e-mail ou nome."},
    {"key": "enriquecimento", "name": "Minha planilha", "area": "Planilhas",
     "path": "/api/enrich/*", "cost": "condicional",
     "what": "Sobe XLSX/CSV, escolhe os campos e recebe a planilha preenchida."},
    {"key": "modelos", "name": "Meus modelos", "area": "Planilhas",
     "path": "/api/prospeccao/modelos", "cost": "grátis",
     "what": "Exporta no layout de coluna que o cliente pede."},
    {"key": "dossie", "name": "Dossiê PDF", "area": "Relatórios",
     "path": "/api/dossie/pdf", "cost": "gasta consulta · só admin",
     "what": "PDF completo de CPF ou CNPJ, com resumo por IA opcional."},
    {"key": "custos", "name": "Custos e consumo", "area": "Administração",
     "path": "/api/custos/*", "cost": "grátis",
     "what": "Consumo por usuário e confronto com o relatório oficial da Assertiva."},
]


@router.get("/status")
def status():
    err = capiblu_error()
    return {"available": err is None, "error": err,
            "tools": TOOLS,
            "areas": sorted({t["area"] for t in TOOLS})}


@router.get("/tools")
def tools():
    return TOOLS


# ── Passagem direta: a UI da Meetime falando com as rotas do CapiBLU ──
@router.get("/empresas")
async def empresas(uf: str = "", municipio: str = "", cnae: str = "", porte: str = "",
                   situacao: str = "ATIVA", capital_min: int = 0, capital_max: int = 0,
                   com_telefone: bool = False, somente_matriz: bool = False,
                   texto: str = "", limite: int = Query(20, le=200), offset: int = 0):
    filtros = {k: v for k, v in {
        "uf": uf, "municipio": municipio, "cnae": cnae, "porte": porte,
        "situacao": situacao, "capital_min": capital_min or None,
        "capital_max": capital_max or None, "com_telefone": com_telefone or None,
        "somente_matriz": somente_matriz or None, "texto": texto,
    }.items() if v}
    code, data = await post("/api/companies/search",
                            json={"filtros": filtros, "limite": limite, "offset": offset})
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na busca de empresas."))
    return data


@router.get("/empresas/{cnpj}")
async def empresa(cnpj: str):
    code, data = await get(f"/api/company/{cnpj}")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha ao consultar o CNPJ."))
    return data


EMPRESA_BLOCOS = {
    "decisores": "decisores", "vinculos": "vinculos", "conexoes": "conexoes",
    "employees": "employees", "contacts": "contacts",
    # cruzamentos da aba "Vínculo empregatício" do CapiBLU
    "vinculos-assertiva": "vinculos/assertiva", "vinculos-cargos": "vinculos/cargos",
    "contatos-serasa": "contacts",
}


@router.get("/empresas/{cnpj}/{bloco}")
async def empresa_bloco(cnpj: str, bloco: str, request: Request):
    """decisores · vinculos · conexoes · employees · contacts ·
    vinculos-assertiva · vinculos-cargos

    A query string do chamador é repassada inteira: é ela que carrega
    `conexoes`, `refresh`, `nivel` e `cargo` — sem isso o bloco vinha sempre
    no modo padrão.
    """
    path = EMPRESA_BLOCOS.get(bloco)
    if not path:
        raise HTTPException(404, f"Bloco desconhecido. Use: {', '.join(EMPRESA_BLOCOS)}")
    code, data = await get(f"/api/company/{cnpj}/{path}",
                           params=dict(request.query_params), timeout=180.0)
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na consulta."))
    return data


@router.get("/pessoas")
async def pessoas(q: str, broad: bool = False, limit: int = Query(40, le=200),
                  offset: int = 0):
    code, data = await get("/api/person/name-search",
                           params={"q": q, "broad": broad, "limit": limit, "offset": offset})
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na busca por nome."))
    return data


@router.get("/pessoas/{cpf}")
async def pessoa(cpf: str):
    code, data = await get(f"/api/person/{cpf}")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha ao consultar o CPF."))
    return data


@router.get("/pessoas/{cpf}/{bloco}")
async def pessoa_bloco(cpf: str, bloco: str):
    """mk · parentes · vinculos · contacts"""
    if bloco not in {"mk", "parentes", "vinculos", "contacts"}:
        raise HTTPException(404, "Bloco desconhecido.")
    code, data = await get(f"/api/person/{cpf}/{bloco}")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na consulta."))
    return data


@router.get("/telefones/{numero}")
async def telefone(numero: str):
    code, data = await get(f"/api/phone/{numero}/reverse")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na consulta reversa."))
    return data


@router.get("/telefones/{numero}/pertence/{documento}")
async def telefone_pertence(numero: str, documento: str):
    code, data = await get(f"/api/phone/{numero}/pertence/{documento}")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na validação."))
    return data


@router.get("/lookups/{tipo}")
async def lookups(tipo: str):
    code, data = await get("/api/cnpj/lookup", params={"tipo": tipo})
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha ao carregar a lista."))
    return data


@router.get("/consumo")
async def consumo(dias: int = 30):
    code, data = await get("/api/custos/total", params={"dias": dias})
    if code >= 400:
        return {"status": "unavailable", "detail": data.get("detail", "")}
    return data


# ── Ponte de prospecção: consulta CapiBLU → base de leads → cadência ──
def _valid_cnpj(raw: str) -> str:
    """Devolve o CNPJ com 14 dígitos, ou "" se o dígito verificador não bater.

    O CapiBLU resolve o CNPJ pela raiz de 8 dígitos: `00000000000000` cai na
    matriz do Banco do Brasil e traz 42 contatos — cada um gastando consulta
    paga. Um erro de digitação não pode virar fatura, então a validação
    acontece aqui, antes de qualquer chamada.
    """
    digits = "".join(ch for ch in str(raw) if ch.isdigit())
    if len(digits) != 14 or len(set(digits)) == 1:
        return ""
    for size in (12, 13):
        weights = [6, 5, 4, 3, 2, 9, 8, 7, 6, 5, 4, 3, 2][-size:]
        total = sum(int(d) * w for d, w in zip(digits[:size], weights))
        check = (total % 11)
        expected = 0 if check < 2 else 11 - check
        if int(digits[size]) != expected:
            return ""
    return digits


def _contact_to_lead(company: dict, contact: dict) -> dict:
    """Converte um contato do CapiBLU em lead, preservando os sinais de ranking.

    Os telefones já vêm ordenados do mais atual para o mais antigo (linha quente,
    titularidade, último contato). O primeiro da lista é o melhor — é dele que
    saem `phone_kind` e `whatsapp`.
    """
    tels = contact.get("telefones") or []
    phones = [t.get("display") or t.get("raw") for t in tels]
    best = tels[0] if tels else {}
    emails = contact.get("emails") or []
    name = (contact.get("nome") or "").strip()
    return {
        "name": name, "firstName": name.split(" ")[0] if name else "",
        "company": company.get("razao_social") or company.get("nome_fantasia") or "",
        "razaoSocial": company.get("razao_social") or "",
        "position": contact.get("cargo") or contact.get("tipo") or "",
        "cnpj": (company.get("cnpj") or "").replace(".", "").replace("/", "").replace("-", ""),
        "cpf": contact.get("cpf") or "",
        "phone": " / ".join(p for p in phones if p),
        "email": emails[0] if emails else "",
        "city": company.get("municipio") or "", "state": company.get("uf") or "",
        "decisionLevel": int(contact.get("nivel") or 0),
        "contactKind": contact.get("tipo") or "",
        "phoneKind": best.get("categoria") or "",
        "whatsapp": bool(best.get("whatsapp")),
        "doNotCall": bool(best.get("nao_perturbe") or contact.get("nao_perturbe")),
    }


# Filtros aceitos por `cnpj_lookup.search`. A lista existe para não repassar
# lixo do cliente e para documentar, num lugar só, tudo que a busca entende.
FILTROS_EMPRESA = {
    "cnpj", "texto", "texto_escopo", "setor", "cnae", "natureza", "uf", "municipio",
    "situacao", "somente_matriz", "somente_filial", "porte", "capital_min",
    "capital_max", "mei_optante", "mei_excluir", "com_telefone", "com_email",
    "fundada_de", "fundada_ate", "tipo_empresa",
}


def _as_int(value, default: int) -> int:
    """Números que chegam do cliente não são confiáveis — um handler mal ligado
    já mandou o objeto do evento no lugar do offset e derrubou a rota com 500."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _clean_filtros(raw: dict) -> dict:
    out = {}
    for key, value in (raw or {}).items():
        if key not in FILTROS_EMPRESA or value in (None, "", [], False):
            continue
        out[key] = value
    return out


@router.post("/prospect/preview")
async def prospect_preview(payload: dict = Body(...)):
    """Roda a consulta de empresas e devolve o que viraria lead — antes de gastar."""
    filtros = _clean_filtros(payload.get("filtros") or {})
    # Sem `situacao` a base devolve empresa baixada e inapta junto com a ativa.
    filtros.setdefault("situacao", ["ATIVA"])
    limite = min(_as_int(payload.get("limite"), 20), 200)
    offset = max(0, _as_int(payload.get("offset"), 0))
    code, data = await post("/api/companies/search",
                            json={"filtros": filtros, "limite": limite, "offset": offset},
                            timeout=180.0)
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na busca."))
    empresas = data.get("empresas") or []
    return {"total": data.get("total", len(empresas)),
            "totalAprox": bool(data.get("total_aprox")),
            "fonte": data.get("fonte"), "empresas": empresas,
            "limite": limite, "offset": offset, "filtros": filtros}


@router.post("/prospect/pessoas")
async def prospect_pessoas(payload: dict = Body(...)):
    """Perfil 'Sócios' da prospecção: busca pessoas na base local (não gasta)."""
    filtros = dict(payload.get("filtros") or {})
    limite = min(_as_int(payload.get("limite"), 20), 200)
    offset = max(0, _as_int(payload.get("offset"), 0))
    code, data = await post("/api/prospeccao/pessoas",
                            json={"filtros": filtros, "limite": limite, "offset": offset},
                            timeout=180.0)
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na busca de pessoas."))
    return data


@router.post("/prospect/cobertura")
async def prospect_cobertura(payload: dict = Body(...)):
    """Mede em quantas empresas existe decisor SEM puxar telefone.

    É o teste barato que evita montar uma lista de 200 CNPJs e descobrir depois
    que dois terços não têm ninguém — 2 consultas por CNPJ, teto de 60.
    """
    cnpjs = [_valid_cnpj(c) for c in (payload.get("cnpjs") or [])]
    cnpjs = [c for c in cnpjs if c][:60]
    if not cnpjs:
        raise HTTPException(400, "Informe CNPJs válidos.")
    code, data = await post("/api/prospeccao/cobertura-decisores",
                            json={"cnpjs": cnpjs, "cargos": payload.get("cargos", "")},
                            timeout=300.0)
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha ao medir cobertura."))
    return data


@router.post("/prospect/import")
async def prospect_import(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Monta contatos das empresas e cria uma base de leads já ligada à cadência.

    É o passo que hoje é manual: exportar XLSX do CapiBLU e reimportar CSV no
    Meetime. Aqui a base guarda a consulta em `sourceQuery`, então dá para
    reexecutá-la depois.
    """
    raw_list = [c for c in (payload.get("cnpjs") or []) if str(c).strip()]
    cnpjs, invalidos = [], []
    for raw in raw_list:
        valid = _valid_cnpj(raw)
        (cnpjs if valid else invalidos).append(valid or str(raw))
    cnpjs = list(dict.fromkeys(cnpjs))
    if invalidos:
        raise HTTPException(400, "CNPJ inválido: " + ", ".join(invalidos[:10]))
    if not cnpjs:
        raise HTTPException(400, "Informe ao menos um CNPJ.")
    if len(cnpjs) > 200:
        raise HTTPException(400, "Máximo de 200 CNPJs por importação.")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Dê um nome à base de leads.")
    cadence_id = payload.get("cadenceId")
    if cadence_id and not db.get(Cadence, cadence_id):
        raise HTTPException(400, "Cadência inválida.")

    # Superfície completa de `GET /api/company/{cnpj}/leads` (main.py:940). O
    # default de `fonte_tel` é `assertiva`, como no CapiBLU.
    params = {"decisores": bool(payload.get("incluirDecisores", True)),
              "modo_tel": payload.get("tipoTelefone", "celular"),
              "max_tel": int(payload.get("maxTelefones", 3)),
              "fonte_tel": payload.get("fonteTelefone", "assertiva"),
              "socios_modo": payload.get("sociosModo", "todos"),
              "max_socios": int(payload.get("maxSocios", 0)),
              "decisores_fonte": payload.get("decisoresFonte", "assertiva"),
              "decisores_cargos": payload.get("cargos", ""),
              "max_decisores": int(payload.get("maxDecisores", 3)),
              "pular_sem_decisor": bool(payload.get("pularSemDecisor", False)),
              "fallback_hierarquia": int(payload.get("fallbackHierarquia", 0)),
              "apenas_cargo": bool(payload.get("apenasCargo", False)),
              "modelo_id": payload.get("modeloId", "")}

    sem = asyncio.Semaphore(6)

    async def fetch(cnpj: str):
        async with sem:
            return await get(f"/api/company/{cnpj}/leads", params=params, timeout=180.0)

    results = await asyncio.gather(*(fetch(c) for c in cnpjs), return_exceptions=True)

    base = LeadBase(name=name, source="CAPIBLU", status="PROCESSING",
                    client_id=payload.get("clientId"),
                    created_by_id=payload.get("createdById"),
                    source_query=json.dumps({"cnpjs": cnpjs, "params": params,
                                             "filtros": payload.get("filtros") or {}},
                                            ensure_ascii=False))
    db.add(base)
    db.flush()

    imported = discarded = 0
    failures: list[str] = []
    sem_decisor: list[dict] = []
    defaults = {"cadenceId": cadence_id, "sdrId": payload.get("sdrId"),
                "clientId": payload.get("clientId"), "leadBaseId": base.id}
    from .flow import _build_lead

    for cnpj, res in zip(cnpjs, results):
        if isinstance(res, Exception):
            failures.append(f"{cnpj}: {type(res).__name__}")
            continue
        code, data = res
        if code >= 400 or data.get("status") not in ("ok", None):
            failures.append(f"{cnpj}: {data.get('message') or data.get('status') or code}")
            continue
        company = data.get("empresa") or {}
        contacts = data.get("contatos") or []
        # `decisores_info` é a explicação do CapiBLU para "por que vieram zero
        # decisores" — sem ela o usuário só vê a lista curta e não entende.
        info = data.get("decisores_info")
        if info and not info.get("encontrados"):
            sem_decisor.append({"cnpj": cnpj,
                                "razaoSocial": company.get("razao_social", ""),
                                "motivo": info.get("motivo") or info.get("aviso") or ""})
        if not contacts:
            discarded += 1
            continue
        for contact in contacts:
            row = _contact_to_lead(company, contact)
            if not row["name"]:
                discarded += 1
                continue
            lead = _build_lead(db, row, defaults)
            lead.lead_base_id = base.id
            db.add(lead)
            db.flush()
            if cadence_id:
                _schedule_cadence(db, lead)
            imported += 1

    base.number_of_leads = imported
    base.discarded_leads = discarded
    base.status = "COMPLETED" if imported else "FAILED"
    db.commit()
    return {"leadBase": serial.lead_base(base), "imported": imported,
            "discarded": discarded, "failures": failures[:20],
            "failureCount": len(failures),
            "semDecisor": sem_decisor[:20], "semDecisorCount": len(sem_decisor)}


@router.post("/leads/{lid}/enrich")
async def enrich_lead(lid: int, db: Session = Depends(get_db)):
    """Enriquece um lead existente com o que o CapiBLU sabe do CNPJ dele."""
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    if not lead.cnpj:
        raise HTTPException(400, "O lead não tem CNPJ para consultar.")
    code, data = await get(f"/api/company/{lead.cnpj}/leads",
                           params={"decisores": True, "max_decisores": 5}, timeout=180.0)
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha ao enriquecer."))
    company = data.get("empresa") or {}
    contacts = data.get("contatos") or []
    changed = []
    if not lead.razao_social and company.get("razao_social"):
        lead.razao_social = company["razao_social"]
        changed.append("razaoSocial")
    for attr, key in [("city", "municipio"), ("state", "uf")]:
        if not getattr(lead, attr) and company.get(key):
            setattr(lead, attr, company[key])
            changed.append(attr)
    mine = next((c for c in contacts if c.get("cpf") and c["cpf"] == lead.cpf),
                contacts[0] if contacts else None)
    if mine:
        phones = [t.get("display") or t.get("raw") for t in (mine.get("telefones") or [])]
        if phones and not lead.phone:
            lead.phone = " / ".join(p for p in phones if p)
            changed.append("phone")
        emails = mine.get("emails") or []
        if emails and not lead.email:
            lead.email = emails[0]
            changed.append("email")
        if mine.get("cargo") and not lead.position:
            lead.position = mine["cargo"]
            changed.append("position")
    db.commit()
    return {"lead": serial.lead(lead), "updated": changed,
            "company": company, "contacts": contacts}


@router.post("/leads/{lid}/validate-phone")
async def validate_phone(lid: int, db: Session = Depends(get_db)):
    lead = db.get(Lead, lid)
    if not lead:
        raise HTTPException(404, "Lead não encontrado.")
    doc = lead.cpf or lead.cnpj
    number = (lead.phone or "").split("/")[0].strip()
    if not doc or not number:
        raise HTTPException(400, "O lead precisa de telefone e de CPF/CNPJ.")
    digits = "".join(ch for ch in number if ch.isdigit())[-11:]
    code, data = await get(f"/api/phone/{digits}/pertence/{doc}")
    if code >= 400:
        raise HTTPException(code, data.get("detail", "Falha na validação."))
    return data


@router.post("/dedup")
async def dedup(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Marca quais CNPJs da lista já existem como lead aqui dentro."""
    cnpjs = {"".join(ch for ch in str(c) if ch.isdigit()) for c in payload.get("cnpjs") or []}
    if not cnpjs:
        return {"existing": [], "new": []}
    rows = db.query(Lead.cnpj, Lead.name, Lead.status).filter(Lead.cnpj.in_(cnpjs)).all()
    existing = {r[0] for r in rows}
    return {"existing": [{"cnpj": c, "name": n, "status": s} for c, n, s in rows],
            "new": sorted(cnpjs - existing),
            "meta": {"checked": len(cnpjs), "duplicates": len(existing)}}
