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

## Fase 2 — Ponte binária com o CapiBLU

`capiblu_client.call()` termina em `r.json()`. Só isso zera três abas inteiras.

- `call_raw` (bytes) e `call_files` (multipart) no cliente
- Rotas de exportação com `StreamingResponse` — XLSX padrão Datastone, export de vínculos, export por modelo
- Upload de planilha (`enrich/upload`, `modelo/analisar`)
- Dossiê PDF por proxy

Destrava: **Minha planilha** (0,43/10), **Meus modelos** (1,13/10) e todo export.

## Fase 3 — Canais de verdade

Hoje "enviar WhatsApp" grava uma linha na tabela e devolve 200. Ninguém recebe nada.

| Canal | O que falta |
|---|---|
| WhatsApp | Envio real pela Evolution API, webhook de entrada, mensagem recebida virando conversa, estado real da instância (hoje `CONNECTED` fixo) |
| E-mail | Não existe rota nenhuma. Envio, rastreio de abertura/clique, e-mail respondido avançando o lead |
| Telefonia | `POST /calls` só registra resultado. Falta discar pelo provedor, gravar e receber status por webhook |

## Fase 4 — Saída e integrações

- Entrega de webhook com reenvio e assinatura HMAC (o modelo `Webhook` existe, nada dispara)
- Sincronia com um CRM de verdade — Ploomes é o que a BLU usa
- Token de API com escopo, no padrão que o CapiBLU já tem

## Fase 5 — Governança

- Permissão por papel **na rota**: hoje o middleware exige login e cota, mas um SDR
  pode apagar cadência e ver o financeiro inteiro
- Escopo por dono: SDR enxerga todos os leads da empresa
- Trilha de auditoria e registro de acesso a dado pessoal (LGPD) — o produto lê
  CPF, telefone e renda; hoje isso não fica registrado
- `nao_perturbe` bloqueando discagem, não só sendo coletado

---

Ordem recomendada: **1 ✅ → 2 → 3 → 5 → 4**. A fase 4 é a única que depende de
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
