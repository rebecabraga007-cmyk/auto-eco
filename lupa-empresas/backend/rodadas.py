# -*- coding: utf-8 -*-
"""Faz a MESMA busca devolver empresas diferentes a cada vez.

O PEDIDO E O QUE ELE REALMENTE QUER DIZER
-----------------------------------------
"Buscar 'alimentos' duas vezes tem que dar resultados diferentes." O objetivo
por tras disso e nao gastar a lista: quem prospecta roda o mesmo filtro varias
vezes por semana e nao quer reencontrar as mesmas cinquenta empresas.

Ha duas maneiras de fazer isso e elas nao sao equivalentes.

A ERRADA e embaralhar (`ORDER BY RANDOM()`). Aleatorio REPETE -- e a partir da
segunda ou terceira rodada ele repete bastante, porque nao lembra do que ja
mostrou. Alem disso, num universo de 68 milhoes de estabelecimentos, `ORDER BY
RANDOM()` obriga a varrer e ordenar tudo antes de escolher.

A CERTA e AVANCAR: lembrar onde a rodada anterior parou e continuar dali. Isso
garante empresa inedita, custa o mesmo que a busca normal, e ao chegar no fim
da lista volta ao comeco -- ai sim, tendo esgotado o universo do filtro.

E VALE DINHEIRO NA BRIGHT DATA
------------------------------
Do lado pago a diferenca deixa de ser so de qualidade. "Puxar de novo" sem
cursor devolve exatamente os mesmos primeiros N registros E COBRA POR ELES DE
NOVO: o pedido de "trazer empresas novas" produziria o oposto, pagando duas
vezes pelas mesmas. Com `search_after` guardado, cada rodada continua de onde
a anterior parou -- empresa nova de verdade, e nada pago duas vezes.

A chave e o FILTRO, nao a sessao: dois operadores com o mesmo filtro estao
procurando a mesma coisa, e faz sentido que o segundo continue de onde o
primeiro parou em vez de repetir o trabalho ja pago.
"""
import hashlib
import json
import os
import sqlite3
import time
from typing import Any

DB = os.path.join(os.environ.get("CNPJ_DB_DIR", "/capiblu_data"), "rodadas.db")

DDL = """
CREATE TABLE IF NOT EXISTS rodadas (
  chave      TEXT PRIMARY KEY,
  offset_bd  INTEGER DEFAULT 0,   -- quantas ja foram mostradas da base local
  cursor     TEXT,                -- search_after da Bright Data
  rodada     INTEGER DEFAULT 0,
  atualizado INTEGER
);
"""

# Campos que NAO identificam a busca: mexer neles nao e "outra pesquisa", e a
# mesma pesquisa pedida de outro jeito. Se entrassem na chave, mudar o limite
# de 25 para 26 zeraria a rotacao e a pessoa reveria tudo de novo.
IGNORAR = {"limite", "limite_linkedin", "offset", "enriquecer_ate",
           "usuario", "pais", "so_com_cnpj", "linkedin"}


def _con():
    con = sqlite3.connect(DB, timeout=5)
    con.executescript(DDL)
    return con


def chave(filtros: dict[str, Any]) -> str:
    """Identidade da BUSCA, estavel entre chamadas.

    Normaliza antes de somar: lista em ordem diferente e o mesmo filtro, e
    valor vazio e o mesmo que ausente. Sem isso, marcar UF na ordem SC,PR
    numa vez e PR,SC na outra criaria duas rodadas independentes e a pessoa
    veria repetido.
    """
    limpo = {}
    for k, v in sorted((filtros or {}).items()):
        if k in IGNORAR or v in (None, "", [], False, 0):
            continue
        if isinstance(v, (list, tuple, set)):
            v = sorted(str(x) for x in v)
        limpo[k] = v
    crua = json.dumps(limpo, sort_keys=True, ensure_ascii=False)
    return hashlib.sha256(crua.encode("utf-8")).hexdigest()[:20]


def ler(filtros: dict[str, Any]) -> dict[str, Any]:
    try:
        con = _con()
        r = con.execute("SELECT offset_bd, cursor, rodada FROM rodadas "
                        "WHERE chave=?", (chave(filtros),)).fetchone()
        con.close()
    except Exception:
        return {"offset": 0, "cursor": None, "rodada": 0}
    if not r:
        return {"offset": 0, "cursor": None, "rodada": 0}
    return {"offset": r[0] or 0,
            "cursor": json.loads(r[1]) if r[1] else None,
            "rodada": r[2] or 0}


def avancar(filtros: dict[str, Any], quantos: int, cursor: Any = None,
            acabou: bool = False) -> None:
    """Guarda onde esta rodada parou.

    `acabou` fecha o ciclo e volta ao inicio. Sem isso a busca comecaria a
    devolver vazio depois de algumas rodadas, e "esgotei o universo do filtro"
    parece "quebrou".

    O SINAL DE FIM E A PAGINA CURTA, nao o campo `total`. Medido: quando ha
    filtro de texto, `cnpj_lookup.search` devolve em `total` o tamanho da
    PAGINA, nao do universo -- entao comparar offset com total dava "acabou"
    na primeira rodada e zerava tudo, e a busca repetia as mesmas tres
    empresas indefinidamente parecendo que a rotacao nem existia.

    Pagina mais curta que o pedido so acontece no fim da lista. Esse sinal
    nao depende de nenhuma fonte concordar sobre o que "total" significa.
    """
    k = chave(filtros)
    atual = ler(filtros)
    novo = 0 if acabou else atual["offset"] + max(0, int(quantos))
    try:
        con = _con()
        con.execute(
            """INSERT INTO rodadas (chave, offset_bd, cursor, rodada, atualizado)
               VALUES (?,?,?,?,?)
               ON CONFLICT(chave) DO UPDATE SET
                 offset_bd=excluded.offset_bd,
                 -- cursor vazio NAO apaga o guardado: uma rodada que veio da
                 -- base local nao sabe nada sobre a paginacao da Bright Data,
                 -- e zera-lo faria a proxima compra recomecar (e recobrar).
                 cursor=COALESCE(excluded.cursor, rodadas.cursor),
                 rodada=excluded.rodada, atualizado=excluded.atualizado""",
            (k, novo, json.dumps(cursor) if cursor else None,
             atual["rodada"] + 1, int(time.time())))
        con.commit()
        con.close()
    except Exception:
        pass


def zerar(filtros: dict[str, Any]) -> None:
    """Recomeca do zero. Serve para o botao "ver desde o inicio"."""
    try:
        con = _con()
        con.execute("DELETE FROM rodadas WHERE chave=?", (chave(filtros),))
        con.commit()
        con.close()
    except Exception:
        pass
