# -*- coding: utf-8 -*-
"""Os dois caminhos perigosos: PARAR no meio e RETOMAR depois de morrer.

Sao os que nao aparecem em teste feliz e sao exatamente os que custam
dinheiro quando quebram -- um cobra linha que ninguem pediu, o outro cobra de
novo linha que ja foi paga.
"""
import asyncio
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("04_parada")

import main                                            # noqa: E402
import enrich_jobs                                     # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

CONSULTADAS = []


async def falso_lento(**kw):
    CONSULTADAS.append(kw.get("cnpj"))
    await asyncio.sleep(0.35)        # cada empresa demora, como na vida real
    return {"pessoas": [
        {"nome": "CARLOS MOTTA", "cargo": "DIRETOR", "cpf": "11122233344",
         "email": "", "telefones": [{"ddd": "47", "number": "999991111"}]}]}


main.funil.decisores_do_linkedin = falso_lento
main.assertiva.enabled = lambda: False

linhas = "\n".join("8290100000%04d;EMPRESA %d" % (i, i) for i in range(1, 41))
CSV = "CNPJ;Empresa\n" + linhas + "\n"
H = {"X-User-Email": "teste@blusalesgroup.com.br"}

with TestClient(main.app) as c:
    up = c.post("/api/enrich/upload",
                files={"file": ("g.csv", CSV.encode("utf-8"), "text/csv")}).json()
    pedido = {"upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"],
              "cnpj_col": "CNPJ", "fields": ["de_dec1_nome", "de_dec1_tel1"],
              "max_decisores": 1, "decisor_fonte": "linkedin",
              "nome": "parada no meio"}

    # ── 1. PARAR NO MEIO ───────────────────────────────────────────────
    j = c.post("/api/enrich/job", headers=H, json=pedido).json()
    jid = j["job"]
    print("criado com", j["total"], "linhas")
    time.sleep(1.2)
    andando = c.get("/api/enrich/jobs", headers=H).json()["jobs"]
    print("a tela reaberta reencontra:", andando)
    assert andando and andando[0]["id"] == jid, andando

    print("parar:", c.post("/api/enrich/job/%s/parar" % jid, headers=H).json())
    for _ in range(40):
        st = c.get("/api/enrich/job/%s" % jid, headers=H).json()
        if st["estado"] not in ("fila", "processando"):
            break
        time.sleep(0.3)
    print("estado:", st["estado"], "| feitas", st["feitas"], "de", st["total"])
    assert st["estado"] == "cancelado", st
    assert 0 < st["feitas"] < 40, st
    consultadas_ate_parar = len(CONSULTADAS)

    # O que ja foi pago tem que ter virado arquivo, e nao lixo.
    it = c.get("/api/enrich/salvos", headers=H).json()["itens"][0]
    print("virou arquivo mesmo cancelado:", it["nome"], it["linhas"], "linhas")
    assert it["linhas"] == st["feitas"], (it, st)

    # ── 2. RETOMAR ─────────────────────────────────────────────────────
    # Simula a morte do processo: o job fica 'processando' com metade no
    # disco, e a subida seguinte tem que continuar de onde parou.
    j2 = c.post("/api/enrich/job", headers=H,
                json=dict(pedido, nome="morte no meio")).json()
    jid2 = j2["job"]
    time.sleep(1.5)
    enrich_jobs.marcar(jid2, cancelar=1)          # para o trabalhador atual
    for _ in range(40):
        if enrich_jobs.pegar(jid2)["status"] not in ("fila", "processando"):
            break
        time.sleep(0.2)
    no_disco = enrich_jobs.ja_feitas(jid2)
    antes = len(CONSULTADAS)
    print("morreu com", no_disco, "linhas no disco")
    assert 0 < no_disco < 40, no_disco

    # Volta o job para 'processando', como o processo anterior o deixaria.
    enrich_jobs.marcar(jid2, status="processando", cancelar=0)
    print("pendentes na subida:", enrich_jobs.pendentes())
    c.portal.call(main._retomar_jobs)
    for _ in range(80):
        st2 = c.get("/api/enrich/job/%s" % jid2, headers=H).json()
        if st2["estado"] not in ("fila", "processando"):
            break
        time.sleep(0.3)
    refeitas = len(CONSULTADAS) - antes
    print("estado:", st2["estado"], "| feitas", st2["feitas"])
    print("linhas consultadas na retomada:", refeitas,
          "(sem retomada seriam", st2["feitas"], ")")
    assert st2["feitas"] == 40, st2
    # A prova: retomou de onde parou em vez de recomeçar e cobrar de novo.
    assert refeitas == 40 - no_disco, (refeitas, no_disco)

print("OK — parada e retomada sem cobrar linha duas vezes")
