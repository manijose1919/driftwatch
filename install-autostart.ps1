# Register DriftWatch as a Windows Scheduled Task that starts at logon.
# Usage:  .\install-autostart.ps1 [-Port 8420]
# Remove with:  .\uninstall-autostart.ps1
param([int]$Port = 8420)

$taskName = "DriftWatch"
$startScript = Join-Path $PSScriptRoot "start.ps1"

$action = New-ScheduledTaskAction -Execute "powershell.exe" `
    -Argument "-NoProfile -WindowStyle Hidden -ExecutionPolicy Bypass -File `"$startScript`" -Port $Port"
$trigger = New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit (New-TimeSpan -Seconds 0)

Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description "DriftWatch API contract drift sentinel (http://127.0.0.1:$Port/)" -Force | Out-Null

Write-Host "Scheduled task '$taskName' registered: DriftWatch starts at logon on port $Port." -ForegroundColor Green
Write-Host "Start it now with:  Start-ScheduledTask -TaskName $taskName"
