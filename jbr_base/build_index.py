"""Cria os indices da base ja carregada, ordenando em DISCO (nao na RAM).

A carga inteira (223M linhas) ja esta no jbr_pf.db; so faltam os indices.
Rodar uma vez:  python build_index.py
"""

import os
import sqlite3
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jbr_pf.db")


def main():
    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    # Ordenacao do indice vai para disco (evita estouro de RAM em 223M linhas).
    cur.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = FILE;
        PRAGMA cache_size = -1048576;  -- ~1GB de cache de pagina
        """
    )
    for name, ddl in [
        ("idx_nome", "CREATE INDEX IF NOT EXISTS idx_nome ON pessoas(nome_norm)"),
        ("idx_cpf", "CREATE INDEX IF NOT EXISTS idx_cpf ON pessoas(cpf)"),
    ]:
        t = time.time()
        print(f"Criando {name}...", flush=True)
        cur.execute(ddl)
        con.commit()
        print(f"  {name} pronto em {time.time()-t:.0f}s", flush=True)

    idx = cur.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    ).fetchall()
    print("Indices:", [i[0] for i in idx], flush=True)
    con.close()
    print("CONCLUIDO", flush=True)


if __name__ == "__main__":
    main()
