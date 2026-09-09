# -*- coding: utf-8 -*-
"""Consulta a base de empresas do LinkedIn que ja esta no nosso disco.

POR QUE ISTO MUDA TUDO
----------------------
A Datastone parece instantanea e sem custo porque a base dela ja esta unida no
disco deles. Nos perguntavamos ao vivo, e por isso cada filtro de porte
custava dinheiro e obrigava a tela a pedir permissao para gastar -- o que
transforma NAVEGAR em DECIDIR GASTAR, que e a pior coisa que uma tela de
prospeccao pode fazer.

A diferenca nunca foi de tecnologia. Era de MOMENTO do pagamento: eles pagaram
na ingestao, nos pagavamos na consulta. `cnpj_base/build_empresas_li.py` move
o nosso pagamento para o mesmo lugar.

O QUE ESTE MODULO RESPONDE, E O QUE ELE NAO INVENTA
---------------------------------------------------
Ele sabe DE QUE FATIA a base local e completa: a ingestao registra "func>200,
terminou" e so entao a consulta local pode dizer "isto e tudo que existe".
Fora da fatia comprada ele devolve o que tem e AVISA que e parcial -- porque
uma base incompleta que se apresenta como completa e pior que base nenhuma:
a pessoa conclui que nao existe empresa naquele filtro.
"""
import os
import re
import sqlite3
from typing import Any


def _dir_dados() -> str:
    aqui = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("CNPJ_DB_DIR"), r"C:\capiblu_data",
              "/capiblu_data", aqui):
        if d and os.path.exists(os.path.join(d, "empresas_li.db")):
            return d
    return os.environ.get("CNPJ_DB_DIR") or aqui


DB = os.path.join(_dir_dados(), "empresas_li.db")


def disponivel() -> bool:
    return os.path.exists(DB)


def _con():
    return sqlite3.connect("file:%s?mode=ro" % DB, uri=True, timeout=5)


def cobertura() -> dict[str, Any]:
    """De que fatia a base local e COMPLETA.

    `piso` e o menor N tal que a ingestao de "func>N" terminou. Uma busca por
    porte igual ou acima disso pode ser respondida so pelo disco, de graca --
    e ai a tela nao precisa perguntar nada a ninguem.
    """
    if not disponivel():
        return {"tem": False, "piso": None, "empresas": 0}
    try:
        con = _con()
        n = con.execute("SELECT count(*) FROM empresas_li").fetchone()[0]
        piso = None
        for chave, cursor in con.execute("SELECT chave, cursor FROM progresso"):
            m = re.search(r"func>(\d+)", chave or "")
            if not m or cursor:            # cursor cheio = parou no meio
                continue
            v = int(m.group(1))
            piso = v if piso is None else min(piso, v)
        con.close()
    except Exception:
        return {"tem": False, "piso": None, "empresas": 0}
    return {"tem": n > 0, "piso": piso, "empresas": n}


def _linha(r: sqlite3.Row) -> dict[str, Any]:
    return {
        "nome": r["nome"] or "",
        "url": r["url"] or "",
        "company_id": r["company_id"] or "",
        "funcionarios_linkedin": r["funcionarios"],
        "setor": r["setor"] or "",
        "sede": r["sede"] or "",
        "site": r["site"] or "",
        "tipo": r["tipo"] or "",
        "fundada": r["fundada"] or "",
        "seguidores": r["seguidores"],
        "pais": "BR",
        "cnpj": r["cnpj"] or "",
        "cnpj_confianca": r["cnpj_confianca"] or "nenhuma",
        "cnpj_motivo": r["cnpj_motivo"] or "",
    }


def buscar(porte_min: int = 0, tipos: Any = None, fundada_apos: int = 0,
           setores: Any = None, nomes: Any = None, ufs: Any = None,
           so_com_cnpj: bool = False, limite: int = 50,
           offset: int = 0) -> dict[str, Any]:
    """Mesma forma de resposta de `brightdata_pessoas.buscar_empresas_por_filtro`,
    para os dois serem intercambiaveis -- so que esta custa zero.
    """
    if not disponivel():
        return {"status": "unavailable", "empresas": [], "total": 0}

    def _l(v):
        if v is None:
            return []
        if isinstance(v, str):
            v = re.split(r"[;,]", v)
        return [str(x).strip() for x in v if str(x).strip()]

    onde, args = ["1=1"], []
    if int(porte_min or 0) > 0:
        onde.append("funcionarios > ?")
        args.append(int(porte_min))
    for grupo, campo in ((_l(tipos), "tipo"), (_l(ufs), "uf")):
        if grupo:
            onde.append("(%s)" % " OR ".join("%s = ?" % campo for _ in grupo))
            args.extend(grupo)
    for termo in _l(setores):
        onde.append("setor LIKE ?")
        args.append("%" + termo + "%")
    for termo in _l(nomes):
        onde.append("nome LIKE ?")
        args.append("%" + termo + "%")
    if int(fundada_apos or 0) > 0:
        # `fundada` e texto na origem; CAST evita comparar "1998" com 2010 como
        # string, que daria "1998" > "2010" por ordem alfabetica.
        onde.append("CAST(fundada AS INTEGER) > ?")
        args.append(int(fundada_apos))
    if so_com_cnpj:
        onde.append("cnpj <> ''")

    sql = " AND ".join(onde)
    try:
        con = _con()
        con.row_factory = sqlite3.Row
        total = con.execute("SELECT count(*) FROM empresas_li WHERE " + sql,
                            args).fetchone()[0]
        linhas = con.execute(
            "SELECT * FROM empresas_li WHERE " + sql +
            " ORDER BY funcionarios DESC LIMIT ? OFFSET ?",
            args + [max(1, int(limite)), max(0, int(offset))]).fetchall()
        con.close()
    except Exception as exc:
        return {"status": "error", "empresas": [], "total": 0,
                "message": str(exc)[:160]}

    cob = cobertura()
    # COMPLETA so quando o filtro cabe inteiro dentro da fatia ja comprada.
    # Abaixo do piso a base tem parte das empresas, e dizer "e isso que
    # existe" faria a pessoa concluir que o resto nao existe.
    completa = bool(cob["piso"] is not None
                    and int(porte_min or 0) >= int(cob["piso"]))
    return {
        "status": "ok",
        "empresas": [_linha(r) for r in linhas],
        "total": len(linhas),
        "total_no_dataset": total,
        "registros_cobrados": 0,
        "custo_usd": 0.0,
        "fonte": "local",
        "completa": completa,
        "piso_local": cob["piso"],
    }
