"""Migração do Meetime para o Bluutime.

Puxa a operação real da conta pela API v2 e preenche as telas. A importação é
idempotente: cada registro guarda o `meetime_id` de origem, então rodar de novo
atualiza em vez de duplicar.

O que o Meetime não modela vira modelagem aqui: o cliente, que lá é prefixo no
nome da cadência (`ADV [BLU] [START]`), é extraído para a entidade `Client`.
"""
import re
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException, Query
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import meetime_api, perm, progresso, serial
from ..db import get_db
from ..models import (Cadence, CadenceUser, Call, Client, Company, Lead,
                      LeadBase, LostReason, Team, User, Webhook)

router = APIRouter(prefix="/api/meetime")

# Tokens que aparecem entre colchetes no nome da cadência e são, de fato, cliente.
# O resto (START, LEADS, CONNECT, ANTIGOS…) é etapa ou recorte, não cliente.
CLIENT_TOKENS = {
    "BLU": "BLU Sales Group", "FROTAI": "Frotaí", "FROTAÍ": "Frotaí",
    "PLANNING": "Planning", "V4": "V4 Company", "TRENTINI": "Trentini Advocacia",
    "JRB": "JRB Benefícios", "GOAT": "G.O.A.T",
}
CLIENT_COLORS = ["#00a443", "#2196f3", "#ff5722", "#5e62ff", "#00bcd4", "#ef6c00", "#9c27b0"]

STATUS_MAP = {
    "WAITING": "WAITING", "EXECUTING": "EXECUTING", "ON_EXTRA_ACTIVITY": "ON_EXTRA_ACTIVITY",
    "PAUSED_FROM_EXECUTING": "PAUSED_FROM_EXECUTING", "PAUSED": "PAUSED_FROM_EXECUTING",
    "WON": "WON", "LOST": "LOST", "SWITCHED_CADENCE": "SWITCHED_CADENCE",
    "FINISHED": "LOST",
}
ROLE_MAP = {"ADMINISTRATOR": "ADMINISTRATOR", "MANAGER": "MANAGER",
            "SDR": "SDR", "SALESMAN": "SALESMAN"}


def _dt(value) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        return None


def _client_name(cadence_name: str) -> str | None:
    for token in re.findall(r"[\[{(]([^\]})]+)[\]})]", cadence_name or ""):
        key = token.strip().upper().replace(".", "")
        if key in CLIENT_TOKENS:
            return CLIENT_TOKENS[key]
    return None


def _get_client(db: Session, name: str | None, cache: dict) -> int | None:
    if not name:
        return None
    if name in cache:
        return cache[name]
    client = db.query(Client).filter(func.lower(Client.name) == name.lower()).first()
    if not client:
        client = Client(name=name, slug=re.sub(r"\W+", "-", name.lower()).strip("-"),
                        color=CLIENT_COLORS[len(cache) % len(CLIENT_COLORS)])
        db.add(client)
        db.flush()
    cache[name] = client.id
    return client.id


def _upsert(db: Session, model, meetime_id: str, **fields):
    row = db.query(model).filter(model.meetime_id == str(meetime_id)).first()
    if not row:
        row = model(meetime_id=str(meetime_id))
        db.add(row)
    for key, value in fields.items():
        setattr(row, key, value)
    db.flush()
    return row


@router.get("/status")
async def status(db: Session = Depends(get_db)):
    if not meetime_api.enabled():
        return {"configured": False,
                "message": "Defina MEETIME_TOKEN no .env para habilitar a migração."}
    try:
        totals = await meetime_api.counts()
    except PermissionError as exc:
        return {"configured": True, "valid": False, "message": str(exc)}
    imported = {
        "users": db.query(func.count(User.id)).filter(User.meetime_id != "").scalar(),
        "cadences": db.query(func.count(Cadence.id)).filter(Cadence.meetime_id != "").scalar(),
        "leads": db.query(func.count(Lead.id)).filter(Lead.meetime_id != "").scalar(),
        "calls": db.query(func.count(Call.id)).filter(Call.meetime_id != "").scalar(),
        "leadBases": db.query(func.count(LeadBase.id)).filter(LeadBase.meetime_id != "").scalar(),
        "clients": db.query(func.count(Client.id)).scalar(),
    }
    return {"configured": True, "valid": True, "baseUrl": meetime_api.BASE_URL,
            "remote": totals, "imported": imported}


@router.get("/preview/{resource}")
async def preview(resource: str, limit: int = Query(5, le=50)):
    if resource not in meetime_api.RESOURCES:
        raise HTTPException(404, f"Recurso desconhecido. Use: {', '.join(meetime_api.RESOURCES)}")
    try:
        return await meetime_api.page(resource, start=0, limit=limit)
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    except RuntimeError as exc:
        raise HTTPException(502, str(exc))


@router.get("/progresso")
def progresso_sync():
    """Como está a migração agora. A tela consulta enquanto a barra anda."""
    return progresso.ler("meetime-sync") or {"estado": "PARADO"}


@router.post("/completar-juncao")
async def completar_juncao(payload: dict = Body(default={}),
                           db: Session = Depends(get_db)):
    """Preenche cadência e SDR nos leads que ficaram sem.

    A migração limita quantas prospecções busca, porque a junção custa **uma
    consulta por lead** — é a única exata que a API oferece. Quem sobra fica sem
    cadência. Aqui os que faltam são completados sem tocar no resto: nada de
    `reset`, nada de reimportar.
    """
    if not meetime_api.enabled():
        raise HTTPException(400, "MEETIME_TOKEN não configurado.")
    perm.ator(db).exigir("gestor", "completar a migração")

    # Cadência **ou** SDR em falta: um lead pode ter ganhado a cadência numa
    # passada anterior e continuar sem dono.
    faltando = (db.query(Lead)
                .filter(Lead.meetime_id != "",
                        or_(Lead.cadence_id.is_(None), Lead.sdr_id.is_(None)))
                .limit(min(int(payload.get("limite", 1000)), 6000)).all())
    if not faltando:
        return {"ok": True, "pendentes": 0, "mensagem": "Nada a completar."}

    progresso.iniciar("meetime-sync", f"Completando {len(faltando)} leads")
    ids = [l.meetime_id for l in faltando]
    try:
        prosp = await meetime_api.prospections_for_leads(
            ids, progress=lambda f, t: progresso.etapa(
                "meetime-sync", "Buscando prospecção por lead", f, t))
    except Exception as exc:
        progresso.concluir("meetime-sync", erro=str(exc))
        raise HTTPException(502, f"Falha ao consultar o Meetime: {exc}"[:200])

    cad_por_meetime = {c.meetime_id: c.id for c in db.query(Cadence).all() if c.meetime_id}
    user_por_meetime = {u.meetime_id: u.id for u in db.query(User).all() if u.meetime_id}
    atualizados = sem_prospeccao = 0
    for lead in faltando:
        p = prosp.get(str(lead.meetime_id))
        if not p:
            sem_prospeccao += 1
            continue
        lead.cadence_id = cad_por_meetime.get(str(p.get("cadence_id") or ""))
        # `owner_id`, não `user_id` — é o nome que a prospecção usa para o dono,
        # e o mesmo que a migração completa consulta.
        lead.sdr_id = user_por_meetime.get(str(p.get("owner_id") or ""))
        novo = STATUS_MAP.get(p.get("status") or "", "")
        if novo:
            lead.status = novo
        atualizados += 1
    db.commit()

    resultado = {"ok": True, "processados": len(faltando), "atualizados": atualizados,
                 "semProspeccao": sem_prospeccao}
    progresso.concluir("meetime-sync", resultado)
    return resultado


@router.post("/sync")
async def sync(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Importa a operação real. `reset=true` apaga antes o que veio do seed."""
    if not meetime_api.enabled():
        raise HTTPException(400, "MEETIME_TOKEN não configurado.")
    progresso.iniciar("meetime-sync", "Migração do Meetime")

    max_leads = min(int(payload.get("maxLeads", 1500)), 12000)
    max_calls = min(int(payload.get("maxCalls", 2000)), 20000)
    max_prospections = min(int(payload.get("maxProspections", 3000)), 20000)

    # Cada recurso é buscado de forma independente: /v2/calls é instável (503 sob
    # carga) e não pode derrubar a migração de leads e cadências.
    warnings: dict[str, str] = {}

    async def pull(resource: str, cap: int) -> list[dict]:
        try:
            return await meetime_api.fetch_all(resource, cap)
        except PermissionError:
            raise
        except Exception as exc:  # noqa: BLE001
            warnings[resource] = str(exc)[:200]
            return []

    try:
        users_raw = await pull("users", 500)
        cadences_raw = await pull("cadences", 500)
        leads_raw = await pull("leads", max_leads)
        calls_raw = await pull("calls", max_calls)
        webhooks_raw = await pull("webhooks", 100)
        live_leads = [str(l["id"]) for l in leads_raw if not l.get("lead_deleted_date")]
        prospections_by_lead = await meetime_api.prospections_for_leads(
            live_leads[:max_prospections],
            progress=lambda feito, total: progresso.etapa(
                "meetime-sync", "Juntando lead com prospecção", feito, total))
    except PermissionError as exc:
        raise HTTPException(403, str(exc))
    if not users_raw and not cadences_raw and not leads_raw:
        raise HTTPException(502, "Nenhum dado veio do Meetime. " + "; ".join(
            f"{k}: {v}" for k, v in warnings.items()))

    if payload.get("reset"):
        _wipe_seed(db)

    company = db.query(Company).first()
    if company:
        company.name = "BLU Sales Group"

    clients: dict[str, int] = {}
    teams: dict[str, int] = {}
    report = {}

    # ── usuários e times ──
    for u in users_raw:
        team_id = None
        team_name = u.get("team_name")
        if team_name:
            if team_name not in teams:
                team = (db.query(Team).filter(Team.name == team_name).first()
                        or Team(name=team_name, meetime_id=str(u.get("team_id") or "")))
                db.add(team)
                db.flush()
                teams[team_name] = team.id
            team_id = teams[team_name]
        email = (u.get("email") or f"user{u['id']}@sem-email.local").strip().lower()
        # e-mail é único no banco: se já existe com outro meetime_id, adota o registro.
        existing = db.query(User).filter(func.lower(User.email) == email).first()
        if existing and existing.meetime_id not in ("", str(u["id"])):
            continue
        row = existing or db.query(User).filter(User.meetime_id == str(u["id"])).first() or User()
        row.meetime_id = str(u["id"])
        row.name = u.get("name") or email
        row.email = email
        row.roles = ROLE_MAP.get(u.get("role") or "", "SDR")
        row.team_id = team_id
        row.active = bool(u.get("active"))
        if row.id is None:
            db.add(row)
    db.flush()
    report["users"] = len(users_raw)
    by_user = {u.meetime_id: u.id for u in db.query(User).filter(User.meetime_id != "")}

    # ── cadências (e os clientes escondidos no nome) ──
    for c in cadences_raw:
        if c.get("deleted"):
            continue
        name = c.get("name") or f"Cadência {c['id']}"
        _upsert(db, Cadence, c["id"], name=name,
                description=c.get("description") or "",
                type=c.get("type") or "STANDARD",
                focus=c.get("cadence_focus") or "OUTBOUND",
                priority=c.get("priority") or "MEDIUM",
                executing=bool(c.get("executing")),
                client_id=_get_client(db, _client_name(name), clients),
                created_at=_dt(c.get("created_at")) or datetime.utcnow())
    db.flush()
    by_cadence = {c.meetime_id: c for c in db.query(Cadence).filter(Cadence.meetime_id != "")}
    report["cadences"] = len(by_cadence)
    report["clients"] = len(clients)

    # ── prospecções: onde moram status, dono, base e resultado do lead ──
    prospections = {}
    lost_reasons: dict[str, int] = {}
    lead_bases: dict[str, int] = {}
    for lead_id, p in prospections_by_lead.items():
        if p.get("deleted_date"):
            continue
        prospections[lead_id] = p
        reason = (p.get("lost_reason") or "").strip()
        if reason and reason not in lost_reasons:
            row = (db.query(LostReason).filter(func.lower(LostReason.name) == reason.lower()).first()
                   or LostReason(name=reason, meetime_id=str(p.get("lost_reason_id") or "")))
            db.add(row)
            db.flush()
            lost_reasons[reason] = row.id
        base_name = (p.get("lead_base") or "").strip()
        if base_name and base_name not in lead_bases:
            row = _upsert(db, LeadBase, p.get("lead_base_id") or f"name:{base_name}",
                          name=base_name, source="MEETIME", status="COMPLETED")
            lead_bases[base_name] = row.id
    db.flush()
    report["prospections"] = len(prospections)
    report["leadBases"] = len(lead_bases)
    report["lostReasons"] = len(lost_reasons)

    # ── leads ──
    imported_leads = 0
    for l in leads_raw:
        if l.get("lead_deleted_date"):
            continue
        p = prospections.get(str(l["id"])) or {}
        cadence = by_cadence.get(str(p.get("cadence_id") or ""))
        phones = l.get("phonesString") or l.get("primaryPhoneString") or ""
        if not phones:
            phones = " / ".join(x.get("phone", "") for x in (l.get("phones") or []) if x.get("phone"))
        status = STATUS_MAP.get(p.get("status") or "", "WAITING")
        name = (l.get("lead_name") or "").strip() or (l.get("lead_company") or "").strip()
        if not name:
            continue
        _upsert(db, Lead, l["id"],
                name=name, first_name=name.split(" ")[0],
                email=(l.get("lead_email") or "").strip().lower(),
                company=l.get("lead_company") or "",
                position=l.get("lead_position") or l.get("cargoContato1") or "",
                phone=phones, site=l.get("lead_site") or "",
                state=l.get("lead_state") or "", city=l.get("lead_city") or "",
                linkedin=l.get("lead_linkedin") or "",
                annotations=_strip_html(l.get("lead_annotations") or ""),
                external_reference=str(l.get("external_reference") or ""),
                cnpj="".join(ch for ch in str(l.get("cnpj") or "") if ch.isdigit()),
                razao_social=l.get("razaoSocial") or l.get("lead_company") or "",
                status=status,
                cadence_id=cadence.id if cadence else None,
                client_id=cadence.client_id if cadence else None,
                sdr_id=by_user.get(str(p.get("owner_id") or "")),
                lead_base_id=lead_bases.get((p.get("lead_base") or "").strip()),
                lost_reason_id=lost_reasons.get((p.get("lost_reason") or "").strip()),
                won_at=_dt(p.get("end_date")) if status == "WON" else None,
                lost_at=_dt(p.get("end_date")) if status == "LOST" else None,
                created_at=_dt(l.get("lead_created_date")) or datetime.utcnow())
        imported_leads += 1
    db.flush()
    report["leads"] = imported_leads
    by_lead = {l.meetime_id: l.id for l in db.query(Lead).filter(Lead.meetime_id != "")}

    # ── ligações ──
    skipped_calls = 0
    for c in calls_raw:
        started = _dt(c.get("started_at") or c.get("date"))
        if not started:
            # Sem data a ligação não pode entrar: cairia em `utcnow()` e
            # apareceria como chamada de hoje nas estatísticas do mês.
            skipped_calls += 1
            continue
        _upsert(db, Call, c["id"],
                user_id=by_user.get(str(c.get("user_id") or "")),
                lead_id=by_lead.get(str(c.get("lead_id") or "")),
                origin_phone=c.get("origin_phone") or "",
                receiver_phone=c.get("receiver_phone") or "",
                receiver_type=c.get("receiver_type") or "MOBILE",
                status=c.get("status") or "NOT_PERFORMED",
                output=c.get("output") or "",
                duration=int(c.get("connected_duration_seconds") or 0),
                price=float(c.get("price") or 0),
                important=bool(c.get("important")),
                started_at=started)
    db.flush()
    report["calls"] = len(calls_raw) - skipped_calls
    if skipped_calls:
        warnings["calls_sem_data"] = f"{skipped_calls} ligações ignoradas por não terem data."

    for w in webhooks_raw:
        if w.get("deleted"):
            continue
        _upsert(db, Webhook, w["id"], events=",".join(w.get("events") or []),
                target_url=w.get("target_url") or "", secret=w.get("secret") or "",
                enabled=bool(w.get("enabled")),
                created_at=_dt(w.get("created")) or datetime.utcnow())
    report["webhooks"] = len(webhooks_raw)

    # Contagem das bases refeita depois dos leads entrarem.
    for base_id in lead_bases.values():
        base = db.get(LeadBase, base_id)
        base.number_of_leads = db.query(func.count(Lead.id)).filter_by(lead_base_id=base_id).scalar()

    db.commit()
    report["syncedAt"] = serial.iso(datetime.utcnow())
    return {"ok": True, "report": report, "warnings": warnings}


def _strip_html(text: str) -> str:
    import html as _html
    return _html.unescape(re.sub(r"<[^>]+>", " ", text)).strip()


def _wipe_seed(db: Session) -> None:
    """Apaga o que veio do seed de demonstração, preservando o que já foi
    importado do Meetime (tudo que tem `meetime_id`)."""
    from ..models import Conversation, LeadActivity, Message

    seed_leads = [l.id for l in db.query(Lead).filter(Lead.meetime_id == "")]
    if seed_leads:
        db.query(Message).filter(Message.conversation_id.in_(
            db.query(Conversation.id).filter(Conversation.lead_id.in_(seed_leads))
        )).delete(synchronize_session=False)
        db.query(Conversation).filter(Conversation.lead_id.in_(seed_leads)).delete(
            synchronize_session=False)
        db.query(LeadActivity).filter(LeadActivity.lead_id.in_(seed_leads)).delete(
            synchronize_session=False)
        db.query(Lead).filter(Lead.id.in_(seed_leads)).delete(synchronize_session=False)
    db.query(Call).filter(Call.meetime_id == "").delete(synchronize_session=False)
    seed_cadences = [c.id for c in db.query(Cadence).filter(Cadence.meetime_id == "")]
    if seed_cadences:
        db.query(CadenceUser).filter(CadenceUser.cadence_id.in_(seed_cadences)).delete(
            synchronize_session=False)
        db.query(Cadence).filter(Cadence.id.in_(seed_cadences)).delete(synchronize_session=False)
    db.query(LeadBase).filter(LeadBase.meetime_id == "").delete(synchronize_session=False)
    db.flush()
