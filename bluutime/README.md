# Bluutime

Substituto do Meetime para a operação da BLU: a casca visual da Meetime, o domínio
de prospecção reconstruído, e o CapiBLU dentro dele como fonte de dados.

## Rodar

```bash
python bluutime/run.py
```

Sobe em <http://localhost:8020>. Um processo só, que junta três coisas:

- **login** — o `auth.py` do CapiBLU, mesmo JWT e mesmo banco de usuários;
- **`/capiblu/*`** — o serviço de dados do CapiBLU (`lupa-empresas/backend/main.py`)
  montado em processo, sem túnel: as bases locais de CNPJ e CPF respondem direto;
- **`/api/*`** — o domínio novo (clientes, cadências, leads, execução, ligações, métricas).

Se o CapiBLU não subir (base ausente, chave faltando), o resto continua de pé e o
motivo aparece em `GET /api/capiblu/status`.

## Migrar a conta do Meetime

```bash
curl -X POST localhost:8020/api/meetime/sync -H 'Content-Type: application/json' \
  -d '{"reset": true, "maxLeads": 1200, "maxProspections": 700, "maxCalls": 3000}'
```

Precisa de `MEETIME_TOKEN` no `.env` do `lupa-empresas/`. Três detalhes que a
documentação oficial não conta e que custaram tempo:

| Detalhe | O que acontece |
|---|---|
| Autenticação | O header é `Authorization: <token>` **cru**. Com `Bearer` a API devolve 401/429 |
| Paginação | Só `limit` (máx. **100**) + `start`, ordem crescente; `sort` e `date` são rejeitados. Paginar do zero traz os registros mais antigos — por isso o cliente salta para a cauda usando `totalItems` |
| Junção lead↔prospecção | `totalItems` de `/v2/prospections` não corresponde ao conjunto real (a cauda paginável para em ids ~27M enquanto os leads vivos apontam para ~37M). A única junção exata é `GET /v2/prospections?lead_id=` — uma consulta por lead |

O que o Meetime **não** expõe na v2: etapas de cadência e atividades. Cadência
importada vem sem etapas, então a fila de execução nasce vazia até as etapas
serem criadas aqui.

## Arquitetura

```
bluutime/
  server/
    app.py            monta auth + CapiBLU + routers + SPA
    models.py         domínio (Client é a entidade que falta no Meetime)
    migrate.py        ALTER TABLE do que faltar, sem recriar o banco
    seed.py           carga de demonstração, só se o banco estiver vazio
    capiblu_client.py ponte em processo com o serviço de dados
    meetime_api.py    cliente da API v2 do Meetime
    routers/          core · flow · dialer · analytics · whatsapp · capiblu · meetime
  web/                SPA no design system da Meetime (index.html + app.js + app.css)
```

## As três coisas que o Meetime não faz

1. **Cliente como entidade.** Lá o cliente é prefixo no nome da cadência
   (`ADV [BLU] [START]`). Aqui a migração extrai esses colchetes para `Client`, e
   cadência, lead, base e meta penduram nele.
2. **CapiBLU como fonte nativa de leads.** Em vez de exportar XLSX e reimportar CSV,
   a consulta vira base de leads e cadência numa tela só — e a base guarda a consulta
   que a gerou em `sourceQuery`.
3. **Fila priorizada.** `serial.queue_score` combina atraso, prioridade da cadência e
   proximidade da janela de melhor contato do lead, em vez da ordem cronológica pura.

## Estado

Ver [`COBERTURA-CAPIBLU.md`](COBERTURA-CAPIBLU.md) para a análise função a função do
quanto do CapiBLU já está utilizável aqui dentro, e o que falta.

| Documento | O que é |
|---|---|
| [`RELATORIO-MEETIME.md`](RELATORIO-MEETIME.md) | Engenharia reversa do Meetime: stack, mapa de funcionalidades, modelo de dados, números reais da operação |
| [`MEETIME-DESIGN-SYSTEM.md`](MEETIME-DESIGN-SYSTEM.md) | O design system extraído do ZIP — navbar, painéis, tabelas, cores, tipografia |
| [`COBERTURA-CAPIBLU.md`](COBERTURA-CAPIBLU.md) | Nota 0–10 por função do CapiBLU e plano para 100% |
| `bluutime-meetime-fusion.html` | Protótipo estático que originou a SPA (mantido como referência visual) |
