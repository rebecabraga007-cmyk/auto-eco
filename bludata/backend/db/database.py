import uuid
import json
from datetime import datetime
from sqlalchemy import (
    create_engine, Column, String, Boolean, DateTime, Text, Integer, Float
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.orm import sessionmaker
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import DeclarativeBase

DATABASE_URL = "sqlite+aiosqlite:///./bludata.db"
SYNC_DATABASE_URL = "sqlite:///./bludata.db"

sync_engine = create_engine(SYNC_DATABASE_URL, connect_args={"check_same_thread": False})
async_engine = create_async_engine(DATABASE_URL, connect_args={"check_same_thread": False})

AsyncSessionLocal = sessionmaker(async_engine, class_=AsyncSession, expire_on_commit=False)
SyncSessionLocal = sessionmaker(sync_engine)


class Base(DeclarativeBase):
    pass


class PersonDB(Base):
    __tablename__ = "persons"

    person_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    name = Column(String, nullable=False)
    cpf = Column(String, nullable=True)
    company_id = Column(String, nullable=True)
    company_name = Column(String, nullable=True)
    role = Column(String, nullable=True)
    department = Column(String, nullable=True)
    seniority = Column(String, nullable=True)
    location = Column(String, nullable=True)
    state = Column(String, nullable=True)
    has_email = Column(Boolean, default=False)
    has_phone = Column(Boolean, default=False)
    has_linkedin = Column(Boolean, default=False)
    linkedin_url = Column(String, nullable=True)
    source = Column(String, default="database")
    created_at = Column(DateTime, default=datetime.utcnow)
    updated_at = Column(DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)


class CompanyDB(Base):
    __tablename__ = "companies"

    company_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    cnpj = Column(String, nullable=True)
    name = Column(String, nullable=False)
    trade_name = Column(String, nullable=True)
    sector = Column(String, nullable=True)
    location = Column(String, nullable=True)
    state = Column(String, nullable=True)
    zip_code = Column(String, nullable=True)
    employee_range = Column(String, nullable=True)
    revenue_range = Column(String, nullable=True)
    founded_at = Column(String, nullable=True)
    cnae_code = Column(String, nullable=True)
    cnae_desc = Column(String, nullable=True)
    legal_nature = Column(String, nullable=True)
    simples_nacional = Column(Boolean, nullable=True)
    mei = Column(Boolean, nullable=True)
    phone = Column(String, nullable=True)
    email = Column(String, nullable=True)
    website = Column(String, nullable=True)
    partners_json = Column(Text, nullable=True)
    source = Column(String, default="database")
    created_at = Column(DateTime, default=datetime.utcnow)


class ContactDB(Base):
    __tablename__ = "contacts"

    contact_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    person_id = Column(String, nullable=True)
    type = Column(String, nullable=False)  # email, mobile, landline, corporate_landline
    value = Column(String, nullable=False)
    status = Column(String, nullable=True)
    classification = Column(String, nullable=True)
    whatsapp = Column(Boolean, nullable=True)
    whatsapp_datetime = Column(String, nullable=True)
    priority = Column(Integer, nullable=True)
    source = Column(String, default="database")
    created_at = Column(DateTime, default=datetime.utcnow)


class JobDB(Base):
    __tablename__ = "jobs"

    job_id = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    type = Column(String, nullable=False)
    status = Column(String, default="in_progress")  # in_progress, completed, failed
    payload = Column(Text, nullable=True)
    result = Column(Text, nullable=True)
    total = Column(Integer, default=0)
    processed = Column(Integer, default=0)
    created_at = Column(DateTime, default=datetime.utcnow)
    completed_at = Column(DateTime, nullable=True)


class CacheKeyDB(Base):
    __tablename__ = "cache_keys"

    cache_key = Column(String, primary_key=True, default=lambda: str(uuid.uuid4()))
    query_hash = Column(String, nullable=True)
    account_id = Column(String, nullable=True)
    created_at = Column(DateTime, default=datetime.utcnow)
    expires_at = Column(DateTime, nullable=True)


def create_tables():
    Base.metadata.create_all(bind=sync_engine)


def get_sync_session():
    db = SyncSessionLocal()
    try:
        yield db
    finally:
        db.close()


async def get_async_session():
    async with AsyncSessionLocal() as session:
        yield session


def seed_database():
    """Populate DB with sample data from public sources."""
    from datetime import timedelta

    db = SyncSessionLocal()
    try:
        # Check if already seeded
        if db.query(CompanyDB).count() > 0:
            return

        companies_data = [
            {
                "company_id": str(uuid.uuid4()),
                "cnpj": "33000167000101",
                "name": "PETROLEO BRASILEIRO S.A. - PETROBRAS",
                "trade_name": "PETROBRAS",
                "sector": "Extração de Petróleo e Gás Natural",
                "location": "Rio de Janeiro, RJ",
                "state": "RJ",
                "zip_code": "20231030",
                "employee_range": "Mais de 1000",
                "revenue_range": "Acima de R$ 300M",
                "founded_at": "1953-10-03",
                "cnae_code": "0600-0/01",
                "cnae_desc": "Extração de petróleo e gás natural",
                "legal_nature": "Sociedade de Economia Mista",
                "simples_nacional": False,
                "mei": False,
                "phone": "(21) 3224-4477",
                "email": "relacionamento@petrobras.com.br",
                "website": "https://petrobras.com.br",
                "source": "brasilapi",
            },
            {
                "company_id": str(uuid.uuid4()),
                "cnpj": "60701190000104",
                "name": "ITAU UNIBANCO S.A.",
                "trade_name": "ITAÚ UNIBANCO",
                "sector": "Bancos",
                "location": "São Paulo, SP",
                "state": "SP",
                "zip_code": "04344902",
                "employee_range": "Mais de 1000",
                "revenue_range": "Acima de R$ 300M",
                "founded_at": "1944-09-09",
                "cnae_code": "6422-1/00",
                "cnae_desc": "Bancos múltiplos, com carteira comercial",
                "legal_nature": "Sociedade Anônima Aberta",
                "simples_nacional": False,
                "mei": False,
                "phone": "(11) 2794-1900",
                "email": "relacoes.investidores@itau-unibanco.com.br",
                "website": "https://www.itau.com.br",
                "source": "brasilapi",
            },
            {
                "company_id": str(uuid.uuid4()),
                "cnpj": "07206816000115",
                "name": "LOCALIZA RENT A CAR S.A.",
                "trade_name": "LOCALIZA",
                "sector": "Aluguel de automóveis",
                "location": "Belo Horizonte, MG",
                "state": "MG",
                "zip_code": "30110021",
                "employee_range": "1001-5000",
                "revenue_range": "R$ 10M - R$ 100M",
                "founded_at": "1973-08-17",
                "cnae_code": "7711-0/00",
                "cnae_desc": "Locação de automóveis sem condutor",
                "legal_nature": "Sociedade Anônima Aberta",
                "simples_nacional": False,
                "mei": False,
                "phone": "(31) 3247-7000",
                "email": "ri@localiza.com",
                "website": "https://www.localiza.com",
                "source": "brasilapi",
            },
            {
                "company_id": str(uuid.uuid4()),
                "cnpj": "47866386000195",
                "name": "MAGAZINE LUIZA S.A.",
                "trade_name": "MAGALU",
                "sector": "Comércio varejista",
                "location": "Franca, SP",
                "state": "SP",
                "zip_code": "14400280",
                "employee_range": "Mais de 1000",
                "revenue_range": "Acima de R$ 300M",
                "founded_at": "1957-09-07",
                "cnae_code": "4753-9/00",
                "cnae_desc": "Comércio varejista especializado de eletrodomésticos",
                "legal_nature": "Sociedade Anônima Aberta",
                "simples_nacional": False,
                "mei": False,
                "phone": "(11) 3504-2000",
                "email": "ri@magazineluiza.com.br",
                "website": "https://www.magazineluiza.com.br",
                "source": "brasilapi",
            },
            {
                "company_id": str(uuid.uuid4()),
                "cnpj": "09346601000125",
                "name": "NUBANK - NU PAGAMENTOS S.A.",
                "trade_name": "NUBANK",
                "sector": "Fintech / Serviços Financeiros",
                "location": "São Paulo, SP",
                "state": "SP",
                "zip_code": "04571010",
                "employee_range": "Mais de 1000",
                "revenue_range": "Acima de R$ 300M",
                "founded_at": "2013-05-06",
                "cnae_code": "6499-3/01",
                "cnae_desc": "Outras atividades de serviços financeiros",
                "legal_nature": "Sociedade Anônima Fechada",
                "simples_nacional": False,
                "mei": False,
                "phone": "(11) 4858-7777",
                "email": "imprensa@nubank.com.br",
                "website": "https://nubank.com.br",
                "source": "brasilapi",
            },
        ]

        company_ids = {}
        for c in companies_data:
            cid = c["company_id"]
            company_ids[c["name"]] = cid
            obj = CompanyDB(**c)
            db.add(obj)

        persons_data = [
            {
                "person_id": str(uuid.uuid4()),
                "name": "Carlos Alberto Silva",
                "company_name": "PETROBRAS",
                "role": "Diretor de Operações",
                "department": "Operações",
                "seniority": "Decisor",
                "location": "Rio de Janeiro, RJ",
                "state": "RJ",
                "has_email": True,
                "has_phone": True,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/carlossilva",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Ana Paula Ferreira",
                "company_name": "ITAÚ UNIBANCO",
                "role": "Gerente de Tecnologia",
                "department": "TI",
                "seniority": "Gerente",
                "location": "São Paulo, SP",
                "state": "SP",
                "has_email": True,
                "has_phone": False,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/anapaulaferreira",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Roberto Mendes Costa",
                "company_name": "LOCALIZA",
                "role": "CEO",
                "department": "Diretoria",
                "seniority": "Decisor",
                "location": "Belo Horizonte, MG",
                "state": "MG",
                "has_email": True,
                "has_phone": True,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/robertomendes",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Mariana Oliveira Santos",
                "company_name": "MAGALU",
                "role": "Head de Marketing",
                "department": "Marketing",
                "seniority": "Gerente",
                "location": "São Paulo, SP",
                "state": "SP",
                "has_email": True,
                "has_phone": True,
                "has_linkedin": False,
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Felipe Rodrigues Lima",
                "company_name": "NUBANK",
                "role": "CTO",
                "department": "Tecnologia",
                "seniority": "Decisor",
                "location": "São Paulo, SP",
                "state": "SP",
                "has_email": True,
                "has_phone": False,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/felipelima-tech",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Juliana Pereira Alves",
                "company_name": "PETROBRAS",
                "role": "Analista de Engenharia Sênior",
                "department": "Engenharia",
                "seniority": "Sênior",
                "location": "Rio de Janeiro, RJ",
                "state": "RJ",
                "has_email": False,
                "has_phone": True,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/julianaalves-eng",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Thiago Barbosa Nunes",
                "company_name": "ITAÚ UNIBANCO",
                "role": "Diretor Financeiro",
                "department": "Finanças",
                "seniority": "Decisor",
                "location": "São Paulo, SP",
                "state": "SP",
                "has_email": True,
                "has_phone": True,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/thiagobarbosa-fin",
                "source": "database",
            },
            {
                "person_id": str(uuid.uuid4()),
                "name": "Camila Souza Moreira",
                "company_name": "NUBANK",
                "role": "Product Manager",
                "department": "Produto",
                "seniority": "Pleno",
                "location": "São Paulo, SP",
                "state": "SP",
                "has_email": True,
                "has_phone": False,
                "has_linkedin": True,
                "linkedin_url": "https://linkedin.com/in/camilasouza-pm",
                "source": "database",
            },
        ]

        person_ids = []
        for p in persons_data:
            db.add(PersonDB(**p))
            person_ids.append(p["person_id"])

        db.commit()

        # Add sample contacts (placeholder — real phones come from external API)
        contacts_data = [
            {
                "contact_id": str(uuid.uuid4()),
                "person_id": person_ids[0],
                "type": "email",
                "value": "carlos.silva@petrobras.com.br",
                "status": "valid",
                "classification": "corporativo",
                "priority": 1,
                "source": "database",
            },
            {
                "contact_id": str(uuid.uuid4()),
                "person_id": person_ids[0],
                "type": "mobile",
                "value": "[PLACEHOLDER - API externa não configurada]",
                "status": "unknown",
                "whatsapp": None,
                "priority": 1,
                "source": "placeholder",
            },
            {
                "contact_id": str(uuid.uuid4()),
                "person_id": person_ids[1],
                "type": "email",
                "value": "ana.ferreira@itau-unibanco.com.br",
                "status": "valid",
                "classification": "corporativo",
                "priority": 1,
                "source": "database",
            },
            {
                "contact_id": str(uuid.uuid4()),
                "person_id": person_ids[2],
                "type": "email",
                "value": "roberto.mendes@localiza.com",
                "status": "valid",
                "classification": "corporativo",
                "priority": 1,
                "source": "database",
            },
        ]

        for c in contacts_data:
            db.add(ContactDB(**c))

        db.commit()
        print("[bludata] Database seeded with sample data.")

    except Exception as e:
        db.rollback()
        print(f"[bludata] Seed error: {e}")
    finally:
        db.close()
