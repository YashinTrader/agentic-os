[CmdletBinding()]
param(
    [ValidateSet('start','stop','status')][string]$Action = 'start',
    [string]$AppRoot,
    [string]$PythonExecutable
)
if (-not $AppRoot) { $AppRoot = $PSScriptRoot }
. "$PSScriptRoot\Package-Common.ps1"
try {
    $AppRoot = Assert-SafeRoot $AppRoot
    $install = Read-Json (Join-Path $AppRoot 'install.json')
    $state = Assert-SafeRoot $install.state_root
    $env:AGENTIC_OS_STATE_ROOT = $state
    $env:AGENTIC_OS_CONFIG_ROOT = Join-Path $AppRoot 'code'
    $env:PYTHONDONTWRITEBYTECODE = '1'
    if (-not $PythonExecutable) { $PythonExecutable = Join-Path $AppRoot 'runtime/venv/Scripts/python.exe' }
    if ($Action -eq 'status') {
        $path = Join-Path $state 'runtime/dispatch/layer_supervisor/status.json'
        if (Test-Path -LiteralPath $path) { Get-Content -Raw -LiteralPath $path; exit 0 }
        Write-Output 'Supervisor has not started'; exit 0
    }
    if ($Action -eq 'stop') {
        & $PythonExecutable -B "$AppRoot\code\scripts\stop_supervisor.py" --state-root $state --actor installer-launcher --reason local-stop --timeout 15
        exit $LASTEXITCODE
    }
    $guard = Join-Path $state 'launcher_crashes.json'
    $lock = [IO.File]::Open((Join-Path $state 'launcher.lock'), 'OpenOrCreate', 'ReadWrite', 'None')
    try {
        $now = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
        $crashes = @()
        if (Test-Path -LiteralPath $guard) {
            $crashes = @((Read-Json $guard).crashes | Where-Object { $_ -gt ($now - 1800) })
        }
        if ($crashes.Count -ge 3) {
            Write-Output "Start refused: 3 supervisor failures within 30 minutes. Inspect $state\logs and layer status; fix the cause, then wait 30 minutes or archive $guard to reset."
            exit 78
        }
        & $PythonExecutable -B "$AppRoot\code\scripts\run_supervisor_layers.py" --state-root $state --config-root "$AppRoot\code"
        $code = $LASTEXITCODE
        if ($code -ne 0) {
            $crashes += [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
            Write-Json $guard @{crashes=@($crashes)}
        }
        exit $code
    } finally { $lock.Dispose() }
} catch {
    Write-Error -ErrorAction Continue (($_ | Out-String) + $_.ScriptStackTrace)
    exit 1
}
