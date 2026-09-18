# -*- coding: utf-8 -*-
"""Empresário Individual não tem sócio -- o dono É a razão social.

O DEFEITO QUE ISTO CONSERTA
---------------------------
A Rebeca mostrou uma lista de TI em que 9 de 9 empresas saíram sem telefone,
e 6 delas com "nenhuma pessoa identificada". Fui conferir na Receita:

    JOHNNATAN WILLIAM DE OLIVEIRA BARROS 06110276154  Empresário (Individual)  0 sócios
    TADEU CASTELO BRANCO MADUREIRA                    Empresário (Individual)  0 sócios
    W C PAVAN SERVICOS E GESTAO DE TECNOLOGIA         Empresário (Individual)  0 sócios
    NATALI FERNANDA PEREIRA LIMA CONSULTORIA          Empresário (Individual)  0 sócios
    FRANCO ITIRO NAKAMURA CONSULTORIA                 Empresário (Individual)  0 sócios

Zero sócios não é falta de dado: **Empresário Individual não tem quadro
societário por lei** -- o dono e a empresa são a mesma pessoa jurídica. O
sistema procurava sócio, achava zero, dizia "nenhuma pessoa identificada" e
descartava a linha. Tecnicamente certo, praticamente errado: o nome do dono
está escrito ali, na razão social.

E repare no primeiro: aqueles 11 dígitos no fim são o CPF dele. A Receita
monta a razão social do EI como "NOME + CPF".

O TAMANHO DISSO (medido em 18/set/2026, na base inteira)
--------------------------------------------------------
    Empresário (Individual) .......... 44.389.558 empresas
    fração da base ................... 64,7%
    razão social terminando em CPF ... 73% (amostra de 2.000)

Ou seja: dois terços da base não tinham como render sócio nenhum, e numa
lista de prestadores de TI -- onde MEI e EI são a maioria -- isso explicava
quase todas as linhas descartadas.

O QUE ISSO ECONOMIZA, além de achar quem não era achado
-------------------------------------------------------
O CPF vindo da razão social PULA a desambiguação de homônimo, que é a etapa
mais caro do funil: até R$ 2,38 por pessoa. Aqui ele vem de graça, da nossa
cópia da Receita, e já certo -- não é um candidato entre 195 homônimos, é o
CPF que o próprio registro da empresa carrega.

O QUE CONTINUA RUIM, e é honesto dizer
--------------------------------------
Nos 27% sem CPF no nome, sobra um nome frequentemente abreviado ("W C PAVAN",
"C. E. O. DE SOUZA") que não desambigua em base nenhuma. Para esses o
resultado segue fraco, e o motivo passa a ser dito em voz alta em vez de
aparecer como "nenhuma pessoa identificada".
"""
import re

# A natureza vem como DESCRIÇÃO (`cnpj_lookup` já traduz o código), e as
# quatro que interessam têm "individual" no nome:
#   2135 Empresário (Individual)
#   2305 / 2313 Empresa Individual de Responsabilidade Limitada (EIRELI)
#   4014 Empresa Individual Imobiliária
_RE_INDIVIDUAL = re.compile(r"individual", re.I)

# O CPF no fim da razão social, do jeito que a Receita escreve.
_RE_CPF_FINAL = re.compile(r"[\s\-]*(\d{11})\s*$")


def cpf_valido(cpf: str) -> bool:
    """Confere os dígitos verificadores.

    Não é preciosismo: sem isso, qualquer razão social terminando em 11
    dígitos -- um número de registro, um ano repetido, um telefone com DDI --
    entraria como CPF e viraria consulta paga num documento que não existe.
    """
    d = re.sub(r"\D", "", str(cpf or ""))
    if len(d) != 11 or d == d[0] * 11:
        return False
    for corte in (9, 10):
        soma = sum(int(d[i]) * ((corte + 1) - i) for i in range(corte))
        resto = (soma * 10) % 11
        if resto == 10:
            resto = 0
        if resto != int(d[corte]):
            return False
    return True


def e_individual(company: dict) -> bool:
    """Esta empresa é do tipo que não tem sócio por lei?"""
    if not isinstance(company, dict):
        return False
    if _RE_INDIVIDUAL.search(str(company.get("natureza_juridica") or "")):
        return True
    # MEI é sempre Empresário Individual; se a natureza vier vazia (base
    # antiga, filial sem empresa), a opção do Simples resolve.
    return str(company.get("opcao_mei") or "").strip().upper() in ("S", "SIM")


def dono(company: dict) -> dict:
    """O titular do EI, no MESMO formato de um sócio do QSA. {} se não se aplica.

    Devolve no formato do QSA de propósito: quem consome não precisa saber que
    esta pessoa veio de outro lugar, e o código que trata sócio passa a tratar
    o titular sem um `if` novo em cada ponto.
    """
    if not isinstance(company, dict):
        return {}
    if company.get("qsa"):
        return {}                      # tem sócio de verdade; não invente
    if not e_individual(company):
        return {}

    razao = str(company.get("razao_social") or "").strip()
    if not razao:
        return {}

    # O NOME NUNCA FICA COM OS DIGITOS, mesmo quando eles nao formam um CPF
    # valido. Numero no fim de nome de pessoa nao existe em base nenhuma:
    # deixar "FULANO DE TAL 11111111111" como nome garante busca vazia. Os
    # digitos saem do nome sempre; viram CPF so se passarem no verificador.
    cpf = ""
    m = _RE_CPF_FINAL.search(razao)
    if m:
        if cpf_valido(m.group(1)):
            cpf = m.group(1)
        razao = razao[:m.start()].strip(" -")

    nome = re.sub(r"\s{2,}", " ", razao).strip()
    if not nome:
        return {}

    return {
        "nome_socio": nome,
        # O QSA real traz o CPF MASCARADO ("***123456**"); aqui ele vem
        # inteiro, e é justamente isso que economiza a desambiguação.
        "cnpj_cpf_do_socio": cpf,
        "cpf_completo": cpf,
        "qualificacao_socio": "Titular (Empresário Individual)",
        "faixa_etaria": "",
        "identificador": "2",           # pessoa física, como no QSA
        # MARCA A ORIGEM. Quem lê a planilha precisa poder distinguir "sócio
        # do quadro societário" de "titular deduzido da razão social" -- são
        # graus de certeza diferentes, e esconder isso seria vender palpite
        # como registro.
        "origem": "razao_social",
        "cpf_da_razao_social": bool(cpf),
    }


def socios_efetivos(company: dict) -> list:
    """O QSA de verdade, ou o titular do EI quando não há QSA.

    É por aqui que todo mundo deve perguntar "quem são as pessoas desta
    empresa" -- se cada ponto do sistema decidir isso por conta, uns vão
    lembrar do Empresário Individual e outros não, e a mesma empresa vai
    render sócio numa tela e nenhum na outra.
    """
    qsa = [s for s in (company or {}).get("qsa") or [] if isinstance(s, dict)]
    if qsa:
        return qsa
    d = dono(company)
    return [d] if d else []
