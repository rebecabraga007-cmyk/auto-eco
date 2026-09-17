# -*- coding: utf-8 -*-
"""Completar uma lista pronta: nao perde linha, nao repete coluna, nao paga duas vezes.

As tres formas de essa funcao mentir sem avisar:

  1. ENTREGAR MENOS LINHAS. Se o complemento devolvesse so as linhas
     reconsultadas, a pessoa abriria um arquivo menor que o que mandou.
  2. COBRAR DE NOVO pelo que ja estava la -- que e justamente o que ela
     existe para evitar.
  3. DUPLICAR COLUNA, porque um campo pedido de novo ja era coluna do
     arquivo anterior. So aparece quando alguem faz PROCV e pega a errada.

O duble de funil responde telefone so para algumas empresas, de proposito:
sem lista incompleta nao da para testar complemento nenhum.
"""
import time
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("05_complemento")

import main                                            # noqa: E402
from fastapi.testclient import TestClient              # noqa: E402

CONSULTAS = []
COM_TELEFONE = {"82901000000001", "82901000000002"}    # so 2 de 10


async def falso_decisores(cnpj="", **kw):
    CONSULTAS.append(("decisor", cnpj))
    tem = cnpj in COM_TELEFONE
    return {"pessoas": [{
        "nome": "CARLOS MOTTA", "cargo": "DIRETOR", "cpf": "11122233344",
        "email": "carlos@x.com.br",
        "telefones": ([{"ddd": "47", "number": "999991111"}] if tem else [])}]}


main.funil.decisores_do_linkedin = falso_decisores
main.assertiva.enabled = lambda: False

# O QUE CONTAR. Minha primeira versao contava chamadas ao funil do LinkedIn --
# e o caminho de SOCIO nao passa por la, entao a rodada 2 marcava zero e o
# teste acusou uma economia que na verdade era o instrumento olhando para o
# lugar errado. O que prova "nao paguei duas vezes" e quantas LINHAS foram
# enriquecidas, e isso e `_enrich_cnpj`.
LINHAS_ENRIQUECIDAS = []
_original = main._enrich_cnpj


async def _contando(cnpj, want, **kw):
    LINHAS_ENRIQUECIDAS.append(cnpj)
    return await _original(cnpj, want, **kw)


main._enrich_cnpj = _contando

CSV = "CNPJ;Empresa\n" + "\n".join(
    "8290100000%04d;EMPRESA %d" % (i, i) for i in range(1, 11)) + "\n"
H = {"X-User-Email": "teste@blusalesgroup.com.br"}


def espera(c, jid):
    for _ in range(80):
        st = c.get("/api/enrich/job/%s" % jid, headers=H).json()
        if st["estado"] not in ("fila", "processando"):
            return st
        time.sleep(0.4)
    raise AssertionError("job nao terminou")


with TestClient(main.app) as c:
    up = c.post("/api/enrich/upload",
                files={"file": ("l.csv", CSV.encode(), "text/csv")}).json()

    # ── RODADA 1: so decisor, sem socio ────────────────────────────────
    j = c.post("/api/enrich/job", headers=H, json={
        "upload_id": up["upload_id"], "sheet": up["sheets"][0]["name"],
        "cnpj_col": "CNPJ", "fields": ["de_dec1_nome", "de_dec1_tel1"],
        "max_decisores": 1, "qtd_telefones": 1, "qtd_socios": 0,
        "nome": "Primeira rodada"}).json()
    st = espera(c, j["job"])
    print("rodada 1 :", st["estado"], "|", st["feitas"], "linhas |",
          "%s%% com telefone" % st["pct_telefone"])
    assert st["pct_telefone"] == 20.0, st
    # A PERGUNTA DO SOCIO tem que nascer sozinha: 20% < 40% e ninguem pediu socio.
    assert st["oferecer_socios"] is True, st
    print("oferece socio:", st["oferecer_socios"], "(20% < 40% e socio nao foi pedido)")
    eid = st["enriquecimento_id"]
    assert len(LINHAS_ENRIQUECIDAS) == 10, LINHAS_ENRIQUECIDAS

    # ── O QUE A LISTA JA TEM ───────────────────────────────────────────
    v = c.get("/api/enrich/salvo/%s/completar" % eid, headers=H).json()
    print()
    print("ja tem   :", v["linhas"], "linhas |", v["com_telefone"], "com telefone |",
          v["sem_telefone"], "sem |", "socios:", v["com_socio"])
    assert v["oferecer_socios"] is True and v["sem_telefone"] == 8, v

    # ── QUANTO CUSTARIA, antes de mandar ───────────────────────────────
    orc = c.post("/api/enrich/complementar", headers=H, json={
        "base": eid, "fields": ["so_socio1_nome", "so_socio1_tel1"],
        "qtd_socios": 1, "qtd_telefones": 1,
        "alvo_linhas": "sem_telefone", "so_calcular": True}).json()
    print("orcamento:", orc["linhas_a_consultar"], "de", orc["linhas_total"],
          "linhas seriam consultadas")
    assert orc["linhas_a_consultar"] == 8, orc

    # ── RODADA 2: completa com socio, so nas linhas sem telefone ───────
    antes = len(LINHAS_ENRIQUECIDAS)
    j2 = c.post("/api/enrich/complementar", headers=H, json={
        "base": eid, "fields": ["so_socio1_nome", "so_socio1_tel1"],
        "qtd_socios": 1, "qtd_telefones": 1,
        "alvo_linhas": "sem_telefone", "nome": "Com socios"}).json()
    print()
    print("rodada 2 :", j2["total"], "linhas a consultar de", j2["linhas_total"])
    st2 = espera(c, j2["job"])
    print("           ", st2["estado"], "|", st2["feitas"], "consultadas")

    # 1. NAO PERDEU LINHA
    it = next(x for x in c.get("/api/enrich/salvos", headers=H).json()["itens"]
              if x["id"] == st2["enriquecimento_id"])
    print()
    print("arquivo  :", it["nome"], "|", it["linhas"], "linhas")
    assert it["linhas"] == 10, ("o complemento encolheu a lista", it)

    # 2. NAO COBROU DE NOVO as 2 que ja tinham telefone
    refeitas = len(LINHAS_ENRIQUECIDAS) - antes
    print("linhas consultadas na rodada 2: %d (a lista tem 10; refazer tudo seriam 10)"
          % refeitas)
    assert refeitas == 8, refeitas

    # 3. NAO DUPLICOU COLUNA
    r = c.get("/api/enrich/job/%s/resultado" % j2["job"], headers=H).json()
    todas = [x["key"] for x in r["added_cols"]] + r["base_cols"]
    dup = [k for k in set(todas) if todas.count(k) > 1]
    print("colunas  :", len(todas), "| repetidas:", dup or "nenhuma")
    assert not dup, dup

    # E o conteudo antigo sobreviveu?
    with_nome = sum(1 for x in r["rows"] if str(x.get("de_dec1_nome") or "").strip())
    print("decisores da rodada 1 ainda presentes:", with_nome, "de", len(r["rows"]))
    assert with_nome == len(r["rows"]), "o complemento apagou dado da rodada anterior"

    # 4. NAO OFERECE COMPRAR SOCIO DE NOVO.
    #    Neste teste os socios vieram VAZIOS (CNPJ ficticio, sem Receita).
    #    "Pedi e nao veio" e diferente de "nunca pedi": insistir seria vender
    #    a mesma decepcao duas vezes.
    v2 = c.get("/api/enrich/salvo/%s/completar" % it["id"], headers=H).json()
    print()
    print("na lista nova: %s%% com telefone | socios encontrados: %d | "
          "ja pediu socio: %s | oferece de novo: %s"
          % (v2["pct_telefone"], v2["com_socio"], v2["ja_pediu_socios"],
             v2["oferecer_socios"]))
    assert v2["ja_pediu_socios"] is True, v2
    assert v2["oferecer_socios"] is False, ("ofereceu comprar o mesmo nada", v2)

print()
print("OK - completa sem perder linha, sem repetir coluna e sem pagar duas vezes")
