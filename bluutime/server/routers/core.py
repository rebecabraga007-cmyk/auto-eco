"""Conta, empresa, usuários, times, clientes e ajustes."""
import asyncio
import os
from datetime import date, datetime, timedelta

import httpx
from fastapi import APIRouter, Body, Depends, File, HTTPException, UploadFile
from sqlalchemy import func, or_
from sqlalchemy.orm import Session

from .. import perm
from .. import webhooks as webhooks_engine
from ..config import WEB
from ..db import get_db
from ..deps import session_email
from ..models import (Client, Company, CustomField, FitscoreRule, Goal, Holiday,
                      Integration, Lead, LeadActivity, LostReason, Team, User, Webhook)
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
               "LEADBASE_UPLOAD", "STATISTICS_ACCESS"]


def _company(db: Session) -> Company:
    c = db.query(Company).first()
    if not c:
        raise HTTPException(500, "Empresa não inicializada.")
    return c


def _current_user(db: Session) -> User | None:
    email = session_email()
    return db.query(User).filter(func.lower(User.email) == (email or "").lower()).first()


@router.get("/me")
def me(db: Session = Depends(get_db)):
    """Usuário operacional da sessão. Casa o e-mail da sessão CapiBLU com o
    cadastro de SDR.

    Sem perfil de CRM correspondente (login liberado antes de alguém rodar
    `POST /users` pra essa pessoa), a identidade é sintética a partir do
    e-mail da sessão — nunca a de outra conta. Antes disto caía "em
    qualquer administrador", e quem estivesse nessa janela editava
    (PATCH /me, POST /me/avatar) o cadastro do administrador de verdade.
    """
    u = _current_user(db)
    c = _company(db)
    if u:
        base = user_full(u)
    else:
        email = session_email()
        base = {"id": None, "name": email, "email": email,
                "initials": (email[:2] or "?").upper(), "avatarUrl": "",
                "roles": [], "dailyGoal": 0, "team": None, "active": True,
                "online": False, "created": None, "emailSignature": ""}
    return {**base, "companyId": c.id, "nivel": perm.ator(db).nivel,
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
    if "emailFrom" in payload:
        # Endereço fora de domínio verificado é recusado pelo provedor na hora
        # do envio — melhor barrar aqui, com o motivo, do que descobrir na
        # primeira cadência que não saiu.
        novo = (payload["emailFrom"] or "").strip().lower()
        if novo:
            if "@" not in novo:
                raise HTTPException(400, "Endereço inválido.")
            dominio = novo.split("@")[-1]
            empresa = _company(db)
            # O domínio de referência é o do remetente da empresa; quando ela
            # não definiu um, vale o do relay configurado no ambiente — que é
            # o único que o provedor aceita de fato.
            padrao = ((empresa.email_from_address or "")
                      or os.environ.get("CAPIBLU_SMTP_DE", "")
                      or os.environ.get("SMTP_FROM", "")).split("@")[-1].strip(" <>")
            if padrao and dominio != padrao:
                raise HTTPException(400, f"O domínio precisa ser {padrao} — é o verificado "
                                         "para envio.")
        u.email_from = novo
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
    except Exception:
        # Mensagem genérica de propósito — o detalhe da exceção do Pillow
        # pode revelar formato/versão da biblioteca no servidor.
        raise HTTPException(400, "Não consegui processar essa imagem. Tente outro arquivo.")
    u.avatar_url = f"/uploads/avatars/{u.id}.jpg?v={int(datetime.utcnow().timestamp())}"
    db.commit()
    return user_full(u)


@router.get("/me/company")
def my_company(db: Session = Depends(get_db)):
    c = _company(db)
    return {"id": c.id, "name": c.name, "phone": c.phone, "site": c.site,
            "modules": c.modules.split(","),
            "addOns": c.add_ons.split(",") if c.add_ons else [],
            "status": c.status, "monthlyValue": c.monthly_value,
            "seatPrice": c.seat_price, "minutePrice": c.minute_price}


@router.get("/users/me/permissions")
def my_permissions(db: Session = Depends(get_db)):
    """Gestor e admin têm tudo. SDR só o que a empresa liberou em
    Ajustes > Permissões — antes essa lista era fixa pra todo mundo."""
    if perm.ator(db).pelo_menos("gestor"):
        return PERMISSIONS
    c = _company(db)
    # "CAPIBLU_ACCESS" saiu daqui — não é uma permissão de verdade, nenhuma
    # rota de capiblu.py confere isso, e não existe toggle em Ajustes pra
    # desligar. Listar como se fosse configurável só prometia um controle
    # que não existe.
    out = []
    if c.leads_visible_all:
        out.append("LEADS_VIEW_ALL")
    if c.leads_add_manual:
        out.append("LEADS_ADD_MANUAL")
    if c.leads_delete:
        out.append("LEADS_DELETE")
    if c.regular_user_can_import:
        out.append("LEADBASE_UPLOAD")
    if c.statistics_access:
        out.append("STATISTICS_ACCESS")
    return out


@router.get("/flow/permissions/configuration")
def permissions_config(db: Session = Depends(get_db)):
    c = _company(db)
    return {"leadsVisibleAll": c.leads_visible_all, "leadsAddManual": c.leads_add_manual,
            "leadbaseUpload": c.regular_user_can_import, "statisticsAccess": c.statistics_access,
            "leadsDelete": c.leads_delete}


@router.patch("/flow/permissions/configuration")
def update_permissions_config(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "configurar permissões")
    c = _company(db)
    if "leadsVisibleAll" in payload:
        c.leads_visible_all = bool(payload["leadsVisibleAll"])
    if "leadsAddManual" in payload:
        c.leads_add_manual = bool(payload["leadsAddManual"])
    if "leadsDelete" in payload:
        c.leads_delete = bool(payload["leadsDelete"])
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


@router.get("/flow/email/domains")
async def email_domains(db: Session = Depends(get_db)):
    """Domínios de envio e o estado do DNS de cada um, direto do Resend.

    É a tela `company/email-whitelabel` do original. Só LEITURA: cadastrar
    domínio cria recurso na conta do provedor, e isso é decisão de quem paga
    a conta, não efeito colateral de abrir uma tela.

    A chave é a mesma senha SMTP — no Resend a senha do relay É a API key.
    """
    perm.ator(db).exigir("gestor", "ver domínios de envio")
    chave = _chave_resend()
    if not chave.startswith("re_"):
        return {"configurado": False,
                "motivo": "Sem chave do Resend no ambiente — a tela não tem o que consultar.",
                "dominios": []}
    try:
        async with httpx.AsyncClient(timeout=15) as cli:
            r = await cli.get("https://api.resend.com/domains",
                              headers={"Authorization": f"Bearer {chave}"})
            r.raise_for_status()
            lista = r.json().get("data", [])
            # O registro DNS só vem no detalhe — sem ele a tela diria
            # "pendente" sem dizer o que publicar, que é o que resolve.
            for d in lista:
                det = await cli.get(f"https://api.resend.com/domains/{d['id']}",
                                    headers={"Authorization": f"Bearer {chave}"})
                d["records"] = det.json().get("records", []) if det.status_code == 200 else []
    except Exception as exc:  # noqa: BLE001
        return {"configurado": True, "motivo": f"{type(exc).__name__} ao falar com o Resend.",
                "dominios": []}
    return {"configurado": True, "motivo": "", "dominios": [
        {"id": d.get("id"), "nome": d.get("name"), "status": d.get("status"),
         "regiao": d.get("region"), "criado": d.get("created_at", "")[:10],
         "envio": (d.get("capabilities") or {}).get("sending"),
         "registros": [{"tipo": rg.get("record"), "nome": rg.get("name"),
                        "valor": rg.get("value"), "status": rg.get("status"),
                        "prioridade": rg.get("priority")}
                       for rg in d.get("records", [])]}
        for d in lista]}


def _chave_resend() -> str:
    """A chave é a mesma senha SMTP — no Resend a senha do relay É a API key."""
    return (os.environ.get("CAPIBLU_SMTP_SENHA") or os.environ.get("RESEND_API_KEY") or "").strip()


@router.post("/flow/email/domains")
async def criar_dominio(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Cadastra um domínio de envio no Resend.

    Cria recurso na conta do provedor, então é do gestor e vem com o aviso na
    tela. O domínio nasce sem verificação: o que ele devolve são os registros
    de DNS que alguém precisa publicar.
    """
    perm.ator(db).exigir("gestor", "cadastrar domínio de envio")
    nome = (payload.get("nome") or "").strip().lower().lstrip("@")
    if not nome or "." not in nome or " " in nome:
        raise HTTPException(400, "Informe um domínio válido, como suaempresa.com.br.")
    chave = _chave_resend()
    if not chave.startswith("re_"):
        raise HTTPException(400, "Sem chave do Resend no ambiente.")
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post("https://api.resend.com/domains",
                               headers={"Authorization": f"Bearer {chave}"},
                               json={"name": nome, "region": payload.get("regiao") or "sa-east-1"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__} ao falar com o Resend.")
    corpo = r.json() if r.content else {}
    if r.status_code >= 400:
        raise HTTPException(400, corpo.get("message") or f"Resend recusou (HTTP {r.status_code}).")
    return {"id": corpo.get("id"), "nome": corpo.get("name"), "status": corpo.get("status"),
            "registros": corpo.get("records", [])}


@router.post("/flow/email/domains/{did}/verificar")
async def verificar_dominio(did: str, db: Session = Depends(get_db)):
    """Pede ao Resend para checar o DNS de novo.

    A verificação é assíncrona lá: o retorno diz que o pedido entrou, não que
    o domínio já está verificado — por isso a tela recarrega a lista depois.
    """
    perm.ator(db).exigir("gestor", "verificar domínio de envio")
    chave = _chave_resend()
    if not chave.startswith("re_"):
        raise HTTPException(400, "Sem chave do Resend no ambiente.")
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.post(f"https://api.resend.com/domains/{did}/verify",
                               headers={"Authorization": f"Bearer {chave}"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__} ao falar com o Resend.")
    if r.status_code >= 400:
        raise HTTPException(400, f"Resend recusou (HTTP {r.status_code}).")
    return {"ok": True}


@router.delete("/flow/email/domains/{did}")
async def remover_dominio(did: str, db: Session = Depends(get_db)):
    """Remove o domínio da conta do Resend.

    Some de vez, e todo envio por aquele domínio para de sair. Só admin, e a
    tela confirma antes — é o tipo de botão que não pode ser um clique
    distraído.
    """
    perm.ator(db).exigir("admin", "remover domínio de envio")
    chave = _chave_resend()
    if not chave.startswith("re_"):
        raise HTTPException(400, "Sem chave do Resend no ambiente.")
    try:
        async with httpx.AsyncClient(timeout=20) as cli:
            r = await cli.delete(f"https://api.resend.com/domains/{did}",
                                 headers={"Authorization": f"Bearer {chave}"})
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(502, f"{type(exc).__name__} ao falar com o Resend.")
    if r.status_code >= 400:
        raise HTTPException(400, f"Resend recusou (HTTP {r.status_code}).")
    return {"ok": True}


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


def _emails_com_login() -> set[str]:
    """E-mails que têm conta no CapiBLU — é o login das duas ferramentas.

    Sem isso, um usuário da operação cadastrado aqui parece pronto mas não
    consegue entrar, e ninguém descobre até ele tentar. Uma leitura só, em
    vez de uma consulta por linha.
    """
    try:
        import auth as capiblu_auth
        return {(u.get("email") or "").lower() for u in capiblu_auth.list_users()}
    except Exception:
        # Sem a base de contas o resto da tela continua de pé; o que some é
        # só o aviso de cadastro incompleto.
        return set()


@router.get("/roles/preview")
def roles_preview(db: Session = Depends(get_db)):
    """O que cada papel passa a poder — a prévia do formulário de usuário.

    Sai de `perm.py`, não de uma lista escrita à mão na tela: ADMINISTRATOR e
    MANAGER viram nível "gestor", o resto fica em "sdr", e o que o SDR pode
    além da própria carteira é o que a empresa liberou em Permissões.
    """
    c = _company(db)
    liberadas = [nome for nome, ligado in (
        ("ver leads de todo mundo", c.leads_visible_all),
        ("adicionar lead individualmente", c.leads_add_manual),
        ("importar lista de leads", c.regular_user_can_import),
        ("acessar Estatísticas", c.statistics_access),
        ("apagar os próprios leads", c.leads_delete)) if ligado]
    comum = ["trabalhar a própria carteira de leads",
             "executar a fila e registrar atividade",
             "conversar no WhatsApp dos próprios leads"]
    gestor = ["ver e editar leads de todo o time", "painel de controle e estatísticas",
              "definir metas, cadências e motivos de perda",
              "dar feedback de coaching nas ligações", "configurar canais e testar envio"]
    admin = ["criar, editar e excluir usuários", "criar e remover times",
             "editar dados da empresa", "gerenciar webhooks e tokens de API"]
    return {"roles": [
        {"key": "ADMINISTRATOR", "label": "Administrador", "nivel": "gestor",
         "pode": comum + gestor + admin,
         "nota": "Administrador da operação. Administrar a plataforma (contas de acesso) "
                 "continua sendo do admin do CapiBLU."},
        {"key": "MANAGER", "label": "Gestor", "nivel": "gestor", "pode": comum + gestor,
         "nota": "Enxerga o time inteiro, mas não mexe em usuários nem na empresa."},
        {"key": "SALESMAN", "label": "Vendedor", "nivel": "sdr", "pode": comum,
         "nota": "Além disso, só o que a empresa liberou em Permissões."},
        {"key": "SDR", "label": "SDR", "nivel": "sdr", "pode": comum,
         "nota": "Mesmo nível do vendedor."},
    ], "liberadoParaSdr": liberadas}


@router.get("/users")
def list_users(q: str | None = None, active: bool | None = None,
               team_id: int | None = None, role: str | None = None,
               page: int = 1, per_page: int = 200, db: Session = Depends(get_db)):
    # Fica aberto pra qualquer nível de propósito — dropdown de "transferir
    # lead"/"responsáveis da cadência" precisa disso pro SDR também, não só
    # pro gestor. O que não faz sentido é peer ver a meta diária individual
    # de peer; isso sai da resposta pra quem não é gestor+ (menos a própria).
    ator = perm.ator(db)
    gestor = ator.pelo_menos("gestor")
    query = db.query(User)
    if q:
        alvo = f"%{q.strip()}%"
        query = query.filter(or_(User.name.ilike(alvo), User.email.ilike(alvo)))
    if active is not None:
        query = query.filter(User.active == active)
    if team_id:
        query = query.filter(User.team_id == team_id)
    if role:
        # `roles` é uma string separada por vírgula; o LIKE tem que casar o
        # papel inteiro, senão "SDR" traria "SDR_MANAGER" se um dia existir.
        query = query.filter(or_(User.roles == role, User.roles.like(f"{role},%"),
                                 User.roles.like(f"%,{role}"), User.roles.like(f"%,{role},%")))
    total = query.count()
    per_page = max(5, min(500, per_page))
    page = max(1, page)
    users = (query.order_by(User.id).offset((page - 1) * per_page).limit(per_page).all())

    # Leads por dono numa consulta só — a coluna existe para explicar por que
    # o botão de excluir fica travado.
    ids = [u.id for u in users]
    leads = dict(db.query(Lead.sdr_id, func.count(Lead.id))
                 .filter(Lead.sdr_id.in_(ids or [-1]))
                 .group_by(Lead.sdr_id).all()) if ids else {}
    com_login = _emails_com_login() if gestor else set()

    data = []
    for u in users:
        row = user_full(u)
        if not gestor and u.id != ator.user_id:
            row.pop("dailyGoal", None)
        if gestor:
            row["leads"] = leads.get(u.id, 0)
            row["temLogin"] = (u.email or "").lower() in com_login if com_login else None
        data.append(row)
    total_pages = max(1, -(-total // per_page))
    return {"data": data,
            "pagination": {"page": page, "perPage": per_page, "totalRowCount": total,
                           "totalPageCount": total_pages, "hasPrev": page > 1,
                           "hasNext": page < total_pages}}


@router.delete("/users/{uid}")
def delete_user(uid: int, db: Session = Depends(get_db)):
    """Exclusão definitiva — o que o Meetime chama de "remover da empresa".

    Três travas: ninguém se exclui, o último administrador ativo não sai (a
    empresa ficaria sem quem gerencia), e quem tem lead ou atividade no nome
    não some — apagar levaria o histórico junto. Para esses, o caminho é
    inativar.
    """
    ator = perm.ator(db)
    ator.exigir("admin", "excluir usuário")
    u = db.get(User, uid)
    if not u:
        raise HTTPException(404, "Usuário não encontrado.")
    if u.id == ator.user_id:
        raise HTTPException(400, "Você não pode excluir a si mesmo.")
    if "ADMINISTRATOR" in u.role_list:
        outros = [x for x in db.query(User).filter(User.active.is_(True)).all()
                  if x.id != u.id and "ADMINISTRATOR" in x.role_list]
        if not outros:
            raise HTTPException(400, "É o último administrador ativo — promova outra "
                                     "pessoa antes de excluir.")
    n_leads = db.query(func.count(Lead.id)).filter(Lead.sdr_id == uid).scalar()
    n_ativ = db.query(func.count(LeadActivity.id)).filter(LeadActivity.user_id == uid).scalar()
    if n_leads or n_ativ:
        raise HTTPException(400, f"{u.name} tem {n_leads} lead(s) e {n_ativ} atividade(s) "
                                 "no nome. Transfira ou inative em vez de excluir — "
                                 "excluir levaria o histórico junto.")
    db.delete(u)
    db.commit()
    return {"ok": True}


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


@router.post("/teams")
def create_team(payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("admin", "criar time")
    nome = (payload.get("name") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome do time é obrigatório.")
    if db.query(Team).filter(func.lower(Team.name) == nome.lower()).first():
        raise HTTPException(400, "Já existe um time com esse nome.")
    t = Team(name=nome)
    db.add(t)
    db.flush()
    _definir_membros(db, t, payload.get("userIds"))
    db.commit()
    return {"id": t.id, "name": t.name}


@router.patch("/teams/{tid}")
def update_team(tid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("admin", "editar time")
    t = db.get(Team, tid)
    if not t:
        raise HTTPException(404, "Time não encontrado.")
    if "name" in payload:
        nome = (payload["name"] or "").strip()
        if not nome:
            raise HTTPException(400, "Nome do time é obrigatório.")
        t.name = nome
    if "userIds" in payload:
        _definir_membros(db, t, payload["userIds"])
    db.commit()
    return {"id": t.id, "name": t.name}


@router.delete("/teams/{tid}")
def delete_team(tid: int, db: Session = Depends(get_db)):
    """Apaga o time, não as pessoas — elas voltam a ficar sem time."""
    perm.ator(db).exigir("admin", "remover time")
    t = db.get(Team, tid)
    if not t:
        raise HTTPException(404, "Time não encontrado.")
    db.query(User).filter(User.team_id == tid).update({"team_id": None},
                                                      synchronize_session=False)
    db.delete(t)
    db.commit()
    return {"ok": True}


def _definir_membros(db: Session, time: Team, ids) -> None:
    """Quem está no time passa a ser exatamente esta lista.

    Tira de quem saiu antes de pôr em quem entrou — um usuário só pertence a
    um time, então trocar de time é sair de um e entrar no outro.
    """
    if ids is None:
        return
    novos = {int(i) for i in ids}
    db.query(User).filter(User.team_id == time.id, ~User.id.in_(novos or [0])) \
        .update({"team_id": None}, synchronize_session=False)
    if novos:
        db.query(User).filter(User.id.in_(novos)) \
            .update({"team_id": time.id}, synchronize_session=False)


@router.patch("/me/company")
def update_company(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Dados gerais da empresa — nome, telefone e site."""
    perm.ator(db).exigir("admin", "editar dados da empresa")
    c = _company(db)
    for chave, attr in (("name", "name"), ("phone", "phone"), ("site", "site")):
        if chave in payload:
            valor = (payload[chave] or "").strip()
            if chave == "name" and not valor:
                raise HTTPException(400, "Nome da empresa é obrigatório.")
            setattr(c, attr, valor)
    db.commit()
    return my_company(db)


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
            "leadStageFieldId": c.lead_stage_field_id,
            "responseTimeGoalHours": c.response_time_goal_hours,
            "fitscoreEnabled": c.fitscore_enabled,
            "minutePrice": c.minute_price, "seatPrice": c.seat_price,
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
    if "fitscoreEnabled" in payload:
        c.fitscore_enabled = bool(payload["fitscoreEnabled"])
    if "minutePrice" in payload:
        c.minute_price = max(0.0, float(payload["minutePrice"] or 0))
    if "seatPrice" in payload:
        c.seat_price = max(0.0, float(payload["seatPrice"] or 0))
    if "responseTimeGoalHours" in payload:
        c.response_time_goal_hours = max(1, int(payload["responseTimeGoalHours"] or 24))
    if "leadStageFieldId" in payload:
        # Vazio desliga o funil por etapa; o valor tem que ser um campo que existe.
        fid = payload["leadStageFieldId"]
        c.lead_stage_field_id = int(fid) if fid else None
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


@router.patch("/flow/lost-reasons/{rid}")
def update_lost_reason(rid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Renomear em vez de apagar e recriar: o motivo já está apontado por
    leads perdidos, e recriar perderia esse vínculo."""
    perm.ator(db).exigir("gestor", "editar motivo de perda")
    r = db.get(LostReason, rid)
    if not r:
        raise HTTPException(404, "Motivo não encontrado.")
    nome = (payload.get("name") or "").strip()
    if not nome:
        raise HTTPException(400, "Nome obrigatório.")
    r.name = nome
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
                    "wonMandatory": f.won_mandatory, "lostMandatory": f.lost_mandatory,
                    "options": [o.strip() for o in (f.options or "").splitlines() if o.strip()]})
    return out


@router.patch("/flow/new-lead-fields/{fid}")
def update_field(fid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Nome, visibilidade, ordem, obrigatoriedade e opções.

    O identificador NÃO muda: é a chave usada em `LeadFieldValue` e nas merge
    tags dos modelos — renomear quebraria o valor já gravado em cada lead.
    """
    perm.ator(db).exigir("gestor", "editar campo personalizado")
    f = db.get(CustomField, fid)
    if not f:
        raise HTTPException(404, "Campo não encontrado.")
    if "name" in payload:
        nome = (payload["name"] or "").strip()
        if not nome:
            raise HTTPException(400, "Nome do campo é obrigatório.")
        f.name = nome
    if "visible" in payload:
        f.visible = bool(payload["visible"])
    if "index" in payload:
        f.index = int(payload["index"] or 0)
    if "wonMandatory" in payload:
        f.won_mandatory = bool(payload["wonMandatory"])
    if "lostMandatory" in payload:
        f.lost_mandatory = bool(payload["lostMandatory"])
    if "options" in payload:
        valor = payload["options"]
        linhas = valor if isinstance(valor, list) else str(valor).splitlines()
        f.options = "\n".join(o.strip() for o in linhas if str(o).strip())
    db.commit()
    return {"id": f.id, "options": [o for o in f.options.splitlines() if o]}


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
    # O identificador vai junto: é por ele que a tela do lead casa a regra com
    # o valor gravado e mostra qual bateu.
    return [{"id": r.id, "fieldId": r.field_id, "fieldName": r.field.name if r.field else "",
             "fieldIdentifier": r.field.identifier if r.field else "",
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
    """Um feriado, ou um intervalo deles.

    Recesso de fim de ano é uma semana inteira; cadastrar dia a dia era seis
    cliques e uma chance de esquecer um.
    """
    perm.ator(db).exigir("gestor", "cadastrar feriado")
    try:
        day = date.fromisoformat(payload["date"])
    except (KeyError, ValueError):
        raise HTTPException(400, "Data inválida (use AAAA-MM-DD).")
    fim = day
    if payload.get("endDate"):
        try:
            fim = date.fromisoformat(payload["endDate"])
        except ValueError:
            raise HTTPException(400, "Data final inválida (use AAAA-MM-DD).")
        if fim < day:
            raise HTTPException(400, "A data final é anterior à inicial.")
        if (fim - day).days > 60:
            raise HTTPException(400, "Intervalo longo demais (máximo 60 dias).")
    nome = (payload.get("name") or "").strip()
    criados = []
    existentes = {h.day for h in db.query(Holiday).filter(Holiday.day.between(day, fim)).all()}
    atual = day
    while atual <= fim:
        if atual not in existentes:      # repetir o mesmo dia não adiciona nada
            h = Holiday(day=atual, name=nome)
            db.add(h)
            criados.append(h)
        atual += timedelta(days=1)
    db.commit()
    return [{"id": h.id, "date": h.day.isoformat(), "name": h.name} for h in criados]


@router.patch("/flow/configuration/holidays/{hid}")
def update_holiday(hid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "editar feriado")
    h = db.get(Holiday, hid)
    if not h:
        raise HTTPException(404, "Feriado não encontrado.")
    if "name" in payload:
        h.name = (payload["name"] or "").strip()
    if payload.get("date"):
        try:
            h.day = date.fromisoformat(payload["date"])
        except ValueError:
            raise HTTPException(400, "Data inválida (use AAAA-MM-DD).")
    db.commit()
    return {"id": h.id, "date": h.day.isoformat(), "name": h.name}


@router.delete("/flow/configuration/holidays/{hid}")
def delete_holiday(hid: int, db: Session = Depends(get_db)):
    perm.ator(db).exigir("gestor", "remover feriado")
    h = db.get(Holiday, hid)
    if h:
        db.delete(h)
        db.commit()
    return {"ok": True}


# ── Integrações, webhooks, financeiro ──
@router.get("/integrations")
def integrations(db: Session = Depends(get_db)):
    return [{"id": i.id, "key": i.key, "name": i.name, "kind": i.kind,
             "connected": i.connected, "lastSync": iso(i.last_sync)}
            for i in db.query(Integration).order_by(Integration.name)]


@router.get("/integrations/zenvia/status")
async def zenvia_status():
    """Saldo e números da conta Zenvia Voice, lidos na hora.

    É o que decide se a telefonia pode ligar: sem DID comprado não há de onde
    sair a chamada, e sem saldo ela não completa. Guardar esse estado no banco
    só criaria uma cópia velha de um número que muda a cada ligação.
    """
    token = os.environ.get("ZENVIA_VOICE_TOKEN") or ""
    if not token:
        return {"configurado": False, "motivo": "Falta ZENVIA_VOICE_TOKEN no .env."}
    base = "https://voice-api.zenvia.com"
    headers = {"Access-Token": token}
    try:
        async with httpx.AsyncClient(timeout=12.0, headers=headers) as cli:
            saldo_r, did_r = await asyncio.gather(cli.get(f"{base}/saldo"),
                                                  cli.get(f"{base}/did"))
    except Exception as e:  # rede fora, DNS, timeout
        return {"configurado": True, "erro": f"Não consegui falar com a Zenvia: {e}"}
    saldo = (saldo_r.json().get("dados") or {}).get("saldo") if saldo_r.status_code == 200 else None
    dids = ((did_r.json().get("dados") or {}).get("dids") or []) if did_r.status_code == 200 else []
    # Um centavo é saldo positivo e não paga ligação nenhuma: o corte útil é
    # um real, senão a tela diria "pronto para ligar" e a chamada cairia.
    return {"configurado": True, "saldo": saldo, "dids": dids, "saldoMinimo": 1,
            "podeLigar": bool(dids) and (saldo or 0) >= 1,
            "erro": "" if saldo_r.status_code == 200 else f"HTTP {saldo_r.status_code} ao ler o saldo"}


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
    erro = webhooks_engine.url_publica_valida(url)
    if erro:
        raise HTTPException(400, erro)
    w = Webhook(events=",".join(payload.get("events") or ["LEAD.WON"]), target_url=url,
                secret=payload.get("secret", ""))
    db.add(w)
    db.commit()
    return {"id": w.id, "events": w.events.split(","), "targetUrl": w.target_url}


@router.patch("/webhooks/{wid}")
def update_webhook(wid: int, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Liga, desliga e reaponta um webhook.

    Antes só dava para remover: um destino fora do ar tinha que ser apagado e
    recadastrado depois, perdendo a data de criação e o histórico de entrega.
    """
    perm.ator(db).exigir("admin", "editar webhook")
    w = db.get(Webhook, wid)
    if not w:
        raise HTTPException(404, "Webhook nao encontrado.")
    if "enabled" in payload:
        w.enabled = bool(payload["enabled"])
    if payload.get("targetUrl"):
        url = str(payload["targetUrl"]).strip()
        if not url.startswith(("http://", "https://")):
            raise HTTPException(400, "A URL precisa comecar com http:// ou https://.")
        w.target_url = url
    if payload.get("events"):
        w.events = ",".join(str(e).strip() for e in payload["events"] if str(e).strip())
    db.commit()
    return {"id": w.id, "targetUrl": w.target_url, "enabled": w.enabled,
            "events": [e for e in w.events.split(",") if e]}


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
    rows = [g for g in db.query(Goal).filter_by(target_month=month).all() if g.user]
    total = sum(g.opportunities_goal for g in rows)
    return {"targetMonth": month.isoformat(),
            # Totais da empresa: é por eles que o original começa, e depois
            # distribui entre os participantes.
            "company": {"opportunitiesGoal": total,
                        "conversionRateGoal": (round(sum(g.conversion_rate_goal for g in rows)
                                                     / len(rows), 4) if rows else 0.15)},
            "usersGoals": [{"user": {"id": g.user.id, "name": g.user.name},
                            "opportunitiesGoal": g.opportunities_goal,
                            "conversionRateGoal": g.conversion_rate_goal} for g in rows]}


@router.put("/flow/goals/{ref}")
def set_goals(ref: str, payload: dict = Body(...), db: Session = Depends(get_db)):
    """Grava a lista de participantes inteira.

    Quem não vem no corpo deixa de ser participante do mês — antes não havia
    como tirar alguém: a meta de um SDR que saiu do time continuava somando
    no total da empresa para sempre.
    """
    perm.ator(db).exigir("gestor", "definir metas do time")
    d = date.fromisoformat(ref) if ref else date.today()
    month = date(d.year, d.month, 1)
    enviados = set()
    for item in payload.get("usersGoals", []):
        uid = int(item["userId"])
        enviados.add(uid)
        g = db.query(Goal).filter_by(user_id=uid, target_month=month).first()
        if not g:
            g = Goal(user_id=uid, target_month=month)
            db.add(g)
        g.opportunities_goal = int(item.get("opportunitiesGoal", 25))
        g.conversion_rate_goal = float(item.get("conversionRateGoal", 0.15))
    (db.query(Goal).filter(Goal.target_month == month, Goal.user_id.notin_(enviados or [-1]))
     .delete(synchronize_session=False))
    db.commit()
    return goals(ref, db)
