# -*- coding: utf-8 -*-
"""Materializa a base de empresas do LinkedIn no disco, com o CNPJ ja resolvido.

POR QUE EXISTE
--------------
A Datastone parece instantanea porque a base dela JA ESTA UNIDA no disco
deles. Nos pergunamos ao vivo, e por isso cada filtro custa dinheiro e alguns
segundos -- o que obriga a tela a avisar de custo o tempo todo e transforma
navegar em decidir gastar.

A diferenca nao e de tecnologia, e de MOMENTO: eles pagaram uma vez, na
ingestao; nos pagavamos toda vez, na consulta. Este arquivo move o pagamento
para o mesmo lugar que o deles.

A CONTA (medida em 8/set/2026, US$ 0,0025 por registro entregue)
    mais de 500 funcionarios ....  6.824 empresas .... US$  17  (~R$ 102)
    mais de 200 ................. 18.021 ............ US$  45  (~R$ 270)
    mais de 50 .................. 69.096 ............ US$ 173  (~R$ 1.036)
    mais de 10 ................. 288.051 ............ US$ 720  (~R$ 4.320)

Depois de ingerida, a fatia comprada nunca mais custa nada: filtrar por porte,
tipo, setor e fundacao vira consulta local, e a tela para de perguntar se pode
gastar. A parte de fora da fatia continua acessivel pela API, sob demanda.

CUIDADOS QUE ESTE SCRIPT TOMA
  - TETO DE GASTO em dolares, conferido a cada pagina. Sem isso um `>10`
    digitado sem pensar viraria US$ 720 sem aviso.
  - RETOMAVEL: guarda o cursor. Queda de rede no meio de 18 mil registros nao
    joga fora o que ja foi pago.
  - NAO RECOMPRA: registro que ja esta no banco e atualizado, nao duplicado.

Uso:
    python build_empresas_li.py --min 200 --teto-usd 50
    python build_empresas_li.py --min 200 --teto-usd 50 --continuar
    python build_empresas_li.py --status
"""
import argparse
import json
import os
import sqlite3
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv("/opt/capiblu/lupa-empresas/.env")
sys.path.insert(0, "/opt/capiblu/lupa-empresas/backend")

DATA = os.environ.get("CNPJ_DB_DIR", "/capiblu_data")
DESTINO = os.path.join(DATA, "empresas_li.db")
DATASET = "gd_l1vikfnt1wgvvqz95w"
URL = "https://api.brightdata.com/datasets/search/" + DATASET
USD_POR_REGISTRO = 0.0025
LOTE = 100                      # teto da API, medido

DDL = """
CREATE TABLE IF NOT EXISTS empresas_li (
  url            TEXT PRIMARY KEY,
  company_id     TEXT,
  nome           TEXT,
  site           TEXT,
  dominio        TEXT,
  funcionarios   INTEGER,
  setor          TEXT,
  tipo           TEXT,
  fundada        TEXT,
  seguidores     INTEGER,
  sede           TEXT,
  uf             TEXT,
  cnpj           TEXT,
  cnpj_confianca TEXT,
  cnpj_motivo    TEXT,
  visto_em       INTEGER
);
CREATE INDEX IF NOT EXISTS ix_li_cnpj  ON empresas_li(cnpj);
CREATE INDEX IF NOT EXISTS ix_li_func  ON empresas_li(funcionarios);
CREATE INDEX IF NOT EXISTS ix_li_tipo  ON empresas_li(tipo);
CREATE INDEX IF NOT EXISTS ix_li_uf    ON empresas_li(uf);
CREATE INDEX IF NOT EXISTS ix_li_dom   ON empresas_li(dominio);

-- Onde a ingestao parou. E o que faz uma queda de rede custar zero em vez de
-- custar tudo de novo.
CREATE TABLE IF NOT EXISTS progresso (
  chave     TEXT PRIMARY KEY,
  cursor    TEXT,
  trazidos  INTEGER,
  gasto_usd REAL,
  atualizado INTEGER
);
"""


def _con():
    con = sqlite3.connect(DESTINO)
    con.executescript(DDL)
    return con


def _headers():
    tok = (os.environ.get("BRIGHTDATA_TOKEN")
           or os.environ.get("BRIGHTDATA_API_KEY") or "")
    return {"Authorization": "Bearer " + tok, "Content-Type": "application/json"}


def _uf_da_sede(rec):
    try:
        import empresa_cnpj
        return empresa_cnpj.uf_do_registro(rec)
    except Exception:
        return ""


def _cnpj(rec):
    try:
        import empresa_cnpj
        p = empresa_cnpj.resolver(registro=rec)
        return p["cnpj"], p["confianca"], p["motivo"]
    except Exception:
        return "", "nenhuma", ""


def status():
    if not os.path.exists(DESTINO):
        print("base ainda nao existe: %s" % DESTINO)
        return
    con = _con()
    n = con.execute("SELECT count(*) FROM empresas_li").fetchone()[0]
    com = con.execute("SELECT count(*) FROM empresas_li WHERE cnpj<>''").fetchone()[0]
    print("empresas na base .......... %d" % n)
    print("com CNPJ resolvido ........ %d (%.0f%%)" % (com, 100.0 * com / max(n, 1)))
    for k, cur, tr, g, ts in con.execute(
            "SELECT chave, cursor, trazidos, gasto_usd, atualizado FROM progresso"):
        print("  %-14s trazidos=%-7d gasto=US$%.2f  %s  %s"
              % (k, tr or 0, g or 0.0, "tem cursor" if cur else "terminou",
                 time.strftime("%d/%m %H:%M", time.localtime(ts or 0))))
    if n:
        print("\n  por faixa de funcionarios:")
        for lo, hi, rot in ((0, 50, "ate 50"), (50, 200, "51 a 200"),
                            (200, 1000, "201 a 1.000"), (1000, 10 ** 9, "mais de 1.000")):
            q = con.execute("SELECT count(*) FROM empresas_li WHERE funcionarios>? "
                            "AND funcionarios<=?", (lo, hi)).fetchone()[0]
            print("     %-16s %d" % (rot, q))
    con.close()


def ingerir(minimo: int, teto_usd: float, continuar: bool) -> None:
    chave = "func>%d" % minimo
    con = _con()
    linha = con.execute("SELECT cursor, trazidos, gasto_usd FROM progresso "
                        "WHERE chave=?", (chave,)).fetchone()
    cursor = (linha[0] if linha and continuar else None)
    trazidos = (linha[1] or 0) if (linha and continuar) else 0
    gasto = (linha[2] or 0.0) if (linha and continuar) else 0.0
    if cursor:
        cursor = json.loads(cursor)
        print("retomando de onde parou: %d ja trazidos, US$ %.2f ja gastos"
              % (trazidos, gasto))

    filtros = [{"name": "country_code", "operator": "=", "value": "BR"},
               {"name": "employees_in_linkedin", "operator": ">", "value": minimo}]
    t0 = time.time()
    novos = atualizados = 0

    while True:
        # O teto e conferido ANTES de pedir a proxima pagina, e nao depois:
        # depois ja teria sido cobrado.
        if gasto + LOTE * USD_POR_REGISTRO > teto_usd:
            print("\nTETO de US$ %.2f alcancado (gasto US$ %.2f). "
                  "Rode com --continuar para seguir." % (teto_usd, gasto))
            break
        corpo = {"size": LOTE, "filter": {"operator": "and", "filters": filtros},
                 "sort": [{"timestamp": "asc"}]}
        if cursor:
            corpo["search_after"] = cursor
        try:
            r = httpx.post(URL, headers=_headers(), json=corpo, timeout=180)
        except Exception as exc:
            print("\nrede caiu (%s). O cursor esta salvo -- rode com --continuar."
                  % str(exc)[:80])
            break
        if r.status_code >= 400:
            print("\nHTTP %s: %s" % (r.status_code, r.text[:160]))
            break
        d = json.loads(r.content)
        hits = d.get("hits") or []
        if not hits:
            print("\nacabou: a fatia inteira foi trazida.")
            cursor = None
            break

        gasto += len(hits) * USD_POR_REGISTRO
        trazidos += len(hits)
        for h in hits:
            url = (h.get("url") or "").strip()
            if not url:
                continue
            cnpj, conf, motivo = _cnpj(h)
            ja = con.execute("SELECT 1 FROM empresas_li WHERE url=?", (url,)).fetchone()
            con.execute("""
                INSERT INTO empresas_li (url,company_id,nome,site,dominio,
                    funcionarios,setor,tipo,fundada,seguidores,sede,uf,
                    cnpj,cnpj_confianca,cnpj_motivo,visto_em)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(url) DO UPDATE SET
                  nome=excluded.nome, funcionarios=excluded.funcionarios,
                  setor=excluded.setor, tipo=excluded.tipo,
                  seguidores=excluded.seguidores, visto_em=excluded.visto_em,
                  cnpj=CASE WHEN excluded.cnpj<>'' THEN excluded.cnpj
                            ELSE empresas_li.cnpj END
            """, (url, str(h.get("company_id") or ""), h.get("name") or "",
                  h.get("website_simplified") or h.get("website") or "",
                  (h.get("website_simplified") or "").lower(),
                  h.get("employees_in_linkedin"), h.get("industries") or "",
                  h.get("organization_type") or "", str(h.get("founded") or ""),
                  h.get("followers"), h.get("headquarters") or "",
                  _uf_da_sede(h), cnpj, conf, motivo, int(time.time())))
            if ja:
                atualizados += 1
            else:
                novos += 1

        cursor = d.get("search_after")
        con.execute("""INSERT INTO progresso (chave,cursor,trazidos,gasto_usd,atualizado)
                       VALUES (?,?,?,?,?)
                       ON CONFLICT(chave) DO UPDATE SET cursor=excluded.cursor,
                         trazidos=excluded.trazidos, gasto_usd=excluded.gasto_usd,
                         atualizado=excluded.atualizado""",
                    (chave, json.dumps(cursor) if cursor else None,
                     trazidos, gasto, int(time.time())))
        con.commit()

        total = d.get("total_hits")
        pct = (100.0 * trazidos / total) if total else 0
        print("\r  %d de %s (%.1f%%) · novos %d · US$ %.2f · %.0fs"
              % (trazidos, total, pct, novos, gasto, time.time() - t0), end="")
        sys.stdout.flush()
        if not cursor:
            print("\nacabou: nao ha mais paginas.")
            break

    con.execute("""INSERT INTO progresso (chave,cursor,trazidos,gasto_usd,atualizado)
                   VALUES (?,?,?,?,?)
                   ON CONFLICT(chave) DO UPDATE SET cursor=excluded.cursor,
                     trazidos=excluded.trazidos, gasto_usd=excluded.gasto_usd,
                     atualizado=excluded.atualizado""",
                (chave, json.dumps(cursor) if cursor else None,
                 trazidos, gasto, int(time.time())))
    con.commit()
    com = con.execute("SELECT count(*) FROM empresas_li WHERE cnpj<>''").fetchone()[0]
    n = con.execute("SELECT count(*) FROM empresas_li").fetchone()[0]
    print()
    print("  novos ............... %d" % novos)
    print("  atualizados ......... %d" % atualizados)
    print("  na base agora ....... %d" % n)
    print("  com CNPJ ............ %d (%.0f%%)" % (com, 100.0 * com / max(n, 1)))
    print("  gasto ............... US$ %.2f" % gasto)
    print("  tempo ............... %.0fs" % (time.time() - t0))
    con.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--min", type=int, default=500,
                    help="so empresas com MAIS que N funcionarios no LinkedIn")
    ap.add_argument("--teto-usd", type=float, default=5.0,
                    help="para de gastar ao chegar aqui")
    ap.add_argument("--continuar", action="store_true",
                    help="retoma do cursor salvo em vez de comecar do zero")
    ap.add_argument("--status", action="store_true")
    a = ap.parse_args()
    if a.status:
        status()
    else:
        ingerir(a.min, a.teto_usd, a.continuar)
