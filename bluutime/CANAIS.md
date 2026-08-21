# Canais: como ligar o envio de verdade

Hoje **nada sai**. Sem credencial e sem o freio de mão liberado, todo envio
volta como `SIMULATED` e fica registrado como tal — a tela nunca diz "enviada"
para uma mensagem que ninguém recebeu.

## O freio de mão

```bash
BLUUTIME_SEND=1
```

Ter credencial no `.env` **não basta**. Enquanto `BLUUTIME_SEND` não for `1`,
todo envio volta `SIMULATED`. Sem isso, no dia em que alguém colar a chave da
Evolution no `.env`, a cadência inteira dispararia para leads reais sem ninguém
ter decidido isso.

Confira o estado a qualquer momento em `GET /api/envio/canais`.

## WhatsApp — Evolution API

```bash
EVOLUTION_API_URL=https://sua-evolution.exemplo.com
EVOLUTION_API_KEY=...
EVOLUTION_INSTANCE=bluutime-blu
EVOLUTION_WEBHOOK_TOKEN=...        # opcional, mas recomendado
```

A instância é um número pareado por QR Code, e **ela cai sozinha** — celular sem
bateria, sessão expirada, WhatsApp Web aberto noutro lugar. Por isso
`GET /api/whatsapp/instances/state` pergunta ao provedor: `CONNECTED`,
`CONNECTING`, `DISCONNECTED`, `UNREACHABLE` ou `NOT_CONFIGURED`.

Para receber resposta, aponte o webhook da Evolution para:

```
POST https://seu-bluutime/api/whatsapp/webhook
```

Essa rota fica **fora do login** — quem chama é o provedor, não o navegador —
e por isso confere o `EVOLUTION_WEBHOOK_TOKEN`. Mensagem com `fromMe` é
descartada: senão o que o SDR manda volta como se o lead tivesse respondido.

O casamento com o lead é pelos **últimos 8 dígitos** do número. O nono dígito do
celular e o DDI entram e saem conforme a origem do cadastro, então comparar a
string inteira erra.

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
