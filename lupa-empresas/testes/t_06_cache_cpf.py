# -*- coding: utf-8 -*-
"""A segunda vez que a mesma pessoa aparecer nao pode custar nada.

E o teste do principio que o projeto inteiro segue e que faltava no passo
mais caro: pagar na ingestao, nao na consulta.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("06_cache")

import linkedin_cache as LC

print("banco de teste:", LC.DB_PATH)
LC.init()

URL = "https://linkedin.com/in/carlos-motta-exemplo"
NOME = LC.norm("Carlos Motta dos Santos")
EMP = LC.norm("Intelbras")

print()
print("1. nunca perguntamos:", LC.recordar_cpf(url=URL, nome_norm=NOME, empresa_norm=EMP))

# O funil resolveu, gastando R$ 1,19
LC.lembrar_cpf(url=URL, nome_norm=NOME, empresa_norm=EMP, cpf="11122233344",
               confianca=90, situacao="resolvido_gratis", forte=True,
               custo_brl=1.19)
r = LC.recordar_cpf(url=URL, nome_norm=NOME, empresa_norm=EMP)
print("2. depois de resolver  :", {k: r[k] for k in ("cpf", "confianca", "custo_brl")})
assert r["cpf"] == "11122233344"

# A MESMA pessoa chegando com OUTRA url (busca diferente, snapshot, link colado)
r2 = LC.recordar_cpf(url="https://br.linkedin.com/in/outro-slug",
                     nome_norm=NOME, empresa_norm=EMP)
print("3. url diferente, mesmo nome+empresa:", r2["cpf"] if r2 else None)
assert r2 and r2["cpf"] == "11122233344", "devia achar por nome+empresa"

# NEGATIVA: o funil tentou e nao fechou
U2 = "https://linkedin.com/in/ana-lima-exemplo"
LC.lembrar_cpf(url=U2, nome_norm=LC.norm("Ana Beatriz Lima"),
               empresa_norm=EMP, cpf="", confianca=0,
               situacao="nao_identificado", custo_brl=2.38)
neg = LC.recordar_cpf(url=U2)
print("4. negativa guardada   :", {"cpf": neg["cpf"] or "(vazio)",
                                   "situacao": neg["situacao"],
                                   "custou": neg["custo_brl"]})
assert neg is not None and not neg["cpf"], "a negativa tem que ser lembrada"

# E a negativa VENCE depois de 30 dias
import sqlite3
import time
con = sqlite3.connect(LC.DB_PATH)
con.execute("UPDATE perfil_cpf SET quando = ? WHERE url = ?",
            (int(time.time()) - 31 * 86400, U2))
con.commit()
con.close()
print("5. negativa com 31 dias:", LC.recordar_cpf(url=U2))
assert LC.recordar_cpf(url=U2) is None, "negativa velha tem que expirar"

# E a POSITIVA nao vence -- CPF nao muda
con = sqlite3.connect(LC.DB_PATH)
con.execute("UPDATE perfil_cpf SET quando = ? WHERE url = ?",
            (int(time.time()) - 900 * 86400, URL))
con.commit()
con.close()
velha = LC.recordar_cpf(url=URL)
print("6. positiva com 900 dias:", velha["cpf"] if velha else None)
assert velha and velha["cpf"], "CPF nao muda -- positiva nao expira"

print()
print("economia acumulada:", LC.economia_cpf())
print()
print("OK - resolve uma vez, lembra para sempre; a negativa esquece em 30 dias")
