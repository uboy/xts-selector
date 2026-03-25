param(
    [string]$Python = "python",
    [string]$DistDir = "dist",
    [string]$BuildDir = "build/pyinstaller"
)

$ErrorActionPreference = "Stop"
$ProjectDir = Split-Path -Parent $PSScriptRoot
$ResolvedDistDir = if ([System.IO.Path]::IsPathRooted($DistDir)) { $DistDir } else { Join-Path $ProjectDir $DistDir }
$ResolvedBuildDir = if ([System.IO.Path]::IsPathRooted($BuildDir)) { $BuildDir } else { Join-Path $ProjectDir $BuildDir }
$ArtifactPath = Join-Path $ResolvedDistDir "arkui-xts-selector.exe"
$EntryScript = Join-Path $ProjectDir "scripts/pyinstaller_entry.py"
$SrcDir = Join-Path $ProjectDir "src"

Set-Location $ProjectDir
& $Python -c "import PyInstaller" *> $null
if ($LASTEXITCODE -ne 0) {
    & $Python -m pip install --upgrade pip pyinstaller
}
& $Python -m PyInstaller --clean --noconfirm --onefile --name arkui-xts-selector --paths $SrcDir --distpath $ResolvedDistDir --workpath $ResolvedBuildDir --specpath $ResolvedBuildDir $EntryScript

if (-not (Test-Path -LiteralPath $ArtifactPath)) {
    throw "expected artifact not found: $ArtifactPath"
}

& $ArtifactPath --help | Out-Null
Write-Host "built:" $ArtifactPath
