# Auditoria: os 57 endpoints sem tela

**195 endpoints** no projeto — 137 no Bluutime, 58 no serviço de dados do CapiBLU.
Cruzando com o que o `app.js` de fato chama: **80 têm tela, 57 não têm.**

Cada um foi testado ao vivo. Das 34 rotas de leitura, **33 responderam 200** com
dado real; a única que não responde é `/api/meetime/status`.

## Como a nota funciona

Todos aqui, por definição, estão sem tela. A nota mede o que falta **além** disso:

| Nota | Significado |
|---|---|
| **9–10** | Não precisa de tela — infraestrutura, webhook ou rota que a UI consome por baixo. Completo |
| **7–8** | Backend completo e testado, com tabela. Só falta interface |
| **5–6** | Backend completo, mas depende de tela para ser usável na prática |
| **3–4** | Funciona, porém com problema conhecido (lentidão, parâmetro obscuro) |
| **0–2** | Casca: rota existe e não entrega o que promete |

---

## 9–10 · Completo, tela não se aplica (12)

Infraestrutura. Contar como "falta tela" seria erro de leitura.

| Endpoint | Nota | Situação |
|---|---|---|
| `GET /health` | 10 | Sonda de saúde. 30 b, instantâneo |
| `GET /` | 10 | Serve a SPA |
| `POST /api/whatsapp/webhook` | 10 | Chamado pelo provedor, não pelo navegador. Testado: `fromMe` descartado, entrada casada pelos últimos 8 dígitos |
| `GET /api/auth/me` | 10 | A UI **usa** por baixo, no `boot()` |
| `GET /api/featureflag` | 10 | Devolve `CONTROL_PANEL`, `ALLOW_CONFIGURABLE_PERMISSIONS`… |
| `GET /api/users/me/permissions` | 10 | 8 permissões nomeadas |
| `GET /api/me/company` | 10 | Cadastro da BLU |
| `GET /api/flow/users` | 10 | Consumido pelos seletores de SDR |
| `GET /api/capiblu/tools` | 10 | Catálogo das 18 ferramentas; alimenta a tela "Todas as ferramentas" |
| `GET /api/flow/cadences/overview` | 9 | Contagem por cadência; a tela de Cadências já traz o mesmo embutido |
| `POST /api/admin/tick` | 9 | Gatilho manual do laço de fundo. Só admin |
| `POST /api/auth/emergency-reset` | 9 | Recuperação de senha. Inerte sem `EMERGENCY_RESET_SECRET` — é o desenho |

## 7–8 · Backend pronto, falta só a tela (18)

Aqui está a **lacuna real**. Tudo testado e com tabela; só não há por onde clicar.

### Modelos de mensagem — 5 rotas · nota 7

`GET/POST/PATCH/DELETE /api/flow/templates` + `POST /templates/{id}/preview`

Entregue na Fase 1 e sem interface. Tabela `template` existe e tem registro. A
pré-visualização avisa quais variáveis ficariam vazias — é o que evita mandar
"Olá {{primeiro_nome}}" para um cliente, e hoje ninguém alcança isso pela tela.
`DELETE` desativa em vez de apagar quando há passo apontando para o modelo.

**Sem essa tela, montar cadência de e-mail ou WhatsApp exige chamar a API na mão.**

### Envio e entregas — 6 rotas · nota 7

`GET /api/envio/{canais,quem-sou-eu,auditoria,entregas}` · `POST /api/envio/{atividades/{id},teste}`

Toda a Fase 3. `canais` reporta `NOT_CONFIGURED` corretamente; `entregas` já tem
5 registros; `auditoria` devolve a trilha com documento mascarado.

`POST /envio/teste` é o que permite conferir a configuração antes de encostar em
lead real — e é justamente o que não tem botão.

### Administração de usuários — 7 rotas · nota 8

`GET/POST /api/admin/users` · `PATCH/DELETE /api/admin/users/{uid}` ·
`POST /api/admin/users/{uid}/password` · `GET/POST/DELETE /api/admin/grupos`

Backend completo, vindo do `auth.py` do CapiBLU. Testado: `admin/users` lista as
3 contas, `admin/grupos` responde `{"grupos":[]}`.

O Bluutime tem tela de **Usuários** (33 linhas), mas ela lê `/api/flow/users` — a
lista operacional vinda do Meetime. Criar conta de acesso, trocar senha de
alguém ou mexer em grupo continua só pelo CapiBLU.

## 5–6 · Funciona, mas depende de tela para servir (17)

### Fichas do CapiBLU — 8 rotas · nota 6

| Endpoint | Testado |
|---|---|
| `GET /api/capiblu/empresas` | 200 · 7.869 b |
| `GET /api/capiblu/empresas/{cnpj}` | 200 · 4.096 b |
| `GET /api/capiblu/empresas/{cnpj}/{bloco}` | 200 · decisores |
| `GET /api/capiblu/pessoas/{cpf}` | 200 |
| `GET /api/capiblu/pessoas/{cpf}/{bloco}` | 200 · `mk`/`parentes`/`vinculos`/`contacts` |
| `GET /api/capiblu/telefones/{numero}` | 200 · telefone reverso |
| `GET /api/capiblu/telefones/{numero}/pertence/{doc}` | 200 |
| `GET /api/capiblu/modelos/campos` | 200 · 2.040 b |

✅ **Feito.** As três fichas passaram de `JSON.stringify` para ficha de verdade:

- **Ficha da empresa** — cadastro, atividade, endereço e QSA da base local
  (grátis), e os blocos pagos (decisores, vínculos, conexões) atrás de botão,
  com o aviso de que gastam consulta. Decisores vêm com o nível traduzido —
  “nível 3 · influencia” em vez do número solto — e o resumo da Assertiva
  (funcionários, porte, idade). O CNPJ na lista da Prospecção B2B abre a ficha.
- **Ficha da pessoa** — cadastro, perfil Mk com telefones (categoria e flag de
  WhatsApp), e-mails e endereços, e parentes. O que não tem forma conhecida cai
  numa tabela montada a partir das próprias chaves, não em JSON.
- **Telefone reverso** — quem está atrelado ao número, com tipo (pessoa ou
  empresa) e link para a ficha quando é CNPJ; mostra quantas consultas restam
  no dia.

### Execução — 3 rotas · nota 6

`POST /api/flow/leads/{lid}/start` · `execution/leads/{lid}/resume` ·
`execution/activities/{aid}/reschedule`

O motor da Fase 1. `start` agenda em dia útil e fuso certo; `resume` retoma
preservando o espaçamento; `reschedule` encaixa na janela.

**Nota 6 e não 7** porque `resume` e `reschedule` são ações que o SDR precisa
tomar no meio do dia — sem botão, o motor tem marcha ré e ninguém alcança.

### Análise — 4 rotas · nota 6

`GET /api/flow/control-panel` · `statistics/summary` · `goals/{ref}/calculate-effort` ·
`dialer/calls/statistics/dropped`

Testadas, com dado real: o painel traz Felipe Oliveira com 17 ganhos e 178
perdas; `calculate-effort` calcula 259 leads necessários para a meta; ligações
derrubadas devolve 32 KB.

Duas têm tela parcial (Painel e Estatísticas mostram parte), mas
`calculate-effort` e `dropped` não aparecem em lugar nenhum.

### Relatórios — 1 rota · nota 6

`GET /api/reports/{key}` — quatro chaves, **todas testadas e funcionando**:
`activity-statistics`, `executed-activities`, `dropped-calls`, `leads`
(248 KB de CSV).

A tela de Relatórios existe e oferece 4 links, mas a rota aceita chave livre e
devolve 404 para o que não conhece — sem a lista, é adivinhação.

### Troca de senha — 1 rota · nota 5

`POST /api/auth/change-password` — funciona, sem tela. O usuário não consegue
trocar a própria senha pelo Bluutime.

## 3–4 · Problema conhecido (3)

| Endpoint | Nota | Problema |
|---|---|---|
| `GET /api/meetime/status` | 3 → **7** ✅ | **Corrigido.** Percorria os 7 recursos em série com `sleep(0.6)` e repique em 429; passava de 25 s sem responder. Agora vão de três em três com prazo de 20 s — devolve em ~21 s, e o recurso que não responde a tempo volta como `"tempo esgotado"` em vez de segurar a resposta |
| `GET /api/meetime/preview/{resource}` | 5 | Funciona (1.145 b), mas só aceita `users`, `cadences`, `leads`, `prospections`, `calls`, `webhooks`, `feedbacks` — sem tela, a lista é invisível |
| `POST /api/meetime/sync` | 5 | A migração inteira, só por `curl`. Funcionou (1.200 leads, 2.984 ligações), mas leva 5 min sem nenhum progresso visível |

## Casos à parte (7)

| Endpoint | Nota | Situação |
|---|---|---|
| `GET/POST/DELETE /api/admin/tokens` | 8 | Token de API com escopo, pronto. É a Fase 4 |
| `GET /api/admin/consumo` | 8 | Consumo por usuário; a tela "Consumo e custo" existe mas está magra (653 b) |
| `POST /api/capiblu/planilha/linha` | 7 | Prévia de uma linha. **A tela usa** o caminho equivalente via `enriquecer` com `limite=1` — duplicação, não lacuna |
| `POST /api/capiblu/export/{kind}` | 9 | Falso negativo da minha varredura: a UI **chama** com `empresas` e `planilha` |
| `DELETE /api/flow/lead-bases/{bid}` | 7 | Exige gestor. Sem botão |

---

## O resumo em três frases

**Não há casca no projeto.** Das 34 rotas de leitura testadas, 33 devolveram dado
real; 30 dos 57 endpoints têm tabela por trás e os outros 27 são passagem para o
CapiBLU ou infraestrutura. Nenhum endpoint promete algo que não entrega.

**O buraco é de interface, concentrado em três lugares:** modelos de mensagem
(5 rotas), envio e entregas (6) e administração de contas (10). São 21 das 57 —
e são justamente as três coisas que entreguei nas Fases 1, 3 e 5.

**Um problema de verdade, já corrigido:** `/api/meetime/status` não respondia.
Era o único endpoint quebrado na prática — agora volta em ~21 s com contagem
parcial em vez de travar.

## Corrigido depois desta auditoria (bloco 1)

| O quê | Situação |
|---|---|
| `/api/meetime/status` travando | Paralelizado com prazo. Responde em ~21 s |
| **Tabela de feriados vazia** | O suporte existia desde a Fase 1 e **não havia um único registro** — o agendador consultava, não achava nada e caía para "só pula fim de semana". `feriados.py` calcula os nacionais (Páscoa por Meeus/Jones/Butcher) e carrega na subida: 26 para 2026–2027 |
| Mensagem órfã no banco | Causa-raiz: o **SQLite ignora `ondelete=CASCADE`** sem `PRAGMA foreign_keys=ON`, que é por conexão. Os modelos declaravam cascata e o banco não cumpria |
