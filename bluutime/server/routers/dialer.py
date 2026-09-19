"""Ligações: lista, estatísticas, extrato e click-to-call."""
import csv
import io
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from fastapi.responses import StreamingResponse
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from ..db import get_db
from ..models import Call, Company, Lead, Team, User
from .. import perm, serial
from .analytics import usuarios_do_time

router = APIRouter(prefix="/api/dialer")

MINUTE_PRICE = 0.47  # R$/min — mesma ordem de grandeza do extrato Meetime


def _company(db: Session) -> Company:
    c = db.query(Company).first()
    if not c:
        raise HTTPException(500, "Empresa não inicializada.")
    return c


@router.get("/configuration")
def dialer_configuration(db: Session = Depends(get_db)):
    c = _company(db)
    return {"voipEnabled": c.voip_enabled, "phoneEnabled": c.phone_enabled,
            "defaultType": c.default_call_type,
            "callerIds": [n for n in c.caller_ids.splitlines() if n.strip()]}


@router.patch("/configuration")
def update_dialer_configuration(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Não existia tela nenhuma pra isso — o SDR registrava a ligação sem
    escolher de qual número da empresa ela saiu."""
    perm.ator(db).exigir("gestor", "configurar o dialer")
    c = _company(db)
    if "voipEnabled" in payload:
        c.voip_enabled = bool(payload["voipEnabled"])
    if "phoneEnabled" in payload:
        c.phone_enabled = bool(payload["phoneEnabled"])
    if "defaultType" in payload and payload["defaultType"] in ("VOIP", "PHONE"):
        c.default_call_type = payload["defaultType"]
    if "callerIds" in payload:
        c.caller_ids = "\n".join(str(n).strip() for n in payload["callerIds"] if str(n).strip())
    db.commit()
    return dialer_configuration(db)


def _range(since: str | None, until: str | None) -> tuple[datetime, datetime]:
    end = datetime.fromisoformat(until) if until else datetime.utcnow()
    start = datetime.fromisoformat(since) if since else end.replace(day=1, hour=0, minute=0)
    return start, end + timedelta(days=1) if until else end


def _escopo(db: Session, q, team_id: int | None, user_id: int | None):
    """Recorte por time e por pessoa, na ordem que o original oferece."""
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    if user_id:
        q = q.filter(Call.user_id == user_id)
    return q


def _etapas(db: Session, inicio, fim, team_id, user_id) -> dict:
    base = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                   team_id, user_id)
    total = base.count()
    conectadas = base.filter(Call.status == "CONNECTED").count()
    significativas = base.filter(Call.status == "CONNECTED",
                                 Call.output == "MEANINGFUL").count()
    return {"total": total, "conectadas": conectadas, "significativas": significativas}


def _variacao(agora: int, antes: int) -> dict:
    """Quanto mudou em relação ao período anterior.

    Sem base de comparação (o período anterior foi zero) não existe variação
    percentual — devolver 100% ali seria inventar um crescimento que ninguém
    pode conferir, então o percentual vem nulo e a tela mostra o absoluto.
    """
    return {"diferenca": agora - antes,
            "percentual": round((agora - antes) / antes * 100, 1) if antes else None}


@router.patch("/calls/{cid}")
def update_call(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Hoje só marcar/desmarcar como importante — o que o original chama de
    estrela na lista, para achar de novo a ligação que interessou."""
    c = db.get(Call, cid)
    if not c:
        raise HTTPException(404, "Ligação não encontrada.")
    ator = perm.ator(db)
    if not ator.pelo_menos("gestor") and c.user_id != ator.user_id:
        raise HTTPException(403, "Só dá para marcar as próprias ligações.")
    if "important" in payload:
        c.important = bool(payload["important"])
    db.commit()
    return serial.call(c)


@router.get("/calls/export")
def export_calls(user_id: int | None = None, status: str | None = None,
                 output: str | None = None, since: str | None = None,
                 until: str | None = None, team_id: int | None = None,
                 q: str | None = None, db: Session = Depends(get_db)):
    """Exporta a lista filtrada, como o botão Exportar do original."""
    res = list_calls(user_id=user_id, status=status, output=output, since=since,
                     until=until, team_id=team_id, q=q, page=1, limit=20000, db=db)
    rotulo = {"MEANINGFUL": "Significativa", "NOT_MEANINGFUL": "Não significativa",
              "NO_CONTACT": "Sem contato"}
    linhas = [[c["originStarted"][:16].replace("T", " ") if c["originStarted"] else "",
               (c["user"] or {}).get("name", ""), c["flowLeadName"] or "",
               c["flowLeadCompany"] or "", c["originPhone"], c["receiverPhone"],
               "Celular" if c["receiverType"] == "MOBILE" else "Fixo",
               "Conectada" if c["status"] == "CONNECTED" else "Não conectada",
               rotulo.get(c["output"], ""), c["receiverConnectedDuration"],
               f'{c["receiverPrice"]:.4f}'.replace(".", ","),
               "sim" if c["important"] else ""]
              for c in res["data"]]
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow(["Data", "Usuário", "Lead", "Empresa", "Origem", "Destino", "Tipo",
                "Situação", "Resultado", "Duração (s)", "Custo (R$)", "Importante"])
    w.writerows(linhas)
    buf.seek(0)
    return StreamingResponse(iter([buf.getvalue().encode("utf-8-sig")]),
                             media_type="text/csv",
                             headers={"Content-Disposition":
                                      f'attachment; filename="ligacoes-{datetime.utcnow():%Y%m%d}.csv"'})


@router.get("/calls/statistics/funnel")
def funnel(since: str | None = None, until: str | None = None,
           team_id: int | None = None, user_id: int | None = None,
           db: Session = Depends(get_db)):
    """Realizadas → conectadas → significativas, contra o período anterior.

    O "anterior" é a janela de mesmo tamanho imediatamente antes: comparar um
    mês com a semana passada diria qualquer coisa.
    """
    inicio, fim = _range(since, until)
    duracao = fim - inicio
    atual = _etapas(db, inicio, fim, team_id, user_id)
    anterior = _etapas(db, inicio - duracao, inicio, team_id, user_id)
    pct = lambda parte, todo: round(parte / todo * 100, 1) if todo else 0.0  # noqa: E731
    return {
        "atual": atual, "anterior": anterior,
        "periodoAnterior": {"since": (inicio - duracao).date().isoformat(),
                            "until": inicio.date().isoformat()},
        "taxas": {"conexao": pct(atual["conectadas"], atual["total"]),
                  "significancia": pct(atual["significativas"], atual["conectadas"])},
        "comparacao": {k: _variacao(atual[k], anterior[k]) for k in atual},
    }


@router.get("/calls/statistics/grouped")
def grouped(since: str | None = None, until: str | None = None,
            by: str = "user", db: Session = Depends(get_db)):
    """Volume de ligações por usuário ou por time."""
    inicio, fim = _range(since, until)
    linhas = (db.query(Call.user_id, Call.status, func.count(Call.id))
              .filter(Call.started_at.between(inicio, fim))
              .group_by(Call.user_id, Call.status).all())
    usuarios = {u.id: u for u in db.query(User).all()}
    times = {t.id: t.name for t in db.query(Team).all()}

    acumulado: dict = {}
    for uid, status, n in linhas:
        u = usuarios.get(uid)
        if by == "team":
            chave = u.team_id if u and u.team_id else 0
            rotulo = times.get(chave, "Sem time")
        else:
            chave = uid or 0
            rotulo = u.name if u else "Sem usuário"
        linha = acumulado.setdefault(chave, {"label": rotulo, "total": 0, "conectadas": 0})
        linha["total"] += n
        if status == "CONNECTED":
            linha["conectadas"] += n
    dados = sorted(acumulado.values(), key=lambda r: r["total"], reverse=True)
    return {"by": by, "data": dados}


@router.get("/calls/statistics/history")
def history(since: str | None = None, until: str | None = None,
            interval: str = "day", team_id: int | None = None,
            status: str | None = None, db: Session = Depends(get_db)):
    """Série temporal de ligações por dia, semana ou mês."""
    inicio, fim = _range(since, until)
    q = _escopo(db, db.query(Call).filter(Call.started_at.between(inicio, fim)),
                team_id, None)
    if status:
        q = q.filter(Call.status == status)
    formato = {"day": "%Y-%m-%d", "week": "%Y-W%W", "month": "%Y-%m"}.get(interval, "%Y-%m-%d")
    contagem: dict = {}
    for c in q.all():
        chave = c.started_at.strftime(formato)
        linha = contagem.setdefault(chave, {"label": chave, "total": 0, "conectadas": 0})
        linha["total"] += 1
        if c.status == "CONNECTED":
            linha["conectadas"] += 1
    return {"interval": interval, "data": [contagem[k] for k in sorted(contagem)]}


@router.get("/calls")
def list_calls(user_id: int | None = None, status: str | None = None,
               output: str | None = None, lead_id: int | None = None,
               since: str | None = None, until: str | None = None,
               team_id: int | None = None, q: str | None = None,
               important: bool | None = None,
               page: int = 1, limit: int = Query(50, le=500),
               db: Session = Depends(get_db)):
    ator = perm.ator(db)
    if not ator.pelo_menos("gestor"):
        empresa = _company(db)
        # Sem isso, um SDR listava ligação (telefone e empresa do lead
        # incluídos) de qualquer colega só passando outro user_id/lead_id —
        # a listagem nunca filtrava por dono, só as telas de lead filtravam.
        if not empresa.leads_visible_all:
            user_id = ator.user_id or -1
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
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        query = query.filter(Call.user_id.in_(do_time))
    if important is not None:
        query = query.filter(Call.important.is_(important))
    if q:
        # Busca pelo número discado ou pelo nome do lead — as duas formas de
        # procurar "aquela ligação" quando não se lembra da data.
        alvo = f"%{q}%"
        query = query.outerjoin(Lead, Call.lead_id == Lead.id).filter(
            or_(Call.receiver_phone.ilike(alvo), Lead.name.ilike(alvo),
                Lead.company.ilike(alvo)))
    total = query.count()
    rows = (query.order_by(Call.started_at.desc())
            .offset((page - 1) * limit).limit(limit).all())
    return {"data": [serial.call(c) for c in rows],
            "pagination": {"page": page, "perPage": limit, "totalRowCount": total,
                           "totalPageCount": max(1, -(-total // limit))}}


@router.post("/calls")
def register_call(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Registra o resultado de uma ligação feita pelo softphone."""
    ator = perm.ator(db)
    # userId vinha livre do payload — um SDR registrava ligação em nome de
    # outro colega e inflava (ou sabotava) o ranking dele.
    user_id = payload.get("userId")
    if not ator.pelo_menos("gestor"):
        user_id = ator.user_id
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
    c = Call(user_id=user_id, lead_id=payload.get("leadId"),
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
             user_id: int | None = None, team_id: int | None = None,
             db: Session = Depends(get_db)):
    start, end = _range(since, until)
    query = db.query(Call).filter(Call.started_at.between(start, end))
    if user_id:
        query = query.filter(Call.user_id == user_id)
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        query = query.filter(Call.user_id.in_(do_time))
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
            team_id: int | None = None, db: Session = Depends(get_db)):
    """Relatório de ligações derrubadas: conectadas e encerradas em até 10s."""
    start, end = _range(since, until)
    q = db.query(Call).filter(Call.started_at.between(start, end),
                              Call.status == "CONNECTED", Call.duration <= 10)
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    rows = q.order_by(Call.started_at.desc()).all()
    return {"data": [serial.call(c) for c in rows], "meta": {"total": len(rows)}}


@router.get("/calls/statements")
def statement(since: str | None = None, until: str | None = None,
              team_id: int | None = None, db: Session = Depends(get_db)):
    start, end = _range(since, until)
    q = (db.query(Call.user_id, func.count(Call.id), func.sum(Call.duration))
         .filter(Call.started_at.between(start, end)))
    do_time = usuarios_do_time(db, team_id)
    if do_time is not None:
        q = q.filter(Call.user_id.in_(do_time))
    rows = q.group_by(Call.user_id).all()
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
