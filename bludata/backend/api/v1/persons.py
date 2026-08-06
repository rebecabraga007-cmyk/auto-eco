"""POST /v1/b2b/persons/ — search persons with filters."""
import uuid
from datetime import datetime
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from sqlalchemy import or_, and_

from models.person import PersonSearchRequest, PersonSearchResponse, PersonRecord
from db.database import PersonDB, CacheKeyDB, get_sync_session

router = APIRouter()


@router.post("/b2b/persons/", response_model=PersonSearchResponse)
def search_persons(
    body: PersonSearchRequest,
    db: Session = Depends(get_sync_session),
):
    pf = body.person_filters
    cf = body.company_filters

    # Determine credit charge: first call (no cache_key) costs 1 credit
    is_first_call = body.cache_key is None
    credits_used = 1 if is_first_call else 0

    # Resolve or create cache key
    if body.cache_key:
        cache_key = body.cache_key
        # Validate cache key exists
        ck = db.query(CacheKeyDB).filter(CacheKeyDB.cache_key == body.cache_key).first()
        if not ck:
            raise HTTPException(status_code=400, detail="cache_key inválida ou expirada")
    else:
        cache_key = str(uuid.uuid4())  # UUID v4, never sequential
        ck = CacheKeyDB(
            cache_key=cache_key,
            query_hash=str(hash(str(body.model_dump()))),
            account_id="demo",
        )
        db.add(ck)
        db.commit()

    # Build query
    query = db.query(PersonDB)

    # Name filters
    if pf.name:
        conditions = [PersonDB.name.ilike(f"%{n}%") for n in pf.name]
        query = query.filter(or_(*conditions))

    if pf.surname:
        conditions = [PersonDB.name.ilike(f"%{s}%") for s in pf.surname]
        query = query.filter(or_(*conditions))

    # Role filters
    if pf.roles:
        conditions = [PersonDB.role.ilike(f"%{r}%") for r in pf.roles]
        query = query.filter(or_(*conditions))

    # Department filters
    if pf.departments:
        conditions = [PersonDB.department.ilike(f"%{d}%") for d in pf.departments]
        query = query.filter(or_(*conditions))

    # Seniority filters
    if pf.seniority_levels:
        conditions = [PersonDB.seniority.ilike(f"%{sl}%") for sl in pf.seniority_levels]
        query = query.filter(or_(*conditions))

    # Location filters
    if pf.locations:
        conditions = [PersonDB.location.ilike(f"%{loc}%") for loc in pf.locations]
        query = query.filter(or_(*conditions))

    # State filters
    if pf.states:
        query = query.filter(PersonDB.state.in_([s.upper() for s in pf.states]))

    # Contact flags
    if pf.has_email is not None:
        query = query.filter(PersonDB.has_email == pf.has_email)
    if pf.has_phone is not None:
        query = query.filter(PersonDB.has_phone == pf.has_phone)
    if pf.has_linkedin is not None:
        query = query.filter(PersonDB.has_linkedin == pf.has_linkedin)

    # Company filters
    if cf.company_name:
        conditions = [PersonDB.company_name.ilike(f"%{cn}%") for cn in cf.company_name]
        query = query.filter(or_(*conditions))

    if cf.states:
        query = query.filter(PersonDB.state.in_([s.upper() for s in cf.states]))

    total = query.count()

    offset = (body.page - 1) * body.per_page
    rows = query.offset(offset).limit(body.per_page).all()

    dados = []
    for r in rows:
        dados.append(PersonRecord(
            person_id=r.person_id,
            name=r.name,
            cpf=r.cpf,
            company_id=r.company_id,
            company_name=r.company_name,
            role=r.role,
            department=r.department,
            seniority=r.seniority,
            location=r.location,
            state=r.state,
            has_email=r.has_email or False,
            has_phone=r.has_phone or False,
            has_linkedin=r.has_linkedin or False,
            linkedin_url=r.linkedin_url,
            source=r.source or "database",
            created_at=r.created_at.isoformat() if r.created_at else None,
        ))

    return PersonSearchResponse(
        sucesso=True,
        dados=dados,
        total=total,
        chave_cache=cache_key,
        page=body.page,
        credits_used=credits_used,
    )


@router.get("/person/info/")
def get_person_info(
    cpf: str = None,
    person_id: str = None,
    db: Session = Depends(get_sync_session),
):
    if not cpf and not person_id:
        raise HTTPException(status_code=400, detail="Forneça cpf ou person_id")

    query = db.query(PersonDB)
    if person_id:
        query = query.filter(PersonDB.person_id == person_id)
    elif cpf:
        cpf_clean = "".join(filter(str.isdigit, cpf))
        query = query.filter(PersonDB.cpf == cpf_clean)

    p = query.first()
    if not p:
        raise HTTPException(status_code=404, detail="Pessoa não encontrada")

    return {
        "sucesso": True,
        "data": PersonRecord(
            person_id=p.person_id,
            name=p.name,
            cpf=p.cpf,
            company_id=p.company_id,
            company_name=p.company_name,
            role=p.role,
            department=p.department,
            seniority=p.seniority,
            location=p.location,
            state=p.state,
            has_email=p.has_email or False,
            has_phone=p.has_phone or False,
            has_linkedin=p.has_linkedin or False,
            linkedin_url=p.linkedin_url,
            source=p.source or "database",
            created_at=p.created_at.isoformat() if p.created_at else None,
        ).model_dump()
    }
