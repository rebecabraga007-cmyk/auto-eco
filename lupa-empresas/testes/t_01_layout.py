# -*- coding: utf-8 -*-
"""As quantidades escolhidas viram as colunas certas, PREENCHIDAS.

O defeito que este teste existe para impedir: a coluna aparecer no exemplo
mostrado antes de rodar e chegar vazia no arquivo. É o pior tipo de erro do
enriquecimento, porque parece que a fonte não tinha o dado.
"""
import asyncio
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import base                                              # noqa: E402

base.preparar("01_layout")
import enrich_layout                                     # noqa: E402
import main                                              # noqa: E402

main.funil.decisores_do_linkedin = base.falso_funil()
main.assertiva.enabled = lambda: False

cols = enrich_layout.colunas(2, 2, 1, 0, com_cpf=True, com_whatsapp=True,
                             com_sinais=False)
want = {k for k, _ in cols}
out = asyncio.run(main._enrich_cnpj("82901000000127", want, max_dec=2,
                                    fonte_dec="linkedin", qtd_tel=2,
                                    qtd_email=1))

faltando = [k for k in want if k not in out]
assert not faltando, "colunas prometidas que nem existem no retorno: %s" % faltando

# A primeira pessoa tem que vir completa -- o dublê devolve tudo para ela.
for k in ("de_dec1_nome", "de_dec1_cargo", "de_dec1_cpf", "de_dec1_tel1"):
    assert str(out.get(k) or "").strip(), "%s veio vazia com dado disponível" % k

# Telefone 1 e 2 têm que ser NÚMEROS DIFERENTES: já aconteceu de o mesmo
# número sair repetido em duas colunas, e isso só aparece olhando o arquivo.
assert out["de_dec1_tel1"] != out["de_dec1_tel2"], "Telefone 1 e 2 iguais"

# A segunda pessoa não tem segundo telefone; a coluna existe e fica VAZIA.
# Vazio é resposta: quer dizer "perguntei e não há", diferente de não existir.
assert "de_dec2_tel2" in out and out["de_dec2_tel2"] == ""

print("colunas pedidas: %d · todas presentes · nenhuma repetida" % len(want))
print("OK")
