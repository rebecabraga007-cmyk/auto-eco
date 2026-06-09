"""POST /v1/b2b/companies/ — search companies with filters."""
import uuid
import json
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_

from models.company import CompanySearchRequest, CompanySearchResponse, CompanyRecord
from db.database import CompanyDB, CacheKeyDB, get_sync_session
from scrapers.brasil_api import fetch_cnpj, parse_brasilapi_cnpj
from scrapers.receita_federal import fetch_receitaws, parse_receitaws

router = APIRouter()


@router.post("/b2b/companies/", response_model=CompanySearchResponse)
def search_companies(
    body: CompanySearchRequest,
    db: Session = Depends(get_sync_session),
):
    is_first_call = body.cache_key is None
    credits_used = 1 if is_first_call else 0

    if body.cache_key:
        cache_key = body.cache_key
        ck = db.query(CacheKeyDB).filter(CacheKeyDB.cache_key == body.cache_key).first()
        if not ck:
            raise HTTPException(status_code=400, detail="cache_key inválida ou expirada")
    else:
        cache_key = str(uuid.uuid4())
        ck = CacheKeyDB(cache_key=cache_key, query_hash=str(hash(str(body.model_dump()))), account_id="demo")
        db.add(ck)
        db.commit()

    query = db.query(CompanyDB)

    if body.company_name:
        conditions = [CompanyDB.name.ilike(f"%{n}%") for n in body.company_name]
        conditions += [CompanyDB.trade_name.ilike(f"%{n}%") for n in body.company_name]
        query = query.filter(or_(*conditions))

    if body.locations:
        conditions = [CompanyDB.location.ilike(f"%{loc}%") for loc in body.locations]
        query = query.filter(or_(*conditions))

    if body.states:
        query = query.filter(CompanyDB.state.in_([s.upper() for s in body.states]))

    if body.sectors:
        conditions = [CompanyDB.sector.ilike(f"%{s}%") for s in body.sectors]
        query = query.filter(or_(*conditions))

    if body.cnae_activities:
        conditions = [CompanyDB.cnae_code.ilike(f"%{c}%") for c in body.cnae_activities]
        conditions += [CompanyDB.cnae_desc.ilike(f"%{c}%") for c in body.cnae_activities]
        query = query.filter(or_(*conditions))

    if body.company_sizes:
        conditions = [CompanyDB.employee_range.ilike(f"%{s}%") for s in body.company_sizes]
        query = query.filter(or_(*conditions))

    if body.legal_natures:
        conditions = [CompanyDB.legal_nature.ilike(f"%{ln}%") for ln in body.legal_natures]
        query = query.filter(or_(*conditions))

    if body.include_mei is not None:
        query = query.filter(CompanyDB.mei == body.include_mei)

    total = query.count()
    offset = (body.page - 1) * body.per_page
    rows = query.offset(offset).limit(body.per_page).all()

    dados = []
    for r in rows:
        partners = None
        if r.partners_json:
            try:
                partners = json.loads(r.partners_json)
            except Exception:
                partners = None

        dados.append(CompanyRecord(
            company_id=r.company_id,
            cnpj=r.cnpj,
            name=r.name,
            trade_name=r.trade_name,
            sector=r.sector,
            cnae_code=r.cnae_code,
            cnae_desc=r.cnae_desc,
            location=r.location,
            state=r.state,
            zip_code=r.zip_code,
            employee_range=r.employee_range,
            revenue_range=r.revenue_range,
            founded_at=r.founded_at,
            legal_nature=r.legal_nature,
            simples_nacional=r.simples_nacional,
            mei=r.mei,
            phone=r.phone,
            email=r.email,
            website=r.website,
            partners=partners,
            source=r.source or "database",
        ))

    return CompanySearchResponse(
        sucesso=True,
        dados=dados,
        total=total,
        chave_cache=cache_key,
        page=body.page,
        credits_used=credits_used,
    )


@router.get("/company/info/")
async def get_company_info(
    cnpj: str = None,
    company_id: str = None,
    db: Session = Depends(get_sync_session),
):
    if not cnpj and not company_id:
        raise HTTPException(status_code=400, detail="Forneça cnpj ou company_id")

    # Try DB first
    q = db.query(CompanyDB)
    if company_id:
        q = q.filter(CompanyDB.company_id == company_id)
    elif cnpj:
        cnpj_clean = "".join(filter(str.isdigit, cnpj))
        q = q.filter(CompanyDB.cnpj == cnpj_clean)

    c = q.first()

    if c:
        partners = None
        if c.partners_json:
            try:
                partners = json.loads(c.partners_json)
            except Exception:
                pass
        return {
            "sucesso": True,
            "source": "database",
            "data": CompanyRecord(
                company_id=c.company_id, cnpj=c.cnpj, name=c.name,
                trade_name=c.trade_name, sector=c.sector, cnae_code=c.cnae_code,
                cnae_desc=c.cnae_desc, location=c.location, state=c.state,
                zip_code=c.zip_code, employee_range=c.employee_range,
                revenue_range=c.revenue_range, founded_at=c.founded_at,
                legal_nature=c.legal_nature, simples_nacional=c.simples_nacional,
                mei=c.mei, phone=c.phone, email=c.email, website=c.website,
                partners=partners, source=c.source or "database",
            ).model_dump()
        }

    # Not in DB — fetch from external APIs
    if cnpj:
        cnpj_clean = "".join(filter(str.isdigit, cnpj))

        # Try BrasilAPI first
        result = await fetch_cnpj(cnpj_clean)
        if result["sucesso"]:
            normalized = parse_brasilapi_cnpj(result)
            if normalized:
                return {"sucesso": True, "source": "brasilapi", "data": normalized}

        # Fallback to ReceitaWS
        result = await fetch_receitaws(cnpj_clean)
        if result["sucesso"]:
            normalized = parse_receitaws(result)
            if normalized:
                return {"sucesso": True, "source": "receitaws", "data": normalized}

        return {"sucesso": False, "error": "Empresa não encontrada em nenhuma fonte", "cnpj": cnpj_clean}

    raise HTTPException(status_code=404, detail="Empresa não encontrada")
