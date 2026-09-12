param(
    [ValidateSet("cuda", "cpu", "skip")][string]$Backend = "cuda",
    [ValidateSet("cu126", "cu128", "cu130")][string]$CudaChannel = "cu128",
    [string]$PythonVersion = "3.11"
)
$ErrorActionPreference = "Stop"
Set-Location $PSScriptRoot
if (-not (Test-Path ".venv\Scripts\python.exe")) {
    & py "-$PythonVersion" -m venv .venv
    if ($LASTEXITCODE -ne 0) { throw "Install 64-bit Python $PythonVersion first." }
}
$VfiPython = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
function Invoke-VfiPython([string[]]$Arguments) {
    & $VfiPython @Arguments
    if ($LASTEXITCODE -ne 0) { throw "Python command failed: $Arguments" }
}
Invoke-VfiPython @("-m", "pip", "install", "--upgrade", "pip")
Invoke-VfiPython @("-m", "pip", "install", "-r", "requirements-core.txt", "-e", ".[dev]")
if ($Backend -ne "skip") {
    $VfiChannel = if ($Backend -eq "cpu") { "cpu" } else { $CudaChannel }
    Invoke-VfiPython @("-m", "pip", "install", "torch>=2.6,<3", "torchvision>=0.21,<1",
                      "--index-url", "https://download.pytorch.org/whl/$VfiChannel")
}
Write-Host "Core installed. Set up FFmpeg and the official RIFE model as described in README.md."
Write-Host "Launch with Launch.bat or .venv\Scripts\python.exe -m animecinemavfi"
