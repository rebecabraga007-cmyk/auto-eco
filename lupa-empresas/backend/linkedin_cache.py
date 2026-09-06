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

import cargos

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB_PATH = (os.environ.get("LINKEDIN_CACHE_PATH")
           or os.path.join(os.environ.get("CNPJ_DB_DIR", _AQUI), "linkedin_cache.db"))

_DDL = """
CREATE TABLE IF NOT EXISTS perfis (
  url          TEXT PRIMARY KEY,
  nome         TEXT,
  nome_norm    TEXT,
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
  visto_em     INTEGER,
  -- Classificados na GRAVACAO, nao na consulta: filtrar por departamento em
  -- 100 mil linhas rodando regex a cada busca seria lento sem necessidade.
  departamento TEXT,
  senioridade  TEXT
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
    """Cria/migra o banco. A ORDEM importa: índice de coluna nova só depois do
    ALTER TABLE, senão o script inteiro falha em banco que já existia."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = _con()
    con.executescript(_DDL)                     # 1. tabelas e índices antigos

    # 2. colunas novas — CREATE TABLE IF NOT EXISTS não altera tabela existente
    tem = {r[1] for r in con.execute("PRAGMA table_info(perfis)")}
    for coluna in ("departamento", "senioridade", "nome_norm"):
        if coluna not in tem:
            con.execute("ALTER TABLE perfis ADD COLUMN %s TEXT" % coluna)

    # 3. só agora os índices que dependem delas
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_depto  ON perfis(departamento)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_senior ON perfis(senioridade)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_nome  ON perfis(nome_norm)")
    con.commit()
    con.close()


def norm(s: str) -> str:
    """Minúsculo, sem acento e sem pontuação: 'Movida Aluguel de Carros' e
    'movida aluguel de carros.' caem na mesma chave."""
    s = (s or "").lower().strip()
    tabela = str.maketrans("áàâãäéèêëíìîïóòôõöúùûüçñ", "aaaaaeeeeiiiiooooouuuucn")
    s = s.translate(tabela)
    return re.sub(r"[^a-z0-9 ]+", " ", s).strip()


def _chave_nome(nome: str) -> str:
    return " ".join(norm(nome).split())


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
            INSERT INTO perfis (url,nome,nome_norm,cargo,empresa,empresa_norm,cidade,pais,
                                foto,formacao,sobre,seguidores,origem,visto_em,
                                departamento,senioridade)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              nome=excluded.nome, nome_norm=excluded.nome_norm,
              cargo=excluded.cargo, empresa=excluded.empresa,
              empresa_norm=excluded.empresa_norm, cidade=excluded.cidade,
              pais=excluded.pais, foto=excluded.foto, formacao=excluded.formacao,
              sobre=excluded.sobre, seguidores=excluded.seguidores,
              visto_em=excluded.visto_em, departamento=excluded.departamento,
              senioridade=excluded.senioridade
        """, (url, p.get("nome"), _chave_nome(p.get("nome") or ""),
              p.get("cargo"), p.get("empresa"),
              norm(p.get("empresa") or ""), p.get("cidade"), p.get("pais"),
              p.get("foto"), p.get("formacao"), p.get("sobre"),
              p.get("seguidores"), origem, agora,
              cargos.departamento(p.get("cargo") or ""),
              cargos.senioridade(p.get("cargo") or "")))
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
    # CONTÉM, não começa-com. Tem que casar com o `includes` da Bright Data, que
    # é o que trouxe esses perfis: buscar "Klabin" lá traz "Grupo Klabin", e com
    # prefixo essa pessoa escapava da checagem de cache e seria comprada de novo.
    # Custa varredura em vez de índice, mas são milhares de linhas, não milhões.
    args: list[Any] = ["%" + alvo + "%"]
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


def procurar(q: str = "", pais: str = "", limite: int = 100,
             departamento: str = "", senioridade: str = "",
             empresa: str = "") -> list[dict[str, Any]]:
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
    if departamento:
        sql.append("AND departamento = ?")
        args.append(departamento)
    if senioridade:
        sql.append("AND senioridade = ?")
        args.append(senioridade)
    if empresa:
        sql.append("AND empresa_norm LIKE ?")
        args.append("%" + norm(empresa) + "%")
    sql.append("ORDER BY visto_em DESC LIMIT ?")
    args.append(int(limite))
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()
    return [dict(r) for r in linhas]


def cruzar(pessoas: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    """Acha, no cache do LinkedIn, quem são as pessoas de uma lista da Receita.

    Recebe [{nome, empresa}] e devolve {nome_normalizado: {perfil..., forca}}.

    DUAS FORÇAS, e a distinção importa:
      "nome+empresa" — o nome bate E a empresa também. Confiável.
      "so nome"      — só o nome bate. Homônimo é comum no Brasil, então isto é
                       pista, não conclusão; a tela mostra em cinza.

    Não inventa correspondência por semelhança: ou o nome normalizado é igual, ou
    não casa. Casar "João Silva" com "João da Silva Santos" produziria telefone
    de estranho no funil de vendas, que é pior que não achar ninguém.
    """
    if not pessoas:
        return {}
    alvos = {}
    for p in pessoas:
        k = _chave_nome(p.get("nome") or "")
        if k:
            alvos.setdefault(k, set()).add(norm(p.get("empresa") or ""))
    if not alvos:
        return {}

    con = _con()
    saida: dict[str, dict[str, Any]] = {}
    # Uma consulta por lote de nomes: 200 consultas separadas seriam lentas à toa.
    nomes = list(alvos)
    for i in range(0, len(nomes), 400):
        pedaco = nomes[i:i + 400]
        marcas = ",".join("?" * len(pedaco))
        linhas = con.execute(
            "SELECT * FROM perfis WHERE nome_norm IN (%s)" % marcas, pedaco
        ).fetchall()
        for r in linhas:
            d = dict(r)
            k = _chave_nome(d.get("nome") or "")
            if k not in alvos:
                continue
            emp_perfil = norm(d.get("empresa") or "")
            forte = any(e and emp_perfil and (e in emp_perfil or emp_perfil in e)
                        for e in alvos[k])
            d["forca"] = "nome+empresa" if forte else "so nome"
            # Match forte sobrescreve fraco já guardado para o mesmo nome.
            if k not in saida or (forte and saida[k].get("forca") != "nome+empresa"):
                saida[k] = d
    con.close()
    return saida


def contagem_por_classificacao() -> dict[str, dict[str, int]]:
    """Quantos perfis em cada departamento e senioridade.

    A tela usa isto para mostrar o número ao lado de cada opção — oferecer um
    filtro que não tem ninguém atrás faz a pessoa clicar e achar que quebrou.
    """
    con = _con()
    saida: dict[str, dict[str, int]] = {}
    for campo in ("departamento", "senioridade"):
        saida[campo] = {
            (k or "(sem)"): n
            for k, n in con.execute(
                "SELECT %s, COUNT(*) FROM perfis GROUP BY 1" % campo)
        }
    con.close()
    return saida


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
