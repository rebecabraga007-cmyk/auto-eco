# E-mail do CapiBLU — `@capiblu.net` pela Resend

O que sai por e-mail hoje: **a planilha enriquecida**, em anexo, para o
e-mail de cadastro de quem pediu (e só para ele — o arquivo leva CPF e
telefone de gente real).

## Por que Resend e não a Cloudflare

A Cloudflare **não envia e-mail**. O Email Routing dela é só de entrada:
recebe em `contato@capiblu.net` e reencaminha para uma caixa que já existe.
O que a Cloudflare faz aqui é guardar os registros que autorizam a Resend a
assinar como `@capiblu.net`.

Estado medido em 17/set/2026, antes de qualquer mudança:

| | capiblu.net | blusalesgroup.com.br |
|---|---|---|
| NS | Cloudflare (`nolan`/`uma.ns.cloudflare.com`) | Hostinger |
| MX | *nenhum* | `SMTP.GOOGLE.COM` |
| SPF | *nenhum* | `include:_spf.mail.hostinger.com` |
| DMARC | *nenhum* | `v=DMARC1; p=none` |

Repare na segunda coluna: o MX aponta para o Google, mas o SPF autoriza só a
Hostinger e não há DKIM do Google publicado. **E-mail que sai pelo Workspace
de vocês falha SPF hoje.** Como o DMARC está em `p=none` ninguém rejeita
ainda, mas é o bastante para não herdar essa configuração no domínio novo.

## Passo 1 — Resend

1. Criar conta em resend.com (plano grátis: 3.000 e-mails/mês, 100/dia,
   anexo até 40 MB — a planilha de 2.000 linhas dá ~1 MB).
2. **Domains → Add Domain** → `capiblu.net`, região `sa-east-1` se
   aparecer (São Paulo; menos salto para destinatário no Brasil).
3. A tela devolve **três registros**. Os valores de DKIM são únicos do
   domínio e nascem nessa hora — não dá para adiantá-los aqui.
4. **API Keys → Create** → permissão `Sending access`. Essa chave é a senha
   de SMTP.

## Passo 2 — Cloudflare (DNS da zona capiblu.net)

Os três registros da tela da Resend, com dois cuidados que a tela deles não
avisa:

- **Tudo em "DNS only" (nuvem CINZA).** Registro de e-mail proxied pela
  Cloudflare para de funcionar sem dar erro claro.
- A Resend usa o subdomínio **`send.capiblu.net`**, não a raiz. Por isso ela
  convive com o Email Routing: o MX da entrada fica na raiz, o MX de retorno
  (bounce) fica no `send.`.

| Tipo | Nome | Valor |
|---|---|---|
| MX | `send` | `feedback-smtp.sa-east-1.amazonses.com` (prioridade 10) |
| TXT | `send` | `v=spf1 include:amazonses.com ~all` |
| TXT | `resend._domainkey` | `p=MIGfMA0GCSqGSIb3…` *(copiar da Resend)* |

Confira o valor exato de cada um na tela da Resend antes de colar: a região
muda o MX, e o DKIM é único.

Mais um, que a Resend não pede mas vale colocar:

| Tipo | Nome | Valor |
|---|---|---|
| TXT | `_dmarc` | `v=DMARC1; p=none; rua=mailto:dmarc@capiblu.net` |

`p=none` só observa, não rejeita nada — é o jeito certo de começar. Depois de
algumas semanas sem falha nos relatórios, sobe para `p=quarantine`.

## Passo 3 — Receber as respostas (opcional, grátis)

**Email Routing** na Cloudflare, para `naoresponda@capiblu.net` e
`contato@capiblu.net` caírem numa caixa de verdade em vez do vazio. Ele
adiciona os MX da raiz sozinho. Um e-mail automático que ninguém lê quando
respondem é como um telefone que só liga.

## Passo 4 — O serviço

No `.env` do serviço de dados (`/opt/capiblu/lupa-empresas/.env`):

```
CAPIBLU_SMTP_HOST=smtp.resend.com
CAPIBLU_SMTP_PORT=587
CAPIBLU_SMTP_USER=resend
CAPIBLU_SMTP_SENHA=re_xxxxxxxxxxxxxxxxxxxx
CAPIBLU_SMTP_DE=CapiBLU <naoresponda@capiblu.net>
```

`CAPIBLU_SMTP_USER` é a palavra `resend`, literal — não é um endereço. A
senha é a API key.

**Reiniciar o serviço depois**, senão nada disso chega ao processo:

```bash
sudo systemctl restart capiblu-data
```

## Passo 5 — Conferir

Painel administrativo → **Envio de e-mail**. A tela mostra o que o *processo*
está lendo (host, porta, usuário, se há senha) e o botão manda um teste,
devolvendo o erro exato do servidor.

Isso existe porque o erro mais comum não é senha errada: é a variável posta
no arquivo certo e o serviço nunca reiniciado. Sem ver o que o processo leu,
os dois sintomas são idênticos.

### Se falhar

| O que aparece | O que é |
|---|---|
| `Falta CAPIBLU_SMTP_USER` | a variável não chegou ao processo — confira o `.env` e **reinicie** |
| `O servidor recusou o login` | API key errada, revogada, ou sem `Sending access` |
| `SMTPSenderRefused` / domínio não verificado | o DNS ainda não propagou ou um registro está proxied (nuvem laranja) |
| Sai, mas cai no spam | DKIM ou SPF faltando — a Resend mostra quais registros ela ainda não enxerga |
