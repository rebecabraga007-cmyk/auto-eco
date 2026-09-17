# -*- coding: utf-8 -*-
"""Confere se um dominio esta autorizado a mandar e-mail. Em portugues.

POR QUE ISTO EXISTE
-------------------
Porque autenticacao de e-mail falha em SILENCIO. Nada quebra, ninguem recebe
erro: a mensagem sai, chega, e simplesmente cai no spam de uma parte dos
destinatarios. O sintoma aparece semanas depois como "fulano disse que nao
recebeu", e ninguem liga isso a um registro de DNS.

Medido em 17/set/2026: o blusalesgroup.com.br manda e-mail pelo Google
Workspace (MX = SMTP.GOOGLE.COM) com um SPF que autoriza apenas a Hostinger e
sem nenhum DKIM publicado. As duas autenticacoes falhando ao mesmo tempo, sem
nenhum aviso em lugar nenhum.

    python conferir_email_dns.py blusalesgroup.com.br capiblu.net

Nao precisa de credencial: le so DNS publico.

O QUE ELE NAO FAZ
-----------------
Nao prova que o e-mail chega. Prova que o dominio AUTORIZA quem envia -- que
e a parte que se conserta no DNS. Reputacao de IP, conteudo e lista suja sao
outro assunto, e nenhum registro resolve.
"""
import subprocess
import sys

# Quem manda o e-mail, deduzido pelo MX, e o `include:` que aquele provedor
# exige. Sem isso o diagnostico ficaria em "falta alguma coisa no SPF" -- e a
# pergunta seguinte ("o que, exatamente?") e a unica que importa.
PROVEDORES = [
    ("google", "_spf.google.com", "Google Workspace"),
    ("outlook", "spf.protection.outlook.com", "Microsoft 365"),
    ("hostinger", "_spf.mail.hostinger.com", "Hostinger"),
    ("zoho", "zoho.com", "Zoho"),
    ("titan", "spf.titan.email", "Titan"),
    ("secureserver", "secureserver.net", "GoDaddy"),
    ("amazonses", "amazonses.com", "Amazon SES / Resend"),
]

# Seletores que os provedores usam. DKIM nao e descobrivel: so da para
# perguntar por nome. Esta lista cobre o que se ve na pratica.
SELETORES = ["google", "default", "selector1", "selector2", "k1", "k2",
             "mail", "dkim", "s1", "s2", "resend", "zoho", "titan1",
             "protonmail", "mandrill", "sendgrid"]


def txt(nome):
    """Registros TXT de um nome, ja remontados (o DNS quebra em pedacos)."""
    try:
        saida = subprocess.run(["nslookup", "-type=TXT", nome, "8.8.8.8"],
                               capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    # O QUE SEPARA UM REGISTRO DO OUTRO e a linha com "text =", nao a aspa.
    #
    # Minha primeira versao juntava tudo que comecasse com aspa, achando que
    # estava remontando um registro longo partido em pedacos. Nao estava:
    # TODAS as linhas de valor vem indentadas e comecando com aspa, entao os
    # tres TXT do dominio viravam uma string so -- que comecava com
    # "google-site-verification" e portanto nunca casava com "v=spf1". O
    # programa entao dizia "SPF: NENHUM" para um dominio que TEM SPF.
    #
    # Errar para o lado de "esta faltando" e o pior erro possivel aqui: manda
    # alguem mexer no DNS que estava certo.
    achados, atual = [], None
    for linha in saida.splitlines():
        if "text =" in linha:
            if atual is not None:
                achados.append(atual)
            atual = ""
        if atual is not None and '"' in linha:
            # Pedacos na mesma linha ("aaa" "bbb") sao UM registro so: o DNS
            # parte string acima de 255 caracteres, e DKIM quase sempre passa.
            atual += "".join(linha.split('"')[1::2])
    if atual:
        achados.append(atual)
    return [a for a in achados if a]


def mx(nome):
    try:
        saida = subprocess.run(["nslookup", "-type=MX", nome, "8.8.8.8"],
                               capture_output=True, text=True, timeout=20).stdout
    except Exception:
        return []
    return [l.split("=")[-1].strip().rstrip(".").lower()
            for l in saida.splitlines() if "mail exchanger" in l.lower()]


def confere(dominio):
    print("=" * 66)
    print(dominio)
    print("=" * 66)
    problemas, avisos = [], []

    servidores = mx(dominio)
    print("MX     : %s" % (", ".join(servidores) or "nenhum"))
    # Quem entrega o e-mail do dominio costuma ser tambem quem o envia. Nao e
    # lei, mas erra pouco -- e e o unico palpite possivel sem perguntar.
    esperados = []
    for chave, incl, nome in PROVEDORES:
        if any(chave in s for s in servidores):
            esperados.append((incl, nome))

    # ── SPF ────────────────────────────────────────────────────────────
    spfs = [t for t in txt(dominio) if t.lower().startswith("v=spf1")]
    if not spfs:
        print("SPF    : NENHUM")
        problemas.append("Nao ha SPF. Qualquer um pode dizer que e voces.")
    elif len(spfs) > 1:
        print("SPF    : %d REGISTROS (invalido)" % len(spfs))
        # Nao e "dois e melhor que um": o padrao manda ter UM, e com dois o
        # destinatario descarta os dois. E o jeito mais facil de piorar
        # tentando melhorar.
        problemas.append("Ha %d registros SPF. O padrao permite UM: com dois, "
                         "o destinatario trata como se nao houvesse nenhum. "
                         "Junte tudo num so." % len(spfs))
    else:
        spf = spfs[0]
        print("SPF    : %s" % spf)
        for incl, nome in esperados:
            if incl not in spf:
                problemas.append(
                    "O MX aponta para %s, mas o SPF nao tem "
                    "`include:%s` — todo e-mail que sai por la FALHA SPF."
                    % (nome, incl))
        if spf.rstrip().endswith("+all"):
            problemas.append("Termina em `+all`: isso autoriza o mundo "
                             "inteiro a enviar como voces. Use `~all`.")
        elif not spf.rstrip().endswith(("~all", "-all")):
            avisos.append("Nao termina em `~all` nem `-all`.")

    # ── DKIM ───────────────────────────────────────────────────────────
    achados = []
    for s in SELETORES:
        r = txt("%s._domainkey.%s" % (s, dominio))
        if any("p=" in x for x in r):
            achados.append(s)
    print("DKIM   : %s" % (", ".join("%s._domainkey" % s for s in achados)
                           or "nenhum (entre os seletores conhecidos)"))
    if not achados:
        problemas.append(
            "Nenhum DKIM publicado. DKIM importa MAIS que SPF: ele sobrevive "
            "a encaminhamento e a listas, onde o SPF sempre quebra.")

    # ── DMARC ──────────────────────────────────────────────────────────
    d = [t for t in txt("_dmarc." + dominio) if t.lower().startswith("v=dmarc1")]
    print("DMARC  : %s" % (d[0] if d else "nenhum"))
    if not d:
        avisos.append("Sem DMARC. Sem ele voce nao sabe quem anda mandando "
                      "e-mail em nome do dominio.")
    elif "rua=" not in d[0]:
        avisos.append("DMARC sem `rua=`: a politica existe mas ninguem "
                      "recebe os relatorios, entao ela nao te conta nada.")

    print()
    if not problemas and not avisos:
        print("Nada a corrigir.")
    for p in problemas:
        print("[CORRIGIR] %s" % p)
    for a in avisos:
        print("[avaliar ] %s" % a)
    print()
    return len(problemas)


if __name__ == "__main__":
    alvos = sys.argv[1:] or ["capiblu.net"]
    ruins = sum(confere(d) for d in alvos)
    sys.exit(1 if ruins else 0)
