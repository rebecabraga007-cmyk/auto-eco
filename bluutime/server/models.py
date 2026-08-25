"""Domínio do Bluutime.

Espelha os enums e campos reais capturados da API do Meetime (ver
RELATORIO-MEETIME.md) e acrescenta as três coisas que faltam lá:
`Client` como entidade, `LeadBase.source` apontando para o CapiBLU e
`Lead.priority_score` para a fila priorizada.
"""
from datetime import datetime, date

from sqlalchemy import (Boolean, Date, DateTime, Float, ForeignKey, Integer,
                        String, Text, UniqueConstraint)
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .db import Base

LEAD_STATUS = ["WAITING", "EXECUTING", "ON_EXTRA_ACTIVITY", "PAUSED_FROM_EXECUTING",
               "WON", "LOST", "SWITCHED_CADENCE"]
ACTIVITY_TYPES = ["SEARCH", "CALL", "E_MAIL", "SOCIAL_POINT"]

# O canal é a pergunta que o resto do sistema faz ("por onde isso sai?"), e
# `SOCIAL_POINT` sozinho não responde: WhatsApp e LinkedIn são o mesmo tipo.
# O armazenamento continua igual ao do Meetime — o canal é derivado.
CHANNELS = ["CALL", "EMAIL", "WHATSAPP", "SOCIAL", "SEARCH"]


def channel_of(type_: str, social_network: str = "") -> str:
    """Canal de uma atividade — o vocabulário único de `Template.channel`."""
    if type_ == "E_MAIL":
        return "EMAIL"
    if type_ == "SOCIAL_POINT":
        return "WHATSAPP" if (social_network or "").upper() == "WHATSAPP" else "SOCIAL"
    return type_ if type_ in CHANNELS else "SEARCH"
CADENCE_FOCUS = ["OUTBOUND", "INBOUND", "ACTIVE_INBOUND", "OTHER"]
CADENCE_PRIORITY = ["VERY_HIGH", "HIGH", "MEDIUM", "LOW"]
PRIORITY_WEIGHT = {"VERY_HIGH": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
CALL_STATUS = ["CONNECTED", "NOT_PERFORMED"]
CALL_OUTPUT = ["MEANINGFUL", "NOT_MEANINGFUL", "NO_CONTACT"]
USER_ROLES = ["ADMINISTRATOR", "MANAGER", "SDR", "SALESMAN"]


class Company(Base):
    __tablename__ = "company"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    phone: Mapped[str] = mapped_column(String(30), default="")
    site: Mapped[str] = mapped_column(String(200), default="")
    modules: Mapped[str] = mapped_column(String(120), default="FLOW,DIALER,WHATSAPP")
    add_ons: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[str] = mapped_column(String(30), default="CLIENT")
    monthly_value: Mapped[float] = mapped_column(Float, default=0.0)


class Client(Base):
    """A entidade que o Meetime não tem: o cliente para quem a BLU prospecta."""
    __tablename__ = "client"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)
    slug: Mapped[str] = mapped_column(String(60), default="")
    color: Mapped[str] = mapped_column(String(10), default="#00a443")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class Team(Base):
    __tablename__ = "team"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(80))
    users: Mapped[list["User"]] = relationship(back_populates="team")


class User(Base):
    __tablename__ = "user"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(120))
    email: Mapped[str] = mapped_column(String(160), unique=True)
    roles: Mapped[str] = mapped_column(String(120), default="SDR")
    team_id: Mapped[int | None] = mapped_column(ForeignKey("team.id"))
    daily_goal: Mapped[int] = mapped_column(Integer, default=170)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    online: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    team: Mapped["Team | None"] = relationship(back_populates="users")

    @property
    def role_list(self) -> list[str]:
        return [r for r in (self.roles or "").split(",") if r]

    @property
    def initials(self) -> str:
        parts = [p for p in (self.name or "").split() if p]
        return ((parts[0][:1] + parts[-1][:1]) if len(parts) > 1 else (self.name or "?")[:2]).upper()


class Cadence(Base):
    __tablename__ = "cadence"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str] = mapped_column(Text, default="")
    type: Mapped[str] = mapped_column(String(30), default="STANDARD")
    focus: Mapped[str] = mapped_column(String(20), default="OUTBOUND")
    priority: Mapped[str] = mapped_column(String(20), default="MEDIUM")
    executing: Mapped[bool] = mapped_column(Boolean, default=True)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    client: Mapped["Client | None"] = relationship()
    steps: Mapped[list["CadenceStep"]] = relationship(
        back_populates="cadence", cascade="all, delete-orphan",
        order_by="CadenceStep.day, CadenceStep.order_in_day")


class CadenceUser(Base):
    __tablename__ = "cadence_user"
    __table_args__ = (UniqueConstraint("cadence_id", "user_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    cadence_id: Mapped[int] = mapped_column(ForeignKey("cadence.id", ondelete="CASCADE"))
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id", ondelete="CASCADE"))
    daily_goal: Mapped[int] = mapped_column(Integer, default=200)


class Activity(Base):
    """Biblioteca reutilizável de atividades (o `activity-management` do Meetime)."""
    __tablename__ = "activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(240))
    type: Mapped[str] = mapped_column(String(20), default="CALL")
    social_network: Mapped[str] = mapped_column(String(20), default="")
    instruction: Mapped[str] = mapped_column(Text, default="")
    email_subject: Mapped[str] = mapped_column(String(240), default="")
    email_html: Mapped[str] = mapped_column(Text, default="")
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"))


class CadenceStep(Base):
    __tablename__ = "cadence_step"
    id: Mapped[int] = mapped_column(primary_key=True)
    cadence_id: Mapped[int] = mapped_column(ForeignKey("cadence.id", ondelete="CASCADE"))
    activity_id: Mapped[int] = mapped_column(ForeignKey("activity.id"))
    day: Mapped[int] = mapped_column(Integer, default=1)
    order_in_day: Mapped[int] = mapped_column(Integer, default=1)
    template_id: Mapped[int | None] = mapped_column(ForeignKey("template.id"))
    cadence: Mapped["Cadence"] = relationship(back_populates="steps")
    activity: Mapped["Activity"] = relationship()
    template: Mapped["Template | None"] = relationship()


class Template(Base):
    """Texto de um passo de e-mail, WhatsApp ou social.

    O corpo aceita variáveis no formato `{{primeiro_nome}}` — a substituição
    fica em `render.py`, para o mesmo modelo servir a canais diferentes.
    """
    __tablename__ = "template"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(160))
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL")  # EMAIL|WHATSAPP|SOCIAL
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    client: Mapped["Client | None"] = relationship()


class LeadBase(Base):
    __tablename__ = "lead_base"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(200))
    status: Mapped[str] = mapped_column(String(30), default="COMPLETED")
    source: Mapped[str] = mapped_column(String(30), default="CSV")   # CSV | CAPIBLU | MANUAL
    source_query: Mapped[str] = mapped_column(Text, default="")      # JSON da consulta CapiBLU
    number_of_leads: Mapped[int] = mapped_column(Integer, default=0)
    discarded_leads: Mapped[int] = mapped_column(Integer, default=0)
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"))
    created_by_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    client: Mapped["Client | None"] = relationship()
    created_by: Mapped["User | None"] = relationship()


class CustomField(Base):
    __tablename__ = "custom_field"
    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120))
    identifier: Mapped[str] = mapped_column(String(80), unique=True)
    data_type: Mapped[str] = mapped_column(String(20), default="STRING")
    index: Mapped[int] = mapped_column(Integer, default=0)
    visible: Mapped[bool] = mapped_column(Boolean, default=True)


class Lead(Base):
    __tablename__ = "lead"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    first_name: Mapped[str] = mapped_column(String(80), default="")
    name: Mapped[str] = mapped_column(String(180))
    email: Mapped[str] = mapped_column(String(180), default="")
    company: Mapped[str] = mapped_column(String(220), default="")
    position: Mapped[str] = mapped_column(String(120), default="")
    phone: Mapped[str] = mapped_column(String(120), default="")
    site: Mapped[str] = mapped_column(String(200), default="")
    state: Mapped[str] = mapped_column(String(10), default="")
    city: Mapped[str] = mapped_column(String(120), default="")
    linkedin: Mapped[str] = mapped_column(String(200), default="")
    annotations: Mapped[str] = mapped_column(Text, default="")
    external_reference: Mapped[str] = mapped_column(String(120), default="")
    cnpj: Mapped[str] = mapped_column(String(20), default="")
    cpf: Mapped[str] = mapped_column(String(14), default="")
    razao_social: Mapped[str] = mapped_column(String(220), default="")

    # Sinais que o CapiBLU calcula e que se perdiam na conversão para lead:
    # o nível de decisão (1 decide sozinho · 2 decide na área · 3 influencia),
    # a categoria do telefone escolhido e se ele tem WhatsApp.
    decision_level: Mapped[int] = mapped_column(Integer, default=0)
    contact_kind: Mapped[str] = mapped_column(String(20), default="")   # socio | decisor
    phone_kind: Mapped[str] = mapped_column(String(20), default="")     # celular | fixo | antigo
    whatsapp: Mapped[bool] = mapped_column(Boolean, default=False)
    do_not_call: Mapped[bool] = mapped_column(Boolean, default=False)

    status: Mapped[str] = mapped_column(String(30), default="WAITING")
    cadence_id: Mapped[int | None] = mapped_column(ForeignKey("cadence.id"))
    sdr_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    lead_base_id: Mapped[int | None] = mapped_column(ForeignKey("lead_base.id"))
    client_id: Mapped[int | None] = mapped_column(ForeignKey("client.id"))
    current_step: Mapped[int] = mapped_column(Integer, default=0)
    best_hour: Mapped[int] = mapped_column(Integer, default=18)
    lost_reason_id: Mapped[int | None] = mapped_column(ForeignKey("lost_reason.id"))
    won_at: Mapped[datetime | None] = mapped_column(DateTime)
    lost_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

    cadence: Mapped["Cadence | None"] = relationship()
    sdr: Mapped["User | None"] = relationship()
    client: Mapped["Client | None"] = relationship()
    lead_base: Mapped["LeadBase | None"] = relationship()
    lost_reason: Mapped["LostReason | None"] = relationship()


class LeadFieldValue(Base):
    __tablename__ = "lead_field_value"
    __table_args__ = (UniqueConstraint("lead_id", "field_id"),)
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    field_id: Mapped[int] = mapped_column(ForeignKey("custom_field.id", ondelete="CASCADE"))
    value: Mapped[str] = mapped_column(Text, default="")


class LeadActivity(Base):
    """Uma atividade agendada/executada para um lead — a unidade da fila."""
    __tablename__ = "lead_activity"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    activity_id: Mapped[int | None] = mapped_column(ForeignKey("activity.id"))
    cadence_step_id: Mapped[int | None] = mapped_column(ForeignKey("cadence_step.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    type: Mapped[str] = mapped_column(String(20), default="CALL")
    social_network: Mapped[str] = mapped_column(String(20), default="")
    status: Mapped[str] = mapped_column(String(20), default="PENDING")
    """PENDING · DONE · SKIPPED · PAUSED (lead respondeu; ver /execution/leads/{id}/resume)"""
    scheduled_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    done_at: Mapped[datetime | None] = mapped_column(DateTime)
    notes: Mapped[str] = mapped_column(Text, default="")
    lead: Mapped["Lead"] = relationship()
    activity: Mapped["Activity | None"] = relationship()
    user: Mapped["User | None"] = relationship()


class Call(Base):
    __tablename__ = "call"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("lead.id"))
    origin_phone: Mapped[str] = mapped_column(String(30), default="")
    receiver_phone: Mapped[str] = mapped_column(String(30), default="")
    receiver_type: Mapped[str] = mapped_column(String(20), default="MOBILE")
    status: Mapped[str] = mapped_column(String(20), default="NOT_PERFORMED")
    output: Mapped[str] = mapped_column(String(20), default="")
    duration: Mapped[int] = mapped_column(Integer, default=0)
    price: Mapped[float] = mapped_column(Float, default=0.0)
    important: Mapped[bool] = mapped_column(Boolean, default=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    user: Mapped["User | None"] = relationship()
    lead: Mapped["Lead | None"] = relationship()


class Goal(Base):
    __tablename__ = "goal"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(ForeignKey("user.id"))
    target_month: Mapped[date] = mapped_column(Date)
    opportunities_goal: Mapped[int] = mapped_column(Integer, default=25)
    conversion_rate_goal: Mapped[float] = mapped_column(Float, default=0.15)
    user: Mapped["User"] = relationship()


class LostReason(Base):
    __tablename__ = "lost_reason"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    name: Mapped[str] = mapped_column(String(160), unique=True)


class Holiday(Base):
    __tablename__ = "holiday"
    id: Mapped[int] = mapped_column(primary_key=True)
    day: Mapped[date] = mapped_column(Date, unique=True)
    name: Mapped[str] = mapped_column(String(120), default="")


class Webhook(Base):
    __tablename__ = "webhook"
    id: Mapped[int] = mapped_column(primary_key=True)
    meetime_id: Mapped[str] = mapped_column(String(20), default="", index=True)
    events: Mapped[str] = mapped_column(String(200), default="LEAD.WON")
    target_url: Mapped[str] = mapped_column(String(400))
    secret: Mapped[str] = mapped_column(String(120), default="")
    enabled: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)


class WebhookDelivery(Base):
    """Cada tentativa de entregar um evento a um webhook.

    Sem isto, "o CRM não recebeu o lead ganho" não tem como ser investigado: o
    envio anterior era `httpx.post` com `except: pass`, então falha sumia sem
    deixar rastro. Aqui a tentativa fica registrada e pode ser repetida.
    """
    __tablename__ = "webhook_delivery"
    id: Mapped[int] = mapped_column(primary_key=True)
    webhook_id: Mapped[int] = mapped_column(ForeignKey("webhook.id", ondelete="CASCADE"))
    event: Mapped[str] = mapped_column(String(40), index=True)
    payload: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="PENDING", index=True)
    # PENDING (na fila) · SENT · FAILED (esgotou as tentativas)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    response_code: Mapped[int] = mapped_column(Integer, default=0)
    error: Mapped[str] = mapped_column(String(240), default="")
    next_try_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    delivered_at: Mapped[datetime | None] = mapped_column(DateTime)
    webhook: Mapped["Webhook"] = relationship()


class AuditLog(Base):
    """Quem olhou o dado pessoal de quem, e quando.

    O produto lê CPF, telefone, endereço e renda de pessoa física a partir de
    bases de terceiros. A LGPD trata isso como tratamento de dado pessoal, e
    tratamento sem registro é o que não dá para explicar depois. Só as consultas
    que tocam pessoa entram aqui — listar cadência não é dado pessoal.
    """
    __tablename__ = "audit_log"
    id: Mapped[int] = mapped_column(primary_key=True)
    at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow, index=True)
    actor_email: Mapped[str] = mapped_column(String(160), default="", index=True)
    actor_level: Mapped[str] = mapped_column(String(12), default="")
    action: Mapped[str] = mapped_column(String(60), default="", index=True)
    subject: Mapped[str] = mapped_column(String(80), default="", index=True)  # CPF/CNPJ/telefone
    path: Mapped[str] = mapped_column(String(200), default="")
    status: Mapped[int] = mapped_column(Integer, default=200)
    detail: Mapped[str] = mapped_column(String(240), default="")


class Integration(Base):
    __tablename__ = "integration"
    id: Mapped[int] = mapped_column(primary_key=True)
    key: Mapped[str] = mapped_column(String(60), unique=True)
    name: Mapped[str] = mapped_column(String(120))
    kind: Mapped[str] = mapped_column(String(60), default="CRM")
    connected: Mapped[bool] = mapped_column(Boolean, default=False)
    last_sync: Mapped[datetime | None] = mapped_column(DateTime)


class Conversation(Base):
    __tablename__ = "conversation"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("lead.id"))
    phone: Mapped[str] = mapped_column(String(30), default="")
    title: Mapped[str] = mapped_column(String(160), default="")
    last_message_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lead: Mapped["Lead | None"] = relationship()


class Message(Base):
    __tablename__ = "message"
    id: Mapped[int] = mapped_column(primary_key=True)
    conversation_id: Mapped[int] = mapped_column(ForeignKey("conversation.id", ondelete="CASCADE"))
    direction: Mapped[str] = mapped_column(String(10), default="OUT")  # IN|OUT
    body: Mapped[str] = mapped_column(Text, default="")
    sent_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    # Sem isto, "gravei a linha" e "o lead recebeu" ficavam indistinguíveis.
    status: Mapped[str] = mapped_column(String(12), default="SENT")
    provider_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    error: Mapped[str] = mapped_column(String(240), default="")


class Delivery(Base):
    """Cada tentativa de envio, de qualquer canal.

    Separado de `Message` porque e-mail não tem conversa e porque o histórico
    de tentativa interessa mesmo quando a mensagem não existe — é aqui que se
    responde "por que este lead não recebeu nada?".
    """
    __tablename__ = "delivery"
    id: Mapped[int] = mapped_column(primary_key=True)
    lead_id: Mapped[int | None] = mapped_column(ForeignKey("lead.id", ondelete="CASCADE"))
    lead_activity_id: Mapped[int | None] = mapped_column(ForeignKey("lead_activity.id"))
    user_id: Mapped[int | None] = mapped_column(ForeignKey("user.id"))
    template_id: Mapped[int | None] = mapped_column(ForeignKey("template.id"))
    channel: Mapped[str] = mapped_column(String(20), default="EMAIL", index=True)
    to_address: Mapped[str] = mapped_column(String(200), default="")
    subject: Mapped[str] = mapped_column(String(240), default="")
    body: Mapped[str] = mapped_column(Text, default="")
    status: Mapped[str] = mapped_column(String(12), default="SIMULATED", index=True)
    provider: Mapped[str] = mapped_column(String(30), default="")
    provider_id: Mapped[str] = mapped_column(String(120), default="", index=True)
    error: Mapped[str] = mapped_column(String(240), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
    lead: Mapped["Lead | None"] = relationship()
