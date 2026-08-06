# CapiBLU — Deploy (dados locais + túnel + Render)

Arquitetura: **App online (Render)** = frontend + login + proxy · **Serviço de dados (sua máquina)** = bases + chaves, exposto por **Cloudflare Tunnel**.

## Primeira vez (setup do túnel nomeado)

Pré-requisito: um domínio na sua conta Cloudflare.

```powershell
cd lupa-empresas\deploy
Copy-Item secrets.example.ps1 secrets.ps1   # e preencha (ou já veio preenchido)
./setup-tunnel.ps1 -Hostname data.seudominio.com.br
```
Isso faz login, cria o túnel `capiblu-data`, aponta o DNS e gera o `config.yml`.

## Dia a dia (subir tudo)

```powershell
./start-capiblu.ps1            # serviço de dados + túnel nomeado
./start-capiblu.ps1 -WithApp   # + app-online local (teste sem Render) em :8010
./start-capiblu.ps1 -Quick     # túnel TEMPORÁRIO trycloudflare (sem domínio)
./stop-capiblu.ps1             # para tudo
```

## Rodar sozinho ao ligar o PC

```powershell
./install-startup.ps1          # registra tarefa "CapiBLU" no logon
```

## Render (App online)

1. New → Blueprint → aponte para o repo (usa `../render.yaml`).
2. Envs no painel:
   - `DATA_SERVICE_URL` = `https://data.seudominio.com.br` (a URL do túnel)
   - `PROXY_SECRET` = **o mesmo** do `secrets.ps1`
   - `JWT_SECRET` = valor fixo e forte
   - `ADMIN_EMAIL` / `ADMIN_PASSWORD`

## Importante

- O "online" depende do **PC ligado** com `start-capiblu.ps1` rodando.
- O `.env` (chaves Assertiva/WorkAPI) e o `secrets.ps1` **ficam só locais** — nunca vão pro Git/Render.
- O quick tunnel (`-Quick`) muda de URL a cada reinício; o **nomeado** é fixo.
