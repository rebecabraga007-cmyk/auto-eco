"""Consulta na base local de CNPJ (Dados Abertos RFB, ingerida por ingest_cnpj.py).

Substitui a busca da Casa dos Dados (sem cap de 20) e o fetch da BrasilAPI na
montagem de listas — tudo local, sem chamada externa.

Funções:
- ready(): base disponível e populada.
- search(filtros, limite, offset): busca filtrada estilo Datastone.
- by_cnpj(cnpj): dados completos de uma empresa (+ sócios), com descrições.
"""

import os
import re
import sqlite3
import time
from urllib.request import pathname2url


def _ro_uri(p: str) -> str:
    return "file:" + pathname2url(os.path.abspath(p)) + "?mode=ro"

# Localização das bases: fora do OneDrive (C:\capiblu_data) pra não sofrer com a
# sincronização/contenção de disco. Auto-detecta; cai no cnpj_base se não achar.
def _data_dir() -> str:
    here = os.path.dirname(os.path.abspath(__file__))
    for d in (os.environ.get("CNPJ_DB_DIR"), r"C:\capiblu_data", here):
        if d and os.path.exists(os.path.join(d, "cnpj.db")):
            return d
    return here


_DATA_DIR = _data_dir()
DB_PATH = os.path.join(_DATA_DIR, "cnpj.db")
FTS_PATH = os.path.join(_DATA_DIR, "cnpj_fts.db")


_fts_ok = False


def _fts_ready() -> bool:
    """True só quando o FTS com localização (tabela estab_fts) está pronto.

    Verifica a TABELA, não só o arquivo — durante o rebuild o arquivo antigo pode
    existir sem estab_fts. Ao concluir, chaveia sozinho (sem reiniciar o backend).
    """
    global _fts_ok
    if _fts_ok:
        return True
    if not os.path.exists(FTS_PATH):
        return False
    try:
        c = sqlite3.connect(_ro_uri(FTS_PATH), uri=True, timeout=2)
        r = c.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='estab_fts'").fetchone()
        c.close()
        _fts_ok = r is not None
        return _fts_ok
    except Exception:
        return False


def _fts_text_expr(texto: str, escopo) -> str:
    """Parte textual do MATCH: tokens (prefixo/radical) restritos às colunas do escopo."""
    toks = [t for t in re.findall(r"[0-9a-zA-Zçãáàâéêíóôõúü]+", (texto or "").lower()) if len(t) >= 2]
    if not toks:
        return ""
    cols = [c for c in ("razao", "fantasia") if c in (escopo or ["razao", "fantasia"])] or ["razao", "fantasia"]
    body = " ".join(f'"{t}"*' for t in toks)  # AND implícito entre tokens
    return "{%s} : (%s)" % (" ".join(cols), body)


def _fts_col_or(col: str, valores) -> str:
    """Filtro de coluna do FTS: (col:v1 OR col:v2). Valores viram tokens simples."""
    vals = [re.sub(r"[^0-9a-z]", "", str(v).lower()) for v in valores if str(v).strip()]
    vals = [v for v in vals if v]
    if not vals:
        return ""
    if len(vals) == 1:
        return f"{col}:{vals[0]}"
    return "(" + " OR ".join(f"{col}:{v}" for v in vals) + ")"

SITUACAO = {"NULA": "01", "ATIVA": "02", "SUSPENSA": "03", "INAPTA": "04", "BAIXADA": "08"}
SITUACAO_REV = {v: k for k, v in SITUACAO.items()}
PORTE = {"00": "NÃO INFORMADO", "01": "MICRO EMPRESA (ME)",
         "03": "EMPRESA DE PEQUENO PORTE (EPP)", "05": "DEMAIS"}

_codes: dict[str, dict[str, str]] = {}


def _conn() -> sqlite3.Connection:
    # timeout curto: durante a ingestão (--full) o DB fica travado; falhar rápido
    # faz o app cair no fallback (Casa dos Dados/BrasilAPI) em vez de pendurar.
    con = sqlite3.connect(_ro_uri(DB_PATH), uri=True, timeout=3)
    con.row_factory = sqlite3.Row
    if _fts_ready():
        try:
            con.execute("ATTACH DATABASE ? AS ftsx", (_ro_uri(FTS_PATH),))
        except Exception:
            pass
    return con


def available() -> bool:
    return os.path.exists(DB_PATH)


def ready() -> bool:
    """True só quando a base terminou de carregar E indexar.

    Durante o rebuild (--full) os índices ficam dropados; sem eles a busca seria
    parcial e lentíssima. Exigir o índice garante que o app use o fallback
    (Casa dos Dados) até a ingestão concluir e recriar os índices.
    """
    if not os.path.exists(DB_PATH):
        return False
    try:
        with _conn() as con:
            r = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='index' AND name='ix_est_cnae_uf'"
            ).fetchone()
            return r is not None
    except Exception:
        return False


def _load_codes(tipo: str) -> dict[str, str]:
    if _codes.get(tipo):
        return _codes[tipo]
    try:
        with _conn() as con:
            rows = con.execute("SELECT codigo,descricao FROM lookup WHERE tipo=?", (tipo,)).fetchall()
        d = {r["codigo"]: r["descricao"] for r in rows}
    except Exception:
        d = {}
    if d:  # não cacheia vazio (durante rebuild a tabela pode ainda não ter chegado)
        _codes[tipo] = d
    return d


def _desc(tipo: str, codigo: str) -> str:
    return _load_codes(tipo).get(str(codigo or ""), "")


def _fmt_cnpj(d: str) -> str:
    d = re.sub(r"\D", "", d or "")
    if len(d) != 14:
        return d
    return f"{d[0:2]}.{d[2:5]}.{d[5:8]}/{d[8:12]}-{d[12:14]}"


def _municipio_codes(nome: str) -> list[str]:
    """Resolve município -> códigos RFB. Aceita CÓDIGO (dígitos) ou NOME (homônimos)."""
    s = (nome or "").strip()
    if not s:
        return []
    if s.isdigit():          # já veio o código (do combo)
        return [s]
    up = s.upper()
    codes = _load_codes("municipio")
    return [c for c, d in codes.items() if (d or "").upper() == up] or \
           [c for c, d in codes.items() if up in (d or "").upper()]


def _codes_by_desc(tipo: str, termo: str, limit: int = 80) -> list[str]:
    """Códigos cuja descrição contém o termo (para busca por nome de CNAE/natureza)."""
    termo = (termo or "").strip().upper()
    if not termo:
        return []
    out = [c for c, d in _load_codes(tipo).items() if termo in (d or "").upper()]
    return out[:limit]


_municipio_uf: dict[str, str] = {}


def _municipio_uf_map() -> dict[str, str]:
    """Mapa código_município -> UF, derivado de estabelecimentos (não vem na
    tabela de apoio da Receita, que só tem código+nome, sem UF).

    Usa o índice (uf, municipio): 27 buscas por UF (uma pra cada), ~3s no total,
    bem mais rápido que um GROUP BY sem esse índice. Cacheado em memória.
    """
    global _municipio_uf
    if _municipio_uf:
        return _municipio_uf
    ufs = ["AC", "AL", "AP", "AM", "BA", "CE", "DF", "ES", "GO", "MA", "MT", "MS",
           "MG", "PA", "PB", "PR", "PE", "PI", "RJ", "RN", "RS", "RO", "RR", "SC",
           "SP", "SE", "TO"]
    mapa: dict[str, str] = {}
    try:
        with _conn() as con:
            for uf in ufs:
                for r in con.execute(
                    "SELECT DISTINCT municipio FROM estabelecimentos WHERE uf=?", (uf,)
                ):
                    mapa.setdefault(r[0], uf)
    except Exception:
        return {}
    if mapa:
        _municipio_uf = mapa
    return mapa


def list_lookup(tipo: str) -> list[dict]:
    """Lista [{codigo, descricao}] de uma tabela de apoio, ordenada por descrição.

    Para tipo='municipio', inclui também 'uf' (derivada de estabelecimentos —
    a tabela de apoio da Receita não tem UF, só código+nome; sem ela municípios
    homônimos de estados diferentes ficam indistinguíveis no combobox).

    Lê direto a tabela `lookup` — funciona mesmo durante o rebuild (não exige
    ready()), pois as tabelas de apoio são ingeridas primeiro.
    """
    if not os.path.exists(DB_PATH):
        return []
    try:
        codes = _load_codes(tipo)
        if tipo == "municipio":
            ufmap = _municipio_uf_map()
            itens = [{"codigo": c, "descricao": d, "uf": ufmap.get(c, "")} for c, d in codes.items()]
        else:
            itens = [{"codigo": c, "descricao": d} for c, d in codes.items()]
        return sorted(itens, key=lambda x: x["descricao"] or "")
    except Exception:
        return []


def _as_list(v):
    if v is None:
        return []
    if isinstance(v, list):
        return [str(x).strip() for x in v if str(x).strip()]
    return [s.strip() for s in str(v).split(",") if s.strip()]


def _build_where(f: dict, skip_texto: bool = False):
    where, params = [], []

    cnaes = _as_list(f.get("cnae"))
    if cnaes:
        where.append("e.cnae_principal IN (%s)" % ",".join("?" * len(cnaes)))
        params += cnaes

    # "Setor": campo de texto livre (estilo Datastone) — casa pela DESCRIÇÃO do CNAE,
    # mais amplo que escolher um código específico no combo de Atividade.
    setor = (f.get("setor") or "").strip()
    if setor:
        codes = _codes_by_desc("cnae", setor, limit=300)
        where.append("e.cnae_principal IN (%s)" % ",".join("?" * len(codes)) if codes else "1=0")
        params += codes

    # "Fundada": data de abertura da empresa (dado real da Receita).
    fde = re.sub(r"\D", "", f.get("fundada_de") or "")
    fate = re.sub(r"\D", "", f.get("fundada_ate") or "")
    if fde:
        where.append("e.data_inicio >= ?"); params.append(fde)
    if fate:
        where.append("e.data_inicio <= ?"); params.append(fate)

    # "Tipo empresa": público (natureza 1xxx) vs privado — aproximação real via
    # o código de natureza jurídica (não temos "tipo de trabalho" tipo LinkedIn).
    tipo_emp = (f.get("tipo_empresa") or "").strip().lower()
    if tipo_emp == "publica":
        where.append("emp.natureza LIKE '1%'")
    elif tipo_emp == "privada":
        where.append("emp.natureza NOT LIKE '1%'")

    ufs = _as_list(f.get("uf"))
    if ufs:
        where.append("e.uf IN (%s)" % ",".join("?" * len(ufs)))
        params += [u.upper() for u in ufs]

    muns = _as_list(f.get("municipio"))
    if muns:
        codes = []
        for m in muns:
            codes += _municipio_codes(m)
        codes = list(dict.fromkeys(codes)) or ["__none__"]
        where.append("e.municipio IN (%s)" % ",".join("?" * len(codes)))
        params += codes

    sits = _as_list(f.get("situacao"))
    if sits:
        codes = [SITUACAO.get(s.upper(), s) for s in sits]
        where.append("e.situacao IN (%s)" % ",".join("?" * len(codes)))
        params += codes

    if f.get("somente_matriz"):
        where.append("e.matriz_filial = '1'")
    if f.get("somente_filial"):
        where.append("e.matriz_filial = '2'")

    natur = _as_list(f.get("natureza"))
    if natur:
        where.append("emp.natureza IN (%s)" % ",".join("?" * len(natur)))
        params += natur

    porte = _as_list(f.get("porte"))
    if porte:
        where.append("emp.porte IN (%s)" % ",".join("?" * len(porte)))
        params += porte

    cap_min = int(f.get("capital_min") or 0)
    cap_max = int(f.get("capital_max") or 0)
    if cap_min > 0:
        where.append("emp.capital_social >= ?"); params.append(cap_min)
    if cap_max > 0:
        where.append("emp.capital_social <= ?"); params.append(cap_max)

    # MEI: EXISTS/NOT EXISTS correlacionado usa o índice ix_sim_cnpj (lookup por
    # cnpj_basico) — nunca tinha sido implementado apesar do checkbox existir.
    if f.get("mei_optante"):
        where.append("EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=e.cnpj_basico AND sm.opcao_mei='S')")
    if f.get("mei_excluir"):
        where.append("NOT EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=e.cnpj_basico AND sm.opcao_mei='S')")

    if f.get("com_telefone"):
        where.append("e.tel1 <> ''")
    if f.get("com_email"):
        where.append("e.email <> ''")

    # Busca geral (lupa): aplica o texto num OU entre os campos do ESCOPO marcado.
    # skip_texto=True quando o FTS vai dirigir a query (tratado em search()).
    # Fallback LIKE (só quando o FTS NÃO está pronto; com FTS, search() trata o texto).
    texto = (f.get("texto") or "").strip().upper()
    if texto and not skip_texto:
        escopo = f.get("texto_escopo") or ["razao", "fantasia"]
        ors, ps = [], []
        if "razao" in escopo:
            ors.append("UPPER(emp.razao_social) LIKE ?"); ps.append(f"%{texto}%")
        if "fantasia" in escopo:
            ors.append("UPPER(e.nome_fantasia) LIKE ?"); ps.append(f"%{texto}%")
        if "cnae" in escopo:
            codes = _codes_by_desc("cnae", texto, limit=80)
            if codes:
                ors.append("e.cnae_principal IN (%s)" % ",".join("?" * len(codes))); ps += codes
        if "natureza" in escopo:
            codes = _codes_by_desc("natureza", texto, limit=80)
            if codes:
                ors.append("emp.natureza IN (%s)" % ",".join("?" * len(codes))); ps += codes
        if ors:
            where.append("(" + " OR ".join(ors) + ")")
            params += ps

    return (" AND ".join(where) if where else "1=1"), params


def search(filtros: dict, limite: int = 50, offset: int = 0) -> dict:
    """Busca filtrada. Retorna {status, total, empresas:[...]}.

    Filtros por índices (CNAE/UF/município/situação) são rápidos; 'texto' é LIKE
    e fica lento se usado sozinho — combine sempre com CNAE ou UF.
    """
    if not ready():
        return {"status": "unavailable", "total": 0, "empresas": []}
    filtros = filtros or {}
    limite = max(1, min(int(limite or 50), 2000))
    CAP = 500  # "500+" já basta pra UX; contar mais custa I/O aleatório caro em disco frio

    # Busca direta por CNPJ (campo "Documento"): ignora os demais filtros.
    cnpj_direto = re.sub(r"\D", "", filtros.get("cnpj") or "")
    if len(cnpj_direto) == 14:
        d = by_cnpj(cnpj_direto)
        if d.get("status") != "ok":
            return {"status": "ok", "total": 0, "total_aprox": False, "empresas": []}
        co = d["company"]
        return {"status": "ok", "total": 1, "total_aprox": False, "empresas": [{
            "cnpj": co["cnpj"], "razao_social": co["razao_social"],
            "nome_fantasia": co["nome_fantasia"], "uf": co["uf"], "municipio": co["municipio"],
            "situacao": co["descricao_situacao_cadastral"], "cnae": co["cnae_fiscal_descricao"],
            "cnae_codigo": co["cnae_fiscal"], "porte": co["porte"], "capital_social": co["capital_social"],
        }]}

    texto = (filtros.get("texto") or "").strip()
    escopo = filtros.get("texto_escopo") or ["razao", "fantasia"]
    text_expr = _fts_text_expr(texto, escopo) if texto else ""
    use_fts = bool(text_expr) and _fts_ready()
    tem_texto = bool(texto)

    try:
        with _conn() as con:
            if use_fts:
                # FTS com colunas de localização: o próprio índice filtra
                # texto+uf+município+situação+cnae (sub-segundo até frio). capital/
                # natureza (não estão no FTS) viram pós-filtro no JOIN empresas.
                parts = [text_expr]
                ufs = _as_list(filtros.get("uf"))
                if ufs:
                    parts.append(_fts_col_or("uf", ufs))
                muni = _as_list(filtros.get("municipio"))
                if muni:
                    codes = []
                    for m in muni:
                        codes += _municipio_codes(m)
                    parts.append(_fts_col_or("municipio", list(dict.fromkeys(codes)) or ["zzzz"]))
                sits = _as_list(filtros.get("situacao"))
                if sits:
                    parts.append(_fts_col_or("situacao", [SITUACAO.get(s.upper(), s) for s in sits]))
                cnaes = _as_list(filtros.get("cnae"))
                if cnaes:
                    parts.append(_fts_col_or("cnae", cnaes))
                setor = (filtros.get("setor") or "").strip()
                if setor:
                    scodes = _codes_by_desc("cnae", setor, limit=300)
                    parts.append(_fts_col_or("cnae", scodes) if scodes else "cnae:zzzz")
                match = " AND ".join(p for p in parts if p)

                post, pp = [], []
                cap_min, cap_max = int(filtros.get("capital_min") or 0), int(filtros.get("capital_max") or 0)
                if cap_min > 0:
                    post.append("emp.capital_social >= ?"); pp.append(cap_min)
                if cap_max > 0:
                    post.append("emp.capital_social <= ?"); pp.append(cap_max)
                natur = _as_list(filtros.get("natureza"))
                if natur:
                    post.append("emp.natureza IN (%s)" % ",".join("?" * len(natur))); pp += natur
                porte = _as_list(filtros.get("porte"))
                if porte:
                    post.append("emp.porte IN (%s)" % ",".join("?" * len(porte))); pp += porte
                tipo_emp = (filtros.get("tipo_empresa") or "").strip().lower()
                if tipo_emp == "publica":
                    post.append("emp.natureza LIKE '1%'")
                elif tipo_emp == "privada":
                    post.append("emp.natureza NOT LIKE '1%'")
                fde = re.sub(r"\D", "", filtros.get("fundada_de") or "")
                fate = re.sub(r"\D", "", filtros.get("fundada_ate") or "")
                if fde:
                    post.append("e.data_inicio >= ?"); pp.append(fde)
                if fate:
                    post.append("e.data_inicio <= ?"); pp.append(fate)
                if filtros.get("mei_optante"):
                    post.append("EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=substr(f.cnpj,1,8) AND sm.opcao_mei='S')")
                if filtros.get("mei_excluir"):
                    post.append("NOT EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=substr(f.cnpj,1,8) AND sm.opcao_mei='S')")
                post_sql = (" AND " + " AND ".join(post)) if post else ""
                capped = None
                rows = con.execute(
                    "SELECT f.cnpj AS cnpj, f.razao AS razao_social, f.fantasia AS nome_fantasia, "
                    "f.uf AS uf, f.municipio AS municipio, f.situacao AS situacao, "
                    "f.cnae AS cnae_principal, emp.porte AS porte, emp.capital_social AS capital_social "
                    "FROM ftsx.estab_fts f "
                    "JOIN empresas emp ON emp.cnpj_basico = substr(f.cnpj, 1, 8) "
                    f"WHERE estab_fts MATCH ?{post_sql} LIMIT ? OFFSET ?",
                    [match] + pp + [limite, int(offset or 0)]
                ).fetchall()
            else:
                where, params = _build_where(filtros, skip_texto=False)
                base = ("FROM estabelecimentos e JOIN empresas emp ON emp.cnpj_basico = e.cnpj_basico "
                        f"WHERE {where}")
                needs_emp = "emp." in where
                count_base = base if needs_emp else f"FROM estabelecimentos e WHERE {where}"
                if tem_texto:  # sem FTS (LIKE) — não conta (varreria muito)
                    capped = None
                else:
                    capped = con.execute(f"SELECT COUNT(*) FROM (SELECT 1 {count_base} LIMIT ?)",
                                         params + [CAP + 1]).fetchone()[0]
                rows = con.execute(
                    f"SELECT e.cnpj, emp.razao_social, e.nome_fantasia, e.uf, e.municipio, "
                    f"e.situacao, e.cnae_principal, emp.porte, emp.capital_social {base} "
                    f"LIMIT ? OFFSET ?", params + [limite, int(offset or 0)]
                ).fetchall()
        empresas = [{
            "cnpj": _fmt_cnpj(r["cnpj"]),
            "razao_social": r["razao_social"] or "",
            "nome_fantasia": r["nome_fantasia"] or "",
            "uf": r["uf"] or "",
            "municipio": _desc("municipio", r["municipio"]),
            "situacao": SITUACAO_REV.get(r["situacao"], r["situacao"] or ""),
            "cnae": _desc("cnae", r["cnae_principal"]),
            "cnae_codigo": r["cnae_principal"] or "",
            "porte": PORTE.get(r["porte"], ""),
            "capital_social": r["capital_social"] or 0,
        } for r in rows]
        if tem_texto:
            total, total_aprox = len(empresas), len(rows) >= limite
        else:
            total, total_aprox = min(capped, CAP), capped > CAP
        return {"status": "ok", "total": total, "total_aprox": total_aprox, "empresas": empresas}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200], "total": 0, "empresas": []}


def search_pessoas(filtros: dict, limite: int = 50, offset: int = 0) -> dict:
    """Busca pessoas (perfil 'Clientes potenciais' estilo Datastone).

    PROXY HONESTO: usamos SÓCIOS reais da Receita (não um dataset de perfis
    profissionais/LinkedIn — isso ainda não está ligado). Cargo = qualificação
    societária (ex.: "Sócio-Administrador"), não cargo de funcionário genérico.
    Cobre só sócios, não funcionários/decisores não-sócios.

    Retorna {status, total, total_aprox, pessoas:[{nome, cpf_mascarado, cargo,
    data_entrada, empresa, cnpj, uf, municipio, cnae}]}.
    """
    if not ready():
        return {"status": "unavailable", "total": 0, "pessoas": []}
    filtros = filtros or {}
    limite = max(1, min(int(limite or 50), 500))
    where, params = [], []

    nome = (filtros.get("nome") or "").strip().upper()
    sobrenome = (filtros.get("sobrenome") or "").strip().upper()
    cargo = (filtros.get("cargo") or "").strip()
    setor = (filtros.get("setor") or "").strip()
    nome_empresa = (filtros.get("nome_empresa") or "").strip().upper()
    tem_texto_pesado = bool(nome or sobrenome or cargo or setor or nome_empresa)

    if nome:
        # RANGE indexado (nomes já vêm em MAIÚSCULO na Receita): 'UPPER(x) LIKE'
        # desabilita o índice (mesma armadilha do JBR — vira SCAN de 27M linhas,
        # 20s+); range direto usa ix_soc_nome via SEARCH, ~0,003s.
        where.append("s.nome_socio >= ? AND s.nome_socio < ?")
        params += [nome, nome + "￿"]
    if sobrenome:
        # Sufixo não é indexável (SCAN inevitável) — só use combinado com outro
        # filtro seletivo (nome/UF/cargo/etc); ver checagem de segurança abaixo.
        where.append("s.nome_socio LIKE ?"); params.append(f"%{sobrenome}")
    if cargo:
        codes = _codes_by_desc("qualificacao", cargo, limit=40)
        where.append("s.qualificacao IN (%s)" % ",".join("?" * len(codes)) if codes else "1=0")
        params += codes

    ufs = _as_list(filtros.get("uf"))
    if ufs:
        where.append("e.uf IN (%s)" % ",".join("?" * len(ufs)))
        params += [u.upper() for u in ufs]

    muni = _as_list(filtros.get("municipio"))
    if muni:
        codes = []
        for m in muni:
            codes += _municipio_codes(m)
        codes = list(dict.fromkeys(codes)) or ["__none__"]
        where.append("e.municipio IN (%s)" % ",".join("?" * len(codes)))
        params += codes

    if setor:
        codes = _codes_by_desc("cnae", setor, limit=300)
        where.append("e.cnae_principal IN (%s)" % ",".join("?" * len(codes)) if codes else "1=0")
        params += codes

    cnaes = _as_list(filtros.get("cnae"))
    if cnaes:
        where.append("e.cnae_principal IN (%s)" % ",".join("?" * len(cnaes)))
        params += cnaes

    naturezas = _as_list(filtros.get("natureza"))
    if naturezas:
        where.append("emp.natureza IN (%s)" % ",".join("?" * len(naturezas)))
        params += naturezas

    porte = _as_list(filtros.get("porte"))
    if porte:
        where.append("emp.porte IN (%s)" % ",".join("?" * len(porte)))
        params += porte

    tipo_emp = (filtros.get("tipo_empresa") or "").strip().lower()
    if tipo_emp == "publica":
        where.append("emp.natureza LIKE '1%'")
    elif tipo_emp == "privada":
        where.append("emp.natureza NOT LIKE '1%'")

    if nome_empresa:
        # LIKE '%...%' sem índice faz SCAN de 68M empresas (20s+). Usa o FTS
        # (razão/fantasia), igual à busca de empresa — IN(subquery) limitado.
        expr = _fts_text_expr(nome_empresa, ["razao", "fantasia"])
        if expr and _fts_ready():
            where.append("e.cnpj_basico IN (SELECT DISTINCT substr(cnpj,1,8) FROM ftsx.estab_fts "
                        "WHERE estab_fts MATCH ? LIMIT 5000)")
            params.append(expr)
        else:
            where.append("UPPER(emp.razao_social) LIKE ?"); params.append(f"%{nome_empresa}%")

    fde = re.sub(r"\D", "", filtros.get("fundada_de") or "")
    fate = re.sub(r"\D", "", filtros.get("fundada_ate") or "")
    if fde:
        where.append("e.data_inicio >= ?"); params.append(fde)
    if fate:
        where.append("e.data_inicio <= ?"); params.append(fate)

    if filtros.get("mei_optante"):
        where.append("EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=e.cnpj_basico AND sm.opcao_mei='S')")
    if filtros.get("mei_excluir"):
        where.append("NOT EXISTS (SELECT 1 FROM simples sm WHERE sm.cnpj_basico=e.cnpj_basico AND sm.opcao_mei='S')")

    # "Anos na empresa": calculado a partir da data de entrada do sócio (dado real).
    anos_min = int(filtros.get("anos_min") or 0)
    anos_max = int(filtros.get("anos_max") or 0)
    if anos_min or anos_max:
        ano_atual = int(time.strftime("%Y"))
        if anos_min > 0:
            where.append("s.data_entrada <= ?"); params.append(f"{ano_atual - anos_min}1231")
        if anos_max > 0:
            where.append("s.data_entrada >= ?"); params.append(f"{ano_atual - anos_max}0101")

    # Sobrenome (sufixo) sem NENHUM filtro seletivo faz SCAN de 27M linhas
    # (20s+). Exige combinar com nome/UF/cidade/cargo/CNAE/natureza/CNPJ.
    tem_seletivo = bool(nome or cargo or ufs or muni or cnaes or naturezas or nome_empresa
                        or (filtros.get("cnpj") or "").strip())
    if sobrenome and not nome and not tem_seletivo:
        return {"status": "error", "total": 0, "total_aprox": False, "pessoas": [],
                "message": "Combine 'Sobrenome' com Nome, Localização, Cargo, Atividade ou "
                           "Natureza — sozinho, esse filtro é lento demais na base completa."}

    where_sql = " AND ".join(where) if where else "1=1"
    # matriz_filial='1' evita duplicar o mesmo sócio uma vez por filial da empresa.
    base = ("FROM socios s "
            "JOIN empresas emp ON emp.cnpj_basico = s.cnpj_basico "
            "JOIN estabelecimentos e ON e.cnpj_basico = s.cnpj_basico AND e.matriz_filial='1' "
            f"WHERE {where_sql}")

    try:
        with _conn() as con:
            capped = None
            if not tem_texto_pesado:
                capped = con.execute(f"SELECT COUNT(*) FROM (SELECT 1 {base} LIMIT 501)", params).fetchone()[0]
            rows = con.execute(
                f"SELECT s.nome_socio, s.cpf_cnpj_socio, s.qualificacao, s.data_entrada, "
                f"emp.razao_social, e.cnpj, e.uf, e.municipio, e.cnae_principal "
                f"{base} LIMIT ? OFFSET ?", params + [limite, int(offset or 0)]
            ).fetchall()
        pessoas = [{
            "nome": r["nome_socio"] or "",
            "cpf_mascarado": r["cpf_cnpj_socio"] or "",
            "cargo": _desc("qualificacao", r["qualificacao"]),
            "data_entrada": r["data_entrada"] or "",
            "empresa": r["razao_social"] or "",
            "cnpj": _fmt_cnpj(r["cnpj"]),
            "uf": r["uf"] or "",
            "municipio": _desc("municipio", r["municipio"]),
            "cnae": _desc("cnae", r["cnae_principal"]),
        } for r in rows]
        if tem_texto_pesado:
            total, total_aprox = len(pessoas), len(rows) >= limite
        else:
            total, total_aprox = min(capped, 500), capped > 500
        return {"status": "ok", "total": total, "total_aprox": total_aprox, "pessoas": pessoas}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200], "total": 0, "pessoas": []}


def by_cnpj(cnpj: str) -> dict:
    """Dados completos de uma empresa por CNPJ (14 díg.), com sócios."""
    if not ready():
        return {"status": "unavailable"}
    digits = re.sub(r"\D", "", cnpj or "")
    if len(digits) != 14:
        return {"status": "error", "message": "CNPJ inválido"}
    basico = digits[:8]
    try:
        with _conn() as con:
            # Filtra por cnpj_basico (indexado) primeiro — WHERE cnpj=? sozinho faz
            # SCAN nos 72M de estabelecimentos; poucas linhas por empresa após o filtro.
            candidatos = con.execute(
                "SELECT * FROM estabelecimentos WHERE cnpj_basico=?", (basico,)
            ).fetchall()
            est = next((r for r in candidatos if r["cnpj"] == digits), None)
            if not est:
                est = next((r for r in candidatos if r["matriz_filial"] == "1"), None)
            if not est and candidatos:
                est = candidatos[0]
            if not est:
                return {"status": "not_found"}
            emp = con.execute("SELECT * FROM empresas WHERE cnpj_basico=?", (basico,)).fetchone()
            socios = con.execute("SELECT * FROM socios WHERE cnpj_basico=?", (basico,)).fetchall()
            sim = con.execute("SELECT * FROM simples WHERE cnpj_basico=?", (basico,)).fetchone()

        company = {
            "cnpj": _fmt_cnpj(est["cnpj"]),
            "razao_social": (emp["razao_social"] if emp else "") or "",
            "nome_fantasia": est["nome_fantasia"] or "",
            "natureza_juridica": _desc("natureza", emp["natureza"]) if emp else "",
            "capital_social": (emp["capital_social"] if emp else 0) or 0,
            "porte": PORTE.get(emp["porte"] if emp else "", ""),
            "descricao_situacao_cadastral": SITUACAO_REV.get(est["situacao"], est["situacao"] or ""),
            "data_inicio_atividade": est["data_inicio"] or "",
            "cnae_fiscal": est["cnae_principal"] or "",
            "cnae_fiscal_descricao": _desc("cnae", est["cnae_principal"]),
            "logradouro": est["logradouro"] or "",
            "numero": est["numero"] or "",
            "bairro": est["bairro"] or "",
            "cep": est["cep"] or "",
            "municipio": _desc("municipio", est["municipio"]),
            "uf": est["uf"] or "",
            "email": est["email"] or "",
            "ddd_telefone_1": ((est["ddd1"] or "") + est["tel1"]) if est["tel1"] else "",
            "ddd_telefone_2": ((est["ddd2"] or "") + est["tel2"]) if est["tel2"] else "",
            "matriz_filial": "MATRIZ" if est["matriz_filial"] == "1" else "FILIAL",
            "complemento": est["complemento"] or "",
            "opcao_simples": (sim["opcao_simples"] if sim else ""),
            "opcao_mei": (sim["opcao_mei"] if sim else ""),
            "qsa": [{
                "nome_socio": s["nome_socio"] or "",
                "cnpj_cpf_do_socio": s["cpf_cnpj_socio"] or "",
                "qualificacao_socio": _desc("qualificacao", s["qualificacao"]),
                "faixa_etaria": s["faixa_etaria"] or "",
                "identificador": s["identificador"] or "",
            } for s in socios],
        }
        return {"status": "ok", "company": company}
    except Exception as exc:
        return {"status": "error", "message": str(exc)[:200]}
