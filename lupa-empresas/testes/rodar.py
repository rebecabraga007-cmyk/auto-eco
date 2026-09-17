# -*- coding: utf-8 -*-
"""Roda a suite inteira. É o que corre antes de cada deploy.

    python testes/rodar.py            # tudo
    python testes/rodar.py cache      # só os que casam com "cache"

CADA TESTE RODA NUM PROCESSO PRÓPRIO, e não é firula: os módulos do backend
guardam estado no import (conexões, caches em memória, o `_UPLOADS`), e um
teste que sujasse o processo faria o seguinte passar ou falhar por motivo
errado. Processo separado é a única forma de "passou sozinho" significar
"passa sempre".

O QUE A SAÍDA PRECISA DIZER quando falha: o que quebra PARA QUEM USA. Um
`AssertionError: 8 != 10` não diz nada às sete da noite; "o complemento
encolheu a lista" diz.
"""
import os
import subprocess
import sys
import time

AQUI = os.path.dirname(os.path.abspath(__file__))

# Ordem proposital: do mais básico ao mais composto. O primeiro que falha
# costuma explicar os seguintes, e olhar a lista de cima para baixo é mais
# rápido que caçar.
TESTES = [
    ("t_01_layout.py", "as quantidades viram as colunas certas"),
    ("t_02_telefone_ordem.py", "o telefone da planilha é o de maior chance"),
    ("t_03_job.py", "o trabalho roda no servidor e vira arquivo"),
    ("t_04_parada_retomada.py", "parar não perde o que foi pago; retomar não paga de novo"),
    ("t_05_complemento.py", "completar não encolhe, não repete coluna, não recobra"),
    ("t_06_cache_cpf.py", "o CPF resolvido não é comprado duas vezes"),
    ("t_07_sinais_memoria.py", "os sinais chegam na planilha e a empresa vazia é lembrada"),
]


def main():
    filtro = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    alvos = [(a, d) for a, d in TESTES if not filtro or filtro in a or filtro in d]
    if not alvos:
        print("nenhum teste casa com %r" % filtro)
        return 1

    print("=" * 72)
    print("SUITE DO CAPIBLU — %d testes" % len(alvos))
    print("Nenhum deles gasta: a rede para fora está bloqueada em testes/base.py")
    print("=" * 72)

    falhas, t0 = [], time.time()
    for arquivo, descricao in alvos:
        caminho = os.path.join(AQUI, arquivo)
        if not os.path.exists(caminho):
            print("  ?  %-30s ARQUIVO NÃO EXISTE" % arquivo)
            falhas.append((arquivo, "não existe"))
            continue
        t = time.time()
        r = subprocess.run([sys.executable, caminho], capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           env={**os.environ, "PYTHONIOENCODING": "utf-8"})
        seg = time.time() - t
        if r.returncode == 0:
            print("  ok %-30s %-46s %4.1fs" % (arquivo, descricao, seg))
        else:
            print("  XX %-30s %-46s %4.1fs" % (arquivo, descricao, seg))
            falhas.append((arquivo, (r.stdout + r.stderr).strip()))

    print("-" * 72)
    if not falhas:
        print("TUDO PASSOU em %.1fs. Pode subir." % (time.time() - t0))
        return 0

    print("%d FALHA(S) — NÃO SUBA:" % len(falhas))
    for arquivo, saida in falhas:
        print()
        print("  ── %s ─────────────────────────────" % arquivo)
        # As últimas linhas são onde está o assert; o resto é contexto.
        for linha in saida.splitlines()[-18:]:
            print("     " + linha)
    return 1


if __name__ == "__main__":
    sys.exit(main())
