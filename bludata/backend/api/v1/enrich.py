"""
POST /v1/b2b/persons/enrich/bulk — bulk enrich persons asynchronously.
GET  /v1/b2b/waterfall/job/       — check job status.
"""
import uuid
import json
import asyncio
import httpx
from datetime import datetime
from fastapi import APIRouter, Depends, BackgroundTasks, HTTPException
from sqlalchemy.orm import Session

from models.contact import EnrichRequest, JobStatusResponse
from db.database import JobDB, PersonDB, ContactDB, get_sync_session, SyncSessionLocal
from scrapers.linkedin import scrape_linkedin_profile
from scrapers.brasil_api import fetch_cnpj, parse_brasilapi_cnpj

router = APIRouter()


async def _do_enrich(job_id: str, pessoas: list, url_webhook: str = None):
    """Background task: enrich each person and update job."""
    db = SyncSessionLocal()
    try:
        job = db.query(JobDB).filter(JobDB.job_id == job_id).first()
        if not job:
            return

        job.total = len(pessoas)
        job.status = "in_progress"
        db.commit()

        results = []
        for i, p in enumerate(pessoas):
            person_result = {"input": p, "enriched": {}}

            pid = p.get("id_pessoa") or p.get("person_id")
            cpf = p.get("cpf")
            linkedin_url = p.get("linkedin_url", "")

            # Try to enrich from LinkedIn if URL provided
            if linkedin_url:
                slug = linkedin_url.rstrip("/").split("/")[-1]
                li_result = await scrape_linkedin_profile(slug)
                person_result["linkedin"] = li_result

            # Update DB person record with enriched data
            if pid:
                person = db.query(PersonDB).filter(PersonDB.person_id == pid).first()
                if person and linkedin_url:
                    person.linkedin_url = linkedin_url
                    person.has_linkedin = True
                    db.commit()

            results.append(person_result)

            # Update progress
            job.processed = i + 1
            db.commit()

            # Polite delay between requests
            await asyncio.sleep(0.5)

        job.status = "completed"
        job.result = json.dumps(results)
        job.completed_at = datetime.utcnow()
        db.commit()

        # Fire webhook if provided
        if url_webhook:
            try:
                async with httpx.AsyncClient(timeout=15) as client:
                    await client.post(url_webhook, json={
                        "job_id": job_id,
                        "status": "completed",
                        "total": len(pessoas),
                        "results": results,
                    })
            except Exception as e:
                print(f"[bludata] Webhook delivery failed: {e}")

    except Exception as e:
        db_job = db.query(JobDB).filter(JobDB.job_id == job_id).first()
        if db_job:
            db_job.status = "failed"
            db_job.result = json.dumps({"error": str(e)})
            db_job.completed_at = datetime.utcnow()
            db.commit()
    finally:
        db.close()


@router.post("/b2b/persons/enrich/bulk")
async def enrich_bulk(
    body: EnrichRequest,
    background_tasks: BackgroundTasks,
    db: Session = Depends(get_sync_session),
):
    job_id = str(uuid.uuid4())

    job = JobDB(
        job_id=job_id,
        type="enrich_bulk",
        status="in_progress",
        payload=json.dumps(body.model_dump()),
        total=len(body.pessoas),
        processed=0,
    )
    db.add(job)
    db.commit()

    background_tasks.add_task(_do_enrich, job_id, body.pessoas, body.url_webhook)

    return {
        "sucesso": True,
        "job_id": job_id,
        "status": "in_progress",
        "total": len(body.pessoas),
        "message": "Job iniciado. Use GET /v1/b2b/waterfall/job/?validationJobId={job_id} para acompanhar.",
    }


@router.get("/b2b/waterfall/job/", response_model=JobStatusResponse)
def get_job_status(
    validationJobId: str = None,
    waterfallJobId: str = None,
    linkedinJobId: str = None,
    db: Session = Depends(get_sync_session),
):
    job_id = validationJobId or waterfallJobId or linkedinJobId
    if not job_id:
        raise HTTPException(status_code=400, detail="Forneça validationJobId, waterfallJobId ou linkedinJobId")

    job = db.query(JobDB).filter(JobDB.job_id == job_id).first()
    if not job:
        raise HTTPException(status_code=404, detail="Job não encontrado")

    result = None
    if job.result:
        try:
            result = json.loads(job.result)
        except Exception:
            result = {"raw": job.result}

    return JobStatusResponse(
        job_id=job.job_id,
        status=job.status,
        total=job.total,
        processed=job.processed,
        result=result,
        created_at=job.created_at.isoformat() if job.created_at else None,
        completed_at=job.completed_at.isoformat() if job.completed_at else None,
    )
