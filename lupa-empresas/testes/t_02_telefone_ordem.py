# -*- coding: utf-8 -*-
"""O telefone que chega na planilha é o de maior chance de alguém atender.

E, acima de tudo: um número no cadastro de NÃO PERTURBE não pode ser o
primeiro. Esse defeito esteve em produção -- o funil respeitava a regra, mas
quem escreve a planilha não, e os dois respondiam coisas diferentes para a
mesma pessoa.

Não é ruído de ordenação: é risco jurídico, e o SDR ligava sem saber.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("02_telefone")
import mkbuscas                                          # noqa: E402

# O caso cruel de propósito: o número do não-perturbe GANHA em todo o resto --
# celular, WhatsApp, do titular, contato no último mês, priority 1.
tels = [
    {"telefone": "47999990001", "ddd": "47", "number": "999990001",
     "nao_perturbe": True, "whatsapp": True, "relacao": "DIRETO",
     "meses_sem_contato": 0, "priority": 1, "hotphone": True},
    {"telefone": "47988880002", "ddd": "47", "number": "988880002",
     "nao_perturbe": False, "whatsapp": True, "relacao": "DIRETO",
     "meses_sem_contato": 6, "priority": 2},
    {"telefone": "47977770003", "ddd": "47", "number": "977770003",
     "nao_perturbe": False, "whatsapp": False, "relacao": "TERCEIRO",
     "meses_sem_contato": 24, "priority": 3},
]
saida = mkbuscas.refine_phones(tels, modo="celular", max_n=3)
ordem = [t["digits"] for t in saida]
print("ordem que vai para a planilha:", ordem)

assert not saida[0].get("nao_perturbe"), \
    "NÃO PERTURBE saiu como Telefone 1 — o SDR liga nele primeiro"
assert saida[-1]["digits"] == "47999990001", \
    "o não-perturbe devia ir para o fim, mesmo ganhando no resto"

# E entre os que podem ser ligados, o melhor vem antes: do titular, com
# WhatsApp e contato mais recente.
assert ordem[0] == "47988880002", "a ordem dos ligáveis está errada: %s" % ordem

# O funil precisa concordar com isso -- duas regras diferentes para a mesma
# pessoa é como o defeito nasceu.
import funil                                             # noqa: E402
pelo_funil = [t["telefone"] for t in sorted(tels, key=funil._ordem_telefone)]
assert pelo_funil[-1] == "47999990001", \
    "o funil e a planilha discordam sobre o não-perturbe"
print("funil e planilha concordam:", pelo_funil[-1], "por último nos dois")
print("OK")
