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
  visto_em   INTEGER,
  -- Só para ALERTA do sistema. É a identidade do PROBLEMA, não da
  -- ocorrência: "descritores do capiblu-data". Enquanto o problema durar, a
  -- mesma linha é atualizada em vez de nascer uma nova a cada verificação --
  -- senão um alarme de dez em dez minutos viraria 144 avisos por dia do
  -- mesmo assunto, e ninguém leria nenhum.
  chave      TEXT,
  medida     TEXT           -- o número que disparou, para dar dimensão
);
CREATE INDEX IF NOT EXISTS ix_ch_status ON chamados(status);
CREATE INDEX IF NOT EXISTS ix_ch_criado ON chamados(criado_em);
"""

STATUS = ("aberto", "visto", "resolvido")
# `alerta` é o sistema falando de si mesmo. Entra na MESMA lista e na
# mesma bolinha: quem cuida da ferramenta olha um lugar só, e um alarme
# num canto que ninguém abre é um alarme que não existe.
TIPOS = ("bug", "melhoria", "alerta")


def _con():
    os.makedirs(os.path.dirname(DB) or ".", exist_ok=True)
    con = sqlite3.connect(DB, timeout=5)
    con.row_factory = sqlite3.Row
    con.executescript(DDL)
    # COLUNAS NOVAS EM TABELA QUE JÁ EXISTE. `CREATE TABLE IF NOT EXISTS` não
    # altera nada quando a tabela está lá -- o banco de produção já tinha
    # chamados reais quando `chave` e `medida` foram criadas, e sem isto a
    # primeira gravação de alerta quebraria com "no such column".
    tem = {r[1] for r in con.execute("PRAGMA table_info(chamados)")}
    for coluna in ("chave", "medida"):
        if coluna not in tem:
            con.execute("ALTER TABLE chamados ADD COLUMN %s TEXT" % coluna)
    con.execute("CREATE UNIQUE INDEX IF NOT EXISTS ix_ch_chave ON chamados(chave) "
                "WHERE chave IS NOT NULL AND chave <> ''")
    con.commit()
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
                # Só alerta tem. É o número que disparou -- "1023 de 1024" diz
                # muito mais que "descritores acabando".
                "medida": (l["medida"] if "medida" in l.keys() else "") or "",
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


def alertar(chave: str, titulo: str, descricao: str = "",
            medida: str = "") -> dict[str, Any]:
    """Abre (ou atualiza) UM alerta do sistema.

    A `chave` identifica o PROBLEMA, não a ocorrência. Enquanto ele durar, a
    verificação passa aqui a cada ciclo e a mesma linha é atualizada -- um
    alarme de dez em dez minutos viraria 144 avisos por dia do mesmo assunto,
    e ninguém leria nenhum.

    Um alerta que estava `resolvido` e volta a acontecer REABRE. Isso importa:
    problema que retorna é informação diferente de problema novo, e deixá-lo
    fechado esconderia justamente o caso que mais merece atenção.
    """
    chave = _limpo(chave, 80)
    if not chave:
        return {"status": "error", "message": "Alerta sem chave."}
    agora = int(time.time())
    con = _con()
    r = con.execute("SELECT id, status FROM chamados WHERE chave=?",
                    (chave,)).fetchone()
    if r:
        con.execute(
            """UPDATE chamados SET titulo=?, descricao=?, medida=?,
                 status=CASE WHEN status='resolvido' THEN 'aberto' ELSE status END,
                 criado_em=CASE WHEN status='resolvido' THEN ? ELSE criado_em END
               WHERE chave=?""",
            (_limpo(titulo, 160), _limpo(descricao, 4000), _limpo(medida, 80),
             agora, chave))
        con.commit()
        ident, reaberto = r["id"], (r["status"] == "resolvido")
    else:
        ident = uuid.uuid4().hex[:12]
        con.execute(
            """INSERT INTO chamados (id,tipo,titulo,descricao,aba,contexto,
                                     usuario,status,anexos,criado_em,chave,medida)
               VALUES (?,'alerta',?,?,'','','sistema','aberto','',?,?,?)""",
            (ident, _limpo(titulo, 160), _limpo(descricao, 4000), agora,
             chave, _limpo(medida, 80)))
        con.commit()
        reaberto = False
    con.close()
    return {"status": "ok", "id": ident, "reaberto": reaberto, "novo": not r}


def resolver_alerta(chave: str) -> bool:
    """Fecha sozinho quando o problema passou.

    Sem isto o painel acumularia alarmes de coisas que já se resolveram, e a
    bolinha vermelha viraria decoração -- o operador aprende a ignorá-la, e aí
    o próximo alarme de verdade também é ignorado.
    """
    try:
        con = _con()
        n = con.execute(
            "UPDATE chamados SET status='resolvido', visto_em=? "
            "WHERE chave=? AND status<>'resolvido'",
            (int(time.time()), _limpo(chave, 80))).rowcount
        con.commit()
        con.close()
        return bool(n)
    except Exception:
        return False
