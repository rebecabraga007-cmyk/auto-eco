# -*- coding: utf-8 -*-
"""Indice `dominio do e-mail -> CNPJ`, construido a partir da Receita.

POR QUE EXISTE
--------------
A Bright Data descreve a empresa (nome, sede, funcionarios, site) mas NAO tem
CNPJ. Do lado brasileiro, o unico campo da Receita que casa com algo que o
LinkedIn publica e o e-mail: o dominio de `estabelecimentos.email` costuma ser
o mesmo dominio do site. E uma chave LITERAL -- nao e semelhanca de nome, nao
depende de fuzzy, nao confunde "Senior Sistemas" com "Senior Engenheiros".

O problema e que `email` nao tem indice e a tabela tem 71,8 milhoes de linhas:
cada `LIKE '%@dominio'` varre tudo (dezenas de segundos). Uma ponte que demora
um minuto por empresa nao serve para uma lista de 100. Dai este arquivo.

O QUE ELE DESCARTA, E POR QUE
-----------------------------
Dominio de provedor gratuito (gmail, hotmail...) nao identifica empresa
nenhuma -- 8 dos 8 primeiros e-mails da base sao @gmail.com, de MEIs. Pior:
um dominio de contabilidade aparece em centenas de CNPJs de clientes
diferentes.

Duas tentativas de corte falharam antes da que ficou, e as duas erraram do
mesmo jeito -- cortando empresa boa junto com contador:

  v1, por QUANTIDADE de CNPJs (>500): apagou `gerdau.com.br` e
  `magazineluiza.com.br`, que tem centenas de filiais. Filial nao e
  ambiguidade.

  v2, por RAIZES DISTINTAS (>20): apagou os mesmos. Medido: Magalu tem 53
  raizes no proprio dominio, Gerdau 76, Banrisul 58 -- Luizacred, Luizaseg,
  Luizalabs, as adquiridas. Grupo grande tem muitas raizes, igual contador.

O que separa os dois nao e contagem, e CONCENTRACAO: no dominio da Magalu uma
raiz responde por quase todas as linhas; no do contador cada cliente tem uma
ou duas e ninguem concentra. Essa decisao mora na consulta (`empresa_cnpj`),
que ve o nome da empresa e pode julgar caso a caso. Aqui o TETO_RAIZES so
descarta o extremo, onde nem concentracao resolveria.

Uso:
    python build_dominios.py            # constroi/reconstroi
    python build_dominios.py --amostra  # so estima, nao escreve
"""
import os
import sqlite3
import sys
import time

DATA = os.environ.get("CNPJ_DB_DIR", "/capiblu_data")
ORIGEM = os.path.join(DATA, "cnpj.db")
DESTINO = os.path.join(DATA, "dominios.db")

# Teto FROUXO de proposito. A segunda versao usava 20 e cortou Magalu (53
# raizes), Gerdau (76) e Banrisul (58): grupo grande tem muitas raizes mesmo
# -- Luizacred, Luizaseg, Luizalabs, as adquiridas. Contar raiz nao separa
# grupo de contador.
#
# Quem separa e a DOMINANCIA, e ela e decidida na consulta (empresa_cnpj):
# no dominio da Magalu uma raiz concentra quase todas as linhas; no do
# contador nenhuma concentra. Aqui o corte so tira o caso extremo, onde nem
# dominancia salva.
TETO_RAIZES = 300

GRATUITOS = {
    "gmail.com", "hotmail.com", "outlook.com", "outlook.com.br", "yahoo.com",
    "yahoo.com.br", "bol.com.br", "uol.com.br", "terra.com.br", "ig.com.br",
    "globo.com", "live.com", "msn.com", "icloud.com", "me.com", "aol.com",
    "zipmail.com.br", "oi.com.br", "r7.com", "superig.com.br", "click21.com.br",
    "pop.com.br", "brturbo.com.br", "veloxmail.com.br", "yahoo.com.ar",
    "protonmail.com", "gmail.com.br", "hotmail.com.br", "gmail.co",
}


def _sql_dominio(col: str = "email") -> str:
    """Dominio em minusculas, sem espaco. Vazio quando o campo nao e e-mail."""
    return ("lower(trim(substr(%s, instr(%s, '@') + 1)))" % (col, col))


def construir(amostra: bool = False) -> None:
    if not os.path.exists(ORIGEM):
        print("nao achei %s" % ORIGEM)
        return
    t0 = time.time()
    con = sqlite3.connect(DESTINO)
    con.execute("PRAGMA journal_mode=OFF")
    con.execute("PRAGMA synchronous=OFF")
    con.execute("ATTACH DATABASE ? AS rfb", ("file:%s?mode=ro" % ORIGEM,))
    # A tabela ANTIGA sai aqui, no comeco, e nao no fim. Ela leva junto o
    # indice `ix_dom`, e enquanto ela existir o indice novo colide com o
    # velho no passo 2 -- o build morre depois de 90s de trabalho.
    # Consequencia aceita: durante o rebuild (~2 min) a consulta por dominio
    # fica sem base e `empresa_cnpj` cai no caminho por nome.
    con.execute("DROP TABLE IF EXISTS dominio_cnpj")
    con.execute("DROP TABLE IF EXISTS bruto")
    con.execute("""CREATE TABLE bruto(
                     dominio TEXT, cnpj TEXT, raiz TEXT, matriz INT,
                     uf TEXT, situacao TEXT, fantasia TEXT)""")

    limite = " LIMIT 2000000" if amostra else ""
    d = _sql_dominio("email")
    print("passo 1/5  extraindo dominios%s..." % (" (amostra)" if amostra else ""))
    con.execute("""INSERT INTO bruto
                   SELECT %s, cnpj, cnpj_basico, matriz_filial, uf, situacao,
                          nome_fantasia
                     FROM rfb.estabelecimentos
                    WHERE email LIKE '%%@%%.%%'%s""" % (d, limite))
    con.commit()
    n = con.execute("SELECT count(*) FROM bruto").fetchone()[0]
    print("           %d linhas com e-mail  (%.0fs)" % (n, time.time() - t0))

    # O INDICE VEM ANTES DOS CORTES, e nao depois. Na primeira versao ele
    # vinha no fim e cada DELETE varria as 50 milhoes de linhas -- 30
    # provedores, 30 varreduras. Indexar primeiro custa uma passada e torna
    # todos os cortes seguintes busca por chave.
    print("passo 2/5  indexando o dominio...")
    con.execute("CREATE INDEX ix_dom ON bruto(dominio)")
    con.commit()

    print("passo 3/5  cortando provedores conhecidos...")
    lista = ",".join("?" * len(GRATUITOS))
    con.execute("DELETE FROM bruto WHERE dominio IN (%s)" % lista,
                sorted(GRATUITOS))
    con.commit()
    n2 = con.execute("SELECT count(*) FROM bruto").fetchone()[0]
    print("           -%d (%.0f%% eram provedor gratuito)"
          % (n - n2, 100.0 * (n - n2) / max(n, 1)))

    print("passo 4/5  cortando dominios com mais de %d raizes..." % TETO_RAIZES)
    con.execute("DROP TABLE IF EXISTS ruins")
    con.execute("""CREATE TABLE ruins AS
                   SELECT dominio FROM bruto GROUP BY dominio
                    HAVING count(DISTINCT raiz) > %d""" % TETO_RAIZES)
    con.execute("CREATE INDEX ix_ruins ON ruins(dominio)")
    quantos = con.execute("SELECT count(*) FROM ruins").fetchone()[0]
    con.execute("DELETE FROM bruto WHERE dominio IN (SELECT dominio FROM ruins)")
    con.execute("DROP TABLE ruins")
    con.commit()
    n3 = con.execute("SELECT count(*) FROM bruto").fetchone()[0]
    print("           %d dominios de contador/provedor, -%d linhas"
          % (quantos, n2 - n3))

    print("passo 5/5  fechando...")
    con.execute("ALTER TABLE bruto RENAME TO dominio_cnpj")
    con.commit()
    # `ANALYZE` puro tenta escrever tambem no banco ANEXADO, que esta em modo
    # leitura -- e ai perde o trabalho todo no ultimo passo. `ANALYZE main`
    # olha so o nosso.
    con.execute("DETACH DATABASE rfb")
    con.execute("ANALYZE main")
    con.commit()

    # A conta que importa e por RAIZ. Um dominio com 900 linhas e uma raiz so
    # resolve sozinho -- e o caso da Magalu, nao um caso ambiguo.
    dist = con.execute("""SELECT
            sum(case when r = 1 then 1 else 0 end),
            sum(case when r between 2 and 5 then 1 else 0 end),
            sum(case when r > 5 then 1 else 0 end), count(*)
          FROM (SELECT dominio, count(DISTINCT raiz) r
                  FROM dominio_cnpj GROUP BY dominio)""").fetchone()
    print()
    print("  linhas ................... %d" % n3)
    print("  dominios distintos ....... %d" % (dist[3] or 0))
    print("    -- 1 empresa so ........ %d (%.0f%%)"
          % (dist[0] or 0, 100.0 * (dist[0] or 0) / max(dist[3] or 1, 1)))
    print("    -- 2 a 5 empresas ...... %d" % (dist[1] or 0))
    print("    -- mais de 5 ........... %d" % (dist[2] or 0))
    print("  arquivo .................. %.2f GB" % (os.path.getsize(DESTINO) / 1e9))
    print("  tempo .................... %.0fs" % (time.time() - t0))
    con.close()


if __name__ == "__main__":
    construir(amostra="--amostra" in sys.argv)
