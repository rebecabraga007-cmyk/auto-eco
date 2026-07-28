"""Teste end-to-end: nome (+ cidade OU empresa) -> CPF certo -> telefone.

Etapas:
1. JBR: nome -> CPFs candidatos (desambiguacao local).
2. Mk:  consulta cada candidato e desambigua por CIDADE (do LinkedIn) ou EMPRESA.
        A Mk ja retorna telefone na mesma consulta.
3. Serasa: consulta o CPF -> telefone (verificacao/complemento).

Uso:
    # por cidade (recomendado p/ funcionario; cidade vem do LinkedIn/Bright Data)
    python test_pipeline.py --city "Renato Moutinho" "Rio de Janeiro" [UF]
    # por empresa
    python test_pipeline.py --company "Renato Moutinho" "Petrobras"
    # forcar um CPF (pula desambiguacao)
    python test_pipeline.py --cpf "Renato Moutinho" 34791213734

Carrega .env automaticamente.
"""

import asyncio
import os
import sys

try:
    from dotenv import load_dotenv
    load_dotenv(os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), ".env"))
except Exception:
    pass

_JBR = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))), "jbr_base"
)
if _JBR not in sys.path:
    sys.path.insert(0, _JBR)

import cpf_lookup
import mkbuscas
import serasa


def hr(t):
    print("\n" + "=" * 60 + f"\n{t}\n" + "=" * 60)


async def main():
    args = sys.argv[1:]
    mode = "city"
    if args and args[0] in ("--city", "--company", "--cpf", "--multi"):
        mode = args[0][2:]
        args = args[1:]
    nome = args[0] if len(args) > 0 else "Renato Moutinho"

    if mode == "multi":
        # multi: nome empresa cargo cidade [uf]
        m_company = args[1] if len(args) > 1 else "Petrobras"
        m_role = args[2] if len(args) > 2 else ""
        m_city = args[3] if len(args) > 3 else "Rio de Janeiro"
        m_uf = args[4] if len(args) > 4 else ""
        hr(f"ALVO: {nome} | multi | empresa={m_company} cargo={m_role} cidade={m_city}/{m_uf}")
    else:
        alvo = args[1] if len(args) > 1 else "Rio de Janeiro"
        uf = args[2] if len(args) > 2 else ""
        hr(f"ALVO: {nome}  |  modo: {mode}  |  {alvo} {uf}".strip())

    # 1) JBR — candidatos por nome
    hr("1) JBR - localizar CPF por nome")
    if not cpf_lookup.ready():
        print("  base JBR indisponivel."); return
    cands = cpf_lookup.by_name(nome, limit=50)
    print(f"  {len(cands)} candidato(s):")
    for c in cands:
        print(f"   - {c['cpf']} | {c['nome']} | nasc {c['nascimento']}")

    # 2) Desambiguar
    cpf_certo = ""
    if mode == "cpf":
        hr("2) CPF forcado (pula desambiguacao)")
        cpf_certo = alvo
        print(f"  CPF: {cpf_certo}")
    elif not mkbuscas.enabled():
        hr("2) Mk - desambiguar")
        print("  Mk NAO configurada (defina MK_BASE_URL). Etapa pulada.")
        if len(cands) == 1:
            cpf_certo = cands[0]["cpf"]
            print(f"  (nome unico -> {cpf_certo})")
    elif mode == "multi":
        hr("2) Mk - desambiguar MULTI (empresa=3 + cidade=2 + cargo=1)")
        res = await mkbuscas.disambiguate_multi(cands, m_company, m_role, m_city, m_uf)
        print(f"  status: {res['status']}")
        for ch in res.get("checked", []):
            print(f"   - {ch['cpf']} | score={ch.get('score')} | hits={ch.get('hits')} | cidades={ch.get('cidades')} | empresas={ch.get('empresas')}")
        if res["status"] == "resolved":
            cpf_certo = res["cpf"]
            tels = res["pessoa"].get("phones_mk", [])
            if tels:
                print("  telefones (Mk, mesma consulta):")
                for t in tels:
                    print(f"     {t['telefone']} | {t['tipo']} | {t['operadora']}")
    elif mode == "company":
        hr("2) Mk - desambiguar por EMPRESA (empregos/empresas)")
        res = await mkbuscas.disambiguate_by_company(cands, alvo)
        print(f"  status: {res['status']}")
        for ch in res.get("checked", []):
            print(f"   - {ch['cpf']} | empresas={ch.get('empresas')} | match={ch.get('match')}")
        if res["status"] == "resolved":
            cpf_certo = res["cpf"]
    else:  # city
        hr("2) Mk - desambiguar por CIDADE (enderecos)")
        res = await mkbuscas.disambiguate_by_city(cands, alvo, uf)
        print(f"  status: {res['status']}")
        for ch in res.get("checked", []):
            print(f"   - {ch['cpf']} | cidades={ch.get('cidades')} | match={ch.get('match')}")
        if res["status"] == "resolved":
            cpf_certo = res["cpf"]
            tels = res["pessoa"].get("phones_mk", [])
            if tels:
                print("  telefones (Mk, mesma consulta):")
                for t in tels:
                    print(f"     {t['telefone']} | {t['tipo']} | {t['operadora']}")

    if not cpf_certo:
        hr("RESULTADO: CPF nao resolvido de forma unica.")
        return
    print(f"\n  >>> CPF resolvido: {cpf_certo}")

    # 3) Serasa — telefone
    hr("3) Serasa - telefone do CPF resolvido")
    if not serasa.enabled():
        print("  Serasa NAO configurada (defina SERASA_CLIENT_ID/SECRET). Etapa pulada.")
        return
    contacts = await serasa.enrich_person(cpf_certo)
    print(f"  status: {contacts.get('status')}")
    for p in contacts.get("phones", []):
        print(f"   TEL: ({p['ddd']}) {p['number']} | movel={p['mobile']} | {p['type']}")
    for e in contacts.get("emails", []):
        print(f"   EMAIL: {e}")


if __name__ == "__main__":
    asyncio.run(main())
