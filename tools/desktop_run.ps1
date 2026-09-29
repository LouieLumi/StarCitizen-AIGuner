# Run a command inside the logged-on user's desktop session from a
# non-interactive one (SSH). Screen capture and windows (the control panel) only work there.
#
# Uses the scheduled task "AI Gunner Desktop Run" (runs as the console user,
# only while they are logged on). Output goes to logs\desktop_run.log.
#
#   desktop_run.ps1 -Command ".venv\Scripts\python.exe tools\pico_test.py --yes"
#   desktop_run.ps1 -Command "..." -Visible      # show a console window
#   desktop_run.ps1 -Command "..." -NoWait       # start and return
#   desktop_run.ps1 -Stop                        # stop a running command
#   desktop_run.ps1 -Remove                      # delete the scheduled task

param(
    [string]$Command,
    [int]$TimeoutSec = 120,
    [switch]$Visible,
    [switch]$NoWait,
    [switch]$Stop,
    [switch]$Remove
)

$ErrorActionPreference = 'Stop'
[Console]::OutputEncoding = [Text.Encoding]::UTF8
$taskName = 'AI Gunner Desktop Run'
$root = Split-Path $PSScriptRoot -Parent
$log = Join-Path $root 'logs\desktop_run.log'
$wrapper = Join-Path $root 'logs\desktop_run.cmd'

function Stop-DesktopRun {
    if (Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue) {
        Stop-ScheduledTask -TaskName $taskName
    }
    # Ending the task does not always end its children; stop project Pythons too.
    Get-CimInstance Win32_Process -Filter "Name='python.exe'" |
        Where-Object { $_.ExecutablePath -like "$root\.venv\*" } |
        ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }
}

if ($Remove) {
    Stop-DesktopRun
    Unregister-ScheduledTask -TaskName $taskName -Confirm:$false -ErrorAction SilentlyContinue
    'removed'
    return
}
if ($Stop) {
    Stop-DesktopRun
    'stopped'
    return
}
if (-not $Command) { throw '-Command is required' }

$user = (Get-CimInstance Win32_ComputerSystem).UserName
if (-not $user) { throw 'nobody is logged on at the console' }

Set-Content -Path $wrapper -Encoding ascii -Value @"
@echo off
cd /d "$root"
chcp 65001 >nul
set PYTHONIOENCODING=utf-8
set PYTHONUNBUFFERED=1
$Command > "$log" 2>&1
echo EXIT=%ERRORLEVEL%>> "$log"
"@
Remove-Item $log -ErrorAction SilentlyContinue

if ($Visible) {
    $action = New-ScheduledTaskAction -Execute 'cmd.exe' -Argument "/c `"$wrapper`""
} else {
    # Headless console: no window, so nothing steals focus from the game.
    $action = New-ScheduledTaskAction -Execute 'conhost.exe' -Argument "--headless cmd.exe /c `"$wrapper`""
}
$principal = New-ScheduledTaskPrincipal -UserId $user -LogonType Interactive -RunLevel Limited
$settings = New-ScheduledTaskSettingsSet -AllowStartIfOnBatteries -DontStopIfGoingOnBatteries `
    -ExecutionTimeLimit (New-TimeSpan -Hours 12) -MultipleInstances IgnoreNew
Register-ScheduledTask -TaskName $taskName -Action $action -Principal $principal -Settings $settings -Force | Out-Null

Start-ScheduledTask -TaskName $taskName
"started as $user"
if ($NoWait) { return }

$deadline = (Get-Date).AddSeconds($TimeoutSec)
Start-Sleep -Milliseconds 500
while ((Get-ScheduledTask -TaskName $taskName).State -eq 'Running') {
    if ((Get-Date) -gt $deadline) {
        Stop-DesktopRun
        "timed out after $TimeoutSec s"
        break
    }
    Start-Sleep -Milliseconds 250
}
if (Test-Path $log) { Get-Content $log -Encoding UTF8 }
