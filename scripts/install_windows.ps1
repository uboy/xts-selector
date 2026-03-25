param(
    [Parameter(Mandatory = $true)]
    [string]$BinaryPath,
    [Parameter(Mandatory = $true)]
    [string]$TargetDir
)

$ErrorActionPreference = "Stop"
$TargetPath = Join-Path $TargetDir "arkui-xts-selector.exe"

if (-not (Test-Path -LiteralPath $BinaryPath)) {
    throw "binary not found: $BinaryPath"
}

New-Item -ItemType Directory -Force -Path $TargetDir | Out-Null
Copy-Item -Force $BinaryPath $TargetPath
Write-Host "installed:" $TargetPath
