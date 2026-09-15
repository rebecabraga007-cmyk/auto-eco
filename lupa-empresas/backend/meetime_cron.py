# -*- coding: utf-8 -*-
"""Atualiza os leads de TODAS as contas Meetime cadastradas, de madrugada.

POR QUE DE MADRUGADA, E POR QUE UM SCRIPT
-----------------------------------------
A sincronizacao e longa na primeira vez de cada conta (12.643 leads da BLU =
~126 paginas de leads + ~190 de prospeccoes, uns dois minutos) e curta depois
(0,4s quando nao ha nada novo). Rodar isso quando alguem abre a aba faz a
pessoa esperar pelo trabalho de ontem; rodar as 3h faz ela abrir a aba com a
base pronta.

Roda FORA do processo do app, chamado por um timer do systemd -- mesmo padrao
do `saude.py`. Um laco dentro do app competiria com as requisicoes pelo mesmo
event loop, e um travamento aqui derrubaria a API junto.

QUAIS CONTAS
------------
Todas as que o servidor conhece: as contas de cada pessoa (varias por pessoa,
desde 15/set/2026), os tokens de grupo e o token global do .env. A lista vem
de `meetime.todas_as_contas()`, deduplicada pelo hash do token -- a mesma
conta cadastrada por duas pessoas e uma conta so.

O QUE ELE NAO FAZ
-----------------
Nao apaga, nao reprocessa o que ja esta no disco e nao decide nada sobre
lead: so busca o que entrou depois do offset guardado. Se uma conta falhar
(token revogado, API fora), as outras seguem -- e o motivo fica no log e, se
for o caso, num alerta.
"""
import asyncio
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from dotenv import load_dotenv

_AQUI = os.path.dirname(os.path.abspath(__file__))
load_dotenv(os.path.join(os.path.dirname(_AQUI), ".env"))

import meetime          # noqa: E402
import meetime_leads    # noqa: E402

# Teto por conta. Uma conta nova precisa de varias voltas; sem teto, uma conta
# gigante (ou um erro que devolve `pendente` para sempre) prenderia o job a
# noite toda e as contas seguintes nunca rodariam.
VOLTAS_MAX = 60
PAGINAS_POR_VOLTA = 40


async def uma_conta(conta_info: dict) -> dict:
    tok = conta_info["token"]
    conta = meetime_leads.id_da_conta(tok)
    rotulo = ", ".join(conta_info.get("rotulos") or []) or conta
    t0 = time.time()
    leads = prosp = voltas = 0
    erro = ""
    for _ in range(VOLTAS_MAX):
        try:
            r = await meetime_leads.sincronizar(tok, conta,
                                                paginas=PAGINAS_POR_VOLTA)
        except Exception as exc:
            erro = str(exc)[:200]
            break
        voltas += 1
        leads += (r.get("trouxe") or {}).get("leads", 0)
        prosp += (r.get("trouxe") or {}).get("prospeccoes", 0)
        if r.get("erros"):
            erro = "; ".join(r["erros"])[:200]
        if not r.get("pendente"):
            break
    return {"rotulo": rotulo, "conta": conta, "leads": leads,
            "prospeccoes": prosp, "voltas": voltas, "erro": erro,
            "segundos": round(time.time() - t0, 1)}


async def main() -> int:
    contas = meetime.todas_as_contas()
    print("%s | %d conta(s) Meetime cadastrada(s)"
          % (time.strftime("%d/%m %H:%M"), len(contas)))
    if not contas:
        return 0

    resultados = []
    for c in contas:
        # UMA POR VEZ, de proposito. Em paralelo seria mais rapido e tambem
        # seria varias sincronizacoes escrevendo no mesmo SQLite e batendo na
        # mesma API com o teto de 100 por pagina -- ganho pequeno, chance de
        # `database is locked` e de rate limit grande.
        r = await uma_conta(c)
        resultados.append(r)
        print("  %-52s leads +%-6d prosp +%-6d %5.1fs %s"
              % (r["rotulo"][:52], r["leads"], r["prospeccoes"], r["segundos"],
                 ("ERRO: " + r["erro"]) if r["erro"] else ""))

    falhas = [r for r in resultados if r["erro"]]

    # O ALERTA USA A MESMA BOLINHA DOS CHAMADOS. Um job de madrugada que falha
    # em silencio e pior que nao existir: a pessoa abre a aba de manha, ve a
    # base velha e nao tem como saber que foi a sincronizacao que parou.
    try:
        import chamados
        if falhas:
            chamados.alertar(
                "meetime:sync",
                "Sincronização da Meetime falhou em %d conta(s)" % len(falhas),
                "O job das 3h não conseguiu atualizar:\n\n"
                + "\n".join("• %s — %s" % (f["rotulo"], f["erro"])
                            for f in falhas)
                + "\n\nA causa mais comum é token revogado ou trocado na "
                  "Meetime: nesse caso o dono da conta precisa cadastrar o "
                  "token novo em ⚙️ Configurações. Enquanto isso, a aba de "
                  "leads mostra a base da última leitura que deu certo.",
                "%d de %d conta(s)" % (len(falhas), len(resultados)))
        else:
            chamados.resolver_alerta("meetime:sync")
    except Exception as exc:
        print("  (não consegui registrar o alerta: %s)" % str(exc)[:120])

    novos = sum(r["leads"] for r in resultados)
    print("  total: %d lead(s) novo(s), %d falha(s)" % (novos, len(falhas)))
    return 1 if falhas else 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
