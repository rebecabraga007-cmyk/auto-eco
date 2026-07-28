<#
  Segredos do CapiBLU (NÃO comitar). Copie para secrets.ps1 e ajuste.
  O start-capiblu.ps1 carrega este arquivo antes de subir os serviços.
#>
$env:PROXY_SECRET = "COLE_AQUI_O_PROXY_SECRET"     # o MESMO valor no Render
$env:JWT_SECRET   = "COLE_AQUI_O_JWT_SECRET"       # só usado se rodar o app-online local
