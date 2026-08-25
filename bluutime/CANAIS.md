# Canais: como ligar o envio de verdade

Hoje **nada sai**. Sem credencial e sem o freio de mão liberado, todo envio
volta como `SIMULATED` e fica registrado como tal — a tela nunca diz "enviada"
para uma mensagem que ninguém recebeu.

## O freio de mão

```bash
BLUUTIME_SEND=1
```

Ter credencial no `.env` **não basta**. Enquanto `BLUUTIME_SEND` não for `1`,
todo envio volta `SIMULATED`. Sem isso, no dia em que alguém parear um número ou
colar as credenciais de SMTP, a cadência inteira dispararia para leads reais sem
ninguém ter decidido isso.

Confira o estado a qualquer momento em `GET /api/envio/canais`.

## WhatsApp — wuzapi (whatsmeow)

```bash
WHATSAPP_PROVIDER=wuzapi
WUZAPI_URL=http://localhost:8080
WUZAPI_ADMIN_TOKEN=...       # gerado localmente; cria e remove usuários
WUZAPI_TOKEN=...             # gerado localmente; é o que envia mensagem
```

**Não há chave a solicitar a ninguém.** O wuzapi roda na sua máquina, então você
é o dono — os dois tokens são gerados aqui, ao contrário da Assertiva ou do
Meetime, que são credenciais de terceiro. Estão separados de propósito pelo
próprio wuzapi: quem manda mensagem não deveria poder apagar usuários.

Sobe com:

```bash
bash bluutime/whatsapp/subir.sh
```

Parear é pela tela: **Prospecção → Canais e entregas → Parear número**. O QR do
whatsmeow expira em cerca de 40 s e a sessão cai junto, então a tela renova
sozinha em vez de deixar um código morto na frente do usuário.

O estado tem dois eixos e a tela mostra os dois traduzidos:

| Estado | O que significa |
|---|---|
| `CONNECTED` | Socket aberto **e** número pareado — pronto |
| `PAIRING` | Socket aberto, ninguém escaneou ainda |
| `DISCONNECTED` | Sem socket |
| `UNAUTHORIZED` | `WUZAPI_TOKEN` recusado |
| `NOT_CONFIGURED` | Falta variável no `.env` |

O webhook é registrado no próprio usuário do wuzapi, apontando para
`/api/whatsapp/webhook` via `host.docker.internal`. A rota entende **os dois
formatos** — wuzapi e Evolution —, então trocar de provedor não exige mexer nela.
O casamento com o lead é pelos **últimos 8 dígitos**: o nono dígito do celular e
o DDI entram e saem conforme a origem do cadastro.

### Por que não a Evolution

A Evolution continua no código (`WHATSAPP_PROVIDER=evolution`), porque voltar
custa uma variável. Mas o whatsmeow é a biblioteca que o próprio WhatsApp Web
usa por baixo, e o wuzapi é uma casca fina sobre ela — menos superfície para
quebrar quando o WhatsApp muda algo.

Isso não é teórico: a Evolution `v2.1.1` do blueprint do Render ficou presa numa
versão de cliente que o WhatsApp já não aceita, entrava em laço de reconexão e
**nem chegava a gerar QR**. Só voltou a funcionar na `v2.3.7`.

## E-mail — SMTP

```bash
SMTP_HOST=smtp.exemplo.com
SMTP_PORT=587
SMTP_USER=...
SMTP_PASSWORD=...
SMTP_FROM=comercial@blusalesgroup.com.br
SMTP_FROM_NAME=BLU Sales Group
SMTP_STARTTLS=1
```

O `Message-ID` de cada envio fica guardado em `Delivery.provider_id`, para casar
a resposta com o lead quando a leitura da caixa de entrada entrar.

Rastreio de abertura fica **desligado** por padrão. Pixel remoto é o que faz
e-mail cair em spam, e é dado pessoal coletado sem necessidade.

## As travas antes do provedor

| Trava | Como se contorna |
|---|---|
| **Não perturbe** (`Lead.do_not_call`) | **Não se contorna.** Tira-se a marca no cadastro do lead — ato deliberado e auditável |
| Janela útil 9h–18h | `foraDaJanela: true` no corpo, quando for intencional |
| Variável de modelo sem valor | `forcar: true` — manda mesmo com lacuna |
| Lead sem e-mail/telefone | Bloqueia; a atividade **continua na fila** |

O sinal de não perturbe vinha da Assertiva, era guardado e **nunca consultado** —
dava para mandar e-mail, WhatsApp e registrar ligação para quem pediu para não
ser incomodado. Agora bloqueia nos três.

Um detalhe do desenho: bloqueio **não conclui a atividade**. Ela volta para a
fila para o SDR resolver, em vez de sumir como se tivesse sido trabalhada.

## Onde ver o que aconteceu

```
GET /api/envio/entregas?lead_id=123
GET /api/envio/entregas?status=FAILED
```

É a tabela que responde "por que este lead não recebeu nada?". Cada tentativa
guarda canal, destino, status, provedor e o erro.

| Status | O que houve |
|---|---|
| `SENT` | O provedor aceitou e devolveu um id |
| `FAILED` | O provedor recusou; `error` diz o porquê |
| `SIMULATED` | Envio desligado ou sem credencial — nada saiu |
| `BLOCKED` | Recusado aqui dentro (não perturbe, fora da janela, sem destino) |

## Telefonia

Continua só registrando o resultado da ligação (`POST /api/dialer/calls`), agora
respeitando o não perturbe. Discagem pelo provedor depende de escolher um —
é decisão comercial, não técnica.
