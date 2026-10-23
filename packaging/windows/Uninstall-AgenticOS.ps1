[CmdletBinding()]
param(
    [string]$AppRoot = "$env:LOCALAPPDATA\Programs\AgenticOS",
    [switch]$RemoveState,
    [switch]$RemoveProjects
)
. "$PSScriptRoot\Package-Common.ps1"
try {
    $AppRoot = Assert-SafeRoot $AppRoot
    $current = Read-Json (Join-Path $AppRoot 'current.json')
    $state = Assert-SafeRoot $current.state_root
    $projects = Assert-SafeRoot $current.projects_root
    Stop-App $current
    if ($current.task_name) {
        if ($current.task_name -notmatch '^AgenticOS-PerUser-[A-F0-9]{16}$') { throw 'Invalid owned task name' }
        $task = Get-ScheduledTask -TaskName $current.task_name -ErrorAction SilentlyContinue
        if ($task) { Unregister-ScheduledTask -TaskName $current.task_name -Confirm:$false }
    }
    foreach ($version in @($current.app_root, $current.previous)) {
        if ($version -and (Test-Path -LiteralPath $version)) {
            $version = Assert-SafeRoot $version
            if ((Split-Path -Parent $version) -ine $AppRoot) { throw 'Invalid installed version path' }
            Set-AppAccess $version $true
            Remove-Item -Recurse -Force -LiteralPath $version
        }
    }
    Remove-Item -LiteralPath (Join-Path $AppRoot 'current.json')
    if ($RemoveState) { Remove-Item -Recurse -Force -LiteralPath $state }
    if ($RemoveProjects) { Remove-Item -Recurse -Force -LiteralPath $projects }
    Write-Output 'Uninstalled Agentic OS'
    exit 0
} catch {
    Write-Error -ErrorAction Continue (($_ | Out-String) + $_.ScriptStackTrace)
    exit 1
}
