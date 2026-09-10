# -*- coding: utf-8 -*-
"""Base local dos leads da Meetime, por conta, com sincronizacao incremental.

O PROBLEMA
----------
Nao existe filtro por CNPJ na API da Meetime. Medido: `GET /v2/leads` aceita
SO `id`, `email`, `limit` e `start` -- `cnpj`, `document`, `search` e mais
dez variantes devolvem HTTP 400. Para saber se uma empresa ja esta no CRM e
preciso varrer a base inteira e indexar deste lado: 20.689 leads deram 207
requisicoes e 118 segundos.

Fazer isso a cada busca e inviavel, e era o que acontecia -- o cache era so
em memoria e com validade curta, entao reiniciar o servico ou esperar demais
custava os 118 segundos de novo.

A SINCRONIZACAO INCREMENTAL, E POR QUE E POR OFFSET
---------------------------------------------------
O caminho natural seria "me da os leads criados depois de tal data". A API
NAO ACEITA: `start_date` e `sort` devolvem 400, e a ordem e sempre crescente,
fixa. Entao o unico jeito de pegar so o que e novo e retomar pelo OFFSET --
se da ultima vez a conta tinha 12.158 leads, comeca em 12.158 e le dali para
frente. O que e novo esta no fim.

Isso tem uma condicao: lead APAGADO encurta a lista e desalinha os offsets.
Por isso guardamos tambem quantos havia; se a contagem DIMINUIU, alguem
apagou, os offsets nao valem mais e a base e refeita do zero. Preferir
refazer a arriscar indice furado silencioso.

O QUE NAO E GUARDADO: O TOKEN
-----------------------------
A conta e identificada pelo SHA-256 do token, nunca pelo token. O operador
redigita quando precisar; o que fica no disco sao os CNPJs e nomes da base
dele, que e o que evita o recrawl. Assim a funcionalidade que a Rebeca pediu
-- "criar um ID para aquele token e lembrar dos prospectados" -- existe sem
que a credencial passe a morar no servidor.
"""
import hashlib
import os
import sqlite3
import time
from typing import Any

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "meetime_base.db")

DDL = """
CREATE TABLE IF NOT EXISTS contas (
  conta       TEXT PRIMARY KEY,   -- sha256(token)[:16] ou "grupo:<id>"
  apelido     TEXT,
  total_visto INTEGER DEFAULT 0,  -- quantos leads a conta tinha na ultima leitura
  offset_fim  INTEGER DEFAULT 0,  -- de onde retomar
  sincronizado INTEGER,
  leads       INTEGER DEFAULT 0
);
CREATE TABLE IF NOT EXISTS leads (
  conta TEXT,
  cnpj  TEXT,
  nome  TEXT,
  PRIMARY KEY (conta, cnpj, nome)
);
CREATE INDEX IF NOT EXISTS ix_lead_cnpj ON leads(conta, cnpj);
"""


def id_da_conta(token: str = "", grupo_id: str = "") -> str:
    """Identidade estavel da conta, sem guardar a credencial."""
    if token:
        return "t:" + hashlib.sha256(token.strip().encode()).hexdigest()[:16]
    return "grupo:" + (grupo_id or "__default__")


def _con():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    con = sqlite3.connect(DB, timeout=10)
    con.executescript(DDL)
    return con


def estado(conta: str) -> dict[str, Any]:
    try:
        con = _con()
        r = con.execute("SELECT total_visto, offset_fim, sincronizado, leads "
                        "FROM contas WHERE conta=?", (conta,)).fetchone()
        con.close()
    except Exception:
        return {"conhecida": False, "total_visto": 0, "offset": 0,
                "sincronizado": 0, "leads": 0}
    if not r:
        return {"conhecida": False, "total_visto": 0, "offset": 0,
                "sincronizado": 0, "leads": 0}
    return {"conhecida": True, "total_visto": r[0] or 0, "offset": r[1] or 0,
            "sincronizado": r[2] or 0, "leads": r[3] or 0}


def carregar(conta: str) -> dict[str, Any]:
    """Os CNPJs e nomes ja conhecidos desta conta."""
    cnpjs, nomes = set(), []
    try:
        con = _con()
        for c, n in con.execute("SELECT cnpj, nome FROM leads WHERE conta=?",
                                (conta,)):
            if c:
                cnpjs.add(c)
            if n:
                nomes.append(n)
        con.close()
    except Exception:
        pass
    return {"cnpjs": cnpjs, "nomes": nomes}


def guardar(conta: str, cnpjs, nomes, offset_fim: int, total_visto: int,
            zerar_antes: bool = False) -> None:
    try:
        con = _con()
        if zerar_antes:
            con.execute("DELETE FROM leads WHERE conta=?", (conta,))
        con.executemany(
            "INSERT OR IGNORE INTO leads (conta, cnpj, nome) VALUES (?,?,?)",
            [(conta, c, "") for c in (cnpjs or set())])
        con.executemany(
            "INSERT OR IGNORE INTO leads (conta, cnpj, nome) VALUES (?,?,?)",
            [(conta, "", n) for n in (nomes or [])])
        quantos = con.execute("SELECT count(*) FROM leads WHERE conta=?",
                              (conta,)).fetchone()[0]
        con.execute(
            """INSERT INTO contas (conta, total_visto, offset_fim, sincronizado, leads)
               VALUES (?,?,?,?,?)
               ON CONFLICT(conta) DO UPDATE SET
                 total_visto=excluded.total_visto, offset_fim=excluded.offset_fim,
                 sincronizado=excluded.sincronizado, leads=excluded.leads""",
            (conta, int(total_visto), int(offset_fim), int(time.time()), quantos))
        con.commit()
        con.close()
    except Exception:
        pass


def esquecer(conta: str) -> None:
    try:
        con = _con()
        con.execute("DELETE FROM leads WHERE conta=?", (conta,))
        con.execute("DELETE FROM contas WHERE conta=?", (conta,))
        con.commit()
        con.close()
    except Exception:
        pass
