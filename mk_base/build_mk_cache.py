"""Cache/DB local da Mk (WorkAPI) — preenchido consultando CPF a CPF, concorrente.

A Mk é por-consulta (sem bulk), mas o plano é ilimitado — então dá pra pré-popular
um cache. Este script puxa N CPFs (do JBR ou de uma lista) com concorrência,
grava em mk.db e é idempotente (pula CPF já coletado).

Uso:
  python build_mk_cache.py --n 4000 --conc 12
  python build_mk_cache.py --cpfs 111,222,333
"""
import argparse
import asyncio
import json
import os
import sqlite3
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
BACKEND = os.path.join(ROOT, "lupa-empresas", "backend")
JBR = os.path.join(ROOT, "jbr_base")
sys.path.insert(0, BACKEND)
sys.path.insert(0, JBR)

from dotenv import load_dotenv
load_dotenv(os.path.join(ROOT, "lupa-empresas", ".env"))

import mkbuscas
try:
    import cpf_lookup
except Exception:
    cpf_lookup = None

DB = os.path.join(HERE, "mk.db")

SCHEMA = """
CREATE TABLE IF NOT EXISTS pessoas_mk (
  cpf TEXT PRIMARY KEY, nome TEXT, nascimento TEXT, sexo TEXT,
  status TEXT, n_tel INTEGER, n_end INTEGER, n_email INTEGER,
  suspeito INTEGER, raw_json TEXT, coletado_em REAL
);
CREATE TABLE IF NOT EXISTS telefones_mk (
  cpf TEXT, ddd TEXT, numero TEXT, tipo TEXT, operadora TEXT, whatsapp TEXT
);
CREATE TABLE IF NOT EXISTS enderecos_mk (
  cpf TEXT, cidade TEXT, uf TEXT, bairro TEXT, logradouro TEXT, cep TEXT
);
CREATE TABLE IF NOT EXISTS emails_mk (cpf TEXT, email TEXT);
CREATE INDEX IF NOT EXISTS ix_tel_cpf ON telefones_mk(cpf);
"""

# registros com volume absurdo são lixo/sentinela (ex.: CPF 000...353 => 884 tels)
SUSPEITO_TEL = 40


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def pick_cpfs_jbr(n):
    if not cpf_lookup:
        return []
    with cpf_lookup._conn() as con:
        rows = con.execute(
            "SELECT cpf FROM pessoas WHERE length(cpf)=11 AND cpf NOT LIKE '0000%' LIMIT ?",
            (n,),
        ).fetchall()
    return [r["cpf"] for r in rows]


def existing(con):
    # NÃO pula CPFs com status 'error' (erro de throttling é transitório) — só os
    # já resolvidos (ok) ou genuinamente sem dado (not_found/empty).
    return {r[0] for r in con.execute(
        "SELECT cpf FROM pessoas_mk WHERE status NOT IN ('error','')").fetchall()}


async def fetch_one(cpf, sem, retries=2):
    async with sem:
        for attempt in range(retries + 1):
            try:
                r = await mkbuscas.consulta_cpf(cpf)
                if r.get("status") == "ok":
                    return cpf, r.get("data") or {}, "ok"
                if attempt == retries:
                    return cpf, None, r.get("status") or "error"
            except Exception:
                if attempt == retries:
                    return cpf, None, "error"
            await asyncio.sleep(0.5 * (attempt + 1))
    return cpf, None, "error"


def store(con, cpf, data, status):
    if data is None:
        con.execute(
            "INSERT OR REPLACE INTO pessoas_mk(cpf,status,coletado_em) VALUES (?,?,?)",
            (cpf, status, time.time()))
        return status, 0
    db_ = data.get("DadosBasicos") or {}
    nome = data.get("nome") or db_.get("nome") or db_.get("nomeCompleto") or ""
    nasc = db_.get("dataNascimento") or data.get("nascimento") or ""
    sexo = db_.get("sexo") or ""
    tels = mkbuscas._extract_phones(data)
    ends = [e for e in (data.get("enderecos") or []) if isinstance(e, dict)]
    mails = data.get("emails") or []
    suspeito = 1 if len(tels) > SUSPEITO_TEL else 0

    con.execute("INSERT OR REPLACE INTO pessoas_mk VALUES (?,?,?,?,?,?,?,?,?,?,?)",
                (cpf, nome, nasc, sexo, "ok", len(tels), len(ends), len(mails),
                 suspeito, json.dumps(data, ensure_ascii=False)[:300000], time.time()))
    for tb in ("telefones_mk", "enderecos_mk", "emails_mk"):
        con.execute(f"DELETE FROM {tb} WHERE cpf=?", (cpf,))
    # não explode o cache com lixo: se suspeito, guarda só os 40 primeiros
    tsave = tels[:SUSPEITO_TEL] if suspeito else tels
    con.executemany("INSERT INTO telefones_mk VALUES (?,?,?,?,?,?)",
                    [(cpf, t.get("ddd", ""), t.get("number") or t.get("telefone", ""),
                      t.get("tipo", ""), t.get("operadora", ""), str(t.get("whatsapp"))) for t in tsave])
    con.executemany("INSERT INTO enderecos_mk VALUES (?,?,?,?,?,?)",
                    [(cpf, e.get("cidade", ""), e.get("uf", ""), e.get("bairro", ""),
                      e.get("logradouro", ""), e.get("cep", "")) for e in (ends[:SUSPEITO_TEL] if suspeito else ends)])
    con.executemany("INSERT INTO emails_mk VALUES (?,?)",
                    [(cpf, (e.get("email") if isinstance(e, dict) else str(e))) for e in mails[:SUSPEITO_TEL]])
    return "ok", len(tels)


async def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=4000)
    ap.add_argument("--conc", type=int, default=8)  # WorkAPI estrangula acima disso
    ap.add_argument("--cpfs", default="")
    args = ap.parse_args()

    if not mkbuscas.enabled():
        log("Mk NÃO habilitada (WORKAPI_KEY ausente). Abortando.")
        return
    con = sqlite3.connect(DB)
    con.executescript(SCHEMA)

    if args.cpfs:
        cpfs = [c.strip() for c in args.cpfs.split(",") if c.strip()]
    else:
        cpfs = pick_cpfs_jbr(args.n + 500)
    done = existing(con)
    cpfs = [c for c in cpfs if c not in done][: args.n]
    log(f"CPFs a coletar: {len(cpfs)} (conc={args.conc}); já em cache: {len(done)}")
    if not cpfs:
        log("nada a fazer.")
        return

    sem = asyncio.Semaphore(args.conc)
    t0 = time.time()
    ok = empty = err = susp = 0
    tasks = [asyncio.create_task(fetch_one(c, sem)) for c in cpfs]
    for i, fut in enumerate(asyncio.as_completed(tasks), 1):
        cpf, data, status = await fut
        st, ntel = store(con, cpf, data, status)
        if st == "ok":
            ok += 1
            if data and len(mkbuscas._extract_phones(data)) > SUSPEITO_TEL:
                susp += 1
        elif status in ("not_found", "empty"):
            empty += 1
        else:
            err += 1
        if i % 100 == 0:
            con.commit()
            rate = i / (time.time() - t0)
            eta = int((len(cpfs) - i) / rate) if rate else 0
            log(f"  {i}/{len(cpfs)} | ok={ok} vazio/erro={empty+err} susp={susp} | {rate:.1f}/s ETA {eta}s")
    con.commit()

    dt = time.time() - t0
    log(f"FIM: {len(cpfs)} em {int(dt)}s ({len(cpfs)/dt:.1f}/s) | ok={ok} empty={empty} err={err} suspeitos={susp}")
    for tb in ("pessoas_mk", "telefones_mk", "enderecos_mk", "emails_mk"):
        n = con.execute(f"SELECT COUNT(*) FROM {tb}").fetchone()[0]
        log(f"  {tb}: {n:,}")
    log(f"  arquivo mk.db: {os.path.getsize(DB)/1e6:.1f} MB")
    con.close()


if __name__ == "__main__":
    asyncio.run(main())
