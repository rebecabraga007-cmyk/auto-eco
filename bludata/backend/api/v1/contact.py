"""GET /v1/person/contact/info/ — return contacts for a person."""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from models.contact import ContactRecord, ContactInfoResponse
from db.database import PersonDB, ContactDB, get_sync_session

router = APIRouter()


@router.get("/person/contact/info/", response_model=ContactInfoResponse)
def get_contact_info(
    cpf: str = None,
    person_id: str = None,
    cnpj: str = None,
    db: Session = Depends(get_sync_session),
):
    if not cpf and not person_id:
        raise HTTPException(status_code=400, detail="Forneça cpf ou person_id")

    # Find person
    q = db.query(PersonDB)
    if person_id:
        q = q.filter(PersonDB.person_id == person_id)
    elif cpf:
        cpf_clean = "".join(filter(str.isdigit, cpf))
        q = q.filter(PersonDB.cpf == cpf_clean)

    person = q.first()

    resolved_person_id = person.person_id if person else person_id

    # Fetch contacts from DB
    contacts = db.query(ContactDB).filter(ContactDB.person_id == resolved_person_id).all()

    emails = []
    landlines = []
    mobile_phones = []
    corporate_landlines = []

    for c in contacts:
        rec = ContactRecord(
            contact_id=c.contact_id,
            person_id=c.person_id,
            type=c.type,
            value=c.value,
            status=c.status,
            classification=c.classification,
            whatsapp=c.whatsapp,
            whatsapp_datetime=c.whatsapp_datetime,
            priority=c.priority,
            source=c.source or "database",
        )
        if c.type == "email":
            emails.append(rec)
        elif c.type == "mobile":
            mobile_phones.append(rec)
        elif c.type == "landline":
            landlines.append(rec)
        elif c.type == "corporate_landline":
            corporate_landlines.append(rec)

    # NOTE: Real phone numbers come from an external API not yet configured.
    # Placeholder is returned when no contacts exist in DB.
    if not contacts:
        placeholder = ContactRecord(
            contact_id="placeholder",
            person_id=resolved_person_id,
            type="mobile",
            value="[API externa de telefones não configurada]",
            status="unknown",
            source="placeholder",
        )
        mobile_phones = [placeholder]

    return ContactInfoResponse(
        sucesso=True,
        person_id=resolved_person_id,
        cpf=cpf,
        emails=emails,
        landlines=landlines,
        mobile_phones=mobile_phones,
        corporate_landlines=corporate_landlines,
    )
