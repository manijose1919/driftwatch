# Remove the DriftWatch autostart scheduled task (and stop the running server).
$taskName = "DriftWatch"
try {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction Stop
} catch {}
Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
Write-Host "Scheduled task '$taskName' removed." -ForegroundColor Green
