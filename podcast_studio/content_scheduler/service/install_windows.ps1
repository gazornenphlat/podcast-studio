# Installs Content Scheduler as a Windows scheduled task that starts at logon with a tray icon (no console window).
# Run in PowerShell:  powershell -ExecutionPolicy Bypass -File service\install_windows.ps1
$dir = Split-Path -Parent $PSScriptRoot
$py  = (Get-Command pythonw.exe -ErrorAction SilentlyContinue).Source
if (-not $py) { $py = (Get-Command python.exe).Source }
$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\Content Scheduler.pyw`"" -WorkingDirectory $dir
$trigger  = New-ScheduledTaskTrigger -AtLogOn
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
            -RestartCount 999 -RestartInterval (New-TimeSpan -Minutes 1) -ExecutionTimeLimit 0
Register-ScheduledTask -TaskName "ContentScheduler" -Action $action -Trigger $trigger -Settings $settings -Force | Out-Null
Start-ScheduledTask -TaskName "ContentScheduler"
Write-Host "Installed. Uninstall: Unregister-ScheduledTask -TaskName ContentScheduler -Confirm:`$false"
