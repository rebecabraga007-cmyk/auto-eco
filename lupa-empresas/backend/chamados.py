# -*- coding: utf-8 -*-
"""Chamados: bug e pedido de melhoria abertos pelo proprio usuario.

POR QUE ISTO NAO E "SO UM FORMULARIO"
-------------------------------------
Hoje o que a operacao percebe de errado chega por WhatsApp, no meio de outra
conversa, sem print e sem contexto -- e quem recebe reconstroi de memoria em
que tela aquilo acontecia. Metade do trabalho de consertar e descobrir onde.

Por isso o registro guarda, junto com o texto, a ABA em que a pessoa estava e
os FILTROS que ela tinha na tela. E o mesmo motivo de aceitar print: "digitei
alimentos e veio empresa de outra area" vira um caso reproduzivel quando a
imagem mostra o que estava marcado.

O ANEXO FICA NO DISCO, NAO NO BANCO
-----------------------------------
Print de tela tem 200 KB a 2 MB. Guardado como base64 numa coluna, ele entra
em toda leitura da lista de chamados -- a tela do admin ficaria pesada
proporcionalmente ao tamanho das imagens, e nao ao numero de chamados. Fica
em arquivo, e o banco guarda so o nome.

O QUE E DELIBERADAMENTE SIMPLES
-------------------------------
Sem prioridade, sem responsavel, sem SLA. Um chamado esta `aberto`, `visto` ou
`resolvido`. Campo que ninguem preenche vira ruido, e a operacao tem uma
pessoa cuidando disso, nao um time de suporte.
"""
import os
import re
import sqlite3
import time
import uuid
from typing import Any

_AQUI = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "chamados.db")
ANEXOS = os.path.join(os.environ.get("CAPIBLU_DATA_DIR", _AQUI), "chamados_anexos")

# Um print de tela raramente passa disso. O teto existe para um upload
# acidental de video ou PDF gigante nao encher o disco do servidor.
MAX_ANEXO = 6 * 1024 * 1024
MAX_ANEXOS = 4
TIPOS_IMAGEM = {"image/png": ".png", "image/jpeg": ".jpg", "image/webp": ".webp",
                "image/gif": ".gif"}

DDL = """
CREATE TABLE IF NOT EXISTS chamados (
  id         TEXT PRIMARY KEY,
  tipo       TEXT,          -- bug | melhoria
  titulo     TEXT,
  descricao  TEXT,
  aba        TEXT,          -- onde a pessoa estava
  contexto   TEXT,          -- filtros/estado da tela, em JSON
  usuario    TEXT,
  status     TEXT DEFAULT 'aberto',
  resposta   TEXT,
  anexos     TEXT,          -- nomes de arquivo, separados por vírgula
  criado_em  INTEGER,
  visto_em   INTEGER
);
CREATE INDEX IF NOT EXISTS ix_ch_status ON chamados(status);
CREATE INDEX IF NOT EXISTS ix_ch_criado ON chamados(criado_em);
"""

STATUS = ("aberto", "visto", "resolvido")
TIPOS = ("bug", "melhoria")


def _con():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    return con


def _limpo(s: Any, teto: int = 4000) -> str:
    return re.sub(r"\s+", " ", str(s or "")).strip()[:teto]


def abrir(tipo: str, titulo: str, descricao: str, usuario: str = "",
          aba: str = "", contexto: str = "", anexos: list | None = None
          ) -> dict[str, Any]:
    tipo = tipo if tipo in TIPOS else "bug"
    titulo = _limpo(titulo, 160)
    descricao = _limpo(descricao, 6000)
    if not titulo and not descricao:
        return {"status": "error", "message": "Escreva o que aconteceu."}
    if not titulo:
        # Sem titulo o chamado vira uma linha vazia na lista do admin. Usa o
        # comeco da descricao, que e melhor que "(sem titulo)".
        titulo = descricao[:80]
    ident = uuid.uuid4().hex[:12]
    con = _con()
    con.execute(
        """INSERT INTO chamados (id,tipo,titulo,descricao,aba,contexto,usuario,
                                 status,anexos,criado_em)
           VALUES (?,?,?,?,?,?,?,'aberto',?,?)""",
        (ident, tipo, titulo, descricao, _limpo(aba, 60),
         _limpo(contexto, 4000), _limpo(usuario, 160),
         ",".join(anexos or []), int(time.time())))
    con.commit()
    con.close()
    return {"status": "ok", "id": ident}


def salvar_anexo(nome: str, conteudo: bytes, mime: str) -> str:
    """Grava um print e devolve o nome interno. Vazio quando recusado.

    O nome de arquivo e gerado aqui e NAO vem do cliente: nome vindo de fora
    e caminho vindo de fora, e caminho vindo de fora e travessia de diretorio.
    A extensao sai do MIME que reconhecemos, nao do que o arquivo diz ser.
    """
    if not conteudo or len(conteudo) > MAX_ANEXO:
        return ""
    ext = TIPOS_IMAGEM.get((mime or "").split(";")[0].strip().lower())
    if not ext:
        return ""
    os.makedirs(ANEXOS, exist_ok=True)
    interno = uuid.uuid4().hex + ext
    with open(os.path.join(ANEXOS, interno), "wb") as f:
        f.write(conteudo)
    return interno


def listar(status: str = "", limite: int = 100) -> dict[str, Any]:
    con = _con()
    if status in STATUS:
        linhas = con.execute("SELECT * FROM chamados WHERE status=? "
                             "ORDER BY criado_em DESC LIMIT ?",
                             (status, limite)).fetchall()
    else:
        linhas = con.execute("SELECT * FROM chamados ORDER BY "
                             # aberto primeiro: o que precisa de acao fica no
                             # topo mesmo quando e mais antigo
                             "CASE status WHEN 'aberto' THEN 0 "
                             "WHEN 'visto' THEN 1 ELSE 2 END, criado_em DESC "
                             "LIMIT ?", (limite,)).fetchall()
    novos = con.execute("SELECT count(*) FROM chamados "
                        "WHERE status='aberto'").fetchone()[0]
    con.close()
    return {"status": "ok", "novos": novos,
            "chamados": [{
                "id": l["id"], "tipo": l["tipo"], "titulo": l["titulo"],
                "descricao": l["descricao"], "aba": l["aba"],
                "contexto": l["contexto"], "usuario": l["usuario"],
                "status_chamado": l["status"], "resposta": l["resposta"] or "",
                "anexos": [a for a in (l["anexos"] or "").split(",") if a],
                "criado_em": l["criado_em"],
            } for l in linhas]}


def contar_novos() -> int:
    """Só o número — é o que a bolinha vermelha precisa, e ela é consultada
    de tempos em tempos. Trazer a lista inteira para contar seria carregar
    todos os chamados a cada ciclo."""
    try:
        con = _con()
        n = con.execute("SELECT count(*) FROM chamados "
                        "WHERE status='aberto'").fetchone()[0]
        con.close()
        return int(n)
    except Exception:
        return 0


def marcar(ident: str, status: str, resposta: str = "") -> dict[str, Any]:
    if status not in STATUS:
        return {"status": "error", "message": "Status inválido."}
    con = _con()
    con.execute("UPDATE chamados SET status=?, resposta=COALESCE(NULLIF(?,''), "
                "resposta), visto_em=? WHERE id=?",
                (status, _limpo(resposta, 4000), int(time.time()), ident))
    con.commit()
    mudou = con.total_changes
    con.close()
    return {"status": "ok" if mudou else "not_found"}


def caminho_anexo(nome: str) -> str:
    """Caminho de um anexo, ou vazio.

    Confere que o nome e um dos que ESTE modulo gera (hex + extensao
    conhecida) antes de tocar no disco. Sem isso, "../../etc/passwd" chegando
    pela URL viraria leitura de arquivo do servidor.
    """
    if not re.fullmatch(r"[0-9a-f]{32}\.(png|jpg|webp|gif)", nome or ""):
        return ""
    caminho = os.path.join(ANEXOS, nome)
    return caminho if os.path.exists(caminho) else ""
