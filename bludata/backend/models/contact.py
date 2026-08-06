from pydantic import BaseModel
from typing import Optional, List


class ContactRecord(BaseModel):
    contact_id: str
    person_id: Optional[str] = None
    type: str  # email, mobile, landline, corporate_landline
    value: str
    status: Optional[str] = None  # valid, invalid, unknown
    classification: Optional[str] = None
    whatsapp: Optional[bool] = None
    whatsapp_datetime: Optional[str] = None
    priority: Optional[int] = None
    source: str = "database"


class ContactInfoResponse(BaseModel):
    sucesso: bool = True
    person_id: Optional[str] = None
    cpf: Optional[str] = None
    emails: List[ContactRecord] = []
    landlines: List[ContactRecord] = []
    mobile_phones: List[ContactRecord] = []
    corporate_landlines: List[ContactRecord] = []


class EnrichRequest(BaseModel):
    pessoas: List[dict]  # [{id_pessoa, cpf, linkedin_url}]
    url_webhook: Optional[str] = None


class JobStatusResponse(BaseModel):
    job_id: str
    status: str  # in_progress, completed, failed
    total: Optional[int] = None
    processed: Optional[int] = None
    result: Optional[dict] = None
    created_at: Optional[str] = None
    completed_at: Optional[str] = None
