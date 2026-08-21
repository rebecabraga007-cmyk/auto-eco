"""Ligações: lista, estatísticas, extrato e click-to-call."""
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Call, Lead, User
from .. import serial

router = APIRouter(prefix="/api/dialer")

MINUTE_PRICE = 0.47  # R$/min — mesma ordem de grandeza do extrato Meetime


def _range(since: str | None, until: str | None) -> tuple[datetime, datetime]:
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end.replace(day=1, hour=0, minute=0)
    return start, end + timedelta(days=1) if until else end


@router.get("/calls")
def list_calls(user_id: int | None = None, status: str | None = None,
               output: str | None = None, lead_id: int | None = None,
               since: str | None = None, until: str | None = None,
               page: int = 1, limit: int = Query(50, le=500),
               db: Session = Depends(get_db)):
    start, end = _range(since, until)
    query = db.query(Call).filter(Call.started_at.between(start, end))
    if user_id:
        query = query.filter(Call.user_id == user_id)
    if status:
        query = query.filter(Call.status == status)
    if output:
        query = query.filter(Call.output == output)
    if lead_id:
        query = query.filter(Call.lead_id == lead_id)
    total = query.count()
    rows = (query.order_by(Call.started_at.desc())
            .offset((page - 1) * limit).limit(limit).all())
    return {"data": [serial.call(c) for c in rows],
            "pagination": {"page": page, "perPage": limit, "totalRowCount": total,
                           "totalPageCount": max(1, -(-total // limit))}}


@router.post("/calls")
def register_call(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Registra o resultado de uma ligação feita pelo softphone."""
    lead = db.get(Lead, payload["leadId"]) if payload.get("leadId") else None
    if payload.get("leadId") and not lead:
        raise HTTPException(404, "Lead não encontrado.")
    # O sinal de "não perturbe" vinha da Assertiva, era guardado e nunca
    # consultado — dava para registrar ligação para quem pediu para não ser
    # incomodado.
    if lead and lead.do_not_call:
        raise HTTPException(403, "Lead marcado como 'não perturbe'. "
                                 "Remova a marca no cadastro do lead.")
    status = payload.get("status", "NOT_PERFORMED")
    c = Call(user_id=payload.get("userId"), lead_id=payload.get("leadId"),
             origin_phone=payload.get("originPhone", ""),
             receiver_phone=payload.get("receiverPhone") or (lead.phone if lead else ""),
             receiver_type=payload.get("receiverType", "MOBILE"),
             status=status,
             output=payload.get("output", "") if status == "CONNECTED" else "",
             duration=int(payload.get("duration") or 0),
             important=bool(payload.get("important")))
    c.price = round(c.duration / 60 * MINUTE_PRICE, 4)
    db.add(c)
    db.commit()
    return serial.call(c)


@router.get("/calls/statistics/overview")
def overview(since: str | None = None, until: str | None = None,
             user_id: int | None = None, db: Session = Depends(get_db)):
    start, end = _range(since, until)
    query = db.query(Call).filter(Call.started_at.between(start, end))
    if user_id:
        query = query.filter(Call.user_id == user_id)
    calls = query.all()
    connected = [c for c in calls if c.status == "CONNECTED"]
    by_hour = defaultdict(lambda: [0, 0])
    for c in calls:
        by_hour[c.started_at.hour][0] += 1
        if c.status == "CONNECTED":
            by_hour[c.started_at.hour][1] += 1
    best_hour, best_pct = None, 0
    for hour, (total, ok) in by_hour.items():
        if total >= 5:
            pct = round(ok / total * 100)
            if pct > best_pct:
                best_hour, best_pct = hour, pct
    duration = sum(c.duration for c in connected)
    days = max(1, (end - start).days)
    reps = max(1, len({c.user_id for c in calls}))
    outputs = Counter(c.output for c in connected if c.output)
    return {"data": [{
        "startDate": serial.iso(start), "endDate": serial.iso(end),
        "totalCalls": len(calls), "totalConnected": len(connected),
        "totalMobile": sum(1 for c in calls if c.receiver_type == "MOBILE"),
        "totalLandline": sum(1 for c in calls if c.receiver_type == "LANDLINE"),
        "totalDurationInSeconds": duration,
        "averageDuration": round(duration / len(connected)) if connected else 0,
        "averageDailyCallsPerRep": round(len(calls) / days / reps, 1),
        "bestHourToCall": ({"bestStartHour": best_hour, "bestEndHour": best_hour + 1,
                            "connectedPercentage": best_pct} if best_hour is not None else None),
        "byHour": [{"hour": h, "total": t, "connected": ok}
                   for h, (t, ok) in sorted(by_hour.items())],
        "statuses": [
            {"status": "CONNECTED", "count": len(connected),
             "outputs": [{"output": k, "count": v} for k, v in outputs.items()]},
            {"status": "NOT_PERFORMED", "count": len(calls) - len(connected), "outputs": []},
        ],
        "meaningfulRate": round(outputs.get("MEANINGFUL", 0) / len(calls) * 100, 1) if calls else 0,
    }], "additionalInfo": {}}


@router.get("/calls/statistics/dropped")
def dropped(since: str | None = None, until: str | None = None,
            db: Session = Depends(get_db)):
    """Relatório de ligações derrubadas: conectadas e encerradas em até 10s."""
    start, end = _range(since, until)
    rows = (db.query(Call).filter(Call.started_at.between(start, end),
                                  Call.status == "CONNECTED", Call.duration <= 10)
            .order_by(Call.started_at.desc()).all())
    return {"data": [serial.call(c) for c in rows], "meta": {"total": len(rows)}}


@router.get("/calls/statements")
def statement(since: str | None = None, until: str | None = None,
              db: Session = Depends(get_db)):
    start, end = _range(since, until)
    rows = (db.query(Call.user_id, func.count(Call.id), func.sum(Call.duration))
            .filter(Call.started_at.between(start, end)).group_by(Call.user_id).all())
    users = {u.id: u for u in db.query(User).all()}
    data, total_min, total_cost = [], 0, 0.0
    for uid, count, seconds in rows:
        minutes = round((seconds or 0) / 60, 1)
        cost = round(minutes * MINUTE_PRICE, 2)
        total_min += minutes
        total_cost += cost
        data.append({"user": serial.user_min(users.get(uid)), "calls": count,
                     "minutes": minutes, "cost": cost})
    return {"data": data, "meta": {"totalMinutes": round(total_min, 1),
                                   "totalCost": round(total_cost, 2),
                                   "pricePerMinute": MINUTE_PRICE,
                                   "startDate": serial.iso(start), "endDate": serial.iso(end)}}
