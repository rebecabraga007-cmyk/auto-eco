"""Progresso de tarefa longa, para a tela não ficar cega.

A migração do Meetime leva cinco minutos e até agora não mostrava nada — quem
disparava não sabia se estava andando ou travado. Guardar em memória basta:
progresso não sobrevive a reinício, e não deveria mesmo, porque a tarefa também
não sobrevive.
"""
import threading
from datetime import datetime

_lock = threading.Lock()
_tarefas: dict[str, dict] = {}


def iniciar(chave: str, titulo: str) -> None:
    with _lock:
        _tarefas[chave] = {"titulo": titulo, "estado": "RODANDO", "feito": 0,
                           "total": 0, "etapa": "", "inicio": datetime.utcnow(),
                           "fim": None, "resultado": None, "erro": ""}


def etapa(chave: str, texto: str, feito: int = 0, total: int = 0) -> None:
    with _lock:
        t = _tarefas.get(chave)
        if t:
            t.update(etapa=texto, feito=feito, total=total)


def concluir(chave: str, resultado=None, erro: str = "") -> None:
    with _lock:
        t = _tarefas.get(chave)
        if t:
            t.update(estado="ERRO" if erro else "PRONTO", fim=datetime.utcnow(),
                     resultado=resultado, erro=erro[:300])


def ler(chave: str) -> dict | None:
    with _lock:
        t = _tarefas.get(chave)
        if not t:
            return None
        d = dict(t)
    inicio, fim = d.pop("inicio"), d.pop("fim")
    d["segundos"] = round(((fim or datetime.utcnow()) - inicio).total_seconds(), 1)
    d["percentual"] = round(d["feito"] / d["total"] * 100) if d["total"] else None
    return d
