"""Serialização — mantém o formato de resposta compatível com a API do Meetime."""
import json
from datetime import datetime, timezone

from . import agenda
from .models import PRIORITY_WEIGHT, channel_of


def iso(dt: datetime | None) -> str | None:
    return dt.isoformat(timespec="seconds") + "Z" if dt else None


def instante(valor) -> datetime | None:
    """Lê um instante vindo do cliente e devolve datetime ingênuo em UTC.

    O `iso()` daqui devolve "…Z", e é isso que o `toISOString()` do navegador
    manda de volta. Só que `fromisoformat("…Z")` produz datetime COM fuso, e
    comparar aware com ingênuo — que é o que está nas colunas — levanta
    TypeError. O erro aparecia depois do commit: a linha entrava no banco e o
    cliente recebia 500, então quem tentasse de novo criava duplicata.

    Devolve None quando a string não é uma data — quem chama decide se isso
    é 400 ou se cai num padrão.
    """
    if not valor:
        return None
    try:
        d = datetime.fromisoformat(str(valor).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d.replace(tzinfo=None) if d.tzinfo is None else         d.astimezone(timezone.utc).replace(tzinfo=None)


def user_min(u):
    if not u:
        return None
    return {"id": u.id, "name": u.name, "email": u.email, "initials": u.initials,
            "avatarUrl": u.avatar_url or ""}


def user_full(u):
    if not u:
        return None
    return {**user_min(u), "roles": u.role_list, "dailyGoal": u.daily_goal,
            "team": {"id": u.team.id, "name": u.team.name} if u.team else None,
            "active": u.active, "online": u.online, "created": iso(u.created_at),
            "emailSignature": u.email_signature or "",
            "emailFrom": u.email_from or "",
            "zenviaRamal": u.zenvia_ramal or ""}


def client(c):
    if not c:
        return None
    return {"id": c.id, "name": c.name, "slug": c.slug, "color": c.color, "active": c.active}


def activity(a):
    if not a:
        return None
    out = {"id": a.id, "name": a.name, "type": a.type, "instruction": a.instruction,
           "channel": channel_of(a.type, a.social_network), "clientId": a.client_id}
    if a.social_network:
        out["socialNetwork"] = a.social_network
    if a.type == "E_MAIL":
        out["emailTemplate"] = {"subject": a.email_subject, "html": a.email_html}
    return out


def cadence(c, overview=None, users=None):
    return {
        "id": c.id, "name": c.name, "description": c.description, "type": c.type,
        "cadenceFocus": c.focus, "priority": c.priority, "executing": c.executing,
        "stepsCount": len(c.steps), "client": client(c.client),
        "users": [user_min(u) for u in (users or [])],
        "overview": overview, "created": iso(c.created_at),
    }


def cadence_step(s):
    return {"id": s.id, "day": s.day, "order": s.order_in_day,
            "activity": activity(s.activity), "templateId": s.template_id,
            "templateName": s.template.name if s.template else ""}


def lead(l, custom=None, fitscore=None):
    return {
        "id": l.id, "name": l.name, "firstName": l.first_name, "email": l.email,
        "company": l.company, "position": l.position, "phone": l.phone, "site": l.site,
        "state": l.state, "city": l.city, "linkedIn": l.linkedin,
        "annotations": l.annotations, "externalReference": l.external_reference,
        "cnpj": l.cnpj, "cpf": l.cpf, "razaoSocial": l.razao_social,
        "decisionLevel": l.decision_level, "contactKind": l.contact_kind,
        "phoneKind": l.phone_kind, "whatsapp": l.whatsapp, "doNotCall": l.do_not_call,
        "status": l.status, "currentStep": l.current_step, "bestHour": l.best_hour,
        "cadence": {"id": l.cadence.id, "name": l.cadence.name} if l.cadence else None,
        "sdr": user_min(l.sdr), "client": client(l.client),
        "leadBase": {"id": l.lead_base.id, "name": l.lead_base.name} if l.lead_base else None,
        "lostReason": {"id": l.lost_reason.id, "name": l.lost_reason.name} if l.lost_reason else None,
        "wonAt": iso(l.won_at), "lostAt": iso(l.lost_at), "createdAt": iso(l.created_at),
        "source": l.source, "channel": l.channel, "campaign": l.campaign,
        "inbound": l.inbound,
        "reprospect": ({"date": l.reprospect_at.isoformat(), "cadenceId": l.reprospect_cadence_id}
                       if l.reprospect_at else None),
        "customFields": custom or {}, "fitscore": fitscore or 0,
    }


def lead_activity(la, overdue_ref=None):
    late = bool(overdue_ref and la.status == "PENDING" and la.scheduled_at < overdue_ref)
    return {
        "id": la.id, "type": la.type, "socialNetwork": la.social_network,
        "channel": channel_of(la.type, la.social_network),
        "status": la.status, "scheduledAt": iso(la.scheduled_at), "doneAt": iso(la.done_at),
        "notes": la.notes, "late": late,
        # Atividade sem passo de cadência é, por construção, extra — a fila e
        # a linha do tempo marcam isso, e antes só a fila sabia.
        "extra": la.cadence_step_id is None,
        "activity": activity(la.activity), "user": user_min(la.user),
        "lead": {"id": la.lead.id, "name": la.lead.name, "company": la.lead.company,
                 "phone": la.lead.phone, "email": la.lead.email,
                 "bestHour": la.lead.best_hour, "status": la.lead.status,
                 "cadence": {"id": la.lead.cadence.id, "name": la.lead.cadence.name,
                             "priority": la.lead.cadence.priority} if la.lead.cadence else None,
                 "client": client(la.lead.client),
                 "leadBase": ({"id": la.lead.lead_base.id, "name": la.lead.lead_base.name}
                              if la.lead.lead_base else None)} if la.lead else None,
    }


def call(c):
    return {
        "id": c.id, "user": user_min(c.user),
        "originPhone": c.origin_phone, "receiverPhone": c.receiver_phone,
        "receiverType": c.receiver_type, "status": c.status, "output": c.output,
        "receiverConnectedDuration": c.duration, "receiverPrice": c.price,
        "important": c.important, "originStarted": iso(c.started_at),
        "flowLeadId": c.lead_id, "provider": c.provider or "",
        # A URL da gravação não sai daqui: ela é pública na Zenvia. Quem pode
        # ouvir pede por GET /api/dialer/calls/{id}/gravacao, que confere o dono.
        "temGravacao": bool(c.recording_url),
        "flowLeadName": c.lead.name if c.lead else None,
        "flowLeadCompany": c.lead.company if c.lead else None,
    }


def _json_ou_lista(texto):
    """Amostra de descarte gravada como JSON; base antiga não tem nada."""
    try:
        return json.loads(texto or "[]")
    except ValueError:
        return []


def lead_base(b):
    return {"id": b.id, "name": b.name, "status": b.status, "source": b.source,
            "sourceQuery": b.source_query, "numberOfLeads": b.number_of_leads,
            "discardedLeads": b.discarded_leads, "client": client(b.client),
            "createdBy": user_min(b.created_by), "created": iso(b.created_at),
            "discardedSample": _json_ou_lista(b.discarded_sample)}


def queue_score(la, now) -> float:
    """Fila priorizada — o que o Meetime não faz.

    Combina atraso, prioridade da cadência e proximidade da janela de melhor
    contato do lead. Quanto maior, mais cedo a atividade deve ser trabalhada.
    """
    hours_late = max(0.0, (now - la.scheduled_at).total_seconds() / 3600)
    prio = PRIORITY_WEIGHT.get(la.lead.cadence.priority, 2) if la.lead and la.lead.cadence else 2
    best = la.lead.best_hour if la.lead else 18
    # `now` e `scheduled_at` são UTC; `best_hour` é hora de Brasília. Sem a
    # conversão a janela das 18h abria às 15h.
    hour_local = agenda.to_local(now).hour
    window = max(0, 6 - abs(hour_local - best))        # 6 na hora exata, 0 longe demais
    call_bonus = 3 if la.type == "CALL" else 0
    return round(hours_late * 1.5 + prio * 6 + window * 2.5 + call_bonus, 2)
