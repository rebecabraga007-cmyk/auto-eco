"""Rastreamento de custo das chamadas à API Assertiva, por modelo de planilha.

Cada consulta de telefone por CPF via Assertiva custa um valor fixo (hoje
R$0,119 por chamada — configurável via ASSERTIVA_CUSTO_POR_CONSULTA). O
registro é feito no momento da chamada (não no export), e o "modelo" é
o selecionado pelo usuário ANTES de clicar em "Montar lista de contatos"
na Prospecção B2B — se nenhum modelo foi selecionado, fica em "Sem modelo".

Armazenamento: JSONL append-only (uma linha por consulta), no mesmo
diretório de dados usado por config_store/modelos (C:\\capiblu_data ou o
diretório do backend em dev).
"""
import json
import os
import threading
import time

CUSTO_POR_CONSULTA = float(os.environ.get("ASSERTIVA_CUSTO_POR_CONSULTA", "0.119"))

# Sentinela pra "planilha de cliente" — enriquecimento feito por fora dos modelos
# próprios salvos (custo externo), mas ainda rastreado.
CLIENTE_ID = "__cliente__"
CLIENTE_NOME = "Cliente (planilha externa)"

_LOCK = threading.Lock()


def _path() -> str:
    base = r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "capiblu_custos.jsonl")


def log_assertiva(modelo_id: str = "", modelo_nome: str = "", cnpj: str = "", cpf: str = "") -> None:
    """Registra 1 consulta Assertiva (1 chamada = 1 CPF = CUSTO_POR_CONSULTA)."""
    rec = {
        "ts": time.time(),
        "modelo_id": modelo_id or "",
        "modelo_nome": modelo_nome or "",
        "cnpj": cnpj or "",
        "cpf": cpf or "",
        "valor": CUSTO_POR_CONSULTA,
    }
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


def _tipo(modelo_id: str) -> str:
    if modelo_id == CLIENTE_ID:
        return "externo"
    if modelo_id:
        return "interno"
    return "sem_modelo"


def resumo(desde_ts: float = None, ate_ts: float = None) -> dict:
    """Agrega consultas/custo por modelo, dentro do intervalo [desde_ts, ate_ts].

    Classifica cada modelo como 'interno' (modelo próprio salvo), 'externo'
    (planilha de cliente, sentinela CLIENTE_ID) ou 'sem_modelo' (nenhum
    selecionado na hora de montar a lista).
    """
    regs = _ler_tudo()
    if desde_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) >= desde_ts]
    if ate_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) <= ate_ts]

    por_modelo: dict[str, dict] = {}
    for r in regs:
        mid_raw = r.get("modelo_id") or ""
        mid = mid_raw or "__sem_modelo__"
        nome = r.get("modelo_nome") or ("Sem modelo selecionado" if not mid_raw else mid_raw)
        if mid not in por_modelo:
            por_modelo[mid] = {"modelo_id": mid_raw, "modelo_nome": nome, "tipo": _tipo(mid_raw),
                                "n_consultas": 0, "custo_total": 0.0}
        por_modelo[mid]["n_consultas"] += 1
        por_modelo[mid]["custo_total"] += r.get("valor", CUSTO_POR_CONSULTA)

    modelos = sorted(por_modelo.values(), key=lambda m: -m["custo_total"])
    for m in modelos:
        m["custo_total"] = round(m["custo_total"], 3)

    custo_interno = round(sum(m["custo_total"] for m in modelos if m["tipo"] == "interno"), 3)
    custo_externo = round(sum(m["custo_total"] for m in modelos if m["tipo"] == "externo"), 3)
    custo_sem_modelo = round(sum(m["custo_total"] for m in modelos if m["tipo"] == "sem_modelo"), 3)
    total_geral = round(custo_interno + custo_externo + custo_sem_modelo, 3)
    total_consultas = sum(m["n_consultas"] for m in modelos)
    return {"modelos": modelos, "total_geral": total_geral, "total_consultas": total_consultas,
            "custo_interno": custo_interno, "custo_externo": custo_externo,
            "custo_sem_modelo": custo_sem_modelo, "custo_por_consulta": CUSTO_POR_CONSULTA}
