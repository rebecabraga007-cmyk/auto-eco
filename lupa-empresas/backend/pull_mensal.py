# -*- coding: utf-8 -*-
"""Puxa a cota mensal do dataset da Bright Data, só Brasil, e alimenta o cache.

O PROBLEMA QUE ESTE SCRIPT RESOLVE: a API de filtro **não tem paginação, offset
nem cursor** (confirmado na doc). Pedir `country_code=BR, records_limit=100000`
todo mês devolveria SEMPRE os mesmos 100 mil perfis — o acúmulo não aconteceria.

A saída é particionar por um campo NUMÉRICO, porque os operadores incluem
`>=`, `<` e `is_null`. Usamos `followers`: cada mês puxa uma faixa diferente e
disjunta, então não há sobreposição entre as puxadas.

As faixas são finas embaixo e grossas em cima porque a distribuição é torta —
medido no cache: 59% dos perfis brasileiros têm menos de 50 seguidores, e 26%
não têm o dado (por isso existe a faixa `is_null`).

SE UMA FAIXA VOLTAR CHEIA (= records_limit), ela foi truncada e sobrou gente
dentro dela: o script marca `truncada` no plano para alguém subdividir. Sem esse
aviso, a faixa pareceria concluída e a diferença sumiria em silêncio.

    python pull_mensal.py                 # roda a próxima faixa pendente
    python pull_mensal.py --plano         # só mostra o plano e sai
    python pull_mensal.py --faixa 3       # força uma faixa específica

Roda no servidor por systemd timer (todo dia 05). Ver deploy/pull-mensal.*
"""
import argparse
import csv
import io
import json
import os
import sys
import time

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CHAVE = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
DATASET = os.environ.get("BRIGHTDATA_PEOPLE_DATASET_ID", "gd_l1viktl72bvl7bjuj0")
FILTER_URL = "https://api.brightdata.com/datasets/filter"
SNAP_URL = "https://api.brightdata.com/datasets/snapshots"

DESTINO = os.environ.get("PULL_DIR", "/capiblu_data/pulls")
PLANO = os.path.join(DESTINO, "plano.json")
LIMITE = int(os.environ.get("PULL_LIMITE", "100000"))
# Filtro amplo demora MUITO: os testes com país inteiro passaram de 7 minutos e
# só ficaram prontos horas depois. Por isso a espera é longa e o intervalo largo.
ESPERA_MAX_S = int(os.environ.get("PULL_ESPERA_MAX", str(6 * 3600)))
INTERVALO_S = 60

# Faixas disjuntas de `followers`. Cobrem todo mundo: as numéricas mais a is_null.
FAIXAS = [
    {"id": 1,  "rotulo": "sem dado de seguidores", "tipo": "null"},
    {"id": 2,  "rotulo": "0 a 4 seguidores",       "min": 0,    "max": 5},
    {"id": 3,  "rotulo": "5 a 9",                  "min": 5,    "max": 10},
    {"id": 4,  "rotulo": "10 a 19",                "min": 10,   "max": 20},
    {"id": 5,  "rotulo": "20 a 34",                "min": 20,   "max": 35},
    {"id": 6,  "rotulo": "35 a 49",                "min": 35,   "max": 50},
    {"id": 7,  "rotulo": "50 a 79",                "min": 50,   "max": 80},
    {"id": 8,  "rotulo": "80 a 119",               "min": 80,   "max": 120},
    {"id": 9,  "rotulo": "120 a 199",              "min": 120,  "max": 200},
    {"id": 10, "rotulo": "200 a 349",              "min": 200,  "max": 350},
    {"id": 11, "rotulo": "350 a 599",              "min": 350,  "max": 600},
    {"id": 12, "rotulo": "600 a 999",              "min": 600,  "max": 1000},
    {"id": 13, "rotulo": "1.000 a 2.499",          "min": 1000, "max": 2500},
    {"id": 14, "rotulo": "2.500 a 9.999",          "min": 2500, "max": 10000},
    {"id": 15, "rotulo": "10.000 ou mais",         "min": 10000},
]


def log(msg):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), msg), flush=True)


def carregar_plano():
    if os.path.exists(PLANO):
        try:
            return json.load(io.open(PLANO, encoding="utf-8"))
        except Exception:
            log("plano.json ilegível — recomeçando do zero")
    return {"feitas": {}}


def salvar_plano(p):
    os.makedirs(DESTINO, exist_ok=True)
    io.open(PLANO, "w", encoding="utf-8").write(
        json.dumps(p, ensure_ascii=False, indent=2))


def condicoes(faixa):
    """Monta o filtro da faixa. Sempre com país — é o ponto do exercício."""
    fs = [{"name": "country_code", "operator": "=", "value": "BR"}]
    if faixa.get("tipo") == "null":
        fs.append({"name": "followers", "operator": "is_null"})
    else:
        if "min" in faixa:
            fs.append({"name": "followers", "operator": ">=", "value": faixa["min"]})
        if "max" in faixa:
            fs.append({"name": "followers", "operator": "<", "value": faixa["max"]})
    return {"operator": "and", "filters": fs}


def disparar(faixa, limite):
    corpo = {"dataset_id": DATASET, "records_limit": limite,
             "filter": condicoes(faixa)}
    h = {"Authorization": "Bearer " + CHAVE, "Content-Type": "application/json"}
    r = httpx.post(FILTER_URL + "?format=json", headers=h, json=corpo, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError("filter HTTP %s: %s" % (r.status_code, r.text[:200]))
    sid = r.json().get("snapshot_id")
    if not sid:
        raise RuntimeError("sem snapshot_id: %s" % r.text[:200])
    return sid


def esperar(sid):
    h = {"Authorization": "Bearer " + CHAVE}
    t0 = time.time()
    while time.time() - t0 < ESPERA_MAX_S:
        m = httpx.get("%s/%s" % (SNAP_URL, sid), headers=h, timeout=120)
        estado = ""
        if m.status_code < 400:
            try:
                d = m.json()
                estado = d.get("status", "")
                if estado == "ready":
                    log("pronto: %s registros, custo informado %s"
                        % (d.get("dataset_size"), d.get("cost")))
                    return d
                if estado in ("failed", "error"):
                    raise RuntimeError("snapshot falhou: %s" % json.dumps(d)[:200])
            except RuntimeError:
                raise
            except Exception:
                pass
        log("  ainda %s… (%.0f min)" % (estado or "processando", (time.time() - t0) / 60))
        time.sleep(INTERVALO_S)
    raise RuntimeError("passou de %.0f h esperando" % (ESPERA_MAX_S / 3600))


def baixar_csv(sid, caminho):
    """Baixa em CSV — é o formato pedido para guardar. O cache é semeado a partir
    dele mesmo, para não baixar duas vezes."""
    h = {"Authorization": "Bearer " + CHAVE}
    with httpx.stream("GET", "%s/%s/download?format=csv" % (SNAP_URL, sid),
                      headers=h, timeout=1800) as r:
        if r.status_code >= 400:
            raise RuntimeError("download HTTP %s" % r.status_code)
        os.makedirs(os.path.dirname(caminho), exist_ok=True)
        with io.open(caminho, "wb") as f:
            for pedaco in r.iter_bytes(1024 * 256):
                f.write(pedaco)
    return os.path.getsize(caminho)


def semear(caminho):
    """Carrega o CSV no cache. Dedupe é por URL, então repuxar não duplica."""
    import linkedin_cache
    linkedin_cache.init()
    lote, total, novos = [], 0, 0
    with io.open(caminho, encoding="utf-8", errors="replace", newline="") as f:
        for linha in csv.DictReader(f):
            url = (linha.get("url") or linha.get("input_url") or "").strip()
            if not url:
                continue
            generica = str(linha.get("default_avatar", "")).lower() in ("true", "1")
            lote.append({
                "url": url,
                "nome": linha.get("name") or "",
                "cargo": linha.get("position") or "",
                "empresa": linha.get("current_company_name") or "",
                "cidade": linha.get("city") or "",
                "pais": linha.get("country_code") or "",
                "foto": "" if generica else (linha.get("avatar") or ""),
                "formacao": linha.get("educations_details") or "",
                "sobre": (linha.get("about") or "")[:400],
                "seguidores": (int(linha["followers"])
                               if str(linha.get("followers", "")).isdigit() else None),
            })
            total += 1
            if len(lote) >= 2000:
                novos += linkedin_cache.salvar_perfis(lote, origem="snapshot")
                lote.clear()
    if lote:
        novos += linkedin_cache.salvar_perfis(lote, origem="snapshot")
    return total, novos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--plano", action="store_true", help="mostra o plano e sai")
    ap.add_argument("--faixa", type=int, default=0, help="força uma faixa pelo id")
    ap.add_argument("--limite", type=int, default=LIMITE)
    args = ap.parse_args()

    plano = carregar_plano()
    feitas = plano.get("feitas", {})

    if args.plano:
        print("faixa  situação      registros  rótulo")
        for f in FAIXAS:
            r = feitas.get(str(f["id"]))
            sit = "pendente"
            qtd = ""
            if r:
                sit = "TRUNCADA" if r.get("truncada") else "feita"
                qtd = str(r.get("registros", ""))
            print("  %-4s %-13s %-10s %s" % (f["id"], sit, qtd, f["rotulo"]))
        return

    if not CHAVE:
        log("BRIGHTDATA_API_KEY ausente"); raise SystemExit(1)

    if args.faixa:
        faixa = next((f for f in FAIXAS if f["id"] == args.faixa), None)
        if not faixa:
            log("faixa %s não existe" % args.faixa); raise SystemExit(2)
    else:
        faixa = next((f for f in FAIXAS if str(f["id"]) not in feitas), None)
        if not faixa:
            log("todas as faixas já foram puxadas — nada a fazer")
            return

    log("faixa %s: %s (limite %s)" % (faixa["id"], faixa["rotulo"], args.limite))
    sid = disparar(faixa, args.limite)
    log("snapshot %s" % sid)
    meta = esperar(sid)

    nome = "br-faixa%02d-%s.csv" % (faixa["id"], time.strftime("%Y%m%d"))
    caminho = os.path.join(DESTINO, nome)
    tam = baixar_csv(sid, caminho)
    log("csv salvo: %s (%.1f MB)" % (caminho, tam / 1024 / 1024))

    total, novos = semear(caminho)
    log("cache: %s lidos, %s novos" % (f"{total:,}", f"{novos:,}"))

    truncada = total >= args.limite
    if truncada:
        log("ATENÇÃO: a faixa voltou CHEIA (%s = limite). Sobrou gente dentro "
            "dela — subdivida antes da próxima rodada." % total)

    feitas[str(faixa["id"])] = {
        "rotulo": faixa["rotulo"], "snapshot": sid, "registros": total,
        "novos": novos, "csv": nome, "truncada": truncada,
        "custo_informado": meta.get("cost"),
        "quando": time.strftime("%Y-%m-%d %H:%M"),
    }
    plano["feitas"] = feitas
    salvar_plano(plano)
    log("plano atualizado: %s de %s faixas concluídas" % (len(feitas), len(FAIXAS)))


if __name__ == "__main__":
    main()
