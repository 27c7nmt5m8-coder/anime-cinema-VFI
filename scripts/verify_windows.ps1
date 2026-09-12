param(
    [Parameter(Mandatory = $true)][string]$ModelDir,
    [Parameter(Mandatory = $true)][string]$RepositoryDir,
    [switch]$RequireCuda
)
$ErrorActionPreference = "Stop"
Set-Location (Split-Path $PSScriptRoot -Parent)
$VfiPython = Join-Path (Get-Location) ".venv\Scripts\python.exe"
if (-not (Test-Path $VfiPython)) { throw "Run Setup.ps1 with Python 3.11 first." }
$VfiVersion = & $VfiPython -c "import sys; print('.'.join(map(str, sys.version_info[:2])))"
if ($VfiVersion -ne "3.11") { throw "The Windows reference environment requires Python 3.11." }
$env:RIFE_MODEL_DIR = (Resolve-Path $ModelDir).Path
$env:RIFE_REPO_DIR = (Resolve-Path $RepositoryDir).Path
$env:QT_QPA_PLATFORM = "offscreen"
$env:ACVFI_REQUIRE_CUDA = if ($RequireCuda) { "1" } else { "0" }
$VfiArtifacts = Join-Path "test-artifacts" (Get-Date -Format "yyyyMMdd-HHmmss")
New-Item -ItemType Directory -Path $VfiArtifacts -ErrorAction Stop | Out-Null
function Invoke-VfiCheck([string[]]$Arguments) {
    & $VfiPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Verification failed: $($Arguments[0..1] -join ' ')" }
}
Invoke-VfiCheck @("-m", "ruff", "check", "src", "tests", "scripts")
Invoke-VfiCheck @("-m", "ruff", "format", "--check", "src", "tests", "scripts")
Invoke-VfiCheck @("-m", "mypy", "src")
Invoke-VfiCheck @("-m", "pytest", "-q", "-ra", "--junitxml=$VfiArtifacts/tests.xml")
Invoke-VfiCheck @("-m", "animecinemavfi", "diagnose", "--encoders", "--output", "$VfiArtifacts/diagnostics.json")
Write-Host "Automated checks completed. Follow docs/WINDOWS_VALIDATION.md for visible GUI/4K/long-video checks."
