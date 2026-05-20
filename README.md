# Mais Obras Enricher — v1.2

API REST que enriquece automaticamente o `Meus_favoritos.xls` exportado do Mais Obras
com telefones e e-mails, usando chamada direta à API interna da plataforma.

---

## Como funciona

```
Renata exporta Meus_favoritos.xls
         ↓
POST /enriquecer  ←  arquivo .xls
         ↓
Converte .xls → .xlsx (LibreOffice)
         ↓
Para cada obra:
  POST /pesquisa_perfil  { contato: nome_profissional, tipo: "Profissional", uf: UF }
  POST /pesquisa_perfil  { contato: nome_proprietario, tipo: "Proprietário", uf: UF }
         ↓
Escreve 7 novas colunas no Excel
         ↓
Retorna Meus_favoritos_enriquecido.xlsx
         ↓
Renata importa no Meetime
```

**Sem browser, sem Playwright.** Usa `httpx` direto na API interna — rápido e leve.

---

## Deploy no Railway

### 1. Faça upload do projeto

Crie um repositório Git com os arquivos e conecte ao Railway,
ou use `railway up` pelo CLI.

### 2. Configure as variáveis de ambiente

No painel Railway → **Settings → Variables**:

| Variável | Valor |
|---|---|
| `MAISOBRAS_EMAIL` | e-mail de login da conta diretoria |
| `MAISOBRAS_PASSWORD` | senha da conta |
| `API_TOKEN` | token secreto gerado por você (ex: UUID aleatório) |
| `MAX_OBRAS_PER_REQUEST` | `100` (padrão) |
| `PLAYWRIGHT_TIMEOUT` | `30000` (padrão — em ms, vale para httpx também) |

### 3. Verifique o deploy

```bash
curl https://SEU_DOMINIO.railway.app/health
```

Esperado:
```json
{
  "status": "ok",
  "scraper_autenticado": true,
  "max_obras_por_request": 100,
  "versao": "1.2.0",
  "modo": "httpx (sem browser)"
}
```

---

## Uso

### Enriquecer o Excel

```bash
curl -X POST https://SEU_DOMINIO.railway.app/enriquecer \
  -H "X-API-Token: seu_token_secreto" \
  -F "arquivo=@Meus_favoritos.xls" \
  --output Meus_favoritos_enriquecido.xlsx
```

**Python:**
```python
import requests

with open("Meus_favoritos.xls", "rb") as f:
    r = requests.post(
        "https://SEU_DOMINIO.railway.app/enriquecer",
        headers={"X-API-Token": "seu_token"},
        files={"arquivo": f},
    )

with open("Meus_favoritos_enriquecido.xlsx", "wb") as f:
    f.write(r.content)
```

### Reautenticar (sessão expirou)

```bash
curl -X POST https://SEU_DOMINIO.railway.app/reautenticar \
  -H "X-API-Token: seu_token_secreto"
```

---

## Colunas adicionadas ao Excel

| Coluna | Conteúdo |
|---|---|
| `Tel_Arq_1` | Primeiro telefone do arquiteto |
| `Tel_Arq_2` | Segundo telefone do arquiteto |
| `Email_Arq` | E-mail do arquiteto |
| `Tel_Prop_1` | Primeiro telefone do proprietário |
| `Tel_Prop_2` | Segundo telefone do proprietário |
| `Email_Prop` | E-mail do proprietário |
| `Status_Enriquecimento` | `OK`, `Sem telefone cadastrado`, ou mensagem de erro |

---

## Detalhes técnicos — o que foi descoberto no código-fonte

O ZIP do site revelou que o Mais Obras tem um endpoint interno:

```
POST /pesquisa_perfil
{ contato: "NOME DO PROFISSIONAL", tipo: "Profissional", cpf_cnpj: "", uf: "SP" }
```

Resposta:
```json
{
  "perfil": [
    {
      "telefones": "16 99999-9999, 16 88888-8888",
      "cidade": "SÃO CARLOS",
      "uf": "SP",
      "cbo": "ARQUITETO",
      "cpfcnpj": ""
    }
  ],
  "emails": [{ "email": "arquiteto@email.com" }],
  "api_json": null
}
```

Os telefones chegam como string separada por vírgula — o scraper divide e distribui
nas colunas `Tel_Arq_1`, `Tel_Arq_2`, etc.

---

## Estrutura do projeto

```
maisobras-enricher/
├── main.py              # API FastAPI (endpoints)
├── scraper.py           # httpx: login + /pesquisa_perfil
├── excel_handler.py     # leitura e enriquecimento do Excel
├── requirements.txt     # fastapi, uvicorn, httpx, openpyxl
├── Dockerfile           # python:3.12-slim + libreoffice-calc
├── railway.toml
├── .env.example
└── README.md
```

---

## Desenvolvimento local

```bash
pip install -r requirements.txt
cp .env.example .env
# edite .env com email e senha

uvicorn main:app --reload
# acesse http://localhost:8000/docs
```
