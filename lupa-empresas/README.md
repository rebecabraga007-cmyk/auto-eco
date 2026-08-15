# Lupa de Empresas

Uma "lupa" de busca de empresas brasileiras. Busque por **CNPJ** ou **nome**,
veja uma lista de resultados e, **ao clicar numa empresa**, abra o detalhe com os
dados completos (BrasilAPI) e uma lista de funcionarios obtida via scraping do
LinkedIn.

> O scraping do LinkedIn acontece **apenas ao abrir o detalhe de uma empresa** —
> nunca na busca/listagem.

## Stack

- **Backend:** FastAPI (Python), porta **8010**. Serve tambem o frontend estatico.
- **Frontend:** HTML + JS vanilla + CSS (sem framework).
- **Sem banco de dados** — cache em memoria apenas.

## Como rodar

### Windows
```
start.bat
```

### Linux / macOS
```
./start.sh
```

### Manual
```
cd backend
python -m pip install -r requirements.txt
python -m uvicorn main:app --host 0.0.0.0 --port 8010
```

Depois abra: **http://localhost:8010**

## Endpoints da API

| Metodo | Rota | Descricao |
|--------|------|-----------|
| GET | `/api/search?q={termo}` | Busca por CNPJ exato (BrasilAPI) ou por nome (Casa dos Dados). **Nao faz scraping.** |
| GET | `/api/company/{cnpj}` | Dados completos da empresa via BrasilAPI. **Nao faz scraping.** |
| GET | `/api/company/{cnpj}/employees` | **Dispara o scraping do LinkedIn** e retorna funcionarios (nome + cargo + url). Cacheado por CNPJ. |
| GET | `/api/company/{cnpj}/vinculos` | Vinculos empregaticios declarados na RAIS (nome + CPF + admissao + desligamento), via FDX APIs. Precisa de `FDX_TOKEN`. Cache de 6h; `?refresh=true` ignora o cache. |
| POST | `/api/vinculos/export` | XLSX da lista de vinculos que esta na tela. Body: `{cnpj, razao_social, referencia_br, vinculos:[...]}`. |

## Limitacao da BrasilAPI (importante)

A [BrasilAPI](https://brasilapi.com.br/api/cnpj/v1/{cnpj}) **so aceita CNPJ exato**
(14 digitos) — **nao existe busca por nome**. Por isso:

- **CNPJ** (14 digitos, com ou sem mascara) → consulta direta na BrasilAPI.
- **Nome** → usa a API publica da **Casa dos Dados**
  (`https://api.casadosdados.com.br/v2/public/cnpj/search`) como fallback gratuito.
  Se ela estiver indisponivel, o app mostra uma mensagem amigavel sugerindo o uso
  do CNPJ.

## Scraping do LinkedIn

O scraper tem **dois caminhos**, escolhidos automaticamente:

### 1. Bright Data (recomendado) — `BRIGHTDATA_API_KEY`

Quando a variavel de ambiente `BRIGHTDATA_API_KEY` esta definida, o app usa a
**Bright Data LinkedIn Scraper API**, que lida com proxies, CAPTCHAs e parsing e
devolve JSON estruturado. Usa o dataset **"LinkedIn people search - collect by
URL"** (`gd_m8d03he47z8nwb5xc`), montando uma URL de busca de pessoas do LinkedIn
a partir do nome da empresa.

**Windows (PowerShell):**
```
$env:BRIGHTDATA_API_KEY = "sua_api_key_do_brightdata"
start.bat
```

**Linux / macOS:**
```
export BRIGHTDATA_API_KEY="sua_api_key_do_brightdata"
./start.sh
```

Como obter a chave: crie a conta em https://brightdata.com/cp/start (US$2 de
credito gratis), va em **Scrapers → biblioteca** e copie a API key. Os dataset IDs
ja estao configurados em `backend/linkedin_scraper.py`:

| Dataset | ID | Uso |
|---------|----|----|
| LinkedIn people search (by URL) | `gd_m8d03he47z8nwb5xc` | funcionarios da empresa (padrao) |
| LinkedIn people profiles (by URL) | `gd_l1viktl72bvl7bjuj0` | perfil individual detalhado |
| LinkedIn company information (by URL) | `gd_l1vikfnt1wgvvqz95w` | dados da empresa |

Endpoint sincrono usado: `POST https://api.brightdata.com/datasets/v3/scrape?dataset_id=...&format=json`
com header `Authorization: Bearer <API_KEY>` e corpo `[{"url": "..."}]`.

### 1b. Roster COMPLETO via Dataset (Marketplace) — opcional, pago

O MVP roda no **plano free** usando os funcionarios em destaque (acima). Quando
quiser a **lista completa de funcionarios** de uma empresa, compre o dataset
**"LinkedIn people profiles"** (671M perfis, min. $250/pedido) e ligue a flag:

```
BRIGHTDATA_USE_DATASET=1
BRIGHTDATA_PEOPLE_DATASET_ID=<id do dataset no painel>
BRIGHTDATA_DATASET_LIMIT=200
```

Com a flag ligada, ao abrir uma empresa o backend:
1. Resolve o `company_id` da empresa (via Scraper API de company).
2. Dispara um **filtro no dataset** por `current_company_company_id` (`POST /datasets/v3/filter`).
3. Faz **polling do snapshot** (`GET /datasets/v3/snapshot/{id}`) ate ficar pronto.
4. Retorna todos os perfis (nome + cargo + url), fonte `brightdata-dataset`.

Se a flag estiver **desligada** (padrao), nada disso roda — fica no free.

> ⚠️ O dataset tem **pedido minimo de $250**. Vale pra volume; para uso
> pontual (uma empresa por vez) o caminho free/Scraper API e mais barato.

### 2. Fallback: Google (sem chave)

Sem `BRIGHTDATA_API_KEY`, o scraper cai numa **busca publica pelo Google**
(`site:linkedin.com/in "NOME_EMPRESA"`). O Google/LinkedIn bloqueiam scraping
anonimo com frequencia; quando isso acontece a API responde de forma graciosa:

```json
{ "status": "blocked", "employees": [], "message": "..." }
```

Opcionalmente, defina `LINKEDIN_LI_AT` (cookie de sessao do LinkedIn) para o
fallback — enviado no header `Cookie`. Menos confiavel que o Bright Data.
