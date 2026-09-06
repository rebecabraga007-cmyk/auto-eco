# -*- coding: utf-8 -*-
"""Semeia o cache com os perfis de um snapshot ja baixado da Bright Data.

POR QUE: o snapshot completo (669 MB, ~100 mil perfis) JA FOI PAGO. Sem isto,
uma busca por uma empresa que esta la dentro pagaria de novo pela mesma gente.

O arquivo e UM array JSON gigante, grande demais para `json.load` numa maquina
de 8 GB: lemos em pedacos e fatiamos por chaves balanceadas, um registro por vez.

    python seed_snapshot.py CAMINHO.json [--saida cache.db]

Roda LOCAL (disco rapido) e depois sobe so o .db, que e ~20x menor. Para juntar
com o cache que ja esta no servidor, use --saida e depois no servidor:

    sqlite3 linkedin_cache.db "ATTACH 'semeado.db' AS s;
      INSERT OR IGNORE INTO perfis SELECT * FROM s.perfis;"
"""
import argparse
import io
import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

PEDACO = 8 * 1024 * 1024
BARRA = chr(92)


def registros(caminho):
    """Gera um dict por registro de nivel 1, com memoria constante."""
    with io.open(caminho, encoding="utf-8", errors="replace") as f:
        sobra = ""
        comecou = False
        while True:
            pedaco = f.read(PEDACO)
            if not pedaco:
                break
            buf = sobra + pedaco
            if not comecou:
                i = buf.find("{")
                if i < 0:
                    sobra = buf[-4:]
                    continue
                buf = buf[i:]
                comecou = True
            prof, ini, instr, esc, corte = 0, None, False, False, 0
            for j, c in enumerate(buf):
                if esc:
                    esc = False
                    continue
                if c == BARRA:
                    esc = True
                    continue
                if c == '"':
                    instr = not instr
                    continue
                if instr:
                    continue
                if c == "{":
                    if prof == 0:
                        ini = j
                    prof += 1
                elif c == "}":
                    prof -= 1
                    if prof == 0 and ini is not None:
                        try:
                            yield json.loads(buf[ini:j + 1])
                        except Exception:
                            pass
                        corte, ini = j + 1, None
            sobra = buf[corte:]


def para_pessoa(d):
    emp = d.get("current_company") or {}
    if not isinstance(emp, dict):
        emp = {}
    generica = bool(d.get("default_avatar"))
    return {
        "url": (d.get("url") or d.get("input_url") or ""),
        "nome": d.get("name") or "",
        "cargo": d.get("position") or "",
        "empresa": d.get("current_company_name") or emp.get("name") or "",
        "cidade": d.get("city") or "",
        "pais": d.get("country_code") or "",
        "foto": "" if generica else (d.get("avatar") or ""),
        "formacao": d.get("educations_details") or "",
        "sobre": (d.get("about") or "")[:400],
        "seguidores": d.get("followers"),
    }


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("snapshot")
    ap.add_argument("--saida", default="", help="caminho do .db (padrao: o do cache)")
    args = ap.parse_args()

    if args.saida:
        os.environ["LINKEDIN_CACHE_PATH"] = os.path.abspath(args.saida)
    import linkedin_cache
    linkedin_cache.init()
    print("cache em:", linkedin_cache.DB_PATH)

    t0 = time.time()
    lote, lidos, gravados = [], 0, 0
    for d in registros(args.snapshot):
        if not isinstance(d, dict) or "linkedin_num_id" not in d:
            continue      # objeto aninhado (similar_profiles), nao e perfil de topo
        p = para_pessoa(d)
        if not p["url"]:
            continue
        lote.append(p)
        lidos += 1
        if len(lote) >= 2000:
            gravados += linkedin_cache.salvar_perfis(lote, origem="snapshot")
            lote.clear()
            print("  %s lidos / %s novos  (%.0fs)"
                  % (f"{lidos:,}", f"{gravados:,}", time.time() - t0))
    if lote:
        gravados += linkedin_cache.salvar_perfis(lote, origem="snapshot")

    mb = os.path.getsize(linkedin_cache.DB_PATH) / 1024 / 1024
    print("\nPRONTO: %s perfis lidos, %s novos no cache (%.1f MB) em %.0fs"
          % (f"{lidos:,}", f"{gravados:,}", mb, time.time() - t0))
    print(json.dumps(linkedin_cache.estatisticas(), indent=2))


if __name__ == "__main__":
    main()
