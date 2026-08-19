"""Ingestao da base JBR_PF (CPF|Nome|Sexo|Nascimento) num SQLite indexado.

Le o .7z por streaming (sem extrair os 14GB em disco), normaliza e insere em
lotes. Indices sao criados DEPOIS da carga (muito mais rapido).

Uso:
    python ingest.py                      # carga completa
    python ingest.py --limit 200000       # teste com amostra
    python ingest.py --reset              # recria a tabela do zero

Requer 7-Zip instalado (C:\\Program Files\\7-Zip\\7z.exe).
"""

import argparse
import os
import sqlite3
import subprocess
import sys
import time
import unicodedata

ARCHIVE = r"C:\Users\rebec\OneDrive\Documentos\JBR_CPF.7z"
SEVENZIP = r"C:\Program Files\7-Zip\7z.exe"
DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jbr_pf.db")
BATCH = 50_000


def norm_name(s: str) -> str:
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode("ascii")
    return " ".join(s.upper().split())


def only_digits(s: str) -> str:
    return "".join(ch for ch in s if ch.isdigit())


def stream_lines():
    """Gera linhas de texto lendo o .7z por streaming em blocos grandes.

    Le blocos binarios (8MB), divide por '\\n' e guarda o resto parcial para o
    proximo bloco (evita quebrar caractere multibyte). Muito mais rapido que
    readline linha-a-linha.
    """
    proc = subprocess.Popen(
        [SEVENZIP, "e", "-so", ARCHIVE],
        stdout=subprocess.PIPE,
        stderr=subprocess.DEVNULL,
        bufsize=8 * 1024 * 1024,
    )
    remainder = b""
    read = proc.stdout.read
    while True:
        chunk = read(8 * 1024 * 1024)
        if not chunk:
            break
        data = remainder + chunk
        lines = data.split(b"\n")
        remainder = lines.pop()  # ultima parte pode estar incompleta
        for raw in lines:
            try:
                yield raw.decode("utf-8")
            except UnicodeDecodeError:
                yield raw.decode("latin-1")
    if remainder:
        try:
            yield remainder.decode("utf-8")
        except UnicodeDecodeError:
            yield remainder.decode("latin-1")
    proc.stdout.close()
    proc.wait()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--reset", action="store_true")
    args = ap.parse_args()

    if args.reset and os.path.exists(DB_PATH):
        os.remove(DB_PATH)

    con = sqlite3.connect(DB_PATH)
    cur = con.cursor()
    cur.executescript(
        """
        PRAGMA journal_mode = OFF;
        PRAGMA synchronous = OFF;
        PRAGMA temp_store = FILE;  -- ordenacao de indice em disco (evita OOM)
        PRAGMA cache_size = -400000;  -- ~400MB
        CREATE TABLE IF NOT EXISTS pessoas (
            cpf TEXT,
            nome TEXT,
            nome_norm TEXT,
            sexo TEXT,
            nascimento TEXT
        );
        """
    )
    con.commit()

    t0 = time.time()
    n = 0
    batch = []
    first = True
    for line in stream_lines():
        if first:  # pula header
            first = False
            if line.upper().startswith("CPF"):
                continue
        line = line.rstrip("\n").rstrip("\r")
        if not line:
            continue
        parts = line.split("|")
        if len(parts) < 4:
            continue
        cpf = only_digits(parts[0]).zfill(11)[:11]
        nome = parts[1].strip()
        sexo = parts[2].strip()[:1]  # M / F
        nasc = parts[3].strip()
        batch.append((cpf, nome, norm_name(nome), sexo, nasc))
        if len(batch) >= BATCH:
            cur.executemany("INSERT INTO pessoas VALUES (?,?,?,?,?)", batch)
            con.commit()
            n += len(batch)
            batch.clear()
            if n % 1_000_000 == 0:
                rate = n / (time.time() - t0)
                print(f"  {n:,} linhas | {rate:,.0f}/s", flush=True)
        if args.limit and n >= args.limit:
            break

    if batch:
        cur.executemany("INSERT INTO pessoas VALUES (?,?,?,?,?)", batch)
        con.commit()
        n += len(batch)

    dt = time.time() - t0
    print(f"Carga: {n:,} linhas em {dt:.0f}s", flush=True)

    print("Criando indices (pode demorar)...", flush=True)
    ti = time.time()
    cur.execute("CREATE INDEX IF NOT EXISTS idx_nome ON pessoas(nome_norm)")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_cpf ON pessoas(cpf)")
    con.commit()
    print(f"Indices em {time.time()-ti:.0f}s", flush=True)

    cur.execute("SELECT COUNT(*) FROM pessoas")
    print("Total na base:", f"{cur.fetchone()[0]:,}", flush=True)
    con.close()


if __name__ == "__main__":
    main()
