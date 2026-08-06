<#
  Setup do túnel NOMEADO do CapiBLU (rodar UMA vez, no seu terminal).
  Passos que ele automatiza: login (abre o navegador na sua conta Cloudflare) ->
  cria o túnel -> aponta o DNS do seu domínio -> gera o config.yml.

  Pré-requisito: ter um domínio adicionado na sua conta Cloudflare.

  Uso:
    ./setup-tunnel.ps1 -Hostname data.seudominio.com.br
    (opcional: -TunnelName capiblu-data  -Cloudflared C:\capiblu_data\cloudflared.exe)
#>
param(
  [Parameter(Mandatory = $true)][string]$Hostname,
  [string]$TunnelName = "capiblu-data",
  [string]$Cloudflared = "C:\capiblu_data\cloudflared.exe"
)
$ErrorActionPreference = "Stop"

if (-not (Test-Path $Cloudflared)) { throw "cloudflared não encontrado em $Cloudflared" }

Write-Host "==> 1/4 Login na Cloudflare (vai abrir o navegador; escolha seu domínio)..." -ForegroundColor Cyan
& $Cloudflared tunnel login

Write-Host "==> 2/4 Criando o túnel '$TunnelName'..." -ForegroundColor Cyan
& $Cloudflared tunnel create $TunnelName 2>&1 | Write-Host

# Descobre o arquivo de credenciais (JSON) recém-criado do túnel.
$cred = Get-ChildItem "$env:USERPROFILE\.cloudflared\*.json" -ErrorAction SilentlyContinue |
        Sort-Object LastWriteTime -Descending | Select-Object -First 1
if (-not $cred) { throw "Credencial do túnel não encontrada em ~/.cloudflared/*.json" }

Write-Host "==> 3/4 Apontando DNS $Hostname -> túnel..." -ForegroundColor Cyan
& $Cloudflared tunnel route dns $TunnelName $Hostname 2>&1 | Write-Host

Write-Host "==> 4/4 Gerando config.yml..." -ForegroundColor Cyan
$config = @"
# Config do túnel nomeado do CapiBLU (gerado por setup-tunnel.ps1)
tunnel: $TunnelName
credentials-file: $($cred.FullName)

ingress:
  - hostname: $Hostname
    service: http://127.0.0.1:8011
  - service: http_status:404
"@
$config | Set-Content -Encoding utf8 "$PSScriptRoot\config.yml"

Write-Host ""
Write-Host "OK! Túnel '$TunnelName' pronto em https://$Hostname" -ForegroundColor Green
Write-Host "No Render, use DATA_SERVICE_URL = https://$Hostname" -ForegroundColor Green
Write-Host "Agora suba tudo com: ./start-capiblu.ps1" -ForegroundColor Green
