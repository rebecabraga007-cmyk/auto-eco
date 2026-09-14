# -*- coding: utf-8 -*-
"""Telefone do jeito que cada ferramenta espera receber.

POR QUE EXISTE
--------------
A planilha enriquecida sai com o telefone espalhado: um do decisor 1, outro do
decisor 2, dois da empresa, um do socio. Para LIGAR isso e otimo -- cada numero
ao lado de quem atende. Para IMPORTAR e ruim: a Meetime pede os telefones de um
lead numa coluna so, e a Zenvia quer o numero com DDI.

Entao a planilha passou a ter as duas coisas. As colunas individuais continuam
exatamente onde estavam, e a coluna unida nasce ao lado.

OS FORMATOS, E DE ONDE VEIO CADA UM
-----------------------------------
meetime  +5548999999999   MEDIDO na conta da BLU em 14/set/2026: 100 leads
                          lidos pela API, e o campo `primaryPhoneString` veio
                          "+55" + DDD + numero em 97 deles (os outros 3
                          vazios). Varios telefones no mesmo lead chegam em
                          `phonesString` separados por ", " -- e por isso a
                          coluna unida usa virgula e espaco. A documentacao da
                          API mostra o mesmo: {"phone": "+551149501024"}.

zenvia   +5548999999999   Pedido da Rebeca: "vem com +55 nos numeros". Vale
                          registrar que os exemplos da API de SMS da Zenvia
                          mostram o numero SEM o "+" ("5511999999999"); os dois
                          formatos convivem no mercado e o "+" e o E.164
                          canonico. Trocar e mudar uma linha em FORMATOS.

bruto                     Como veio da fonte: "(48) 99999-9999". E o padrao,
                          porque e o que se le no telefone antes de discar.

O QUE ESTA FUNCAO NAO FAZ
-------------------------
Nao inventa DDD. Numero de 8 ou 9 digitos chega sem DDD, e um DDD chutado
manda a ligacao para outro estado -- pior que nao ter numero. Esses passam
intactos e sem "+55", para ficar visivel que estao incompletos.
"""
import re

# Chaves do catalogo que sao telefone ATOMICO (um numero por celula). Os
# compostos ("Todos os decisores") ficam de fora de proposito: eles carregam
# nome e cargo junto, e reescrever a celula inteira destruiria o texto.
COLUNAS_TELEFONE = (
    "rfb_tel1", "rfb_tel2",
    "as_empresa_tel", "as_empresa_tel2", "as_empresa_whatsapp",
    "de_dec1_celular", "de_dec2_celular", "de_dec3_celular",
    "so_socio1_celular", "so_socio1_whatsapp", "so_socio2_celular",
    "vf_telefone",
)

# Compostos: deles so se EXTRAI numero para a coluna unida.
COLUNAS_COMPOSTAS = ("de_todos", "so_todos_tel")

COLUNA_UNIDA = "tel_unidos"
ROTULO_UNIDA = "Telefones (todos, separados por vírgula)"

# DDDs que existem no Brasil. Serve para decidir se os dois primeiros digitos
# de um numero de 10/11 sao DDD ou pedaco do numero.
DDDS = {
    11, 12, 13, 14, 15, 16, 17, 18, 19, 21, 22, 24, 27, 28, 31, 32, 33, 34,
    35, 37, 38, 41, 42, 43, 44, 45, 46, 47, 48, 49, 51, 53, 54, 55, 61, 62,
    63, 64, 65, 66, 67, 68, 69, 71, 73, 74, 75, 77, 79, 81, 82, 83, 84, 85,
    86, 87, 88, 89, 91, 92, 93, 94, 95, 96, 97, 98, 99,
}


def digitos(valor) -> str:
    return re.sub(r"\D", "", str(valor or ""))


def _e164(num: str) -> str:
    """Numero brasileiro em E.164 ("+5548999999999"), ou "" se nao der.

    Devolver vazio e proposital: quem chama decide se mantem o original. Um
    numero que nao vira E.164 e um numero que a ferramenta de destino vai
    recusar, e e melhor a pessoa ver o numero torto do que uma celula vazia.
    """
    d = digitos(num)
    if not d:
        return ""
    # "0" de operadora na frente ("0 48 9999-9999") nao faz parte do numero.
    d = d.lstrip("0")
    if d.startswith("55") and len(d) in (12, 13) and int(d[2:4] or 0) in DDDS:
        return "+" + d
    if len(d) in (10, 11) and int(d[:2]) in DDDS:
        return "+55" + d
    return ""


def formatar(valor, modo: str = "") -> str:
    """Um numero no formato pedido. Sem modo, devolve como veio."""
    modo = (modo or "").strip().lower()
    if not modo or modo == "bruto":
        return str(valor or "").strip()
    e = _e164(valor)
    if not e:
        # Incompleto: sai como veio, e sem "+55" mentiroso na frente.
        return str(valor or "").strip()
    if modo == "meetime":
        return e
    if modo == "zenvia":
        return e
    return e


def _numeros_do_texto(texto) -> list[str]:
    """Numeros soltos dentro de um texto composto.

    "CARLOS — DIRETOR — 47999812345 | ANA — GERENTE — (47) 3333-4444" devolve
    os dois. Sequencia curta demais para ser telefone fica de fora: CPF, CNPJ
    e ano nao entram na coluna de ligar.
    """
    achados = []
    for pedaco in re.findall(r"[\d][\d\s().\-]{7,}", str(texto or "")):
        d = digitos(pedaco)
        # 14 = CNPJ, 11 com DDD invalido = CPF. O teste de DDD resolve os dois.
        if len(d) in (10, 11) and int(d[:2]) in DDDS:
            achados.append(d)
        elif len(d) in (12, 13) and d.startswith("55") and int(d[2:4] or 0) in DDDS:
            achados.append(d)
    return achados


def unir(linha: dict, modo: str = "") -> str:
    """Todos os telefones da linha numa string so, sem repetir.

    A ordem e a das colunas: empresa, decisores, socios, verificado. Quem abre
    a planilha le da esquerda para a direita, e a coluna unida segue a mesma
    ordem -- o primeiro numero da celula e o mesmo primeiro numero da linha.

    A chave da deduplicacao e o numero em E.164: "(47) 99981-2345" e
    "+5547999812345" sao o mesmo telefone escrito de dois jeitos, e entregar
    os dois faria o SDR ligar duas vezes para a mesma pessoa.
    """
    vistos, saida = set(), []
    para_importar = modo in ("meetime", "zenvia")

    def _junta(bruto, original=None):
        e = _e164(bruto)
        # NUMERO INCOMPLETO NAO ENTRA NA COLUNA DE IMPORTAR.
        #
        # Sem DDD (um "99999999" que veio assim da fonte) a Meetime e a Zenvia
        # recusam a linha inteira -- um numero torto derruba o lead junto. Ele
        # continua visivel na coluna individual, que ninguem importa; aqui,
        # numa coluna cujo unico proposito e ser colada em outro sistema, o
        # lugar dele e fora.
        if para_importar and not e:
            return
        chave = e or digitos(bruto)
        if not chave or chave in vistos:
            return
        vistos.add(chave)
        # No modo bruto vale o texto como a pessoa ve na celula: "(48)
        # 3281-9500" e mais legivel que "4832819500" para quem vai discar.
        saida.append(formatar(original if (not para_importar and original) else bruto,
                              modo))

    for col in COLUNAS_TELEFONE:
        v = str(linha.get(col) or "").strip()
        if not v:
            continue
        # Uma celula pode ter mais de um numero ("47 3333-4444 / 47 99999-8888")
        achados = _numeros_do_texto(v)
        if len(achados) == 1:
            _junta(achados[0], original=v)
        else:
            for n in (achados or [v]):
                _junta(n)

    for col in COLUNAS_COMPOSTAS:
        for n in _numeros_do_texto(linha.get(col)):
            _junta(n)

    # ", " e o separador que a propria Meetime usa em `phonesString` -- medido.
    return ", ".join(x for x in saida if x)


def aplicar(linha: dict, unir_col: bool = False, modo: str = "") -> dict:
    """Formata as colunas de telefone da linha e, se pedido, cria a unida.

    Trabalha sobre uma COPIA das chaves de telefone, nunca sobre o resto da
    linha: as colunas originais da planilha da pessoa nao sao nossas para
    mexer.
    """
    saida = dict(linha)
    if unir_col:
        # Une ANTES de reformatar: assim o "bruto" tambem produz uma coluna
        # unida legivel, e a uniao nao depende da ordem das operacoes.
        saida[COLUNA_UNIDA] = unir(linha, modo)
    if modo and modo != "bruto":
        for col in COLUNAS_TELEFONE:
            if saida.get(col):
                saida[col] = formatar(saida[col], modo)
    return saida
