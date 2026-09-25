"""Academia: progresso da wiki gamificada e dos tours guiados.

Cada pessoa guarda o que concluiu (capítulos lidos, quizzes, missões do tour).
O XP é calculado aqui, a partir do catálogo abaixo — o navegador manda só a
lista do que foi feito. Gestor vê o progresso do time para acompanhar quem
está chegando.
"""
import json
from datetime import datetime

from fastapi import APIRouter, Body, Depends, HTTPException
from sqlalchemy.orm import Session

from .. import perm
from ..db import get_db
from ..deps import session_email
from ..models import AcademiaProgresso, User

router = APIRouter(prefix="/api/academia")

CAPITULOS = ["papeis", "rotina", "cadencia", "ligacao", "ganho", "perdido",
             "metricas", "armadilhas"]
MISSOES = {"execucao": 60, "iniciar": 50, "pesquisa": 50, "email": 50, "ligacao": 80, "extra": 50,
           "perdido": 60, "ganho": 80, "novo-lead": 60, "numeros": 50}
XP_LEITURA = 20
XP_QUIZ_MAX = 30  # proporcional aos acertos
NIVEIS = [(0, "Recruta"), (150, "SDR em treinamento"), (400, "SDR"),
          (800, "BDR pleno"), (1200, "Máquina de reuniões")]
_LIMITE_BYTES = 32_000


def catalogo() -> dict:
    return {"capitulos": {c: {"leitura": XP_LEITURA, "quiz": XP_QUIZ_MAX} for c in CAPITULOS},
            "missoes": MISSOES, "niveis": [{"xp": x, "nome": n} for x, n in NIVEIS]}


def _lista(v) -> list:
    return [x for x in v if isinstance(x, str)] if isinstance(v, list) else []


def _inteiro(v) -> int:
    try:
        return int(v)
    except (TypeError, ValueError):
        return -1


def _limpo(data: dict) -> dict:
    """Só o que o catálogo conhece entra — o resto é descartado em silêncio."""
    data = data if isinstance(data, dict) else {}
    lidos = [c for c in dict.fromkeys(_lista(data.get("lidos"))) if c in CAPITULOS]
    quizzes = {}
    qs = data.get("quizzes") if isinstance(data.get("quizzes"), dict) else {}
    for cap, r in qs.items():
        if cap not in CAPITULOS or not isinstance(r, dict):
            continue
        total, acertos = _inteiro(r.get("total")), _inteiro(r.get("acertos"))
        if 0 < total <= 20 and 0 <= acertos <= total:
            quizzes[cap] = {"acertos": acertos, "total": total}
    missoes = [m for m in dict.fromkeys(_lista(data.get("missoes"))) if m in MISSOES]
    return {"lidos": lidos, "quizzes": quizzes, "missoes": missoes,
            "tourOferecido": bool(data.get("tourOferecido"))}


def calcular_xp(data: dict) -> int:
    xp = XP_LEITURA * len(data["lidos"])
    xp += sum(round(XP_QUIZ_MAX * q["acertos"] / q["total"]) for q in data["quizzes"].values())
    xp += sum(MISSOES[m] for m in data["missoes"])
    return xp


def nivel_de(xp: int) -> dict:
    atual, prox = NIVEIS[0], None
    for i, (limite, nome) in enumerate(NIVEIS):
        if xp >= limite:
            atual = (limite, nome)
            prox = NIVEIS[i + 1] if i + 1 < len(NIVEIS) else None
    return {"nome": atual[1], "desde": atual[0],
            "proximo": {"nome": prox[1], "xp": prox[0]} if prox else None}


def _saida(p: AcademiaProgresso | None) -> dict:
    data = _limpo(json.loads(p.data) if p else {})
    xp = calcular_xp(data)
    return {"progresso": data, "xp": xp, "nivel": nivel_de(xp), "catalogo": catalogo(),
            "atualizadoEm": p.updated_at.isoformat() + "Z" if p and p.updated_at else None}


@router.get("/me")
def meu_progresso(db: Session = Depends(get_db)):
    email = session_email()
    if not email:
        raise HTTPException(401, "Sem sessão.")
    p = db.query(AcademiaProgresso).filter(AcademiaProgresso.email == email).first()
    return _saida(p)


@router.put("/me")
def salvar_progresso(payload: dict = Body(...), db: Session = Depends(get_db)):
    email = session_email()
    if not email:
        raise HTTPException(401, "Sem sessão.")
    bruto = payload.get("progresso") or {}
    if not isinstance(bruto, dict) or len(json.dumps(bruto)) > _LIMITE_BYTES:
        raise HTTPException(400, "Progresso inválido.")
    data = _limpo(bruto)
    p = db.query(AcademiaProgresso).filter(AcademiaProgresso.email == email).first()
    if not p:
        p = AcademiaProgresso(email=email)
        db.add(p)
    p.data = json.dumps(data, ensure_ascii=False)
    p.xp = calcular_xp(data)
    p.updated_at = datetime.utcnow()
    db.commit()
    return _saida(p)


@router.get("/time")
def progresso_do_time(db: Session = Depends(get_db)):
    """Quem já fez o quê — para o gestor acompanhar a entrada de gente nova."""
    perm.ator(db).exigir("gestor", "ver o progresso do time")
    nomes = {u.email: u.name for u in db.query(User).all()}
    linhas = []
    for p in db.query(AcademiaProgresso).order_by(AcademiaProgresso.xp.desc()).all():
        data = _limpo(json.loads(p.data or "{}"))
        linhas.append({"email": p.email, "nome": nomes.get(p.email) or p.email, "xp": p.xp,
                       "nivel": nivel_de(p.xp)["nome"], "lidos": len(data["lidos"]),
                       "quizzes": len(data["quizzes"]), "missoes": len(data["missoes"]),
                       "atualizadoEm": p.updated_at.isoformat() + "Z" if p.updated_at else None})
    return {"data": linhas, "totais": {"capitulos": len(CAPITULOS), "missoes": len(MISSOES)}}
