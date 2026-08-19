"""Ingestão dos Dados Abertos de CNPJ da Receita Federal para SQLite local.

Baixa do mirror (CDN Cloudflare da Casa dos Dados), descompacta e faz streaming
dos CSVs (cp1252, separador ';') para tabelas SQLite, em lotes. Idempotente:
registra cada arquivo já ingerido e pula em re-execuções.

Uso:
  python ingest_cnpj.py --slice     # tabelas de apoio + 1 parte de cada (valida)
  python ingest_cnpj.py --full      # base completa (Empresas/Estab/Socios/Simples)
  python ingest_cnpj.py --data 2026-06-14   # escolhe o mês (default: mais recente conhecido)
  python ingest_cnpj.py --keep-zip  # não apaga os .zip após ingerir

Layouts (RFB): CSV sem cabeçalho, ';' , aspas '"', encoding cp1252/latin-1.
"""

import argparse
import csv
import io
import os
import sqlite3
import sys
import time
import urllib.request
import zipfile

HERE = os.path.dirname(os.path.abspath(__file__))
# Bases ficam fora do OneDrive (C:\capiblu_data). Sobrescreva com CNPJ_DB_DIR.
DATA_DIR = os.environ.get("CNPJ_DB_DIR") or (r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else HERE)
DB_PATH = os.path.join(DATA_DIR, "cnpj.db")
DL_DIR = os.path.join(HERE, "_downloads")

MIRROR = "https://dados-abertos-rf-cnpj.casadosdados.com.br/arquivos"
DEFAULT_DATA = "2026-06-14"

BATCH = 50_000
csv.field_size_limit(10_000_000)

# ---------------------------------------------------------------- schema
SCHEMA = """
CREATE TABLE IF NOT EXISTS empresas (
  cnpj_basico TEXT, razao_social TEXT, natureza TEXT,
  capital_social REAL, porte TEXT
);
CREATE TABLE IF NOT EXISTS estabelecimentos (
  cnpj_basico TEXT, cnpj TEXT, matriz_filial TEXT, nome_fantasia TEXT,
  situacao TEXT, data_inicio TEXT, cnae_principal TEXT, cnae_secundaria TEXT,
  logradouro TEXT, numero TEXT, complemento TEXT, bairro TEXT, cep TEXT,
  uf TEXT, municipio TEXT, ddd1 TEXT, tel1 TEXT, ddd2 TEXT, tel2 TEXT, email TEXT
);
CREATE TABLE IF NOT EXISTS socios (
  cnpj_basico TEXT, identificador TEXT, nome_socio TEXT, cpf_cnpj_socio TEXT,
  qualificacao TEXT, data_entrada TEXT, faixa_etaria TEXT
);
CREATE TABLE IF NOT EXISTS simples (
  cnpj_basico TEXT, opcao_simples TEXT, opcao_mei TEXT
);
CREATE TABLE IF NOT EXISTS lookup (
  tipo TEXT, codigo TEXT, descricao TEXT
);
CREATE TABLE IF NOT EXISTS _ingested (arquivo TEXT PRIMARY KEY, linhas INTEGER, ts REAL);
"""

# tabela -> (n_partes, prefixo). Apoio tem 1 parte só.
BIG = {
    "empresas": ("Empresas", "empresas", None),
    "estabelecimentos": ("Estabelecimentos", "estabelecimentos", None),
    "socios": ("Socios", "socios", None),
}
LOOKUPS = {
    "Cnaes": "cnae", "Naturezas": "natureza", "Municipios": "municipio",
    "Paises": "pais", "Qualificacoes": "qualificacao", "Motivos": "motivo",
}


def _row_empresas(r):
    cap = (r[4] or "0").replace(".", "").replace(",", ".")
    try:
        cap = float(cap)
    except ValueError:
        cap = 0.0
    return (r[0], r[1], r[2], cap, r[5])


def _row_estab(r):
    # concatena CNPJ completo (basico+ordem+dv)
    cnpj = (r[0] or "") + (r[1] or "") + (r[2] or "")
    return (r[0], cnpj, r[3], r[4], r[5], r[10], r[11], r[12],
            r[14], r[15], r[16], r[17], r[18], r[19], r[20],
            r[21], r[22], r[23], r[24], r[27])


def _row_socios(r):
    return (r[0], r[1], r[2], r[3], r[4], r[5], r[10])


def _row_simples(r):
    return (r[0], r[1], r[4])


INSERTS = {
    "empresas": ("INSERT INTO empresas VALUES (?,?,?,?,?)", _row_empresas, 7),
    "estabelecimentos": ("INSERT INTO estabelecimentos VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", _row_estab, 30),
    "socios": ("INSERT INTO socios VALUES (?,?,?,?,?,?,?)", _row_socios, 11),
    "simples": ("INSERT INTO simples VALUES (?,?,?)", _row_simples, 7),
}


def log(msg):
    print(f"[{time.strftime('%H:%M:%S')}] {msg}", flush=True)


def download(data, fname):
    os.makedirs(DL_DIR, exist_ok=True)
    dest = os.path.join(DL_DIR, fname)
    if os.path.exists(dest) and os.path.getsize(dest) > 1000:
        return dest
    url = f"{MIRROR}/{data}/{fname}"
    tmp = dest + ".part"
    log(f"baixando {fname} …")
    req = urllib.request.Request(url, headers={
        "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                       "(KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"),
        "Accept": "*/*",
    })
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
        total = int(resp.headers.get("Content-Length") or 0)
        got = 0
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            got += len(chunk)
            if total:
                pct = got * 100 // total
                if pct % 10 == 0:
                    print(f"\r  {fname}: {pct}% ({got>>20}/{total>>20} MB)", end="", flush=True)
    print()
    os.replace(tmp, dest)
    return dest


def _open_csv_member(zip_path):
    zf = zipfile.ZipFile(zip_path)
    member = zf.namelist()[0]
    raw = zf.open(member)
    text = io.TextIOWrapper(raw, encoding="latin-1", newline="")
    return zf, csv.reader(text, delimiter=";", quotechar='"')


def ingest_big(con, table, zip_path, fname):
    sql, mapper, ncols = INSERTS[table]
    cur = con.cursor()
    zf, reader = _open_csv_member(zip_path)
    batch, n = [], 0
    for r in reader:
        if len(r) < ncols:
            continue
        try:
            batch.append(mapper(r))
        except Exception:
            continue
        if len(batch) >= BATCH:
            cur.executemany(sql, batch)
            n += len(batch)
            batch.clear()
    if batch:
        cur.executemany(sql, batch)
        n += len(batch)
    zf.close()
    con.execute("INSERT OR REPLACE INTO _ingested VALUES (?,?,?)", (fname, n, time.time()))
    con.commit()
    log(f"  {fname}: {n:,} linhas")
    return n


def ingest_lookup(con, tipo, zip_path, fname):
    cur = con.cursor()
    cur.execute("DELETE FROM lookup WHERE tipo=?", (tipo,))
    zf, reader = _open_csv_member(zip_path)
    rows = [(tipo, r[0], r[1]) for r in reader if len(r) >= 2]
    cur.executemany("INSERT INTO lookup VALUES (?,?,?)", rows)
    zf.close()
    con.execute("INSERT OR REPLACE INTO _ingested VALUES (?,?,?)", (fname, len(rows), time.time()))
    con.commit()
    log(f"  {fname}: {len(rows)} códigos ({tipo})")


def already(con, fname):
    return con.execute("SELECT 1 FROM _ingested WHERE arquivo=?", (fname,)).fetchone() is not None


def drop_indexes(con):
    names = ["ix_emp_cnpj", "ix_soc_cnpj", "ix_sim_cnpj", "ix_est_cnpj",
             "ix_est_cnae", "ix_est_cnae_uf", "ix_est_uf_mun", "ix_est_sit"]
    for n in names:
        con.execute(f"DROP INDEX IF EXISTS {n}")
    con.commit()


def build_indexes(con):
    log("criando índices (pode demorar)…")
    idx = [
        "CREATE INDEX IF NOT EXISTS ix_emp_cnpj ON empresas(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS ix_soc_cnpj ON socios(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS ix_sim_cnpj ON simples(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS ix_est_cnpj ON estabelecimentos(cnpj_basico)",
        "CREATE INDEX IF NOT EXISTS ix_est_cnae ON estabelecimentos(cnae_principal)",
        "CREATE INDEX IF NOT EXISTS ix_est_cnae_uf ON estabelecimentos(cnae_principal, uf)",
        "CREATE INDEX IF NOT EXISTS ix_est_uf_mun ON estabelecimentos(uf, municipio)",
        "CREATE INDEX IF NOT EXISTS ix_est_sit ON estabelecimentos(situacao)",
    ]
    for s in idx:
        log("  " + s.split("ON ")[1])
        con.execute(s)
    con.commit()
    # ANALYZE: sem estatísticas o planejador escolhe o índice errado (varria SP
    # inteiro em vez do CNAE seletivo — 92s vs 3s).
    log("  ANALYZE (estatísticas do planejador)…")
    con.execute("ANALYZE")
    con.commit()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--slice", action="store_true", help="apoio + 1 parte de cada (valida)")
    ap.add_argument("--full", action="store_true", help="base completa")
    ap.add_argument("--data", default=DEFAULT_DATA)
    ap.add_argument("--keep-zip", action="store_true")
    ap.add_argument("--no-index", action="store_true", help="não criar índices ao final")
    args = ap.parse_args()
    if not (args.slice or args.full):
        ap.error("use --slice ou --full")

    con = sqlite3.connect(DB_PATH)
    con.executescript(SCHEMA)
    # WAL + synchronous=NORMAL: à prova de kill. Cada arquivo é commitado; se o
    # processo morrer no meio, perde-se só o arquivo em andamento (idempotente
    # refaz), SEM corromper o banco. (journal_mode=OFF corrompeu no crash anterior.)
    con.execute("PRAGMA journal_mode=WAL")
    con.execute("PRAGMA synchronous=NORMAL")
    con.execute("PRAGMA wal_autocheckpoint=20000")
    con.execute("PRAGMA temp_store=MEMORY")
    con.execute("PRAGMA cache_size=-200000")  # ~200MB

    parts = [1] if args.slice else list(range(10))
    include_simples = args.full
    t0 = time.time()

    # No full, dropar índices existentes (da fatia) antes do bulk load — inserir
    # 190M linhas com índice é MUITO mais lento. Recria tudo no final.
    if args.full and not args.no_index:
        log("dropando índices antes do bulk load full…")
        drop_indexes(con)

    # apoio (sempre)
    for fzip, tipo in LOOKUPS.items():
        fname = fzip + ".zip"
        if already(con, fname):
            log(f"pulando {fname} (já ingerido)")
            continue
        zp = download(args.data, fname)
        ingest_lookup(con, tipo, zp, fname)
        if not args.keep_zip:
            os.remove(zp)

    # tabelas grandes
    for table, (prefix, _t, _x) in BIG.items():
        for i in parts:
            fname = f"{prefix}{i}.zip"
            if already(con, fname):
                log(f"pulando {fname} (já ingerido)")
                continue
            zp = download(args.data, fname)
            ingest_big(con, table, zp, fname)
            if not args.keep_zip:
                os.remove(zp)

    # simples/mei (arquivo único; só no full)
    if include_simples:
        fname = "Simples.zip"
        if already(con, fname):
            log(f"pulando {fname} (já ingerido)")
        else:
            zp = download(args.data, fname)
            ingest_big(con, "simples", zp, fname)
            if not args.keep_zip:
                os.remove(zp)

    if not args.no_index:
        build_indexes(con)

    for t in ("empresas", "estabelecimentos", "socios", "simples"):
        n = con.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
        log(f"total {t}: {n:,}")
    con.close()
    log(f"concluído em {int(time.time()-t0)}s. DB: {DB_PATH}")


if __name__ == "__main__":
    main()
