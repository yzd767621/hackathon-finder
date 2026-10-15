# Registers a daily Windows scheduled task that runs the hackathon notifier (free, built into Windows).
# Run once:  powershell -ExecutionPolicy Bypass -File setup_schedule.ps1
# Remove:    Unregister-ScheduledTask -TaskName "Hackathon Notifier" -Confirm:$false
$dir = Split-Path -Parent $MyInvocation.MyCommand.Path
$py  = Join-Path (Split-Path (& python -c "import sys;print(sys.executable)")) "pythonw.exe"

$action   = New-ScheduledTaskAction -Execute $py -Argument "`"$dir\hackathon_notifier.py`"" -WorkingDirectory $dir
$triggers = @(
    (New-ScheduledTaskTrigger -Daily -At 9:00am),
    (New-ScheduledTaskTrigger -AtLogOn -User $env:USERNAME)
)
$settings = New-ScheduledTaskSettingsSet -StartWhenAvailable -RunOnlyIfNetworkAvailable -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries -ExecutionTimeLimit (New-TimeSpan -Minutes 15)

Register-ScheduledTask -TaskName "Hackathon Notifier" -Action $action -Trigger $triggers -Settings $settings `
    -Description "Daily check for free, student-friendly hackathons (online or KL)" -Force | Out-Null
Write-Host "Scheduled: daily 9:00 AM + at logon, using $py"
