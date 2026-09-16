# -*- coding: utf-8 -*-
"""Le os cabecalhos de uma planilha e diz o que cada coluna E.

POR QUE EXISTE
--------------
"Confere se esses telefones sao dessas pessoas" parece simples e nao e: cada
planilha que chega tem outro cabecalho. "Fone movel contato 1", "Celular",
"TEL2", "WhatsApp Empresa", "telemovel". E um nome pode vir em "Nome contato
2", "Socio", "Responsavel" ou so "Nome".

Este arquivo e o equivalente do `columnMapper.js` do BLU LITE, com duas
diferencas deliberadas:

  1. NAO usa IA. O BLU LITE chama um modelo quando o mapeamento deterministico
     falha. Aqui a planilha ja chegou e o operador esta olhando: e melhor
     acertar 90% na hora, de graca, e deixar ele corrigir o resto num seletor,
     do que esperar por uma chamada que pode errar igual e custa dinheiro.

  2. O PAR importa mais que a coluna. O que se quer saber e "este telefone e
     desta pessoa", entao cada coluna de telefone precisa saber QUAL nome da
     linha e o dono candidato. Onde ha numeracao ("Nome contato 2" /
     "Fone movel contato 2") o par e obvio; onde nao ha, vale o unico nome da
     linha.

O CASAMENTO DE NOME E O PONTO DELICADO
--------------------------------------
O BLU LITE compara so o PRIMEIRO nome: `firstNameMatches` da match se
"MARIA" aparece em qualquer nome devolvido. Numa base de telefone reverso isso
confirma quase tudo -- MARIA, JOSE e ANA aparecem em qualquer lista. Aqui a
regra e a mesma do funil de CPF (`funil._nome_contido`): TODO token do nome
procurado tem que estar no nome encontrado, e nome de uma palavra so nao
confirma nada.
"""
import re
import unicodedata

# ---------------------------------------------------------------- normalizar

def _norm(s) -> str:
    """Minusculo, sem acento, sem pontuacao -- para comparar cabecalho."""
    s = unicodedata.normalize("NFD", str(s or "").lower())
    s = "".join(c for c in s if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]+", " ", s).strip()


def digitos(v) -> str:
    return re.sub(r"\D", "", str(v or ""))


# ---------------------------------------------------------------- telefone
# Radicais de cabecalho de telefone. Vieram do BLU LITE (`isPhoneColumnForZenvia`)
# mais o que aparece nas planilhas da Receita e da Meetime.
_TEL_RADICAIS = ("telefone", "telemovel", "celular", "whatsapp", "whats",
                 "fone", "phone", "contato tel", "tel comercial")
_TEL_CURTOS = re.compile(r"^(tel|cel|fone)\s*\d*$")

# Cabecalhos que TEM "tel" no meio e nao sao telefone. Sem esta lista,
# "operadora do telefone" e "tem telefone?" viram coluna para consultar.
_TEL_FALSOS = ("operadora", "tipo de telefone", "tem telefone", "possui telefone",
               "ddd", "status do telefone", "telefonia")

_NOME_RADICAIS = ("nome", "contato", "socio", "responsavel", "titular",
                  "proprietario", "decisor", "cliente", "lead name",
                  "razao social", "representante")
# "Nome fantasia" e "nome da empresa" sao EMPRESA, nao pessoa -- e telefone de
# empresa nao "pertence" a uma pessoa. Confundir os dois faria a coluna dizer
# "pertence" para o nome de uma loja.
_NOME_FALSOS = ("fantasia", "empresa", "company", "razao social", "nome da rua",
                "nome do arquivo", "nome da lista", "nome do usuario")


def _indice(cabecalho_norm: str) -> int:
    """O numero que amarra "Nome contato 2" a "Fone movel contato 2"."""
    achados = re.findall(r"\d+", cabecalho_norm)
    return int(achados[-1]) if achados else 0


def eh_telefone(cabecalho: str) -> bool:
    n = _norm(cabecalho)
    if not n:
        return False
    if any(f in n for f in _TEL_FALSOS):
        return False
    if _TEL_CURTOS.match(n):
        return True
    return any(r in n for r in _TEL_RADICAIS)


def eh_nome(cabecalho: str) -> bool:
    n = _norm(cabecalho)
    if not n:
        return False
    if any(f in n for f in _NOME_FALSOS):
        return False
    # TELEFONE GANHA DE NOME. "Fone movel contato 1" e "Celular do socio"
    # contem "contato" e "socio", mas sao telefone -- quem manda e o objeto da
    # coluna, nao a pessoa a que ela se refere. Sem esta linha, `eh_nome`
    # devolvia True para coluna de telefone e qualquer codigo novo que
    # confiasse nela sozinha (sem a ordem de `mapear`) leria numero como nome.
    if eh_telefone(cabecalho):
        return False
    return any(r in n for r in _NOME_RADICAIS)


def _parece_telefone(valor) -> bool:
    d = digitos(valor)
    return 10 <= len(d) <= 13


def _parece_nome(valor) -> bool:
    t = str(valor or "").strip()
    if len(t) < 5 or digitos(t):
        return False
    return len(t.split()) >= 2


def mapear(colunas: list, linhas: list = None, amostra: int = 40) -> dict:
    """Diz quais colunas sao telefone, quais sao nome, e quem casa com quem.

    O cabecalho decide primeiro; o CONTEUDO desempata. Planilha exportada de
    sistema costuma vir com cabecalho generico ("Campo 3", "Unnamed: 7") ou em
    outro idioma, e nesse caso a unica pista e o que esta nas celulas -- vinte
    linhas de numeros de 11 digitos sao um telefone, com qualquer titulo.
    """
    linhas = linhas or []
    tels, nomes = [], []

    for col in colunas:
        por_titulo_tel = eh_telefone(col)
        por_titulo_nome = eh_nome(col)

        # Le a amostra uma vez so por coluna.
        vals = [l.get(col) for l in linhas[:amostra] if str(l.get(col) or "").strip()]
        n_tel = sum(1 for v in vals if _parece_telefone(v))
        n_nome = sum(1 for v in vals if _parece_nome(v))
        # 60% da amostra: abaixo disso e coincidencia (um CEP de 8 digitos, um
        # codigo de 11). Exigir 100% quebraria na primeira celula vazia ou
        # torta, que toda planilha tem.
        por_dado_tel = bool(vals) and n_tel >= 0.6 * len(vals)
        por_dado_nome = bool(vals) and n_nome >= 0.6 * len(vals)

        if por_titulo_tel or (por_dado_tel and not por_titulo_nome):
            tels.append({"coluna": col, "indice": _indice(_norm(col)),
                         "certeza": "título" if por_titulo_tel else "conteúdo",
                         "amostra": n_tel, "de": len(vals)})
        elif por_titulo_nome or (por_dado_nome and not por_titulo_tel):
            nomes.append({"coluna": col, "indice": _indice(_norm(col)),
                          "certeza": "título" if por_titulo_nome else "conteúdo",
                          "amostra": n_nome, "de": len(vals)})

    # ---- o PAR: de quem e este telefone? -------------------------------
    #
    # Tres regras, da mais forte para a mais fraca:
    #   1. mesmo numero no titulo   "Nome contato 2" <- "Fone movel contato 2"
    #   2. nome sem numero, unico   uma planilha com uma pessoa por linha
    #   3. nenhum                   sobra a verificacao sem dono candidato: a
    #                               coluna nova diz quem e o dono, sem afirmar
    #                               que e a pessoa da linha
    nomes_por_indice = {n["indice"]: n["coluna"] for n in nomes if n["indice"]}
    nome_unico = nomes[0]["coluna"] if len(nomes) == 1 else ""
    if not nome_unico:
        sem_indice = [n["coluna"] for n in nomes if not n["indice"]]
        nome_unico = sem_indice[0] if len(sem_indice) == 1 else ""

    for t in tels:
        t["nome"] = nomes_por_indice.get(t["indice"], "") or nome_unico
        t["par_por"] = ("número no título" if nomes_por_indice.get(t["indice"])
                        else ("única coluna de nome" if t["nome"] else "sem par"))

    tels.sort(key=lambda x: (x["indice"], colunas.index(x["coluna"])))
    return {"telefones": tels, "nomes": nomes,
            "colunas_do_arquivo": list(colunas)}


# ------------------------------------------------------- casamento de nome
_SO_SOBRENOME = {"da", "de", "do", "das", "dos", "e", "jr", "junior", "filho",
                 "neto", "sobrinho", "santo", "santos"}


def nome_casa(procurado: str, achado: str) -> bool:
    """O nome da planilha e o nome que o telefone devolveu sao a mesma pessoa?

    Regra: TODO token do nome procurado precisa estar no encontrado. Mesma do
    funil de CPF, e o motivo e o mesmo -- "Ana Silva" tem que casar com "Ana
    Beatriz Silva", e NAO pode casar com "Ana Silvana".

    Nome de uma palavra so nao confirma: numa base de telefone reverso,
    "MARIA" bate com dezenas de MARIAs diferentes. O BLU LITE aceita esse
    caso (compara so o primeiro nome) e por isso marca como confirmado muita
    coisa que e homonimo.
    """
    a = [t for t in _norm(procurado).split() if len(t) > 1 and t not in _SO_SOBRENOME]
    b = set(t for t in _norm(achado).split() if len(t) > 1)
    if len(a) < 2 or not b:
        return False
    return all(t in b for t in a)


def telefone_para_api(valor) -> str:
    """Numero pronto para o integralX: 10 ou 11 digitos, SEM DDI.

    O BLU LITE manda com "55" na frente porque o gateway dele aceita assim.
    O nosso NAO: medido em 16/set/2026, mandar "5547999812345" devolve
    "Parametro phone deve conter 10 ou 11 digitos" -- e o modulo ainda embrulha
    isso num 403, que o cliente lia como "chave sem acesso". Cinco consultas
    gastas para receber cinco erros que pareciam problema de assinatura.

    Devolve vazio quando nao da para ligar: menos de 10 digitos e ramal,
    codigo interno ou celula truncada, e mandar isso gasta consulta paga para
    receber "invalido".
    """
    d = digitos(valor)
    if d.startswith("55") and len(d) in (12, 13):
        d = d[2:]          # tira o DDI: quem pede 10/11 nao quer o 55
    if len(d) < 10:
        return ""
    return d[:11]


def telefones_da_celula(valor) -> list:
    """Uma celula pode ter varios numeros: quebra em linha, virgula ou barra."""
    bruto = re.split(r"[\n;,/|]+", str(valor or ""))
    saida = []
    for pedaco in bruto:
        tel = telefone_para_api(pedaco)
        if tel and tel not in saida:
            saida.append(tel)
    return saida
