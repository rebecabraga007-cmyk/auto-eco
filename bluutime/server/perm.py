"""Quem pode o quê.

Dois cadastros de papel coexistem e nenhum dos dois sozinho responde:

- o **login** é do CapiBLU (`admin` ou `user`) — é quem está na sessão;
- o **papel operacional** vem do Meetime (`ADMINISTRATOR`, `MANAGER`,
  `SALESMAN`) e está no `User` do Bluutime, que é quem é dono de lead.

A ligação entre os dois é o e-mail. Aqui eles viram um nível efetivo, e é esse
nível que as rotas exigem.
"""
from fastapi import HTTPException
from sqlalchemy import func
from sqlalchemy.orm import Session

from .deps import session_user
from .models import Company, User

# Do mais fraco para o mais forte — a comparação é por índice.
NIVEIS = ("sdr", "gestor", "admin")


class Ator:
    """O usuário do request: identidade do login + registro operacional."""

    def __init__(self, sessao: dict | None, user: User | None):
        self.sessao = sessao or {}
        self.user = user

    @property
    def email(self) -> str:
        return self.sessao.get("email", "")

    @property
    def user_id(self) -> int | None:
        return self.user.id if self.user else None

    @property
    def nivel(self) -> str:
        # Admin do CapiBLU manda em tudo: é a conta que administra a plataforma.
        if self.sessao.get("role") == "admin":
            return "admin"
        papeis = set(self.user.role_list if self.user else [])
        if papeis & {"ADMINISTRATOR", "MANAGER"}:
            return "gestor"
        return "sdr"

    def pelo_menos(self, nivel: str) -> bool:
        return NIVEIS.index(self.nivel) >= NIVEIS.index(nivel)

    def exigir(self, nivel: str, acao: str = "") -> None:
        if not self.pelo_menos(nivel):
            raise HTTPException(403, f"Requer perfil de {nivel}"
                                     + (f" para {acao}." if acao else "."))

    def as_dict(self) -> dict:
        return {"email": self.email, "nivel": self.nivel, "userId": self.user_id,
                "nome": self.user.name if self.user else self.email,
                "papeisMeetime": self.user.role_list if self.user else []}


def ator(db: Session) -> Ator:
    """O ator do request atual. Nunca levanta: rota pública devolve ator vazio."""
    sessao = session_user()
    user = None
    if sessao and sessao.get("email"):
        user = (db.query(User)
                .filter(func.lower(User.email) == sessao["email"].strip().lower()).first())
        # Desativado no Bluutime perde o papel operacional na hora. Antes só o
        # "ativo" do login do CapiBLU contava: um gestor desativado em Usuários
        # e times seguia vendo e exportando a carteira de todo mundo.
        if user is not None and user.active is False:
            user = None
    return Ator(sessao, user)


def escopo_leads(db: Session, query, a: Ator, coluna):
    """Restringe a consulta ao que o ator pode ver.

    SDR enxerga só os leads dos quais é dono — a menos que a empresa tenha
    ligado "Ver leads de outros usuários" nas permissões (o que no Meetime é
    LEADS_VIEW_ALL). Gestor e admin sempre veem tudo — é o trabalho deles.
    """
    if a.pelo_menos("gestor"):
        return query
    empresa = db.query(Company).first()
    if empresa and empresa.leads_visible_all:
        return query
    # SDR sem registro operacional não é dono de nada: melhor lista vazia do
    # que a carteira inteira por falta de vínculo.
    return query.filter(coluna == (a.user_id or -1))


def exigir_dono_lead(db: Session, a: Ator, lead, *, escrita: bool = True,
                     sem_lead_ok: bool = False) -> None:
    """Mesma regra de `escopo_leads`, mas para acesso por ID direto.

    A listagem já filtrava a carteira do SDR; o acesso por ID (`GET/PATCH
    /leads/{lid}`, executar atividade, retomar cadência, marcar ganho/perda)
    não conferia nada — um SDR que soubesse ou adivinhasse o ID de um lead
    alheio lia e mexia nele mesmo sem "Ver leads de outros usuários" ligado.

    `lead=None` passa direto: usado também para recursos que só ÀS VEZES têm
    lead associado (conversa de WhatsApp por telefone avulso, sem lead) — não
    há dono nenhum pra violar, então não há o que bloquear.
    """
    if a.pelo_menos("gestor"):
        return
    if lead is None:
        # Recurso sem lead (conversa de WhatsApp de número desconhecido, por
        # exemplo) não tem dono para conferir — e por isso é de gestor. Antes
        # passava direto e qualquer SDR lia e respondia pelo número da empresa.
        if sem_lead_ok:
            return
        raise HTTPException(403, "Só gestor acessa o que não está ligado a um lead seu.")
    # Sem cadastro de SDR (user_id None) nada é "seu": antes `None == None`
    # dava acesso a todo lead sem dono.
    if a.user_id is not None and lead.sdr_id == a.user_id:
        return
    # "Ver leads de outros usuários" é VER: editar, dar ganho, executar, enviar
    # ou discar continua sendo só do dono (ou de gestor).
    if not escrita:
        empresa = db.query(Company).first()
        if empresa and empresa.leads_visible_all:
            return
    raise HTTPException(403, "Este lead não é seu.")


def exigir_ou_permissao(db: Session, a: Ator, campo: str, acao: str) -> None:
    """Gestor/admin sempre passam; SDR só se a empresa liberou essa permissão
    especificamente (equivalente ao LEADS_ADD_MANUAL/STATISTICS_ACCESS/etc. do
    Meetime, configurável em Ajustes > Permissões)."""
    if a.pelo_menos("gestor"):
        return
    empresa = db.query(Company).first()
    if not (empresa and getattr(empresa, campo, False)):
        raise HTTPException(403, f"Sem permissão para {acao}.")
