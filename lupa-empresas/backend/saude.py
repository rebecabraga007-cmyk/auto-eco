# -*- coding: utf-8 -*-
"""Vigia o proprio sistema e abre alerta antes de ele cair.

POR QUE EXISTE
--------------
Em 14/set/2026 o servico passou TRES DIAS quebrando em silencio: um vazamento
de conexao SQLite consumiu 1023 dos 1024 descritores, e a partir dai nenhuma
chamada externa conseguia abrir socket. A Rebeca viu 502; o log do servico
nao tinha um unico erro, porque do ponto de vista dele cada requisicao
terminava normalmente. So a contagem de `/proc/<pid>/fd` denunciou.

Descobrimos porque alguem reclamou. Este arquivo troca isso por "o sistema
vai cair na quinta".

RODA FORA DO APP, DE PROPOSITO
------------------------------
E um script chamado por um timer do systemd, e nao uma tarefa dentro do
processo. Um vigia que mora dentro do que ele vigia para junto -- e o modo de
falha que mais interessa aqui e exatamente esse: o app vivo, respondendo, e
incapaz de abrir qualquer coisa nova.

O QUE ELE NAO FAZ
-----------------
Nao tenta consertar nada. Medir e avisar e o trabalho todo; reiniciar
servico sozinho esconderia a causa e transformaria um vazamento diario numa
rotina invisivel.
"""
import os
import shutil
import subprocess
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chamados

SERVICOS = ("capiblu-data", "capiblu-app", "bluutime")

# Distribuidor de leads (Rails do João, migrado para esta VPS) e os gateways do WhatsApp dele.
# Vigiados SO quando `enabled`: antes do corte eles ficam disabled de proposito (nao podem rodar
# ao mesmo tempo que o Render), e alerta de "fora do ar" ali seria ruido. No corte o
# `systemctl enable --now` os coloca aqui sozinhos; num rollback, o disable fecha o alerta.
SERVICOS_SE_HABILITADOS = (
    "distribuidor-global", "distribuidor-movida", "cloudflared-distribuidor",
    "wa-gateway-maicon", "wa-gateway-marlon", "wa-gateway-eduarda",
    "wa-gateway-luan", "wa-gateway-pedro",
)

# Backup noturno do Postgres do distribuidor (distribuidor-backup-pg.timer).
BACKUP_DIR = "/var/backups/distribuidor-pg"
BACKUP_BANCOS = ("global_america", "distribuidor_leads")
BACKUP_MAX_HORAS = 30      # roda 1x/dia; 30h da folga para um atraso sem virar alerta falso

# Quando avisar. Os numeros vem do incidente: o limite antigo era 1024 e a
# queda veio sem aviso nenhum. 60% da margem para varios dias de folga --
# o vazamento levou tres dias para encher, entao um alerta aos 60% chegaria
# no primeiro dia.
TETO_FD = 0.60
TETO_DISCO = 0.88          # acima disso a ingestao da Receita ja nao cabe
MIN_LIVRE_GB = 12          # um rebuild do indice de dominios precisa disso


def _fds(servico: str) -> dict:
    """Descritores usados e o limite, para um servico do systemd."""
    try:
        pid = subprocess.run(["systemctl", "show", "-p", "MainPID", "--value",
                              servico], capture_output=True, text=True,
                             timeout=10).stdout.strip()
        if not pid or pid == "0":
            return {"ativo": False}
        usados = len(os.listdir("/proc/%s/fd" % pid))
        limite = 0
        with open("/proc/%s/limits" % pid) as f:
            for linha in f:
                if linha.startswith("Max open files"):
                    limite = int(linha.split()[3])
                    break
        return {"ativo": True, "pid": pid, "usados": usados, "limite": limite,
                "fracao": (usados / limite) if limite else 0.0}
    except Exception as exc:
        return {"ativo": False, "erro": str(exc)[:120]}


def _ativo(servico: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-active", servico],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "active"
    except Exception:
        return False


def _habilitado(unidade: str) -> bool:
    try:
        r = subprocess.run(["systemctl", "is-enabled", unidade],
                           capture_output=True, text=True, timeout=10)
        return r.stdout.strip() == "enabled"
    except Exception:
        return False


def _backups() -> dict:
    """Idade (h) do dump mais novo de cada banco; None = nenhum dump."""
    idades = {}
    for banco in BACKUP_BANCOS:
        try:
            arqs = [os.path.join(BACKUP_DIR, a) for a in os.listdir(BACKUP_DIR)
                    if a.startswith(banco + "-") and a.endswith(".dump")]
            idades[banco] = ((time.time() - max(os.path.getmtime(a) for a in arqs)) / 3600
                             if arqs else None)
        except FileNotFoundError:
            idades[banco] = None
    return idades


def medir() -> dict:
    dados = {"servicos": {}, "quando": int(time.time())}
    for s in SERVICOS:
        dados["servicos"][s] = {"ativo": _ativo(s), **_fds(s)}
    for s in SERVICOS_SE_HABILITADOS:
        if _habilitado(s):
            dados["servicos"][s] = {"ativo": _ativo(s), **_fds(s)}
        else:
            dados["servicos"][s] = {"ativo": True, "desligado_de_proposito": True}
    dados["backups"] = _backups() if _habilitado("distribuidor-backup-pg.timer") else {}
    try:
        uso = shutil.disk_usage("/")
        dados["disco"] = {"total_gb": uso.total / 1e9, "livre_gb": uso.free / 1e9,
                          "fracao": uso.used / uso.total}
    except Exception:
        dados["disco"] = {}
    return dados


def verificar(silencioso: bool = False) -> dict:
    """Mede, abre o que estiver ruim e FECHA o que voltou ao normal."""
    d = medir()
    abertos, fechados = [], []

    def avisa(chave, ok, titulo, descricao, medida):
        if ok:
            if chamados.resolver_alerta(chave):
                fechados.append(chave)
        else:
            chamados.alertar(chave, titulo, descricao, medida)
            abertos.append(chave)

    for s, info in d["servicos"].items():
        avisa("servico:%s" % s, info.get("ativo"),
              "Serviço %s está fora do ar" % s,
              "O systemd não reporta este serviço como ativo. Enquanto isso, "
              "a parte do CapiBLU que depende dele não responde.",
              "inativo")
        if not info.get("ativo") or not info.get("limite") or info.get("desligado_de_proposito"):
            continue
        frac = info.get("fracao") or 0
        avisa(
            "fd:%s" % s, frac < TETO_FD,
            "Descritores de arquivo subindo em %s" % s,
            "Este serviço está segurando %d arquivos/conexões abertos de um "
            "teto de %d. Foi exatamente assim que o sistema caiu em "
            "14/set/2026: ao chegar no teto, nenhuma chamada externa consegue "
            "mais abrir socket — a BrasilAPI falha, a Meetime falha, e a tela "
            "mostra 502 SEM nenhum erro no log. Costuma ser conexão de banco "
            "aberta e não fechada.\n\n"
            "Para ver o que está aberto:\n"
            "  ls -l /proc/%s/fd | awk '{print $NF}' | sort | uniq -c | sort -rn | head"
            % (info["usados"], info["limite"], info.get("pid", "<pid>")),
            "%d de %d (%.0f%%)" % (info["usados"], info["limite"], frac * 100))

    disco = d.get("disco") or {}
    if disco:
        livre = disco.get("livre_gb", 0)
        avisa("disco", disco.get("fracao", 0) < TETO_DISCO and livre > MIN_LIVRE_GB,
              "Disco do servidor enchendo",
              "Restam %.0f GB de %.0f GB. Abaixo de %d GB não cabe reconstruir "
              "o índice de domínios nem reingerir a base da Receita, e a "
              "ingestão falha no meio."
              % (livre, disco.get("total_gb", 0), MIN_LIVRE_GB),
              "%.0f GB livres (%.0f%% usado)"
              % (livre, disco.get("fracao", 0) * 100))

    for banco, horas in (d.get("backups") or {}).items():
        avisa("backup:%s" % banco, horas is not None and horas < BACKUP_MAX_HORAS,
              "Backup do banco %s atrasado" % banco,
              "O dump noturno do Postgres do distribuidor não aparece em %s há mais de %dh. "
              "Depois do corte este banco só existe nesta VPS; sem dump recente, a volta de "
              "um erro depende só do snapshot diário do disco da Hetzner.\n\n"
              "Ver: journalctl -u distribuidor-backup-pg"
              % (BACKUP_DIR, BACKUP_MAX_HORAS),
              "nenhum dump" if horas is None else "último há %.0fh" % horas)

    if not silencioso:
        print("verificado em %s" % time.strftime("%d/%m %H:%M"))
        for s, i in d["servicos"].items():
            if i.get("desligado_de_proposito"):
                print("  %-14s desligado (fora da vigia ate o enable)" % s)
            elif i.get("ativo") and i.get("limite"):
                print("  %-14s %5d/%d descritores (%.0f%%)"
                      % (s, i["usados"], i["limite"], (i["fracao"] or 0) * 100))
            else:
                print("  %-14s INATIVO" % s)
        if disco:
            print("  %-14s %.0f GB livres (%.0f%% usado)"
                  % ("disco", disco.get("livre_gb", 0),
                     disco.get("fracao", 0) * 100))
        for banco, horas in (d.get("backups") or {}).items():
            print("  %-14s %s" % ("bkp " + banco[:10],
                                   "nenhum dump" if horas is None else "ultimo ha %.1fh" % horas))
        print("  alertas abertos: %s" % (", ".join(abertos) or "nenhum"))
        print("  alertas fechados: %s" % (", ".join(fechados) or "nenhum"))
    return {"abertos": abertos, "fechados": fechados, "medida": d}


if __name__ == "__main__":
    verificar(silencioso="--quieto" in sys.argv)
