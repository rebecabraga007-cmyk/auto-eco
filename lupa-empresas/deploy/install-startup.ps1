<#
  Faz o CapiBLU subir no logon SEM exigir admin: cria um .cmd na pasta
  Inicializar (Startup) do Windows que chama start-capiblu.ps1 oculto.
  Rodar UMA vez. Para remover: apague o arquivo indicado no final.
#>
$ErrorActionPreference = "Stop"
$start = Join-Path $PSScriptRoot "start-capiblu.ps1"
if (-not (Test-Path $start)) { throw "start-capiblu.ps1 nao encontrado." }

$startupDir = [Environment]::GetFolderPath('Startup')   # ...\Start Menu\Programs\Startup
$cmdPath = Join-Path $startupDir "CapiBLU.cmd"
$cmd = "@echo off`r`npowershell -NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File `"$start`"`r`n"
[System.IO.File]::WriteAllText($cmdPath, $cmd)

Write-Host "OK! Criado: $cmdPath" -ForegroundColor Green
Write-Host "O CapiBLU (dados + tunel) vai subir sozinho a cada logon." -ForegroundColor Green
Write-Host "Para remover no futuro: Remove-Item `"$cmdPath`"" -ForegroundColor Gray
