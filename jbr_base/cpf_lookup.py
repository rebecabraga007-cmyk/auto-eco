"""Consulta na base JBR_PF (CPF|Nome|Sexo|Nascimento).

Funcoes principais:
- by_cpf(cpf): dados de um CPF exato.
- by_name(nome, limit): candidatos por nome (homonimos).
- resolve_socio(nome, cpf_mascarado): resolve o CPF EXATO de um socio do QSA,
  cruzando o nome com os 6 digitos do meio revelados na mascara (ex.: '***912137**').

O banco (jbr_pf.db) e somente-leitura aqui e fica FORA do git.
"""

import os
import re
import sqlite3
import unicodedata

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jbr_pf.db")


def _norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s or "").encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def _conn() -> sqlite3.Connection:
    # Somente-leitura, nao trava a carga em andamento.
    uri = f"file:{DB_PATH}?mode=ro"
    con = sqlite3.connect(uri, uri=True, timeout=5)
    con.row_factory = sqlite3.Row
    return con


def available() -> bool:
    return os.path.exists(DB_PATH)


def ready() -> bool:
    """True somente quando a base terminou de carregar E indexar.

    Durante a ingestao o indice idx_nome ainda nao existe, entao os endpoints
    nao tentam consultar (evita leitura durante escrita pesada).
    """
    if not os.path.exists(DB_PATH):
        return False
    try:
        with _conn() as con:
            r = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_nome'"
            ).fetchone()
            return r is not None
    except Exception:
        return False


def _row(r: sqlite3.Row) -> dict:
    return {
        "cpf": r["cpf"],
        "nome": r["nome"],
        "sexo": r["sexo"],
        "nascimento": r["nascimento"],
    }


def by_cpf(cpf: str) -> dict | None:
    digits = re.sub(r"\D", "", cpf or "").zfill(11)[:11]
    with _conn() as con:
        r = con.execute(
            "SELECT cpf,nome,sexo,nascimento FROM pessoas WHERE cpf=? LIMIT 1", (digits,)
        ).fetchone()
        return _row(r) if r else None


def by_name(nome: str, limit: int = 20) -> list[dict]:
    nn = _norm(nome)
    if not nn:
        return []
    with _conn() as con:
        rows = con.execute(
            "SELECT cpf,nome,sexo,nascimento FROM pessoas WHERE nome_norm=? LIMIT ?",
            (nn, limit),
        ).fetchall()
        return [_row(r) for r in rows]


def _mask_middle6(cpf_mascarado: str) -> str | None:
    """Extrai os 6 digitos do meio de uma mascara tipo '***912137**'."""
    digits = re.sub(r"\D", "", cpf_mascarado or "")
    return digits if len(digits) == 6 else None


def resolve_socio(nome: str, cpf_mascarado: str = "") -> dict:
    """Resolve o CPF de um socio/pessoa.

    Retorna {status, cpf?, pessoa?, candidates?}:
    - 'resolved': match unico por nome + 6 digitos do meio (ou nome unico).
    - 'ambiguous': varios candidatos (retorna a lista).
    - 'not_found': nenhum.
    """
    nn = _norm(nome)
    if not nn:
        return {"status": "not_found", "candidates": []}

    mid6 = _mask_middle6(cpf_mascarado)
    with _conn() as con:
        rows = con.execute(
            "SELECT cpf,nome,sexo,nascimento FROM pessoas WHERE nome_norm=? LIMIT 500",
            (nn,),
        ).fetchall()

    cands = [_row(r) for r in rows]
    if mid6:
        exact = [c for c in cands if c["cpf"][3:9] == mid6]
        if len(exact) == 1:
            return {"status": "resolved", "cpf": exact[0]["cpf"], "pessoa": exact[0]}
        if len(exact) > 1:
            return {"status": "ambiguous", "candidates": exact}
        # mascara nao bateu com ninguem desse nome
        return {"status": "not_found", "candidates": cands[:20]}

    if len(cands) == 1:
        return {"status": "resolved", "cpf": cands[0]["cpf"], "pessoa": cands[0]}
    if not cands:
        return {"status": "not_found", "candidates": []}
    return {"status": "ambiguous", "candidates": cands[:20]}


def _broad_where(nome: str):
    """Monta cláusula WHERE + params para busca ampla por todas as palavras.

    O primeiro termo vira um RANGE (nome_norm >= 'JANINE' AND < 'JANINE\\uffff')
    em vez de LIKE 'JANINE%'. Isso é crucial: o LIKE case-insensitive do SQLite
    NÃO usa o índice idx_nome (faz SCAN de 223M linhas ~ 90s); o range faz um
    SEARCH (seek) no índice, em milissegundos. Os demais termos usam %palavra%
    como filtro residual — barato, pois já restrito à faixa do primeiro nome.
    """
    parts = _norm(nome).split()
    if not parts:
        return None, None
    prefix = parts[0]
    where = "nome_norm >= ? AND nome_norm < ?"
    params = [prefix, prefix + "￿"]
    for w in parts[1:]:
        where += " AND nome_norm LIKE ?"
        params.append("%" + w + "%")
    return where, params


def count_name_broad(nome: str) -> int:
    """Total de pessoas que batem na busca ampla (sem paginação)."""
    where, params = _broad_where(nome)
    if not where:
        return 0
    with _conn() as con:
        r = con.execute(
            f"SELECT COUNT(*) AS n FROM pessoas WHERE {where}", params
        ).fetchone()
        return r["n"] if r else 0


def by_name_broad(nome: str, limit: int = 50, offset: int = 0) -> list[dict]:
    """Busca ampla — nomes que contenham todas as palavras pesquisadas.

    Ex.: 'Janine Sampaio' → JANINE% AND %SAMPAIO% no SQL, ordenado por nome.
    Suporta paginação via offset (para 'Ver mais' / 'Buscar todos').
    """
    where, params = _broad_where(nome)
    if not where:
        return []
    with _conn() as con:
        rows = con.execute(
            f"SELECT cpf,nome,sexo,nascimento FROM pessoas WHERE {where} "
            "ORDER BY nome_norm LIMIT ? OFFSET ?",
            params + [limit, offset],
        ).fetchall()
    return [
        {"cpf": r["cpf"], "nome": r["nome"], "sexo": r["sexo"], "nascimento": r["nascimento"]}
        for r in rows
    ]


if __name__ == "__main__":
    import sys

    if len(sys.argv) >= 2:
        print(by_name(sys.argv[1]))
