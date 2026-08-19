"""Monitor de progresso da ingestao da base JBR_PF.

Mostra o andamento no formato de tabela e atualiza a cada poucos segundos,
estimando % e ETA pelo crescimento do arquivo .db.

Uso:
    python progress.py           # atualiza ao vivo (Ctrl+C para sair)
    python progress.py --once    # mostra uma vez e sai
"""

import argparse
import os
import time

DB_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "jbr_pf.db")

# Alvos estimados: ~230M linhas / ~19GB no fim da carga (antes dos indices).
TARGET_BYTES = 19.0 * 1024**3
TARGET_ROWS = 230_000_000
BYTES_PER_ROW = 83.0


def _fmt_gb(b: float) -> str:
    return f"{b / 1024**3:.2f} GB"


def _ready() -> bool:
    try:
        import sqlite3

        con = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True, timeout=2)
        r = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='index' AND name='idx_nome'"
        ).fetchone()
        con.close()
        return r is not None
    except Exception:
        return False


def snapshot():
    if not os.path.exists(DB_PATH):
        return None
    size = os.path.getsize(DB_PATH)
    rows = int(size / BYTES_PER_ROW)
    pct = min(99, size / TARGET_BYTES * 100)
    return size, rows, pct


def render(prev=None):
    snap = snapshot()
    if snap is None:
        print("Banco ainda nao criado. Aguardando inicio da ingestao...")
        return None

    size, rows, pct = snap
    ready = _ready()

    eta = ""
    if prev and not ready:
        dsize = size - prev[0]
        dt = time.time() - prev[3]
        if dsize > 0 and dt > 0:
            rate = dsize / dt  # bytes/s
            remaining = max(0, TARGET_BYTES - size)
            secs = remaining / rate
            eta = f"  |  ETA ~{int(secs // 60)} min"

    os.system("cls" if os.name == "nt" else "clear")
    print("=" * 58)
    print("  INGESTAO JBR_PF - progresso")
    print("=" * 58)
    print(f"{'Tamanho do DB':<22}{'Progresso aprox.'}")
    print(f"{'-'*20}  {'-'*22}")
    marker = f"{_fmt_gb(size)} (agora)"
    if ready:
        print(f"{marker:<22}CARGA + INDICES PRONTOS [OK]")
    else:
        print(f"{marker:<22}~{rows // 1_000_000}M / ~{pct:.0f}%{eta}")
    print(f"{'~8 GB':<22}~50%")
    print(f"{'~19 GB':<22}carga completa -> indexando")
    print("=" * 58)
    if ready:
        print("STATUS: PRONTA para consulta (indices criados).")
    else:
        print("STATUS: carregando/indexando... (Ctrl+C para sair do monitor)")
    return (size, rows, pct, time.time())


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--once", action="store_true")
    ap.add_argument("--interval", type=int, default=5)
    args = ap.parse_args()

    prev = None
    while True:
        prev = render(prev)
        if args.once or (prev and _ready()):
            break
        time.sleep(args.interval)


if __name__ == "__main__":
    main()
