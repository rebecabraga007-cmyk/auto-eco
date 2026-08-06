<#
  Registra o CapiBLU para subir automaticamente no logon (Agendador de Tarefas).
  Rode UMA vez. Para remover: Unregister-ScheduledTask -TaskName CapiBLU -Confirm:$false
#>
$ErrorActionPreference = "Stop"
$script = Join-Path $PSScriptRoot "start-capiblu.ps1"
if (-not (Test-Path $script)) { throw "start-capiblu.ps1 não encontrado." }

$arg = '-NoProfile -ExecutionPolicy Bypass -WindowStyle Hidden -File "' + $script + '"'
$action  = New-ScheduledTaskAction -Execute "powershell.exe" -Argument $arg
$trigger = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
  -StartWhenAvailable -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 2)

Register-ScheduledTask -TaskName "CapiBLU" -Action $action -Trigger $trigger `
  -Settings $settings -Description "Sobe serviço de dados + Cloudflare Tunnel do CapiBLU" -Force | Out-Null

Write-Host "Tarefa 'CapiBLU' registrada — sobe sozinho no próximo logon." -ForegroundColor Green
Write-Host "Testar agora: Start-ScheduledTask -TaskName CapiBLU" -ForegroundColor Gray
