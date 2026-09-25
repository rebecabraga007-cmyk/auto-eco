# Auditoria do backend do Bluutime (25/09/2026)

Duas frentes, lidas no código e conferidas uma a uma antes de corrigir: segurança e
permissões; corretude, dados e desempenho. As correções foram testadas numa cópia do
banco (`regressao.py`: 13 de 13 casos passando, mais a perda duplicada devolvendo 409).

## Corrigido

### Segurança

| Peso | Problema | Correção |
|---|---|---|
| Crítico | O serviço de dados montado em `/capiblu` decidia admin e grupo pelos headers `X-User-*` **que vinham do navegador**. Um SDR mandava `X-User-Role: admin` e trocava a URL da Meetime para roubar o token, lia o CRM de outro grupo ou jogava custo na conta de outra pessoa | `app.py`: em todo `/capiblu/*` os headers de identidade do cliente são descartados e trocados pelos da sessão (`capiblu_client.identidade`) |
| Alto | As rotas `/api/capiblu/*` chamavam o serviço por dentro e escapavam do limite diário de consultas pagas | A cota agora é cobrada em `capiblu_client.call` para toda rota paga |
| Alto | O `para` novo do envio aceitava qualquer destino: a atividade virava relay de e-mail/WhatsApp com o domínio da empresa | SDR só envia para os contatos cadastrados no lead; fora disso, só gestor |
| Alto | Conversa de WhatsApp sem lead furava dono e "não perturbe" (bastava digitar o telefone em outro formato) | SDR só abre conversa a partir de lead seu; telefone normalizado; "não perturbe" conferido |
| Alto | `PATCH /leads/{id}` deixava o SDR trocar o dono do lead | Trocar responsável, cliente ou base exige gestor (reenviar o mesmo valor continua ok) |
| Médio | Bases de leads e rascunhos de importação sem dono (ler, sobrescrever e apagar o de outra pessoa) | Amostra da base segue o escopo do SDR; rascunho só para quem criou ou gestor |
| Médio | Estatísticas de ligação sem a permissão de estatística; derrubadas e extrato expunham telefone, nome e custo de todos | Permissão aplicada; derrubadas e extrato mostram ao SDR só as próprias ligações |
| Médio | `register_call` não conferia o dono do lead | `exigir_dono_lead` |
| Médio | `GET /api/meetime/preview/*` aberto a qualquer usuário | Exige gestor |
| Médio | `/t/c/{token}?u=` redirecionava para qualquer URL (phishing com o domínio da BLU) | Só redireciona para link que estava na mensagem daquele token |
| Médio | Reapontar webhook não passava pela validação de rede interna (SSRF) | `url_publica_valida` também no PATCH |
| Médio | Login sem limite de tentativas; segredo do reset comparado com `!=` | 8 erros em 15 min bloqueiam o e-mail (e o IP real do Cloudflare); `hmac.compare_digest` no reset. Fica no `auth.py` compartilhado com o CapiBLU |

### Corretude e dados

| Peso | Problema | Correção |
|---|---|---|
| Alto | E-mail bloqueado dava erro 500 (`token` não inicializado) e não registrava o bloqueio | Reescrito o envio: reserva, envia, registra |
| Alto | `LostReason(active=True)` derrubaria o `tick` inteiro (expiração, reaproveitamento e webhooks parados para sempre) | Removido; cada etapa do `tick` agora tem transação própria e trava contra execução simultânea |
| Alto | Clique duplo em Ganho gerava dois feedbacks e dois webhooks; lead podia ficar ganho e perdido ao mesmo tempo nas estatísticas | Desfecho repetido devolve 409; ganho zera a perda e vice-versa |
| Alto | Atividades PAUSED ficavam órfãs e ressuscitavam lead encerrado em "retomar cadência" | Limpeza trata PENDING e PAUSED; retomar recusa lead ganho/perdido |
| Médio-alto | Perda automática por fim de cadência não fechava a prospecção nem avisava os webhooks | Fecha o `CadenceRun` e enfileira `LEAD.LOST` |
| Médio | "Hoje" calculado com meia-noite UTC (21h em Brasília) no progresso, no Iniciar novos leads e no painel de controle | Meia-noite local |
| Médio | Dois SDRs clicando juntos em Iniciar novos leads agendavam a mesma cadência em dobro | Reserva condicional por `UPDATE ... WHERE status='WAITING'` |
| Médio | Clique duplo em Enviar mandava a mensagem duas vezes | Atividade reservada como `SENDING` antes do envio; o `tick` solta reservas presas há mais de 10 min |
| Médio | Banco em `journal_mode=delete`, sem espera de lock ("database is locked" com importação ou tick) | WAL e `busy_timeout=5000` por conexão |
| Médio | Cadência sem passos aceita em troca em massa e no Iniciar novos leads (lead parado fora da fila) | Recusada |
| Médio | Perda em massa não limpava reaproveitamento, não fechava a prospecção nem disparava webhook | Corrigido |
| Médio | `current_step` avançava com atividade extra e pulada; reagendar devolvia atividade feita para pendente | Só passo da cadência cumprido avança; só pendente é reagendável |
| Médio | Nenhum índice nas colunas quentes | 11 índices criados na migração (`CREATE INDEX IF NOT EXISTS`) |
| Médio | Fila de execução com centenas de consultas (lead, cadência, cliente, base e atividade um a um) | Carregamento antecipado na mesma consulta |
| Baixo | Entradas estranhas davam 500 (`start_leads`, `reprospect`, Academia, `draftId`) | Viram 400 ou são descartadas |

## Não corrigido (fica registrado)

- `delete_base?com_leads=true` quebra FOREIGN KEY quando algum lead tem ligação ou conversa: deveria reaproveitar a sequência do `bulk delete`.
- `goal_progress` e `control_panel` fazem várias consultas por usuário; com 50 mil leads passam de 5 s. Pede um `GROUP BY user_id` por métrica.
- O `prospecting` do ranking ignora os filtros de cadência e usuário do Dashboard.
- `webhook_delivery` e `audit_log` crescem sem limpeza.
- Remetente livre no domínio (`emailFrom` no Meu perfil), limite do webhook do WhatsApp por IP atrás do túnel, `userId` livre na prévia de modelo, CSV sem limite de tamanho, meta diária de todos em `/flow/users`, e o `_disponiveis` sem conferir se o SDR participa da cadência.
- `PROXY_SECRET` vazio no Bluutime: com a correção do crítico deixou de ser explorável pelo navegador, mas vale definir no Hetzner.
