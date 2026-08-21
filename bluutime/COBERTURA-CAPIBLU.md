# Cobertura do CapiBLU dentro do Bluutime

Análise função a função: 171 funções do CapiBLU, nota 0–10 para cada uma conforme
o quanto está utilizável na interface do Bluutime.

**Régua.** 0 = não existe rota nem tela · 1–3 = rota existe mas sem tela, ou tela
sem os parâmetros · 4–6 = tela e rota, faltando filtros importantes ou resultado
em JSON cru · 7–9 = quase toda a superfície do original · 10 = paridade completa.

## Dois fatos que explicam quase tudo

1. **Todas as rotas do CapiBLU já respondem.** `app.py` monta o serviço de dados
   inteiro em `/capiblu`. O gargalo nunca foi backend: é interface e repasse de
   parâmetro.
2. **`capiblu_client.call()` terminava em `r.json()`.** Nenhum XLSX e nenhum
   upload multipart atravessava a ponte — isso sozinho zerava "Minha planilha",
   "Meus modelos" e todos os exports. Resolvido na Fase 2 com `call_raw` e
   `call_files`.

## Nota por aba

| Aba do CapiBLU | Funções | Nota inicial | Depois do Bloco 1 |
|---|---|---|---|
| Dossiê | 4 | 8,75 | 8,75 → **10** (Fase 2) |
| De quem é este telefone | 3 | 5,67 | 5,67 |
| Painel administrativo | 16 | 3,44 | 3,9 |
| **Prospecção B2B** | 57 | **2,79** | **~7** |
| Uma empresa | 10 | 2,50 | 2,50 |
| Uma pessoa | 14 | 2,00 | 2,00 |
| Pessoa pelo nome | 12 | 1,67 | 1,67 |
| Empresa Assertiva | 11 | 1,36 | 1,8 |
| Consulta Assertiva | 10 | 1,30 | 1,30 |
| Vínculo empregatício | 13 | 1,15 | 1,6 |
| Meus modelos | 8 | 1,13 | 1,13 → **~7** (Fase 2) |
| Início | 6 | 0,67 | 0,67 |
| Minha planilha | 7 | 0,43 | 0,43 → **~7** (Fase 2) |

**Nota geral inicial: 2,3/10** — o motor inteiro, ~14% da superfície.

## O que já foi corrigido (Bloco 1)

- **Filtros de prospecção**: de 7 para os 20 que `cnpj_lookup.search` aceita —
  `situacao` (antes a lista trazia empresa baixada e inapta), `capital_max`,
  `natureza`, `setor`, `cnpj` direto, `fundada_de/até`, `tipo_empresa`, MEI,
  escopo do texto, e-mail. `uf`/`município`/`cnae`/`natureza` viraram seleção
  múltipla com combos vindos de `/api/capiblu/lookups`.
- **Telefone e e-mail na lista**: `cnpj_lookup.search` não selecionava esses
  campos, então a coluna vinha sempre vazia mesmo com o filtro "só com telefone"
  ligado. Agora vêm (no ramo filtrado; o índice FTS não os guarda).
- **Paginação real** com `offset` e escolha de 20/50/100/200 por página.
- **Parâmetros de montagem** que eram engolidos: `socios_modo`, `max_socios`,
  `decisores_fonte`, `fallback_hierarquia`, `apenas_cargo`, `pular_sem_decisor`,
  `modelo_id`. Chips de cargo por nível (1/2/3) e por termo.
- **Fonte de telefone** voltou ao padrão do CapiBLU (Assertiva, não Mk).
- **Sinais de ranking preservados** no lead: `decision_level`, `contact_kind`,
  `phone_kind`, `whatsapp`, `do_not_call` — antes o nível de decisão e a
  categoria do telefone eram descartados na conversão.
- **`decisores_info`** devolvido: explica por que uma empresa veio sem decisor.
- **Perfil "Sócios e pessoas"** na prospecção, consumindo `/api/prospeccao/pessoas`.
- **Teste de cobertura de decisores** antes de gastar (`/prospeccao/cobertura`).
- **Blocos de empresa** repassam a query string e ganharam `vinculos-assertiva`
  e `vinculos-cargos`.
- **Validação de CNPJ** com dígito verificador antes de qualquer consulta paga —
  `00000000000000` caía na matriz do Banco do Brasil e gerava 42 consultas.

## O que falta

### Bloco 2 — rota nova (destrava categorias inteiras)

✅ **Feito** (ver `ROTEIRO-BACKEND.md`, Fase 2): `call_raw`, `call_files`, as
rotas de exportação em `StreamingResponse`, o ciclo inteiro de "Minha planilha"
e o dossiê PDF por proxy. **Minha planilha** sai de 0,43 e **Meus modelos** de
1,13 para utilizáveis.

Continua faltando:

| O quê | Onde | Destrava |
|---|---|---|
| Dedup contra o CRM Meetime (distinto do dedup local) | `routers/capiblu.py` | `/api/meetime/dedup` |
| "Continuar buscando" no servidor (repaginar até fechar N com decisor) | `routers/capiblu.py` | hoje é laço de browser no CapiBLU |
| Validação de telefone em lote, por pessoa, parando no 1º confirmado | `routers/capiblu.py` | hoje valida só o primeiro número de um lead |
| Ranking de candidatos por pistas (UF/cidade/descrição), normal e agressivo | `routers/capiblu.py` | o ranking de pessoas do CapiBLU |

### Bloco 3 — tela nova sobre rota que já existe

Decisores por CNPJ (com filtro de nível 1/2/3) · Vínculos RAIS (abas Todos /
Ainda lá / Já saíram) · Ficha da pessoa renderizada no lugar do JSON · Ficha da
empresa · Minha planilha de verdade · Meus modelos · Consulta Assertiva (5
modalidades + finalidade LGPD) · Admin (tabela de preços, navlog, tokens de API) ·
Painel de uso pessoal.

## Ranking de pessoas — o que sobrevive

A classificação roda no servidor, então **sobrevive inteira**: decisores em níveis
1/2/3 (`decisores.classificar`, com as 10 exclusões antes dos níveis para
"Gerente de Contas" não virar nível 3 por engano), sócios ordenados por
qualificação societária (`_rank_socio`), e telefones ordenados por
`(formato, recência, linha quente, titularidade, WhatsApp)` em `refine_phones`.

O que se perdia era na saída — e foi isso que o Bloco 1 corrigiu: o nível de
decisão e a categoria do telefone agora chegam ao lead em vez de serem jogados
fora na concatenação `" / "`.

Um detalhe que continua valendo para os dois produtos: `nao_perturbe` é
normalizado pela Assertiva e **não entra na chave de ordenação** — sinal de
compliance coletado e ignorado.
