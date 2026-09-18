# -*- coding: utf-8 -*-
"""Empresário Individual rende o titular, não "nenhuma pessoa identificada".

O caso real que motivou: numa lista de TI, 6 de 9 empresas saíram com
"nenhuma pessoa identificada". Todas eram Empresário Individual — que não tem
quadro societário POR LEI. O sistema procurava sócio, achava zero, e
descartava a linha com o nome do dono escrito na razão social.

São 44,4 milhões de empresas na base (64,7%). E em 73% delas a razão social
termina no CPF do dono, o que pula a etapa mais cara do funil.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("08_ei")
import socio_unico as S                                  # noqa: E402

EI = "Empresário (Individual)"
LTDA = "Sociedade Empresária Limitada"


def empresa(razao, nat=EI, qsa=None, mei=""):
    return {"razao_social": razao, "natureza_juridica": nat,
            "qsa": qsa or [], "opcao_mei": mei}


# ── 1. O CASO REAL: razão social com CPF no fim ────────────────────────
d = S.dono(empresa("JOHNNATAN WILLIAM DE OLIVEIRA BARROS 06110276154"))
assert d, "o titular do EI não foi extraído"
assert d["nome_socio"] == "JOHNNATAN WILLIAM DE OLIVEIRA BARROS", d
assert d["cpf_completo"] == "06110276154", d
assert d["cpf_da_razao_social"] is True
print("com CPF no nome  : %-38s CPF %s" % (d["nome_socio"], d["cpf_completo"]))

# ── 2. EI sem CPF no nome: rende o NOME, e diz que não tem CPF ─────────
d = S.dono(empresa("TADEU CASTELO BRANCO MADUREIRA"))
assert d and d["nome_socio"] == "TADEU CASTELO BRANCO MADUREIRA"
assert d["cpf_completo"] == "" and d["cpf_da_razao_social"] is False
print("sem CPF no nome  : %-38s CPF (nenhum, e a coluna diz isso)"
      % d["nome_socio"])

# ── 3. NÃO INVENTA quando há sócio de verdade ─────────────────────────
assert S.dono(empresa("CHRONOS LTDA", LTDA, [{"nome_socio": "ALGUEM"}])) == {}, \
    "inventou titular numa empresa que TEM quadro societário"
# ...nem quando é Ltda sem sócio (aí é falta de dado mesmo, não é EI)
assert S.dono(empresa("EMPRESA SEM SOCIO LTDA", LTDA, [])) == {}, \
    "tratou Ltda sem QSA como Empresário Individual"
print("com QSA real     : não inventa · Ltda sem QSA: não inventa")

# ── 4. O CPF PASSA PELO VERIFICADOR ───────────────────────────────────
# Sem isto, qualquer razão social terminando em 11 dígitos (número de
# registro, telefone com DDI) entraria como CPF e viraria consulta paga num
# documento que não existe.
d = S.dono(empresa("FULANO DE TAL 11111111111"))
assert d["cpf_completo"] == "", "aceitou CPF com dígito verificador inválido"
# E o nome NUNCA fica com os dígitos: "FULANO 11111111111" não acha ninguém.
assert d["nome_socio"] == "FULANO DE TAL", d
print("CPF inválido     : rejeitado, e os dígitos saíram do nome")
assert S.cpf_valido("06110276154") and not S.cpf_valido("11111111111")

# ── 5. MEI pela opção do Simples, quando a natureza vem vazia ─────────
d = S.dono(empresa("MARIA DA SILVA 12345678909", nat="", mei="S"))
assert d and d["cpf_completo"] == "12345678909", d
print("MEI sem natureza : reconhecido pela opção do Simples")

# ── 6. `socios_efetivos` é a porta única ──────────────────────────────
assert len(S.socios_efetivos(empresa("X LTDA", LTDA, [{"nome_socio": "A"},
                                                      {"nome_socio": "B"}]))) == 2
assert len(S.socios_efetivos(empresa("JOAO DA SILVA 06110276154"))) == 1
assert S.socios_efetivos(empresa("NADA LTDA", LTDA, [])) == []
print("socios_efetivos  : QSA quando existe, titular quando não, vazio quando nem um")

print()
print("OK - o dono do Empresário Individual deixa de ser jogado fora")
