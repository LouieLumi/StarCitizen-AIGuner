# Build the AI Crew Controller firmware -> build\ai_crew_fw.uf2.
# Requires CMake, Ninja and arm-none-eabi-gcc on PATH, plus the Pico SDK.
param(
    [string]$Board = 'pico2_w',
    [string]$SdkPath = $env:PICO_SDK_PATH,
    [string]$ToolchainBin,
    [string]$PicotoolDir,
    [switch]$Clean
)

$ErrorActionPreference = 'Stop'
$src = $PSScriptRoot
$build = Join-Path $src 'build'

if (-not $SdkPath -or -not (Test-Path (Join-Path $SdkPath 'pico_sdk_init.cmake'))) {
    throw 'Set PICO_SDK_PATH or pass -SdkPath pointing to a Pico SDK checkout. See docs/firmware.md.'
}
$env:PICO_SDK_PATH = (Resolve-Path $SdkPath).Path
if ($ToolchainBin) {
    $env:PATH = "$ToolchainBin;$env:PATH"
}
foreach ($tool in @('cmake', 'ninja', 'arm-none-eabi-gcc')) {
    if (-not (Get-Command $tool -ErrorAction SilentlyContinue)) {
        throw "$tool is not on PATH. See docs/firmware.md."
    }
}
if ($PicotoolDir -and -not (Test-Path $PicotoolDir -PathType Container)) {
    throw "Picotool directory not found: $PicotoolDir"
}
if ($Clean -and (Test-Path $build)) {
    Remove-Item -Recurse -Force $build
}

$configureArgs = @('-S', $src, '-B', $build, '-G', 'Ninja',
    '-DCMAKE_BUILD_TYPE=Release', "-DPICO_BOARD=$Board", "-DPICO_SDK_PATH=$env:PICO_SDK_PATH")
if ($PicotoolDir) { $configureArgs += "-Dpicotool_DIR=$PicotoolDir" }
cmake @configureArgs
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
cmake --build $build
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$uf2 = Get-Item (Join-Path $build 'ai_crew_fw.uf2')
"built {0} ({1:N0} bytes)" -f $uf2.FullName, $uf2.Length
