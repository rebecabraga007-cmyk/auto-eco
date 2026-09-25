"""Enviar de verdade: o passo da cadência virando mensagem no lead.

Toda saída passa por aqui, e por três travas antes do provedor:

1. **Não perturbe.** O CapiBLU já coleta o sinal da Assertiva e o Bluutime já o
   guarda em `Lead.do_not_call` — mas até agora ninguém consultava. Aqui ele
   bloqueia.
2. **Janela útil.** Mandar WhatsApp de cadência às 23h queima o número.
3. **Freio de mão.** `BLUUTIME_SEND != 1` faz tudo voltar como `SIMULATED`.
"""
import base64
import re
import secrets
from datetime import datetime
from urllib.parse import unquote

from fastapi import APIRouter, Body, Depends, HTTPException, Request, Response
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from .. import agenda, auditoria, channels, perm, ratelimit, render, serial, webhooks
from ..db import get_db
from ..models import (AuditLog, CadenceStep, Company, Conversation, Delivery,
                      Lead, LeadActivity, Message, Template, User, channel_of)

router = APIRouter(prefix="/api/envio")
# Rastreio mora fora de /api: são endereços que o LEAD abre, não a aplicação.
# Curto, sem prefixo e sem sessão — o destinatário do e-mail não está logado.
publico = APIRouter()


@router.get("/canais")
async def canais():
    """Estado real de cada canal — sem `CONNECTED` inventado."""
    return {"sendingEnabled": channels.envio_ligado(), "channels": await channels.states()}


@router.post("/whatsapp/conectar")
async def whatsapp_conectar(db: Session = Depends(get_db)):
    """Abre a sessão do WhatsApp. No wuzapi isso é explícito, ao contrário da
    Evolution, que reconecta sozinha."""
    perm.ator(db).exigir("gestor", "conectar o WhatsApp")
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "connect"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} "
                                 "não expõe conexão manual.")
    return await ch.connect()


@router.get("/whatsapp/qrcode")
async def whatsapp_qrcode(db: Session = Depends(get_db)):
    """QR para parear o número. Vem vazio quando a sessão já está logada.

    Sem checagem, qualquer usuário conseguia o QR do número comercial único
    da empresa e escaneava com o próprio celular — sequestro de canal.
    """
    perm.ator(db).exigir("gestor", "parear o WhatsApp")
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "qrcode"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} "
                                 "não expõe QR Code por aqui.")
    return await ch.qrcode()


@router.post("/whatsapp/desconectar")
async def whatsapp_desconectar(payload: dict = Body(default={}), db: Session = Depends(get_db)):
    """Derruba a sessão; com `logout`, desparea o número.

    Estava só no provedor: para trocar o número da empresa era preciso entrar
    no wuzapi por fora, e quem não tinha esse acesso ficava preso ao número
    pareado.
    """
    perm.ator(db).exigir("gestor", "desconectar o WhatsApp")
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "disconnect"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} "
                                 "não expõe desconexão por aqui.")
    return await ch.disconnect(logout=bool(payload.get("logout")))


@router.post("/whatsapp/webhook")
async def whatsapp_webhook(request: Request, db: Session = Depends(get_db)):
    """Aponta o webhook do provedor para o Bluutime, com o token na URL.

    Estava vazio em produção: nenhuma resposta de lead entrava nas conversas.
    A URL é a pública (`BLUUTIME_PUBLIC_URL`, ou o endereço desta chamada),
    porque o contêiner do wuzapi não alcança o 127.0.0.1 do servidor."""
    import os
    perm.ator(db).exigir("gestor", "configurar o webhook do WhatsApp")
    ch = channels.get("WHATSAPP")
    if not hasattr(ch, "configurar_webhook"):
        raise HTTPException(400, f"O provedor {channels.provedor_whatsapp()} não é configurado por aqui.")
    token = os.environ.get("EVOLUTION_WEBHOOK_TOKEN", "")
    if not token:
        raise HTTPException(400, "Defina EVOLUTION_WEBHOOK_TOKEN no .env antes de configurar o webhook.")
    base = (os.environ.get("BLUUTIME_PUBLIC_URL") or str(request.base_url)).rstrip("/")
    r = await ch.configurar_webhook(f"{base}/api/whatsapp/webhook?token={token}")
    return {**r, "url": f"{base}/api/whatsapp/webhook?token=•••"}


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
               user_id=None, activity_id=None, template_id=None, token="") -> Delivery:
    d = Delivery(lead_id=lead.id, lead_activity_id=activity_id, user_id=user_id,
                 template_id=template_id, channel=canal, to_address=destino,
                 subject=assunto, body=corpo, status=resultado.status,
                 provider=resultado.provider, provider_id=resultado.provider_id,
                 error=resultado.error, tracking_token=token)
    db.add(d)
    return d


# 1×1 transparente. Fica embutido para o pixel não depender de arquivo em disco.
_PIXEL = base64.b64decode(
    "R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")


def _marcar(db: Session, token: str, campo: str) -> Delivery | None:
    d = db.query(Delivery).filter(Delivery.tracking_token == token).first()
    if not d:
        return None
    agora = datetime.utcnow()
    if campo == "open":
        d.open_count += 1
        # Guarda a PRIMEIRA abertura: é ela que diz quanto tempo o lead levou
        # para abrir. A última seria sobrescrita a cada releitura.
        d.opened_at = d.opened_at or agora
    else:
        d.click_count += 1
        d.clicked_at = d.clicked_at or agora
        # Clicou, então abriu — mesmo que a imagem tenha sido bloqueada.
        d.opened_at = d.opened_at or agora
    db.commit()
    return d


@publico.get("/t/o/{token}.gif", include_in_schema=False)
def rastrear_abertura(token: str, db: Session = Depends(get_db)):
    _marcar(db, token, "open")
    # Devolve o pixel mesmo com token desconhecido: a imagem quebrada no
    # e-mail do lead denunciaria o rastreio sem nenhum ganho.
    return Response(content=_PIXEL, media_type="image/gif",
                    headers={"Cache-Control": "no-store"})


@publico.get("/t/c/{token}", include_in_schema=False)
def rastrear_clique(token: str, u: str = "", db: Session = Depends(get_db)):
    destino = unquote(u or "")
    # Valida ANTES de contar. Contar primeiro inflava a métrica com tentativa
    # recusada — clique que não levou a lugar nenhum não é clique.
    # Só http(s): sem isto o redirecionador viraria um encaminhador aberto
    # para `javascript:` e afins, assinado pelo nosso domínio.
    if not destino.startswith(("http://", "https://")):
        raise HTTPException(400, "Destino inválido.")
    # Só redireciona para um link que estava na mensagem daquele token. Sem
    # isso, /t/c/qualquer?u=https://golpe virava link de phishing com o
    # domínio da BLU.
    entrega = db.query(Delivery).filter(Delivery.tracking_token == token).first()
    if not entrega or destino not in (entrega.body or ""):
        raise HTTPException(404, "Link não encontrado.")
    _marcar(db, token, "click")
    return RedirectResponse(destino, status_code=302)


@router.get("/atividades/{aid}/previa")
def previa_atividade(aid: int, db: Session = Depends(get_db)):
    """O que o editor da atividade mostra antes do envio: destinatário, assunto e
    corpo já com as variáveis do lead, e o que falta ou bloqueia."""
    act = db.get(LeadActivity, aid)
    if not act:
        raise HTTPException(404, "Atividade não encontrada.")
    perm.exigir_dono_lead(db, perm.ator(db), act.lead)
    lead = act.lead
    canal = channel_of(act.type, act.social_network)
    step = db.get(CadenceStep, act.cadence_step_id) if act.cadence_step_id else None
    tpl = step.template if step else None
    user = db.get(User, act.user_id) if act.user_id else lead.sdr
    valores = render.lead_vars(lead, user)
    return {"canal": canal, "para": lead.email if canal == "EMAIL" else lead.phone,
            "temModelo": bool(tpl),
            "assunto": render.render(tpl.subject, valores) if tpl else "",
            "corpo": render.render(tpl.body, valores) if tpl else "",
            "faltando": render.missing(f"{tpl.subject}\n{tpl.body}", valores) if tpl else [],
            "bloqueio": (_pode_enviar(lead, canal, False) or "")
                        if canal in ("EMAIL", "WHATSAPP") else ""}


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
    perm.exigir_dono_lead(db, perm.ator(db), act.lead)
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
    # O SDR pode ajustar o texto antes de enviar, como no editor do Meetime. O
    # texto editado também passa pelo render: quem mantém uma variável no corpo
    # continua recebendo o valor do lead.
    modelo_assunto = tpl.subject if payload.get("assunto") is None else str(payload["assunto"])
    modelo_corpo = tpl.body if payload.get("corpo") is None else str(payload["corpo"])
    assunto = render.render(modelo_assunto, valores)
    corpo = render.render(modelo_corpo, valores)
    # Duas permissões distintas de propósito. `forcar` é cosmético — manda mesmo
    # com variável vazia. `foraDaJanela` é uma decisão de horário. Nenhum dos
    # dois fura o "não perturbe".
    faltando = render.missing(f"{modelo_assunto}\n{modelo_corpo}", valores)
    if faltando and not payload.get("forcar"):
        raise HTTPException(422, "O modelo tem variáveis sem valor para este lead: "
                                 f"{', '.join(faltando)}. Reenvie com forcar=true "
                                 "se quiser mandar assim mesmo.")

    if canal == "EMAIL" and user and user.email_signature:
        corpo = f"{corpo}\n\n{user.email_signature}"

    destino = lead.email if canal == "EMAIL" else lead.phone
    para = str(payload.get("para") or "").strip()
    if para:
        if canal == "EMAIL" and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[^@\s]+", para):
            raise HTTPException(400, "Destinatário inválido.")
        # O SDR escolhe entre os contatos do lead; mandar para fora dele é
        # decisão de gestor — senão a atividade vira um relay de mensagens com
        # o domínio da empresa, furando o "não perturbe" de quem recebe.
        digitos = lambda t: re.sub(r"\D", "", t or "")[-11:]
        do_lead = (para.lower() == (lead.email or "").strip().lower() if canal == "EMAIL"
                   else digitos(para) in {digitos(t) for t in re.split(r"[,;/|]", lead.phone or "") if digitos(t)})
        if not do_lead and not perm.ator(db).pelo_menos("gestor"):
            raise HTTPException(403, "Só é possível enviar para os contatos cadastrados no lead. "
                                     "Atualize o cadastro do lead ou peça a um gestor.")
        destino = para
    # Reserva a atividade antes de enviar: dois cliques seguidos em "Enviar"
    # mandavam a mensagem duas vezes, porque o envio acontece antes do DONE.
    reservou = (db.query(LeadActivity)
                .filter(LeadActivity.id == act.id, LeadActivity.status == "PENDING")
                .update({"status": "SENDING", "done_at": datetime.utcnow()},
                        synchronize_session=False))
    db.commit()
    if not reservou:
        raise HTTPException(409, "Esta atividade já está sendo enviada.")
    db.refresh(act)
    try:
        return await _enviar_reservada(db, act, lead, canal, destino, assunto, corpo,
                                       user, tpl, payload)
    except Exception:
        db.rollback()
        act = db.get(LeadActivity, aid)
        if act and act.status == "SENDING":
            act.status, act.done_at = "PENDING", None
            db.commit()
        raise


async def _enviar_reservada(db, act, lead, canal, destino, assunto, corpo, user, tpl, payload):
    token = ""
    bloqueio = _pode_enviar(lead, canal, bool(payload.get("foraDaJanela")))
    if bloqueio:
        resultado = channels.SendResult("BLOCKED", canal, error=bloqueio)
    elif canal == "EMAIL":
        empresa = db.query(Company).first()
        # Sorteado antes porque a linha de Delivery só nasce depois do envio.
        token = secrets.token_urlsafe(16)
        # Remetente do SDR quando ele tem um; senão o da empresa. O lead
        # responde para quem está falando com ele, não para um alias genérico.
        de_usuario = (user.email_from or "").strip() if user else ""
        resultado = await channels.send(canal, to=destino, body=corpo, subject=assunto,
                                        reply_to=(user.email if user else ""),
                                        from_name=((user.name if de_usuario and user else "")
                                                   or (empresa.email_from_name if empresa else "")),
                                        from_addr=(de_usuario
                                                   or (empresa.email_from_address if empresa else "")),
                                        tracking_token=token)
    else:
        resultado = await channels.send(canal, to=destino, body=corpo, subject=assunto,
                                        reply_to=(user.email if user else ""))

    entrega = _registrar(db, lead=lead, canal=canal, destino=destino, assunto=assunto,
                         corpo=corpo, resultado=resultado, user_id=act.user_id,
                         activity_id=act.id, template_id=tpl.id,
                         token=token if canal == "EMAIL" else "")

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
    if resultado.status not in ("SENT", "SIMULATED"):
        act.status, act.done_at = "PENDING", None
    if resultado.status in ("SENT", "SIMULATED"):
        act.status = "DONE"
        act.done_at = resultado.at
        act.notes = (act.notes + "\n" if act.notes else "") + \
            f"{canal} via {resultado.provider or '—'}: {resultado.status}"
        if act.cadence_step_id:          # extra não é passo da cadência
            lead.current_step += 1
        if lead.status == "WAITING":
            lead.status = "EXECUTING"
        webhooks.enfileirar(db, "ACTIVITY.DONE", {**serial.lead_activity(act, resultado.at),
                                                   "lead": serial.lead(lead)})

    if resultado.status == "SENT":
        webhooks.enfileirar(db, "MESSAGE.SENT", {
            "leadId": lead.id, "leadName": lead.name, "channel": canal,
            "to": destino, "subject": assunto, "providerId": resultado.provider_id})
    db.commit()
    return {"delivery": {"id": entrega.id, **resultado.as_dict()},
            "activityStatus": act.status,
            "preview": {"to": destino, "subject": assunto, "body": corpo}}


@router.post("/teste")
async def enviar_teste(payload: dict = Body(...), db: Session = Depends(get_db)):
    """Manda uma mensagem para conferir a configuração de um canal.

    Sem checagem, era um relay aberto: qualquer conta autenticada mandava
    conteúdo arbitrário pra qualquer destinatário externo usando a
    credencial de e-mail/WhatsApp da empresa. Testar canal é tarefa de quem
    configura, não do dia a dia do SDR — por isso "gestor", igual ao
    conectar/parear do WhatsApp.
    """
    ator = perm.ator(db)
    ator.exigir("gestor", "testar canal de envio")
    # Defesa em profundidade: mesmo já sendo gestor+, um relay de envio não
    # deveria aguentar rajada — 10 tentativas a cada 10 min por conta.
    if not ratelimit.permitir(f"envio-teste:{ator.user_id or ator.email}", 10, 600):
        raise HTTPException(429, "Muitas tentativas de teste em pouco tempo. Aguarde um pouco.")
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
    q = perm.escopo_leads(db, db.query(Delivery), perm.ator(db), Delivery.user_id)
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
