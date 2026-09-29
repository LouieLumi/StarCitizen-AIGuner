# Flash build\ai_crew_fw.uf2 to the Pico.
#
# Uses the RP2350 BOOTSEL drive if it is mounted; otherwise, if the AI Crew
# firmware is running, sends BOOTSEL over its COM port to reboot it into the
# bootloader first (no button press needed).
#
#   powershell -ExecutionPolicy Bypass -File firmware\flash.ps1

param(
    [string]$Uf2 = (Join-Path $PSScriptRoot 'build\ai_crew_fw.uf2'),
    [int]$TimeoutSec = 15
)

$ErrorActionPreference = 'Stop'

function Get-BootDrive {
    Get-Volume | Where-Object { $_.DriveLetter -and $_.FileSystemLabel -eq 'RP2350' } | Select-Object -First 1
}

function Get-FirmwarePort {
    $dev = Get-CimInstance Win32_PnPEntity |
        Where-Object { $_.PNPDeviceID -match 'VID_CAFE&PID_4143' -and $_.Name -match '\((COM\d+)\)' } |
        Select-Object -First 1
    if ($dev) { $Matches[1] }
}

if (-not (Test-Path $Uf2)) { throw "UF2 not found: $Uf2 (run build.ps1 first)" }

$vol = Get-BootDrive
if (-not $vol) {
    $port = Get-FirmwarePort
    if (-not $port) { throw 'No RP2350 BOOTSEL drive and no AI Crew Controller COM port. Hold BOOTSEL while plugging in the Pico.' }
    "requesting BOOTSEL via $port"
    $sp = New-Object System.IO.Ports.SerialPort $port, 115200
    $sp.DtrEnable = $true
    $sp.Open()
    $sp.Write("BOOTSEL`n")
    Start-Sleep -Milliseconds 200
    $sp.Close()

    $deadline = (Get-Date).AddSeconds($TimeoutSec)
    while (-not ($vol = Get-BootDrive)) {
        if ((Get-Date) -gt $deadline) { throw 'BOOTSEL drive did not appear' }
        Start-Sleep -Milliseconds 250
    }
}

"copying $(Split-Path $Uf2 -Leaf) -> $($vol.DriveLetter):\"
Copy-Item $Uf2 "$($vol.DriveLetter):\"
'done - the Pico reboots into the new firmware'
