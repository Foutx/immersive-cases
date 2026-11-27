Set-Location $PSScriptRoot
$python = Join-Path $PSScriptRoot ".venv\Scripts\python.exe"
if (-not (Test-Path -LiteralPath $python)) {
    throw "Python environment not found. See START_HERE.txt."
}
& $python -m services.collect_pilot @args
exit $LASTEXITCODE
