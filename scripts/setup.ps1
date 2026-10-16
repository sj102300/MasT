# MasT setup for Windows (PowerShell).
#   powershell -ExecutionPolicy Bypass -File scripts\setup.ps1
$ErrorActionPreference = "Stop"
Set-Location (Split-Path -Parent $PSScriptRoot)

if (-not (Test-Path ".venv")) {
    Write-Host "Creating virtualenv (.venv)..."
    if (Get-Command py -ErrorAction SilentlyContinue) { & py -3 -m venv .venv }
    else { & python -m venv .venv }
    if ($LASTEXITCODE -ne 0) { throw "venv creation failed (Python 3.11+ required)" }
}
$venvPy = ".\.venv\Scripts\python.exe"
& $venvPy -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
if ($LASTEXITCODE -ne 0) { throw "Python 3.11+ required. Delete .venv and install a newer Python." }
& $venvPy -m pip install --upgrade pip
& $venvPy -m pip install -e ".[dev,web]"

if (-not (Test-Path "config.yaml")) {
    Copy-Item config.example.yaml config.yaml
    Write-Host "Created config.yaml from config.example.yaml"
}
Write-Host ""
Write-Host "Done. Activate with:  .\.venv\Scripts\Activate.ps1"
Write-Host "Then set your API key, e.g.:  `$env:ANTHROPIC_API_KEY = 'sk-...'"
Write-Host "Check LLM connectivity:  mast check-llm"
Write-Host "Check the C++ toolchain:  mast selftest --project examples\calculator\calculator.vcxproj"
Write-Host "Web UI:  mast ui"
