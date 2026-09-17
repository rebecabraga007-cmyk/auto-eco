# -*- coding: utf-8 -*-
"""Cria no Cloudflare os registros de DNS que autorizam o envio de e-mail.

POR QUE UM SCRIPT E NAO QUATRO CLIQUES
--------------------------------------
Porque a parte que da errado nao e criar -- e criar ERRADO de um jeito que
nao avisa. Registro de e-mail proxied pela Cloudflare para de funcionar sem
nenhuma mensagem; um TXT colado com aspas sobrando quebra a assinatura; um MX
sem prioridade e recusado. Nos quatro casos a tela fica verde e o e-mail cai
no spam semanas depois, quando ninguem mais lembra do dia em que mexeu no DNS.

Aqui cada registro nasce com `proxied=False` explicito, o script CONFERE o que
ficou gravado e imprime lado a lado o que foi pedido e o que a Cloudflare
devolveu.

COMO USAR
---------
1. Na Resend: Domains -> Add Domain -> capiblu.net. A tela devolve 3
   registros (1 MX + 2 TXT). Os valores de DKIM nascem nessa hora e sao
   unicos do dominio -- nao da para adiantar.
2. Salve o JSON que a Resend mostra (ou monte a mao) num arquivo:

       [{"type":"MX","name":"send","content":"feedback-smtp.sa-east-1.amazonses.com","priority":10},
        {"type":"TXT","name":"send","content":"v=spf1 include:amazonses.com ~all"},
        {"type":"TXT","name":"resend._domainkey","content":"p=MIGfMA0GCSq..."}]

3. Rode:

       CF_TOKEN=... python cloudflare_email_dns.py registros.json

   `--dmarc` acrescenta a politica de observacao. `--aplicar` e obrigatorio
   para gravar: sem ele o script so MOSTRA o que faria.

O token precisa de `Zone -> DNS -> Edit` na zona capiblu.net, e so nela.
"""
import json
import os
import sys
import urllib.error
import urllib.request

API = "https://api.cloudflare.com/client/v4"
DOMINIO = os.environ.get("CF_DOMINIO", "capiblu.net")
TOKEN = os.environ.get("CF_TOKEN", "").strip()

# DMARC em `p=none` de proposito: observa e nao rejeita nada. Comecar em
# `quarantine` com SPF/DKIM recem-criados e o jeito mais rapido de mandar o
# proprio e-mail para o spam num dominio que ainda nao se conhece.
DMARC = {"type": "TXT", "name": "_dmarc", "content": "v=DMARC1; p=none"}


def _chama(metodo, caminho, corpo=None):
    req = urllib.request.Request(
        API + caminho, method=metodo,
        data=json.dumps(corpo).encode() if corpo is not None else None,
        headers={"Authorization": "Bearer " + TOKEN,
                 "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.load(r)
    except urllib.error.HTTPError as e:
        return json.load(e)


def zona():
    d = _chama("GET", "/zones?name=" + DOMINIO)
    res = d.get("result") or []
    if not res:
        raise SystemExit("Zona %s nao encontrada (o token ve essa zona?): %s"
                         % (DOMINIO, d.get("errors")))
    return res[0]["id"]


def existentes(zid):
    d = _chama("GET", "/zones/%s/dns_records?per_page=100" % zid)
    return d.get("result") or []


def nome_cheio(nome):
    if nome in ("@", "", DOMINIO):
        return DOMINIO
    return nome if nome.endswith(DOMINIO) else "%s.%s" % (nome, DOMINIO)


def main():
    if not TOKEN:
        raise SystemExit("Falta CF_TOKEN no ambiente.")
    if len(sys.argv) < 2:
        raise SystemExit(__doc__)
    aplicar = "--aplicar" in sys.argv
    com_dmarc = "--dmarc" in sys.argv
    arquivo = [a for a in sys.argv[1:] if not a.startswith("--")][0]

    pedidos = json.load(open(arquivo, encoding="utf-8"))
    if com_dmarc:
        pedidos = list(pedidos) + [DMARC]

    zid = zona()
    ja = existentes(zid)
    print("zona %s (%s) — %d registros hoje\n" % (DOMINIO, zid, len(ja)))

    for p in pedidos:
        alvo = nome_cheio(p["name"])
        corpo = {"type": p["type"], "name": alvo,
                 # `proxied` SEMPRE False e SEMPRE explicito. A Cloudflare nao
                 # proxia MX/TXT, mas se a Resend um dia pedir um CNAME o
                 # padrao da conta pode liga-lo -- e um CNAME de e-mail
                 # proxied quebra em silencio.
                 "proxied": False, "ttl": 3600,
                 "content": p["content"],
                 "comment": "envio de e-mail (Resend) — criado pelo CapiBLU"}
        if p["type"] == "MX":
            corpo["priority"] = int(p.get("priority") or 10)

        # JA EXISTE? Atualiza em vez de duplicar. Dois TXT de SPF no mesmo
        # nome e uma falha classica: o padrao manda ter UM, e com dois o
        # destinatario trata como nenhum.
        igual = [r for r in ja if r["name"] == alvo and r["type"] == p["type"]
                 and (p["type"] != "TXT"
                      or r["content"].split("=")[0] == p["content"].split("=")[0])]

        if not aplicar:
            print("[só mostrando] %s %-34s %s%s"
                  % (p["type"], alvo, str(p["content"])[:56],
                     "  (substituiria um existente)" if igual else ""))
            continue

        if igual:
            d = _chama("PUT", "/zones/%s/dns_records/%s" % (zid, igual[0]["id"]), corpo)
            acao = "atualizado"
        else:
            d = _chama("POST", "/zones/%s/dns_records" % zid, corpo)
            acao = "criado"
        if not d.get("success"):
            print("[FALHOU] %s %s -- %s" % (p["type"], alvo, d.get("errors")))
            continue
        r = d["result"]
        # SO ASCII NA SAIDA. O console do Windows usa cp1252 e um "check"
        # bonito derruba o script com UnicodeEncodeError DEPOIS de ja ter
        # gravado o registro -- o pior momento possivel, porque parece que
        # falhou quando na verdade funcionou.
        print("[OK] %s %s %-30s proxy=%s  %s"
              % (acao, r["type"], r["name"], r.get("proxied"),
                 str(r["content"])[:50]))

    if not aplicar:
        print("\nNada foi gravado. Repita com --aplicar para valer.")


if __name__ == "__main__":
    main()
