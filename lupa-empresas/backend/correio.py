# -*- coding: utf-8 -*-
"""Mandar arquivo por e-mail. E dizer, alto e claro, quando nao da.

POR QUE EXISTE
--------------
A Datastone entrega o enriquecimento de duas formas: link na tela e arquivo
no e-mail. A segunda nao e conveniencia -- e o que permite fechar o navegador.
Um lote de mil linhas leva minutos, e hoje quem fecha a aba perde o trabalho
ja pago.

O ESTADO DE HOJE (17/set/2026)
------------------------------
NAO HA credencial de e-mail em lugar nenhum deste projeto. Procurei por
smtplib, sendgrid, resend e SMTP no backend, no app_online e no .env do
servidor: nada. Entao este modulo nasce funcionando de verdade e DESLIGADO,
esperando quatro variaveis de ambiente:

    CAPIBLU_SMTP_HOST   (padrao smtp.gmail.com)
    CAPIBLU_SMTP_PORT   (padrao 587, STARTTLS)
    CAPIBLU_SMTP_USER   o endereco que envia
    CAPIBLU_SMTP_SENHA  senha de app do Google Workspace, nao a senha da conta
    CAPIBLU_SMTP_DE     opcional: "CapiBLU <naoresponda@blusalesgroup.com.br>"

Enquanto faltarem, `configurado()` responde False e a tela diz isso em vez de
oferecer um botao que nao faz nada. Botao que promete e nao cumpre e pior que
botao que nao existe: quem clica vai embora achando que o e-mail esta a
caminho.
"""
import os
import re
import smtplib
import ssl
from email.message import EmailMessage

HOST = os.environ.get("CAPIBLU_SMTP_HOST", "smtp.gmail.com")
PORTA = int(os.environ.get("CAPIBLU_SMTP_PORT", "587") or 587)
USUARIO = os.environ.get("CAPIBLU_SMTP_USER", "")
SENHA = os.environ.get("CAPIBLU_SMTP_SENHA", "")
DE = os.environ.get("CAPIBLU_SMTP_DE", "") or USUARIO

_RE_EMAIL = re.compile(r"^[^@\s]+@[^@\s]+\.[A-Za-z]{2,}$")


def configurado() -> bool:
    """Da para enviar agora? A tela pergunta antes de oferecer o botao."""
    return bool(HOST and USUARIO and SENHA)


def por_que_nao() -> str:
    """A frase exata que falta, para quem for configurar nao ter que adivinhar."""
    if not USUARIO:
        return "Falta CAPIBLU_SMTP_USER (o endereço que envia)."
    if not SENHA:
        return ("Falta CAPIBLU_SMTP_SENHA — é a senha de APP do Google "
                "Workspace, gerada em myaccount.google.com/apppasswords, e "
                "não a senha da conta.")
    if not HOST:
        return "Falta CAPIBLU_SMTP_HOST."
    return ""


def como_esta() -> dict:
    """O que o servidor esta enxergando -- SEM a senha.

    Serve para a pessoa que configurou conferir se a variavel chegou mesmo no
    processo. O erro mais comum nao e a senha errada: e a variavel escrita no
    lugar errado e o servico nunca ter sido reiniciado, e isso e invisivel
    ate alguem mostrar o que o processo leu.
    """
    return {"host": HOST, "porta": PORTA, "usuario": USUARIO,
            "de": DE, "tem_senha": bool(SENHA)}


def endereco_valido(e: str) -> bool:
    return bool(_RE_EMAIL.match((e or "").strip()))


def enviar(para: str, assunto: str, corpo: str,
           anexo: tuple = None) -> dict:
    """Envia. Devolve {status, message} -- nunca levanta para quem chamou.

    `anexo` e (nome_do_arquivo, bytes, tipo_mime).

    A falha volta como TEXTO porque quem vai ler e a operacao, nao um log:
    "senha de app recusada" resolve sozinho, "SMTPAuthenticationError" nao.
    """
    if not configurado():
        return {"status": "error", "message": por_que_nao()}
    if not endereco_valido(para):
        return {"status": "error", "message": "Endereço de e-mail inválido."}

    msg = EmailMessage()
    msg["From"] = DE
    msg["To"] = para
    msg["Subject"] = assunto
    msg.set_content(corpo)
    if anexo:
        nome, dados, mime = anexo
        tipo, _, sub = (mime or "application/octet-stream").partition("/")
        msg.add_attachment(dados, maintype=tipo, subtype=sub or "octet-stream",
                           filename=nome)
    try:
        ctx = ssl.create_default_context()
        if PORTA == 465:
            with smtplib.SMTP_SSL(HOST, PORTA, context=ctx, timeout=30) as s:
                s.login(USUARIO, SENHA)
                s.send_message(msg)
        else:
            with smtplib.SMTP(HOST, PORTA, timeout=30) as s:
                s.starttls(context=ctx)
                s.login(USUARIO, SENHA)
                s.send_message(msg)
        return {"status": "ok", "message": "Enviado para %s." % para}
    except smtplib.SMTPAuthenticationError:
        # O erro mais provavel, e o mais mal explicado pelo Google: conta com
        # 2FA recusa a senha normal e so aceita senha de app.
        return {"status": "error",
                "message": ("O servidor recusou o login. Com 2FA ligado, o "
                            "Google só aceita SENHA DE APP "
                            "(myaccount.google.com/apppasswords).")}
    except Exception as exc:
        return {"status": "error",
                "message": "%s: %s" % (type(exc).__name__, str(exc)[:160])}
