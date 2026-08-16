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
import contextvars
import json
import os
import threading
import time

CUSTO_POR_CONSULTA = float(os.environ.get("ASSERTIVA_CUSTO_POR_CONSULTA", "0.119"))

# ---------------------------------------------------------------------------
# Tabela de preço por TIPO de consulta.
#
# A Assertiva cobra preços diferentes por funcionalidade, e a API não expõe
# nenhum campo de valor — só o contrato comercial diz quanto é cada uma. Até
# alguém preencher os valores reais, tudo cai no CUSTO_POR_CONSULTA (0,119),
# que é o preço conhecido do telefone por CPF. Por isso o total do painel é
# ESTIMATIVA, não fatura.
#
# Os nomes são os que a própria Assertiva usa no relatório de uso
# (functionality), pra bater 1:1 com o que ela contabiliza.
# ---------------------------------------------------------------------------
FUNCIONALIDADES = [
    "CPF", "CNPJ", "Telefone", "E-mail", "Nome ou endereço",
    "Possíveis decisores", "Pessoas de referência", "Mais telefones",
    "Conexões API",
]


def precos() -> dict:
    """Preço por funcionalidade. O que o admin salvar vence; o resto usa o padrão."""
    import config_store
    salvos = config_store.get("assertiva_precos") or {}
    tabela = {f: CUSTO_POR_CONSULTA for f in FUNCIONALIDADES}
    for nome, valor in salvos.items():
        try:
            tabela[nome] = float(valor)
        except (TypeError, ValueError):
            continue
    return tabela


def salvar_precos(novos: dict) -> dict:
    """Guarda a tabela editada pelo admin. Valor vazio/invalido volta ao padrão."""
    import config_store
    limpos = {}
    for nome, valor in (novos or {}).items():
        if valor in (None, ""):
            continue
        try:
            v = float(str(valor).replace(",", "."))
        except (TypeError, ValueError):
            continue
        if v >= 0:
            limpos[nome] = round(v, 4)
    config_store.set_many({"assertiva_precos": limpos})
    return precos()


def preco_de(funcionalidade: str, tabela: dict | None = None) -> float:
    """Preço de uma funcionalidade, com fallback pro valor padrão."""
    t = tabela if tabela is not None else precos()
    return t.get((funcionalidade or "").strip(), CUSTO_POR_CONSULTA)

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


# ---------------------------------------------------------------------------
# Custo por USUÁRIO (todas as chamadas reais à Assertiva, não só as do
# enriquecimento por planilha). Registrado no único ponto por onde toda
# chamada à Assertiva passa (assertiva._get) — cobre CPF/CNPJ/telefone/e-mail/
# nome, tanto Busca Assertiva direta quanto usos internos (dossiê, prospecção).
#
# Armazenamento separado (capiblu_custos_usuario.jsonl) do log por-modelo
# acima, pra não contar a mesma chamada duas vezes nos dois widgets.
# ---------------------------------------------------------------------------

_user_ctx: contextvars.ContextVar[str] = contextvars.ContextVar("assertiva_user_email", default="")


def set_current_user(email: str) -> None:
    """Chamado pelo middleware do backend a cada request, com o e-mail vindo
    do header X-User-Email (que só o app-online/proxy envia)."""
    _user_ctx.set((email or "").strip().lower())


def _path_usuario() -> str:
    base = r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else os.path.dirname(os.path.abspath(__file__))
    return os.path.join(base, "capiblu_custos_usuario.jsonl")


def log_chamada_assertiva(endpoint: str = "") -> None:
    """Registra 1 chamada real (billable) à API Assertiva, atribuída ao usuário
    da request atual (via contextvar) — chamado de dentro de assertiva._get()."""
    rec = {"ts": time.time(), "user": _user_ctx.get() or "desconhecido",
           "endpoint": endpoint or "", "valor": CUSTO_POR_CONSULTA}
    linha = json.dumps(rec, ensure_ascii=False)
    with _LOCK:
        try:
            with open(_path_usuario(), "a", encoding="utf-8") as fh:
                fh.write(linha + "\n")
        except Exception:
            pass


def _ler_tudo_usuario() -> list[dict]:
    p = _path_usuario()
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


def resumo_por_usuario(desde_ts: float = None, ate_ts: float = None, excluir_emails: set = None) -> dict:
    """Custo total de chamadas Assertiva por usuário, no intervalo [desde_ts, ate_ts].

    excluir_emails: emails a remover do resultado (usado pra tirar admins,
    já que um admin não deve ver o consumo de outro admin no painel).
    """
    regs = _ler_tudo_usuario()
    if desde_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) >= desde_ts]
    if ate_ts is not None:
        regs = [r for r in regs if r.get("ts", 0) <= ate_ts]
    excluir = excluir_emails or set()

    por_usuario: dict[str, dict] = {}
    for r in regs:
        u = r.get("user") or "desconhecido"
        if u in excluir:
            continue
        if u not in por_usuario:
            por_usuario[u] = {"user": u, "n_consultas": 0, "custo_total": 0.0}
        por_usuario[u]["n_consultas"] += 1
        por_usuario[u]["custo_total"] += r.get("valor", CUSTO_POR_CONSULTA)

    usuarios = sorted(por_usuario.values(), key=lambda u: -u["custo_total"])
    for u in usuarios:
        u["custo_total"] = round(u["custo_total"], 3)

    total_geral = round(sum(u["custo_total"] for u in usuarios), 3)
    total_consultas = sum(u["n_consultas"] for u in usuarios)
    return {"usuarios": usuarios, "total_geral": total_geral, "total_consultas": total_consultas,
            "custo_por_consulta": CUSTO_POR_CONSULTA}
