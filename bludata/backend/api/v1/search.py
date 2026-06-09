"""GET /v1/b2b/search/ — autocomplete endpoint."""
from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from sqlalchemy import or_

from db.database import PersonDB, CompanyDB, get_sync_session
from scrapers.brasil_api import fetch_municipios

router = APIRouter()

# Static autocomplete data for dropdowns
SECTORS = [
    "Tecnologia da Informação", "Bancos", "Seguros", "Varejo", "Saúde",
    "Educação", "Construção Civil", "Agronegócio", "Manufatura",
    "Logística e Transporte", "Consultoria", "Serviços Financeiros",
    "Telecomunicações", "Energia", "Mineração", "Alimentos e Bebidas",
    "Farmacêutico", "Automotivo", "Imóveis", "Turismo e Hospitalidade",
    "Extração de Petróleo e Gás Natural", "Comércio varejista",
]

SENIORITY_LEVELS = [
    "Decisores", "C-Level", "Diretor", "Gerente", "Coordenador",
    "Supervisor", "Analista Sênior", "Analista Pleno", "Analista Júnior",
    "Especialista", "Consultor", "Estágio",
]

DEPARTMENTS = [
    "TI", "Tecnologia", "Engenharia", "Marketing", "Vendas", "Comercial",
    "Financeiro", "Recursos Humanos", "Operações", "Jurídico", "Produto",
    "Diretoria", "Estratégia", "Compras", "Logística", "Produção",
]

ROLES = [
    "CEO", "CTO", "CFO", "COO", "CMO", "CISO", "CRO",
    "Diretor de TI", "Diretor Comercial", "Diretor Financeiro", "Diretor de Operações",
    "Gerente de TI", "Gerente Comercial", "Gerente de Marketing", "Gerente de Produto",
    "Head de Tecnologia", "Head de Marketing", "Head de Vendas",
    "Analista de Sistemas", "Desenvolvedor", "Engenheiro de Software",
    "Product Manager", "Scrum Master", "Arquiteto de Soluções",
]

STATES = [
    "AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO",
    "MA", "MT", "MS", "MG", "PA", "PB", "PR", "PE", "PI",
    "RJ", "RN", "RS", "RO", "RR", "SC", "SP", "SE", "TO",
]

SKILLS = [
    "Python", "Java", "JavaScript", "TypeScript", "React", "Node.js",
    "SQL", "AWS", "Azure", "GCP", "Docker", "Kubernetes", "Machine Learning",
    "Data Science", "Power BI", "Tableau", "SAP", "Salesforce",
    "Gestão de Projetos", "Scrum", "Agile", "ITIL",
]


@router.get("/b2b/search/")
async def autocomplete(
    termo: str = Query("", description="Termo de busca"),
    campo: str = Query("nome_empresa", description="Campo: nome_empresa, localizacao, setor, especialidade, atividade_cnae, cargo, habilidade, estado"),
    db: Session = Depends(get_sync_session),
):
    termo_lower = termo.lower().strip()
    results = []

    if campo == "nome_empresa":
        rows = db.query(CompanyDB.name, CompanyDB.trade_name, CompanyDB.company_id).filter(
            or_(
                CompanyDB.name.ilike(f"%{termo}%"),
                CompanyDB.trade_name.ilike(f"%{termo}%"),
            )
        ).limit(20).all()
        for r in rows:
            results.append({
                "value": r.company_id,
                "label": r.trade_name or r.name,
                "sublabel": r.name,
            })

    elif campo == "localizacao":
        rows = db.query(PersonDB.location, PersonDB.state).filter(
            PersonDB.location.ilike(f"%{termo}%")
        ).distinct().limit(20).all()
        seen = set()
        for r in rows:
            if r.location and r.location not in seen:
                seen.add(r.location)
                results.append({"value": r.location, "label": r.location})

    elif campo == "setor":
        filtered = [s for s in SECTORS if termo_lower in s.lower()]
        results = [{"value": s, "label": s} for s in filtered[:20]]

    elif campo == "especialidade" or campo == "habilidade":
        filtered = [s for s in SKILLS if termo_lower in s.lower()]
        results = [{"value": s, "label": s} for s in filtered[:20]]

    elif campo == "cargo":
        filtered = [r for r in ROLES if termo_lower in r.lower()]
        results = [{"value": r, "label": r} for r in filtered[:20]]

        # Also search DB
        db_rows = db.query(PersonDB.role).filter(
            PersonDB.role.ilike(f"%{termo}%")
        ).distinct().limit(10).all()
        seen_labels = {r["label"] for r in results}
        for row in db_rows:
            if row.role and row.role not in seen_labels:
                results.append({"value": row.role, "label": row.role})
                seen_labels.add(row.role)

    elif campo == "atividade_cnae":
        rows = db.query(CompanyDB.cnae_code, CompanyDB.cnae_desc).filter(
            or_(
                CompanyDB.cnae_code.ilike(f"%{termo}%"),
                CompanyDB.cnae_desc.ilike(f"%{termo}%"),
            )
        ).distinct().limit(20).all()
        for r in rows:
            if r.cnae_code:
                results.append({
                    "value": r.cnae_code,
                    "label": f"{r.cnae_code} — {r.cnae_desc or ''}",
                })

    elif campo == "estado":
        filtered = [s for s in STATES if termo_lower in s.lower()]
        results = [{"value": s, "label": s} for s in filtered[:27]]

    elif campo == "nivel_senioridade":
        filtered = [s for s in SENIORITY_LEVELS if termo_lower in s.lower()]
        results = [{"value": s, "label": s} for s in filtered[:20]]

    elif campo == "departamento":
        filtered = [d for d in DEPARTMENTS if termo_lower in d.lower()]
        results = [{"value": d, "label": d} for d in filtered[:20]]

    return {
        "sucesso": True,
        "campo": campo,
        "termo": termo,
        "total": len(results),
        "resultados": results,
    }
