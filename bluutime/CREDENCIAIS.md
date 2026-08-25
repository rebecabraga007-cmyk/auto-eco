# O que você precisa trazer

Lista obtida cruzando o que o código procura em `os.environ` com o que já existe
em `lupa-empresas/.env` — não é de memória.

Tudo vai no mesmo arquivo: **`lupa-empresas/.env`**.

---

## 1 · Bloqueia agora (o recurso existe e não funciona sem isto)

### WhatsApp — Evolution API

Sem isto, `GET /api/envio/canais` reporta `NOT_CONFIGURED` e todo envio volta
`SIMULATED`. A tela de Canais mostra exatamente o que falta.

```bash
EVOLUTION_API_URL=https://sua-evolution.exemplo.com
EVOLUTION_API_KEY=
EVOLUTION_INSTANCE=bluutime-blu
EVOLUTION_WEBHOOK_TOKEN=          # você inventa; confere quem chama o webhook
```

**Onde conseguir:** a Evolution API é auto-hospedada. Se a BLU já usa uma (o
`whatsapp-reader` sugere que sim), são a URL do painel, a `apikey` global e o
nome da instância pareada por QR Code.

**Documentação:** <https://doc.evolution-api.com> — as rotas que uso são
`/instance/connectionState/{instance}`, `/message/sendText/{instance}` e
`/chat/whatsappNumbers/{instance}`.

### E-mail — SMTP

Sem isto, passo de e-mail de cadência nunca sai.

```bash
SMTP_HOST=
SMTP_PORT=587
SMTP_USER=
SMTP_PASSWORD=
SMTP_FROM=comercial@blusalesgroup.com.br
SMTP_FROM_NAME=BLU Sales Group
SMTP_STARTTLS=1
```

**Onde conseguir:** o provedor de e-mail da BLU. Se for Google Workspace, é
`smtp.gmail.com:587` com **senha de app** (a senha normal não funciona com 2FA):
<https://support.google.com/accounts/answer/185833>. Microsoft 365 é
`smtp.office365.com:587`.

**Atenção ao volume:** Gmail limita ~2.000 envios/dia e Workspace pode barrar
disparo de cadência. Para volume real, o caminho é um serviço transacional
(Amazon SES, Resend, Postmark) — todos falam SMTP, então **não precisa mudar
código**, só as quatro variáveis.

### O freio de mão

```bash
BLUUTIME_SEND=1
```

Não é credencial, é decisão sua. Enquanto não for `1`, **nada sai** mesmo com
tudo configurado. Deixe desligado até rodar `POST /api/envio/teste` (botão
"Enviar teste para mim", na tela de Canais) e confirmar que a mensagem chegou.

---

## 2 · Depende de decisão sua

### CRM — Ploomes (a parte que falta da Fase 4)

Os webhooks já cadastrados no banco apontam para `meetime.ploomes.com`, o que
sugere Ploomes. Duas opções, com custo bem diferente:

| Opção | O que precisa | Estado |
|---|---|---|
| **Só disparar webhook** para o Ploomes consumir | Nada além da URL de destino | **Já pronto** — cadastre em Integrações |
| **Sync com a API do Ploomes** | `PLOOMES_API_KEY` + documentação de campos | Não começou |

Se for a segunda, preciso de:

- **Chave de API**: no Ploomes, `Administração → Integrações → Chave de API`
- **Documentação**: <https://developers.ploomes.com>
- **Uma resposta sua**: o lead ganho no Bluutime vira *Contato*, *Negócio* ou
  os dois no Ploomes? E o que fazer quando o CNPJ já existe lá — atualizar,
  duplicar ou ignorar?

Sem essa última resposta eu construo às cegas e você descobre o mapeamento errado
depois de sincronizar mil leads.

### Telefonia

`POST /api/dialer/calls` só registra o resultado. Discar de verdade exige
escolher provedor (Twilio, Zenvia, Totalvoice…) — **decisão comercial antes de
técnica**. Me diga qual e eu trago as credenciais necessárias.

---

## 3 · Melhora o que já funciona (opcional)

### Serasa — bloco "Contatos"

```bash
SERASA_CLIENT_ID=
SERASA_CLIENT_SECRET=
SERASA_PACKAGE_TOKEN=
SERASA_ENV=production
```

O bloco `contacts` da ficha de empresa e de pessoa depende disto. Sem, o resto
da ficha funciona normalmente — só esse bloco fica vazio.

### LinkedIn — decisores por scraping

```bash
LINKEDIN_LI_AT=
```

**Está no `.env` e vazio.** É o cookie `li_at` de uma sessão logada do LinkedIn.
Sem ele, a montagem de base com `decisoresFonte=linkedin` cai no caminho da
Assertiva — que é o padrão e costuma ser melhor de todo jeito. Vale registrar
que raspar o LinkedIn viola os termos de uso deles e a conta pode ser bloqueada;
a Assertiva não tem esse problema.

### `PROXY_SECRET`

```bash
PROXY_SECRET=
```

Só faz sentido quando o serviço de dados roda atrás de um proxy separado. **No
uso local não precisa** — o CapiBLU está montado em processo.

### `EMERGENCY_RESET_SECRET`

```bash
EMERGENCY_RESET_SECRET=
```

Libera `POST /api/auth/emergency-reset`. Deixe **ausente** — a rota fica inerte,
que é o desenho. Só defina se ficar sem nenhum admin conseguindo entrar, e apague
depois de usar.

---

## Já configurado — não precisa trazer nada

| Serviço | Para quê |
|---|---|
| `MEETIME_TOKEN` | Migração da conta. Já importou 1.199 leads e 2.984 ligações |
| `ASSERTIVA_CLIENT_ID` / `_SECRET` | Telefone, decisores, enriquecimento — o motor da prospecção |
| `MK_TEL_KEY` / `MK_CPF_PATH` | Perfil completo de pessoa |
| `WORKAPI_KEY` | Verificação de telefone (integralX) |
| `FDX_TOKEN` / `_PF` | Consulta cadastral |
| `MISTRAL_API_KEY` | Resumo por IA no dossiê |
| `BRIGHTDATA_API_KEY` | LinkedIn via API, alternativa ao cookie |

---

## Ordem sugerida

1. **SMTP** — é o que destrava a cadência de e-mail, e provavelmente você já tem
   as credenciais.
2. **Evolution** — se a BLU já roda uma instância, são três linhas.
3. Testar os dois com `BLUUTIME_SEND` **desligado**, depois ligar.
4. **Decidir sobre o Ploomes** — e aí eu sigo a Fase 4.

Serasa e LinkedIn podem esperar: nenhum bloqueia fluxo, só deixam bloco vazio.
