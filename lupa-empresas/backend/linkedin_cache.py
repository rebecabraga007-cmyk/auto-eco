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

-- Livro-caixa da Bright Data. Existe porque a fatura deles vem por MÊS e sem
-- dizer quem pediu o quê: sem registrar na hora da chamada, não há como saber
-- depois se os US$ 40 do mês foram de uma busca útil ou de teste.
-- Também registra o que o cache ECONOMIZOU (custo_usd = 0, economia > 0), senão
-- o painel só mostra gasto e o cache parece não servir pra nada.
CREATE TABLE IF NOT EXISTS gastos_bd (
  id          INTEGER PRIMARY KEY AUTOINCREMENT,
  quando      INTEGER,
  usuario     TEXT,
  tipo        TEXT,      -- 'search' | 'scrape_empresa' | 'snapshot' | 'cache'
  detalhe     TEXT,      -- empresa/termo pedido, para auditoria
  registros   INTEGER,   -- perfis cobrados (ou servidos pelo cache)
  custo_usd   REAL,
  economia_usd REAL
);
CREATE INDEX IF NOT EXISTS idx_lc_gastos ON gastos_bd(quando);

-- PERFIL DO LINKEDIN -> CPF. A resposta mais CARA do sistema, guardada.
--
-- Resolver "qual dos 195 Vinicius Ferreira e este" custa de R$ 0,31 a
-- R$ 2,38 por pessoa -- e ate agora a resposta era descartada. A planilha
-- seguinte que tivesse a mesma pessoa pagava de novo.
--
-- O projeto inteiro acredita em PAGAR NA INGESTAO, NAO NA CONSULTA: e por
-- isso que a Receita e a JBR estao no disco e a busca de empresa e gratis.
-- Faltava aplicar o mesmo principio no passo mais caro de todos.
--
-- Guarda o NAO RESOLVIDO tambem, e isso importa: tentar de novo uma pessoa
-- que o funil ja nao fechou custa o mesmo e da o mesmo resultado. Mas com
-- validade -- dado novo aparece, e uma negativa eterna viraria uma porta
-- fechada para sempre.
CREATE TABLE IF NOT EXISTS perfil_cpf (
  url          TEXT PRIMARY KEY,   -- o perfil; e o unico identificador unico
  nome_norm    TEXT,               -- para achar sem a URL
  empresa_norm TEXT,
  cpf          TEXT,               -- vazio = tentamos e nao fechou
  confianca    INTEGER,
  situacao     TEXT,               -- resolvido_por_email, resolvido_gratis...
  forte        INTEGER DEFAULT 0,
  custo_brl    REAL DEFAULT 0,     -- quanto custou descobrir, para medir o ganho
  quando       INTEGER
);
CREATE INDEX IF NOT EXISTS idx_lc_pcpf_nome ON perfil_cpf(nome_norm, empresa_norm);
"""

# US$ 2,50 por 1.000 registros — medido na fatura, não estimado: a chamada
# devolve `cost: 0` no corpo e isso me fez errar duas vezes antes de conferir.
USD_POR_REGISTRO = 0.0025


def _con():
    con = sqlite3.connect(DB_PATH, timeout=10)
    con.row_factory = sqlite3.Row
    return con


# Quanto tempo uma NEGATIVA vale. Positiva nao expira: CPF de uma pessoa nao
# muda. Negativa expira porque a base muda -- a JBR recebe carga, a pessoa
# aparece num cadastro novo, e insistir daqui a um mes pode fechar o que hoje
# nao fecha. Trinta dias e o intervalo entre as cargas que recebemos.
DIAS_NEGATIVA = 30


def lembrar_cpf(url: str, nome_norm: str, empresa_norm: str, cpf: str,
                confianca: int = 0, situacao: str = "", forte: bool = False,
                custo_brl: float = 0.0) -> None:
    """Guarda o que o funil descobriu -- inclusive o "nao achei"."""
    if not (url or nome_norm):
        return
    init()
    con = _con()
    try:
        con.execute(
            "INSERT INTO perfil_cpf (url, nome_norm, empresa_norm, cpf,"
            " confianca, situacao, forte, custo_brl, quando)"
            " VALUES (?,?,?,?,?,?,?,?,?)"
            " ON CONFLICT(url) DO UPDATE SET"
            "   nome_norm=excluded.nome_norm, empresa_norm=excluded.empresa_norm,"
            "   cpf=excluded.cpf, confianca=excluded.confianca,"
            "   situacao=excluded.situacao, forte=excluded.forte,"
            "   custo_brl=excluded.custo_brl, quando=excluded.quando",
            (url or ("nome:%s|%s" % (nome_norm, empresa_norm)), nome_norm or "",
             empresa_norm or "", cpf or "", int(confianca or 0), situacao or "",
             1 if forte else 0, float(custo_brl or 0), int(time.time())))
        con.commit()
    finally:
        con.close()


def recordar_cpf(url: str = "", nome_norm: str = "",
                 empresa_norm: str = "") -> dict | None:
    """Ja sabemos o CPF deste perfil? None = nunca perguntamos (ou venceu).

    Procura pela URL primeiro, que e exata. Cai para nome+empresa porque o
    mesmo perfil chega com URL diferente dependendo da origem (busca da Bright
    Data, snapshot, link colado a mao).
    """
    init()
    con = _con()
    try:
        r = None
        if url:
            r = con.execute("SELECT * FROM perfil_cpf WHERE url = ?",
                            (url,)).fetchone()
        if r is None and nome_norm:
            r = con.execute(
                "SELECT * FROM perfil_cpf WHERE nome_norm = ?"
                " AND (empresa_norm = ? OR ? = '')"
                " ORDER BY (cpf <> '') DESC, quando DESC LIMIT 1",
                (nome_norm, empresa_norm or "", empresa_norm or "")).fetchone()
    finally:
        con.close()
    if r is None:
        return None
    # A NEGATIVA VENCE. Positiva nao: CPF nao muda.
    if not r["cpf"] and (time.time() - (r["quando"] or 0)) > DIAS_NEGATIVA * 86400:
        return None
    return {"cpf": r["cpf"], "confianca": r["confianca"],
            "situacao": r["situacao"], "forte": bool(r["forte"]),
            "custo_brl": r["custo_brl"], "quando": r["quando"]}


def economia_cpf() -> dict:
    """Quanto o cache de CPF ja poupou. Sem numero, ele e so fe."""
    init()
    con = _con()
    try:
        r = con.execute(
            "SELECT count(*) n, sum(cpf <> '') fechados, round(sum(custo_brl),2) gasto"
            " FROM perfil_cpf").fetchone()
    finally:
        con.close()
    return {"pessoas": r["n"] or 0, "com_cpf": r["fechados"] or 0,
            "custo_ja_pago": r["gasto"] or 0.0}


def init() -> None:
    """Cria/migra o banco. A ORDEM importa: índice de coluna nova só depois do
    ALTER TABLE, senão o script inteiro falha em banco que já existia."""
    os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    con = _con()
    con.executescript(_DDL)                     # 1. tabelas e índices antigos
    # `perfil_cpf` nasce aqui em banco novo E em banco antigo: CREATE TABLE IF
    # NOT EXISTS cria tabela que falta, so nao mexe em tabela que existe.

    # 2. colunas novas — CREATE TABLE IF NOT EXISTS não altera tabela existente
    tem = {r[1] for r in con.execute("PRAGMA table_info(perfis)")}
    novas = ("departamento", "senioridade", "nome_norm",
             # Campos que o dataset da Bright Data já entregava e a gente
             # descartava. Medido em 300 registros do snapshot:
             "sobrenome",       # last_name  — 99,0% preenchido
             "primeiro_nome",   # first_name — 99,7%
             "uf",              # derivada de `city` ("…, Rio de Janeiro, Brazil")
             "empresa_id",      # current_company_company_id — 40,7%
             "idiomas",         # languages       — 11,7%
             "certificacoes",   # certifications  —  8,0%
             "desde_na_empresa",  # de `experience` — 80,3%; guarda AAAAMM
             # Só o dataset ENRIQUECIDO traz. É o único identificador único que
             # um perfil carrega: nome tem homônimo, e-mail não. 5,0% dos
             # brasileiros têm; por empresa chega a 31%.
             "email")
    for coluna in novas:
        if coluna not in tem:
            con.execute("ALTER TABLE perfis ADD COLUMN %s TEXT" % coluna)
    if "conexoes" not in tem:
        con.execute("ALTER TABLE perfis ADD COLUMN conexoes INTEGER")
    # Estimadores de idade: ano da última formação e ano do primeiro emprego.
    # Alimentam `faixa_nascimento()`, que é o filtro grátis que mais corta
    # homônimo — "Vinicius Ferreira" cai de 5.442 para ~2.600 só com isso.
    for c in ("formatura_ano", "carreira_desde"):
        if c not in tem:
            con.execute("ALTER TABLE perfis ADD COLUMN %s INTEGER" % c)

    # 3. só agora os índices que dependem delas
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_depto  ON perfis(departamento)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_senior ON perfis(senioridade)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_nome  ON perfis(nome_norm)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_uf    ON perfis(uf)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_sobre ON perfis(sobrenome)")
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_empid ON perfis(empresa_id)")

    # A empresa da Bright Data nao vem com CNPJ -- ele e deduzido pelo dominio
    # do site (ver empresa_cnpj). Guardar aqui evita refazer a deducao, e
    # guardar a CONFIANCA junto evita o pior: uma tela que mostra o CNPJ
    # deduzido por semelhanca de nome com a mesma cara de um exato.
    tem_emp = {r[1] for r in con.execute("PRAGMA table_info(empresas)")}
    for coluna in ("cnpj", "cnpj_confianca"):
        if coluna not in tem_emp:
            con.execute("ALTER TABLE empresas ADD COLUMN %s TEXT" % coluna)
    con.execute("CREATE INDEX IF NOT EXISTS idx_lc_emp_cnpj ON empresas(cnpj)")
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


# O LinkedIn não tem campo de UF: `city` vem como texto livre, e em três formatos
# diferentes no mesmo dataset — "Niterói, Rio de Janeiro, Brazil", "São Paulo,
# São Paulo, Brasil" e só "Curitiba". Então a UF é DEDUZIDA do nome do estado
# quando ele aparece, e fica vazia quando não aparece. Filtro por UF que
# silenciosamente descarta quem não tem UF mentiria; por isso `uf_vazia_conta`.
_ESTADOS = {
    "acre": "AC", "alagoas": "AL", "amapa": "AP", "amazonas": "AM",
    "bahia": "BA", "ceara": "CE", "distrito federal": "DF",
    "espirito santo": "ES", "goias": "GO", "maranhao": "MA",
    "mato grosso do sul": "MS", "mato grosso": "MT", "minas gerais": "MG",
    "para": "PA", "paraiba": "PB", "parana": "PR", "pernambuco": "PE",
    "piaui": "PI", "rio de janeiro": "RJ", "rio grande do norte": "RN",
    "rio grande do sul": "RS", "rondonia": "RO", "roraima": "RR",
    "santa catarina": "SC", "sao paulo": "SP", "sergipe": "SE",
    "tocantins": "TO",
    # O LinkedIn escreve parte dos estados em inglês, no MESMO dataset:
    # "Cruzeiro, Federal District, Brazil" convive com "…, Paraná, Brazil".
    "federal district": "DF", "state of sao paulo": "SP",
    "state of rio de janeiro": "RJ", "state of minas gerais": "MG",
    "state of parana": "PR", "state of santa catarina": "SC",
    "state of rio grande do sul": "RS", "state of bahia": "BA",
    "state of goias": "GO", "state of ceara": "CE",
    "state of pernambuco": "PE", "state of espirito santo": "ES",
    "state of para": "PA", "state of amazonas": "AM",
    "state of mato grosso": "MT", "state of mato grosso do sul": "MS",
    "state of maranhao": "MA", "state of paraiba": "PB",
    "state of rio grande do norte": "RN", "state of alagoas": "AL",
    "state of piaui": "PI", "state of sergipe": "SE",
    "state of rondonia": "RO", "state of tocantins": "TO",
    "state of acre": "AC", "state of amapa": "AP", "state of roraima": "RR",
}
# Capitais e cidades grandes resolvem parte do caso "só Curitiba", que é 38% do
# dataset. Não é lista completa de municípios de propósito: 5.570 municípios com
# nomes repetidos entre estados dariam UF errada, e UF errada é pior que vazia.
_CIDADES_UF = {
    "sao paulo": "SP", "rio de janeiro": "RJ", "brasilia": "DF",
    "salvador": "BA", "fortaleza": "CE", "belo horizonte": "MG",
    "manaus": "AM", "curitiba": "PR", "recife": "PE", "goiania": "GO",
    "belem": "PA", "porto alegre": "RS", "guarulhos": "SP",
    "campinas": "SP", "sao luis": "MA", "maceio": "AL", "campo grande": "MS",
    "natal": "RN", "teresina": "PI", "joao pessoa": "PB", "cuiaba": "MT",
    "aracaju": "SE", "florianopolis": "SC", "vitoria": "ES",
    "porto velho": "RO", "macapa": "AP", "rio branco": "AC",
    "boa vista": "RR", "palmas": "TO", "niteroi": "RJ",
    "sao bernardo do campo": "SP", "santo andre": "SP", "osasco": "SP",
    "sorocaba": "SP", "ribeirao preto": "SP", "santos": "SP",
    "joinville": "SC", "londrina": "PR", "uberlandia": "MG",
    "contagem": "MG", "duque de caxias": "RJ", "jundiai": "SP",
    "caxias do sul": "RS", "blumenau": "SC", "barueri": "SP",
}


def uf_de(cidade: str) -> str:
    """UF a partir do texto livre de cidade. Vazio quando não dá pra afirmar.

    ATENÇÃO: separa por vírgula ANTES de normalizar. `norm()` troca pontuação
    por espaço, então normalizar primeiro apaga as vírgulas e "Ribeirão Pires,
    São Paulo, Brazil" vira um pedaço só que não casa com estado nenhum.
    """
    if not (cidade or "").strip():
        return ""
    partes = [norm(p) for p in str(cidade).split(",")]
    partes = [p for p in partes if p]
    # Estado costuma ser o penúltimo pedaço ("cidade, estado, brazil"),
    # então varre de trás pra frente.
    for p in reversed(partes):
        if p in _ESTADOS:
            return _ESTADOS[p]
    # Sigla solta ("Niteroi, RJ")
    siglas = set(_ESTADOS.values())
    for p in partes:
        if len(p) == 2 and p.upper() in siglas:
            return p.upper()
    # "Greater Curitiba", "Grande São Paulo": região metropolitana.
    for p in partes:
        limpo = re.sub(r"^(greater|grande|regiao metropolitana de|area de)\s+", "", p)
        if limpo in _CIDADES_UF:
            return _CIDADES_UF[limpo]
    return ""


def _sobrenome_de(nome: str, last_name: str = "") -> str:
    """Sobrenome normalizado. Usa `last_name` da origem quando existe; senão a
    última palavra do nome. Ignora partícula ('da', 'de', 'dos') sozinha, que é
    o que faria 'João da Silva' virar sobrenome 'da'."""
    alvo = norm(last_name) or norm(nome)
    palavras = [p for p in alvo.split()
                if p not in ("da", "de", "do", "das", "dos", "e")]
    return palavras[-1] if palavras else ""


def faixa_nascimento(formatura_ano: int = 0, carreira_desde: int = 0,
                     folga: int = 0) -> tuple[int, int]:
    """Faixa de ano de nascimento a partir de formatura e primeiro emprego.

    O LinkedIn não tem data de nascimento. Mas tem quando a pessoa se formou e
    quando começou a trabalhar, e os dois cercam a idade. Devolve (de, ate);
    (0, 0) quando não há sinal nenhum — e aí NÃO se filtra por idade.

    As faixas são largas de propósito. Errar para largo custa algumas consultas
    a mais; errar para estreito descarta a pessoa certa e o erro fica invisível.

      formatura      → nascimento ≈ ano − 22, com −9/+7
                       (cobre técnico aos ~17 e pós aos ~30)
      1º emprego     → nascimento ≈ ano − 21, com −9/+5
                       (primeiro registro entre 16 e 30 anos)

    Com os dois sinais, INTERSECTA — e se a interseção ficar absurda (menos de
    4 anos, ou invertida), devolve a união, porque interseção estreita demais
    quase sempre significa que um dos dois anos está errado, não que a pessoa
    nasceu naquele intervalo exato.
    """
    faixas = []
    if formatura_ano and 1930 <= formatura_ano <= 2049:
        faixas.append((formatura_ano - 22 - 9, formatura_ano - 22 + 7))
    if carreira_desde and 1930 <= carreira_desde <= 2049:
        faixas.append((carreira_desde - 21 - 9, carreira_desde - 21 + 5))
    if not faixas:
        return (0, 0)
    if len(faixas) == 1:
        de, ate = faixas[0]
    else:
        de, ate = max(f[0] for f in faixas), min(f[1] for f in faixas)
        if ate - de < 4:                       # interseção implausível
            de, ate = min(f[0] for f in faixas), max(f[1] for f in faixas)
    de, ate = de - int(folga or 0), ate + int(folga or 0)
    # Ninguém no LinkedIn nasceu antes de 1935 nem depois de 2010.
    return (max(de, 1935), min(ate, 2010))


def dentro_da_faixa(nascimento: str, de: int, ate: int) -> bool:
    """`nascimento` é 'dd/mm/aaaa' (JBR e Assertiva usam esse formato).

    Sem faixa, tudo passa. Sem data na pessoa, TAMBÉM passa: quem não tem data
    não pode ser descartado por idade — descartar seria inventar um critério.
    """
    if not de or not ate:
        return True
    m = re.search(r"(\d{4})\s*$", str(nascimento or "").strip())
    if not m:
        return True
    return de <= int(m.group(1)) <= ate


def registrar_gasto(tipo: str, detalhe: str = "", registros: int = 0,
                    custo_usd: float = 0.0, economia_usd: float = 0.0,
                    usuario: str = "") -> None:
    """Anota uma chamada paga (ou uma servida de graça pelo cache).

    Nunca levanta erro: perder a busca do usuário porque a contabilidade falhou
    seria trocar um problema pequeno por um grande.
    """
    try:
        con = _con()
        con.execute("""INSERT INTO gastos_bd
            (quando,usuario,tipo,detalhe,registros,custo_usd,economia_usd)
            VALUES (?,?,?,?,?,?,?)""",
                    (int(time.time()), (usuario or "")[:120], tipo,
                     (detalhe or "")[:200], int(registros or 0),
                     float(custo_usd or 0), float(economia_usd or 0)))
        con.commit()
        con.close()
    except Exception as exc:
        # Mesma regra do outro livro-caixa: nao levanta, mas deixa
        # rastro. Sem isto o gasto da Bright Data some da conta e o
        # extrato do admin passa a mentir para menos.
        print('[gastos_bd] perdi um lancamento (%s): %s: %s'
              % (tipo, type(exc).__name__, str(exc)[:140]), flush=True)


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
                                departamento,senioridade,
                                primeiro_nome,sobrenome,uf,empresa_id,
                                idiomas,certificacoes,desde_na_empresa,conexoes,
                                formatura_ano,carreira_desde,email)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
            ON CONFLICT(url) DO UPDATE SET
              nome=excluded.nome, nome_norm=excluded.nome_norm,
              cargo=excluded.cargo, empresa=excluded.empresa,
              empresa_norm=excluded.empresa_norm, cidade=excluded.cidade,
              pais=excluded.pais, foto=excluded.foto, formacao=excluded.formacao,
              sobre=excluded.sobre, seguidores=excluded.seguidores,
              visto_em=excluded.visto_em, departamento=excluded.departamento,
              senioridade=excluded.senioridade,
              primeiro_nome=excluded.primeiro_nome, sobrenome=excluded.sobrenome,
              uf=excluded.uf,
              -- COALESCE: o Search não devolve todos os campos que o snapshot
              -- devolve. Sobrescrever com vazio apagaria dado já pago.
              empresa_id=COALESCE(NULLIF(excluded.empresa_id,''), perfis.empresa_id),
              idiomas=COALESCE(NULLIF(excluded.idiomas,''), perfis.idiomas),
              certificacoes=COALESCE(NULLIF(excluded.certificacoes,''), perfis.certificacoes),
              desde_na_empresa=COALESCE(NULLIF(excluded.desde_na_empresa,''), perfis.desde_na_empresa),
              conexoes=COALESCE(excluded.conexoes, perfis.conexoes),
              -- NULLIF(...,0): o Search nao devolve `education`/`experience`, so o
              -- snapshot devolve. Sobrescrever com 0 apagaria o ano ja obtido.
              formatura_ano=COALESCE(NULLIF(excluded.formatura_ano,0), perfis.formatura_ano),
              carreira_desde=COALESCE(NULLIF(excluded.carreira_desde,0), perfis.carreira_desde),
              -- mesma proteção: o dataset padrão não tem e-mail, e um perfil
              -- revisto por ele não pode apagar o que o enriquecido trouxe.
              email=COALESCE(NULLIF(excluded.email,''), perfis.email)
        """, (url, p.get("nome"), _chave_nome(p.get("nome") or ""),
              p.get("cargo"), p.get("empresa"),
              norm(p.get("empresa") or ""), p.get("cidade"), p.get("pais"),
              p.get("foto"), p.get("formacao"), p.get("sobre"),
              p.get("seguidores"), origem, agora,
              cargos.departamento(p.get("cargo") or ""),
              cargos.senioridade(p.get("cargo") or ""),
              norm(p.get("primeiro_nome") or (p.get("nome") or "").split(" ")[0]),
              _sobrenome_de(p.get("nome") or "", p.get("sobrenome") or ""),
              uf_de(p.get("cidade") or ""),
              p.get("empresa_id") or "", p.get("idiomas") or "",
              p.get("certificacoes") or "", p.get("desde_na_empresa") or "",
              p.get("conexoes"),
              int(p.get("formatura_ano") or 0), int(p.get("carreira_desde") or 0),
              (p.get("email") or "").strip().lower()))
    con.commit()
    con.close()
    return novos


def por_empresa(empresa: str, pais: str = "", cargo: str = "",
                limite: int = 200,
                decisores: bool = False) -> list[dict[str, Any]]:
    """O que já temos guardado dessa empresa. Não gasta nada.

    `decisores` FALTAVA AQUI, e isso tornava o filtro "Só decisores" da tela
    inócuo sempre que a resposta vinha do cache: o checkbox ia para a Bright
    Data mas não para cá, então a busca devolvia a empresa inteira — BDR, SDR,
    estagiário — com o filtro marcado. Ninguém via erro nenhum.

    O corte usa `funcoes.decisor()` (coordenação para cima), não os quatro
    termos que a Bright Data aceita. Lá o teto é do `or` deles — no máximo 4
    condições, então sobram só "diretor, head, presidente, ceo" e gerente fica
    de fora. Aqui não existe esse teto: dá para usar o dicionário inteiro, com
    gerência, coordenação, sócio, fundador e as siglas de C-level.
    """
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
    # Com o filtro de decisor, o corte acontece em Python (o dicionário de
    # cargos não cabe em SQL), então o LIMIT tem que vir DEPOIS. Buscar
    # `limite` linhas e filtrar em cima devolveria 2 de 50 pedidos só porque o
    # LIMIT cortou antes. Pega uma folga e corta no fim.
    args.append(int(limite) * 8 if decisores else int(limite))
    con = _con()
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()
    saida = [dict(r) for r in linhas]
    if decisores:
        import funcoes
        saida = [p for p in saida if funcoes.decisor(p.get("cargo") or "")]
        saida = saida[:int(limite)]
    return saida


def _lista(v: Any) -> list[str]:
    """Aceita "a, b" ou ["a","b"]: a tela manda os dois formatos."""
    if v is None:
        return []
    if isinstance(v, str):
        v = re.split(r"[;,]", v)
    return [str(x).strip() for x in v if str(x).strip()]


def procurar(q: str = "", pais: str = "", limite: int = 100,
             departamento: str = "", senioridade: str = "",
             empresa: str = "",
             # --- filtros no vocabulário da Datastone ---
             nome: str = "", sobrenome: str = "", cargo: str = "",
             ufs: Any = None, cidade: str = "",
             palavras: str = "", tempo_empresa: str = "",
             so_com_foto: bool = False, min_seguidores: int = 0,
             linkedin_url: str = "",
             nasc_de: int = 0, nasc_ate: int = 0) -> list[dict[str, Any]]:
    """Busca no que já foi pago. `q` é o texto livre; os outros são os filtros
    equivalentes aos da Datastone (nome, sobrenome, cargo, UF, tempo na
    empresa, palavras-chave, dados disponíveis).

    TODOS são AND entre si e OR dentro de cada um — é o que a Datastone faz e o
    que a operação espera: "diretor OU head", mas "diretor E em SP".
    """
    con = _con()
    termo = "%" + (q or "").strip().lower() + "%"
    sql = ["SELECT * FROM perfis WHERE 1=1"]
    args: list[Any] = []

    # Lookup direto por URL: curto-circuita todo o resto, igual à Datastone.
    if (linkedin_url or "").strip():
        u = (linkedin_url or "").strip().split("?")[0].rstrip("/")
        linhas = con.execute("SELECT * FROM perfis WHERE url=? OR url LIKE ?",
                             (u, "%" + u.split("/in/")[-1] + "%")).fetchall()
        con.close()
        return [dict(r) for r in linhas]

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

    # Nome: casa no começo de qualquer palavra do nome, não no meio. "ana" tem
    # que achar "Ana Paula" e "Maria Ana", mas não "Adriana".
    for alvo_n, coluna in ((norm(nome), "nome_norm"), ):
        if alvo_n:
            sql.append("AND (%s = ? OR %s LIKE ? OR %s LIKE ?)"
                       % (coluna, coluna, coluna))
            args += [alvo_n, alvo_n + " %", "% " + alvo_n + " %"]
    if norm(sobrenome):
        sql.append("AND (sobrenome = ? OR nome_norm LIKE ?)")
        args += [norm(sobrenome), "% " + norm(sobrenome)]

    # Cargo: vários termos em OR ("diretor, head, gerente").
    termos_cargo = [norm(c) for c in _lista(cargo) if norm(c)]
    if termos_cargo:
        sql.append("AND (%s)" % " OR ".join(["lower(cargo) LIKE ?"] * len(termos_cargo)))
        args += ["%" + t + "%" for t in termos_cargo]

    # UF: só filtra quem TEM uf preenchida. Quem não tem não entra — e a tela
    # avisa quantos ficaram de fora, porque descartar em silêncio esconderia
    # que a UF é deduzida do texto de cidade, não um campo do LinkedIn.
    lista_uf = [u.strip().upper()[:2] for u in _lista(ufs) if u.strip()]
    if lista_uf:
        sql.append("AND uf IN (%s)" % ",".join("?" * len(lista_uf)))
        args += lista_uf
    if (cidade or "").strip():
        sql.append("AND lower(cidade) LIKE ?")
        args.append("%" + cidade.strip().lower() + "%")

    # Palavras-chave = o "skills/especialidades" da Datastone. Não temos campo de
    # skill; procuramos no texto do perfil (sobre, formação, idiomas,
    # certificações). É aproximação, e a tela diz isso.
    for p in [norm(x) for x in _lista(palavras) if norm(x)]:
        sql.append("""AND (lower(sobre) LIKE ? OR lower(formacao) LIKE ?
                        OR lower(idiomas) LIKE ? OR lower(certificacoes) LIKE ?
                        OR lower(cargo) LIKE ?)""")
        args += ["%" + p + "%"] * 5

    # Tempo na empresa: `desde_na_empresa` é AAAAMM. Faixas iguais às da tela.
    faixas = {"ate1": (0, 12), "1a3": (12, 36), "3a5": (36, 60),
              "5a10": (60, 120), "mais10": (120, 10000)}
    if tempo_empresa in faixas:
        de_meses, ate_meses = faixas[tempo_empresa]
        hoje = time.localtime()
        agora_m = hoje.tm_year * 12 + hoje.tm_mon
        # meses = agora - início  →  início entre (agora-ate) e (agora-de)
        lim_novo = agora_m - de_meses      # entrou no máximo isto
        lim_velho = agora_m - ate_meses    # entrou no mínimo isto
        sql.append("""AND desde_na_empresa <> '' AND desde_na_empresa IS NOT NULL
                      AND (CAST(substr(desde_na_empresa,1,4) AS INTEGER)*12
                         + CAST(substr(desde_na_empresa,5,2) AS INTEGER))
                          BETWEEN ? AND ?""")
        args += [lim_velho, lim_novo]

    # Faixa de nascimento derivada de formatura/1o emprego. Quem NAO tem os
    # anos continua entrando: nao da pra descartar por idade quem nao declarou.
    if nasc_de and nasc_ate:
        sql.append("""AND (
            (formatura_ano IS NULL OR formatura_ano=0) AND
            (carreira_desde IS NULL OR carreira_desde=0)
            OR (formatura_ano BETWEEN ? AND ?)
            OR (carreira_desde BETWEEN ? AND ?))""")
        args += [int(nasc_de) + 13, int(nasc_ate) + 31,
                 int(nasc_de) + 12, int(nasc_ate) + 30]
    if so_com_foto:
        sql.append("AND foto IS NOT NULL AND foto <> ''")
    if int(min_seguidores or 0) > 0:
        sql.append("AND seguidores >= ?")
        args.append(int(min_seguidores))

    # Empresa aceita VÁRIAS, como o `selected_companies` da Datastone, que é uma
    # lista. Antes só dava uma por vez e a operação tinha que filtrar 6 vezes.
    alvos = [norm(e) for e in _lista(empresa) if norm(e)]
    if alvos:
        sql.append("AND (%s)" % " OR ".join(["empresa_norm LIKE ?"] * len(alvos)))
        args += ["%" + a + "%" for a in alvos]
    sql.append("ORDER BY visto_em DESC LIMIT ?")
    # Com empresa no filtro, pede folga: a checagem por palavra abaixo descarta
    # parte, e sem folga a lista voltaria mais curta que o limite pedido.
    args.append(int(limite) * (4 if alvos else 1))
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()
    if not alvos:
        return [dict(r) for r in linhas]

    # Filtrar empresa por LIKE é substring: "Localiza" traz "Maxlocaliza
    # Rastreamento" e "Natura" traz "Natural Sabore Alimentos". Não jogamos fora
    # (o perfil é real e já foi pago), mas marcamos, para a tela poder mostrar o
    # parecido em cinza no fim em vez de misturar com quem a pessoa pediu.
    exatas, parecidas = [], []
    for r in linhas:
        d = dict(r)
        emp = " %s " % (d.get("empresa_norm") or "")
        casou = next((a for a in alvos if (" %s " % a) in emp), None)
        d["empresa_casada"] = casou or ""
        d["exata"] = bool(casou)
        (exatas if casou else parecidas).append(d)
    return (exatas + parecidas)[:int(limite)]


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


def por_empresas(empresas: list[str], pais: str = "", limite: int = 300,
                 departamento: str = "", senioridade: str = "") -> list[dict[str, Any]]:
    """Pessoas de VÁRIAS empresas numa consulta só. Grátis e instantâneo.

    É assim que a Datastone faz (visto no `prospect.js` deles): o filtro manda
    `selected_companies` como LISTA, porque a base já tem pessoa ligada a empresa.
    Ninguém consulta empresa por empresa.

    Aqui vale o mesmo: o cache tem `empresa_norm`, então N empresas custam uma
    query. Na Bright Data isso não dá — o `or` de lá aceita no máximo 4 termos.
    """
    alvos = [norm(e) for e in (empresas or []) if norm(e)]
    if not alvos:
        return []
    # OR de LIKE: "movida" tem que casar "Movida Aluguel de Carros" e
    # "Grupo Movida", igual ao `includes` que trouxe esses perfis.
    ors = " OR ".join(["empresa_norm LIKE ?"] * len(alvos))
    sql = ["SELECT * FROM perfis WHERE (%s)" % ors]
    args: list[Any] = ["%" + a + "%" for a in alvos]
    if pais:
        sql.append("AND pais = ?")
        args.append(pais.upper()[:2])
    if departamento:
        sql.append("AND departamento = ?")
        args.append(departamento)
    if senioridade:
        sql.append("AND senioridade = ?")
        args.append(senioridade)
    # Decisor primeiro, depois quem tem foto: é a ordem em que a operação usa.
    sql.append("""ORDER BY CASE WHEN senioridade='Decisores' THEN 0 ELSE 1 END,
                           (foto IS NULL OR foto=''), visto_em DESC LIMIT ?""")
    # Pede mais do que o limite porque o casamento por palavra abaixo descarta:
    # sem isso, o ruído comeria as vagas e a lista voltaria curta.
    args.append(int(limite) * 4)
    con = _con()
    linhas = con.execute(" ".join(sql), args).fetchall()
    con.close()

    # O LIKE acima casa SUBSTRING, e isso traz ruído real: "Localiza" pega
    # "Maxlocaliza Rastreamento", "Natura" pega "Natural Sabore Alimentos".
    # Aqui separamos por PALAVRA INTEIRA e marcamos qual empresa casou, para a
    # tela poder mostrar o parecido em cinza em vez de misturar com o certo.
    exatas, parecidas = [], []
    for r in linhas:
        d = dict(r)
        emp = " %s " % (d.get("empresa_norm") or "")
        casou = next((a for a in alvos if (" %s " % a) in emp), None)
        d["empresa_casada"] = casou or ""
        d["exata"] = bool(casou)
        (exatas if casou else parecidas).append(d)
    return (exatas + parecidas)[:int(limite)]


def cobertura_empresas(empresas: list[str], pais: str = "") -> list[dict[str, Any]]:
    """Quantos perfis já temos de cada empresa da lista — e quantos são decisores.

    Serve para a tela dizer, ANTES de gastar, quais empresas já estão cobertas e
    quais precisam ir à Bright Data.
    """
    saida = []
    con = _con()
    for e in (empresas or []):
        alvo = norm(e)
        if not alvo:
            continue
        args: list[Any] = ["%" + alvo + "%"]
        extra = ""
        if pais:
            extra = " AND pais = ?"
            args.append(pais.upper()[:2])
        # Conta por PALAVRA INTEIRA, nao por substring: contar "Maxlocaliza"
        # como cobertura de "Localiza" faria a tela achar que ja tem a empresa e
        # nunca buscar a de verdade.
        linhas = con.execute(
            "SELECT empresa_norm, senioridade FROM perfis WHERE empresa_norm LIKE ?"
            + extra, args).fetchall()
        marca = " %s " % alvo
        casadas = [x for x in linhas if marca in (" %s " % (x[0] or ""))]
        saida.append({
            "empresa": e,
            "perfis": len(casadas),
            "decisores": sum(1 for x in casadas if x[1] == "Decisores"),
            "parecidos_ignorados": len(linhas) - len(casadas),
        })
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
        INSERT INTO empresas (url,nome,company_id,funcionarios,setor,sede,site,pais,
                              visto_em,cnpj,cnpj_confianca)
        VALUES (?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(url) DO UPDATE SET
          nome=excluded.nome, company_id=excluded.company_id,
          funcionarios=excluded.funcionarios, setor=excluded.setor,
          sede=excluded.sede, site=excluded.site, pais=excluded.pais,
          visto_em=excluded.visto_em,
          -- CNPJ so e sobrescrito por CNPJ: uma releitura que nao conseguiu
          -- deduzir nao pode apagar a deducao boa da vez anterior.
          cnpj=COALESCE(NULLIF(excluded.cnpj,''), empresas.cnpj),
          cnpj_confianca=CASE WHEN NULLIF(excluded.cnpj,'') IS NOT NULL
                              THEN excluded.cnpj_confianca
                              ELSE empresas.cnpj_confianca END
    """, (url, d.get("nome"), d.get("company_id"), d.get("funcionarios_linkedin"),
          d.get("setor"), d.get("sede"), d.get("site"), d.get("pais"),
          int(time.time()), d.get("cnpj") or "", d.get("cnpj_confianca") or ""))
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


def ufs_disponiveis() -> list[dict[str, Any]]:
    """UFs presentes no cache, com contagem. Alimenta o select da tela — só
    oferece UF que tem gente, para o filtro não devolver zero por opção morta."""
    con = _con()
    linhas = con.execute("""SELECT uf, COUNT(*) n FROM perfis
                            WHERE pais='BR' AND uf IS NOT NULL AND uf<>''
                            GROUP BY uf ORDER BY n DESC""").fetchall()
    sem = con.execute("SELECT COUNT(*) FROM perfis WHERE pais='BR' "
                      "AND (uf IS NULL OR uf='')").fetchone()[0]
    con.close()
    return [{"uf": r[0], "perfis": r[1]} for r in linhas] + \
           [{"uf": "", "perfis": sem, "rotulo": "sem UF identificada"}]


def resumo_gastos(desde_ts: int = 0, ate_ts: int = 0) -> dict[str, Any]:
    """Quanto a Bright Data custou no período, por tipo e por dia.

    Também devolve `economia_usd`: o que o cache serviu de graça. Os dois números
    juntos são a única forma honesta de mostrar o custo — só o gasto sugeriria
    que cada busca cobra, e só a economia sugeriria que nada cobra.
    """
    con = _con()
    onde, args = "WHERE 1=1", []
    if desde_ts:
        onde += " AND quando >= ?"
        args.append(int(desde_ts))
    if ate_ts:
        onde += " AND quando <= ?"
        args.append(int(ate_ts))

    tot = con.execute("""SELECT COALESCE(SUM(custo_usd),0), COALESCE(SUM(economia_usd),0),
                                COALESCE(SUM(registros),0), COUNT(*)
                         FROM gastos_bd %s""" % onde, args).fetchone()
    por_tipo = con.execute("""SELECT tipo, COUNT(*) n, COALESCE(SUM(registros),0) r,
                                     COALESCE(SUM(custo_usd),0) c,
                                     COALESCE(SUM(economia_usd),0) e
                              FROM gastos_bd %s GROUP BY tipo
                              ORDER BY c DESC""" % onde, args).fetchall()
    por_dia = con.execute("""SELECT date(quando,'unixepoch','localtime') d,
                                    COALESCE(SUM(custo_usd),0) c,
                                    COALESCE(SUM(registros),0) r
                             FROM gastos_bd %s GROUP BY d
                             ORDER BY d DESC LIMIT 60""" % onde, args).fetchall()
    por_usuario = con.execute("""SELECT COALESCE(NULLIF(usuario,''),'(não identificado)') u,
                                        COUNT(*) n, COALESCE(SUM(custo_usd),0) c,
                                        COALESCE(SUM(registros),0) r
                                 FROM gastos_bd %s AND custo_usd > 0
                                 GROUP BY u ORDER BY c DESC""" % onde, args).fetchall()
    ultimos = con.execute("""SELECT quando, usuario, tipo, detalhe, registros,
                                    custo_usd, economia_usd
                             FROM gastos_bd %s ORDER BY quando DESC LIMIT 40""" % onde,
                          args).fetchall()
    con.close()
    return {
        "gasto_usd": round(tot[0], 4),
        "economia_usd": round(tot[1], 4),
        "registros": tot[2],
        "chamadas": tot[3],
        "usd_por_registro": USD_POR_REGISTRO,
        "por_tipo": [{"tipo": r[0], "chamadas": r[1], "registros": r[2],
                      "gasto_usd": round(r[3], 4), "economia_usd": round(r[4], 4)}
                     for r in por_tipo],
        "por_dia": [{"dia": r[0], "gasto_usd": round(r[1], 4), "registros": r[2]}
                    for r in por_dia],
        "por_usuario": [{"usuario": r[0], "chamadas": r[1],
                         "gasto_usd": round(r[2], 4), "registros": r[3]}
                        for r in por_usuario],
        "ultimos": [{"quando": r[0], "usuario": r[1], "tipo": r[2], "detalhe": r[3],
                     "registros": r[4], "gasto_usd": round(r[5] or 0, 4),
                     "economia_usd": round(r[6] or 0, 4)} for r in ultimos],
    }
