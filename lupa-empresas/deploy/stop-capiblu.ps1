<# Para os serviços do CapiBLU (uvicorn 8010/8011 + cloudflared). #>
$ErrorActionPreference = "SilentlyContinue"
foreach ($p in 8010, 8011) {
  $c = Get-NetTCPConnection -LocalPort $p -State Listen -ErrorAction SilentlyContinue
  if ($c) { Stop-Process -Id $c.OwningProcess -Force; Write-Host "porta $p parada" }
}
Get-Process cloudflared -ErrorAction SilentlyContinue | Stop-Process -Force
Write-Host "cloudflared parado." -ForegroundColor Green
