from pydantic import BaseModel, Field
from typing import Optional, List


class PersonFilters(BaseModel):
    name: List[str] = []
    surname: List[str] = []
    roles: List[str] = []
    departments: List[str] = []
    seniority_levels: List[str] = []
    skills: List[str] = []
    locations: List[str] = []
    states: List[str] = []
    has_email: Optional[bool] = None
    has_phone: Optional[bool] = None
    has_linkedin: Optional[bool] = None
    contact_lists: List[str] = []
    list_exclusion_filter: bool = False


class CompanyFilters(BaseModel):
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


class PersonSearchRequest(BaseModel):
    page: int = 1
    per_page: int = 20
    cache_key: Optional[str] = None
    person_filters: PersonFilters = Field(default_factory=PersonFilters)
    company_filters: CompanyFilters = Field(default_factory=CompanyFilters)


class PersonRecord(BaseModel):
    person_id: str
    name: str
    cpf: Optional[str] = None
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    role: Optional[str] = None
    department: Optional[str] = None
    seniority: Optional[str] = None
    location: Optional[str] = None
    state: Optional[str] = None
    has_email: bool = False
    has_phone: bool = False
    has_linkedin: bool = False
    linkedin_url: Optional[str] = None
    source: str = "database"
    created_at: Optional[str] = None


class PersonSearchResponse(BaseModel):
    sucesso: bool = True
    dados: List[PersonRecord]
    total: int
    chave_cache: str
    page: int
    credits_used: int = 0
