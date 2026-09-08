# -*- coding: utf-8 -*-
"""Auditoria: cada etapa do documento existe MESMO no codigo, e roda?

A pergunta que esta auditoria responde e exatamente a que me pegou hoje: o
docstring listava dez etapas e o codigo tinha cinco, e nada acusava. Aqui cada
etapa e verificada por TRES criterios:

  declarada  aparece no docstring do modulo
  no codigo  existe a funcao/chamada que a implementa
  executa    dispara num perfil real e deixa marca em `etapas`

Uma etapa so conta como configurada se passar nos tres. R$ 0,00 -- roda com
`usar_pagas=False` e nao chega nas etapas 08/09 pagas.
"""
import asyncio
import inspect
import os
import re
import sys

from dotenv import load_dotenv
load_dotenv("/opt/capiblu/lupa-empresas/.env")
sys.path.insert(0, "/opt/capiblu/lupa-empresas/backend")
os.environ.setdefault("CNPJ_DB_DIR", "/capiblu_data")

import funil
import identidade as I

# (numero, nome, o que procurar no codigo, marca esperada em `etapas`)
ETAPAS = [
    # 00 nao e chamada por este modulo: o perfil chega pronto da tela.
    ("00", "Bright Data (entra pronto)", r"perfil.*pronto|Bright Data", None),
    ("01", "porta de cargo",         r"funcoes\.eh_cargo",           "01 cargo"),
    ("02", "porte da empresa",       r"I\.estrategia",               None),
    ("03", "possiveis decisores",    r"assertiva\.possiveis_decisores", "03/04"),
    ("04", "RAIS / CAGED",           r"rais\.vinculos_cnpj",         "03/04"),
    ("05", "JBR",                    r"_pela_jbr",                   "05 JBR"),
    ("06", "WorkAPI",                r"workapi\.nome_search",        "06 WorkAPI"),
    ("07", "MK",                     r"mkbuscas\.consulta_cpf",      "07 MK"),
    ("08", "Assertiva nome+cidade",  r"nome-endereco",               "08 Assertiva"),
    ("09", "Assertiva consulta_cpf", r"assertiva\.consulta_cpf",     "09 consulta"),
    ("10", "decidir()",              r"I\.decidir",                  None),
]

# desambiguadores que o documento tambem lista
EXTRAS = [
    ("slug da URL",            r"_nome_do_slug"),
    ("faixa de nascimento",    r"faixa_nascimento"),
    ("idade 18-60",            r"_idade_ok"),
    ("CPF suspenso/falecido",  r"_situacao_ok"),
    ("regiao fiscal do CPF",   r"REGIAO|regiao_fiscal|digito"),
    ("particao pelo nome do meio", r"_nomes_do_meio"),
    ("nome do meio conferido", r"_nome_contido"),
    ("diretorio de cidades",   r"cidades\."),
]

PERFIS = [
    {"nome": "Aline Manchini", "cargo": "SDR Team Lead",
     "empresa": "BLU Sales Group", "cidade": "Greater São Paulo Area",
     "url": "https://br.linkedin.com/in/aline-mello-manchini-8b2a1b1b0"},
    {"nome": "David Mikael Schuster", "cargo": "",
     "empresa": "BLU Sales Group", "cidade": "Itajaí, Santa Catarina, Brazil",
     "url": "https://br.linkedin.com/in/david-mikael-schuster-2253b0352"},
]


async def main():
    fonte = inspect.getsource(funil)
    doc = funil.__doc__ or ""

    # roda de graca para colher as marcas
    marcas = set()
    gasto = funil.Gasto(0.0)          # teto zero: nenhuma consulta paga passa
    emp = funil.Empresa("BLU Sales Group")
    await emp.preparar(gasto, usar_pagas=False)
    for p in PERFIS:
        r = await funil.resolver_pessoa(p, emp, gasto)
        for e in (r.get("etapas") or []):
            marcas.add(e.split(":")[0])

    print("=" * 82)
    print("AUDITORIA DO FUNIL — as 10 etapas do documento")
    print("=" * 82)
    print("%-4s %-24s %-10s %-10s %s" % ("#", "ETAPA", "DECLARADA", "NO CODIGO", "EXECUTA"))
    print("-" * 82)
    faltando = []
    for num, nome, padrao, marca in ETAPAS:
        declarada = bool(re.search(r"^\s*%s\s" % num, doc, re.M))
        no_codigo = bool(re.search(padrao, fonte))
        if marca is None:
            executa = "n/a"
        else:
            executa = "sim" if any(m.startswith(marca.split()[0]) for m in marcas) else "NAO"
        ok = declarada and no_codigo and executa in ("sim", "n/a")
        if not ok:
            faltando.append("%s %s" % (num, nome))
        print("%-4s %-24s %-10s %-10s %s%s"
              % (num, nome[:24], "sim" if declarada else "NAO",
                 "sim" if no_codigo else "NAO", executa,
                 "" if ok else "   <<<"))

    print()
    print("=" * 82)
    print("DESAMBIGUADORES")
    print("=" * 82)
    for nome, padrao in EXTRAS:
        tem = bool(re.search(padrao, fonte))
        print("  %-30s %s%s" % (nome, "no codigo" if tem else "AUSENTE",
                                "" if tem else "   <<<"))
        if not tem:
            faltando.append(nome)

    print()
    print("=" * 82)
    if faltando:
        print("FALTAM %d: %s" % (len(faltando), " | ".join(faltando)))
    else:
        print("TODAS as etapas declaradas existem no codigo e executam.")
    print("gasto desta auditoria: R$ %.2f" % gasto.brl)

asyncio.run(main())
