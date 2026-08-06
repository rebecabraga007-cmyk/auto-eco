<#
  Sobe o CapiBLU local (rodar ao ligar o PC):
    1) Serviço de DADOS  (uvicorn :8011, com PROXY_SECRET)
    2) Cloudflare Tunnel (expõe o serviço de dados online via config.yml)
    3) (opcional -WithApp) App-online local :8010 para testar sem o Render

  Uso:
    ./start-capiblu.ps1            # dados + túnel (produção: front vem do Render)
    ./start-capiblu.ps1 -WithApp   # + app-online local em http://127.0.0.1:8010
    ./start-capiblu.ps1 -Quick     # túnel temporário trycloudflare (sem config.yml)
#>
param(
  [switch]$WithApp,
  [switch]$Quick,
  [string]$Cloudflared = "C:\capiblu_data\cloudflared.exe"
)
$ErrorActionPreference = "Stop"
$root    = Split-Path $PSScriptRoot -Parent          # ...\lupa-empresas
$backend = Join-Path $root "backend"
$appdir  = Join-Path $root "app_online"

# 1) carrega segredos
$secrets = Join-Path $PSScriptRoot "secrets.ps1"
if (-not (Test-Path $secrets)) { throw "Crie o deploy/secrets.ps1 (copie de secrets.example.ps1)." }
. $secrets
if (-not $env:PROXY_SECRET) { throw "PROXY_SECRET vazio no secrets.ps1" }

Write-Host "==> Serviço de dados em http://127.0.0.1:8011 ..." -ForegroundColor Cyan
Start-Process python -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","8011" `
  -WorkingDirectory $backend -WindowStyle Minimized
Start-Sleep -Seconds 3

if ($Quick) {
  Write-Host "==> Túnel TEMPORÁRIO (trycloudflare)..." -ForegroundColor Yellow
  Start-Process $Cloudflared -ArgumentList "tunnel","--url","http://127.0.0.1:8011","--no-autoupdate" `
    -WindowStyle Minimized
  Write-Host "   (veja a URL *.trycloudflare.com na janela do cloudflared)" -ForegroundColor Yellow
} else {
  $config = Join-Path $PSScriptRoot "config.yml"
  if (-not (Test-Path $config)) { throw "config.yml nao existe. Rode ./setup-tunnel.ps1 antes (ou use -Quick)." }
  Write-Host "==> Tunel NOMEADO (config.yml)..." -ForegroundColor Cyan
  Start-Process $Cloudflared -ArgumentList "tunnel","--config",$config,"run" -WindowStyle Minimized
}

if ($WithApp) {
  Write-Host "==> App-online local em http://127.0.0.1:8010 ..." -ForegroundColor Cyan
  $env:DATA_SERVICE_URL = "http://127.0.0.1:8011"
  Start-Process python -ArgumentList "-m","uvicorn","main:app","--host","127.0.0.1","--port","8010" `
    -WorkingDirectory $appdir -WindowStyle Minimized
}

$appMsg = if ($WithApp) { "  App:8010" } else { "" }
Write-Host ""
Write-Host "CapiBLU no ar. Dados:8011  Tunel:ativo$appMsg" -ForegroundColor Green
Write-Host "Para PARAR: rode ./stop-capiblu.ps1" -ForegroundColor Gray
