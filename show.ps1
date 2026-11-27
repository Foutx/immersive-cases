Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    Write-Host "First run: py -3 -m venv .venv"
    Write-Host "Then: .\.venv\Scripts\python.exe -m pip install -r immersive_pipeline/requirements.txt"
    exit 1
}
& $python -m services.showcase @args
exit $LASTEXITCODE
