"""Tokens de API do CapiBLU — credencial de máquina, separada do login de gente.

Nos moldes da API da Meetime: o cliente manda `Authorization: Bearer <token>` e
recebe JSON. Diferente da sessão do navegador (cookie de 24h que desliza), um
token de API não expira sozinho — vive até alguém revogar.

Guardamos apenas o HASH do token (sha256). O valor em claro aparece UMA vez, na
criação: se a pessoa perder, revoga e cria outro. Isso evita que um vazamento do
banco de usuários entregue acesso à API.

Formato do token: `capi_<prefixo8>_<segredo32>`
O prefixo vai em claro na tabela — serve pra identificar o token na listagem e
nos logs sem nunca guardar o segredo.
"""

import hashlib
import os
import secrets
import sqlite3
import time
from typing import Optional

_DB_PATH = os.environ.get(
    "AUTH_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "capiblu_auth.db"),
)

PREFIXO = "capi"

_DDL = """
CREATE TABLE IF NOT EXISTS api_tokens (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  user_id     INTEGER NOT NULL,
  nome        TEXT NOT NULL,
  prefixo     TEXT NOT NULL,
  token_hash  TEXT NOT NULL UNIQUE,
  escopo      TEXT NOT NULL DEFAULT 'leitura',
  ativo       INTEGER NOT NULL DEFAULT 1,
  criado_em   INTEGER NOT NULL,
  ultimo_uso  INTEGER,
  chamadas    INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_api_tokens_hash ON api_tokens(token_hash);
"""


def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    con = _conn()
    con.executescript(_DDL)
    con.commit()
    con.close()


def _hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def criar(user_id: int, nome: str, escopo: str = "leitura") -> dict:
    """Cria um token e devolve o valor EM CLARO (única vez que ele existe assim)."""
    nome = (nome or "").strip() or "sem nome"
    if escopo not in ("leitura", "consulta"):
        raise ValueError("escopo deve ser 'leitura' (base local) ou 'consulta' (permite gastar).")
    prefixo = secrets.token_hex(4)
    segredo = secrets.token_urlsafe(24)
    token = f"{PREFIXO}_{prefixo}_{segredo}"
    con = _conn()
    cur = con.execute(
        "INSERT INTO api_tokens (user_id, nome, prefixo, token_hash, escopo, criado_em) "
        "VALUES (?,?,?,?,?,?)",
        (user_id, nome, prefixo, _hash(token), escopo, int(time.time())))
    con.commit()
    tid = cur.lastrowid
    con.close()
    return {"id": tid, "nome": nome, "prefixo": prefixo, "escopo": escopo, "token": token}


def listar(user_id: Optional[int] = None) -> list[dict]:
    """Tokens cadastrados (sem o segredo — ele não existe mais em lugar nenhum)."""
    con = _conn()
    if user_id is None:
        rows = con.execute("SELECT * FROM api_tokens ORDER BY criado_em DESC").fetchall()
    else:
        rows = con.execute("SELECT * FROM api_tokens WHERE user_id=? ORDER BY criado_em DESC",
                           (user_id,)).fetchall()
    con.close()
    return [{"id": r["id"], "user_id": r["user_id"], "nome": r["nome"],
             "token": f"{PREFIXO}_{r['prefixo']}_••••••••", "escopo": r["escopo"],
             "ativo": bool(r["ativo"]), "criado_em": r["criado_em"],
             "ultimo_uso": r["ultimo_uso"], "chamadas": r["chamadas"]} for r in rows]


def revogar(token_id: int) -> bool:
    con = _conn()
    cur = con.execute("UPDATE api_tokens SET ativo=0 WHERE id=?", (token_id,))
    con.commit()
    mudou = cur.rowcount > 0
    con.close()
    return mudou


def autenticar(token: str) -> Optional[dict]:
    """Token válido → {token_id, user_id, escopo, nome}. Registra o uso."""
    token = (token or "").strip()
    if not token.startswith(PREFIXO + "_"):
        return None
    con = _conn()
    r = con.execute("SELECT * FROM api_tokens WHERE token_hash=? AND ativo=1",
                    (_hash(token),)).fetchone()
    if not r:
        con.close()
        return None
    con.execute("UPDATE api_tokens SET ultimo_uso=?, chamadas=chamadas+1 WHERE id=?",
                (int(time.time()), r["id"]))
    con.commit()
    con.close()
    return {"token_id": r["id"], "user_id": r["user_id"], "escopo": r["escopo"],
            "nome": r["nome"]}
