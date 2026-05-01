$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
$projectRoot = Resolve-Path (Join-Path $scriptDir '..')
$pythonExe = Join-Path $projectRoot '.venv\Scripts\python.exe'
$runner = Join-Path $scriptDir 'run_benchmark_suite.py'

if (Test-Path $pythonExe) {
    & $pythonExe $runner @args
} else {
    & python $runner @args
}

exit $LASTEXITCODE
