"""Registro de acesso a dado pessoal.

Fica no middleware, e não espalhado pelas rotas, por um motivo prático: rota
nova nasce auditada. Depender de cada autor lembrar de chamar o log é como o
`nao_perturbe`, que era coletado e nunca consultado.

O que **não** entra: listar cadência, abrir o painel, mexer em meta. Registrar
tudo transforma a trilha em ruído e some com o que importa.
"""
import re

from .db import SessionLocal
from .models import AuditLog

# Rotas que tocam pessoa física ou fazem a plataforma gastar consulta paga.
# A ordem importa: a primeira que casar nomeia a ação.
# Dois vocabulários de caminho passam por aqui: as rotas do Bluutime
# (`/api/capiblu/empresas/...`) e as do serviço de dados montado
# (`/capiblu/api/company/...`), que a UI antiga ainda alcança direto. Os dois
# precisam casar, senão a trilha fica com buraco justamente no caminho curto.
ACOES = [
    (re.compile(r"/api/capiblu/dossie/|/capiblu/api/dossie"), "DOSSIE"),
    (re.compile(r"/api/capiblu/pessoas/[^/]+/(mk|parentes|vinculos)"
                r"|/capiblu/api/person/[^/]+/(mk|parentes|vinculos)"), "PESSOA_PERFIL"),
    (re.compile(r"/api/capiblu/pessoas|/capiblu/api/person"), "PESSOA"),
    (re.compile(r"/api/capiblu/telefones|/capiblu/api/phone"), "TELEFONE_REVERSO"),
    (re.compile(r"/capiblu/api/assertiva"), "ASSERTIVA"),
    (re.compile(r"/api/capiblu/planilha/(enriquecer|linha)"
                r"|/capiblu/api/enrich/(run|linha)"), "ENRIQUECIMENTO"),
    (re.compile(r"/api/capiblu/empresas/\d+/(decisores|conexoes|contacts|employees|vinculos)"
                r"|/capiblu/api/company/[^/]+/(decisores|conexoes|leads|contacts|vinculos)"),
     "DECISORES"),
    (re.compile(r"/api/capiblu/prospect/(import|cobertura)"), "MONTAR_BASE"),
    (re.compile(r"/api/envio/(atividades|teste)"), "ENVIO"),
    (re.compile(r"/api/whatsapp/conversations/\d+/messages"), "ENVIO"),
]

# Documento ou telefone no caminho — é o "de quem" da consulta.
_SUBJECT = re.compile(r"/(\d{8,14})(?:/|$|\?)")


def acao_de(path: str) -> str:
    for padrao, nome in ACOES:
        if padrao.search(path):
            return nome
    return ""


def _mascara(doc: str) -> str:
    """CPF vira 123.***.**9-00: dá para reconciliar sem republicar o número.

    A trilha existe para provar quem acessou o quê; guardar o CPF inteiro de
    novo, num lugar a mais, aumenta a exposição em vez de reduzir.
    """
    if len(doc) == 11:
        return f"{doc[:3]}.***.**{doc[8]}-{doc[9:]}"
    if len(doc) == 14:
        return f"{doc[:2]}.***.***/{doc[8:12]}-{doc[12:]}"
    return doc[:4] + "*" * max(0, len(doc) - 6) + doc[-2:]


def registrar(*, path: str, acao: str, ator, status: int, detail: str = "") -> None:
    m = _SUBJECT.search(path)
    db = SessionLocal()
    try:
        db.add(AuditLog(actor_email=ator.email, actor_level=ator.nivel, action=acao,
                        subject=_mascara(m.group(1)) if m else "",
                        path=path[:200], status=status, detail=detail[:240]))
        db.commit()
    except Exception:                       # auditoria nunca derruba o request
        db.rollback()
    finally:
        db.close()
