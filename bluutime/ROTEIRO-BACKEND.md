# Roteiro até o backend ficar completo

Estado atual: **94 rotas**, CRUD inteiro de pé, migração da conta real funcionando.
O que falta não é cadastro — é **o que acontece sozinho** e **o que sai do sistema**.

## O diagnóstico em uma frase

O Bluutime hoje sabe guardar tudo e não sabe fazer nada sozinho: nenhum processo
de fundo avança cadência, nenhuma mensagem sai de verdade (WhatsApp e e-mail só
gravam no banco), e a ponte com o CapiBLU só passa JSON — o que zera planilha,
modelo e PDF.

## Fase 1 — Motor de execução ✅

Sem isso o produto não rodava: a fila nascia vazia e nada avançava sozinho.

| Item | O que era | Onde ficou |
|---|---|---|
| **Fuso horário** | `_schedule_cadence` usava `utcnow()` e aplicava `best_hour` em cima — a atividade das 18h caía às 15h de Brasília | `agenda.py` |
| **Feriado** | O modelo `Holiday` existia e **nunca era consultado**; o agendador só pulava fim de semana | `agenda.py` |
| **Tick de fundo** | Ninguém fechava cadência. Na operação real "Fim de cadência" é o maior motivo de perda (254 de 507) | `tick.py` |
| **Modelos de mensagem** | Passo de e-mail/WhatsApp não tinha texto | `Template` + `render.py` |
| **Regra de avanço** | Toda atividade era materializada de uma vez, sem reação à resposta do lead | `flow.py` |

Dois bugs apareceram ao testar e foram corrigidos junto:

- `queue_score` comparava hora UTC com a janela local do lead — a fila priorizava
  pela hora errada.
- `PATCH /leads/{id}` **aceitava `cadenceId` e ignorava em silêncio**: o campo não
  estava no mapa, então a rota devolvia 200 sem gravar nada. Agora campo
  desconhecido é 400.

### O que o motor faz agora

| Rota | Comportamento |
|---|---|
| `POST /leads/{id}/start` | Agenda as etapas em dias úteis, no fuso da operação, pulando feriado |
| `POST /execution/activities/{id}/execute` | Com `replied: true` **pausa a cadência** — continuar disparando e-mail para quem já está conversando com o SDR queima o lead |
| `POST /execution/leads/{id}/resume` | Retoma preservando o espaçamento original entre etapas, recontado a partir de hoje |
| `POST /execution/activities/{id}/reschedule` | Encaixa na janela útil — antes dava para agendar ligação para domingo às 3h |
| `POST /admin/tick` | Roda agora o que o laço de 5 min faria |
| `GET/POST /templates` + `/templates/{id}/preview` | Modelos com `{{variável}}`, e a pré-visualização avisa quais ficariam vazias |

Verificado de ponta a ponta: 5 etapas agendadas em dia útil às 18h locais, resposta
pausando 4 atividades, retomada reagendando, domingo 3h ajustado para segunda 9h,
e o tick fechando cadência com o motivo "Fim de cadência".

## Fase 2 — Ponte binária com o CapiBLU ✅

`capiblu_client.call()` terminava em `r.json()`, então nenhum XLSX, PDF ou upload
atravessava a ponte. Agora `call_raw` devolve bytes e headers, e `call_files`
repassa multipart.

### Rotas novas

| Rota | O que faz |
|---|---|
| `POST /export/{empresas·vinculos·modelo·planilha}` | XLSX, preservando o nome que o CapiBLU escolheu (ele carrega o filtro da consulta) |
| `GET /dossie/{cpf·cnpj}/{doc}` | PDF; `insight`, `familia` e `web` são repassados como opt-in porque cada um gasta consulta a mais |
| `POST /planilha/upload` · `/modelo/analisar` | Recebem a planilha do usuário |
| `GET /planilha/catalogo` | 37 campos em 4 grupos, por fonte e custo |
| `POST /planilha/enriquecer` · `/planilha/linha` | Preenche a aba, ou uma linha só como prévia |
| `GET/POST /modelos` · `GET /modelos/campos` | Layout de coluna que o cliente pede |

Verificado de ponta a ponta com CNPJs reais: subir planilha → 37 campos no
catálogo → enriquecer 3 de 3 linhas com razão social, situação, capital e
telefone da Assertiva → baixar XLSX de 7 colunas com as originais preservadas.

### Três coisas que a ponte teve de consertar

1. **Erro silencioso.** Várias rotas do serviço de dados devolvem **HTTP 200 com
   `{"status": "error"}`** — "upload expirado", "selecione ao menos um campo".
   Repassado assim, o front trata como sucesso e mostra tabela vazia sem dizer o
   porquê. `_unwrap()` converte em 422.
2. **Duas formas na mesma resposta.** `/enrich/run` devolve `base_cols` como
   lista de texto e `added_cols` como lista de objeto; juntar os dois e mandar
   para o export dava **500**. `_norm_columns()` aceita as duas formas.
3. **Nome de parâmetro.** O dossiê espera `doc`, não `documento`.

### Por que a lista de exports é fechada

`EXPORTS` é um mapa fixo em vez de proxy de caminho livre: um proxy genérico
deixaria o cliente alcançar qualquer rota do serviço de dados por fora das
checagens do Bluutime — inclusive as que gastam consulta paga.

## Fase 3 — Canais de verdade ✅

Ver [`CANAIS.md`](CANAIS.md) para configurar. Uma regra manda no desenho:
**nunca fingir que enviou**. `POST /conversations/{id}/messages` gravava a linha
e devolvia 200 — a conversa mostrava a mensagem como enviada sem ninguém ter
recebido nada. E `instances/state` devolvia `CONNECTED` fixo, sem credencial
nenhuma configurada.

Agora todo envio devolve um estado explícito, e "não configurado" é um estado,
não um sucesso silencioso:

| Status | O que houve |
|---|---|
| `SENT` | O provedor aceitou e devolveu um id |
| `FAILED` | O provedor recusou |
| `SIMULATED` | Envio desligado ou sem credencial — nada saiu |
| `BLOCKED` | Recusado aqui (não perturbe, fora da janela, sem destino) |

| Canal | Estado |
|---|---|
| WhatsApp | Evolution API: envio, estado real da instância, webhook de entrada casando pelos últimos 8 dígitos, `fromMe` descartado |
| E-mail | SMTP com `Message-ID` guardado para casar a resposta depois; rastreio de abertura preparado e **desligado** |
| Telefonia | Continua registrando resultado — discar depende de escolher provedor, que é decisão comercial |

### O freio de mão

Ter credencial não basta: enquanto `BLUUTIME_SEND != 1`, tudo volta `SIMULATED`.
Sem isso, no dia em que alguém colar a chave da Evolution no `.env`, a cadência
inteira dispararia para leads reais sem ninguém ter decidido isso.

### O bug que o teste pegou

`forcar` servia a dois propósitos e acabou **furando o "não perturbe"** — a
atividade foi concluída para um lead marcado. Separado em dois: `forcar` é
cosmético (manda com variável vazia), `foraDaJanela` é decisão de horário, e
**não perturbe não tem escape por parâmetro**. Para falar com o lead, tira-se a
marca no cadastro dele: ato deliberado e auditável.

Esse sinal vinha da Assertiva, era guardado e **nunca consultado**. Agora
bloqueia em e-mail, WhatsApp e no registro de ligação.

## Fase 4 — Saída e integrações

- Entrega de webhook com reenvio e assinatura HMAC (o modelo `Webhook` existe, nada dispara)
- Sincronia com um CRM de verdade — Ploomes é o que a BLU usa
- Token de API com escopo, no padrão que o CapiBLU já tem

## Fase 5 — Governança ✅

### Dois cadastros de papel, um nível efetivo

Nenhum dos dois responde sozinho: o **login** é do CapiBLU (`admin`/`user`), e o
**papel operacional** vem do Meetime (`ADMINISTRATOR`/`MANAGER`/`SALESMAN`), no
`User` do Bluutime — que é quem é dono de lead. A ligação é o e-mail, e
`perm.py` os resolve em `sdr` < `gestor` < `admin`.

| Rota | Exige |
|---|---|
| Criar · alterar · excluir cadência | gestor |
| Excluir base de leads | gestor |
| Ação em massa sobre leads | gestor |
| Ver a trilha de auditoria | gestor |

Verificado: SDR recebe **403 nas cinco**, admin passa.

### Escopo por dono

`GET /flow/leads` e a fila de execução passam por `perm.escopo_leads`. SDR vê só
a própria carteira; gestor e admin veem tudo. Antes disso, qualquer conta
listava os leads da empresa inteira — medido: **1.199 para admin, 0 para SDR**.

Uma consequência de desenho que vale saber: SDR **sem `User` correspondente por
e-mail não é dono de nada**, e recebe lista vazia. É deliberado — melhor vazio
do que a carteira inteira por falta de vínculo — mas significa que todo SDR de
verdade precisa do registro operacional com o mesmo e-mail do login.

### Trilha de auditoria (LGPD)

O produto lê CPF, telefone, endereço e renda de pessoa física a partir de bases
de terceiros. Tratamento sem registro é o que não dá para explicar depois.

Fica no **middleware**, não espalhado pelas rotas, para que rota nova nasça
auditada — depender de cada autor lembrar de chamar o log é como o
`nao_perturbe`, que era coletado e nunca consultado.

O documento é **mascarado** na trilha (`76.***.***/0001-07`): ela existe para
provar quem acessou o quê, e reescrever o CPF inteiro num lugar a mais aumenta
a exposição em vez de reduzir.

Só o que toca pessoa entra — `DOSSIE`, `PESSOA`, `PESSOA_PERFIL`,
`TELEFONE_REVERSO`, `ASSERTIVA`, `ENRIQUECIMENTO`, `DECISORES`, `MONTAR_BASE`,
`ENVIO`. Listar cadência e abrir o painel não entram: registrar tudo transforma
a trilha em ruído e some com o que importa.

Um erro que o teste pegou: escrevi os padrões contra os caminhos internos do
CapiBLU (`/capiblu/api/company/...`) e esqueci os do Bluutime
(`/api/capiblu/empresas/...`) — a consulta de decisores passava sem registro.
Agora os dois vocabulários casam.

### Não perturbe

Feito na Fase 3: bloqueia e-mail, WhatsApp e registro de ligação, sem escape por
parâmetro.

---

Ordem recomendada: **1 ✅ → 2 ✅ → 3 ✅ → 5 ✅ → 4**. A fase 4 é a única que depende de
decisão comercial (qual CRM), o resto é técnico e independente.

## Canal: um vocabulário, não dois

WhatsApp **já** era modelado — como `SOCIAL_POINT` + `social_network="WHATSAPP"`,
que é como o Meetime faz. O problema não era falta de tipo, era haver dois
vocabulários para a mesma coisa:

| Onde | Como dizia "WhatsApp" |
|---|---|
| `Activity` · `LeadActivity` | `type="SOCIAL_POINT"` + `social_network="WHATSAPP"` |
| `Template` | `channel="WHATSAPP"` |

Isso deixava pendurar um modelo de WhatsApp num passo de e-mail sem ninguém
reclamar — só se descobriria quando a mensagem saísse errada para um lead real.

**Decisão:** o armazenamento continua igual ao do Meetime (sem migração, sem
perder compatibilidade) e o canal passa a ser **derivado**, por `channel_of()`
em `models.py`:

| type | social_network | canal |
|---|---|---|
| `E_MAIL` | — | `EMAIL` |
| `SOCIAL_POINT` | `WHATSAPP` | `WHATSAPP` |
| `SOCIAL_POINT` | outro | `SOCIAL` |
| `CALL` · `SEARCH` | — | `CALL` · `SEARCH` |

`activity()` e `lead_activity()` passam a expor `channel`, e montar uma etapa com
modelo de canal diferente agora é 400. É esse `channel` que a Fase 3 vai
perguntar na hora de enviar — não o `type`.
