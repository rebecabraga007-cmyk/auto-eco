from pydantic import BaseModel
from typing import Optional, List


class CompanyRecord(BaseModel):
    company_id: str
    cnpj: Optional[str] = None
    name: str
    trade_name: Optional[str] = None
    sector: Optional[str] = None
    cnae_code: Optional[str] = None
    cnae_desc: Optional[str] = None
    location: Optional[str] = None
    state: Optional[str] = None
    zip_code: Optional[str] = None
    employee_range: Optional[str] = None
    revenue_range: Optional[str] = None
    founded_at: Optional[str] = None
    legal_nature: Optional[str] = None
    simples_nacional: Optional[bool] = None
    mei: Optional[bool] = None
    phone: Optional[str] = None
    email: Optional[str] = None
    website: Optional[str] = None
    partners: Optional[List[dict]] = None
    source: str = "database"


class CompanySearchRequest(BaseModel):
    page: int = 1
    per_page: int = 20
    cache_key: Optional[str] = None
    company_name: List[str] = []
    locations: List[str] = []
    states: List[str] = []
    sectors: List[str] = []
    cnae_activities: List[str] = []
    company_sizes: List[str] = []
    legal_natures: List[str] = []
    foundation_date: Optional[str] = None
    revenue_range: Optional[str] = None
    include_mei: Optional[bool] = None
    has_cnpj: Optional[bool] = None


class CompanySearchResponse(BaseModel):
    sucesso: bool = True
    dados: List[CompanyRecord]
    total: int
    chave_cache: str
    page: int
    credits_used: int = 0
