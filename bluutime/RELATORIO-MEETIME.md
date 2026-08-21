# Relatório de engenharia reversa — Meetime → Bluutime

Fonte: 6 arquivos `meetime.com.br*.zip` (capturas "salvar página como" do dashboard em 19/08/2026, conta **BLU Sales Group**, `companyId 9210`).
Cada zip é uma sessão progressivamente mais completa: o `z0` só tem o Dashboard, o `z5` acumula Prospecção, Ligações, WhatsApp, Estatísticas, Integrações e Financeiro. As respostas de API vêm salvas como `.html` dentro de `app.meetime.com.br/` — é daí que sai o modelo de dados real, com os números da própria operação BLU.

---

## 1. O que o Meetime é, tecnicamente

| Camada | Tecnologia |
|---|---|
| Front-end legado (99% das telas) | **AngularJS 1.x** + `ui-router` (estados `mt.app.*`), template Limitless/Bootstrap 3, gráficos Highcharts |
| Front-end novo (ilhas) | **Angular moderno** em `app.meetime.com.br/ng/*` — só `control-panel` e `whatsapp/conversation`, embutidos via `<iframe>` no app velho |
| Auth | **Keycloak** (`assets/keycloak/keycloak.js`) + Firebase Auth/Firestore/Realtime DB (notificações em tempo real) |
| Telefonia | **Twilio** WebRTC no browser + **Asterisk** como provider SIP (`voipProvider: ASTERISK`, `webPhone: TWILIO`) |
| Back-end | Java/Kotlin (erros vazam `br.com.meetime.whatsapp_middleware.dtos.evolution_api...`) |
| WhatsApp | **Evolution API** por trás de um `whatsapp-middleware` próprio |
| Instrumentação | Mixpanel, GTM, LinkedIn Ads, Cloudflare, CloudHumans (chat de suporte), Statuspage |

Detalhe revelador: o "Painel de Controle" — a feature mais nova, marcada como `NOVO` no menu — é um **iframe** de app Angular novo dentro do AngularJS antigo. O Meetime está no meio de uma migração de front-end travada. Isso é uma janela: a superfície de produto está congelada há tempo.

---

## 2. Mapa completo de funcionalidades

Extraído das 289 rotas `mt.app.*` e dos 94 templates capturados.

### 2.1 Prospecção (módulo `FLOW`) — o coração
- **Painel** (`control-panel`) — visão do gestor: por SDR, leads prospectando/disponíveis/ganhos/perdidos, atividades pendentes/executadas/ignoradas quebradas por tipo, ligações não conectadas e derrubadas.
- **Execução** (`cadence-execution`) — a fila de trabalho do SDR. Sub-telas: `activities` (fila do dia), `power-dialer` (discagem em série), `hot-leads`, modais de execução por tipo de atividade (pesquisa, e-mail, ponto social, ligação), modais de ganho/perda, `startLeadsModal`, indicador de tempo por atividade.
- **Cadências** (`cadence-management`) — CRUD de cadências com `focus` (OUTBOUND / INBOUND / ACTIVE_INBOUND / OTHER), `priority` (VERY_HIGH…LOW), `stepsCount`, usuários atribuídos com meta diária, flag `executing`, visualização de leads, export, pausa, integração por cadência com CRM.
- **Atividades** (`activity-management`) — biblioteca de atividades reutilizáveis com template de e-mail (assunto + HTML) e instrução de script para ligação/WhatsApp. Suporta merge tags `{{firstName}}`, `{{company}}`.
- **Leads** (`lead-list` + `lead.details`) — lista com filtro por etapa/responsável/cadência, ações em massa (transferir, trocar cadência, voltar para espera, marcar perdido, apagar execução), e o **card do lead** com timeline por tipo de passo (call/email/search/socialPoint/meeting/feedback), chat de WhatsApp embutido, resumo por IA (`mtSummaryIa`), agendamento de reunião, painel do deal no CRM.
- **Bases de leads** (`lead-base-list`, `leads-importation`) — wizard de importação CSV: upload → associação de campos → configuração de execução → processamento.
- **Ajustes** (`config.*`) — meta diária, motivos de perda, calendário de trabalho (dias úteis + feriados), campos personalizados, associação de campos por CRM, fit score / lead scoring, blacklist, Account Based Sales, permissões configuráveis, feedback de oportunidade.

### 2.2 Ligações (módulo `DIALER`)
Painel de ligações, lista de ligações, extrato (minutos + custo), ajustes (geral, números, gravações), softphone modal (`modalIphoneDialer`), add-ons `PREDICTIVE_DIALER` e `CALLER_ID_NUMBERS`.

### 2.3 Demonstrações (módulo `DEMO`)
Painel, lista, ajustes de sala, "demo instantânea". **Não contratado pela BLU** (`modules: [FLOW, DIALER, WHATSAPP]`).

### 2.4 WhatsApp (módulo `WHATSAPP`)
Tela de Conversas (Angular novo, iframe) + integração via instância (`whatsapp/instances/state`).

### 2.5 Estatísticas
- **Prospecção**: conversão por etapa, dashboard, performance, overview de cadência (status + conversão acumulada), motivos de perda (3 recortes), templates de e-mail.
- **Demo e Ligação**: overview, funil, agrupado, cumulativo, histórico.
- **Feedback de Oportunidade**: preenchidos, não preenchidos, qualificação.

### 2.6 Relatórios (feature nova)
Exatamente 3, todos por download:
1. **Estatísticas de Atividades** — produtividade e performance por usuário.
2. **Atividades Executadas** — todas as atividades realizadas ou ignoradas com horário, usuário, cadência e lead.
3. **Ligações Derrubadas** — chamadas encerradas manualmente em até 10s.

### 2.7 Integrações
Pipedrive (2 gerações), Salesforce, RD Station Marketing, RD Station CRM, Nectar CRM, HubSpot, Ploomes (via webhook), Google Agenda, caixa de e-mail (Nylas v3), e-mail whitelabel com config de DNS, **Webhooks** (eventos tipo `LEAD.WON`), **API Token**, Meetime Recording.

### 2.8 Empresa / Perfil
Usuários (papéis `ADMINISTRATOR`, `MANAGER`, `SDR`, `SALESMAN`), times, caller IDs, financeiro, whitelabel de e-mail, perfil e senha.

---

## 3. Modelo de dados (enums reais capturados)

```
Lead.status        WAITING · EXECUTING · ON_EXTRA_ACTIVITY · PAUSED_FROM_EXECUTING
                   · WON · LOST · SWITCHED_CADENCE
Activity.type      SEARCH · CALL · E_MAIL · SOCIAL_POINT(socialNetwork: WHATSAPP|LINKEDIN)
Cadence.focus      OUTBOUND · INBOUND · ACTIVE_INBOUND · OTHER
Cadence.priority   VERY_HIGH · HIGH · MEDIUM · LOW
Call.status        CONNECTED · NOT_PERFORMED
Call.output        MEANINGFUL · NOT_MEANINGFUL · NO_CONTACT
Call.originType    EXTENSION | receiverType: MOBILE · LANDLINE
User.roles         ADMINISTRATOR · MANAGER · SDR · SALESMAN
Company.modules    FLOW · DIALER · WHATSAPP · DEMO
Permissions        LEADS_VIEW_ALL · LEADS_DELETE · LEADS_ADD_MANUAL
                   · LEADBASE_UPLOAD · STATISTICS_ACCESS
```

Campos de lead (`flow/new-lead-fields`): 16 nativos (`firstName`, `name`, `email`, `company`, `position`, `phone`, `site`, `state`, `city`, `linkedIn`, `twitter`, `facebook`, `annotations`, `salesmanEmail`, `externalReference`, `createdAt`) + personalizados — a BLU criou **CNPJ** como campo custom (`id 36596`).

Feature flags ativas na conta: `CONTROL_PANEL`, `ALLOW_CONFIGURABLE_PERMISSIONS`, `ALLOW_REPORT_EXTRACTION_ON_LEADS_PAGE`, `EXCLUSIVE_LEAD_BASE_QUEUE`, `SHOW_STATISTICS_ACTIVITIES_TAB`, `NYLAS_V3`, `SANKHYA_BILLING`.

---

## 4. Como a BLU realmente usa (e onde o Meetime não serve)

Os dados capturados são da operação BLU de agosto/2026. Eles dizem muito.

**A BLU opera prospecção para clientes dentro de uma única conta Meetime.** A lista de usuários mistura `@blusalesgroup.com.br` com `@frotai.com.br`, `@planning.com.br`, `@v4company.com`, `@trentiniadvocacia.com`. E as cadências carregam o cliente no *nome*, porque não há campo para isso:

```
ADV [BLU] [START]          IND [BLU] [START]        CNT [BLU] [START]
[FROTAÍ] [LEADS RICARDO]   [IMOB] [Planning]        [ENERGIA] [Planning]
[TRANSPORT] [Planning]     [CONNECT] [BLU] [DAVID]  LISTA LULEADS [BLU] [START]
```

Isso é convenção de nomenclatura substituindo modelagem. O Meetime tem `teams` — e a BLU tem **exatamente um time** ("BLU", com 1 usuário). A multi-operação não é suportada; é improvisada.

**Números da operação (01–19/08/2026):**

| Métrica | Valor |
|---|---|
| Execuções de cadência no mês | 597 |
| Atividades finalizadas (SDR ativo) | 272 — 158 ligações, 98 WhatsApp, 16 e-mails |
| Atividades **atrasadas** | 151 (56% das finalizadas) |
| Dias trabalhados | 4 |
| Ligações | 170 · 145 conectadas · **19 significativas (11%)** |
| Duração média | 246s · melhor janela: **18h–19h, 96% de conexão** |
| Oportunidades no mês | 3 ganhos · 7 perdidos |
| Meta mensal | 25 oportunidades, 15% de conversão |
| Esforço calculado p/ meta | 167 leads · 810 atividades · **41 atividades/SDR/dia** |
| Leads disponíveis sem dono | 10 (+1.043 na fila de 1 SDR) |
| Cadências cadastradas | ~90, a maioria com `executing: false` |
| Bases importadas | dezenas de `[ADV 72] - [JUN 26]`, `[Lista Luleads]`, `[CNT 34]`… |

**Custo:** `financial/company` mostra **R$ 1.789,98/mês** — FLOW R$ 581,19/usuário, COMBO R$ 327,68, add-on CALLER_ID R$ 46,41, cobrança por boleto, 3 usuários gratuitos disponíveis mas só 2 pagantes ativos. Ou seja: a BLU paga ~R$ 21,5k/ano por uma ferramenta em que 2 pessoas trabalham, para operar prospecção de terceiros num modelo que a ferramenta não modela.

**As três dores estruturais que o Meetime não resolve para a BLU:**
1. **Multi-cliente.** Não existe entidade "cliente/operação". Vira prefixo no nome da cadência e mistura de e-mails na mesma base de usuários.
2. **Origem dos leads.** As bases entram por CSV manual (`[Lista Luleads] - [JUN 26]`). A BLU já tem o **CapiBLU** gerando essas listas — hoje o caminho é exportar XLSX e reimportar à mão.
3. **Atividade atrasada como regra.** 151 de 272 atividades saíram fora do prazo. A fila não prioriza sozinha; o `bestHourToCall` (18h–19h, 96%) existe no relatório mas não é usado para ordenar a fila.

---

## 5. O que o Bluutime precisa ser

Um clone funcional do FLOW + DIALER do Meetime, com três coisas que o Meetime não tem:

**a) Cliente como entidade de primeira classe.** Toda cadência, lead, base e meta pendura num cliente (BLU, Frotaí, Planning, V4…). Dashboard filtra por cliente. Fim dos prefixos `[BLU]`.

**b) CapiBLU como fonte nativa de leads.** Em vez de "importar CSV", o passo é "montar lista no CapiBLU → jogar direto na cadência", já com CNPJ, sócios, decisores e telefone validado. A base de leads deixa de ser um upload e passa a ser uma *query salva*.

**c) Fila inteligente.** Ordenação por janela de melhor contato, prioridade da cadência e atraso — em vez de ordem cronológica pura.

O resto (cadências, atividades, execução, timeline, estatísticas, relatórios, softphone, WhatsApp) é paridade com o Meetime.

---

## 6. Escopo do MVP front-end entregue

Arquivo: [`bluutime-mvp.html`](bluutime-mvp.html) — HTML único, sem dependências externas além das fontes IBM Plex.
Design: sistema do CapiBLU (papel `#F1EEE7`, azul-noite `#12385C`, terracota `#A85A2C`, IBM Plex Sans/Mono, borda em vez de sombra, sidebar agrupada por intenção).
Dados: mock derivado dos números reais capturados acima.

| Tela | Origem Meetime | Estado no MVP |
|---|---|---|
| Painel do gestor | `prospector.control-panel` | ✅ interativo, por SDR e por cliente |
| Dashboard de metas | `mt.app.goals` | ✅ oportunidades × meta, ranking, insights |
| Execução | `cadence-execution.activities` | ✅ fila do dia, card do lead, ações por tipo, ganho/perda |
| Leads | `prospector.lead-list` | ✅ filtro por etapa/cliente/cadência |
| Cadências | `cadence-management` | ✅ lista com foco, prioridade, etapas, overview |
| Atividades | `activity-management` | ✅ biblioteca com template e script |
| Bases de leads | `lead-base-list` | ✅ **+ importar do CapiBLU** (novo) |
| Ligações | `dialer.list` + `statement` | ✅ lista, estatísticas, melhor horário |
| WhatsApp | `whatsapp.conversation` | ✅ layout de conversas |
| Estatísticas | `statistics.flow` | ✅ conversão, atividades, perdas, origem |
| Relatórios | `mt.app.reports` | ✅ os 3 relatórios |
| Ajustes | `prospector.config.*` | ✅ metas, motivos de perda, calendário, campos |
| Clientes | — | ✅ **novo** — a entidade que falta no Meetime |

Fora do MVP (front-end): softphone WebRTC real, editor de cadência drag-and-drop, OAuth dos CRMs, Demonstrações.

---

## 7. Recomendação de arquitetura para a versão real

Aproveitar o que já está de pé no CapiBLU em vez de começar do zero:

- **Back-end**: FastAPI (`lupa-empresas/backend`) já tem auth JWT (`auth.py`), tokens de API com escopo (`api_tokens.py`), controle de custo (`custos.py`) e o conector Meetime (`meetime.py` — útil para migrar os dados de saída).
- **Dados**: Postgres para o domínio transacional (leads, cadências, atividades, execuções) — SQLite não aguenta a fila de execução com concorrência.
- **Fila/agendamento**: as atividades precisam de um scheduler (dias úteis + feriados do `flow/configuration/*` são regra de negócio, não enfeite).
- **Telefonia**: Asterisk + WebRTC é o caminho que o Meetime usa; alternativa é começar com click-to-call via provedor e evoluir.
- **WhatsApp**: Evolution API — mesma escolha do Meetime, e a BLU já tem experiência com `whatsapp-web.js` no projeto de métricas de BDR.
- **Migração**: a API do Meetime (`auth/api-token`) permite extrair leads, cadências e histórico antes do desligamento.

Ordem de construção sugerida: Clientes → Cadências/Atividades → Leads/Bases (com CapiBLU) → Execução → Estatísticas → Ligações → WhatsApp.
