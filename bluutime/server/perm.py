"""Quem pode o quê.

Dois cadastros de papel coexistem e nenhum dos dois sozinho responde:

- o **login** é do CapiBLU (`admin` ou `user`) — é quem está na sessão;
- o **papel operacional** vem do Meetime (`ADMINISTRATOR`, `MANAGER`,
  `SALESMAN`) e está no `User` do Bluutime, que é quem é dono de lead.

A ligação entre os dois é o e-mail. Aqui eles viram um nível efetivo, e é esse
nível que as rotas exigem.
"""
from fastapi import HTTPException
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
        user = db.query(User).filter(User.email == sessao["email"]).first()
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


def exigir_ou_permissao(db: Session, a: Ator, campo: str, acao: str) -> None:
    """Gestor/admin sempre passam; SDR só se a empresa liberou essa permissão
    especificamente (equivalente ao LEADS_ADD_MANUAL/STATISTICS_ACCESS/etc. do
    Meetime, configurável em Ajustes > Permissões)."""
    if a.pelo_menos("gestor"):
        return
    empresa = db.query(Company).first()
    if not (empresa and getattr(empresa, campo, False)):
        raise HTTPException(403, f"Sem permissão para {acao}.")
