# Deploy no Railway

## Variaveis obrigatorias

Configure em **Railway > Variables**:

```env
MAISOBRAS_EMAIL=seu_email_do_mais_obras
MAISOBRAS_PASSWORD=sua_senha_do_mais_obras
MAISOBRAS_BASE_URL=https://www.maisobras.online
MAX_OBRAS_PER_REQUEST=1500
PLAYWRIGHT_TIMEOUT=30000
API_TOKEN=
```

`API_TOKEN` pode ficar vazio para a interface web funcionar sem header. Se definir um token, chamadas diretas para `/enriquecer`, `/enriquecer_async` e `/reautenticar` exigem `X-API-Token`.

## Deploy

O projeto usa Dockerfile. No Railway:

1. Crie um novo projeto.
2. Conecte o repositorio ou suba pelo Railway CLI.
3. Garanta que as variaveis acima estejam configuradas.
4. O Railway vai usar `railway.toml` e o `Dockerfile`.

## URLs para validar

Depois do deploy:

```text
https://SEU-DOMINIO.up.railway.app/
https://SEU-DOMINIO.up.railway.app/health
https://SEU-DOMINIO.up.railway.app/docs
```

`/health` deve retornar:

```json
{
  "status": "ok",
  "scraper_autenticado": true,
  "max_obras_por_request": 1500,
  "versao": "1.2.0",
  "modo": "httpx (sem browser)"
}
```

## Observacoes

- A leitura de `.xls` legado usa `python-calamine`, sem LibreOffice.
- O processamento roda como job em memoria. Se o container reiniciar durante uma planilha, envie o arquivo novamente.
- Para planilhas grandes, acompanhe o andamento na tela principal.
