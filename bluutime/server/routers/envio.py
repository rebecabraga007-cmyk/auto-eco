"""Enviar de verdade: o passo da cadência virando mensagem no lead.

Toda saída passa por aqui, e por três travas antes do provedor:

1. **Não perturbe.** O CapiBLU já coleta o sinal da Assertiva e o Bluutime já o
   guarda em `Lead.do_not_call` — mas até agora ninguém consultava. Aqui ele
   bloqueia.
2. **Janela útil.** Mandar WhatsApp de cadência às 23h queima o número.
3. **Freio de mão.** `BLUUTIME_SEND != 1` faz tudo voltar como `SIMULATED`.
"""
from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import agenda, auditoria, channels, perm, render, serial, webhooks
from ..db import get_db
from ..models import (AuditLog, CadenceStep, Conversation, Delivery, Lead,
                      LeadActivity, Message, Template, User, channel_of)

router = APIRouter(prefix="/api/envio")


@router.get("/canais")
async def canais():
    """Estado real de cada canal — sem `CONNECTED` inventado."""
    return {"sendingEnabled": channels.envio_ligado(), "channels": await channels.states()}


@router.post("/whatsapp/conectar")
async def whatsapp_conectar():
    """Abre a sessão do WhatsApp. No wuzapi isso é explícito, ao contrário da
    Evolution, que reconecta sozinha."""
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "connect"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} "
                                 "não expõe conexão manual.")
    return await ch.connect()


@router.get("/whatsapp/qrcode")
async def whatsapp_qrcode():
    """QR para parear o número. Vem vazio quando a sessão já está logada."""
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "qrcode"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} "
                                 "não expõe QR Code por aqui.")
    return await ch.qrcode()


@router.get("/quem-sou-eu")
def quem_sou_eu(db: Session = Depends(get_db)):
    """O nível efetivo do usuário — é isto que a UI usa para esconder botão."""
    return perm.ator(db).as_dict()


@router.get("/auditoria")
def trilha(action: str | None = None, actor: str | None = None,
           limit: int = 100, db: Session = Depends(get_db)):
    """Quem acessou dado pessoal de quem. Só gestor — é a trilha, não o dado."""
    perm.ator(db).exigir("gestor", "ver a trilha de auditoria")
    q = db.query(AuditLog)
    if action:
        q = q.filter(AuditLog.action == action.upper())
    if actor:
        q = q.filter(AuditLog.actor_email.ilike(f"%{actor}%"))
    rows = q.order_by(AuditLog.at.desc()).limit(min(limit, 500)).all()
    return {"data": [{
        "id": r.id, "at": serial.iso(r.at), "actor": r.actor_email,
        "level": r.actor_level, "action": r.action, "subject": r.subject,
        "path": r.path, "status": r.status, "detail": r.detail} for r in rows],
        "actions": [nome for _, nome in auditoria.ACOES]}


def _pode_enviar(lead: Lead, canal: str, fora_da_janela: bool) -> str:
    """Motivo do bloqueio, ou string vazia se pode seguir.

    `do_not_call` **não tem como ser furado por parâmetro**. É sinal de
    compliance, não aviso de conveniência: quem precisar mesmo falar com o lead
    tira a marca no cadastro dele, e essa é uma ação deliberada e auditável —
    ao contrário de repetir a chamada com uma flag a mais.
    """
    if lead.do_not_call:
        return "Lead marcado como 'não perturbe'. Remova a marca no cadastro do lead."
    if canal == "WHATSAPP" and not lead.phone:
        return "Lead sem telefone."
    if canal == "EMAIL" and not lead.email:
        return "Lead sem e-mail."
    if not fora_da_janela:
        agora = agenda.now_local()
        if agora.hour < agenda.WORK_START or agora.hour >= agenda.WORK_END:
            return (f"Fora da janela de {agenda.WORK_START}h–{agenda.WORK_END}h "
                    f"(agora são {agora:%H:%M}). Use foraDaJanela=true se for intencional.")
    return ""


def _registrar(db: Session, *, lead, canal, destino, assunto, corpo, resultado,
               user_id=None, activity_id=None, template_id=None) -> Delivery:
    d = Delivery(lead_id=lead.id, lead_activity_id=activity_id, user_id=user_id,
                 template_id=template_id, channel=canal, to_address=destino,
                 subject=assunto, body=corpo, status=resultado.status,
                 provider=resultado.provider, provider_id=resultado.provider_id,
                 error=resultado.error)
    db.add(d)
    return d


@router.post("/atividades/{aid}")
async def enviar_atividade(aid: int, payload: dict = Body(default={}),
                           db: Session = Depends(get_db)):
    """Envia a mensagem do passo e conclui a atividade.

    O texto vem do `Template` pendurado no passo da cadência; sem modelo, não há
    o que mandar — e é melhor dizer isso do que mandar mensagem em branco.
    """
    act = db.get(LeadActivity, aid)
    if not act:
        raise HTTPException(404, "Atividade não encontrada.")
    if act.status != "PENDING":
        raise HTTPException(400, "Atividade já finalizada.")
    lead = act.lead
    canal = channel_of(act.type, act.social_network)
    if canal not in ("EMAIL", "WHATSAPP"):
        raise HTTPException(400, f"Atividade de {canal} não envia mensagem — "
                                 "use a fila de execução.")

    step = db.get(CadenceStep, act.cadence_step_id) if act.cadence_step_id else None
    tpl = step.template if step else None
    if payload.get("templateId"):
        tpl = db.get(Template, payload["templateId"])
    if not tpl:
        raise HTTPException(400, "O passo não tem modelo de mensagem. "
                                 "Anexe um modelo à etapa da cadência.")
    if tpl.channel != canal:
        raise HTTPException(400, f"O modelo é de {tpl.channel} e o passo é de {canal}.")

    user = db.get(User, act.user_id) if act.user_id else lead.sdr
    valores = render.lead_vars(lead, user)
    assunto = render.render(tpl.subject, valores)
    corpo = render.render(tpl.body, valores)
    # Duas permissões distintas de propósito. `forcar` é cosmético — manda mesmo
    # com variável vazia. `foraDaJanela` é uma decisão de horário. Nenhum dos
    # dois fura o "não perturbe".
    faltando = render.missing(f"{tpl.subject}\n{tpl.body}", valores)
    if faltando and not payload.get("forcar"):
        raise HTTPException(422, "O modelo tem variáveis sem valor para este lead: "
                                 f"{', '.join(faltando)}. Reenvie com forcar=true "
                                 "se quiser mandar assim mesmo.")

    destino = lead.email if canal == "EMAIL" else lead.phone
    bloqueio = _pode_enviar(lead, canal, bool(payload.get("foraDaJanela")))
    if bloqueio:
        resultado = channels.SendResult("BLOCKED", canal, error=bloqueio)
    else:
        resultado = await channels.send(canal, to=destino, body=corpo, subject=assunto,
                                        reply_to=(user.email if user else ""))

    entrega = _registrar(db, lead=lead, canal=canal, destino=destino, assunto=assunto,
                         corpo=corpo, resultado=resultado, user_id=act.user_id,
                         activity_id=act.id, template_id=tpl.id)

    # WhatsApp entra no histórico da conversa; e-mail vive só em `Delivery`.
    if canal == "WHATSAPP" and resultado.status in ("SENT", "SIMULATED"):
        conv = (db.query(Conversation)
                .filter(Conversation.lead_id == lead.id).first())
        if not conv:
            conv = Conversation(lead_id=lead.id, phone=lead.phone,
                                title=lead.name or lead.company)
            db.add(conv)
            db.flush()
        db.add(Message(conversation_id=conv.id, direction="OUT", body=corpo,
                       status=resultado.status, provider_id=resultado.provider_id,
                       error=resultado.error))
        conv.last_message_at = resultado.at

    # Bloqueio não conclui a atividade: ela continua na fila para o SDR resolver.
    if resultado.status in ("SENT", "SIMULATED"):
        act.status = "DONE"
        act.done_at = resultado.at
        act.notes = (act.notes + "\n" if act.notes else "") + \
            f"{canal} via {resultado.provider or '—'}: {resultado.status}"
        lead.current_step += 1
        if lead.status == "WAITING":
            lead.status = "EXECUTING"

    if resultado.status == "SENT":
        webhooks.enfileirar(db, "MESSAGE.SENT", {
            "leadId": lead.id, "leadName": lead.name, "channel": canal,
            "to": destino, "subject": assunto, "providerId": resultado.provider_id})
    db.commit()
    return {"delivery": {"id": entrega.id, **resultado.as_dict()},
            "activityStatus": act.status,
            "preview": {"to": destino, "subject": assunto, "body": corpo}}


@router.post("/teste")
async def enviar_teste(payload: dict = Body(...)):
    """Manda uma mensagem para você mesmo, para conferir a configuração."""
    canal = (payload.get("channel") or "").upper()
    destino = (payload.get("to") or "").strip()
    if not destino:
        raise HTTPException(400, "Informe o destino.")
    r = await channels.send(canal, to=destino,
                            subject=payload.get("subject") or "Teste do Bluutime",
                            body=payload.get("body") or "Mensagem de teste do Bluutime.")
    return r.as_dict()


@router.get("/entregas")
def listar_entregas(lead_id: int | None = None, status: str | None = None,
                    channel: str | None = None, limit: int = 100,
                    db: Session = Depends(get_db)):
    """O histórico que responde 'por que este lead não recebeu nada?'."""
    q = db.query(Delivery)
    if lead_id:
        q = q.filter(Delivery.lead_id == lead_id)
    if status:
        q = q.filter(Delivery.status == status.upper())
    if channel:
        q = q.filter(Delivery.channel == channel.upper())
    rows = q.order_by(Delivery.created_at.desc()).limit(min(limit, 500)).all()
    return {"data": [{
        "id": d.id, "channel": d.channel, "status": d.status, "to": d.to_address,
        "subject": d.subject, "error": d.error, "provider": d.provider,
        "createdAt": serial.iso(d.created_at),
        "lead": {"id": d.lead.id, "name": d.lead.name} if d.lead else None,
    } for d in rows]}
