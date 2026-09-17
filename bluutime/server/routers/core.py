"""Conta, empresa, usuários, times, clientes e ajustes."""
import os
from datetime import date, datetime

from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import func
from sqlalchemy.orm import Session

from .. import perm
from ..config import WEB
from ..db import get_db
from ..models import (Client, Company, CustomField, FitscoreRule, Goal, Holiday,
                      Integration, LostReason, Team, User, Webhook)
from ..serial import client as ser_client
from ..serial import iso, user_full

router = APIRouter(prefix="/api")

NATIVE_FIELDS = [
    ("firstName", "Primeiro nome", True), ("name", "Nome completo", True),
    ("email", "E-mail", True), ("company", "Empresa", True),
    ("position", "Cargo", False), ("phone", "Telefone(s)", False),
    ("site", "Site", False), ("state", "Estado", False), ("city", "Cidade", False),
    ("linkedIn", "LinkedIn", False), ("annotations", "Anotações", False),
    ("externalReference", "Referência externa", False), ("createdAt", "Criado em", False),
]

FEATURE_FLAGS = ["CONTROL_PANEL", "ALLOW_CONFIGURABLE_PERMISSIONS", "CAPIBLU_LEAD_SOURCE",
                 "SMART_QUEUE", "MULTI_CLIENT", "SHOW_STATISTICS_ACTIVITIES_TAB"]
PERMISSIONS = ["LEADS_VIEW_ALL", "LEADS_DELETE", "LEADS_ADD_MANUAL",
               "LEADBASE_UPLOAD", "STATISTICS_ACCESS", "CAPIBLU_ACCESS"]


def _company(db: Session) -> Company:
    c = db.query(Company).first()
    if not c:
        raise HTTPException(500, "Empresa não inicializada.")
    return c


def _current_user(db: Session) -> User | None:
    from ..deps import session_email
    email = session_email()
    return (db.query(User).filter(func.lower(User.email) == (email or "").lower()).first()
            or db.query(User).filter(User.roles.contains("ADMINISTRATOR")).first())


@router.get("/me")
def me(db: Session = Depends(get_db)):
    """Usuário operacional da sessão. Casa o e-mail da sessão CapiBLU com o
    cadastro de SDR; se não houver, cai no administrador."""
    u = _current_user(db)
    c = _company(db)
    return {**user_full(u), "companyId": c.id, "nivel": perm.ator(db).nivel,
            "modules": c.modules.split(","), "addOns": c.add_ons.split(",") if c.add_ons else []}


@router.patch("/me")
def update_me(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Meu Perfil — cada um só edita o próprio nome e assinatura de e-mail,
    sem precisar de perm nenhuma (não é gerenciar OUTRO usuário)."""
    u = _current_user(db)
    if not u:
        raise HTTPException(404, "Usuário operacional não encontrado para esta sessão.")
    if "name" in payload:
        name = (payload["name"] or "").strip()
        if not name:
            raise HTTPException(400, "Nome não pode ficar vazio.")
        u.name = name
    if "emailSignature" in payload:
        u.email_signature = payload["emailSignature"] or ""
    db.commit()
    return user_full(u)


@router.post("/me/avatar")
async def upload_avatar(file: UploadFile = File(...), db: Session = Depends(get_db)):
    u = _current_user(db)
    if not u:
        raise HTTPException(404, "Usuário operacional não encontrado para esta sessão.")
    if not (file.content_type or "").startswith("image/"):
        raise HTTPException(400, "Envie uma imagem.")
    content = await file.read()
    if len(content) > 4 * 1024 * 1024:
        raise HTTPException(400, "Imagem maior que 4MB.")
    try:
        from io import BytesIO

        from PIL import Image
        img = Image.open(BytesIO(content)).convert("RGB")
        img.thumbnail((200, 200))
        out_dir = os.path.join(WEB, "uploads", "avatars")
        os.makedirs(out_dir, exist_ok=True)
        path = os.path.join(out_dir, f"{u.id}.jpg")
        img.save(path, "JPEG", quality=85)
    except Exception as exc:
        raise HTTPException(400, f"Não consegui processar a imagem: {exc}")
    u.avatar_url = f"/uploads/avatars/{u.id}.jpg?v={int(datetime.utcnow().timestamp())}"
    db.commit()
    return user_full(u)


@router.get("/me/company")
def my_company(db: Session = Depends(get_db)):
    c = _company(db)
    return {"id": c.id, "name": c.name, "phone": c.phone, "site": c.site,
            "modules": c.modules.split(","),
            "addOns": c.add_ons.split(",") if c.add_ons else [],
            "status": c.status, "monthlyValue": c.monthly_value}


@router.get("/users/me/permissions")
def my_permissions(db: Session = Depends(get_db)):
    """Gestor e admin têm tudo. SDR só o que a empresa liberou em
    Ajustes > Permissões — antes essa lista era fixa pra todo mundo."""
    if perm.ator(db).pelo_menos("gestor"):
        return PERMISSIONS
    c = _company(db)
    out = ["CAPIBLU_ACCESS"]
    if c.leads_visible_all:
        out.append("LEADS_VIEW_ALL")
    if c.leads_add_manual:
        out.append("LEADS_ADD_MANUAL")
    if c.regular_user_can_import:
        out.append("LEADBASE_UPLOAD")
    if c.statistics_access:
        out.append("STATISTICS_ACCESS")
    return out


@router.get("/flow/permissions/configuration")
def permissions_config(db: Session = Depends(get_db)):
    c = _company(db)
    return {"leadsVisibleAll": c.leads_visible_all, "leadsAddManual": c.leads_add_manual,
            "leadbaseUpload": c.regular_user_can_import, "statisticsAccess": c.statistics_access}


@router.patch("/flow/permissions/configuration")
def update_permissions_config(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "configurar permissões")
    c = _company(db)
    if "leadsVisibleAll" in payload:
        c.leads_visible_all = bool(payload["leadsVisibleAll"])
    if "leadsAddManual" in payload:
        c.leads_add_manual = bool(payload["leadsAddManual"])
    if "leadbaseUpload" in payload:
        c.regular_user_can_import = bool(payload["leadbaseUpload"])
    if "statisticsAccess" in payload:
        c.statistics_access = bool(payload["statisticsAccess"])
    db.commit()
    return permissions_config(db)


@router.get("/flow/email/configuration")
def email_configuration(db: Session = Depends(get_db)):
    c = _company(db)
    return {"fromName": c.email_from_name, "fromAddress": c.email_from_address,
            "domainVerified": c.email_domain_verified}


@router.patch("/flow/email/configuration")
def update_email_configuration(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Remetente de e-mail — antes só dava pra trocar editando SMTP_FROM no
    .env do servidor. Trocar o endereço derruba a verificação de domínio:
    é outro domínio, precisa provar de novo que tem SPF."""
    perm.ator(db).exigir("gestor", "configurar remetente de e-mail")
    c = _company(db)
    if "fromName" in payload:
        c.email_from_name = (payload["fromName"] or "").strip()
    if "fromAddress" in payload:
        novo = (payload["fromAddress"] or "").strip().lower()
        if novo != c.email_from_address:
            c.email_domain_verified = False
        c.email_from_address = novo
    db.commit()
    return email_configuration(db)


@router.post("/flow/email/configuration/verify")
def verify_email_domain(db: Session = Depends(get_db)):
    """Confere de verdade — consulta o TXT do domínio e procura um SPF
    (v=spf1). Não é "liguei e acreditei": se não achar, continua False."""
    perm.ator(db).exigir("gestor", "verificar domínio de e-mail")
    c = _company(db)
    endereco = c.email_from_address
    if not endereco or "@" not in endereco:
        raise HTTPException(400, "Configure um endereço de e-mail remetente antes de verificar.")
    dominio = endereco.rsplit("@", 1)[-1]
    try:
        import dns.resolver
        respostas = dns.resolver.resolve(dominio, "TXT", lifetime=10)
        achou = any("v=spf1" in b"".join(r.strings).decode("utf-8", "ignore").lower()
                   for r in respostas)
    except Exception as exc:
        c.email_domain_verified = False
        db.commit()
        return {"domainVerified": False, "domain": dominio,
                "message": f"Não consegui verificar {dominio}: {type(exc).__name__}."}
    c.email_domain_verified = achou
    db.commit()
    return {"domainVerified": achou, "domain": dominio,
            "message": "Registro SPF encontrado." if achou
                      else f"Nenhum registro SPF encontrado em {dominio}."}


@router.get("/featureflag")
def featureflags():
    return FEATURE_FLAGS


@router.get("/users")
def list_users(db: Session = Depends(get_db)):
    users = db.query(User).order_by(User.id).all()
    return {"data": [user_full(u) for u in users],
            "pagination": {"page": 1, "perPage": 100, "totalRowCount": len(users),
                           "totalPageCount": 1, "hasPrev": False, "hasNext": False}}


@router.post("/users")
def create_user(payload: dict = Body(...), db: Session = Depends(get_db)):
    # Cria conta e define papel (inclusive ADMINISTRATOR) — só quem já
    # administra a plataforma pode fazer isso, senão qualquer SDR se promove.
    perm.ator(db).exigir("admin", "gerenciar usuários")
    email = (payload.get("email") or "").strip().lower()
    if not email or not payload.get("name"):
        raise HTTPException(400, "Nome e e-mail são obrigatórios.")
    if db.query(User).filter(func.lower(User.email) == email).first():
        raise HTTPException(400, "Já existe usuário com esse e-mail.")
    u = User(name=payload["name"], email=email,
             roles=",".join(payload.get("roles") or ["SDR"]),
             team_id=payload.get("teamId"),
             daily_goal=int(payload.get("dailyGoal") or _company(db).default_daily_goal))
    db.add(u)
    db.commit()
    return user_full(u)


@router.patch("/users/{uid}")
def update_user(uid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("admin", "gerenciar usuários")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado.")
    for key, attr in [("name", "name"), ("teamId", "team_id"),
                      ("dailyGoal", "daily_goal"), ("active", "active"), ("online", "online")]:
        if key in payload:
            setattr(u, attr, payload[key])
    if "roles" in payload:
        u.roles = ",".join(payload["roles"])
    db.commit()
    return user_full(u)


@router.get("/teams")
def list_teams(db: Session = Depends(get_db)):
    return [{"id": t.id, "name": t.name,
             "users": [{"id": u.id, "name": u.name} for u in t.users]}
            for t in db.query(Team).all()]


@router.get("/flow/users")
def flow_users(db: Session = Depends(get_db)):
    return [{"id": u.id, "name": u.name, "email": u.email, "dailyGoal": u.daily_goal}
            for u in db.query(User).filter(User.active).all()]


# ── Clientes: a entidade que falta no Meetime ──
@router.get("/clients")
def list_clients(db: Session = Depends(get_db)):
    from ..models import Cadence, Lead
    out = []
    for c in db.query(Client).order_by(Client.name).all():
        row = ser_client(c)
        row["cadences"] = db.query(func.count(Cadence.id)).filter_by(client_id=c.id).scalar()
        row["leads"] = db.query(func.count(Lead.id)).filter_by(client_id=c.id).scalar()
        row["won"] = db.query(func.count(Lead.id)).filter_by(client_id=c.id, status="WON").scalar()
        row["lost"] = db.query(func.count(Lead.id)).filter_by(client_id=c.id, status="LOST").scalar()
        out.append(row)
    return out


@router.post("/clients")
def create_client(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "cadastrar cliente")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome do cliente é obrigatório.")
    if db.query(Client).filter(func.lower(Client.name) == name.lower()).first():
        raise HTTPException(400, "Cliente já cadastrado.")
    c = Client(name=name, slug=payload.get("slug") or name.lower().replace(" ", "-"),
               color=payload.get("color") or "#00a443")
    db.add(c)
    db.commit()
    return ser_client(c)


@router.patch("/clients/{cid}")
def update_client(cid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "editar cliente")
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404, "Cliente não encontrado.")
    for key in ("name", "slug", "color", "active"):
        if key in payload:
            setattr(c, key, payload[key])
    db.commit()
    return ser_client(c)


@router.delete("/clients/{cid}")
def delete_client(cid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "excluir cliente")
    c = db.get(Client, cid)
    if not c:
        raise HTTPException(404, "Cliente não encontrado.")
    db.delete(c)
    db.commit()
    return {"ok": True}


# ── Ajustes de prospecção ──
@router.get("/flow/configuration")
def flow_config(db: Session = Depends(get_db)):
    c = _company(db)
    users = db.query(User).filter(User.active).all()
    return {"defaultDailyGoal": c.default_daily_goal,
            "accountBasedSalesEnabled": c.account_based_sales,
            "leadsVisible": True, "regularUserCanImportLeadList": c.regular_user_can_import,
            "smartQueueEnabled": c.smart_queue_enabled,
            "blacklist": [d for d in c.blacklist_domains.splitlines() if d.strip()],
            "workingDays": [int(x) for x in c.working_days.split(",") if x.strip()],
            "usersGoals": [{"userId": u.id, "dailyGoal": u.daily_goal} for u in users]}


@router.patch("/flow/configuration")
def update_flow_config(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Grava de verdade o que antes era só exibido — a tela de Ajustes
    mostrava vendas por conta/blacklist/dias úteis sem nenhum jeito de mudar."""
    perm.ator(db).exigir("gestor", "editar ajustes de prospecção")
    c = _company(db)
    if "defaultDailyGoal" in payload:
        c.default_daily_goal = max(1, int(payload["defaultDailyGoal"]))
    if "accountBasedSalesEnabled" in payload:
        c.account_based_sales = bool(payload["accountBasedSalesEnabled"])
    if "regularUserCanImportLeadList" in payload:
        c.regular_user_can_import = bool(payload["regularUserCanImportLeadList"])
    if "smartQueueEnabled" in payload:
        c.smart_queue_enabled = bool(payload["smartQueueEnabled"])
    if "workingDays" in payload:
        days = sorted({int(d) for d in payload["workingDays"] if 1 <= int(d) <= 7})
        c.working_days = ",".join(str(d) for d in days) or "1,2,3,4,5"
    if "blacklist" in payload:
        c.blacklist_domains = "\n".join(
            str(d).strip().lower() for d in payload["blacklist"] if str(d).strip())
    db.commit()
    return flow_config(db)


@router.get("/flow/deal-feedback/configuration")
def deal_feedback_config(db: Session = Depends(get_db)):
    c = _company(db)
    return {"dealFeedbackEnabled": c.deal_feedback_enabled,
            "qualificationTags": [t for t in c.deal_feedback_tags.splitlines() if t.strip()],
            "automationCadenceId": c.deal_feedback_automation_cadence_id}


@router.patch("/flow/deal-feedback/configuration")
def update_deal_feedback_config(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Feedback de oportunidade: liga a pergunta ao vendedor após o ganho e,
    opcionalmente, reencaminha pra uma cadência quem respondeu 'sem reunião'."""
    perm.ator(db).exigir("gestor", "configurar feedback de oportunidade")
    from ..models import Cadence
    c = _company(db)
    if "dealFeedbackEnabled" in payload:
        c.deal_feedback_enabled = bool(payload["dealFeedbackEnabled"])
    if "qualificationTags" in payload:
        c.deal_feedback_tags = "\n".join(
            str(t).strip() for t in payload["qualificationTags"] if str(t).strip())
    if "automationCadenceId" in payload:
        cid = payload["automationCadenceId"]
        if cid and not db.get(Cadence, int(cid)):
            raise HTTPException(400, "Cadência de automação inválida.")
        c.deal_feedback_automation_cadence_id = int(cid) if cid else None
    db.commit()
    return deal_feedback_config(db)


@router.get("/flow/lost-reasons")
def lost_reasons(db: Session = Depends(get_db)):
    return [{"id": r.id, "name": r.name} for r in db.query(LostReason).order_by(LostReason.name)]


@router.post("/flow/lost-reasons")
def create_lost_reason(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "cadastrar motivo de perda")
    name = (payload.get("name") or "").strip()
    if not name:
        raise HTTPException(400, "Nome obrigatório.")
    r = LostReason(name=name)
    db.add(r)
    db.commit()
    return {"id": r.id, "name": r.name}


@router.delete("/flow/lost-reasons/{rid}")
def delete_lost_reason(rid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "excluir motivo de perda")
    r = db.get(LostReason, rid)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


@router.get("/flow/new-lead-fields")
def lead_fields(db: Session = Depends(get_db)):
    out = [{"id": i + 1, "name": label, "identifier": ident, "customField": False,
            "visible": True, "required": req}
           for i, (ident, label, req) in enumerate(NATIVE_FIELDS)]
    for f in db.query(CustomField).order_by(CustomField.index).all():
        out.append({"id": f.id, "name": f.name, "identifier": f.identifier,
                    "dataType": f.data_type, "index": f.index,
                    "customField": True, "visible": f.visible, "required": False,
                    "wonMandatory": f.won_mandatory, "lostMandatory": f.lost_mandatory})
    return out


@router.post("/flow/new-lead-fields")
def create_field(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "criar campo personalizado")
    ident = (payload.get("identifier") or "").strip()
    if not ident or not payload.get("name"):
        raise HTTPException(400, "Nome e identificador são obrigatórios.")
    if db.query(CustomField).filter_by(identifier=ident).first():
        raise HTTPException(400, "Identificador já existe.")
    idx = (db.query(func.max(CustomField.index)).scalar() or 0) + 1
    f = CustomField(name=payload["name"], identifier=ident,
                    data_type=payload.get("dataType", "STRING"), index=idx,
                    won_mandatory=bool(payload.get("wonMandatory")),
                    lost_mandatory=bool(payload.get("lostMandatory")))
    db.add(f)
    db.commit()
    return {"id": f.id, "name": f.name, "identifier": f.identifier}


# ── Lead scoring (fitscore) ──
# Cada regra bate contra o valor de um campo personalizado do lead; os pontos
# das regras que baterem se somam. Isso não existia — o admin não tinha como
# priorizar lead nenhum por características do próprio lead, só por atraso.
@router.get("/flow/fitscore")
def fitscore_rules(db: Session = Depends(get_db)):
    rows = db.query(FitscoreRule).order_by(FitscoreRule.id).all()
    return [{"id": r.id, "fieldId": r.field_id, "fieldName": r.field.name if r.field else "",
             "expressionType": r.expression_type, "targetValue": r.target_value, "score": r.score}
            for r in rows]


@router.post("/flow/fitscore")
def create_fitscore_rule(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "configurar lead scoring")
    field = db.get(CustomField, int(payload.get("fieldId") or 0))
    if not field:
        raise HTTPException(400, "Campo inválido.")
    target = str(payload.get("targetValue") or "").strip()
    if not target:
        raise HTTPException(400, "Valor alvo é obrigatório.")
    r = FitscoreRule(field_id=field.id,
                     expression_type="LIKE" if payload.get("expressionType") == "LIKE" else "EQUALS",
                     target_value=target, score=int(payload.get("score") or 1))
    db.add(r)
    db.commit()
    return {"id": r.id}


@router.delete("/flow/fitscore/{rid}")
def delete_fitscore_rule(rid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "configurar lead scoring")
    r = db.get(FitscoreRule, rid)
    if r:
        db.delete(r)
        db.commit()
    return {"ok": True}


@router.get("/flow/configuration/holidays")
def holidays(db: Session = Depends(get_db)):
    return [{"id": h.id, "date": h.day.isoformat(), "name": h.name}
            for h in db.query(Holiday).order_by(Holiday.day)]


@router.post("/flow/configuration/holidays")
def add_holiday(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "cadastrar feriado")
    try:
        day = date.fromisoformat(payload["date"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Data inválida (use AAAA-MM-DD).")
    h = Holiday(day=day, name=payload.get("name", ""))
    db.add(h)
    db.commit()
    return {"id": h.id, "date": h.day.isoformat(), "name": h.name}


# ── Integrações, webhooks, financeiro ──
@router.get("/integrations")
def integrations(db: Session = Depends(get_db)):
    return [{"id": i.id, "key": i.key, "name": i.name, "kind": i.kind,
             "connected": i.connected, "lastSync": iso(i.last_sync)}
            for i in db.query(Integration).order_by(Integration.name)]


@router.patch("/integrations/{key}")
def toggle_integration(key: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "ligar/desligar integração")
    i = db.query(Integration).filter_by(key=key).first()
    if not i:
        raise HTTPException(404, "Integração não encontrada.")
    i.connected = bool(payload.get("connected", not i.connected))
    i.last_sync = datetime.utcnow() if i.connected else None
    db.commit()
    return {"key": i.key, "connected": i.connected, "lastSync": iso(i.last_sync)}


@router.get("/webhooks")
def webhooks(db: Session = Depends(get_db)):
    return [{"id": w.id, "events": w.events.split(","), "targetUrl": w.target_url,
             "enabled": w.enabled, "created": iso(w.created_at)}
            for w in db.query(Webhook).order_by(Webhook.id.desc())]


@router.post("/webhooks")
def create_webhook(payload: dict = Body(...), db: Session = Depends(get_db)):
    # Admin estrito, não gestor: webhook é integração de saída de dados da
    # empresa inteira — no Meetime é `isAdministrator`, mais restrito que o
    # resto de Integrações (que qualquer nível acessa).
    perm.ator(db).exigir("admin", "cadastrar webhook")
    url = (payload.get("targetUrl") or "").strip()
    if not url.startswith("http"):
        raise HTTPException(400, "URL inválida.")
    w = Webhook(events=",".join(payload.get("events") or ["LEAD.WON"]), target_url=url,
                secret=payload.get("secret", ""))
    db.add(w)
    db.commit()
    return {"id": w.id, "events": w.events.split(","), "targetUrl": w.target_url}


@router.delete("/webhooks/{wid}")
def delete_webhook(wid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("admin", "excluir webhook")
    w = db.get(Webhook, wid)
    if w:
        db.delete(w)
        db.commit()
    return {"ok": True}


@router.get("/financial/company")
def financial(db: Session = Depends(get_db)):
    # Admin estrito, como no Meetime real (menu "Empresa" é isAdministrator,
    # não abre nem pra Manager) — não tinha checagem nenhuma antes.
    perm.ator(db).exigir("admin", "ver dados financeiros")
    c = _company(db)
    paid = db.query(func.count(User.id)).filter(User.active).scalar()
    return {"subscription": {"cycle": "MONTHLY", "value": c.monthly_value,
                             "userProductValues": {"FLOW": 581.19, "COMBO": 327.68, "WHATSAPP": 0}},
            "addOns": {"CALLER_ID_NUMBERS": 46.41, "PREDICTIVE_DIALER": 0},
            "billingType": "BANK_SLIP", "availableFreeUsers": 3, "paidUsers": paid,
            "yearlyEstimate": round(c.monthly_value * 12, 2)}


@router.get("/flow/goals/{ref}")
def goals(ref: str, db: Session = Depends(get_db)):
    try:
        d = date.fromisoformat(ref)
    except ValueError:
        d = date.today()
    month = date(d.year, d.month, 1)
    rows = db.query(Goal).filter_by(target_month=month).all()
    return {"targetMonth": month.isoformat(),
            "usersGoals": [{"user": {"id": g.user.id, "name": g.user.name},
                            "opportunitiesGoal": g.opportunities_goal,
                            "conversionRateGoal": g.conversion_rate_goal} for g in rows]}


@router.put("/flow/goals/{ref}")
def set_goals(ref: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "definir metas do time")
    d = date.fromisoformat(ref) if ref else date.today()
    month = date(d.year, d.month, 1)
    for item in payload.get("usersGoals", []):
        uid = item["userId"]
        g = db.query(Goal).filter_by(user_id=uid, target_month=month).first()
        if not g:
            g = Goal(user_id=uid, target_month=month)
            db.add(g)
        g.opportunities_goal = int(item.get("opportunitiesGoal", 25))
        g.conversion_rate_goal = float(item.get("conversionRateGoal", 0.15))
    db.commit()
    return goals(ref, db)
