# -*- coding: utf-8 -*-
"""O job roda inteiro, sobrevive, grava e aparece na lista.

Sem API de verdade: o funil vira duble. O que esta sendo testado e a
maquinaria do job (fila, retomada, gravacao onda a onda, fechamento), nao a
busca -- e rodar isso contra a Assertiva custaria dinheiro para provar uma
coisa que nao e sobre ela.
"""
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("03_job")

import main                                            # noqa: E402
import enrich_jobs                                     # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

VISTOS = []


async def falso_decisores(**kw):
    VISTOS.append(kw.get("cnpj"))
    return {"pessoas": [
        {"nome": "CARLOS MOTTA", "cargo": "DIRETOR", "cpf": "11122233344",
         "email": "carlos@x.com.br",
         "telefones": [{"ddd": "47", "number": "999991111", "whatsapp": True}]},
    ]}


main.funil.decisores_do_linkedin = falso_decisores
main.assertiva.enabled = lambda: False

CSV = ("CNPJ;Empresa\n"
       "82901000000127;INTELBRAS\n"
       "17688085000145;EVEN3\n"
       "07175725000321;WEG\n"
       "79379491000183;HAVAN\n"
       "82936378000190;NELINHO\n")

H = {"X-User-Email": "teste@blusalesgroup.com.br"}

with TestClient(main.app) as c:
    up = c.post("/api/enrich/upload",
                files={"file": ("teste.csv", CSV.encode("utf-8"), "text/csv")}
                ).json()
    assert up["status"] == "ok", up
    print("upload:", up["upload_id"], up["sheets"][0]["linhas"], "linhas",
          "| coluna CNPJ:", up["sheets"][0]["cnpj_col"])

    pedido = {
        "upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"],
        "cnpj_col": up["sheets"][0]["cnpj_col"],
        "fields": ["rfb_razao", "de_dec1_nome", "de_dec1_cargo", "de_dec1_tel1"],
        "qtd_telefones": 1, "max_decisores": 1, "decisor_fonte": "linkedin",
        "nome": "teste do job", "email": False, "origem": "teste.csv",
    }
    j = c.post("/api/enrich/job", headers=H, json=pedido).json()
    print("job criado:", j)
    assert j["status"] == "ok", j
    jid = j["job"]

    # A tela que reabre tem que reencontrar o trabalho andando.
    print("em andamento:", c.get("/api/enrich/jobs", headers=H).json())

    for _ in range(60):
        st = c.get("/api/enrich/job/%s" % jid, headers=H).json()
        if st["estado"] not in ("fila", "processando"):
            break
        time.sleep(0.5)
    print("estado final:", st)
    assert st["estado"] == "concluido", st
    assert st["feitas"] == 5, st

    r = c.get("/api/enrich/job/%s/resultado" % jid, headers=H).json()
    print("colunas novas:", [x["label"] for x in r["added_cols"]])
    print("linha 1:", {k: v for k, v in r["rows"][0].items() if v})

    lista = c.get("/api/enrich/salvos", headers=H).json()
    it = lista["itens"][0]
    print("na lista:", it["nome"], "| linhas", it["linhas"],
          "| com decisor", it["com_decisor"], "| bytes", it["bytes"])
    assert it["linhas"] == 5 and it["com_decisor"] == 5, it

    arq = c.get("/api/enrich/salvo/%s/arquivo" % it["id"], headers=H)
    print("xlsx:", arq.status_code, len(arq.content), "bytes")

    # O parcial tem que ter sumido: ele so existe enquanto E o trabalho.
    print("parcial apagado:", not os.path.exists(enrich_jobs._arquivo(jid)))

    # ── PARAR NO MEIO ──────────────────────────────────────────────────
    pedido2 = dict(pedido, nome="teste de parada")
    j2 = c.post("/api/enrich/job", headers=H, json=pedido2).json()
    c.post("/api/enrich/job/%s/parar" % j2["job"], headers=H)
    for _ in range(60):
        st2 = c.get("/api/enrich/job/%s" % j2["job"], headers=H).json()
        if st2["estado"] not in ("fila", "processando"):
            break
        time.sleep(0.5)
    print("parada:", st2["estado"], "| feitas", st2["feitas"], "de", st2["total"])

    outro = c.get("/api/enrich/job/%s" % jid,
                  headers={"X-User-Email": "outro@x.com"}).status_code
    print("job de outra pessoa:", outro)

print("empresas consultadas:", len(VISTOS))
