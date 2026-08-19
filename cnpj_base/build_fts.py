"""FTS5 por ESTABELECIMENTO com localização — busca de texto+município sub-segundo.

Índice full-text com colunas filtráveis (uf, municipio, situacao, cnae) além de
razão/fantasia. Assim o próprio FTS filtra `construtora + municipio:4123 + uf:mg`
sem ler linha nenhuma da base — rápido até com cache frio.

Arquivo SEPARADO (cnpj_fts.db), build em .building → rename ao concluir, então o
backend nunca abre um índice pela metade e o cnpj.db (28 GB) não é tocado.

Uso: python build_fts.py
"""
import os
import sqlite3
import time

HERE = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.environ.get("CNPJ_DB_DIR") or (r"C:\capiblu_data" if os.path.isdir(r"C:\capiblu_data") else HERE)
MAIN = os.path.join(DATA_DIR, "cnpj.db")
FTS = os.path.join(DATA_DIR, "cnpj_fts.db")
TMP = FTS + ".building"


def log(m):
    print(f"[{time.strftime('%H:%M:%S')}] {m}", flush=True)


def main():
    if not os.path.exists(MAIN):
        log("cnpj.db não existe."); return
    for p in (TMP, TMP + "-journal", TMP + "-wal", TMP + "-shm"):
        if os.path.exists(p):
            os.remove(p)

    con = sqlite3.connect(TMP, uri=False)
    con.execute("PRAGMA journal_mode=OFF")   # descartável: se morrer, refaço
    con.execute("PRAGMA synchronous=OFF")
    con.execute("PRAGMA cache_size=-400000")  # ~400MB
    con.execute("ATTACH DATABASE ? AS src", (MAIN,))
    # Colunas de filtro (uf/municipio/situacao/cnae) indexadas junto do texto.
    con.execute("CREATE VIRTUAL TABLE estab_fts USING fts5("
                "cnpj UNINDEXED, razao, fantasia, uf, municipio, situacao, cnae, "
                "tokenize='unicode61 remove_diacritics 2')")

    t0 = time.time()
    total = con.execute("SELECT COUNT(*) FROM src.estabelecimentos").fetchone()[0]
    log(f"indexando {total:,} estabelecimentos (razão+fantasia+uf+município+situação+cnae)…")
    con.execute(
        "INSERT INTO estab_fts(cnpj, razao, fantasia, uf, municipio, situacao, cnae) "
        "SELECT e.cnpj, emp.razao_social, e.nome_fantasia, e.uf, e.municipio, "
        "       e.situacao, e.cnae_principal "
        "FROM src.estabelecimentos e "
        "JOIN src.empresas emp ON emp.cnpj_basico = e.cnpj_basico")
    con.commit()
    n = con.execute("SELECT COUNT(*) FROM estab_fts").fetchone()[0]
    log("otimizando índice FTS…")
    con.execute("INSERT INTO estab_fts(estab_fts) VALUES('optimize')")
    con.commit()
    con.execute("DETACH DATABASE src")
    con.close()

    os.replace(TMP, FTS)
    log(f"FTS pronto: {n:,} linhas em {int(time.time()-t0)}s. Arquivo: {FTS} "
        f"({os.path.getsize(FTS)/1e9:.1f} GB)")


if __name__ == "__main__":
    main()
