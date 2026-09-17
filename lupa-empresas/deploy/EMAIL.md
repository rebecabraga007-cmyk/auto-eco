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

## Passo 2 — Cloudflare — **FEITO em 17/set/2026**

Domínio cadastrado na Resend (`sa-east-1`) e os registros criados na zona pela
API. Estado conferido depois de gravar:

| Tipo | Nome | Proxy | Conteúdo |
|---|---|---|---|
| TXT | `resend._domainkey` | cinza | `p=MIGfMA0GCSq…` (DKIM) |
| MX | `send` | cinza | `feedback-smtp.sa-east-1.amazonses.com` (10) |
| TXT | `send` | cinza | `v=spf1 include:amazonses.com ~all` |
| CNAME | `rsend` | cinza | `send.forge.rmta.net` |
| TXT | `_dmarc` | cinza | `v=DMARC1; p=none` |

Os cinco em **DNS only**. O `CNAME rsend` é o que justifica o cuidado: CNAME é
o único tipo desta lista que a Cloudflare consegue proxiar, e proxiado ele
quebraria sem dar erro. Os cinco registros antigos (`app`, `bluu`, `data`,
raiz, `www`) continuam laranja e intocados.

**Resend: `verified`** — DKIM e SPF confirmados por ela.

**SMTP: login aceito** em `smtp.resend.com:587` com usuário `resend` e a API
key como senha (testado com handshake, sem enviar mensagem).

Para refazer isso noutro domínio, ou depois de trocar a chave:

```bash
CF_TOKEN=... python cloudflare_email_dns.py registros-da-resend.json --dmarc --aplicar
```

Sem `--aplicar` ele só mostra o que faria. Rodar duas vezes é seguro: ele
atualiza em vez de duplicar — e isso salvou a primeira execução, que gravou o
DKIM e morreu no `print` antes de seguir.

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


---

# O outro domínio: `blusalesgroup.com.br`

Medido em 17/set/2026. **O DNS deste domínio está na Hostinger** (`ns1`/`ns2.dns-parking.com`),
não no Cloudflare — então o token do CapiBLU não alcança esta zona.

| | Hoje |
|---|---|
| MX | `SMTP.GOOGLE.COM` (Google Workspace) |
| SPF | `v=spf1 include:_spf.mail.hostinger.com ~all` |
| DKIM | **nenhum** — conferidos 16 seletores |
| DMARC | `v=DMARC1; p=none` |

O MX aponta para o Google e o SPF autoriza só a Hostinger. **Todo e-mail que
sai pelo Workspace falha SPF, e não há DKIM para compensar** — as duas
autenticações falhando ao mesmo tempo. Nada quebra e ninguém recebe erro: a
mensagem sai, chega, e cai no spam de uma parte dos destinatários. O sintoma
aparece semanas depois como "fulano disse que não recebeu".

## 1. SPF — hPanel da Hostinger → Domínios → DNS

**EDITE** o TXT que já existe. Não crie um segundo: o padrão permite UM
registro SPF, e com dois o destinatário trata como se não houvesse nenhum.

```
v=spf1 include:_spf.google.com include:_spf.mail.hostinger.com ~all
```

O `include` da Hostinger fica — se algum formulário do site ainda manda e-mail
por lá, tirá-lo quebraria isso sem aviso. Custa 4 consultas de DNS no total,
bem abaixo do teto de 10.

Acrescentar o Google só AUTORIZA a mais; não há como essa mudança piorar o que
já funciona.

## 2. DKIM — e este importa mais

DKIM sobrevive a encaminhamento e a listas de distribuição, onde o SPF sempre
quebra. É no console de admin do Google, não no DNS:

**admin.google.com → Apps → Google Workspace → Gmail → Autenticar e-mail →
Gerar novo registro** (2048 bits). Ele devolve um TXT `google._domainkey`
para publicar na Hostinger; depois volte na mesma tela e clique em **Iniciar
autenticação**.

## 3. Conferir

```bash
python conferir_email_dns.py blusalesgroup.com.br capiblu.net
```

Lê só DNS público, não precisa de credencial. Ele diz o que falta e por quê.

## Antes de finalizar: quem mais manda como voces?

O SPF precisa listar **todo** serviço que envia com o endereço de vocês no
remetente. Se a Meetime dispara e-mail de cadência assinando como
`@blusalesgroup.com.br`, ela também precisa entrar — e isso eu não tenho como
descobrir pelo DNS. Vale conferir na configuração da Meetime antes de dar o
assunto por encerrado.
