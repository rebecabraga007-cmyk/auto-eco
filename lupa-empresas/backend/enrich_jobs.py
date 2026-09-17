# -*- coding: utf-8 -*-
"""O enriquecimento roda no SERVIDOR. A aba vira espectadora.

O QUE ISTO RESOLVE
------------------
A Cloudflare corta requisicao em ~100 segundos e devolve uma pagina de erro
HTML. Ate aqui eu contornava isso mantendo cada requisicao curta -- ondas de
55s emendadas pelo navegador -- e funcionava, mas o contorno tinha um preco
escondido: o trabalho so existia enquanto a aba existisse. Fechou no meio,
perdeu as linhas daquele lote. E linha perdida aqui e consulta PAGA perdida.

Com job, nao ha o que contornar. O `POST` cria o trabalho e responde na hora
com um id; o processamento roda num `asyncio.Task` que nao tem requisicao
nenhuma pendurada nele e pode levar quarenta minutos. O navegador so pergunta
"em que pe esta?" -- e pode nem perguntar.

AS TRES COISAS QUE FAZEM ISSO SER CONFIAVEL
-------------------------------------------
1. CADA ONDA VAI PARA O DISCO na hora, num `.jsonl` proprio do job. Nao e
   detalhe de arrumacao: um deploy no meio de um job de 2.000 linhas mataria
   o processo, e sem isso morreria junto tudo que ja foi consultado e pago.
   Com o arquivo, o retomar sabe exatamente onde parar de repetir.

2. UM JOB DE CADA VEZ (semaforo em `main.py`). Tres pessoas enriquecendo ao
   mesmo tempo batiam na Assertiva em paralelo, sem nada segurando. A fila
   troca "todo mundo lento e a fornecedora reclamando" por "um rapido e os
   outros com hora prevista".

3. CANCELAR E UM PEDIDO GRAVADO, nao uma variavel na memoria. Quem clica em
   parar pode estar em outro computador, e a variavel morreria com o
   processo. O trabalhador le a flag no comeco de cada onda.
"""
import json
import os
import re
import sqlite3
import time
import uuid

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "enrich_jobs.db")
PARCIAIS = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI),
                        "enrich_jobs_parciais")

# fila -> processando -> concluido | erro | cancelado
DDL = """
CREATE TABLE IF NOT EXISTS enrich_job (
  id            TEXT PRIMARY KEY,
  usuario       TEXT,
  nome          TEXT,
  status        TEXT DEFAULT 'fila',
  total         INTEGER DEFAULT 0,   -- linhas que o job vai processar
  feitas        INTEGER DEFAULT 0,
  com_decisor   INTEGER DEFAULT 0,
  sem_telefone  INTEGER DEFAULT 0,
  pedido        TEXT,                -- JSON: o corpo original da tela
  colunas       TEXT,                -- JSON [{key,label}] do resultado
  erro          TEXT,
  cancelar      INTEGER DEFAULT 0,   -- pedido de parada, lido a cada onda
  quer_email    INTEGER DEFAULT 0,
  enriquecimento_id TEXT,            -- o arquivo final, em `enriquecimentos`
  criado_em     INTEGER,
  atualizado_em INTEGER,
  terminado_em  INTEGER
);
CREATE INDEX IF NOT EXISTS ix_job_user ON enrich_job(usuario, criado_em DESC);
CREATE INDEX IF NOT EXISTS ix_job_status ON enrich_job(status);
"""


def _con():
    """Conexao que FECHA -- `with sqlite3.connect()` faz commit, nao fecha.

    Ja custou caro neste projeto: 1023 descritores vazados derrubaram o
    servico inteiro com 502 e nenhum erro no log.
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
    os.makedirs(PARCIAIS, exist_ok=True)


_init()


def _valido(jid: str) -> bool:
    return bool(re.fullmatch(r"[0-9a-f]{6,40}", str(jid or "")))


def _arquivo(jid: str) -> str:
    return os.path.join(PARCIAIS, "%s.jsonl" % jid)


def criar(usuario: str, nome: str, pedido: dict, total: int,
          quer_email: bool = False) -> str:
    jid = uuid.uuid4().hex[:12]
    agora = int(time.time())
    c = _con()
    try:
        c.execute(
            "INSERT INTO enrich_job (id, usuario, nome, status, total, pedido,"
            " quer_email, criado_em, atualizado_em)"
            " VALUES (?,?,?,'fila',?,?,?,?,?)",
            (jid, (usuario or "").strip().lower(), (nome or "").strip()[:120],
             int(total or 0), json.dumps(pedido or {}, ensure_ascii=False),
             1 if quer_email else 0, agora, agora))
        c.commit()
    finally:
        c.close()
    return jid


def pegar(jid: str, usuario: str = "", admin: bool = False) -> dict:
    """Um job. Sem admin, so o dono ve -- o progresso revela o que a outra
    pessoa esta prospectando."""
    if not _valido(jid):
        return None
    c = _con()
    try:
        r = c.execute("SELECT * FROM enrich_job WHERE id = ?", (jid,)).fetchone()
    finally:
        c.close()
    if not r:
        return None
    if usuario and not admin and (r["usuario"] or "") != usuario.strip().lower():
        return None
    d = dict(r)
    d["pedido"] = json.loads(r["pedido"] or "{}")
    d["colunas"] = json.loads(r["colunas"] or "[]")
    d["cancelar"] = bool(r["cancelar"])
    d["quer_email"] = bool(r["quer_email"])
    return d


def em_andamento(usuario: str) -> list:
    """Os jobs vivos desta pessoa.

    A tela chama isso ao abrir: quem fechou a aba e voltou precisa reencontrar
    o trabalho andando, senao conclui que morreu e manda rodar de novo --
    pagando tudo duas vezes.
    """
    c = _con()
    try:
        rs = c.execute(
            "SELECT * FROM enrich_job WHERE usuario = ?"
            " AND status IN ('fila','processando') ORDER BY criado_em",
            ((usuario or "").strip().lower(),)).fetchall()
    finally:
        c.close()
    return [{"id": r["id"], "nome": r["nome"], "status": r["status"],
             "total": r["total"], "feitas": r["feitas"],
             "criado_em": r["criado_em"]} for r in rs]


def listar(usuario: str, admin: bool = False, limite: int = 30) -> list:
    c = _con()
    try:
        if admin:
            rs = c.execute("SELECT * FROM enrich_job ORDER BY criado_em DESC"
                           " LIMIT ?", (int(limite),)).fetchall()
        else:
            rs = c.execute("SELECT * FROM enrich_job WHERE usuario = ?"
                           " ORDER BY criado_em DESC LIMIT ?",
                           ((usuario or "").strip().lower(), int(limite))).fetchall()
    finally:
        c.close()
    return [dict(r) for r in rs]


def pendentes() -> list:
    """Jobs que o processo anterior deixou pelo caminho.

    Chamado uma vez, na subida. Sem isso, um deploy no meio de um job deixaria
    o trabalho em 'processando' para sempre: a tela mostraria uma barra que
    nunca anda e ninguem saberia dizer se ainda esta rodando.
    """
    c = _con()
    try:
        rs = c.execute("SELECT id FROM enrich_job WHERE status IN"
                       " ('fila','processando') ORDER BY criado_em").fetchall()
    finally:
        c.close()
    return [r["id"] for r in rs]


def marcar(jid: str, **campos) -> None:
    if not campos:
        return
    campos["atualizado_em"] = int(time.time())
    sets = ", ".join("%s = ?" % k for k in campos)
    c = _con()
    try:
        c.execute("UPDATE enrich_job SET %s WHERE id = ?" % sets,
                  tuple(campos.values()) + (jid,))
        c.commit()
    finally:
        c.close()


def pedir_cancelamento(jid: str, usuario: str, admin: bool = False) -> bool:
    d = pegar(jid, usuario, admin)
    if not d or d["status"] not in ("fila", "processando"):
        return False
    marcar(jid, cancelar=1)
    return True


def quer_parar(jid: str) -> bool:
    """Lido no comeco de cada onda -- e do BANCO, nao da memoria.

    Quem clicou em parar pode estar em outro computador, ou em outra aba. Uma
    variavel de processo nao atravessa nada disso.
    """
    c = _con()
    try:
        r = c.execute("SELECT cancelar FROM enrich_job WHERE id = ?",
                      (jid,)).fetchone()
    finally:
        c.close()
    return bool(r and r["cancelar"])


def anexar(jid: str, linhas: list) -> None:
    """Grava a onda no disco ANTES de contar como feita.

    A ordem importa: se contasse primeiro e o processo morresse no meio da
    escrita, o job diria "80 prontas" com 70 no arquivo, e as 10 no vao
    seriam consultas pagas que ninguem sabe que existiram.
    """
    if not linhas:
        return
    os.makedirs(PARCIAIS, exist_ok=True)
    with open(_arquivo(jid), "a", encoding="utf-8") as f:
        for l in linhas:
            f.write(json.dumps(l, ensure_ascii=False, default=str) + "\n")
        f.flush()
        os.fsync(f.fileno())


def ja_feitas(jid: str) -> int:
    """Quantas linhas ja estao no disco. E por onde o retomar comeca."""
    try:
        with open(_arquivo(jid), encoding="utf-8") as f:
            return sum(1 for _ in f)
    except OSError:
        return 0


def ler(jid: str, limite: int = 0) -> list:
    linhas = []
    try:
        with open(_arquivo(jid), encoding="utf-8") as f:
            for n, l in enumerate(f):
                if limite and n >= limite:
                    break
                try:
                    linhas.append(json.loads(l))
                except ValueError:
                    continue      # linha meio escrita numa morte feia
    except OSError:
        pass
    return linhas


def encolher_parcial(jid: str, manter: int = 300) -> None:
    """Depois do XLSX gravado, o parcial vira so a PREVIA.

    Nao apago inteiro, e isso foi um erro que cometi e o teste pegou: apagar
    deixava a tela sem nada para mostrar assim que o job terminava -- a
    pessoa via "concluido" e uma tabela vazia, como se o trabalho tivesse
    sumido.

    Tambem nao guardo tudo: enquanto o job corria este arquivo ERA o
    trabalho, mas depois do XLSX ele passa a ser copia, e copia de 2.000
    linhas em JSON ocupa disco para mostrar as 300 primeiras que a tela
    desenha.
    """
    caminho = _arquivo(jid)
    try:
        with open(caminho, encoding="utf-8") as f:
            cabeca = [next(f) for _ in range(manter)]
    except StopIteration:
        return                     # tinha menos que o teto: fica como esta
    except OSError:
        return
    tmp = caminho + ".parcial"
    try:
        with open(tmp, "w", encoding="utf-8") as f:
            f.writelines(cabeca)
        os.replace(tmp, caminho)
    except OSError:
        try:
            os.remove(tmp)
        except OSError:
            pass


def limpar_parcial(jid: str) -> None:
    """Apaga de vez -- so quando o enriquecimento inteiro e apagado."""
    try:
        os.remove(_arquivo(jid))
    except OSError:
        pass
