# API CapiBLU — v1

Documentação técnica · Arquitetura REST · JSON · Autenticação por API Token

| | |
|---|---|
| **Versão** | 1.0 |
| **Arquitetura** | REST / HTTP |
| **Autenticação** | API Token (Bearer) |
| **Formato** | JSON |
| **URL base** | `https://capiblu-app.onrender.com/api/v1` |

---

## 1. Introdução

A API do CapiBLU permite que outros sistemas consultem os mesmos dados que a
plataforma usa: cadastro de empresas da Receita Federal, quadro de sócios com
CPF resolvido, possíveis decisores com cargo, vínculos empregatícios da RAIS,
telefones e parentes.

**O que dá para fazer:**

- Buscar empresas por UF, município, CNAE, porte e capital social
- Trazer sócios com CPF resolvido e decisores com cargo e nível de decisão
- Consultar quem trabalha (ou trabalhou) numa empresa, pela RAIS
- Descobrir onde uma pessoa trabalha, a partir do CPF
- Montar contatos prontos para abordagem, com telefone priorizado por atualidade
- Acompanhar o próprio consumo e o limite diário

**Pré-requisitos:** um token de API, gerado por um administrador do CapiBLU.

---

## 2. Autenticação

Toda requisição precisa do token no header:

```
Authorization: Bearer capi_a1b2c3d4_xxxxxxxxxxxxxxxxxxxxxxxx
```

### Como obter

Um administrador cria o token no painel (ou por `POST /api/admin/tokens`). O
valor em claro aparece **uma única vez, na criação** — o CapiBLU guarda apenas
o hash. Se perder, revogue e gere outro.

### Escopos

| Escopo | O que libera |
|---|---|
| `leitura` | Só o que sai de base local: empresas, sócios, busca por nome, CPF |
| `consulta` | Também o que **gasta consulta paga**: telefones, decisores, RAIS, parentes, conexões |

Um token `leitura` que chamar rota paga recebe **403** com explicação. Isso
existe para você poder entregar um token a um sistema de leitura sem risco de
ele gerar custo.

> **Segurança:** nunca exponha o token em repositório ou código de frontend.
> Use variável de ambiente.

---

## 3. Conceitos gerais

### 3.1 Datas

ISO 8601 em UTC: `2026-08-19T17:00:00Z`.
Datas vindas de bases públicas (RAIS, Receita) podem chegar no formato original
`dd/mm/aaaa` — nesse caso o campo tem sufixo `_br`.

### 3.2 Filtros

Endpoints de listagem aceitam filtros por query string:

```
GET /api/v1/empresas?uf=MG&municipio=GOVERNADOR%20VALADARES&porte=05
```

### 3.3 Paginação

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `page` | integer | Página, começando em 1 |
| `limit` | integer | Registros por página (máximos por rota) |

### 3.4 Estrutura das respostas

Todo retorno bem-sucedido usa o mesmo envelope:

```json
{
  "data": [ ... ],
  "meta": { "total": 100, "page": 1, "limit": 20, "fonte": "Receita Federal" }
}
```

Erros trazem corpo previsível:

```json
{ "error": { "code": "cnpj_invalido", "message": "CNPJ deve ter 14 dígitos." } }
```

| Status | Quando acontece |
|---|---|
| 200 | Sucesso |
| 400 | Requisição inválida (documento malformado, filtro impossível) |
| 401 | Token ausente, inválido ou revogado |
| 403 | Escopo insuficiente, ou usuário do token inativo |
| 404 | Recurso não encontrado |
| 429 | Limite diário de consultas atingido |
| 502/503 | Serviço de dados indisponível |

### 3.5 Custo por chamada

Rotas marcadas **(gasta consulta)** consomem o limite diário do usuário dono do
token — o mesmo contador da plataforma. Rotas de base local não consomem nada.
Consulte o saldo em `GET /api/v1/conta`.

---

## 4. Endpoints

### 4.1 Conta

#### `GET /conta`
Dados do usuário, do token em uso e do limite diário.

```json
{
  "data": {
    "usuario": { "id": 1, "nome": "Rebeca", "email": "rebeca@…", "role": "admin" },
    "token": { "id": 3, "nome": "Integração CRM", "escopo": "consulta" },
    "limites": { "consultas_por_dia": 100, "usadas_hoje": 12, "restantes_hoje": 88, "ilimitado": true }
  },
  "meta": { "gerado_em": "2026-08-19T20:14:03Z" }
}
```

---

### 4.2 Empresas

#### `GET /empresas`
Busca na base local da Receita Federal. Não gasta consulta.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `uf` | string | Sigla do estado |
| `municipio` | string | Nome do município |
| `cnae` | string | Código CNAE (vários separados por vírgula) |
| `porte` | string | `01` micro · `03` pequeno · `05` demais (médias e grandes) |
| `situacao` | string | Ex.: `ATIVA` |
| `capital_min` / `capital_max` | integer | Faixa de capital social |
| `com_telefone` | boolean | Só empresas com telefone na Receita |
| `somente_matriz` | boolean | Exclui filiais |
| `texto` | string | Busca livre por razão social / nome fantasia |
| `page` / `limit` | integer | Paginação (limit máximo 200) |

> A Receita não classifica "grande": `05` é o balde de médias **e** grandes.
> Para chegar nas grandes, combine `porte=05` com `capital_min`.

#### `GET /empresas/{cnpj}`
Cadastro completo: razão social, situação, CNAE, endereço, capital, QSA.

#### `GET /empresas/{cnpj}/socios`
Quadro de sócios com **CPF resolvido** quando a base local consegue cruzar.

```json
{ "data": [ { "nome": "CELIO COUTINHO DA CUNHA", "qualificacao": "Sócio-Administrador",
              "cpf": "03702149600", "data_entrada": "2021-06-10" } ],
  "meta": { "total": 1, "fonte": "Receita Federal (QSA)" } }
```

#### `GET /empresas/{cnpj}/decisores` **(gasta consulta)**
Possíveis decisores com cargo, classificados em três níveis de decisão.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `nivel` | string | `1` decide sozinho · `2` decide na área · `3` influencia |
| `cargo` | string | Filtro por cargo, ex.: `diretor` |
| `page` / `limit` | integer | Paginação |

Cobertura desigual: empresa grande costuma ter muitos, micro empresa quase nunca
tem — nesses casos o `meta.aviso` explica e `data` vem vazio.

#### `GET /empresas/{cnpj}/funcionarios` **(gasta consulta)**
Vínculos declarados na RAIS: nome, CPF, admissão, desligamento, tempo de casa.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `situacao` | string | `ativos` ou `desligados` |
| `page` / `limit` | integer | Paginação (limit máximo 500) |

A RAIS é um retrato do último ano entregue (`meta.referencia`): quem entrou
depois não aparece, e "ativo" significa "estava lá naquela data". De quem saiu,
a base informa dia e mês, sem o ano.

#### `GET /empresas/{cnpj}/contatos` **(gasta consulta)**
O endpoint de prospecção: sócios e decisores já com telefone priorizado.

| Parâmetro | Tipo | Padrão | Descrição |
|---|---|---|---|
| `incluir_decisores` | boolean | `true` | Anexa decisores não-sócios |
| `cargos` | string | — | Filtro de cargo dos decisores |
| `max_decisores` | integer | 3 | Teto por empresa |
| `max_telefones` | integer | 3 | Telefones por contato |
| `tipo_telefone` | string | `celular` | `celular`, `celular_fixo` ou `todos` |
| `fonte_telefone` | string | `assertiva` | `assertiva` ou `mk` |

Os telefones vêm **do mais atual para o mais antigo**, usando o último contato
registrado, linha quente e se o número é do próprio titular.

#### `GET /empresas/{cnpj}/conexoes` **(gasta consulta)**
Sócios, possíveis decisores e empresas ligadas — com telefone e flag de WhatsApp.

---

### 4.3 Pessoas

#### `GET /pessoas`
Busca por nome na base local. Não gasta consulta.

| Parâmetro | Tipo | Descrição |
|---|---|---|
| `nome` | string | **Obrigatório**, mínimo 3 caracteres |
| `ampla` | boolean | `true` procura nomes compostos parecidos |
| `page` / `limit` | integer | Paginação |

#### `GET /pessoas/{cpf}`
Dados cadastrais: nome, nascimento, sexo, nome da mãe quando disponível.

#### `GET /pessoas/{cpf}/telefones` **(gasta consulta)**

#### `GET /pessoas/{cpf}/vinculos` **(gasta consulta)**
Onde a pessoa trabalha ou trabalhou, pela RAIS — o inverso do CNPJ.

#### `GET /pessoas/{cpf}/parentes` **(gasta 2 consultas)**
Mãe, pai, filhos, irmãos, cônjuge e sócios, com telefone quando existe.
Funde duas fontes e marca a origem de cada linha em `fonte`.

---

### 4.4 Telefones

#### `GET /telefones/{numero}` **(gasta consulta)**
Telefone reverso: CPFs e CNPJs atrelados ao número. Aceita 10 ou 11 dígitos
com DDD, com ou sem máscara.

---

### 4.5 Consumo

#### `GET /consumo`
Consumo de hoje, limite e tokens do usuário. Para token de admin, inclui o
relatório do período (`?dias=30`) com o total oficial da Assertiva.

---

### 4.6 Cobertura total — JSON bruto e visões compostas

A plataforma consulta várias fontes e cada uma devolve muito mais campo do que
a tela mostra. Estes endpoints entregam **tudo**.

#### JSON bruto das fontes

| Rota | O que devolve | Custo |
|---|---|---|
| `GET /empresas/{cnpj}/assertiva` | Resposta completa da Assertiva para o CNPJ, sem recorte | gasta |
| `GET /pessoas/{cpf}/assertiva` | Resposta completa da Assertiva para o CPF | gasta |
| `GET /pessoas/{cpf}/mk` | Perfil Mk: renda, score, endereços, parentes, vizinhos, benefícios | gasta |
| `GET /pessoas/{cpf}/contatos` | Telefones e e-mails pela Serasa | gasta |
| `GET /empresas/{cnpj}/contatos-serasa` | Telefones e e-mails da empresa pela Serasa | gasta |
| `GET /empresas/{cnpj}/linkedin` | Funcionários com cargo pelo LinkedIn | gasta |
| `GET /assertiva/telefone/{numero}` | Dono do telefone, resposta completa | gasta |
| `GET /assertiva/email/{email}` | Quem está por trás do e-mail | gasta |
| `POST /pessoas/busca-avancada` | Busca por nome e/ou endereço na Assertiva | gasta |

Nessas rotas o `meta.bruto` vem `true`: o `data` é o JSON da fonte, sem
tradução nossa. Use quando precisar de um campo que a API tratada não expõe.

#### Visões compostas — tudo numa chamada

```
GET /empresas/{cnpj}/completo?incluir=cadastro,socios,decisores,funcionarios,conexoes,assertiva,linkedin
GET /pessoas/{cpf}/completo?incluir=cadastro,mk,assertiva,vinculos,parentes,serasa
```

Cada bloco é opcional e **cada bloco pago gasta consulta** — peça só o que vai
usar. Um bloco que falha **não derruba os outros**:

```json
{
  "data": { "cadastro": {...}, "socios": [...], "decisores": {...} },
  "meta": {
    "blocos": ["cadastro", "socios", "decisores"],
    "falhas": { "funcionarios": "A base RAIS respondeu 504." }
  }
}
```

Medido no CNPJ da Google Brasil com cinco blocos: cadastro, 3 sócios, **602
decisores**, **1.023 funcionários** e 14 conexões, tudo em uma resposta.

#### Validação

`GET /telefones/{numero}/pertence/{documento}` **(gasta)** — confirma se o
número é daquele CPF/CNPJ e avisa quando é linha compartilhada.

#### Lote

| Rota | Descrição |
|---|---|
| `POST /prospeccao/cobertura` | Mede em quantas empresas existe decisor, **sem puxar telefone** (2 consultas por CNPJ, máx. 60) |
| `POST /prospeccao/pessoas` | Busca sócios/pessoas por filtros na base local (não gasta) |
| `POST /enriquecimento` | O "Minha planilha" em API: manda CNPJs + campos, recebe uma linha por CNPJ (máx. 200) |
| `GET /enriquecimento/campos` | Catálogo de campos aceitos pelo enriquecimento |

```bash
curl -X POST "$BASE/enriquecimento" -H "Authorization: Bearer $TOKEN"   -H 'Content-Type: application/json'   -d '{"cnpjs":["06990590000123"],"campos":["rfb_razao","rfb_municipio","as_empresa_tel"]}'
```

Campo com nome errado não é descartado em silêncio: volta em
`meta.campos_ignorados`.

#### Apoio

| Rota | Descrição |
|---|---|
| `GET /fontes` | Quais fontes estão ativas, o que cada uma entrega e se cobra |
| `GET /lookups/{tipo}` | Listas de CNAE, natureza jurídica, município, país, qualificação, motivo |

#### Dossiê

`GET /dossie/{tipo}/{documento}` — **só token de admin**. Devolve
`application/pdf`, não JSON. `tipo` é `cpf` ou `cnpj`; aceita `insight=true`
(resumo por IA) e `familia=true` (consulta os parentes).

---

## 5. Administração de tokens

Estas rotas usam **sessão de administrador** (não token de API).

| Método | Rota | Descrição |
|---|---|---|
| GET | `/api/admin/tokens` | Lista tokens (só prefixo, nunca o segredo) |
| POST | `/api/admin/tokens` | Cria token. Body: `{user_id, nome, escopo}` |
| DELETE | `/api/admin/tokens/{id}` | Revoga um token |

O token criado herda o **limite diário do usuário** ao qual pertence. Para dar
mais folga a uma integração, ajuste o limite desse usuário.

---

## 6. Objetos e relacionamentos

| Objeto | Descrição | Relacionamentos |
|---|---|---|
| **Empresa** | CNPJ na base da Receita | tem Sócios, Decisores, Funcionários, Conexões |
| **Sócio** | Pessoa no quadro societário | pertence a Empresa; é uma Pessoa quando o CPF resolve |
| **Decisor** | Gestor ligado ao CNPJ, com cargo e nível | pertence a Empresa; é uma Pessoa |
| **Funcionário** | Vínculo declarado na RAIS | liga Pessoa e Empresa, com admissão e desligamento |
| **Pessoa** | CPF na base local | tem Telefones, Vínculos, Parentes |
| **Contato** | Sócio ou Decisor já com telefone | o que a prospecção consome |

---

## 7. Casos de uso comuns

### Enriquecer um CRM com quem decide

```bash
# 1. acha as empresas do perfil
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \
  "$BASE/empresas?uf=MG&porte=05&capital_min=1000000&limit=50"

# 2. para cada CNPJ, pega contatos com telefone
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \
  "$BASE/empresas/06990590000123/contatos?max_decisores=2&tipo_telefone=celular"
```

### Descobrir onde um lead trabalha, a partir do CPF

```bash
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \
  "$BASE/pessoas/03702149600/vinculos"
```

### Validar de quem é um número que ligou

```bash
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" \
  "$BASE/telefones/33997332652"
```

### Controlar custo antes de rodar em lote

```bash
curl -H "Authorization: Bearer $CAPIBLU_TOKEN" "$BASE/conta"
# → meta.limites.restantes_hoje diz quantas consultas ainda cabem
```

---

## 8. Boas práticas

1. **Um token por integração**, com nome que diga quem usa. Revogar fica cirúrgico.
2. **Escopo `leitura` por padrão.** Só suba para `consulta` o que precisa gastar.
3. **Trate o 429**: o limite é diário e por usuário. Repita no dia seguinte ou peça mais folga a um admin.
4. **Cacheie do seu lado.** CNPJ e RAIS mudam devagar; consultar o mesmo documento duas vezes no mesmo dia é dinheiro fora.
5. **Não trate ausência como erro.** Micro empresa sem decisor devolve 200 com `data: []` e um `meta.aviso` — é resposta legítima, não falha.
