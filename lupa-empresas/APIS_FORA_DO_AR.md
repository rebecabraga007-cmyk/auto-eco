# APIs fora do ar no CapiBLU

**Medido em 25/09/2026**, de dentro do servidor de produção (Hetzner `capiblu-data-01`),
com as chaves do `.env` de produção. As chamadas de teste foram escolhidas para não gastar
crédito: listagens, pedido de token, corpo vazio (para ver a validação) e documento
inválido.

> Este retrato vale para o dia em que foi medido. Fornecedor volta e cai. A seção
> [Como medir de novo](#como-medir-de-novo) repete o teste em 1 minuto.

---

## Resumo

| Fornecedor | Situação | O que o servidor responde | Causa provável | Quem sente |
|---|---|---|---|---|
| **WorkAPI** (3 módulos) | 🔴 fora do ar | `523 Origin is unreachable`, em todos os caminhos, do Hetzner **e** da rede local | O servidor da própria WorkAPI caiu (a Cloudflare dela não alcança a origem) | Achar pessoa por nome, telefones por CPF, telefone reverso, validação de telefone, planilha |
| **FDX / RAIS** | 🔴 fora do ar | `401 {"response": "token expirado"}` nos dois tokens | Token vencido; precisa renovar com o fornecedor | Aba Vínculo empregatício, vínculos por CPF, funil |
| **Bright Data: Web Scraper API** (`/datasets/v3/scrape`, `/v3/trigger`) | ✅ **reativada em 25/09** | Estava `400 Customer is not active` com `GET /status` → `"suspended"`; depois da reativação, `"active"` | Conta tinha sido **suspensa** entre 17/09 e 25/09; reativada pela dona da conta no painel de cobrança. Ver [3.1](#31-o-que-houve-com-a-bright-data) | Voltou: Funcionários no LinkedIn por URL, `/employees` e decisores via slug testados ok |
| **Bright Data: `/datasets/v3/filter` + `/v3/snapshot`** | ⚫ endpoint removido | `404 Cannot POST /datasets/v3/filter` | A Bright Data aposentou essa versão da API | Nada hoje: o caminho está desligado (`BRIGHTDATA_USE_DATASET` vazio) |
| **Google (raspagem da busca)** | 🔴 bloqueado | `200` com página "ative o JavaScript", **0 perfis** | O Google passou a exigir JavaScript; raspagem com `httpx` não tem mais resultado | Só entraria se a chave da Bright Data fosse removida |
| **LinkedIn (cookie `li_at`)** | 🔴 sessão morta | `302` (redireciona para login) | Cookie expirado | Só era usado junto com a busca do Google (acima) |
| **DonoDoZap** | 🔴 bloqueado | Site responde `200`, mas a ação do servidor exige token Cloudflare Turnstile (CAPTCHA) | Proteção anti-robô, não é queda | Nenhuma tela chama; só as rotas de API |

**No ar** (para referência): Assertiva Localize, Casa dos Dados (v5 e v4), BrasilAPI,
Mistral, Meetime, Bright Data *Datasets* (`/datasets/search`, `/datasets/snapshots`).
**Desligados por falta de configuração**, não por queda: Serasa Experian (sem
`SERASA_CLIENT_ID/SECRET` no `.env`), Zenvia SMS (sem `ZENVIA_API_TOKEN`) e o WhatsApp do
Bluutime (wuzapi no ar, mas `connected: false`: falta parear o celular pelo QR).

---

## Tabela de funções: o que parou e quem substitui

Uma linha por **função de negócio** que depende de um endpoint fora do ar. "Já integrado"
é alternativa que já tem código no CapiBLU e respondeu no teste de 25/09; "externo" é
fornecedor que faz a mesma coisa mas exigiria contrato e integração nova (não testados).

| # | Função | API atual (endpoint) | Situação | Telas / rotas afetadas | Alternativa já integrada | Cobertura da alternativa | Alternativas externas | Ação recomendada |
|---|---|---|---|---|---|---|---|---|
| 1 | **Nome → CPF** (achar a pessoa) | WorkAPI `GET /intelgrax-nomev2?name=` | 🔴 523 | Achar uma pessoa; funil `resolver_pessoa`; `/api/v1/pessoas` | **Base JBR local** (já é o 1º passo do funil); **Assertiva** `/localize/v3/nome-endereco` | JBR: CPF, sexo, nascimento (sem mãe/endereço), grátis. Assertiva: completa, paga por consulta | BigDataCorp, Procob, Directd, Lemit, Datastone | Nada urgente: JBR já cobre o CPF; Assertiva cobre o resto |
| 2 | **CPF → telefones, endereços, empregos** | WorkAPI `GET /integrax-cpf?cpf=` | 🔴 523 | Uma pessoa (`/api/person/{cpf}/mk`); leads (`fonte_tel=mk`); funil; dossiê; `/api/v1/pessoas/{cpf}/telefones` | **Assertiva** `/localize/v3/cpf` (`fonte_tel=assertiva`); **Serasa** `/enrichments/people` (código pronto, sem credencial) | Assertiva: igual ou melhor (flag WhatsApp, "não perturbe", último contato), porém mais cara | BigDataCorp, Procob, Directd, Nova Vida TI, Lemit, Datastone | Trocar o padrão `fonte_tel` para `assertiva` enquanto durar a queda |
| 3 | **Telefone → dono do número** | WorkAPI `GET /intelgrax-tel?phone=` | 🔴 523 | De quem é este telefone; validação `/pertence` na Prospecção B2B; `/api/telefone/planilha`; colunas `vf_*` e `nome_donodozap` | **Assertiva** `/localize/v3/telefone` (rota `/api/assertiva/telefone`) | Assertiva: faz a mesma função, mas `/pertence` e a planilha não sabem usá-la | BigDataCorp, Procob | Ensinar `/pertence` e a planilha a cair na Assertiva |
| 4 | **Telefone → titular do WhatsApp** | DonoDoZap `POST /telefone/{n}` + `GET /resultado` | 🔴 CAPTCHA | Só rotas de API (nenhuma tela) | **Assertiva** `/localize/v3/telefone`; **wuzapi** `/user/check` | Assertiva: titular. wuzapi: só "tem WhatsApp" + nome do perfil, e exige parear | BigDataCorp, Procob | Aposentar o módulo |
| 5 | **CNPJ → todos os funcionários (RAIS)** | FDX `GET api.php?raispj=` | 🔴 token expirado | Vínculo empregatício; começo de todo funil; `/api/v1/empresas/{cnpj}/funcionarios` | **Bright Data Search** por empresa; **Assertiva** `/possiveis-decisores` | Bright Data: só quem tem LinkedIn. Assertiva: só gestores. Nenhuma traz a lista RAIS completa com CPF | BigDataCorp, Datastone (vínculos derivados da RAIS) | **Renovar o token FDX** |
| 6 | **CPF → empregadores (RAIS)** | FDX `GET api.php?rais_pf=` | 🔴 token expirado | `/api/person/{cpf}/vinculos`; API v1 | **Assertiva** `/localize/v3/cpf` (bloco de empregos) | Parcial: empregos declarados, sem datas RAIS | BigDataCorp, Datastone | Renovar o token FDX |
| 7 | **URL da empresa no LinkedIn → dados da empresa** | Bright Data `POST /datasets/v3/scrape` (dataset empresas) | ✅ reativada 25/09 | Funcionários no LinkedIn (`/api/linkedin/empresa`); "Não achou? Ver empresas" | **Bright Data Search** no mesmo dataset, por `url`/`company_id`; `linkedin_cache.db` e base de empresas LI no disco | Mesma informação, vinda do snapshot (pode ter semanas) em vez da página ao vivo | Coresignal, People Data Labs, Apify, ScrapingDog | Feito: conta reativada. Opcional: trocar o scrape pela Search |
| 8 | **Nome da empresa → funcionários em destaque** (slug adivinhado) | Bright Data `POST /datasets/v3/scrape` (empresas + perfis) | ✅ reativada 25/09 | `/api/company/{cnpj}/employees`; `…/vinculos/cargos`; leads com `decisores_fonte=linkedin`; `/api/v1/empresas/{cnpj}/linkedin` | **Bright Data Search** por empresa (`buscar_agora`, já no ar) | Melhor: a página pública só mostra ~1 funcionário; a Search traz a lista | Coresignal, People Data Labs | Opcional: trocar para a Search (tira a dependência do Scraper) |
| 9 | **URL do perfil → cargo, nome, cidade** | Bright Data `POST /datasets/v3/scrape` (dataset perfis) | ✅ reativada 25/09 | As mesmas da linha 8 | **Bright Data Search** no dataset de pessoas, por `url`/`id` | Mesma informação, do snapshot | People Data Labs, Coresignal, Apify, Scrapin.io | Opcional: trocar para a Search (tira a dependência do Scraper) |
| 10 | **Lista completa de funcionários (job assíncrono)** | Bright Data `POST /datasets/v3/filter` + `GET /v3/snapshot/{id}` | ⚫ endpoint removido | Nenhuma (flag `BRIGHTDATA_USE_DATASET` desligada) | **Bright Data Search** (síncrona, 2–3 s) | Superior | — | Apagar o caminho |
| 11 | **Nome da empresa → perfis via Google** | Google `GET /search?q=site:linkedin.com/in` (+ cookie `li_at`) | 🔴 muro de JS / cookie expirado | Nenhuma (só roda sem chave da Bright Data) | **Bright Data Search**; **Mistral** `web_search` | Bright Data: superior | Serper.dev, SerpAPI, Brave Search API, DataForSEO | Apagar o caminho (e parar de mandar o `li_at` ao Google) |

## A queda que ninguém vê

As rotas do CapiBLU respondem **HTTP 200** mesmo quando o fornecedor caiu: o erro vai no
corpo (`{"status": "error"}`). Por isso o log do `capiblu-data` mostra
`GET /api/person/…/mk 200 OK` hoje, com a WorkAPI fora do ar há horas, e o
[`saude.py`](backend/saude.py) (que vigia serviços, disco e descritores) não percebe nada.
Ver [Achados colaterais](#achados-colaterais).

---

## 1. WorkAPI

`https://api.workapi.dev/v1/gateway`, header `x-api-key`. Cada módulo tem a sua chave e a
sua cota diária.

**Diagnóstico:** `523` em `/`, `/v1/gateway` e nos três módulos, a partir do Hetzner e da
rede da usuária. O 523 vem da Cloudflare **da WorkAPI**, dizendo que a origem deles não
responde. Não é o nosso túnel: `data.capiblu.net` respondeu normalmente no mesmo momento.
Em 23/09 já tinha acontecido a mesma coisa (com 522).

### Endpoints

| Endpoint | Chave (`.env`) | Função no código | O que faz | Onde isso aparece no CapiBLU |
|---|---|---|---|---|
| `GET /intelgrax-nomev2?name=` | `WORKAPI_KEY` · 2.000/dia | [`workapi.nome_search`](backend/workapi.py) | **Nome → pessoas**, com CPF completo, nascimento, mãe e endereço | Aba **Achar uma pessoa** (`GET /api/person/name-search`); funil `resolver_pessoa` (`POST /api/funil/resolver`, `/api/funil/pessoa`); Bluutime `/api/capiblu/pessoas`; API v1 `/api/v1/pessoas` |
| `GET /integrax-cpf?cpf=` | `MK_AUTH_VALUE` · 15.000/dia | [`mkbuscas.consulta_cpf`](backend/mkbuscas.py) | **CPF → telefones, endereços, empregos/empresas, CBO** | Aba **Uma pessoa** (`GET /api/person/{cpf}/mk`); ranking de homônimos em `/api/company/{cnpj}/employees`; telefones dos leads em `/api/company/{cnpj}/leads` (fonte padrão `fonte_tel=mk`); funil (`_pelo_mk`, `_telefones_do_cpf`); dossiê em PDF; Bluutime `/api/capiblu/pessoas/{cpf}/mk`; API v1 `/pessoas/{cpf}/telefones` |
| `GET /intelgrax-tel?phone=` | `MK_TEL_KEY` · 5.000/dia | [`mkbuscas.consulta_telefone`](backend/mkbuscas.py), `telefone_pertence` | **Telefone → CPFs/CNPJs donos do número** | Aba **De quem é este telefone** (`GET /api/phone/{p}/reverse`); validação de telefone na Prospecção B2B (`GET /api/phone/{p}/pertence/{doc}`); lote `POST /api/telefone/planilha`; colunas `vf_*` da Minha planilha; dossiê; Bluutime `/api/capiblu/telefones/*` e `…/validate-phone` |

**Quando cai:** as funções devolvem `status: "error"` com o texto cru da Cloudflare
(`WorkAPI 523: <!DOCTYPE html>…`), que aparece na tela.

### Quem faz a mesma função

| Função | Já integrado no CapiBLU (no ar) | Fora do CapiBLU |
|---|---|---|
| **Nome → CPF** | **Base JBR local** (223 mi de CPFs, grátis, instantânea; o funil já consulta antes da WorkAPI em `funil._pela_jbr`). Só traz nome, sexo e nascimento: sem mãe nem endereço. **Assertiva** `/localize/v3/nome-endereco` (já é o passo 08 do funil e a rota `POST /api/assertiva/nome`). | BigDataCorp, Procob, Directd, Lemit, Datastone |
| **CPF → telefones/empregos** | **Assertiva** `/localize/v3/cpf`: traz telefones com flag de WhatsApp, "não perturbe", último contato, e-mails e empregos. Já é selecionável: `fonte_tel=assertiva` em `/api/company/{cnpj}/leads` (o Bluutime já usa por padrão). Custa mais por consulta que a WorkAPI. **Serasa** `/enrichments/people`: código pronto em [`serasa.py`](backend/serasa.py), falta contratar e pôr a credencial. | BigDataCorp (telefones, e-mails, dados profissionais), Procob, Directd, Nova Vida TI, Lemit, Datastone |
| **Telefone → dono** | **Assertiva** `/localize/v3/telefone` (rota `GET /api/assertiva/telefone` já existe, mas a validação `/pertence` e a planilha só sabem usar a WorkAPI). | BigDataCorp, Procob. Parcial: **wuzapi** `/user/check` diz se o número tem WhatsApp e o nome do perfil, **não** o titular (e depende de parear o WhatsApp). |

**✅ Feito em 25/09/2026: contingência "Work API Suspenso"** no Painel administrativo. Um
interruptor manda as três funções para a Assertiva, no formato da WorkAPI, em todas as telas,
no Bluutime e na API v1 (código em [`backend/workapi_suspensa.py`](backend/workapi_suspensa.py)).
Os usos em laço têm proteção de custo:
- o funil confere homônimos dentro do teto do lote e pula a busca por nome da WorkAPI (a
  etapa 08 da Assertiva já faz essa busca);
- a lista de funcionários só desempata quem tem até 3 homônimos
  (`WORKAPI_SUSPENSA_MAX_HOMONIMOS`);
- a busca por nome passa a contar na cota diária de quem não é admin.

Com a contingência ligada, renda/score e parentes ficam vazios na ficha do CPF: a Assertiva
não os entrega nessa consulta.

---

## 2. FDX APIs / RAIS

`GET https://api.fdxapis.us/api.php`, com o token na query string.

**Diagnóstico:** `401 {"status": false, "response": "token expirado"}` nos dois tokens
(`FDX_TOKEN` e `FDX_TOKEN_PF`). O endpoint está vivo; o que venceu foi o acesso. O
fornecedor responde o mesmo 401 para token errado e para token vencido, mas aqui a mensagem
é explícita. O próprio código já chama esse gateway de "irregular" (`funil.py:318`).

### Endpoints

| Endpoint | Chave | Função no código | O que faz | Onde isso aparece no CapiBLU |
|---|---|---|---|---|
| `?raispj=<cnpj>` | `FDX_TOKEN` | [`rais.vinculos_cnpj`](backend/rais.py) | **CNPJ → quem trabalha ou trabalhou lá** (nome, CPF, admissão/demissão, faixa de renda) | Aba **Vínculo empregatício** (`GET /api/company/{cnpj}/vinculos`, `…/vinculos/cargos`); todo começo de funil (`funil.Empresa.preparar`); API v1 `/empresas/{cnpj}/funcionarios` |
| `?rais_pf=<cpf>` | `FDX_TOKEN_PF` | [`rais.vinculos_cpf`](backend/rais.py) | **CPF → empregadores que a pessoa teve** | `GET /api/person/{cpf}/vinculos`; API v1 |

**Quando cai:** `status: "unavailable"` com "Acesso à base RAIS recusado (token
expirado). Renove o FDX_TOKEN…".

### Quem faz a mesma função

| Função | Já integrado no CapiBLU (no ar) | Fora do CapiBLU |
|---|---|---|
| **CNPJ → funcionários** | **Bright Data Datasets** `/datasets/search` por empresa (aba Funcionários no LinkedIn, `POST /api/linkedin/funcionarios`): só quem tem LinkedIn, mas com cargo atual. **Assertiva** `/localize/v3/possiveis-decisores`: só gestores, com CPF e cargo. | Renovar o token FDX (é o único com a lista RAIS completa). BigDataCorp e Datastone vendem vínculos empregatícios derivados da RAIS. |
| **CPF → empregadores** | **Assertiva** `/localize/v3/cpf` (bloco de empregos). | BigDataCorp (dados profissionais), Datastone |

**Caminho mais curto:** renovar o token com a FDX. Nenhuma alternativa integrada devolve a
lista completa de funcionários com CPF.

---

## 3. Bright Data

`https://api.brightdata.com`, header `Authorization: Bearer $BRIGHTDATA_API_KEY`.

### 3.1 O que houve com a Bright Data

> **Atualização 25/09/2026: conta reativada.** Depois da reativação no painel, `GET /status`
> passou a `"status": "active"`, e `/datasets/v3/scrape` voltou a responder erro de
> validação (`No data to trigger`) em vez de `Customer is not active`. Testado de ponta a
> ponta pelo próprio CapiBLU: `POST /api/linkedin/empresa` com a Localiza voltou `ok` em 6 s,
> e `GET /api/company/16670085000155/employees` voltou `ok` (`source: brightdata`) em 12 s.
> O `/status` ainda mostra `can_make_requests: false` / `zone_not_found`, mas isso se refere a
> zonas de **proxy**, que o CapiBLU não usa. O resto desta seção é o registro da investigação.

**A conta estava suspensa.** A própria API da Bright Data respondia, em `GET /status`:

```json
{"status": "suspended", "customer": "hl_390b364b", "can_make_requests": false}
```

**O que a suspensão bloqueia e o que ela deixa passar** (testado hoje com chamadas reais):

| Produto | Teste | Resultado |
|---|---|---|
| Web Scraper API (`/datasets/v3/scrape`) | Raspar `linkedin.com/company/movida`, uma URL válida | ❌ `400 Customer is not active` |
| Datasets: Search (`/datasets/search/{id}`) | Buscar a Movida pelo domínio (1 registro, US$ 0,0025) | ✅ `200`, devolveu a empresa |
| Datasets: snapshots (`/datasets/snapshots`) | Listar as entregas da assinatura | ✅ `200` |
| Proxies (zonas) | `GET /zone/get_active_zones` | Nenhuma zona ativa (`[]`). O CapiBLU não usa proxy, então isso não afeta nada |

**Quando começou.** O extrato de consumo da conta (`GET /customer/bw`, agosto a 25/09)
mostra:
- **Web Scraper:** último uso em **17/09**. O último job registrado é das 12:48 UTC. Não há
  nenhum uso depois disso.
- **Search:** uso contínuo até **24/09** (última chamada às 22:08 UTC pelo livro-caixa
  local), e funcionando hoje.

Ou seja, a suspensão aconteceu **entre 17/09 e 25/09**, e ninguém percebeu porque as
funções que dependem do Scraper devolvem `blocked` na tela com HTTP 200 no log. Não dá para
afirmar o dia exato: pode ser que ninguém tenha usado essas telas nesse intervalo.

**Por quê.** A chave de API do CapiBLU não tem permissão para ler o saldo
(`GET /customer/balance` → `403 Your API key lacks the required permissions`), então daqui
não dá para ver o motivo. O padrão da Bright Data para conta suspensa é pedir a reativação
em **brightdata.com/cp/setting/billing**. Na prática, isso costuma significar saldo
pré-pago esgotado ou pagamento recusado. A assinatura de Datasets é cobrada à parte, e por
isso a Search continua funcionando.

**Consumo real vs. o que o CapiBLU registra.** A Bright Data cobrou, de 06/09 a 24/09,
**~13.600 registros** em buscas (≈ US$ 34 a US$ 2,50/mil), fora os 100 mil da entrega
mensal de 04/09 (assinatura). O livro-caixa local (`gastos_bd` em
`/capiblu_data/linkedin_cache.db`) registra só **3.672 registros (US$ 9,18)**. A
diferença é quase toda do dataset de pessoas enriquecido (`gd_me5ppxjr2ge6icjuh0`): 8.113
registros desde 14/09 que não aparecem em lugar nenhum do CapiBLU.

A causa está no código: `brightdata_pessoas.buscar_agora` e `buscar_varias` chamam a Search
e **não lançam o gasto**. Só `buscar_por_filtro`, `buscar_empresas_por_filtro` e
`nome_no_linkedin` chamam `registrar_gasto`. `buscar_agora` é o que roda na aba
Funcionários no LinkedIn e no funil de decisores (colunas `de_*` da Minha planilha, em
jobs de lote). Isso explica o pico de 16 e 17/09 (2.542 e 1.949 registros).

**Risco próximo.** A próxima entrega da assinatura mensal (100 mil perfis; a de setembro
chegou em 04/09) e o `pull-mensal.timer`, que roda no dia 5, dependem da conta. Com a
suspensão, a entrega de outubro pode não vir.

**O que fazer, em ordem:**
1. ✅ **Feito em 25/09:** a dona da conta reativou pelo painel de cobrança
   (brightdata.com/cp/setting/billing).
2. ✅ **Conferido em 25/09:** `GET /status` com `"status": "active"` e `/datasets/v3/scrape`
   com `[]` respondendo `No data to trigger` (validação), não `Customer is not active`.
   O `can_make_requests` continua `false` porque se refere a proxy, que o CapiBLU não usa.
3. Fazer `buscar_agora`/`buscar_varias` lançarem o gasto, senão o painel de custos do
   CapiBLU continua mostrando ~1/4 do que a Bright Data cobra.
4. Opcional: trocar o `/v3/scrape` pela Search (linhas 7 a 9 da tabela de funções), o que
   tira do CapiBLU a dependência do produto suspenso.

### 3.2 Endpoints

**Diagnóstico:** a conta tem **dois produtos**, e só um caiu.
- **Web Scraper API** (`/datasets/v3/scrape`, `/v3/trigger`): `400 Customer is not
  active` enquanto a conta esteve suspensa; **reativada em 25/09** (ver 3.1).
- **Datasets / Marketplace** (`/datasets/search/{dataset}`, `/datasets/snapshots`,
  `/datasets/list`): **no ar**. Testado com busca de 0 resultados → `200`.
- **`/datasets/v3/filter` e `/datasets/v3/snapshot/{id}`**: `404`, endpoint removido pela
  Bright Data (já anotado em `brightdata_pessoas.py:9-12`).

#### Endpoints fora do ar

| Endpoint | Função no código | O que faz | Onde isso aparece no CapiBLU |
|---|---|---|---|
| `POST /datasets/v3/scrape?dataset_id=gd_l1vikfnt1wgvvqz95w` (empresas) | [`brightdata_pessoas.empresa_por_url`](backend/brightdata_pessoas.py) | **URL da página da empresa no LinkedIn → nome, company_id, nº de funcionários, setor, sede, site, funcionários em destaque**; deduz o CNPJ localmente | Aba **Funcionários no LinkedIn** (`POST /api/linkedin/empresa`); ajuda "Não achou? Ver empresas" (`GET /api/linkedin/empresas?conferir=N`) |
| mesmo endpoint, com slugs adivinhados | [`linkedin_scraper._brightdata_call`](backend/linkedin_scraper.py) via `_brightdata_employees` | **Nome da empresa → candidatos `linkedin.com/company/<slug>` → empresa + funcionários em destaque** | `GET /api/company/{cnpj}/employees` (Bluutime `/api/capiblu/empresas/{cnpj}/employees`, API v1 `/empresas/{cnpj}/linkedin`); `…/vinculos/cargos`; `/api/company/{cnpj}/leads?decisores_fonte=linkedin` |
| `POST /datasets/v3/scrape?dataset_id=gd_l1viktl72bvl7bjuj0` (perfis) | `linkedin_scraper._brightdata_call` | **Até 20 URLs de perfil → cargo, nome, cidade** (completa os funcionários acima) | As mesmas rotas da linha anterior |
| `POST /datasets/v3/filter` + `GET /datasets/v3/snapshot/{id}` | `linkedin_scraper._dataset_employees_by_company` | Lista completa de funcionários de uma empresa (job assíncrono) | Nenhuma hoje: só roda com `BRIGHTDATA_USE_DATASET=1`, que está desligado. Se alguém ligar, quebra. |

**Quando cai:** `linkedin_scraper` devolve `status: "blocked"`; o log do serviço guarda o
traceback de `_brightdata_call` (`linkedin_scraper.py:155`), mas a rota responde 200.

#### Endpoints da Bright Data que continuam no ar (não precisam de substituto)

`POST /datasets/search/{dataset}` (busca de pessoas e empresas: abas Funcionários no
LinkedIn, Prospecção de pessoas, lista unificada de empresas, `nome_no_linkedin`),
`GET /datasets/snapshots` + `/download` (pull mensal, timer `pull-mensal.timer`), e
`POST /datasets/filter` (v1; hoje sem chamador: `disparar()` é código morto).

#### Quem faz a mesma função

| Função | Já integrado no CapiBLU (no ar) | Fora do CapiBLU |
|---|---|---|
| **URL/slug da empresa → dados da empresa** | **Bright Data Search** no mesmo dataset de empresas (`gd_l1vikfnt1wgvvqz95w`), filtrando por `url` ou `company_id` em vez de raspar: é o mesmo padrão de `nome_no_linkedin`, que já filtra por `website_simplified`. O dado vem do snapshot (pode ter semanas), não da página ao vivo. **Base de empresas do LinkedIn no disco** e `linkedin_cache.db`: grátis, para o que já foi visto. | Reativar a Web Scraper API no painel da Bright Data. Coresignal (API de empresas), People Data Labs (Company Enrichment), atores do Apify, ScrapingDog |
| **URL de perfil → cargo/nome/cidade** | **Bright Data Search** no dataset de pessoas, filtrando por `url`/`id`. | Reativar a Web Scraper API. People Data Labs (Person Enrichment), Coresignal, Apify, Scrapin.io. (O Proxycurl, que fazia isso, encerrou em 2025.) |
| **Funcionários de uma empresa** | **Bright Data Search** por empresa: é o que `buscar_agora` já faz na aba Funcionários no LinkedIn, e funciona. | Coresignal, People Data Labs |

**Caminho mais curto:** as rotas que dependem de `/v3/scrape` fazem algo que a Search já
cobre. Trocar `empresa_por_url` e `_brightdata_employees` para buscar no dataset elimina a
dependência do produto desativado. Se o dado precisa ser do dia, a saída é reativar a Web
Scraper API.

---

## 4. Google (raspagem) e cookie do LinkedIn

| Endpoint | Função no código | O que faz | Onde isso aparece no CapiBLU |
|---|---|---|---|
| `GET https://www.google.com/search?q=site:linkedin.com/in "<empresa>"` (com `Cookie: li_at=…` se houver) | [`linkedin_scraper._google_search`](backend/linkedin_scraper.py) | **Nome da empresa → perfis públicos do LinkedIn**, lidos da página de resultados | As mesmas rotas de `/employees`, mas **só quando `BRIGHTDATA_API_KEY` está vazio**. Com a chave configurada, como está hoje, nunca roda. |

**Diagnóstico:** o Google devolve `200` com uma página que manda ativar o JavaScript e
zero perfis. O `li_at` responde `302` para o login do LinkedIn (sessão expirada). O
CapiBLU não chama `linkedin.com` diretamente em nenhum outro lugar.

**Quando cai:** `status: "blocked"` ("0 resultados").

### Quem faz a mesma função

| Já integrado no CapiBLU (no ar) | Fora do CapiBLU |
|---|---|
| **Bright Data Search** (o caminho principal, já no ar). **Mistral** com a ferramenta `web_search` (já usada no dossiê, `mistral.web_search_dossie`): aceita a mesma consulta `site:linkedin.com/in`. | APIs de SERP pagas por consulta: Serper.dev, SerpAPI, Brave Search API, DataForSEO. (A Bing Search API foi aposentada em 2025, e a Custom Search JSON API do Google está fechada para clientes novos.) |

**Recomendação:** não vale consertar. É um plano B de um plano A que funciona.

---

## 5. DonoDoZap

| Endpoint | Função no código | O que faz | Onde isso aparece no CapiBLU |
|---|---|---|---|
| `POST https://donodozap.com/telefone/{phone}` (Server Action do Next.js, header `next-action` fixo) → `GET /resultado?id={uuid}` | [`donodozap.consultar`](backend/donodozap.py) | **Telefone → nomes do titular do WhatsApp e CPF mascarado**, depois compara com o nome esperado | `GET /api/phone/{p}/donodozap`; Bluutime `/api/capiblu/telefones/{n}/donodozap`. **Nenhuma tela chama.** |

**Diagnóstico:** o site está no ar, mas a ação do servidor exige um token Cloudflare
Turnstile (CAPTCHA). Sem ele, responde 500. O módulo já devolve `status: "blocked"`. O hash
da ação também muda a cada deploy deles.

**Atenção ao nome:** a coluna `nome_donodozap` da tela e a rota `/api/telefone/planilha`
**não usam o DonoDoZap**: usam a WorkAPI `intelgrax-tel`. Ou seja, elas também estão fora
hoje, mas por causa da WorkAPI (seção 1).

### Quem faz a mesma função

| Já integrado no CapiBLU (no ar) | Fora do CapiBLU |
|---|---|
| **Assertiva** `/localize/v3/telefone` (titular do número). **wuzapi** `/user/check` e `/user/info`: se o número tem WhatsApp e o nome do perfil. A função `check_number` existe no Bluutime, mas nunca é chamada, e depende de parear o WhatsApp. | BigDataCorp, Procob (telefone reverso) |

---

## Achados colaterais

1. **Queda invisível.** Rota de dados responde 200 com `{"status": "error"}` no corpo, então
   nem o log nem o `saude.py` registram que um fornecedor caiu. Um teste por fornecedor no
   `saude.py` (as mesmas chamadas sem custo daqui) abriria chamado sozinho: 523 da WorkAPI,
   "token expirado" da FDX, "Customer is not active" da Bright Data.
2. **Credencial vazando para o lugar errado.** `_google_search` envia o cookie de sessão do
   LinkedIn (`li_at`) para `google.com` (`linkedin_scraper.py:468-469`). Não serve para nada
   lá e expõe a credencial. Hoje o cookie está expirado e o caminho não roda, mas vale
   remover.
3. **Erro cru na tela.** Quando a WorkAPI cai, a mensagem mostra o HTML/JSON da Cloudflare
   deles (`mkbuscas.py`: `f"WorkAPI {status}: {resp.text[:150]}"`).
4. **Caminho que quebra se ligado.** `BRIGHTDATA_USE_DATASET=1` ativa `/v3/filter`, que não
   existe mais.
5. **Gasto da Bright Data que não entra no painel.** `buscar_agora` e `buscar_varias` não
   chamam `registrar_gasto`, então ~3/4 do consumo real de setembro (8.113 de ~13.600
   registros) não aparece nos custos do CapiBLU. Ver 3.1.

---

## Como medir de novo

Do servidor, com o `.env` de produção (nenhuma destas chamadas gasta crédito):

```bash
ssh -i ~/.ssh/capiblu_vps root@167.233.71.218
```

```bash
cd /opt/capiblu/lupa-empresas && set -a && . ./.env && set +a
curl -s -o /dev/null -w "workapi %{http_code}\n" https://api.workapi.dev/v1/gateway
curl -s "https://api.fdxapis.us/api.php?token=$FDX_TOKEN&raispj=00000000000000"; echo
curl -s -X POST -H "Authorization: Bearer $BRIGHTDATA_API_KEY" -H "Content-Type: application/json" -d '[]' "https://api.brightdata.com/datasets/v3/scrape?dataset_id=gd_l1viktl72bvl7bjuj0"; echo
curl -s -H "Authorization: Bearer $BRIGHTDATA_API_KEY" https://api.brightdata.com/status; echo
```

O que significa cada resposta:
- **WorkAPI:** `523`/`522` = fora do ar; `401`/`403` = no ar.
- **FDX:** `token expirado` = vencido.
- **Bright Data:** `Customer is not active` = Web Scraper desativado; um erro de validação
  = produto ativo. `/status` com `"status":"suspended"` = conta suspensa;
  `"status":"active"` = ativa (ignore `can_make_requests`: é sobre proxy).
