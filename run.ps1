Set-Location $PSScriptRoot
$pipelinePython = Join-Path $PSScriptRoot '.venv/Scripts/python.exe'
if (-not (Test-Path -LiteralPath $pipelinePython)) {
    $pipelinePython = 'C:/Program Files/PostgreSQL/18/pgAdmin 4/python/python.exe'
}
if (-not (Test-Path -LiteralPath $pipelinePython)) {
    throw 'Python not found. Install Python and create .venv in the project folder.'
}
if ($args.Count -eq 0) {
    $pipelineArgs = @('status')
} else {
    $pipelineArgs = $args
}
& $pipelinePython -u -c "import sys,runpy; sys.path[:0]=['.test-deps','immersive_pipeline']; sys.argv=['main.py',*sys.argv[1:]]; runpy.run_path('immersive_pipeline/main.py',run_name='__main__')" @pipelineArgs
exit $LASTEXITCODE
