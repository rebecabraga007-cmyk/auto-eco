# -*- coding: utf-8 -*-
"""O que JA sabemos sobre enriquecer esta empresa. Para nao pagar pelo vazio.

O CASO QUE DEU ORIGEM
---------------------
Na lista SP CAPITAL de 101 linhas, 29 empresas nunca devolveram ninguem --
nem decisor, nem sócio com contato. Mesmo assim cada uma custou o minimo:
a busca da empresa no LinkedIn e a lista de possiveis decisores acontecem
ANTES de se descobrir que nao ha ninguem.

E a lista foi rodada cinco vezes. Aquelas 29 empresas foram consultadas de
novo em cada passada, com o mesmo resultado, ao mesmo preco. Medido: R$ 66,16
dos R$ 120,67 daquela lista -- 55% -- foi pagar de novo pelo que ja se sabia.

O QUE ISTO NAO E
----------------
Nao e cache de dado: o dado (telefone, nome) continua vindo da fonte. E
memoria de RESULTADO: "esta empresa foi consultada em tal dia e nao tinha
ninguem". Serve para a tela poder AVISAR antes de gastar, e para o
complemento poder pular.

E tem validade, por dois motivos opostos e os dois reais: empresa contrata
diretor e passa a ter decisor; empresa fecha e para de ter. Trinta dias e o
intervalo entre as cargas que recebemos da Receita.
"""
import os
import re
import sqlite3
import time

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "memoria_empresa.db")

DIAS_VALIDA = 30

DDL = """
CREATE TABLE IF NOT EXISTS tentativa (
  cnpj        TEXT PRIMARY KEY,
  decisores   INTEGER DEFAULT 0,   -- quantos foram achados
  com_tel     INTEGER DEFAULT 0,   -- quantos tinham telefone
  socios      INTEGER DEFAULT 0,
  fonte       TEXT,                -- linkedin | assertiva | ambas
  cargos      TEXT,                -- o filtro usado: muda o resultado
  custou      REAL DEFAULT 0,
  quando      INTEGER
);
CREATE INDEX IF NOT EXISTS ix_mem_quando ON tentativa(quando);
"""


def _con():
    """Conexao que FECHA -- `with sqlite3.connect()` faz commit, nao fecha.

    Ja derrubou este servico: 1023 descritores vazados, 502 sem erro no log.
    """
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    c = sqlite3.connect(DB, timeout=10)
    c.row_factory = sqlite3.Row
    return c


def _init():
    c = _con()
    try:
        c.executescript(DDL)
        c.commit()
    finally:
        c.close()


_init()


def _cnpj(v) -> str:
    d = re.sub(r"\D", "", str(v or ""))
    return d.zfill(14) if 8 <= len(d) <= 14 else ""


def anotar(cnpj: str, decisores: int = 0, com_tel: int = 0, socios: int = 0,
           fonte: str = "", cargos: str = "", custou: float = 0.0) -> None:
    """Registra o que esta empresa rendeu nesta tentativa."""
    cn = _cnpj(cnpj)
    if not cn:
        return
    c = _con()
    try:
        c.execute(
            "INSERT INTO tentativa (cnpj, decisores, com_tel, socios, fonte,"
            " cargos, custou, quando) VALUES (?,?,?,?,?,?,?,?)"
            " ON CONFLICT(cnpj) DO UPDATE SET"
            "   decisores=excluded.decisores, com_tel=excluded.com_tel,"
            "   socios=excluded.socios, fonte=excluded.fonte,"
            "   cargos=excluded.cargos, custou=excluded.custou,"
            "   quando=excluded.quando",
            (cn, int(decisores or 0), int(com_tel or 0), int(socios or 0),
             fonte or "", cargos or "", float(custou or 0), int(time.time())))
        c.commit()
    finally:
        c.close()


def consultar(cnpjs: list) -> dict:
    """O que sabemos de cada um destes CNPJs. Só o que ainda vale.

    Devolve {cnpj: {decisores, com_tel, socios, dias, vazia}}. `vazia` e o
    que a tela usa: nem decisor, nem socio, nem telefone -- e a empresa que
    nao vale reconsultar.
    """
    limpos = [c for c in (_cnpj(x) for x in (cnpjs or [])) if c]
    if not limpos:
        return {}
    corte = int(time.time()) - DIAS_VALIDA * 86400
    saida = {}
    c = _con()
    try:
        # Em blocos: SQLite tem teto de variaveis por consulta (999 por
        # padrao), e uma planilha de 2.000 linhas estouraria isso com um
        # "too many SQL variables" que parece erro de codigo e e de tamanho.
        for i in range(0, len(limpos), 500):
            fatia = limpos[i:i + 500]
            marcas = ",".join("?" * len(fatia))
            for r in c.execute(
                    "SELECT * FROM tentativa WHERE cnpj IN (%s) AND quando >= ?"
                    % marcas, tuple(fatia) + (corte,)):
                saida[r["cnpj"]] = {
                    "decisores": r["decisores"], "com_tel": r["com_tel"],
                    "socios": r["socios"], "fonte": r["fonte"],
                    "cargos": r["cargos"], "custou": r["custou"],
                    "dias": int((time.time() - (r["quando"] or 0)) / 86400),
                    "vazia": not (r["decisores"] or r["socios"]),
                }
    finally:
        c.close()
    return saida


def resumo_planilha(cnpjs: list) -> dict:
    """O aviso ANTES de rodar: quantas destas linhas já se sabe que são vazias.

    É o "filtrar antes de cobrar" que a Datastone faz com as bandeiras
    `tem_telefone`/`tem_email` na busca. A nossa versão não adivinha o que a
    fonte tem -- ela lembra o que a fonte já respondeu.
    """
    sabido = consultar(cnpjs)
    vazias = [c for c, d in sabido.items() if d["vazia"]]
    com_tel = [c for c, d in sabido.items() if d["com_tel"]]
    return {
        "linhas": len(cnpjs or []),
        "conhecidas": len(sabido),
        "vazias": len(vazias),
        "com_telefone": len(com_tel),
        "cnpjs_vazios": vazias[:200],
        # O que se economiza pulando as vazias. R$ 0,133 e o minimo medido:
        # Bright Data (achar a empresa) + possiveis decisores, que se paga
        # antes de descobrir que nao ha ninguem.
        "economia_brl": round(len(vazias) * 0.133, 2),
    }
