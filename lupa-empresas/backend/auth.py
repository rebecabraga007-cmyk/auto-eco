"""Autenticação do CapiBLU: contas, login (JWT), roles (admin/user), gestão de usuários.

Armazenamento: SQLite (AUTH_DB_PATH, default ./capiblu_auth.db). Pequeno e portável —
no Render pode apontar pra um disco persistente ou trocar por Postgres depois.

Cadastro é SÓ por admin: não há auto-registro público. O 1º admin é criado no
bootstrap a partir de ADMIN_EMAIL/ADMIN_PASSWORD (ou um default logado uma vez).
"""
import os
import re
import secrets
import sqlite3
import time
from typing import Any, Optional

import bcrypt
import jwt
from fastapi import APIRouter, Body, Depends, Header, HTTPException, Request, Response

_DB_PATH = os.environ.get(
    "AUTH_DB_PATH",
    os.path.join(os.path.dirname(os.path.abspath(__file__)), "capiblu_auth.db"),
)
_JWT_ALG = "HS256"
COOKIE_NAME = "capiblu_session"  # sessão via cookie httpOnly (robusto, não depende de localStorage)
_TOKEN_TTL = int(os.environ.get("JWT_TTL_SECONDS", str(60 * 60 * 12)))  # 12h
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_UNSET = object()  # sentinela p/ distinguir "não mandou o campo" de "mandou vazio/None"

_DDL = """
CREATE TABLE IF NOT EXISTS users (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  email         TEXT UNIQUE NOT NULL,
  nome          TEXT,
  senha_hash    TEXT NOT NULL,
  role          TEXT NOT NULL DEFAULT 'user',
  ativo         INTEGER NOT NULL DEFAULT 1,
  criado_em     INTEGER NOT NULL,
  ultimo_login  INTEGER
);
CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
CREATE TABLE IF NOT EXISTS grupos (
  id       TEXT PRIMARY KEY,
  nome     TEXT UNIQUE NOT NULL,
  criado_em INTEGER NOT NULL
);
"""


def _migrar_grupo_id(con) -> None:
    """Adiciona users.grupo_id se ainda não existir (SQLite não tem ADD COLUMN IF NOT EXISTS)."""
    cols = [r["name"] for r in con.execute("PRAGMA table_info(users)").fetchall()]
    if "grupo_id" not in cols:
        con.execute("ALTER TABLE users ADD COLUMN grupo_id TEXT")
        con.commit()


def _conn():
    con = sqlite3.connect(_DB_PATH)
    con.row_factory = sqlite3.Row
    return con


def _get_secret(con) -> str:
    # Segredo do JWT: env tem prioridade; senão gera e persiste (estável entre restarts).
    env = os.environ.get("JWT_SECRET")
    if env:
        return env
    row = con.execute("SELECT valor FROM meta WHERE chave='jwt_secret'").fetchone()
    if row:
        return row["valor"]
    s = secrets.token_hex(32)
    con.execute("INSERT INTO meta (chave, valor) VALUES ('jwt_secret', ?)", (s,))
    con.commit()
    return s


def _hash(senha: str) -> str:
    return bcrypt.hashpw(senha.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def _check(senha: str, hash_: str) -> bool:
    try:
        return bcrypt.checkpw(senha.encode("utf-8"), hash_.encode("ascii"))
    except Exception:
        return False


def _row_to_user(r: sqlite3.Row) -> dict:
    cols = r.keys()
    return {"id": r["id"], "email": r["email"], "nome": r["nome"],
            "role": r["role"], "ativo": bool(r["ativo"]),
            "criado_em": r["criado_em"], "ultimo_login": r["ultimo_login"],
            "grupo_id": r["grupo_id"] if "grupo_id" in cols else None}


def init() -> None:
    """Cria as tabelas e o admin inicial (idempotente)."""
    con = _conn()
    con.executescript(_DDL)
    con.commit()
    _migrar_grupo_id(con)
    n = con.execute("SELECT COUNT(*) AS c FROM users").fetchone()["c"]
    if n == 0:
        email = (os.environ.get("ADMIN_EMAIL") or "rebeca@blusalesgroup.com.br").strip().lower()
        senha = os.environ.get("ADMIN_PASSWORD") or secrets.token_urlsafe(9)
        con.execute(
            "INSERT INTO users (email,nome,senha_hash,role,ativo,criado_em) VALUES (?,?,?,?,1,?)",
            (email, "Administrador", _hash(senha), "admin", int(time.time())),
        )
        con.commit()
        if not os.environ.get("ADMIN_PASSWORD"):
            print("=" * 60)
            print(f"[CapiBLU auth] ADMIN criado: {email}")
            print(f"[CapiBLU auth] SENHA INICIAL (troque no 1º acesso): {senha}")
            print("=" * 60)
    con.close()


# ---- Operações de usuário ----

def get_by_email(email: str) -> Optional[dict]:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE email=?", (email.strip().lower(),)).fetchone()
    con.close()
    return dict(r) if r else None


def authenticate(email: str, senha: str) -> Optional[dict]:
    u = get_by_email(email)
    if not u or not u["ativo"] or not _check(senha, u["senha_hash"]):
        return None
    con = _conn()
    con.execute("UPDATE users SET ultimo_login=? WHERE id=?", (int(time.time()), u["id"]))
    con.commit()
    con.close()
    return u


def make_token(user: dict) -> str:
    con = _conn(); secret = _get_secret(con); con.close()
    now = int(time.time())
    payload = {"sub": str(user["id"]), "email": user["email"], "role": user["role"],
               "iat": now, "exp": now + _TOKEN_TTL}
    return jwt.encode(payload, secret, algorithm=_JWT_ALG)


def _decode(token: str) -> dict:
    con = _conn(); secret = _get_secret(con); con.close()
    return jwt.decode(token, secret, algorithms=[_JWT_ALG])


def list_users() -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT * FROM users ORDER BY criado_em DESC").fetchall()
    con.close()
    return [_row_to_user(r) for r in rows]


def create_user(email: str, nome: str, senha: str, role: str = "user", grupo_id: str = "") -> dict:
    email = (email or "").strip().lower()
    if not _EMAIL_RE.match(email):
        raise ValueError("E-mail inválido.")
    if len(senha or "") < 8:
        raise ValueError("Senha deve ter ao menos 8 caracteres.")
    if role not in ("admin", "user"):
        raise ValueError("Role inválida.")
    if get_by_email(email):
        raise ValueError("Já existe um usuário com esse e-mail.")
    con = _conn()
    cur = con.execute(
        "INSERT INTO users (email,nome,senha_hash,role,ativo,criado_em,grupo_id) VALUES (?,?,?,?,1,?,?)",
        (email, (nome or "").strip(), _hash(senha), role, int(time.time()), grupo_id or None))
    con.commit()
    uid = cur.lastrowid
    r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    return _row_to_user(r)


def update_user(uid: int, *, nome=None, role=None, ativo=None, grupo_id=_UNSET) -> dict:
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    if not r:
        con.close(); raise ValueError("Usuário não encontrado.")
    if role is not None and role not in ("admin", "user"):
        con.close(); raise ValueError("Role inválida.")
    if grupo_id is _UNSET:
        con.execute("UPDATE users SET nome=COALESCE(?,nome), role=COALESCE(?,role), ativo=COALESCE(?,ativo) WHERE id=?",
                    (nome, role, (None if ativo is None else int(bool(ativo))), uid))
    else:
        # grupo_id explicitamente enviado (mesmo "" pra remover do grupo) — não é COALESCE.
        gid = grupo_id or None
        con.execute("UPDATE users SET nome=COALESCE(?,nome), role=COALESCE(?,role), ativo=COALESCE(?,ativo), grupo_id=? WHERE id=?",
                    (nome, role, (None if ativo is None else int(bool(ativo))), gid, uid))
    con.commit()
    r = con.execute("SELECT * FROM users WHERE id=?", (uid,)).fetchone()
    con.close()
    return _row_to_user(r)


# ---- Grupos (cada grupo tem seu proprio token Meetime, gerenciado no servico de dados) ----

def listar_grupos() -> list[dict]:
    con = _conn()
    rows = con.execute("SELECT * FROM grupos ORDER BY nome").fetchall()
    con.close()
    return [{"id": r["id"], "nome": r["nome"], "criado_em": r["criado_em"]} for r in rows]


def criar_grupo(nome: str) -> dict:
    nome = (nome or "").strip()
    if not nome:
        raise ValueError("Informe um nome para o grupo.")
    con = _conn()
    existente = con.execute("SELECT id FROM grupos WHERE nome=?", (nome,)).fetchone()
    if existente:
        con.close(); raise ValueError("Já existe um grupo com esse nome.")
    gid = secrets.token_hex(6)
    con.execute("INSERT INTO grupos (id,nome,criado_em) VALUES (?,?,?)", (gid, nome, int(time.time())))
    con.commit(); con.close()
    return {"id": gid, "nome": nome}


def excluir_grupo(gid: str) -> None:
    con = _conn()
    con.execute("UPDATE users SET grupo_id=NULL WHERE grupo_id=?", (gid,))
    con.execute("DELETE FROM grupos WHERE id=?", (gid,))
    con.commit(); con.close()


def set_password(uid: int, senha: str) -> None:
    if len(senha or "") < 8:
        raise ValueError("Senha deve ter ao menos 8 caracteres.")
    con = _conn()
    con.execute("UPDATE users SET senha_hash=? WHERE id=?", (_hash(senha), uid))
    con.commit(); con.close()


def delete_user(uid: int) -> None:
    con = _conn()
    con.execute("DELETE FROM users WHERE id=?", (uid,))
    con.commit(); con.close()


# ---- Dependências FastAPI ----

def _token_from_request(request: Request, authorization: str = "") -> str:
    """Extrai o JWT do header Authorization OU do cookie de sessão."""
    if authorization and authorization.lower().startswith("bearer "):
        return authorization.split(" ", 1)[1].strip()
    try:
        return request.cookies.get(COOKIE_NAME, "") or ""
    except Exception:
        return ""


def _user_from_token(token: str) -> Optional[dict]:
    if not token:
        return None
    try:
        payload = _decode(token)
    except Exception:
        return None
    con = _conn()
    r = con.execute("SELECT * FROM users WHERE id=?", (int(payload.get("sub", 0)),)).fetchone()
    con.close()
    if not r or not r["ativo"]:
        return None
    return _row_to_user(r)


def current_user(request: Request, authorization: str = Header(default="")) -> dict:
    u = _user_from_token(_token_from_request(request, authorization))
    if not u:
        raise HTTPException(status_code=401, detail="Não autenticado.")
    return u


def user_from_request(request: Request) -> Optional[dict]:
    """Header Authorization OU cookie → usuário (sem exceção). Usado no middleware."""
    return _user_from_token(_token_from_request(request, request.headers.get("authorization", "")))


# compat: mantém a assinatura antiga usada em algum lugar
def user_from_bearer(authorization: str) -> Optional[dict]:
    if not authorization or not authorization.lower().startswith("bearer "):
        return None
    return _user_from_token(authorization.split(" ", 1)[1].strip())


def require_admin(user: dict = Depends(current_user)) -> dict:
    if user.get("role") != "admin":
        raise HTTPException(status_code=403, detail="Requer permissão de administrador.")
    return user


# ---- Router ----

router = APIRouter()


@router.post("/api/auth/emergency-reset")
async def emergency_reset(payload: dict = Body(default={})):
    """Reset de senha sem sessão — só funciona se EMERGENCY_RESET_SECRET estiver
    setado no ambiente. Uso único: remover esta rota e a env var depois de usar.
    """
    secret_env = os.environ.get("EMERGENCY_RESET_SECRET")
    if not secret_env or payload.get("secret") != secret_env:
        raise HTTPException(status_code=404)
    u = get_by_email(payload.get("email", ""))
    if not u:
        raise HTTPException(status_code=404, detail="Usuário não encontrado.")
    try:
        set_password(u["id"], payload.get("nova_senha", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.post("/api/auth/login")
async def login(response: Response, payload: dict = Body(default={})):
    u = authenticate(payload.get("email", ""), payload.get("senha", "") or payload.get("password", ""))
    if not u:
        raise HTTPException(status_code=401, detail="E-mail ou senha incorretos.")
    token = make_token(u)
    # Cookie de sessão httpOnly — robusto (não depende de localStorage do navegador).
    response.set_cookie(COOKIE_NAME, token, max_age=_TOKEN_TTL, httponly=True,
                        secure=True, samesite="lax", path="/")
    return {"token": token, "user": _row_to_user(u)}


@router.post("/api/auth/logout")
async def logout(response: Response):
    response.delete_cookie(COOKIE_NAME, path="/")
    return {"ok": True}


@router.get("/api/auth/me")
async def me(user: dict = Depends(current_user)):
    return {"user": user}


@router.post("/api/auth/change-password")
async def change_password(payload: dict = Body(default={}), user: dict = Depends(current_user)):
    atual = payload.get("senha_atual", "")
    nova = payload.get("nova_senha", "")
    full = get_by_email(user["email"])
    if not full or not _check(atual, full["senha_hash"]):
        raise HTTPException(status_code=400, detail="Senha atual incorreta.")
    try:
        set_password(user["id"], nova)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.get("/api/admin/users")
async def admin_list(_: dict = Depends(require_admin)):
    return {"users": list_users()}


@router.post("/api/admin/users")
async def admin_create(payload: dict = Body(default={}), _: dict = Depends(require_admin)):
    try:
        u = create_user(payload.get("email", ""), payload.get("nome", ""),
                        payload.get("senha", ""), payload.get("role", "user"),
                        payload.get("grupo_id", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user": u}


@router.patch("/api/admin/users/{uid}")
async def admin_update(uid: int, payload: dict = Body(default={}),
                       admin: dict = Depends(require_admin)):
    if uid == admin["id"] and payload.get("ativo") is False:
        raise HTTPException(status_code=400, detail="Você não pode se desativar.")
    try:
        u = update_user(uid, nome=payload.get("nome"), role=payload.get("role"),
                        ativo=payload.get("ativo"),
                        grupo_id=(payload.get("grupo_id") if "grupo_id" in payload else _UNSET))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"user": u}


@router.get("/api/admin/grupos")
async def admin_grupos_listar(_: dict = Depends(require_admin)):
    return {"grupos": listar_grupos()}


@router.post("/api/admin/grupos")
async def admin_grupos_criar(payload: dict = Body(default={}), _: dict = Depends(require_admin)):
    try:
        g = criar_grupo(payload.get("nome", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"grupo": g}


@router.delete("/api/admin/grupos/{gid}")
async def admin_grupos_excluir(gid: str, _: dict = Depends(require_admin)):
    excluir_grupo(gid)
    return {"ok": True}


@router.post("/api/admin/users/{uid}/password")
async def admin_reset_password(uid: int, payload: dict = Body(default={}),
                               _: dict = Depends(require_admin)):
    try:
        set_password(uid, payload.get("senha", ""))
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    return {"ok": True}


@router.delete("/api/admin/users/{uid}")
async def admin_delete(uid: int, admin: dict = Depends(require_admin)):
    if uid == admin["id"]:
        raise HTTPException(status_code=400, detail="Você não pode se excluir.")
    delete_user(uid)
    return {"ok": True}
