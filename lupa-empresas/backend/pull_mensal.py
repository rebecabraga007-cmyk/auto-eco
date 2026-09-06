# -*- coding: utf-8 -*-
"""Baixa o snapshot mensal da ASSINATURA e alimenta o cache. Não chama API paga.

POR QUE ASSIM, e não pela API:

    Assinatura   $31,82/mês por 100.000 registros  =  $0,32 por mil
    Search/Filter                                     $2,50 por mil

A assinatura é **7,9x mais barata**. A primeira versão deste script puxava pela
Filter API e teria gasto $250 no dia 5 para buscar o que a assinatura entrega por
$31,82 no dia 4. Este script não gasta nada: só baixa o que já foi pago.

COMO FUNCIONA A ASSINATURA (painel da Bright Data): entrega dia 4 de cada mês,
100 mil registros, "dados mais recentes". Os snapshots aparecem em
`GET /datasets/snapshots?dataset_id=...` com status `scheduled` e depois `ready`.

**ELES EXPIRAM.** O de setembro tinha `expiry_date` 14 dias após a coleta. Se
ninguém baixar, o mês é perdido — e a cota não volta. Por isso o script roda dia
5 (um dia depois da entrega) e avisa alto quando acha snapshot perto de vencer.

    python pull_mensal.py                # baixa o que estiver pronto e não baixado
    python pull_mensal.py --listar       # só mostra o que existe lá
    python pull_mensal.py --snapshot ID  # força um específico
"""
import argparse
import csv
import io
import json
import os
import sys
import time
from datetime import datetime, timezone

import httpx

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

CHAVE = os.environ.get("BRIGHTDATA_API_KEY", "").strip()
DATASET = os.environ.get("BRIGHTDATA_PEOPLE_DATASET_ID", "gd_l1viktl72bvl7bjuj0")
SNAPS_URL = "https://api.brightdata.com/datasets/snapshots"
DESTINO = os.environ.get("PULL_DIR", "/capiblu_data/pulls")
REGISTRO = os.path.join(DESTINO, "baixados.json")
# Só perfis deste país entram no cache. O snapshot vem do mundo inteiro e ~92%
# não serve para prospecção no Brasil — guardar tudo só deixa a busca lenta.
PAIS = os.environ.get("PULL_PAIS", "BR")
DIAS_ALERTA = 5
# A listagem traz TODO snapshot da conta, inclusive os de 3 a 13 registros que
# sobram de teste da Search/Filter API. Entrega de assinatura são 100 mil, então
# qualquer coisa pequena não é entrega e não deve ser baixada automaticamente
# (use --snapshot para forçar um específico).
MINIMO_ENTREGA = int(os.environ.get("PULL_MINIMO", "1000"))


def log(m):
    print("[%s] %s" % (time.strftime("%H:%M:%S"), m), flush=True)


def h():
    return {"Authorization": "Bearer " + CHAVE}


def listar():
    r = httpx.get(SNAPS_URL, headers=h(), params={"dataset_id": DATASET}, timeout=120)
    if r.status_code >= 400:
        raise RuntimeError("listagem HTTP %s: %s" % (r.status_code, r.text[:200]))
    d = json.loads(r.content)
    return d if isinstance(d, list) else (d.get("snapshots") or [])


def ja_baixados():
    if os.path.exists(REGISTRO):
        try:
            return json.load(io.open(REGISTRO, encoding="utf-8"))
        except Exception:
            log("baixados.json ilegível — tratando como vazio")
    return {}


def anotar(reg):
    os.makedirs(DESTINO, exist_ok=True)
    io.open(REGISTRO, "w", encoding="utf-8").write(
        json.dumps(reg, ensure_ascii=False, indent=2))


def dias_para_expirar(s):
    exp = s.get("expiry_date")
    if not exp:
        return None
    try:
        d = datetime.fromisoformat(exp.replace("Z", "+00:00"))
        return (d - datetime.now(timezone.utc)).total_seconds() / 86400
    except Exception:
        return None


def baixar(sid, caminho):
    """CSV é o formato pedido para guardar; o cache é semeado do mesmo arquivo,
    para não baixar duas vezes."""
    os.makedirs(os.path.dirname(caminho), exist_ok=True)
    with httpx.stream("GET", "%s/%s/download" % (SNAPS_URL, sid), headers=h(),
                      params={"format": "csv"}, timeout=3600) as r:
        if r.status_code >= 400:
            raise RuntimeError("download HTTP %s: %s" % (r.status_code, r.read()[:200]))
        with io.open(caminho, "wb") as f:
            for pedaco in r.iter_bytes(1024 * 512):
                f.write(pedaco)
    return os.path.getsize(caminho)


def semear(caminho):
    import linkedin_cache
    linkedin_cache.init()
    lote, guardados, pulados, novos = [], 0, 0, 0
    with io.open(caminho, encoding="utf-8", errors="replace", newline="") as f:
        for linha in csv.DictReader(f):
            url = (linha.get("url") or linha.get("input_url") or "").strip()
            if not url:
                continue
            if PAIS and (linha.get("country_code") or "").upper() != PAIS.upper():
                pulados += 1
                continue
            generica = str(linha.get("default_avatar", "")).lower() in ("true", "1")
            seg = linha.get("followers")
            lote.append({
                "url": url,
                "nome": linha.get("name") or "",
                "cargo": linha.get("position") or "",
                "empresa": linha.get("current_company_name") or "",
                "cidade": linha.get("city") or "",
                "pais": linha.get("country_code") or "",
                "foto": "" if generica else (linha.get("avatar") or ""),
                "formacao": linha.get("educations_details") or "",
                "sobre": (linha.get("about") or "")[:400],
                "seguidores": int(seg) if str(seg).isdigit() else None,
            })
            guardados += 1
            if len(lote) >= 2000:
                novos += linkedin_cache.salvar_perfis(lote, origem="snapshot")
                lote.clear()
    if lote:
        novos += linkedin_cache.salvar_perfis(lote, origem="snapshot")
    return guardados, pulados, novos


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--listar", action="store_true")
    ap.add_argument("--snapshot", default="")
    args = ap.parse_args()

    if not CHAVE:
        log("BRIGHTDATA_API_KEY ausente"); raise SystemExit(1)

    snaps = listar()
    if args.listar:
        print("%-26s %-11s %9s  %s" % ("id", "status", "registros", "expira em"))
        for s in snaps:
            d = dias_para_expirar(s)
            print("%-26s %-11s %9s  %s"
                  % (s.get("id", "")[:26], s.get("status"), s.get("dataset_size"),
                     ("%.1f dias" % d) if d is not None else "—"))
        return

    reg = ja_baixados()
    prontos = [s for s in snaps if s.get("status") == "ready"
               and (s.get("dataset_size") or 0) >= MINIMO_ENTREGA]

    # Avisa alto sobre o que está para vencer sem ter sido baixado — cota perdida
    # nao volta, e descobrir isso depois do vencimento nao adianta nada.
    for s in prontos:
        d = dias_para_expirar(s)
        if s["id"] not in reg and d is not None and d < DIAS_ALERTA:
            log("ATENÇÃO: %s expira em %.1f dias e ainda não foi baixado."
                % (s["id"], d))

    if args.snapshot:
        # Forçado ignora o mínimo: serve justamente para pegar um pequeno.
        alvos = [s for s in snaps if s["id"] == args.snapshot
                 and s.get("status") == "ready"]
        if not alvos:
            log("snapshot %s não está pronto ou não existe" % args.snapshot)
            raise SystemExit(2)
    else:
        alvos = [s for s in prontos if s["id"] not in reg]
        if not alvos:
            agendados = [s for s in snaps if s.get("status") == "scheduled"]
            pequenos = sum(1 for s in snaps if s.get("status") == "ready"
                           and 0 < (s.get("dataset_size") or 0) < MINIMO_ENTREGA)
            log("nada novo para baixar (%d já baixados, %d agendados, "
                "%d pequenos ignorados)" % (len(reg), len(agendados), pequenos))
            return

    for s in alvos:
        sid = s["id"]
        log("baixando %s (%s registros)" % (sid, f"{s.get('dataset_size', 0):,}"))
        nome = "%s-%s.csv" % (time.strftime("%Y%m"), sid[-8:])
        caminho = os.path.join(DESTINO, nome)
        tam = baixar(sid, caminho)
        log("  csv: %s (%.1f MB)" % (nome, tam / 1024 / 1024))

        guardados, pulados, novos = semear(caminho)
        log("  cache: %s de %s guardados (%s novos); %s de outros países pulados"
            % (f"{guardados:,}", f"{s.get('dataset_size', 0):,}", f"{novos:,}",
               f"{pulados:,}"))

        reg[sid] = {"quando": time.strftime("%Y-%m-%d %H:%M"), "csv": nome,
                    "registros": s.get("dataset_size"), "guardados": guardados,
                    "novos": novos, "pais": PAIS}
        anotar(reg)

    log("pronto — nada foi cobrado (snapshot da assinatura, já pago)")


if __name__ == "__main__":
    main()
