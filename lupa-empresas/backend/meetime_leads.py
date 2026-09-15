# -*- coding: utf-8 -*-
"""A base de leads da Meetime do lado de ca: espelho local, incremental.

POR QUE ESTE ARQUIVO EXISTE, E POR QUE ELE NAO E O `meetime_base`
-----------------------------------------------------------------
`meetime_base` guarda o MINIMO para deduplicar: conta, CNPJ e nome. Serve ao
filtro da aba B2B, que so precisa responder "esta empresa ja esta la?".

A aba de leads pergunta outra coisa: QUEM esta la, EM QUE PE esta, e o que
mudou desde ontem. Isso exige o lead inteiro e, principalmente, a PROSPECCAO
-- porque o status nao mora no lead.

O QUE A API ACEITA (medido em 15/set/2026, conta da BLU, 12.643 leads)
----------------------------------------------------------------------
A documentacao que circula descreve outra API. Conferido contra o servidor:

    Authorization: <token>          200      (com "Bearer" -> 401)
    GET /v2/leads?limit&start       200      limit teto 100 (500 -> 400)
    GET /v2/leads?page|status|created_after|offset|updated_after  -> 400
    GET /v2/prospections?limit&start&lead_id&cadence_id           -> 200
    GET /v2/prospections?status|page                              -> 400
    GET /v2/cadences, /v2/users, /v2/demos, /v2/webhooks          -> 200
    GET /v2/account, /v2/loss-reasons, /v2/custom-fields          -> 404

Ou seja: nao existe "me de o que mudou depois de tal data". A ordem e
crescente e fixa, entao o incremental e por OFFSET -- o que e novo esta no
fim. Se a contagem DIMINUIR, alguem apagou e os offsets nao valem mais: a
base daquele recurso e refeita do zero, porque indice furado em silencio e
pior que uma sincronizacao demorada.

ONDE MORA O STATUS
------------------
No lead nao ha status. Ha em /prospections, uma por lead por cadencia:

    WON, WAITING, PAUSED_FROM_WAITING, SWITCHED_CADENCE, ...

com `lost_reason`, `owner_name`, `cadence` e as datas. O lead traz
`current_prospection_id`, que aponta para a que vale agora. Por isso os dois
recursos sao espelhados: sem prospeccao nao ha status; sem lead nao ha CNPJ.

O TOKEN NAO E GUARDADO
----------------------
A conta e o SHA-256 do token (mesma regra do `meetime_base`). O que fica no
disco sao os dados da base, nunca a credencial.
"""
import os
import sqlite3
import time
from typing import Any

import httpx

import meetime

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "meetime_leads.db")

# 100 e o teto da API (500 -> 400). Paginas por CHAMADA nossa: o primeiro
# espelho sao ~126 paginas de leads e ~190 de prospeccoes, e cada uma leva
# ~1,2s -- juntas passam de seis minutos, muito alem do corte da Cloudflare.
# A tela chama de novo enquanto vier `pendente`.
PAGINA = 100
PAGINAS_POR_CHAMADA = 25

DDL = """
CREATE TABLE IF NOT EXISTS mt_lead (
  conta     TEXT NOT NULL,
  lead_id   TEXT NOT NULL,
  cnpj      TEXT,
  empresa   TEXT,
  contato   TEXT,
  email     TEXT,
  telefone  TEXT,
  cidade    TEXT,
  uf        TEXT,
  criado    TEXT,
  atualizado TEXT,
  prospeccao_id TEXT,
  PRIMARY KEY (conta, lead_id)
);
CREATE INDEX IF NOT EXISTS ix_mtl_cnpj ON mt_lead(conta, cnpj);
CREATE INDEX IF NOT EXISTS ix_mtl_criado ON mt_lead(conta, criado);

CREATE TABLE IF NOT EXISTS mt_prosp (
  conta     TEXT NOT NULL,
  prosp_id  TEXT NOT NULL,
  lead_id   TEXT,
  status    TEXT,
  cadencia  TEXT,
  owner     TEXT,
  criado    TEXT,
  atualizado TEXT,
  motivo    TEXT,
  PRIMARY KEY (conta, prosp_id)
);
CREATE INDEX IF NOT EXISTS ix_mtp_lead ON mt_prosp(conta, lead_id);
CREATE INDEX IF NOT EXISTS ix_mtp_status ON mt_prosp(conta, status);

CREATE TABLE IF NOT EXISTS mt_sync (
  conta   TEXT NOT NULL,
  recurso TEXT NOT NULL,
  offset_fim  INTEGER DEFAULT 0,
  total_visto INTEGER DEFAULT 0,
  quando  INTEGER,
  PRIMARY KEY (conta, recurso)
);
"""

# Como a tela escreve cada status. O ingles cru da API nao diz nada para quem
# vende; e o rotulo aparece em contagem, entao precisa ser curto.
# Os nomes vieram da medicao, nao de um palpite: sao os status que a conta da
# BLU realmente usa, contados nos 12.643 leads espelhados em 15/set/2026 --
# Perdido 9.496, Pausado 1.082, Ganho 931, Executando 385, e a cauda.
ROTULO = {
    "WON": "Ganho",
    "LOST": "Perdido",
    "WAITING": "Em cadência",
    "EXECUTING": "Em execução",
    "ON_EXTRA_ACTIVITY": "Em atividade extra",
    "PAUSED_FROM_WAITING": "Pausado (na fila)",
    "PAUSED_FROM_EXECUTING": "Pausado (em execução)",
    "PAUSED_FROM_EXTRA_ACTIVITY": "Pausado (atividade extra)",
    "SWITCHED_CADENCE": "Trocou de cadência",
    "FINISHED": "Finalizado",
    "": "Sem prospecção",
}


def _con() -> sqlite3.Connection:
    con = sqlite3.connect(DB, timeout=20)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con


def id_da_conta(token: str = "", grupo_id: str = "") -> str:
    """Mesma identidade do `meetime_base`, para as duas bases combinarem."""
    import meetime_base
    return meetime_base.id_da_conta(token, grupo_id)


def rotulo(status: str) -> str:
    return ROTULO.get((status or "").upper(), (status or "").title())


# --------------------------------------------------------------- leitura
def estado(conta: str) -> dict[str, Any]:
    """Onde cada recurso parou, para a tela poder dizer o que falta."""
    fora = {}
    try:
        con = _con()
        for r in con.execute("SELECT * FROM mt_sync WHERE conta=?", (conta,)):
            fora[r["recurso"]] = {"offset": r["offset_fim"],
                                  "total": r["total_visto"],
                                  "quando": r["quando"]}
        fora["leads_locais"] = con.execute(
            "SELECT count(*) FROM mt_lead WHERE conta=?", (conta,)).fetchone()[0]
        fora["prosp_locais"] = con.execute(
            "SELECT count(*) FROM mt_prosp WHERE conta=?", (conta,)).fetchone()[0]
        con.close()
    except Exception:
        pass
    return fora


def resumo(conta: str) -> dict[str, Any]:
    """Contagem por status + o que entrou nos ultimos dias.

    O status vem da prospeccao ATUAL do lead (`prospeccao_id`); lead sem
    prospeccao aparece separado, porque ele existe no CRM e nao esta sendo
    trabalhado -- que e uma informacao de operacao, nao um buraco de dados.
    """
    out = {"total": 0, "por_status": [], "sem_prospeccao": 0, "recentes": 0}
    try:
        con = _con()
        out["total"] = con.execute("SELECT count(*) FROM mt_lead WHERE conta=?",
                                   (conta,)).fetchone()[0]
        linhas = con.execute(
            """SELECT COALESCE(p.status,'') AS s, count(*) AS n
                 FROM mt_lead l
                 LEFT JOIN mt_prosp p
                        ON p.conta = l.conta AND p.prosp_id = l.prospeccao_id
                WHERE l.conta = ?
                GROUP BY s ORDER BY n DESC""", (conta,)).fetchall()
        out["por_status"] = [{"status": r["s"], "rotulo": rotulo(r["s"]),
                              "quantos": r["n"]} for r in linhas]
        out["sem_prospeccao"] = next(
            (r["n"] for r in linhas if not r["s"]), 0)
        corte = time.strftime("%Y-%m-%d", time.gmtime(time.time() - 7 * 86400))
        out["recentes"] = con.execute(
            "SELECT count(*) FROM mt_lead WHERE conta=? AND criado >= ?",
            (conta, corte)).fetchone()[0]
        con.close()
    except Exception:
        pass
    return out


def listar(conta: str, status: str = "", texto: str = "",
           limite: int = 100, offset: int = 0) -> dict[str, Any]:
    """Os leads com o status da prospeccao atual, para a tabela da tela."""
    onde = ["l.conta = ?"]
    params: list[Any] = [conta]
    if status:
        if status == "__sem__":
            onde.append("COALESCE(p.status,'') = ''")
        else:
            onde.append("p.status = ?")
            params.append(status)
    if texto:
        onde.append("(l.empresa LIKE ? OR l.cnpj LIKE ? OR l.email LIKE ? "
                    "OR l.contato LIKE ?)")
        t = "%" + texto.strip() + "%"
        params += [t, t, t, t]
    sql = ("""SELECT l.*, COALESCE(p.status,'') AS status, p.cadencia,
                     p.owner, p.motivo, p.atualizado AS status_em
                FROM mt_lead l
                LEFT JOIN mt_prosp p
                       ON p.conta = l.conta AND p.prosp_id = l.prospeccao_id
               WHERE %s
               ORDER BY l.criado DESC
               LIMIT ? OFFSET ?""" % " AND ".join(onde))
    try:
        con = _con()
        linhas = [dict(r) for r in con.execute(sql, params + [int(limite),
                                                              int(offset)])]
        total = con.execute(
            "SELECT count(*) FROM mt_lead l LEFT JOIN mt_prosp p "
            "ON p.conta=l.conta AND p.prosp_id=l.prospeccao_id WHERE %s"
            % " AND ".join(onde), params).fetchone()[0]
        con.close()
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:160], "leads": []}
    for l in linhas:
        l["rotulo"] = rotulo(l.get("status"))
    return {"status": "ok", "leads": linhas, "total": total}


def conferir(conta: str, cnpjs) -> dict[str, Any]:
    """Quais desses CNPJs ja estao na Meetime. Consulta local, instantanea."""
    alvo = [str(c) for c in (cnpjs or []) if c]
    if not alvo:
        return {"ja_tem": set(), "quantos": 0}
    achados: set[str] = set()
    try:
        con = _con()
        for i in range(0, len(alvo), 400):
            lote = alvo[i:i + 400]
            q = ("SELECT DISTINCT cnpj FROM mt_lead WHERE conta=? AND cnpj IN (%s)"
                 % ",".join("?" * len(lote)))
            for r in con.execute(q, [conta] + lote):
                achados.add(r["cnpj"])
        con.close()
    except Exception:
        pass
    return {"ja_tem": achados, "quantos": len(achados)}


# --------------------------------------------------------------- escrita
def _so_digitos(v) -> str:
    return "".join(c for c in str(v or "") if c.isdigit())


def _cnpj14(v) -> str:
    """CNPJ com os 14 digitos, zero da frente incluido.

    A Meetime devolve o CNPJ como NUMERO, e numero nao tem zero a esquerda:
    medido, "05.561.786/0001-30" chega como 5561786000130, com 13 digitos. O
    indice do CapiBLU e de 14, entao nenhum desses casava -- a conferencia de
    planilha dizia "nova" para empresa que estava la dentro, que e o erro que
    mais custa: leva a prospectar de novo quem ja esta em cadencia.
    """
    d = _so_digitos(v)
    if not d or len(d) > 14:
        return d[:14]
    return d.zfill(14) if len(d) >= 11 else d


def _lead_da_api(rec: dict) -> tuple:
    tel = (rec.get("primaryPhoneString") or rec.get("phonesString")
           or rec.get("foneMovelContato1") or "")
    return (
        str(rec.get("id") or ""),
        _cnpj14(rec.get("cnpj")),
        (rec.get("lead_company") or rec.get("razaoSocial")
         or rec.get("nomeFantasia") or "")[:160],
        (rec.get("lead_name") or rec.get("nomeContato1") or "")[:120],
        (rec.get("lead_email") or rec.get("emailContato1") or "").lower()[:160],
        str(tel)[:120],
        (rec.get("lead_city") or "")[:80],
        (rec.get("lead_state") or "")[:2],
        (rec.get("lead_created_date") or "")[:24],
        (rec.get("lead_updated_date") or "")[:24],
        str(rec.get("current_prospection_id") or ""),
    )


def _prosp_da_api(rec: dict) -> tuple:
    return (
        str(rec.get("id") or ""),
        str(rec.get("lead_id") or ""),
        (rec.get("status") or "")[:40],
        (rec.get("cadence") or "")[:120],
        (rec.get("owner_name") or "")[:80],
        (rec.get("created_date") or "")[:24],
        (rec.get("updated_date") or "")[:24],
        (rec.get("lost_reason") or "")[:120],
    )


async def _pagina(cli: httpx.AsyncClient, url: str, token: str,
                  recurso: str, start: int) -> dict:
    r = await cli.get("%s/%s" % (url, recurso),
                      params={"limit": PAGINA, "start": start},
                      headers={"Accept": "application/json",
                               meetime._auth_header(): token})
    if r.status_code >= 400:
        raise RuntimeError("HTTP %s em %s: %s"
                           % (r.status_code, recurso, r.text[:120]))
    return r.json()


async def sincronizar(token: str, conta: str,
                      paginas: int = PAGINAS_POR_CHAMADA) -> dict[str, Any]:
    """Traz o que e novo desde a ultima vez. Em pedacos, porque e longo.

    Devolve `pendente=True` enquanto faltar -- a tela chama de novo. Fazer
    tudo numa requisicao so morreria no corte de 100s da Cloudflare DEPOIS de
    ja ter lido metade, que e o pior dos dois mundos.
    """
    base = meetime._base_url().rstrip("/")
    if not base.endswith("/v2"):
        base += "/v2"
    feito = {"leads": 0, "prospeccoes": 0}
    pendente = False
    erros = []

    con = _con()
    try:
        async with httpx.AsyncClient(timeout=httpx.Timeout(60.0)) as cli:
            for recurso, tabela in (("leads", "mt_lead"),
                                    ("prospections", "mt_prosp")):
                st = con.execute(
                    "SELECT offset_fim, total_visto FROM mt_sync "
                    "WHERE conta=? AND recurso=?", (conta, recurso)).fetchone()
                inicio = int(st["offset_fim"]) if st else 0
                antes = int(st["total_visto"]) if st else 0

                try:
                    primeira = await _pagina(cli, base, token, recurso, inicio)
                except Exception as exc:
                    erros.append(str(exc)[:160])
                    continue

                # PASSAR DO FIM DA LISTA NAO E A LISTA TER ENCOLHIDO.
                #
                # Medido em 15/set/2026, e este bug apagou o espelho inteiro
                # uma vez antes de ser visto: pedindo `start` igual ao total,
                # a API devolve `{"data": [], "size": 0}` e OMITE
                # `totalItems` -- nao manda zero, nao manda o numero, omite o
                # campo. O codigo lia `totalItems or 0`, concluia que a base
                # havia caido de 12.643 para 0 e disparava a reconstrucao.
                #
                # Ou seja: clicar "Atualizar" estando em dia destruia a base.
                # E o pior tipo de defeito -- acontece justamente no caminho
                # mais comum, e o estrago fica parecido com "ainda nao
                # sincronizou".
                bruto = primeira.get("totalItems")
                total = int(bruto) if str(bruto or "").isdigit() else 0
                itens_primeira = primeira.get("data") or []
                if not itens_primeira and not total:
                    # Em dia: nada novo desde a ultima leitura. Nao mexe em
                    # nada, nem no offset -- ele ja esta certo.
                    continue

                # ENCOLHEU DE VERDADE = ALGUEM APAGOU. So vale quando a API
                # MANDOU um total e ele e menor que o que vimos antes; ai os
                # offsets nao apontam mais para o mesmo lugar e seguir
                # incrementando furaria o indice em silencio.
                if antes and total and total < antes:
                    con.execute("DELETE FROM %s WHERE conta=?" % tabela, (conta,))
                    inicio = 0
                    try:
                        primeira = await _pagina(cli, base, token, recurso, 0)
                    except Exception as exc:
                        erros.append(str(exc)[:160])
                        continue
                    # O total tem que ser RELIDO da pagina nova: mante-lo da
                    # leitura anterior parava a reconstrucao na primeira
                    # pagina (total=0 => "ja acabou").
                    bruto = primeira.get("totalItems")
                    total = int(bruto) if str(bruto or "").isdigit() else 0

                lote = primeira
                for n in range(paginas):
                    itens = lote.get("data") or []
                    if not itens:
                        break
                    if recurso == "leads":
                        con.executemany(
                            "INSERT OR REPLACE INTO mt_lead (conta, lead_id, cnpj,"
                            " empresa, contato, email, telefone, cidade, uf,"
                            " criado, atualizado, prospeccao_id)"
                            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                            [(conta,) + _lead_da_api(x) for x in itens])
                    else:
                        con.executemany(
                            "INSERT OR REPLACE INTO mt_prosp (conta, prosp_id,"
                            " lead_id, status, cadencia, owner, criado,"
                            " atualizado, motivo) VALUES (?,?,?,?,?,?,?,?,?)",
                            [(conta,) + _prosp_da_api(x) for x in itens])
                    feito["leads" if recurso == "leads" else "prospeccoes"] += len(itens)
                    inicio += len(itens)
                    con.execute(
                        """INSERT INTO mt_sync (conta, recurso, offset_fim,
                                                total_visto, quando)
                           VALUES (?,?,?,?,?)
                           ON CONFLICT(conta, recurso) DO UPDATE SET
                             offset_fim=excluded.offset_fim,
                             total_visto=excluded.total_visto,
                             quando=excluded.quando""",
                        (conta, recurso, inicio, total, int(time.time())))
                    con.commit()
                    if inicio >= total:
                        break
                    if n + 1 >= paginas:
                        pendente = True
                        break
                    try:
                        lote = await _pagina(cli, base, token, recurso, inicio)
                    except Exception as exc:
                        erros.append(str(exc)[:160])
                        break
                else:
                    pendente = pendente or inicio < total
                if inicio < total:
                    pendente = True
    finally:
        con.close()

    # PENDENTE SAI DO ESTADO GRAVADO, nao de um flag acumulado no caminho.
    #
    # Um erro de rede no meio fazia o `continue` pular o trecho que liga o
    # flag, e a resposta saia "parcial, pendente=false" com metade das
    # prospeccoes faltando -- a tela pararia de chamar e a base ficaria
    # incompleta parecendo pronta. O disco sabe a verdade: se algum recurso
    # tem offset menor que o total, falta.
    est = estado(conta)
    pendente = pendente or any(
        isinstance(v, dict) and (v.get("offset") or 0) < (v.get("total") or 0)
        for v in est.values())
    saida = {"status": "ok" if not erros else "parcial", "pendente": pendente,
             "trouxe": feito, "estado": est}
    if erros:
        saida["erros"] = erros[:3]
    return saida


def esquecer(conta: str) -> None:
    try:
        con = _con()
        for t in ("mt_lead", "mt_prosp", "mt_sync"):
            con.execute("DELETE FROM %s WHERE conta=?" % t, (conta,))
        con.commit()
        con.close()
    except Exception:
        pass
