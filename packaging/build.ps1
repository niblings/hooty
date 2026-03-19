# Build Hooty standalone binary for Windows (onedir mode).
#
# Usage:
#   powershell packaging/build.ps1
#
# Output:
#   dist\hooty\hooty.exe  (executable + bundled dependencies)

$ErrorActionPreference = "Stop"

$ScriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$ProjectRoot = Split-Path -Parent $ScriptDir
Set-Location $ProjectRoot

# Use a dedicated venv to avoid conflicts with WSL's .venv
$env:UV_PROJECT_ENVIRONMENT = ".buildenv"
$env:VIRTUAL_ENV = Join-Path $ProjectRoot ".buildenv"

Write-Host "==> Installing dependencies into .buildenv ..."
uv sync --all-extras
uv pip install pyinstaller

Write-Host "==> Building with PyInstaller (onedir)..."
uv run pyinstaller packaging/hooty.spec --noconfirm

Write-Host "==> Smoke test..."
$smokeResult = & .\dist\hooty\hooty.exe --version 2>&1
if ($LASTEXITCODE -eq 0) {
    Write-Host $smokeResult
    Write-Host "==> Build successful!"
} else {
    Write-Host "==> ERROR: Smoke test failed" -ForegroundColor Red
    Write-Host $smokeResult
    exit 1
}

Write-Host ""
Write-Host "Output: dist\hooty\"
$size = (Get-ChildItem -Recurse dist\hooty | Measure-Object -Property Length -Sum).Sum / 1MB
Write-Host ("Size: {0:N1} MB" -f $size)

Write-Host ""
Write-Host "To package for distribution:"
Write-Host "  Compress-Archive -Path dist\hooty -DestinationPath hooty-windows-x86_64.zip"
