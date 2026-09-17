# -*- coding: utf-8 -*-
"""Os tres consertos, do jeito que a planilha vai ver.

1. O "nao perturbe" e os sinais CHEGAM nas colunas.
2. A memoria de empresa lembra quem nao devolveu ninguem.
3. (o cache de CPF tem teste proprio: t_cache_cpf.py)
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("07_sinais")

import main                                    # noqa: E402
import enrich_layout                           # noqa: E402
import memoria_empresa                         # noqa: E402


# O duble devolve o telefone COM os sinais, como a Assertiva faz: o melhor
# numero e do titular, tem WhatsApp e contato recente; o segundo esta em
# nao-perturbe (e por isso tem que ficar atras).
async def falso_decisores(**kw):
    return {"pessoas": [{
        "nome": "CARLOS MOTTA", "cargo": "DIRETOR", "cpf": "11122233344",
        "email": "carlos@x.com.br",
        "telefones": [
            {"ddd": "47", "number": "999991111", "telefone": "47999991111",
             "whatsapp": True, "relacao": "DIRETO", "meses_sem_contato": 0,
             "nao_perturbe": False, "hotphone": True},
            {"ddd": "47", "number": "988882222", "telefone": "47988882222",
             "whatsapp": False, "relacao": "TERCEIRO",
             "meses_sem_contato": 14, "nao_perturbe": True}]}]}


main.funil.decisores_do_linkedin = falso_decisores
main.assertiva.enabled = lambda: False

# ── 1 e 3: os sinais na planilha ───────────────────────────────────────
cols = enrich_layout.colunas(1, 2, 0, 0, com_sinais=True)
want = {k for k, _ in cols}
out = asyncio.run(main._enrich_cnpj("82901000000127", want, max_dec=1,
                                    fonte_dec="linkedin", qtd_tel=2))
print("O QUE A PLANILHA RECEBE")
for k, rot in cols:
    print("  %-34s %s" % (rot, out.get(k) or "(vazio)"))

assert out.get("de_dec1_sinal"), "a coluna de sinais veio vazia"
assert "do titular" in out["de_dec1_sinal"], out["de_dec1_sinal"]
assert "WhatsApp" in out["de_dec1_sinal"], out["de_dec1_sinal"]
# O melhor numero NAO esta em nao-perturbe, entao a coluna fica vazia...
assert out.get("de_dec1_naoperturbe") == "", out.get("de_dec1_naoperturbe")
# ...e o numero do nao-perturbe foi para o segundo lugar.
assert out["de_dec1_tel1"] == "47999991111", out["de_dec1_tel1"]
assert out["de_dec1_tel2"] == "47988882222", out["de_dec1_tel2"]
print()
print("  o nao-perturbe ficou em Telefone 2, como devia")

# ── 2: a memoria da empresa ────────────────────────────────────────────
print()
print("MEMORIA DE EMPRESA")
sabe = memoria_empresa.consultar(["82901000000127"])
print("  depois de enriquecer:", sabe.get("82901000000127"))
assert sabe.get("82901000000127"), "nao anotou o resultado"
assert sabe["82901000000127"]["decisores"] == 1

# Uma empresa que nao devolveu ninguem
memoria_empresa.anotar("36173166000157", decisores=0, com_tel=0, socios=0,
                       fonte="linkedin")
r = memoria_empresa.resumo_planilha(
    ["82901000000127", "36173166000157", "99999999999999"])
print()
print("  aviso ANTES de rodar uma planilha de 3 linhas:")
print("    conhecidas   :", r["conhecidas"], "de", r["linhas"])
print("    vazias       :", r["vazias"], "(nao vale reconsultar)")
print("    com telefone :", r["com_telefone"])
print("    economia     : R$ %.2f pulando as vazias" % r["economia_brl"])
assert r["vazias"] == 1 and r["conhecidas"] == 2, r

print()
print("OK - sinais na planilha, nao-perturbe em segundo, memoria funcionando")
