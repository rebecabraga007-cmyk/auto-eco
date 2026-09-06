# -*- coding: utf-8 -*-
"""Cache local dos perfis do LinkedIn que já foram pagos na Bright Data.

POR QUE EXISTE: a Bright Data cobra POR PERFIL ENTREGUE. Buscar "Movida" duas
vezes paga duas vezes pela mesma gente. Aqui todo perfil que chega é guardado, e
a busca olha o cache antes de gastar.

O cache também é consultável por conta própria (`procurar`), então vira uma base
de gente que a operação já comprou — inclusive os ~100 mil perfis do snapshot que
foi baixado inteiro (ver `seed_snapshot.py`).

CHAVE DE DEDUPE = URL do perfil. É o único campo estável: `linkedin_id` falta em
alguns registros e o nome repete.

SOBRE VALIDADE: perfil não é fato imutável — a pessoa troca de emprego. Não
apagamos nada por idade; guardamos `visto_em` e devolvemos junto, para a tela
poder dizer "buscado há 40 dias" e a pessoa decidir se quer pagar por dado novo.
Esconder a idade seria pior que o dado velho.
"""
import os
import re
import sqlite3
import time
from typing import Any

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = (os.environ.get("LINKEDIN_CACHE_PATH")
           or os.path.join(os.environ.get("CNPJ_DB_DIR", _AQUI), "linkedin_cache.db"))

_DDL = """
CREATE TABLE IF NOT EXISTS perfis (
  url          TEXT PRIMARY KEY,
  nome         TEXT,
  cargo        TEXT,
  empresa      TEXT,
  empresa_norm TEXT,
  cidade       TEXT,
  pais         TEXT,
  foto         TEXT,
  formacao     TEXT,
  sobre        TEXT,
  seguidores   INTEGER,
  origem       TEXT,      -- 'api' | 'snapshot'
  visto_em     INTEGER
);
CREATE INDEX IF NOT EXISTS idx_lc_empresa ON perfis(empresa_norm);
CREATE INDEX IF NOT EXISTS idx_lc_pais    ON perfis(pais);

-- Empresas conferidas pelo link: a raspagem também é cobrada.
CREATE TABLE IF NOT EXISTS empresas (
  url          TEXT PRIMARY KEY,
  nome         TEXT,
  company_id   TEXT,
  funcionarios INTEGER,
  setor        TEXT,
  sede         TEXT,
  site         TEXT,
  pais         TEXT,
  visto_em     INTEGER
);

-- Histórico do que já foi pedido, para a tela mostrar "já buscamos isso".
CREATE TABLE IF NOT EXISTS buscas (
  id        INTEGER PRIMARY KEY AUTOINCREMENT,
  empresa   TEXT,
  pais      TEXT,
  cargo     TEXT,
  limite    INTEGER,
  protocolo TEXT,
  achados   INTEGER,
  feita_em  INTEGER
);
CREATE INDEX IF NOT EXISTS idx_lc_buscas ON buscas(empresa, pais, cargo);
"""


def _con():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


def init() -> None:
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = _con()
    con.executescript(_DDL)
    con.commit()
    con.close()


def norm(s: str) -> str:
    """Minúsculo, sem acento e sem pontuação: 'Movida Aluguel de Carros' e
    'movida aluguel de carros.' caem na mesma chave."""
    s = (s or "").lower().strip()
    tabela = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    s = s.translate(tabela)
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def salvar_perfis(pessoas: list[dict[str, Any]], origem: str = "api") -> int:
    """Guarda/atualiza perfis. Retorna quantos entraram novos."""
    if not pessoas:
        return 0
    agora = int(time.time())
    con = _con()
    novos = 0
    for p in pessoas:
        url = (p.get("url") or "").split("?")[0].strip().rstrip("/")
        if not url:
            continue
        ja = con.execute("SELECT 1 FROM perfis WHERE url=?", (url,)).fetchone()
        if not ja:
            novos += 1
        con.execute("""
            INSERT INTO perfis (url,nome,cargo,empresa,empresa_norm,cidade,pais,
                                foto,formacao,sobre,seguidores,origem,visto_em)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              nome=excluded.nome, cargo=excluded.cargo, empresa=excluded.empresa,
              empresa_norm=excluded.empresa_norm, cidade=excluded.cidade,
              pais=excluded.pais, foto=excluded.foto, formacao=excluded.formacao,
              sobre=excluded.sobre, seguidores=excluded.seguidores,
              visto_em=excluded.visto_em
        """, (url, p.get("nome"), p.get("cargo"), p.get("empresa"),
              norm(p.get("empresa") or ""), p.get("cidade"), p.get("pais"),
              p.get("foto"), p.get("formacao"), p.get("sobre"),
              p.get("seguidores"), origem, agora))
    con.commit()
    con.close()
    return novos


def por_empresa(empresa: str, pais: str = "", cargo: str = "",
                limite: int = 200) -> list[dict[str, Any]]:
    """O que já temos guardado dessa empresa. Não gasta nada."""
    alvo = norm(empresa)
    if not alvo:
        return []
    sql = ["SELECT * FROM perfis WHERE empresa_norm LIKE ?"]
    # LIKE com % no fim usa o indice; o alvo vem normalizado dos dois lados.
    args: list[Any] = [alvo + "%"]
    if pais:
        sql.append("AND pais = ?")
        args.append(pais.upper()[:2])
    if cargo:
        sql.append("AND lower(cargo) LIKE ?")
        args.append("%" + (cargo or "").lower() + "%")
    sql.append("ORDER BY (foto IS NULL OR foto='') , visto_em DESC LIMIT ?")
    args.append(int(limite))
    con = _con()
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()
    return [dict(r) for r in linhas]


def procurar(q: str = "", pais: str = "", limite: int = 100) -> list[dict[str, Any]]:
    """Busca livre no que já foi pago — por nome, empresa ou cargo."""
    con = _con()
    termo = "%" + (q or "").strip().lower() + "%"
    sql = ["SELECT * FROM perfis WHERE 1=1"]
    args: list[Any] = []
    if q:
        sql.append("AND (lower(nome) LIKE ? OR empresa_norm LIKE ? OR lower(cargo) LIKE ?)")
        args += [termo, "%" + norm(q) + "%", termo]
    if pais:
        sql.append("AND pais = ?")
        args.append(pais.upper()[:2])
    sql.append("ORDER BY visto_em DESC LIMIT ?")
    args.append(int(limite))
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()
    return [dict(r) for r in linhas]


def empresas_parecidas(q: str, limite: int = 15) -> list[dict[str, Any]]:
    """Empresas que já temos gente, com nome parecido. Grátis e instantâneo.

    Serve para o caso mais comum de frustração: a pessoa digita "movida" e não
    sabe se o LinkedIn escreve "Movida", "Movida Aluguel de Carros" ou
    "Movida Participações". Aqui ela vê as grafias reais e escolhe.
    """
    alvo = norm(q)
    if not alvo:
        return []
    con = _con()
    linhas = con.execute("""
        SELECT empresa, COUNT(*) AS quantos, MAX(visto_em) AS visto_em
          FROM perfis
         WHERE empresa_norm LIKE ? AND COALESCE(empresa,'') <> ''
      GROUP BY empresa_norm
      ORDER BY quantos DESC
         LIMIT ?
    """, ("%" + alvo + "%", int(limite))).fetchall()
    con.close()
    return [dict(r) for r in linhas]


def salvar_empresa(d: dict[str, Any]) -> None:
    url = (d.get("url") or "").strip().rstrip("/")
    if not url:
        return
    con = _con()
    con.execute("""
        INSERT INTO empresas (url,nome,company_id,funcionarios,setor,sede,site,pais,visto_em)
        VALUES (?,?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
          nome=excluded.nome, company_id=excluded.company_id,
          funcionarios=excluded.funcionarios, setor=excluded.setor,
          sede=excluded.sede, site=excluded.site, pais=excluded.pais,
          visto_em=excluded.visto_em
    """, (url, d.get("nome"), d.get("company_id"), d.get("funcionarios_linkedin"),
          d.get("setor"), d.get("sede"), d.get("site"), d.get("pais"),
          int(time.time())))
    con.commit()
    con.close()


def empresa_cacheada(url: str) -> dict[str, Any] | None:
    url = (url or "").strip().rstrip("/")
    if not url:
        return None
    con = _con()
    r = con.execute("SELECT * FROM empresas WHERE url=?", (url,)).fetchone()
    con.close()
    return dict(r) if r else None


def registrar_busca(empresa: str, pais: str, cargo: str, limite: int,
                    protocolo: str, achados: int = 0) -> None:
    con = _con()
    con.execute("""INSERT INTO buscas (empresa,pais,cargo,limite,protocolo,achados,feita_em)
                   VALUES (?,?,?,?,?,?,?)""",
                (empresa, pais, cargo, limite, protocolo, achados, int(time.time())))
    con.commit()
    con.close()


def estatisticas() -> dict[str, Any]:
    con = _con()
    def um(sql, *a):
        r = con.execute(sql, a).fetchone()
        return r[0] if r else 0
    d = {
        "perfis": um("SELECT COUNT(*) FROM perfis"),
        "perfis_br": um("SELECT COUNT(*) FROM perfis WHERE pais='BR'"),
        "da_api": um("SELECT COUNT(*) FROM perfis WHERE origem='api'"),
        "do_snapshot": um("SELECT COUNT(*) FROM perfis WHERE origem='snapshot'"),
        "empresas": um("SELECT COUNT(DISTINCT empresa_norm) FROM perfis WHERE empresa_norm<>''"),
        "empresas_conferidas": um("SELECT COUNT(*) FROM empresas"),
        "buscas": um("SELECT COUNT(*) FROM buscas"),
    }
    con.close()
    return d
