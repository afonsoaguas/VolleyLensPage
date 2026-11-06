param([switch]$Uninstall)
# Starts watch_scouts.py hidden at Windows logon (current user only, no administrator rights needed).
$ErrorActionPreference = 'Stop'
$taskName = 'VolleyLens scout watcher'
$root = $PSScriptRoot

if ($Uninstall) {
    Stop-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false
    Write-Host "Removed '$taskName'."
    return
}

$python = (& python -c "import sys; print(sys.executable)").Trim()
$pythonw = Join-Path (Split-Path $python) 'pythonw.exe'
if (-not (Test-Path $pythonw)) { throw "pythonw.exe not found next to $python" }

$action = New-ScheduledTaskAction -Execute $pythonw -Argument "`"$root\watch_scouts.py`"" -WorkingDirectory $root
$trigger = New-ScheduledTaskTrigger -AtLogOn -User "$env:USERDOMAIN\$env:USERNAME"
$settings = New-ScheduledTaskSettingsSet -ExecutionTimeLimit ([TimeSpan]::Zero) -RestartCount 3 -RestartInterval (New-TimeSpan -Minutes 1) `
    -StartWhenAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Trigger $trigger -Settings $settings `
    -Description 'Publishes new DV4 .dvw scouts to the VolleyLensPage GitHub Pages repository.' -Force | Out-Null
Start-ScheduledTask -TaskName $taskName
Write-Host "Installed and started '$taskName'. Log: $root\.automation\watcher.log"
