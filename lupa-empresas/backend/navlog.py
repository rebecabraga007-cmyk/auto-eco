"""Histórico de navegação: qual usuário abriu qual aba, e quando.

Usado pelo painel administrativo (aba "admin"). Armazenamento: JSONL
append-only, mesmo padrão de custos.py/config_store.py.
"""
import json
import os
import threading
import time

_LOCK = threading.Lock()
_MAX_ENTRIES_RETORNO = 3000


def _path() -> str:
    base = r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "capiblu_navlog.jsonl")


def registrar(user_email: str, tab: str, tipo: str = "", query: str = "", resultado: str = "") -> None:
    if not tab:
        return
    rec = {"ts": time.time(), "user": (user_email or "desconhecido").strip().lower(), "tab": tab}
    if tipo:
        rec["tipo"] = tipo
        rec["query"] = query
        rec["resultado"] = resultado
    linha = json.dumps(rec, ensure_ascii=False)
    with _LOCK:
        try:
            with open(_path(), "a", encoding="utf-8") as fh:
                fh.write(linha + "\n")
        except Exception:
            pass


def _ler_tudo() -> list[dict]:
    p = _path()
    if not os.path.exists(p):
        return []
    out = []
    try:
        with open(p, encoding="utf-8") as fh:
            for linha in fh:
                linha = linha.strip()
                if not linha:
                    continue
                try:
                    out.append(json.loads(linha))
                except Exception:
                    continue
    except Exception:
        pass
    return out


def listar(desde_ts: float = None, ate_ts: float = None, user_email: str = "") -> dict:
    """Histórico filtrado, mais recente primeiro, + agregados por usuário e por aba."""
    regs = _ler_tudo()
    if desde_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) >= desde_ts]
    if ate_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) <= ate_ts]
    if user_email:
        alvo = user_email.strip().lower()
        regs = [r for r in regs if r.get("user") == alvo]

    regs = sorted(regs, key=lambda r: -r.get("ts", 0))

    por_usuario: dict[str, int] = {}
    por_aba: dict[str, int] = {}
    usuarios = set()
    for r in regs:
        u = r.get("user", "")
        t = r.get("tab", "")
        por_usuario[u] = por_usuario.get(u, 0) + 1
        por_aba[t] = por_aba.get(t, 0) + 1
        usuarios.add(u)

    return {
        "entradas": regs[:_MAX_ENTRIES_RETORNO],
        "total": len(regs),
        "truncado": len(regs) > _MAX_ENTRIES_RETORNO,
        "por_usuario": por_usuario,
        "por_aba": por_aba,
        "usuarios": sorted(usuarios),
    }


def resumo_usuario(user_email: str, dias: int = 7) -> dict:
    """Resumo pro painel "Início" de UM usuário: uso por dia, ferramenta mais
    usada e últimas pesquisas (só as que tiveram tipo/query, não todo clique
    de aba)."""
    alvo = (user_email or "").strip().lower()
    desde_ts = time.time() - dias * 86400
    regs = [r for r in _ler_tudo() if r.get("user") == alvo and r.get("ts", 0) >= desde_ts]

    por_dia: dict[str, int] = {}
    por_aba: dict[str, int] = {}
    for r in regs:
        dia = time.strftime("%d/%m", time.localtime(r.get("ts", 0)))
        por_aba[r.get("tab", "")] = por_aba.get(r.get("tab", ""), 0) + 1
        if r.get("tipo"):
            por_dia[dia] = por_dia.get(dia, 0) + 1

    pesquisas = sorted([r for r in regs if r.get("tipo")], key=lambda r: -r.get("ts", 0))[:8]

    return {
        "por_dia": por_dia,
        "por_aba": por_aba,
        "total_pesquisas": sum(por_dia.values()),
        "ultimas_pesquisas": pesquisas,
    }
